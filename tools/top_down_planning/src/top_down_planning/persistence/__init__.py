"""Persistence adapter layer (proposal §17.5, §18)."""

from core_tools.persistence import (
    PersistenceError,
    RunNotFoundError,
    StoreRevisionConflictError,
    TransactionRecoveryError,
)

from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    contract_config_projection,
    digest_binding_payload,
    compute_output_digest,
    compute_plan_digest,
    execution_config_projection,
    semantic_config_projection,
)
from top_down_planning.persistence.commit import StoreAuthorizationConflictError, StagedArtifact
from top_down_planning.persistence.file_store import AGENT_REQUESTS_DIR, FileRunStore, new_run_record
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.run_schema import (
    CURRENT_RUN_SCHEMA_VERSION,
    UNSUPPORTED_RUN_SCHEMA_MESSAGE,
    UnsupportedRunSchemaVersionError,
    validate_run_digests,
    validate_run_schema_version,
)
from top_down_planning.domain.plan_schema import (
    PLAN_SCHEMA_VERSION,
    UNSUPPORTED_PLAN_SCHEMA_MESSAGE,
    UnsupportedPlanSchemaVersionError,
    validate_plan_schema_version,
)

__all__ = [
    "AGENT_REQUESTS_DIR",
    "FileRunStore",
    "PersistenceError",
    "RunNotFoundError",
    "RunStore",
    "StagedArtifact",
    "StoreRevisionConflictError",
    "TransactionRecoveryError",
    "CURRENT_RUN_SCHEMA_VERSION",
    "PLAN_SCHEMA_VERSION",
    "UNSUPPORTED_PLAN_SCHEMA_MESSAGE",
    "UNSUPPORTED_RUN_SCHEMA_MESSAGE",
    "UnsupportedPlanSchemaVersionError",
    "UnsupportedRunSchemaVersionError",
    "compute_config_contract_digest",
    "compute_config_execution_digest",
    "contract_config_projection",
    "digest_binding_payload",
    "compute_output_digest",
    "compute_plan_digest",
    "execution_config_projection",
    "semantic_config_projection",
    "new_run_record",
    "validate_plan_schema_version",
    "validate_run_digests",
    "validate_run_schema_version",
]
