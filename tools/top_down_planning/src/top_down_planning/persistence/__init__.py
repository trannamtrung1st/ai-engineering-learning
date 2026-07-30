"""Persistence adapter layer (proposal §17.5, §18)."""

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
)

from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_context_digest,
    compute_output_digest,
    compute_plan_digest,
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
    "compute_context_digest",
    "compute_output_digest",
    "compute_plan_digest",
    "new_run_record",
]
