import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// ── Custom Metrics ────────────────────────────────────────────────────────────
const ingestOK = new Counter('ingest_success_total');
const ingestErrors = new Counter('ingest_error_total');
const queryErrors = new Counter('query_error_total');
const errorRate = new Rate('error_rate');
const ingestLat = new Trend('ingest_latency');
const queryLat = new Trend('query_latency');

// ── Config ────────────────────────────────────────────────────────────────────
const BASE_URL = __ENV.API_URL || 'http://localhost:8000';
const API_KEY = __ENV.API_KEY || 'test-api-key-12345';
const HEADERS = { 'Content-Type': 'application/json', 'X-API-Key': API_KEY };

// ── Test Options ──────────────────────────────────────────────────────────────
export const options = {
    scenarios: {
        // Scenario 1: Ingest load — 50 concurrent virtual users
        ingest_load: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: 50 },   // ramp up
                { duration: '2m', target: 50 },   // steady state
                { duration: '30s', target: 0 },   // ramp down
            ],
            exec: 'ingestScenario',
            tags: { scenario: 'ingest' },
        },

        // Scenario 2: Query load — 200 concurrent virtual users
        query_load: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: 200 },
                { duration: '2m', target: 200 },
                { duration: '30s', target: 0 },
            ],
            exec: 'queryScenario',
            startTime: '1m',   // start after ingest builds some data
            tags: { scenario: 'query' },
        },

        // Scenario 3: Mixed realistic load — 100 VUs
        mixed_load: {
            executor: 'constant-vus',
            vus: 100,
            duration: '3m',
            exec: 'mixedScenario',
            startTime: '4m',
            tags: { scenario: 'mixed' },
        },
    },

    thresholds: {
        // p95 ingest latency < 500ms
        ingest_latency: ['p(95)<500'],
        // p95 query latency < 250ms
        query_latency: ['p(95)<250'],
        // Overall error rate < 1%
        error_rate: ['rate<0.01'],
        // HTTP failures < 1%
        http_req_failed: ['rate<0.01'],
    },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function randomAppNumber() {
    return 'APP-LOAD-' + Math.random().toString(36).substring(2, 9).toUpperCase();
}

function randomScore() {
    return Math.floor(Math.random() * 600) + 300;  // 300–900
}

const EMPLOYMENT_TYPES = ['Salaried', 'SelfEmployed', 'Unemployed', 'Student', 'Other'];
const PRODUCT_TYPES = ['PersonalLoan', 'HomeLoan', 'CarLoan', 'CreditCard', 'BusinessLoan'];

function randomPayload() {
    return JSON.stringify({
        application_number: randomAppNumber(),
        request_id: `REQ-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        transunion_score: randomScore(),
        loan_amount: Math.round(Math.random() * 900000 + 10000),
        tenure_months: [12, 24, 36, 48, 60, 84][Math.floor(Math.random() * 6)],
        interest_rate_apr: parseFloat((Math.random() * 20 + 5).toFixed(2)),
        employment_type: EMPLOYMENT_TYPES[Math.floor(Math.random() * EMPLOYMENT_TYPES.length)],
        product_type: PRODUCT_TYPES[Math.floor(Math.random() * PRODUCT_TYPES.length)],
        customer_city: 'LoadTestCity',
        income_monthly: Math.round(Math.random() * 20000 + 3000),
        existing_debt: Math.round(Math.random() * 50000),
    });
}

const appNumbers = ['APP001', 'APP002', 'APP003', 'APP-SEED-001', 'APP-SEED-002'];

// ── Scenarios ─────────────────────────────────────────────────────────────────
export function ingestScenario() {
    const start = Date.now();
    const r = http.post(`${BASE_URL}/transactions`, randomPayload(), { headers: HEADERS });
    ingestLat.add(Date.now() - start);

    const ok = check(r, {
        'ingest: status 202': (res) => res.status === 202,
        'ingest: has composite_key': (res) => JSON.parse(res.body || '{}').composite_key !== undefined,
    });

    if (r.status === 202) {
        ingestOK.add(1);
        errorRate.add(false);
    } else if (r.status !== 409) {   // 409 = expected for dedup, not an error
        ingestErrors.add(1);
        errorRate.add(true);
    } else {
        errorRate.add(false);
    }
    sleep(Math.random() * 0.5 + 0.1);
}

export function queryScenario() {
    const appNum = appNumbers[Math.floor(Math.random() * appNumbers.length)];
    const start = Date.now();
    const r = http.get(`${BASE_URL}/transactions?application_number=${appNum}&pageSize=20`, { headers: HEADERS });
    queryLat.add(Date.now() - start);

    const ok = check(r, {
        'query: status 200': (res) => res.status === 200,
        'query: has data': (res) => Array.isArray(JSON.parse(res.body || '{}').data),
    });

    if (!ok) {
        queryErrors.add(1);
        errorRate.add(true);
    } else {
        errorRate.add(false);
    }
    sleep(Math.random() * 0.3 + 0.05);
}

export function mixedScenario() {
    // 70% reads, 30% writes
    if (Math.random() < 0.7) {
        queryScenario();
    } else {
        ingestScenario();
    }
}
