"""Persistence adapter layer (proposal §17.5, §18)."""

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
)

from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_digest,
    compute_config_execution_digest,
    contract_config_projection,
    digest_binding_payload,
    compute_output_digest,
    compute_plan_digest,
    execution_config_projection,
    semantic_config_projection,
)
from top_down_planning.persistence.file_store import FileRunStore, new_run_record
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.run_schema import (
    CURRENT_RUN_SCHEMA_VERSION,
    UNSUPPORTED_RUN_SCHEMA_MESSAGE,
    UnsupportedRunSchemaVersionError,
    validate_run_digests,
    validate_run_schema_version,
)

__all__ = [
    "FileRunStore",
    "PersistenceError",
    "RunNotFoundError",
    "RunStore",
    "StoreRevisionConflictError",
    "CURRENT_RUN_SCHEMA_VERSION",
    "UNSUPPORTED_RUN_SCHEMA_MESSAGE",
    "UnsupportedRunSchemaVersionError",
    "compute_config_contract_digest",
    "compute_config_digest",
    "compute_config_execution_digest",
    "contract_config_projection",
    "digest_binding_payload",
    "compute_output_digest",
    "compute_plan_digest",
    "execution_config_projection",
    "semantic_config_projection",
    "new_run_record",
    "validate_run_digests",
    "validate_run_schema_version",
]
