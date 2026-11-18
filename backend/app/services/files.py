"""File storage.

Uploaded documents -- signed letter scans, custodian statements, valuer reports,
opening balance CSVs -- are stored under a content-addressed key and their SHA-256 is
recorded.  Nothing is ever overwritten, which is what makes the hash on an instruction
a meaningful record of the document that was actually signed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFound
from app.models import FileKind, StoredFile


def _root() -> Path:
    path = Path(get_settings().file_store_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def store(
    db: Session,
    *,
    kind: FileKind,
    filename: str,
    content: bytes,
    uploaded_by: str,
    content_type: str = "application/octet-stream",
) -> StoredFile:
    digest = hashlib.sha256(content).hexdigest()
    key = f"{digest[:2]}/{digest}"
    target = _root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)

    row = StoredFile(
        kind=kind,
        filename=filename,
        content_type=content_type,
        sha256=digest,
        size=len(content),
        storage_key=key,
        uploaded_by=uploaded_by,
        created_by=uploaded_by,
    )
    db.add(row)
    db.flush()
    return row


def read(db: Session, file_id: int) -> tuple[StoredFile, bytes]:
    row = db.get(StoredFile, file_id)
    if row is None:
        raise NotFound(f"unknown file {file_id}", file_id=file_id)
    target = _root() / row.storage_key
    if not target.exists():  # pragma: no cover - storage fault
        raise NotFound(f"file {file_id} is no longer in the store", file_id=file_id)
    return row, target.read_bytes()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
