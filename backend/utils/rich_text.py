"""Shared handling for stored ProseMirror documents (#197, #198, ADR-0034).

Two surfaces now persist admin-authored rich text — the sign-in notice
(`SiteSettings.login_notice`) and custom pages (`Page.content`) — and both feed
the *same* read-only renderer on the frontend. Keeping one validator means they
cannot drift on what counts as a valid document, which matters because the
frontend's `RichTextView` renders `null` for anything it considers malformed:
a shape the backend accepted but the renderer rejects is a silently blank page.

**The server never interprets the document.** It checks the outer shape and a
size cap, and stores the JSON verbatim. Safety comes from the rendering path,
not from sanitising here: page content becomes a React tree under the editor's
own schema, so unknown nodes and marks are dropped rather than executed
(ADR-0034). Validating deeply would imply a security property this layer does
not provide.
"""

from __future__ import annotations

import json


def doc_text(node: object) -> str:
    """Flatten a ProseMirror node to its text.

    The Python analogue of the frontend's ``richTextToPlain``, used to detect
    visually-empty documents (a doc of empty paragraphs is "no content" to a
    reader, whatever its JSON says) and to derive plain-text previews.
    """
    if not isinstance(node, dict):
        return ""
    parts: list[str] = []
    text = node.get("text")
    if isinstance(text, str):
        parts.append(text)
    content = node.get("content")
    if isinstance(content, list):
        parts.extend(doc_text(child) for child in content)
    return "".join(parts)


def is_doc_shaped(value: object) -> bool:
    """Does this look like a ProseMirror document the renderer will accept?

    Mirrors the guard in ``RichTextView`` exactly (``type == "doc"`` and a list
    ``content``) so the two agree on what is renderable.
    """
    return (
        isinstance(value, dict)
        and value.get("type") == "doc"
        and isinstance(value.get("content"), list)
    )


def validate_rich_text_doc(
    value: dict | None,
    *,
    max_bytes: int,
    field_label: str,
    too_large_hint: str = "",
) -> dict | None:
    """Validate a stored rich-text document, returning it normalized.

    Raises ``ValueError`` (so a pydantic ``field_validator`` surfaces it as a
    422) when the payload isn't doc-shaped or exceeds ``max_bytes``. A document
    with no visible text normalizes to ``None``, so "empty means unset" holds
    for every client rather than only for the admin form that happens to do the
    same normalization locally.

    ``too_large_hint`` is appended to the size error: each caller caps for its
    own reason, and telling the author *why* is the difference between a usable
    message and a wall.
    """
    if value is None:
        return None
    if not is_doc_shaped(value):
        raise ValueError(
            f"{field_label} must be a rich-text document "
            '({"type": "doc", "content": [...]})'
        )
    # Measured as compact JSON so the limit reflects stored bytes rather than
    # however the client happened to indent its payload.
    if len(json.dumps(value, separators=(",", ":"))) > max_bytes:
        raise ValueError(f"{field_label} is too large{too_large_hint}")
    if not doc_text(value).strip():
        return None
    return value
