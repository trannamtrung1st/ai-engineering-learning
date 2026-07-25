from pathlib import Path

from top_down_planning.models import (
    AgentResponse,
    MarkActionableOperation,
)
from top_down_planning.response_parser import (
    load_planning_response,
    parse_agent_response,
)
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan
from top_down_planning.renderer import render_plan_markdown


def test_parse_fenced_json_legacy() -> None:
    payload = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                expected_outputs=["x"],
                acceptance_criteria=["y"],
            )
        ]
    )
    text = "```json\n" + payload.model_dump_json(indent=2) + "\n```"
    parsed = parse_agent_response(text)
    assert parsed.operations[0].node_id == "item-001"


def test_load_planning_response_from_transaction_file(tmp_path: Path) -> None:
    payload = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                expected_outputs=["x"],
                acceptance_criteria=["y"],
            )
        ]
    )
    path = tmp_path / "001-transaction.json"
    path.write_text(payload.model_dump_json(), encoding="utf-8")
    loaded = load_planning_response(path)
    assert loaded.operations[0].node_id == "item-001"


def test_render_markdown_contains_views() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )
    md = render_plan_markdown(plan)
    assert "## Hierarchical view" in md
    assert "## Actionable items" in md
    assert "item-001" in md
