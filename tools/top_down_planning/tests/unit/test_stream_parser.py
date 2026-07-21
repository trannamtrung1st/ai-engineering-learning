from top_down_planning.stream_parser import NdjsonStreamParser


def test_stream_parser_handles_split_lines() -> None:
    parser = NdjsonStreamParser()
    payload = b'{"type":"assistant","text":"hi"}\n'
    first = parser.feed(payload[:10])
    second = parser.feed(payload[10:])
    finish = parser.finish()
    events = first + second + finish
    assert any(event.get("type") == "assistant" for event in events)


def test_malformed_lines_increment_errors() -> None:
    parser = NdjsonStreamParser(parse_error_threshold=5)
    parser.feed(b"@@@\n")
    assert parser.parse_errors == 1
