"""Content-addressed, integrity-checked local storage for run artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Stable metadata for an immutable artifact."""

    sha256: str
    size_bytes: int
    path: str


class FileArtifactStore:
    """Store immutable artifacts by SHA-256 beneath a caller-owned directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(payload: bytes) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("artifact payload must be bytes")
        return hashlib.sha256(payload).hexdigest()

    def put(self, payload: bytes) -> StoredArtifact:
        """Persist bytes once; repeated writes of identical content are idempotent."""
        digest = self._digest(payload)
        directory = self.root / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise OSError("artifact directory must not be a symbolic link")
        target = directory / digest[2:]
        if target.exists():
            if target.is_symlink() or target.read_bytes() != payload:
                raise OSError("existing content-addressed artifact failed integrity check")
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary_name, target)
                except FileExistsError as exc:
                    if target.is_symlink() or target.read_bytes() != payload:
                        raise OSError("concurrent artifact write failed integrity check") from exc
            finally:
                Path(temporary_name).unlink(missing_ok=True)
        return StoredArtifact(digest, len(payload), str(target.relative_to(self.root)))

    def get(self, sha256: str) -> bytes:
        """Read an artifact only when its content matches the requested digest."""
        if (
            len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")
        directory = self.root / sha256[:2]
        if directory.is_symlink():
            raise OSError("artifact directory must not be a symbolic link")
        path = directory / sha256[2:]
        if path.is_symlink():
            raise OSError("artifact path must not be a symbolic link")
        payload = path.read_bytes()
        if self._digest(payload) != sha256:
            raise OSError("artifact integrity verification failed")
        return payload
