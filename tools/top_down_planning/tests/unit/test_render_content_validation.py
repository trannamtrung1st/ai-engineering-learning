from top_down_planning.models import OutputMode, RenderManifestItem
from top_down_planning.render_content_validation import validate_artifact_content


def _item(*, set_order: int = 1) -> RenderManifestItem:
    return RenderManifestItem(
        plan_item_id="item-002",
        top_level_branch_id="item-001",
        order=2,
        set_order=set_order,
        title="Example",
        assigned_batch_id="render-batch-001",
        artifact_key="todo-item-002",
        relative_path="items/002-example.yaml",
        publish_relative_path=f"{set_order:02d}-example.yaml",
    )


def test_validate_artifact_content_accepts_matching_order() -> None:
    content = "id: example\ntitle: Example\norder: '01'\n"
    errors = validate_artifact_content(
        content,
        _item(set_order=1),
        output_mode=OutputMode.MULTI_FILE,
    )
    assert errors == []


def test_validate_artifact_content_rejects_order_mismatch() -> None:
    content = "id: example\ntitle: Example\norder: '11'\n"
    errors = validate_artifact_content(
        content,
        _item(set_order=10),
        output_mode=OutputMode.MULTI_FILE,
    )
    assert any("order mismatch" in error for error in errors)


def test_validate_artifact_content_rejects_missing_title() -> None:
    content = "id: example\norder: '01'\n"
    errors = validate_artifact_content(
        content,
        _item(set_order=1),
        output_mode=OutputMode.MULTI_FILE,
    )
    assert any("title" in error for error in errors)


def test_validate_artifact_content_skips_single_document_mode() -> None:
    content = "plain markdown"
    errors = validate_artifact_content(
        content,
        _item(),
        output_mode=OutputMode.SINGLE_DOCUMENT,
    )
    assert errors == []
