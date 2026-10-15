"""Statement conversion for problem packages (#451): Markdown / LaTeX → rich
text, and rich text → Markdown on export. Best effort by design, so these
pin the subset statements actually use, the schema-shape of every output, and
that nothing — however hostile — raises or runs away."""

from __future__ import annotations

import random
import time

import pytest

from utils.statement_convert import (
    doc_to_markdown,
    latex_problem_name,
    latex_to_doc,
    markdown_to_doc,
)

# --- the shape every output must have ----------------------------------------------

BLOCKS = {"paragraph", "heading", "bulletList", "orderedList", "blockquote", "codeBlock", "horizontalRule"}
MARKS = {"bold", "italic", "underline", "strike", "code", "link"}


def assert_valid(doc: dict) -> None:
    """The StarterKit schema, as far as the renderer cares: a malformed node is
    a silently blank description."""
    assert doc["type"] == "doc"
    assert doc["content"], "a doc needs at least one block"
    for block in doc["content"]:
        _check_block(block, depth=0)


def _check_block(node: dict, depth: int) -> None:
    kind = node["type"]
    assert kind in BLOCKS, kind
    content = node.get("content", [])
    if kind in ("paragraph", "heading"):
        _check_inline(content)
        if kind == "heading":
            assert node["attrs"]["level"] in (2, 3), "statement headings sit under the title"
            assert content
    elif kind in ("bulletList", "orderedList"):
        assert content
        for item in content:
            assert item["type"] == "listItem"
            assert item["content"][0]["type"] == "paragraph", "a list item opens with a paragraph"
            for child in item["content"]:
                _check_block(child, depth + 1)
        if kind == "orderedList":
            assert isinstance(node["attrs"]["start"], int)
    elif kind == "blockquote":
        assert content
        for child in content:
            _check_block(child, depth + 1)
    elif kind == "codeBlock":
        assert "language" in node["attrs"]
        assert all(c["type"] == "text" and c["text"] and "marks" not in c for c in content)
    elif kind == "horizontalRule":
        assert not content


def _check_inline(nodes: list[dict]) -> None:
    for node in nodes:
        assert node["type"] in ("text", "hardBreak"), node
        if node["type"] == "text":
            assert isinstance(node["text"], str) and node["text"], "no empty text nodes"
            marks = node.get("marks", [])
            kinds = [m["type"] for m in marks]
            assert set(kinds) <= MARKS
            assert len(kinds) == len(set(kinds))
            if "code" in kinds:
                assert kinds == ["code"], "the code mark excludes the others"
            for m in marks:
                if m["type"] == "link":
                    assert m["attrs"]["href"].startswith(("http://", "https://", "mailto:"))


def text_of(node) -> str:
    if isinstance(node, dict):
        if "text" in node:
            return node["text"]
        if node.get("type") == "hardBreak":
            return "\n"
        sep = "\n" if node.get("type") == "doc" else ""
        return sep.join(text_of(c) for c in node.get("content", []))
    return ""


def runs(doc: dict) -> list[tuple[str, tuple[str, ...]]]:
    """Every text run with its mark types, in order."""
    out = []

    def walk(node):
        if node.get("type") == "text":
            out.append((node["text"], tuple(m["type"] for m in node.get("marks", []))))
        for c in node.get("content", []):
            walk(c)

    walk(doc)
    return out


def blocks(doc: dict) -> list[str]:
    return [b["type"] for b in doc["content"]]


# --- Markdown ------------------------------------------------------------------------


def test_markdown_headings_sit_under_the_challenge_title():
    doc = markdown_to_doc("## Input\n\ntext\n\n### Constraints\n\n#### Deeper\n")
    assert_valid(doc)
    levels = [b["attrs"]["level"] for b in doc["content"] if b["type"] == "heading"]
    # The statement's top level becomes h2, everything deeper h3.
    assert levels == [2, 3, 3]


def test_markdown_setext_and_closing_hashes():
    doc = markdown_to_doc("Input\n=====\n\nOutput ##\n------\n\n# Sample #\n")
    assert_valid(doc)
    assert [text_of(b) for b in doc["content"]] == ["Input", "Output ##", "Sample"]


def test_markdown_inline_marks_and_soft_breaks():
    doc = markdown_to_doc("A **bold** and *em* and _also em_ and ~~gone~~,\nthen `x < y` and **nest *both***.")
    assert_valid(doc)
    assert blocks(doc) == ["paragraph"]
    assert runs(doc) == [
        ("A ", ()),
        ("bold", ("bold",)),
        (" and ", ()),
        ("em", ("italic",)),
        (" and ", ()),
        ("also em", ("italic",)),
        (" and ", ()),
        ("gone", ("strike",)),
        # The soft line break joins with a space.
        (", then ", ()),
        ("x < y", ("code",)),
        (" and ", ()),
        ("nest ", ("bold",)),
        ("both", ("bold", "italic")),
        (".", ()),
    ]


def test_markdown_hard_breaks():
    doc = markdown_to_doc("one  \ntwo\\\nthree")
    kinds = [n["type"] for n in doc["content"][0]["content"]]
    assert kinds == ["text", "hardBreak", "text", "hardBreak", "text"]


def test_markdown_maths_is_kept_verbatim_and_opaque():
    doc = markdown_to_doc("Let $a_i \\le 10^9$ and $$\\sum_{i=1}^{n} a_i$$ but costs $5 and $6.")
    assert_valid(doc)
    text = text_of(doc)
    assert "$a_i \\le 10^9$" in text
    assert "$$\\sum_{i=1}^{n} a_i$$" in text
    # Underscores inside maths are not emphasis; prices are not maths.
    assert all(marks == () for _, marks in runs(doc))
    assert "costs $5 and $6." in text


def test_markdown_display_maths_across_lines_lands_on_one_line():
    doc = markdown_to_doc("$$\nx = 1\ny = 2\n$$")
    assert text_of(doc) == "$$ x = 1 y = 2 $$"


def test_markdown_links_safe_and_unsafe():
    doc = markdown_to_doc(
        "[docs](https://example.com/a) and <https://example.org> and "
        "[evil](javascript:alert(1)) and [rel](../other.md)"
    )
    assert_valid(doc)
    linked = [n for n in doc["content"][0]["content"] if n.get("marks")]
    assert [(n["text"], n["marks"][0]["attrs"]["href"]) for n in linked] == [
        ("docs", "https://example.com/a"),
        ("https://example.org", "https://example.org"),
    ]
    text = text_of(doc)
    # A non-web link keeps its text, and shows where it pointed, unlinked.
    assert "evil (javascript:alert(1" in text
    assert "rel (../other.md)" in text


def test_markdown_images_become_placeholders_and_html_stays_text():
    doc = markdown_to_doc('![A tree](tree.png "title") <img src=x onerror=alert(1)> <b>bold?</b>')
    assert text_of(doc) == "[image: A tree] <img src=x onerror=alert(1)> <b>bold?</b>"
    assert all(marks == () for _, marks in runs(doc))


def test_markdown_lists_nest_and_keep_their_start():
    doc = markdown_to_doc("- a\n- b\n  - b1\n  - b2\n- c\n\n3. three\n4. four\n")
    assert_valid(doc)
    assert blocks(doc) == ["bulletList", "orderedList"]
    bullet, ordered = doc["content"]
    assert len(bullet["content"]) == 3
    nested = bullet["content"][1]["content"][1]
    assert nested["type"] == "bulletList" and len(nested["content"]) == 2
    assert ordered["attrs"]["start"] == 3
    assert text_of(ordered) == "threefour"


def test_markdown_a_number_mid_sentence_is_not_a_list():
    doc = markdown_to_doc("It happened in\n1999. That was a year.")
    assert blocks(doc) == ["paragraph"]


def test_markdown_list_item_with_continuation_and_paragraphs():
    doc = markdown_to_doc("1. first line\n   continued\n\n   second para\n2. next\n")
    assert_valid(doc)
    item = doc["content"][0]["content"][0]
    assert [b["type"] for b in item["content"]] == ["paragraph", "paragraph"]
    assert text_of(item["content"][0]) == "first line continued"


def test_markdown_quotes_code_rules_and_tables():
    src = (
        "> quoted\n> more\n\n"
        "```python\nprint('hi')\n  indented\n```\n\n"
        "    indented code\n\n"
        "***\n\n"
        "| n | answer |\n|---|:---:|\n| 1 | 2 \\| 3 |\n"
    )
    doc = markdown_to_doc(src)
    assert_valid(doc)
    assert blocks(doc) == ["blockquote", "codeBlock", "codeBlock", "horizontalRule", "paragraph", "paragraph"]
    fenced, indented = doc["content"][1], doc["content"][2]
    assert fenced["attrs"]["language"] == "python"
    assert text_of(fenced) == "print('hi')\n  indented"
    assert text_of(indented) == "indented code"
    header, row = doc["content"][4], doc["content"][5]
    assert text_of(header) == "n | answer"
    assert ("n", ("bold",)) in runs({"content": [header]})
    assert text_of(row) == "1 | 2 | 3"


def test_markdown_unclosed_fence_runs_to_the_end():
    doc = markdown_to_doc("```\ncode\nmore")
    assert blocks(doc) == ["codeBlock"]
    assert text_of(doc) == "code\nmore"


def test_markdown_escapes():
    doc = markdown_to_doc(r"\*not em\* and \_x\_ and \# and \\")
    assert text_of(doc) == "*not em* and _x_ and # and \\"
    assert all(marks == () for _, marks in runs(doc))


def test_markdown_empty_and_blank():
    for src in ("", "   \n\n  ", None):
        doc = markdown_to_doc(src)  # type: ignore[arg-type]
        assert doc == {"type": "doc", "content": [{"type": "paragraph"}]}


# --- LaTeX ---------------------------------------------------------------------------

STATEMENT = r"""\problemname{Hello World! --- \emph{again}}

\illustration{0.3}{hello.jpg}{Picture by someone}
% a comment: \section{not a heading}
Print ``Hello World!''---no more. It costs \$5 and 50\% of $x_i \le 10^9$.
Caf\'e na\"ive \c{c}a, {\bf bold \it both} plain \textbf{B \emph{BI}} \texttt{a--b}.

\section*{Input}
No input.\\ Next line.
\begin{itemize}
  \item First
  \item Second
  \begin{enumerate}
    \item nested
  \end{enumerate}
  \item[(c)] labelled
\end{itemize}

\section*{Output}
\begin{verbatim}
  int main() { return 0; } % kept
\end{verbatim}
\begin{tabular}{|l|r|}
\hline
$n$ & Points \\ \hline
1 & 10 \\
\end{tabular}
\[ \sum_{i=1}^n a_i \]
\begin{align*}
 a &= b
\end{align*}
\subsection{Sub}
\begin{quote}Quoted \unknownmacro{kept}\end{quote}
"""


def test_latex_problem_name():
    assert latex_problem_name(STATEMENT) == "Hello World! — again"
    assert latex_problem_name(r"\problemname{}") is None
    assert latex_problem_name("no name here") is None
    assert latex_problem_name(r"\problemname{unclosed") is None


def test_latex_statement_structure():
    doc = latex_to_doc(STATEMENT)
    assert_valid(doc)
    assert blocks(doc) == [
        "paragraph",  # the illustration's placeholder
        "paragraph",
        "heading",
        "paragraph",
        "bulletList",
        "heading",
        "codeBlock",
        "paragraph",  # table header row
        "paragraph",  # table row
        "paragraph",  # \[ … \]
        "paragraph",  # align*
        "heading",
        "blockquote",
    ]
    c = doc["content"]
    # The \problemname is the title, not part of the body; comments vanish.
    assert "Hello World! —" not in text_of(c[1])
    assert text_of(c[0]) == "[image: hello.jpg]"
    assert "not a heading" not in text_of(doc)
    assert [text_of(c[i]) for i in (2, 5, 11)] == ["Input", "Output", "Sub"]
    assert [c[i]["attrs"]["level"] for i in (2, 5, 11)] == [2, 2, 3]


def test_latex_text_typography_accents_and_escapes():
    para = latex_to_doc(STATEMENT)["content"][1]
    text = text_of(para)
    assert "Print “Hello World!”—no more." in text
    assert "It costs $5 and 50% of $x_i \\le 10^9$." in text
    assert "Café naïve ça," in text
    assert runs({"content": [para]}) == [
        ("Print “Hello World!”—no more. It costs $5 and 50% of $x_i \\le 10^9$. Café naïve ça, ", ()),
        ("bold ", ("bold",)),
        ("both", ("bold", "italic")),  # \\it inside a {\\bf …} group lasts to its end
        (" plain ", ()),
        ("B ", ("bold",)),
        ("BI", ("bold", "italic")),
        (" ", ()),
        ("a--b", ("code",)),  # typewriter text keeps its dashes
        (".", ()),
    ]


def test_latex_typewriter_text_keeps_its_dashes():
    doc = latex_to_doc(r"Use \texttt{a--b} or \verb|x--y|, not a--b.")
    assert runs(doc) == [
        ("Use ", ()),
        ("a--b", ("code",)),
        (" or ", ()),
        ("x--y", ("code",)),
        (", not a–b.", ()),
    ]


def test_latex_groups_scope_declarations():
    doc = latex_to_doc(r"{\bf bold \it both} plain")
    assert runs(doc) == [("bold ", ("bold",)), ("both", ("bold", "italic")), (" plain", ())]


def test_latex_lists():
    doc = latex_to_doc(STATEMENT)
    bullet = doc["content"][4]
    items = bullet["content"]
    assert [text_of(i["content"][0]) for i in items] == ["First", "Second", "(c) labelled"]
    assert items[1]["content"][1]["type"] == "orderedList"
    assert text_of(items[1]["content"][1]) == "nested"
    assert runs({"content": [items[2]]})[0] == ("(c)", ("bold",))


def test_latex_hard_break_and_paragraphs():
    doc = latex_to_doc("one\\\\ two\n\nthree\n% comment\n\nfour\nstill four\\par five")
    assert [text_of(b) for b in doc["content"]] == ["one\ntwo", "three", "four still four", "five"]


def test_latex_verbatim_is_untouched():
    code = latex_to_doc(STATEMENT)["content"][6]
    assert code["attrs"]["language"] is None
    assert text_of(code) == "  int main() { return 0; } % kept"
    listing = latex_to_doc("\\begin{lstlisting}[language=Python]\nprint(1)  # x\n\\end{lstlisting}")
    assert listing["content"][0]["attrs"]["language"] == "python"
    assert text_of(listing) == "print(1)  # x"


def test_latex_tables_and_display_maths():
    c = latex_to_doc(STATEMENT)["content"]
    assert text_of(c[7]) == "$n$ | Points"
    assert text_of(c[8]) == "1 | 10"
    # Display maths is kept as written, in the dollar form Markdown also uses.
    assert text_of(c[9]) == "$$\\sum_{i=1}^n a_i$$"
    assert text_of(c[10]) == "$$\\begin{align*} a &= b \\end{align*}$$"
    inline = latex_to_doc(r"where \( n \ge 1 \) holds")
    assert text_of(inline) == "where $n \\ge 1$ holds"


def test_latex_links():
    doc = latex_to_doc(r"See \url{https://example.com/a\_b} or \href{https://x.org}{\textbf{here}} or \href{file:///etc}{there}.")
    assert_valid(doc)
    linked = [(n["text"], [m["type"] for m in n["marks"]]) for n in doc["content"][0]["content"] if n.get("marks")]
    assert linked == [("https://example.com/a_b", ["link"]), ("here", ["link", "bold"])]
    assert "there (file:///etc)" in text_of(doc)


def test_latex_unknown_macros_keep_their_last_argument_and_layout_vanishes():
    doc = latex_to_doc(
        r"\textcolor{red}{warm} \foo \vspace{2em}\noindent\label{x}"
        r"\sampletable{sample.in}{sample.out}\mbox{box}\textsc{caps}"
    )
    assert text_of(doc) == "warm boxcaps"


def test_latex_full_document_keeps_only_the_body():
    doc = latex_to_doc(
        "\\documentclass{article}\n\\usepackage{amsmath}\n\\title{x}\n"
        "\\begin{document}\nBody text.\n\\end{document}\nafter"
    )
    assert text_of(doc) == "Body text."


def test_latex_comment_environment_and_stray_ends():
    doc = latex_to_doc("a \\begin{comment} hidden \\end{comment} b \\end{itemize} \\item c")
    assert_valid(doc)
    assert "hidden" not in text_of(doc)
    # A stray \\end is ignored; a stray \\item just starts a new paragraph.
    assert text_of(doc) == "a b\nc"


def test_latex_includegraphics_and_figure():
    doc = latex_to_doc(
        "\\begin{figure}[h]\\centering\\includegraphics[width=5cm]{pic.png}"
        "\\caption{A caption}\\end{figure}"
    )
    assert text_of(doc) == "[image: pic.png]A caption"


# --- doc → Markdown ------------------------------------------------------------------


def test_export_escapes_text_but_not_maths():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "a*b_c [x] `q` <tag> and $x_1*y$ ~~"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "# not a heading"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "1. not a list"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "- nor this"}]},
    ]}
    md = doc_to_markdown(doc)
    assert md == (
        "a\\*b\\_c \\[x\\] \\`q\\` \\<tag> and $x_1*y$ \\~\\~\n\n"
        "\\# not a heading\n\n"
        "1\\. not a list\n\n"
        "\\- nor this\n"
    )
    assert markdown_to_doc(md) == doc


def test_export_code_spans_and_fences_outgrow_their_content():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "a ` tick", "marks": [{"type": "code"}]}]},
        {"type": "codeBlock", "attrs": {"language": "md"}, "content": [{"type": "text", "text": "```\nfence\n```"}]},
    ]}
    md = doc_to_markdown(doc)
    assert "``a ` tick``" in md
    assert "````md\n```\nfence\n```\n````" in md
    assert markdown_to_doc(md) == doc


def test_export_keeps_spaces_outside_emphasis():
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "x "},
        {"type": "text", "text": "bold ", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "y"},
    ]}]}
    assert doc_to_markdown(doc) == "x **bold** y\n"


def test_export_underline_has_no_markdown_and_drops_quietly():
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "under", "marks": [{"type": "underline"}]},
    ]}]}
    assert doc_to_markdown(doc) == "under\n"


def test_export_tolerates_junk():
    assert doc_to_markdown(None) == ""
    assert doc_to_markdown({"type": "doc"}) == ""
    assert doc_to_markdown({"type": "doc", "content": [{"type": "paragraph"}]}) == ""
    weird = {"type": "doc", "content": [
        "str", 5, {"type": "image", "content": [{"type": "text", "text": "alt"}]},
        {"type": "heading", "attrs": {"level": "x"}, "content": [{"type": "text", "text": "H"}]},
        {"type": "orderedList", "attrs": {"start": None}, "content": [{"type": "listItem"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "l", "marks": [{"type": "link"}]}]},
    ]}
    md = doc_to_markdown(weird)
    assert "alt" in md and "## H" in md and "1. " in md


# --- round trips ---------------------------------------------------------------------

ROUND_TRIP_SOURCES = [
    ("md", "## Input\n\nA **bold *both*** `x` [l](https://e.com) $a_i$.\n\n- one\n- two\n  1. n\n\n> q\n\n---\n"),
    ("md", "```c\nint x;\n```\n\nline  \nbreak\n\n3. three\n4. four\n"),
    ("tex", STATEMENT),
]


@pytest.mark.parametrize("kind,src", ROUND_TRIP_SOURCES)
def test_export_then_import_is_identity(kind, src):
    doc = markdown_to_doc(src) if kind == "md" else latex_to_doc(src)
    assert_valid(doc)
    assert markdown_to_doc(doc_to_markdown(doc)) == doc


# --- robustness ------------------------------------------------------------------------

ALPHABET_MD = list("*_`$#>-+|[]()!<>~\\ \n\n1. abc") + ["**", "```", "$$", "    ", "- ", "1. ", "> ", "|---|"]
ALPHABET_TEX = list("{}\\$%&~#_^ \n\nab") + [
    r"\begin{itemize}", r"\end{itemize}", r"\item", r"\section{", r"\textbf{", r"\\", r"\[", r"\]",
    r"\(", r"\)", r"\begin{tabular}{ll}", r"\end{tabular}", r"\begin{verbatim}", r"\end{verbatim}",
    r"\'", r"\verb|", r"\begin{quote}", r"\end{quote}", r"\href{", r"\foo{", "--", "``",
]


@pytest.mark.parametrize("seed", range(40))
def test_random_input_never_raises_and_stays_valid(seed):
    rng = random.Random(seed)
    for alphabet, convert in ((ALPHABET_MD, markdown_to_doc), (ALPHABET_TEX, latex_to_doc)):
        src = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 400)))
        doc = convert(src)
        assert_valid(doc)
        md = doc_to_markdown(doc)
        assert isinstance(md, str)
        assert_valid(markdown_to_doc(md))


@pytest.mark.parametrize(
    "convert,src",
    [
        (markdown_to_doc, "`" * 19000),
        (markdown_to_doc, "*a " * 6600),
        (markdown_to_doc, "[" * 19000),
        (markdown_to_doc, ("*a " * 1000 + "\n\n") * 100),
        (markdown_to_doc, "> " * 5000 + "x"),
        (markdown_to_doc, "".join("  " * k + "- x\n" for k in range(2000))),
        (latex_to_doc, "{" * 400_000),
        (latex_to_doc, "\\(" * 200_000),
        (latex_to_doc, "\\begin{tabular}" * 30_000),
        (latex_to_doc, "\\begin{itemize}" * 30_000),
        (latex_to_doc, "\\textbf{" * 3000 + "x" + "}" * 3000),
    ],
    ids=[
        "md-backticks", "md-unclosed-em", "md-brackets", "md-many-paragraphs", "md-deep-quotes",
        "md-deep-lists", "tex-unclosed-braces", "tex-unclosed-parens", "tex-unclosed-tables",
        "tex-unclosed-lists", "tex-deep-groups",
    ],
)
def test_hostile_statements_finish_quickly(convert, src):
    started = time.perf_counter()
    doc = convert(src)
    assert time.perf_counter() - started < 5
    assert_valid(doc)


# Single lines that once sent a regex quadratic — and the regex engine holds the
# GIL, so a worker thread doesn't spare the event loop. 60K characters is ~2 s
# quadratic here (minutes at the 1 MB statement cap); linear, milliseconds.
HOSTILE_LINES = {
    "fence-tail": "```" + "a" * 60_000 + "`",
    "tilde-fence-tail": "~~~" + "a" * 60_000 + "`",
    "heading-spaces": "# a" + " " * 60_000 + "x",
    "heading-hashes": "# a " + "#" * 60_000 + "x",
    "space-run": "a" + " " * 60_000 + "a",
    "space-run-newline": "a" + " " * 60_000 + "\nb",
    # Paragraphs under the inline cap are parsed: ~0.6 s each, quadratic.
    "space-run-inline": ("a" + " " * 19_000 + "a\n\n") * 3,
    "tab-run": "a" + "\t" * 60_000 + "a",
    "table-rule": "|" + "-|" * 30_000 + "x",
    "hr-spaced": "- " * 30_000 + "x",
    "emphasis-openers": "*a " * 20_000,
    "strong-openers": "**a " * 15_000,
    "dollars": "$a " * 20_000,
    "table-separator-spaces": "a | b\n|-" + " " * 60_000 + "x",
    # Under the inline cap, so each paragraph is parsed (~0.3 s each, unanchored).
    "link-openers": ("[x](" * 4_900 + "\n\n") * 10,
    "nested-link-openers": ("[[" * 9_000 + "\n\n") * 5,
    "image-openers": ("![" * 9_000 + "\n\n") * 5,
}


@pytest.mark.parametrize("line", list(HOSTILE_LINES.values()), ids=list(HOSTILE_LINES))
def test_hostile_markdown_lines_are_linear(line):
    started = time.perf_counter()
    doc = markdown_to_doc(line)
    md = doc_to_markdown(doc)
    assert time.perf_counter() - started < 1
    assert_valid(doc) and isinstance(md, str)


def test_long_display_maths_survives_export():
    maths = "$$" + "x_{1} \\alpha * [y] " * 300 + "$$"  # well past any span bound
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": maths}]}]}
    md = doc_to_markdown(doc)
    assert md == maths + "\n"  # unescaped: other judges render it as TeX
    assert markdown_to_doc(md) == doc


def test_latex_verb_scans_are_budgeted():
    # Every \verb with a delimiter that never recurs scans to the end.
    started = time.perf_counter()
    # (1 MB, the statement cap: ~3 s of scanning unbudgeted, nothing budgeted.)
    doc = latex_to_doc("".join("\\verb" + chr(0x10000 + i) for i in range(170_000)))
    assert time.perf_counter() - started < 1.5
    assert_valid(doc)


def test_latex_option_scans_are_budgeted():
    started = time.perf_counter()
    doc = latex_to_doc("\\item[" * 200_000)
    assert time.perf_counter() - started < 5
    assert_valid(doc)


def test_heading_closing_sequences():
    cases = {"# Title #": "Title", "# Title ##  ": "Title", "# a#": "a#", "# #": None, "#": None,
             "## Sum # of #": "Sum # of", "# \\#": "#"}
    for src, expected in cases.items():
        doc = markdown_to_doc(src)
        if expected is None:
            assert blocks(doc) == ["paragraph"] and not doc["content"][0].get("content"), src
        else:
            assert blocks(doc) == ["heading"] and text_of(doc) == expected, src


def test_soft_breaks_keep_their_spacing():
    doc = markdown_to_doc("a \n \n")  # a trailing whitespace line ends the paragraph
    assert text_of(doc) == "a"
    assert text_of(markdown_to_doc("one  \t\n\t two\nthree")) == "one two three"
