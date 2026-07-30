"""Persistence adapter layer (proposal §17.5, §18)."""

from top_down_planning.persistence.atomic import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_context_digest,
    compute_plan_digest,
    digest_bytes,
    digest_file,
    digest_text,
)
from top_down_planning.persistence.errors import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
)
from top_down_planning.persistence.file_store import FileRunStore, new_run_record
from top_down_planning.persistence.interface import RunStore

__all__ = [
    "FileRunStore",
    "PersistenceError",
    "RunNotFoundError",
    "RunStore",
    "StoreRevisionConflictError",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "compute_config_digest",
    "compute_context_digest",
    "compute_plan_digest",
    "digest_bytes",
    "digest_file",
    "digest_text",
    "new_run_record",
]
