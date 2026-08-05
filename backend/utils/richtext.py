"""Rich-text (TipTap/ProseMirror) helpers shared across domains.

Descriptions, rules and other authored prose are stored as TipTap JSON docs.
``doc_to_text`` flattens one to plain text — used by the challenge YAML export and
by the competitor assistant's tools, which hand challenge descriptions to the
model as text rather than as a nested JSON tree.
"""

from __future__ import annotations


def doc_to_text(doc: object) -> str:
    """Flatten a TipTap/ProseMirror doc to plain text (paragraph-joined)."""
    if not isinstance(doc, dict):
        return ""
    lines: list[str] = []

    def walk(node: dict, buf: list[str]) -> None:
        if node.get("type") == "text":
            buf.append(node.get("text", ""))
        for child in node.get("content", []) or []:
            walk(child, buf)

    for block in doc.get("content", []) or []:
        buf: list[str] = []
        walk(block, buf)
        lines.append("".join(buf))
    return "\n".join(lines).strip()
