"""Producer session manifest helpers."""

from __future__ import annotations

PRODUCER_BATCH_COMPLETE_SIGNAL = "batch_complete"


def build_producer_protocol_instructions() -> list[str]:
    """Provider-agnostic producer behavior instructions for session manifests."""

    return [
        (
            "You are the TDP producer. Record batches, evidence, and "
            "dispositions through tdp agent production commands in "
            "tool_instructions."
        ),
        (
            "Do not use host planning modes or planning-only tools. Production "
            "state advances only through persisted tdp agent commands."
        ),
        (
            "Emit batch_complete_signal after each recorded batch when more "
            "work remains. Submit completion with goal_met and "
            "goal_assessment when the output goal is met."
        ),
        (
            "Discover request contracts with tdp agent readme, tdp agent "
            "schema, and tdp agent example."
        ),
    ]


def build_producer_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in producer session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token exported "
            "as TDP_CAPABILITY_TOKEN."
        ),
        "snapshot": f"tdp agent production snapshot --run {run_id} --view ready",
        "apply": f"tdp agent production apply --run {run_id} --request <file>",
        "check": f"tdp agent production check --run {run_id}",
        "request_amendment": (
            f"tdp agent production request-amendment --run {run_id} --request <file>"
        ),
        "submit_completion": (
            f"tdp agent production submit-completion --run {run_id} "
            "--request <file>  # requires goal_met: true and goal_assessment"
        ),
        "report_blocked": (
            f"tdp agent production report-blocked --run {run_id} --request <file>"
        ),
        "request_review": f"tdp agent review request --run {run_id} --request <file>",
        "batch_complete_signal": PRODUCER_BATCH_COMPLETE_SIGNAL,
    }


__all__ = [
    "PRODUCER_BATCH_COMPLETE_SIGNAL",
    "build_producer_protocol_instructions",
    "build_producer_tool_instructions",
]
