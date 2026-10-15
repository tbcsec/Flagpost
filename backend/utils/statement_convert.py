"""Problem statements between Markdown / LaTeX and Flagpost's rich text (#451).

A problem package's statement is Markdown or LaTeX (or a PDF); a Flagpost
challenge description is TipTap/ProseMirror JSON over StarterKit — paragraphs,
headings, lists, quotes, code, rules, hard breaks; bold, italic, strike, code
and link marks — and nothing else (no maths, images or tables). So conversion
is **best effort**, by owner decision, with the original kept as an attachment:

- maths (``$..$``, ``$$..$$``, ``\\(..\\)``, ``\\[..\\]``, equation-like
  environments) is kept **verbatim as text** — readable, never rendered;
- an image becomes a ``[image: name]`` placeholder (the importer attaches the
  file); a table becomes one ``a | b | c`` paragraph per row;
- raw HTML is never interpreted — it stays literal text.

No new dependency (the stack is fixed): two small hand-written parsers for the
subset statements actually use, and ``doc_to_markdown`` for export. Every
function here accepts anything and never raises; the worst case is the raw
text as paragraphs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# --- building the document ----------------------------------------------------------

_MARK_ORDER = ("link", "bold", "italic", "underline", "strike", "code")


def _txt(text: str, marks: list[dict] | None = None) -> dict | None:
    if not text:
        return None  # ProseMirror forbids empty text nodes
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        # The code mark excludes every other mark (StarterKit).
        if any(m["type"] == "code" for m in marks):
            marks = [{"type": "code"}]
        seen, unique = set(), []
        for m in sorted(marks, key=lambda m: _MARK_ORDER.index(m["type"])):
            if m["type"] not in seen:
                seen.add(m["type"])
                unique.append(m)
        node["marks"] = unique
    return node


def _inline(nodes: list[dict | None]) -> list[dict]:
    """Drop empties and merge adjacent text nodes with the same marks."""
    out: list[dict] = []
    for node in nodes:
        if not node:
            continue
        if (
            out
            and node.get("type") == "text"
            and out[-1].get("type") == "text"
            and out[-1].get("marks") == node.get("marks")
        ):
            out[-1] = {**out[-1], "text": out[-1]["text"] + node["text"]}
        else:
            out.append(node)
    return out


def _block(kind: str, content: list[dict] | None = None, **attrs: Any) -> dict:
    node: dict[str, Any] = {"type": kind}
    if attrs:
        node["attrs"] = attrs
    if content:
        node["content"] = content
    return node


def _para(inline: list[dict]) -> dict:
    # Leading/trailing hard breaks look like stray blank lines; drop them.
    while inline and inline[0].get("type") == "hardBreak":
        inline = inline[1:]
    while inline and inline[-1].get("type") == "hardBreak":
        inline = inline[:-1]
    return _block("paragraph", inline or None)


def _doc(blocks: list[dict]) -> dict:
    return {"type": "doc", "content": blocks or [{"type": "paragraph"}]}


def _plain_doc(text: str) -> dict:
    """The fallback: the raw text, a paragraph per blank-line-separated chunk."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", str(text or "")):
        lines = [ln for ln in chunk.split("\n")]
        inline: list[dict | None] = []
        for i, line in enumerate(lines):
            if i:
                inline.append({"type": "hardBreak"})
            inline.append(_txt(line))
        para = _para(_inline(inline))
        if para.get("content"):
            blocks.append(para)
    return _doc(blocks)


def _safe_href(url: str) -> str | None:
    url = url.strip()
    return url if re.match(r"^(https?://|mailto:)", url, re.IGNORECASE) else None


def _link_nodes(text_nodes: list[dict], url: str) -> list[dict]:
    href = _safe_href(url)
    if href is None:
        # Not a web link: keep the text and show where it pointed.
        return _inline([*text_nodes, _txt(f" ({url})")]) if url else text_nodes
    out = []
    for n in text_nodes:
        if n.get("type") == "text":
            marks = [m for m in n.get("marks", []) if m["type"] != "link"]
            out.append(_txt(n["text"], [*marks, {"type": "link", "attrs": {"href": href}}]))
        else:
            out.append(n)
    return _inline(out)


# --- Markdown → doc: inline -----------------------------------------------------------

# Earliest-match tokens; maths and code spans are opaque (no markup inside).
# Every span is length-bounded and every opener anchored (possessive runs,
# look-behinds), so a hostile paragraph costs linear time, not quadratic.
_SPAN, _EMPH = 2000, 500  # code/maths, emphasis
_MD_INLINE = re.compile(
    r"(?P<code>(?<!`)(?P<ticks>`++)(?P<codetext>.{1,%(n)d}?)(?<!`)(?P=ticks)(?!`))"
    # Maths spans are unbounded but still linear: an opener only ever fails
    # when no closer follows it at all, which is true of the last one alone.
    r"|(?P<dmath>(?<!\$)\$\$.+?\$\$)"
    r"|(?P<math>(?<![\\$])\$(?!\s)[^$\n]+?(?<!\s)\$)"
    # Link and image spans stop at the next "[": then no character is scanned
    # by more than one opener, however many "[x](" a paragraph repeats.
    r"|(?P<image>!\[(?P<alt>[^\[\]]{0,500}+)\]\((?P<src>[^)\s\[]{0,2000}+)(?:\s++\"[^\"]{0,500}+\")?\))"
    r"|(?P<link>\[(?P<ltext>(?:[^\[\]]|\[[^\[\]]{0,500}+\]){0,500}+)\]\((?P<href>[^)\s\[]{0,2000}+)(?:\s++\"[^\"]{0,500}+\")?\))"
    r"|(?P<auto><(?P<autourl>(?:https?://|mailto:)[^>\s]{1,2000}+)>)"
    r"|(?P<strong>(?<!\*)\*\*(?P<s1>.{1,%(e)d}?)\*\*(?!\*)|(?<![\w])__(?P<s2>.{1,%(e)d}?)__(?![\w]))"
    r"|(?P<strike>~~(?P<k>.{1,%(e)d}?)~~)"
    r"|(?P<em>\*(?P<e1>[^*\s](?:.{0,%(e)d}?[^*\s])?)\*|(?<![\w])_(?P<e2>[^_\s](?:.{0,%(e)d}?[^_\s])?)_(?![\w]))"
    r"|(?P<escape>\\(?P<esc>[!-/:-@\[-`{-~]))"
    r"|(?P<hard>(?:(?<! ) {2,}+|\\)\n)" % {"n": _SPAN, "e": _EMPH},
    re.DOTALL,
)


_MAX_INLINE = 20_000  # a longer "paragraph" is shown as written, not interpreted


def _md_inline(text: str, marks: list[dict] | None = None, depth: int = 0) -> list[dict]:
    marks = marks or []
    if depth > 20 or len(text) > _MAX_INLINE:  # pathological input: stop interpreting
        return _inline([_txt(_soft(text), marks)])
    out: list[dict | None] = []
    pos = 0
    for m in _MD_INLINE.finditer(text):
        if m.start() < pos:
            continue
        out.append(_txt(_soft(text[pos:m.start()]), marks))
        pos = m.end()
        if m.group("code"):
            out.append(_txt(m.group("codetext").strip() or m.group("codetext"), [*marks, {"type": "code"}]))
        elif m.group("dmath") or m.group("math"):
            out.append(_txt(_soft(m.group(0)), marks))  # maths as written, on one line
        elif m.group("image"):
            alt = m.group("alt") or m.group("src") or "image"
            out.append(_txt(f"[image: {alt}]", marks))
        elif m.group("link"):
            inner = _md_inline(m.group("ltext"), marks, depth + 1)
            out.extend(_link_nodes(inner, m.group("href")))
        elif m.group("auto"):
            url = m.group("autourl")
            out.extend(_link_nodes([_txt(url, marks)], url))
        elif m.group("strong"):
            out.extend(_md_inline(m.group("s1") or m.group("s2"), [*marks, {"type": "bold"}], depth + 1))
        elif m.group("strike"):
            out.extend(_md_inline(m.group("k"), [*marks, {"type": "strike"}], depth + 1))
        elif m.group("em"):
            out.extend(_md_inline(m.group("e1") or m.group("e2"), [*marks, {"type": "italic"}], depth + 1))
        elif m.group("escape"):
            out.append(_txt(m.group("esc"), marks))
        elif m.group("hard"):
            out.append({"type": "hardBreak"})
    out.append(_txt(_soft(text[pos:]), marks))
    return _inline(out)


def _soft(text: str) -> str:
    """Soft line breaks join with a space, as Markdown renders them. (Split, not
    ``re.sub(r"[ \\t]*\\n[ \\t]*")``: that is quadratic on a long space run.)"""
    if "\n" not in text:
        return text
    *head, last = text.split("\n")
    return " ".join([head[0].rstrip(" \t"), *(p.strip(" \t") for p in head[1:]), last.lstrip(" \t")])


# --- Markdown → doc: blocks -----------------------------------------------------------

# Possessive tails: "```" + "a" * n + "`" would otherwise split the run between
# two overlapping classes every possible way — quadratic, with the GIL held.
_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*+([^\s`]*+)[^`]*+$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")  # the closing #s: _atx_text
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_BULLET = re.compile(r"^( {0,3})([-*+])([ \t]+|$)")
_ORDERED = re.compile(r"^( {0,3})(\d{1,9})([.)])([ \t]+|$)")
_QUOTE = re.compile(r"^ {0,3}> ?")
_TABLE_SEP = re.compile(r"^ {0,3}\|?[ \t]*+:?-++:?[ \t]*+(?:\|[ \t]*+:?-++:?[ \t]*+)*+\|?[ \t]*+$")
_MAX_DEPTH = 12


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _starts_block(line: str) -> bool:
    return bool(
        _ATX.match(line) or _FENCE.match(line) or _HR.match(line) or _QUOTE.match(line)
        or _BULLET.match(line) or _ORDERED.match(line)
    )


def _code(text: str, language: str | None = None) -> dict:
    node = _block("codeBlock", [{"type": "text", "text": text}] if text else None)
    node["attrs"] = {"language": language or None}
    return node


def _list_item(blocks: list[dict]) -> dict:
    # A list item opens with a paragraph (the schema's "paragraph block*").
    if not blocks or blocks[0].get("type") != "paragraph":
        blocks = [{"type": "paragraph"}, *blocks]
    return _block("listItem", blocks)


def _atx_text(raw: str | None) -> str:
    """An ATX heading's text without its optional closing ``#`` sequence —
    trimmed in Python, since a regex for it backtracks on long space runs."""
    text = (raw or "").rstrip(" \t")
    bare = text.rstrip("#")
    if bare != text and (not bare or bare[-1] in " \t"):
        text = bare.rstrip(" \t")
    return text


def _md_heading(level: int, text: str) -> dict | None:
    inline = [n for n in _md_inline(text.strip()) if n.get("type") == "text"]
    return _block("heading", inline, level=level) if inline else None  # a bare "#" is nothing


def _table_row(line: str, header: bool) -> dict:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]
    marks = [{"type": "bold"}] if header else None
    inline: list[dict | None] = []
    for k, cell in enumerate(cells):
        if k:
            inline.append(_txt(" | "))
        inline.extend(_md_inline(cell, marks))
    return _para(_inline(inline))


def _md_list(lines: list[str], i: int, depth: int) -> tuple[dict, int]:
    first = _BULLET.match(lines[i]) or _ORDERED.match(lines[i])
    assert first is not None
    ordered = first.re is _ORDERED
    marker = first.group(3) if ordered else first.group(2)

    def same_list(line: str) -> re.Match | None:
        m = (_ORDERED if ordered else _BULLET).match(line)
        if m and (m.group(3) if ordered else m.group(2)) == marker and not _HR.match(line):
            return m
        return None

    items: list[dict] = []
    n = len(lines)
    while i < n:
        m = same_list(lines[i])
        if not m:
            break
        gap = len(m.group(m.lastindex or 0))
        # Content starts after the marker and its spacing (CommonMark: a gap
        # of 5+ spaces means indented code, so the content column is marker+1).
        width = m.end() - gap + (1 if gap == 0 or gap > 4 else gap)
        item_lines = [lines[i][width:]]
        i += 1
        while i < n:
            line = lines[i]
            if not line.strip():
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _indent(lines[j]) >= width:
                    item_lines.extend([""] * (j - i))
                    i = j
                    continue
                break
            if _indent(line) >= width:
                item_lines.append(line[width:])
            elif item_lines[-1].strip() and not _starts_block(line):
                item_lines.append(line.strip())  # lazy paragraph continuation
            else:
                break
            i += 1
        items.append(_list_item(_md_blocks(item_lines, depth + 1)))
        j = i
        while j < n and not lines[j].strip():
            j += 1
        if j < n and same_list(lines[j]):
            i = j
            continue
        break
    if ordered:
        return _block("orderedList", items, start=int(first.group(2))), i
    return _block("bulletList", items), i


def _md_blocks(lines: list[str], depth: int = 0) -> list[dict]:
    if depth > _MAX_DEPTH:  # pathological nesting: the rest as one paragraph
        text = " ".join(ln.strip() for ln in lines if ln.strip())
        return [_para(_inline([_txt(text)]))] if text else []
    blocks: list[dict] = []
    para: list[str] = []

    def flush() -> None:
        text = "\n".join(para).strip()
        para.clear()
        if text:
            blocks.append(_para(_md_inline(text)))

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if m := _FENCE.match(line):
            flush()
            indent, fence, body = len(m.group(1)), m.group(2), []
            close = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")
            i += 1
            while i < n and not close.match(lines[i]):
                body.append(lines[i][min(indent, _indent(lines[i])):])
                i += 1
            i += 1  # the closing fence (or the end)
            blocks.append(_code("\n".join(body), m.group(3) or None))
            continue
        if m := _ATX.match(line):
            flush()
            if heading := _md_heading(len(m.group(1)), _atx_text(m.group(2))):
                blocks.append(heading)
            i += 1
            continue
        if para and _SETEXT.match(line):
            text = "\n".join(para)
            para.clear()
            if heading := _md_heading(1 if line.strip()[0] == "=" else 2, text):
                blocks.append(heading)
            i += 1
            continue
        if _HR.match(line):
            flush()
            blocks.append(_block("horizontalRule"))
            i += 1
            continue
        if _QUOTE.match(line):
            flush()
            body = []
            while i < n and lines[i].strip() and (_QUOTE.match(lines[i]) or not _starts_block(lines[i])):
                body.append(_QUOTE.sub("", lines[i], count=1))
                i += 1
            inner = _md_blocks(body, depth + 1)
            if inner:
                blocks.append(_block("blockquote", inner))
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush()
            blocks.append(_table_row(line, header=True))
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                blocks.append(_table_row(lines[i], header=False))
                i += 1
            continue
        lm = _BULLET.match(line) or _ORDERED.match(line)
        # A list may interrupt a paragraph, but "1999. was a year" mid-sentence
        # is prose: an ordered list only interrupts when it starts at 1.
        if lm and (not para or lm.re is _BULLET or lm.group(2) == "1"):
            flush()
            block, i = _md_list(lines, i, depth)
            blocks.append(block)
            continue
        if not para and _indent(line) >= 4:
            body = []
            while i < n and (not lines[i].strip() or _indent(lines[i]) >= 4):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            blocks.append(_code("\n".join(body)))
            continue
        para.append(line)
        i += 1
    flush()
    return blocks


def _demote_headings(blocks: list[dict]) -> None:
    """The challenge title is the page's heading, so the statement's own
    headings start one level down: its top level → h2, everything deeper → h3."""
    levels: list[int] = []

    def walk(nodes: list[dict], fn) -> None:
        for node in nodes:
            if node.get("type") == "heading":
                fn(node)
            walk(node.get("content") or [], fn)

    walk(blocks, lambda h: levels.append(h["attrs"]["level"]))
    if levels:
        top = min(levels)
        walk(blocks, lambda h: h["attrs"].update(level=min(3, 2 + h["attrs"]["level"] - top)))


def _lines(text: str) -> list[str]:
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Leading tabs to spaces (indentation is measured in spaces).
    return [re.sub(r"^[ \t]+", lambda m: m.group(0).expandtabs(4), ln) for ln in src.split("\n")]


def markdown_to_doc(text: str) -> dict:
    """A Markdown statement as a rich-text document (best effort; never raises)."""
    try:
        blocks = _md_blocks(_lines(text))
        _demote_headings(blocks)
        return _doc(blocks)
    except Exception:  # noqa: BLE001 — formatting must never fail an import
        return _plain_doc(text)


# --- LaTeX → doc ---------------------------------------------------------------------
#
# A single pass over the source emits a flat stream of events — text runs (with
# their marks), maths, breaks, headings, list/quote open+close, code — which
# ``_assemble`` then nests into blocks. Groups and formatting commands recurse
# on their argument with the marks extended, so a declaration like ``{\bf x}``
# lasts exactly to the end of its group, as in TeX.

_TEX_SECTIONS = {"chapter": 1, "section": 1, "subsection": 2, "subsubsection": 3}
_TEX_RUN_IN = {"paragraph", "subparagraph"}  # a bold lead-in, not a heading
_TEX_MARKS = {
    "textbf": "bold", "emph": "italic", "textit": "italic", "textsl": "italic",
    "texttt": "code", "underline": "underline", "uline": "underline", "sout": "strike",
}
_TEX_DECLS = {
    "bf": "bold", "bfseries": "bold", "it": "italic", "itshape": "italic", "em": "italic",
    "sl": "italic", "slshape": "italic", "tt": "code", "ttfamily": "code",
}
_TEX_SYMBOLS = {
    "ldots": "…", "dots": "…", "textellipsis": "…", "LaTeX": "LaTeX", "TeX": "TeX",
    "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^", "textless": "<",
    "textgreater": ">", "textbar": "|", "textendash": "–", "textemdash": "—", "textbullet": "•",
    "textquoteleft": "‘", "textquoteright": "’", "textquotedblleft": "“", "textquotedblright": "”",
    "S": "§", "P": "¶", "copyright": "©", "textdegree": "°", "textregistered": "®",
    "texttrademark": "™", "quad": " ", "qquad": " ", "enspace": " ", "thinspace": " ",
    "space": " ", "slash": "/", "i": "i", "j": "j", "ss": "ß", "ae": "æ", "AE": "Æ",
    "oe": "œ", "OE": "Œ", "o": "ø", "O": "Ø", "aa": "å", "AA": "Å", "l": "ł", "L": "Ł",
}
# \x for a non-letter x: the character itself unless listed (spacing commands).
_TEX_CHAR = {" ": " ", "\n": " ", "\t": " ", ",": " ", ";": " ", ":": " ", "!": "", "-": "", "/": "", "@": ""}
_TEX_ACCENTS = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
    ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "r": "\u030a",
    "k": "\u0328",
}
# Layout-only commands: their arguments are swallowed, nothing is shown.
_TEX_SKIP = {
    "label": 1, "vspace": 1, "hspace": 1, "setlength": 2, "addtolength": 2, "fontsize": 2,
    "sampletable": 2, "sampletableinteractive": 3, "usepackage": 1, "documentclass": 1,
    "input": 1, "include": 1, "pagestyle": 1, "thispagestyle": 1, "color": 1, "definecolor": 3,
    "setcounter": 2, "addtocounter": 2, "phantom": 1, "hphantom": 1, "vphantom": 1,
    "hypersetup": 1, "newcommand": 2, "renewcommand": 2, "providecommand": 2,
    "newenvironment": 3, "renewenvironment": 3, "cline": 1, "rule": 2, "problemname": 1,
    "author": 1, "source": 1, "date": 1, "title": 1,
}
_TEX_IGNORE = {
    "noindent", "indent", "medskip", "bigskip", "smallskip", "centering", "raggedright",
    "raggedleft", "clearpage", "newpage", "pagebreak", "nopagebreak", "maketitle", "small",
    "footnotesize", "scriptsize", "tiny", "large", "Large", "LARGE", "huge", "Huge",
    "normalsize", "normalfont", "rmfamily", "sffamily", "upshape", "mdseries", "selectfont",
    "hfill", "vfill", "hfil", "vfil", "hline", "toprule", "midrule", "bottomrule", "protect",
    "relax", "leavevmode", "displaystyle", "tableofcontents", "today", "hrule", "break",
    "allowbreak", "nobreak", "sloppy", "fussy", "null", "strut",
}
_TEX_LISTS = {
    "itemize": "bulletList", "enumerate": "orderedList", "description": "bulletList",
    "compactitem": "bulletList", "compactenum": "orderedList",
}
_TEX_QUOTES = {"quote", "quotation", "verse"}
_TEX_VERBATIM = {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "alltt"}
_TEX_DROP = {"comment"}
_TEX_MATH = {
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*",
    "displaymath", "eqnarray", "eqnarray*", "math", "flalign", "flalign*", "alignat", "alignat*",
}
_TEX_TABLES = {"tabular": 1, "tabular*": 2, "tabularx": 2, "tabulary": 2, "longtable": 1}
_TEX_ENV_ARGS = {"minipage": 1, "wrapfigure": 2, "multicols": 1, "list": 2}

_TEX_BUDGET = 8_000_000  # characters examined; past it, fall back to plain text
_TEX_MAX_DEPTH = 40
_TEX_PLAIN_RUN = re.compile(r"[^\\%\n{}$~&]+")
_TEX_BRACE = re.compile(r"\\.|[{}]|%[^\n]*", re.DOTALL)
_WS = re.compile(r"[ \t\r\n]+")


class _TooComplex(Exception):
    pass


def _skip_spaces(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _tex_typography(text: str) -> str:
    return (
        text.replace("---", "—").replace("--", "–")
        .replace("``", "“").replace("''", "”").replace("`", "‘")
    )


def _split_top(s: str, rows: bool) -> list[str]:
    """Split a tabular body into rows (on ``\\\\``) or a row into cells (on
    ``&``), ignoring separators inside braces and escaped characters."""
    parts: list[str] = []
    depth = start = i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if rows and depth == 0 and s.startswith("\\\\", i):
                parts.append(s[start:i])
                i += 2
                if i < n and s[i] == "[":  # \\[2pt] row spacing
                    close = s.find("]", i, i + 40)
                    i = close + 1 if close >= 0 else i
                start = i
                continue
            i += 2
            continue
        if c == "%":
            nl = s.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "&" and not rows and depth == 0:
            parts.append(s[start:i])
            start = i + 1
        i += 1
    parts.append(s[start:])
    return parts


class _Tex:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.budget = _TEX_BUDGET

    def spend(self, n: int) -> None:
        self.budget -= max(n, 1)
        if self.budget < 0:
            raise _TooComplex

    def sub(self, s: str, marks: list[dict], depth: int) -> list[tuple]:
        saved, self.events = self.events, []
        try:
            self.scan(s, marks, depth)
            return self.events
        finally:
            self.events = saved

    # -- reading arguments --

    def group_end(self, s: str, i: int) -> int | None:
        """``s[i] == "{"`` → the index of its matching ``}`` (None if unclosed)."""
        depth = 0
        for m in _TEX_BRACE.finditer(s, i):
            t = m.group()
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    self.spend(m.end() - i)
                    return m.start()
        self.spend(len(s) - i)
        return None

    def arg(self, s: str, i: int) -> tuple[str | None, int]:
        j = _skip_spaces(s, i)
        if j < len(s) and s[j] == "{":
            e = self.group_end(s, j)
            if e is not None:
                return s[j + 1:e], e + 1
        return None, i

    def opt(self, s: str, i: int) -> tuple[str | None, int]:
        j = _skip_spaces(s, i)
        if j < len(s) and s[j] == "[":
            depth = 0
            self.spend(min(len(s), j + 2000) - j)
            for k in range(j, min(len(s), j + 2000)):
                if s[k] in "[{":
                    depth += 1
                elif s[k] in "]}":
                    depth -= 1
                    if depth == 0:
                        return s[j + 1:k], k + 1
        return None, i

    def skip_args(self, s: str, i: int, count: int) -> int:
        _, i = self.opt(s, i)
        for _ in range(count):
            got, i = self.arg(s, i)
            if got is None:
                break
            _, i = self.opt(s, i)
        return i

    def env_end(self, s: str, i: int, env: str) -> tuple[int, int]:
        """From just after ``\\begin{env}``: where the matching ``\\end{env}``
        starts and ends (the end of the text when it's never closed)."""
        depth = 1
        for m in re.finditer(r"\\(begin|end)\s*\{" + re.escape(env) + r"\}", s[i:]):
            depth += 1 if m.group(1) == "begin" else -1
            if depth == 0:
                self.spend(m.end())
                return i + m.start(), i + m.end()
        self.spend(len(s) - i)
        return len(s), len(s)

    # -- the scan --

    def text(self, t: str, marks: list[dict]) -> None:
        if t:
            self.events.append(("text", t, marks))

    def scan(self, s: str, marks: list[dict], depth: int) -> None:
        if depth > _TEX_MAX_DEPTH:
            raise _TooComplex
        self.spend(len(s))
        buf: list[str] = []
        cur = marks

        def flush() -> None:
            if buf:
                self.text("".join(buf), cur)
                buf.clear()

        i, n = 0, len(s)
        line_start = False  # just after a newline (a comment's included)
        while i < n:
            c = s[i]
            if c == "\\":
                flush()
                i, cur = self.command(s, i, cur, depth)
                line_start = False
            elif c == "%":
                nl = s.find("\n", i)
                i = _skip_spaces(s, n if nl < 0 else nl + 1)
                line_start = True
            elif c == "\n":
                j = _skip_spaces(s, i + 1)
                if line_start or (j < n and s[j] == "\n"):
                    flush()
                    self.events.append(("par",))
                    while j < n and s[j].isspace():
                        j += 1
                    line_start = False
                else:
                    buf.append(" ")
                    line_start = True
                i = j
            elif c == "{":
                e = self.group_end(s, i)
                if e is None:
                    i += 1
                else:
                    flush()
                    self.scan(s[i + 1:e], cur, depth + 1)
                    i = e + 1
                line_start = False
            elif c == "}":
                i += 1
            elif c == "$":
                flush()
                i = self.math(s, i, cur)
                line_start = False
            elif c == "~":
                buf.append("\u00a0")
                i += 1
                line_start = False
            elif c == "&":  # a stray alignment tab
                buf.append(" ")
                i += 1
            else:
                m = _TEX_PLAIN_RUN.match(s, i)
                run = m.group() if m else c
                buf.append(run)
                i += len(run)
                if run.strip():
                    line_start = False
        flush()

    def math(self, s: str, i: int, marks: list[dict]) -> int:
        if s.startswith("$$", i):
            e = s.find("$$", i + 2)
            self.spend((e if e >= 0 else len(s)) - i)
            if e < 0:
                self.text("$$", marks)
                return i + 2
            self.events.append(("display", s[i:e + 2]))
            return e + 2
        j = i + 1
        while True:
            e = s.find("$", j)
            self.spend((e if e >= 0 else len(s)) - j)
            if e < 0:
                self.text("$", marks)
                return i + 1
            if s[e - 1] != "\\":
                break
            j = e + 1
        self.events.append(("math", s[i:e + 1], marks))
        return e + 1

    def delimited(self, s: str, start: int, i: int, close: str, display: bool, marks: list[dict]) -> int:
        """``\\(…\\)`` / ``\\[…\\]``: kept as written, in the dollar form the
        Markdown side (and a Markdown export) also uses."""
        e = s.find(close, i)
        self.spend((e if e >= 0 else len(s)) - i)
        if e < 0:
            self.text(s[start + 1:i], marks)
            return i
        inner = s[i:e].strip()
        if inner and display:
            self.events.append(("display", f"$${inner}$$"))
        elif inner:
            self.events.append(("math", f"${inner}$", marks))
        return e + 2

    def command(self, s: str, i: int, marks: list[dict], depth: int) -> tuple[int, list[dict]]:
        start, n = i, len(s)
        j = i + 1
        if j >= n:
            return n, marks
        if s[j].isalpha():
            k = j
            while k < n and s[k].isalpha():
                k += 1
            name = s[j:k]
            if k < n and s[k] == "*" and (name in _TEX_SECTIONS or name in _TEX_RUN_IN or name in _TEX_SKIP):
                k += 1
            i = k if name == "verb" else _skip_spaces(s, k)
        else:
            name, i = s[j], j + 1

        if name in _TEX_SECTIONS:
            _, i = self.opt(s, i)
            arg, i = self.arg(s, i)
            if arg is not None:
                self.events.append(("heading", _TEX_SECTIONS[name], self.sub(arg, [], depth + 1)))
        elif name in _TEX_RUN_IN:
            arg, i = self.arg(s, i)
            if arg is not None:
                self.events.append(("par",))
                self.scan(arg, [*marks, {"type": "bold"}], depth + 1)
                self.text(" ", marks)
        elif name == "begin":
            i = self.begin(s, start, i, marks, depth)
        elif name == "end":
            env, i = self.arg(s, i)
            env = (env or "").strip()
            if env in _TEX_LISTS:
                self.events.append(("close", "list"))
            elif env in _TEX_QUOTES:
                self.events.append(("close", "quote"))
            else:
                self.events.append(("par",))
        elif name == "item":
            label, i = self.opt(s, i)
            self.events.append(("item",))
            if label:
                self.scan(label, [*marks, {"type": "bold"}], depth + 1)
                self.text(" ", marks)
        elif name in ("\\", "newline", "linebreak"):
            if name == "\\":
                if i < n and s[i] == "*":
                    i += 1
                _, i = self.opt(s, i)
            self.events.append(("hard",))
        elif name == "par":
            self.events.append(("par",))
        elif name == "(":
            i = self.delimited(s, start, i, "\\)", False, marks)
        elif name == "[":
            i = self.delimited(s, start, i, "\\]", True, marks)
        elif name in _TEX_MARKS:
            arg, i = self.arg(s, i)
            if arg is not None:
                self.scan(arg, [*marks, {"type": _TEX_MARKS[name]}], depth + 1)
        elif name in _TEX_DECLS:
            return i, [*marks, {"type": _TEX_DECLS[name]}]
        elif name == "url":
            arg, i = self.arg(s, i)
            if arg is not None:
                url = re.sub(r"\\([%#&_~$])", r"\1", arg.strip())
                href = _safe_href(url)
                self.text(url, [*marks, {"type": "link", "attrs": {"href": href}}] if href else marks)
        elif name == "href":
            url, i = self.arg(s, i)
            label, i = self.arg(s, i)
            if url is not None and label is not None:
                url = re.sub(r"\\([%#&_~$])", r"\1", url.strip())
                href = _safe_href(url)
                if href:
                    self.scan(label, [*marks, {"type": "link", "attrs": {"href": href}}], depth + 1)
                else:
                    self.scan(label, marks, depth + 1)
                    self.text(f" ({url})", marks)
        elif name == "includegraphics":
            _, i = self.opt(s, i)
            arg, i = self.arg(s, i)
            if arg is not None:
                self.text(f"[image: {arg.strip()}]", marks)
        elif name == "illustration":  # the problem-format macro: {width}{file}{credit}
            _, i = self.arg(s, i)
            image, i = self.arg(s, i)
            _, i = self.arg(s, i)
            if image is not None:
                self.events.append(("par",))
                self.text(f"[image: {image.strip()}]", marks)
                self.events.append(("par",))
        elif name == "verb":
            if i < n:
                e = s.find(s[i], i + 1)
                self.spend((e if e >= 0 else n) - i)
                if e > i:
                    self.text(s[i + 1:e], [*marks, {"type": "code"}])
                    i = e + 1
        elif name in _TEX_ACCENTS:
            i = self.accent(s, i, name, marks)
        elif name in _TEX_SYMBOLS:
            self.text(_TEX_SYMBOLS[name], marks)
        elif name in _TEX_SKIP:
            i = self.skip_args(s, i, _TEX_SKIP[name])
        elif name in _TEX_IGNORE:
            pass
        elif not name.isalpha():
            self.text(_TEX_CHAR.get(name, name), marks)
        else:
            # Unknown macro: keep its (last) argument's text, drop the rest.
            _, i = self.opt(s, i)
            last = None
            while True:
                got, j = self.arg(s, i)
                if got is None:
                    break
                last, i = got, j
            if last is not None:
                self.scan(last, marks, depth + 1)
        return i, marks

    def accent(self, s: str, i: int, name: str, marks: list[dict]) -> int:
        if i < len(s) and s[i] == "{":
            e = self.group_end(s, i)
            if e is None:
                return i
            base, i = s[i + 1:e].strip(), e + 1
        else:
            base, i = s[i:i + 1], i + 1
            if base == "\\":  # \'\i
                k = i
                while k < len(s) and s[k].isalpha():
                    k += 1
                base, i = s[i - 1:k], k
        if base.startswith("\\"):
            base = _TEX_SYMBOLS.get(base[1:].strip(), base[1:].strip())
        if base:
            self.text(unicodedata.normalize("NFC", base[0] + _TEX_ACCENTS[name] + base[1:]), marks)
        elif not name.isalpha():
            self.text(name, marks)  # \^{} is a caret, \~{} a tilde
        return i

    def begin(self, s: str, start: int, i: int, marks: list[dict], depth: int) -> int:
        env, i = self.arg(s, i)
        if env is None:
            return i
        env = env.strip()
        if env in _TEX_VERBATIM:
            lang = None
            if env == "minted":
                _, i = self.opt(s, i)
                lang, i = self.arg(s, i)
            elif env == "lstlisting":
                options, i = self.opt(s, i)
                m = re.search(r"language\s*=\s*\{?([\w+#-]+)", options or "")
                lang = m.group(1) if m else None
            close = "\\end{" + env + "}"
            e = s.find(close, i)
            self.spend((e if e >= 0 else len(s)) - i)
            body = s[i:] if e < 0 else s[i:e]
            body = re.sub(r"^[ \t]*\n", "", body).rstrip()
            self.events.append(("code", body, lang.strip().lower() if lang else None))
            return len(s) if e < 0 else e + len(close)
        if env in _TEX_DROP:
            _, after = self.env_end(s, i, env)
            return after
        if env in _TEX_MATH:
            _, after = self.env_end(s, i, env)
            self.events.append(("display", f"$${s[start:after]}$$"))
            return after
        if env in _TEX_TABLES:
            i = self.skip_args(s, i, _TEX_TABLES[env])
            body_end, after = self.env_end(s, i, env)
            self.spend(2 * (body_end - i))  # split into rows, then cells
            self.events.append(("par",))
            for row in _split_top(s[i:body_end], rows=True):
                for k, cell in enumerate(_split_top(row, rows=False)):
                    if k:
                        self.text(" | ", marks)
                    self.scan(cell, marks, depth + 1)
                self.events.append(("par",))
            return after
        if env in _TEX_LISTS:
            _, i = self.opt(s, i)
            self.events.append(("open", "list", _TEX_LISTS[env]))
            return i
        if env in _TEX_QUOTES:
            self.events.append(("open", "quote", None))
            return i
        # Anything else (center, figure, minipage, document…) is transparent.
        i = self.skip_args(s, i, _TEX_ENV_ARGS.get(env, 0))
        self.events.append(("par",))
        return i


def _tidy(nodes: list[dict]) -> list[dict]:
    """Collapse TeX whitespace across a run of inline nodes; [] if nothing shows."""
    out: list[dict] = []
    for node in nodes:
        if node.get("type") == "text":
            text = _WS.sub(" ", node["text"])
            if not out or out[-1].get("type") == "hardBreak" or out[-1]["text"].endswith(" "):
                text = text.lstrip(" ")
            if text:
                out.append({**node, "text": text})
        else:
            if out and out[-1].get("type") == "text":
                out[-1] = {**out[-1], "text": out[-1]["text"].rstrip(" ")}
                if not out[-1]["text"]:
                    out.pop()
            out.append(node)
    if out and out[-1].get("type") == "text":
        out[-1] = {**out[-1], "text": out[-1]["text"].rstrip(" ")}
        if not out[-1]["text"]:
            out.pop()
    out = _inline(out)
    if not any(n.get("type") == "text" and n["text"].strip() for n in out):
        return []
    return out


def _tex_inline(event: tuple) -> dict | None:
    kind = event[0]
    if kind == "text":
        marks = event[2]
        code = any(m["type"] == "code" for m in marks)
        return _txt(event[1] if code else _tex_typography(event[1]), list(marks))
    if kind == "math":
        return _txt(event[1], [m for m in event[2] if m["type"] != "code"])
    if kind == "hard":
        return {"type": "hardBreak"}
    if kind in ("par", "item", "open", "close", "heading", "code", "display"):
        return _txt(" ")
    return None


def _assemble(events: list[tuple]) -> list[dict]:
    """Nest the event stream into blocks. Frames: root, list, item, quote."""
    root: dict = {"kind": "root", "blocks": []}
    stack: list[dict] = [root]
    para: list[dict] = []

    def target() -> list[dict]:
        if stack[-1]["kind"] == "list":  # content before the first \item
            stack.append({"kind": "item", "blocks": []})
        return stack[-1]["blocks"]

    def flush() -> None:
        nodes = _tidy([n for n in para if n])
        para.clear()
        if nodes:
            p = _para(nodes)
            if p.get("content"):
                target().append(p)

    def finish(frame: dict) -> dict | None:
        if frame["kind"] == "item":
            return _list_item(frame["blocks"])
        if frame["kind"] == "list":
            if not frame["items"]:
                return None
            if frame["type"] == "orderedList":
                return _block("orderedList", frame["items"], start=1)
            return _block("bulletList", frame["items"])
        return _block("blockquote", frame["blocks"]) if frame["blocks"] else None

    def pop() -> None:
        frame = stack.pop()
        node = finish(frame)
        if node is None:
            return
        if frame["kind"] == "item":
            stack[-1]["items"].append(node)
        else:
            target().append(node)

    def close(kind: str) -> None:
        flush()
        if not any(f["kind"] == kind for f in stack[1:]):
            return  # a stray \end
        while True:
            kind_popped = stack[-1]["kind"]
            pop()
            if kind_popped == kind:
                break

    for ev in events:
        kind = ev[0]
        if kind in ("text", "math", "hard"):
            para.append(_tex_inline(ev))
        elif kind == "par":
            flush()
        elif kind == "heading":
            flush()
            inline = _tidy([n for n in map(_tex_inline, ev[2]) if n])
            if inline:
                target().append(_block("heading", inline, level=ev[1]))
        elif kind == "open":
            flush()
            target()
            if ev[1] == "list":
                stack.append({"kind": "list", "type": ev[2], "items": []})
            else:
                stack.append({"kind": "quote", "blocks": []})
        elif kind == "close":
            close(ev[1])
        elif kind == "item":
            flush()
            if any(f["kind"] == "list" for f in stack):
                while stack[-1]["kind"] != "list":
                    pop()
                stack.append({"kind": "item", "blocks": []})
        elif kind == "code":
            flush()
            target().append(_code(ev[1], ev[2]))
        elif kind == "display":
            flush()
            maths = _WS.sub(" ", ev[1]).strip()
            if maths:
                target().append(_para([{"type": "text", "text": maths}]))
    flush()
    while len(stack) > 1:
        pop()
    return root["blocks"]


def _tex_body(text: str) -> str:
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # A full document: only its body. (Problem statements are usually fragments.)
    m = re.search(r"\\begin\s*\{document\}", src)
    if m:
        src = src[m.end():]
        end = src.find("\\end{document}")
        if end >= 0:
            src = src[:end]
    return src


def latex_to_doc(text: str) -> dict:
    """A LaTeX statement as a rich-text document (best effort; never raises)."""
    try:
        tex = _Tex()
        tex.scan(_tex_body(text), [], 0)
        blocks = _assemble(tex.events)
        _demote_headings(blocks)
        return _doc(blocks)
    except Exception:  # noqa: BLE001 — formatting must never fail an import
        return _plain_doc(text)


def latex_problem_name(text: str) -> str | None:
    """The ``\\problemname{…}`` of a LaTeX statement, as plain text."""
    try:
        src = str(text or "")
        m = re.search(r"\\problemname\s*(?=\{)", src)
        if not m:
            return None
        tex = _Tex()
        arg, _ = tex.arg(src, m.end())
        if arg is None:
            return None
        nodes = _tidy([n for n in map(_tex_inline, tex.sub(arg, [], 0)) if n])
        name = "".join(n.get("text", " ") for n in nodes).strip()
        return name[:200] or None
    except Exception:  # noqa: BLE001
        return None


# --- doc → Markdown (export) ----------------------------------------------------------

# The importer's maths patterns exactly, so what was maths there stays maths.
_MD_MATH = re.compile(r"(?<!\$)\$\$.+?\$\$|(?<![\\$])\$(?!\s)[^$\n]+?(?<!\s)\$", re.DOTALL)
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<~])")
_MD_LINE_START = re.compile(r"^([#>+=|-]|\d{1,9}(?=[.)]))")


def _md_escape(text: str) -> str:
    # Maths stays exactly as written: "$x_1$" must not become "$x\_1$".
    out, pos = [], 0
    for m in _MD_MATH.finditer(text):
        out.append(_MD_SPECIAL.sub(r"\\\1", text[pos:m.start()]))
        out.append(m.group())
        pos = m.end()
    out.append(_MD_SPECIAL.sub(r"\\\1", text[pos:]))
    return "".join(out)


def _md_code_span(text: str) -> str:
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def _mark_key(mark: dict) -> tuple:
    return (mark.get("type"), (mark.get("attrs") or {}).get("href"))


def _delims(mark: dict) -> tuple[str, str]:
    kind = mark.get("type")
    if kind == "link":
        href = str((mark.get("attrs") or {}).get("href") or "").replace(")", "%29").replace(" ", "%20")
        return "[", f"]({href})"
    return {"bold": ("**", "**"), "italic": ("*", "*"), "strike": ("~~", "~~")}.get(kind, ("", ""))


def _md_inline_out(nodes: list[dict]) -> str:
    out: list[str] = []
    stack: list[tuple[tuple, str]] = []  # open marks: (key, closing delimiter)
    for node in [*nodes, None]:
        if node is not None and node.get("type") == "hardBreak":
            out.append("\\\n")
            continue
        if node is not None and node.get("type") != "text":
            node = {"type": "text", "text": _doc_plain(node)}
        marks = (node or {}).get("marks") or []
        code = any(m.get("type") == "code" for m in marks)
        want = sorted(
            (m for m in marks if m.get("type") in ("link", "bold", "italic", "strike")),
            key=lambda m: _MARK_ORDER.index(m["type"]),
        )
        keep = 0
        while keep < len(stack) and keep < len(want) and stack[keep][0] == _mark_key(want[keep]):
            keep += 1
        if len(stack) > keep:
            # "**a **" isn't emphasis: a run's trailing spaces go after its closer.
            trail = ""
            if out and out[-1].endswith(" "):
                trail = out[-1][len(out[-1].rstrip(" ")):]
                out[-1] = out[-1].rstrip(" ")
            while len(stack) > keep:
                out.append(stack.pop()[1])
            out.append(trail)
        text = str((node or {}).get("text") or "")
        if len(want) > keep:
            lead = text[: len(text) - len(text.lstrip(" "))]  # …and leading ones before the opener
            out.append(lead)
            text = text[len(lead):]
            for mark in want[keep:]:
                opening, closing = _delims(mark)
                out.append(opening)
                stack.append((_mark_key(mark), closing))
        if node is not None:
            out.append(_md_code_span(text) if code and text else _md_escape(text))
    md = "".join(out)
    # A line that would read as a heading, quote, list or table: escape its start.
    return "\n".join(_MD_LINE_START.sub(_escape_line_start, ln.lstrip(" ")) for ln in md.split("\n"))


def _escape_line_start(m: re.Match) -> str:
    lead = m.group(1)
    return lead + "\\" if lead.isdigit() else "\\" + lead


def _doc_plain(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if isinstance(node.get("text"), str):
        return node["text"]
    return "".join(_doc_plain(c) for c in node.get("content") or [])


def _md_blocks_out(nodes: list[Any]) -> str:
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        content = [c for c in node.get("content") or [] if isinstance(c, dict)]
        attrs = node.get("attrs") or {}
        if kind == "paragraph":
            text = _md_inline_out(content)
            if text.strip():
                parts.append(text)
        elif kind == "heading":
            level = attrs.get("level") if isinstance(attrs.get("level"), int) else 2
            text = _md_inline_out([c for c in content if c.get("type") != "hardBreak"]).replace("\n", " ")
            if text.strip():
                parts.append("#" * max(1, min(6, level)) + " " + text)
        elif kind in ("bulletList", "orderedList"):
            start = attrs.get("start") if isinstance(attrs.get("start"), int) else 1
            items = []
            for k, item in enumerate(content):
                marker = f"{start + k}. " if kind == "orderedList" else "- "
                lines = _md_blocks_out(item.get("content") or []).split("\n")
                pad = " " * len(marker)
                items.append(marker + lines[0] + "".join("\n" + (pad + ln if ln else "") for ln in lines[1:]))
            if items:
                parts.append("\n".join(items))
        elif kind == "blockquote":
            body = _md_blocks_out(content)
            if body:
                parts.append("\n".join("> " + ln if ln else ">" for ln in body.split("\n")))
        elif kind == "codeBlock":
            text = _doc_plain(node)
            longest = max((len(r) for r in re.findall(r"^`{3,}", text, re.MULTILINE)), default=2)
            fence = "`" * max(3, longest + 1)
            lang = attrs.get("language") if isinstance(attrs.get("language"), str) else ""
            parts.append(f"{fence}{lang}\n{text}\n{fence}")
        elif kind == "horizontalRule":
            parts.append("---")
        else:
            text = _doc_plain(node).strip()
            if text:
                parts.append(_md_escape(text))
    return "\n\n".join(parts)


def doc_to_markdown(doc: Any) -> str:
    """A rich-text document as Markdown, for a package's statement (never raises)."""
    try:
        if not isinstance(doc, dict):
            return ""
        body = _md_blocks_out(doc.get("content") or [])
        return body + "\n" if body else ""
    except Exception:  # noqa: BLE001
        return _doc_plain(doc) + "\n"
