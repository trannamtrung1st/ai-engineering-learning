"""Tests for the minimal YAML loader used by resolved config and agent requests."""

from __future__ import annotations

import pytest

from core_tools.persistence.yaml_util import load_yaml


def test_load_yaml_folded_scalar_in_mapping() -> None:
    parsed = load_yaml(
        """
agent_context:
  producer:
    guidance:
      - text: >
          Line one continues
          on the next line.
"""
    )
    entry = parsed["agent_context"]["producer"]["guidance"][0]
    assert entry["text"] == "Line one continues on the next line."


def test_load_yaml_literal_scalar_in_mapping() -> None:
    parsed = load_yaml(
        """
run:
  output_goal: |
    First line.
    Second line.
"""
    )
    assert parsed["run"]["output_goal"] == "First line.\nSecond line."


def test_load_yaml_list_item_mapping_with_folded_scalar() -> None:
    parsed = load_yaml(
        """
items:
  - text: >
      Folded guidance text
      with a blank line below.

      And another paragraph.
"""
    )
    assert "Folded guidance text with a blank line below." in parsed["items"][0]["text"]
    assert "And another paragraph." in parsed["items"][0]["text"]


def test_load_yaml_list_item_mapping_with_multiple_keys() -> None:
    parsed = load_yaml(
        """
items:
  - text: hello
    file: notes.md
"""
    )
    assert parsed["items"][0] == {"text": "hello", "file": "notes.md"}


def test_load_yaml_rejects_unexpected_indentation() -> None:
    with pytest.raises(ValueError, match="unexpected indentation"):
        load_yaml(
            """
top:
    bad: value
"""
        )
