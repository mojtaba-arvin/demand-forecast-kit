# Run registry

`SQLiteRunRegistry` records immutable execution identity (idempotency key, dataset fingerprint, model ID/version, configuration), completion/failure outcomes, and inventory decisions linked to a run. Repeating a run or decision write with the same key and identical payload is idempotent; reusing a key with different identity or decision data is rejected.

Forecast/evaluation payloads that are too large for JSON metadata should be written through `FileArtifactStore` and referenced by SHA-256 digest in the run result. Keep artifact storage and the SQLite database on durable, backed-up storage when used operationally. The registry is a local persistence primitive, not a distributed transaction coordinator or multi-host database.
