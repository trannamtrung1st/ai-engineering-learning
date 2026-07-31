"""Persistence adapter layer (proposal §17.5, §18)."""

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
)

from top_down_planning.persistence.digests import (
    compute_config_digest,
    digest_binding_payload,
    compute_output_digest,
    compute_plan_digest,
    semantic_config_projection,
)
from top_down_planning.persistence.file_store import FileRunStore, new_run_record
from top_down_planning.persistence.interface import RunStore

__all__ = [
    "FileRunStore",
    "PersistenceError",
    "RunNotFoundError",
    "RunStore",
    "StoreRevisionConflictError",
    "compute_config_digest",
    "digest_binding_payload",
    "compute_output_digest",
    "compute_plan_digest",
    "semantic_config_projection",
    "new_run_record",
]
