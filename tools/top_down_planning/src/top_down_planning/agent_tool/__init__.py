"""Structured agent tool service (proposal §17.3).

Exposes atomic domain operations to agents with revision checks and concise
response shaping.
"""

from top_down_planning.agent_tool.errors import (
    AgentToolError,
    CapabilityDeniedError,
    OperationError,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.agent_tool.production_service import ProductionAgentService
from top_down_planning.agent_tool.request import load_structured_request
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.agent_tool.run_service import RunAgentService

__all__ = [
    "AgentToolError",
    "CapabilityDeniedError",
    "OperationError",
    "PlanAgentService",
    "ProductionAgentService",
    "RequestError",
    "ReviewAgentService",
    "RevisionConflictError",
    "RunAgentService",
    "load_structured_request",
]
