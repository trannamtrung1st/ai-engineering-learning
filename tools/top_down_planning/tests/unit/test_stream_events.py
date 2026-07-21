import json
from io import StringIO

from top_down_planning.stream_events import StreamEmitter


def test_stream_emitter_writes_valid_jsonl(monkeypatch) -> None:
    buffer = StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    emitter = StreamEmitter(enabled=True)
    emitter.emit("planning.started", input="./idea.md")
    emitter.emit("planning.completed", status="complete", items=3)
    lines = buffer.getvalue().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        payload = json.loads(line)
        assert "type" in payload
