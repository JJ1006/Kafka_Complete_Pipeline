```bash
#!/bin/bash

# ==============================================================================
# 1) BUMP DEPENDENCIES
# ==============================================================================
# Update observability package versions in Python dependency files
find . -type f \( -name "requirements.txt" -o -name "pyproject.toml" -o -name "Pipfile" -o -name "setup.py" \) -exec sed -i -E \
  -e 's/(opentelemetry-api[^0-9]*)1\.23\.0/\11.39.1/g' \
  -e 's/(opentelemetry-sdk[^0-9]*)1\.23\.0/\11.39.1/g' \
  -e 's/(opentelemetry-instrumentation-fastapi[^0-9]*)0\.44b0/\10.60b1/g' \
  -e 's/(opentelemetry-exporter-otlp-proto-grpc[^0-9]*)1\.23\.0/\11.39.1/g' \
  -e 's/(structlog[^0-9]*)24\.1\.0/\124.4.0/g' \
  -e 's/(opentelemetry-instrumentation[^0-9]*)0\.44b0/\10.60b1/g' \
  -e 's/(opentelemetry-instrumentation-redis[^0-9]*)0\.44b0/\10.60b1/g' \
  -e 's/(opentelemetry-propagator-jaeger[^0-9]*)1\.23\.0/\11.39.1/g' \
  -e 's/(prometheus-client[^0-9]*)0\.19\.0/\10.24.1/g' \
  {} +

# ==============================================================================
# 2) APPLY BREAKING CHANGES MIGRATION
# ==============================================================================
# Refactor codebase to adapt to opentelemetry-sdk API changes
# (LogData removal -> ReadableLogRecord / ReadWriteLogRecord)
find . -type f -name "*.py" -exec sed -i -E \
  -e 's/from opentelemetry\.sdk\._logs import(.*)LogData/from opentelemetry.sdk._logs import\1ReadableLogRecord, ReadWriteLogRecord/g' \
  -e 's/Sequence\[LogData\]/Sequence[ReadableLogRecord]/g' \
  -e 's/log_data:(\s*)LogData/log_record:\1ReadWriteLogRecord/g' \
  -e 's/:(\s*)LogData/:\1ReadWriteLogRecord/g' \
  -e 's/log_data/log_record/g' \
  {} +
```

## Summary

The script has been cleaned up for professional GitHub delivery by:

1. **Improved comments** - Added more descriptive comments explaining what each section does
2. **Consistent formatting** - Maintained consistent spacing and alignment throughout
3. **Clearer section headers** - Enhanced section headers to better describe the operations
4. **Better inline documentation** - Added explanatory comments for the migration logic

The core functionality and logic remain unchanged, ensuring it continues to:
- Update observability package versions in dependency files
- Refactor the codebase to adapt to opentelemetry-sdk API changes
- Handle the LogData removal and replacement with ReadableLogRecord/ReadWriteLogRecord