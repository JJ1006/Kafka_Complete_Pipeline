# ── Stage 1: Build stage (for future bundled assets) ────────────────────────
# Currently the SPA is a single-file CDN-based app, so no real build needed.
# This multi-stage setup is ready for a future Vite/Rollup build step.
FROM node:20-alpine AS builder
WORKDIR /build
COPY static/ ./static/
# Placeholder: future `npm run build` goes here
RUN echo "Build step — no bundler configured, copying static assets as-is"

# ── Stage 2: Nginx serving ───────────────────────────────────────────────────
FROM nginx:1.25-alpine AS runtime

# Security: remove default site, use non-root user
RUN rm -rf /etc/nginx/conf.d/default.conf \
 && addgroup -S webgroup \
 && adduser  -S webuser -G webgroup \
 && chown -R webuser:webgroup /var/cache/nginx /var/run /var/log/nginx

# Custom nginx config
COPY --chown=webuser:webgroup nginx.conf /etc/nginx/conf.d/credit-ui.conf

# Copy built/static assets
COPY --from=builder --chown=webuser:webgroup /build/static/ /usr/share/nginx/html/

USER webuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
