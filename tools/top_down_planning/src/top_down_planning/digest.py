"""SHA-256 digests for resume compatibility checks and plan snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from top_down_planning.models import PlanState, RenderConfig


def digest_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    data = path.read_bytes()
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def compute_plan_digest(plan: PlanState) -> str:
    """Deterministic digest of canonical plan content for review invalidation."""
    source = plan.source
    payload = {
        "source": {
            "input_digest": source.input_digest,
            "output_goal_digest": source.output_goal_digest,
            "stop_hint_digest": source.stop_hint_digest,
        },
        "plan": [
            {
                "id": item.id,
                "parent_id": item.parent_id,
                "title": item.title,
                "objective": item.objective,
                "depth": item.depth,
                "order": item.order,
                "decomposition_status": item.decomposition_status.value,
                "readiness_status": item.readiness_status.value,
                "dependencies": list(item.dependencies),
                "expected_outputs": list(item.expected_outputs),
                "acceptance_criteria": list(item.acceptance_criteria),
                "notes": list(item.notes),
                "risks": list(item.risks),
                "open_questions": list(item.open_questions),
                "blocked_reason": item.blocked_reason,
                "blocked_constraint_code": (
                    item.blocked_constraint_code.value
                    if item.blocked_constraint_code is not None
                    else None
                ),
                "blocked_required_min_children": item.blocked_required_min_children,
                "out_of_scope_reason": item.out_of_scope_reason,
            }
            for item in sorted(plan.plan, key=lambda entry: (entry.order, entry.id))
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)


def compute_render_config_digest(render_config: RenderConfig) -> str:
    payload = render_config.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)
