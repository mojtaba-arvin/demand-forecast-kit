FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEMAND_FORECAST_STATE_DIR=/var/lib/demand-forecast-kit

WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir ".[api]" \
    && useradd --system --uid 10001 --create-home app \
    && mkdir -p /var/lib/demand-forecast-kit \
    && chown -R app:app /app /var/lib/demand-forecast-kit

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "demand_forecast_kit.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
