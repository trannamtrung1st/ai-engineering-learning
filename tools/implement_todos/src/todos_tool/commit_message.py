"""Generate and validate developer-style commit subjects."""

from __future__ import annotations

import re

from todos_tool.errors import GitError
from todos_tool.models import ItemType, TodoItem

TYPE_PREFIX = {
    ItemType.FEATURE: "feat",
    ItemType.FIX: "fix",
    ItemType.REFACTOR: "refactor",
}

BANNED_WORDS = re.compile(
    r"\b(ai|agent|cursor|todo|backlog|review|attempt|retry|"
    r"generation|automation|orchestrat)\b",
    re.IGNORECASE,
)

ITEM_ID_RE = re.compile(r"\bTASK-\d+\b", re.IGNORECASE)


def prefix_for(item_type: ItemType) -> str:
    return TYPE_PREFIX[item_type]


def _slug_from_diff(diff_stat: str) -> str | None:
    """Derive a short subject hint from staged diff --stat output."""
    lines = [ln.strip() for ln in diff_stat.splitlines() if ln.strip()]
    # Prefer first file path line like "path/to/file.py | 10 +++"
    for line in lines:
        if "|" in line:
            path = line.split("|", 1)[0].strip()
            name = path.rsplit("/", 1)[-1]
            name = re.sub(r"\.[^.]+$", "", name)
            name = name.replace("_", " ").replace("-", " ")
            if name:
                return name.lower()
    return None


def _slug_from_criteria(item: TodoItem) -> str | None:
    if not item.acceptance_criteria:
        return None
    text = item.acceptance_criteria[0].strip()
    text = re.sub(r"[.!?]+$", "", text)
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    if not words:
        return None
    return " ".join(words[:8])


def _slug_from_title(item: TodoItem) -> str:
    text = re.sub(r"[.!?]+$", "", item.title.strip())
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return " ".join(words[:10]) or "update"


def generate_commit_message(item: TodoItem, staged_diff_stat: str) -> str:
    """Build ``prefix: subject`` from diff, then AC, then title."""
    prefix = prefix_for(item.type)
    subject = (
        _slug_from_diff(staged_diff_stat)
        or _slug_from_criteria(item)
        or _slug_from_title(item)
    )
    # Prefer title when it is already imperative and short
    title_subject = re.sub(r"[.!?]+$", "", item.title.strip())
    if 3 <= len(title_subject) <= 60 and not BANNED_WORDS.search(title_subject):
        # Use title if diff slug is just a filename-ish token
        if subject and " " not in subject and len(title_subject.split()) >= 2:
            subject = title_subject[0].lower() + title_subject[1:]
        elif " " in title_subject:
            subject = title_subject[0].lower() + title_subject[1:]

    message = f"{prefix}: {subject}"
    message = re.sub(r"\s+", " ", message).strip()
    if message.endswith((".", "!", "?")):
        message = message[:-1]
    if len(message) > 72:
        message = message[:72].rstrip()
    validate_commit_message(message, item)
    return message


def validate_commit_message(message: str, item: TodoItem | None = None) -> None:
    if not message:
        raise GitError("Empty commit message")
    if len(message) > 72:
        raise GitError(f"Commit message exceeds 72 chars: {message!r}")
    if message.endswith((".", "!", "?")):
        raise GitError("Commit message must not end with punctuation")
    prefix = message.split(":", 1)[0]
    if prefix not in TYPE_PREFIX.values():
        raise GitError(f"Commit message must start with feat/fix/refactor: {message!r}")
    if BANNED_WORDS.search(message) or ITEM_ID_RE.search(message):
        raise GitError(f"Commit message contains banned terms: {message!r}")
    if item is not None and item.id.lower() in message.lower():
        raise GitError(f"Commit message must not mention item id: {message!r}")
