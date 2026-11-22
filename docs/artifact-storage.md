# Run artifact storage

The run registry stores small JSON metadata. Forecast arrays, evaluation payloads,
and other larger outputs can be stored separately with `FileArtifactStore`.

Artifacts are immutable and addressed by their SHA-256 digest. Store the returned
digest and relative path in a run result; retrieve with `get(digest)`, which
recomputes the digest before returning bytes. Repeated writes of identical
content are idempotent. The store is local filesystem persistence, not a remote
object store or a substitute for backups and access controls.

```python
from demand_forecast_kit.artifacts import FileArtifactStore

store = FileArtifactStore("./artifacts")
artifact = store.put(b'{"forecast": [1, 2, 3]}')
payload = store.get(artifact.sha256)
```
