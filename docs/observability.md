# Logging and process-local metrics

The optional `demand_forecast_kit.observability` module provides standard-library
building blocks for applications embedding the library:

- `JsonLogFormatter` emits structured one-line JSON and includes only extra
  fields that are JSON serializable.
- `InMemoryMetrics` provides thread-safe counters and count/sum/min/max
  observations without label cardinality or external service dependencies.

These metrics are process-local and reset on restart. They are not a Prometheus
exporter, durable telemetry store, or distributed aggregation system. Applications
should expose snapshots through their own authenticated monitoring endpoint and
avoid putting SKU/customer identifiers in metric names.
