"""Guard against inline protocol prose returning to orchestrator session modules."""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"

_PROTOCOL_BUILDER_FILES = (
    Path("orchestrator/planner_session.py"),
    Path("orchestrator/producer_session.py"),
    Path("orchestrator/reviewer_session.py"),
)

_STAGE_GUIDANCE_DUPLICATE_PATTERNS = (
    "Mandatory whole-plan gate",
    "Mandatory whole-output gate",
    "Report every material issue with severity and category",
    "Complete audit_attestation and a discovery_sweep",
    "Verify disposition of prior findings and direct revision side effects",
)

_INLINE_PROTOCOL_PATTERNS = (
    "instructions.append(",
    "PLAN_ROOT_PLANNER_INSTRUCTION",
    "PLAN_ROOT_REVIEWER_INSTRUCTION",
    "You are the TDP planner",
    "You are the TDP producer",
    "You are the TDP reviewer",
)


def test_protocol_builders_delegate_to_render_prompt() -> None:
    violations: list[str] = []
    for rel in _PROTOCOL_BUILDER_FILES:
        text = (_SRC_ROOT / rel).read_text(encoding="utf-8")
        if "def build_" not in text or "protocol_instructions" not in text:
            violations.append(f"{rel}: missing protocol builder")
            continue
        if "render_prompt(" not in text:
            violations.append(f"{rel}: missing render_prompt delegation")
        for pattern in _INLINE_PROTOCOL_PATTERNS:
            if pattern in text:
                violations.append(f"{rel}: {pattern}")
    assert not violations, "inline protocol remnants:\n" + "\n".join(violations)


def test_mandatory_stage_guidance_defers_to_protocol_instructions() -> None:
    stage_path = _SRC_ROOT / "orchestrator/mandatory_review_stages.py"
    text = stage_path.read_text(encoding="utf-8")
    violations = [
        pattern
        for pattern in _STAGE_GUIDANCE_DUPLICATE_PATTERNS
        if pattern in text
    ]
    assert not violations, "duplicate stage guidance prose:\n" + "\n".join(violations)
