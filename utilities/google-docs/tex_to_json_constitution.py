"""
tex_to_json_constitution.py — Parse the English LaTeX constitution into JSON.

Reads documents/constitution/main.tex, resolves all \\input{} includes, and
produces constitution.json in the same directory as this script.

Handles:
  - \\section / \\subsection / \\subsubsection (starred variants too)
  - \\label
  - \\begin{enumerate} / \\end{enumerate} (nested)
  - \\item
  - \\begin{tblr} / \\end{tblr}  → "table" node with rows of cells
  - \\textbf{...} inline → plain bold text (kept as plain text in output)
  - Plain paragraph text
"""

import re
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
section_re      = re.compile(r"\\section(\*)?\{(.+?)\}")
subsection_re   = re.compile(r"\\subsection(\*)?\{(.+?)\}")
subsubsection_re = re.compile(r"\\subsubsection(\*)?\{(.+?)\}")
label_re        = re.compile(r"\\label\{(.+?)\}")
begin_enum_re   = re.compile(r"\\begin\{enumerate\}")
end_enum_re     = re.compile(r"\\end\{enumerate\}")
item_re         = re.compile(r"\\item\s*(.*)")
begin_tblr_re   = re.compile(r"\\begin\{tblr\}.*")
end_tblr_re     = re.compile(r"\\end\{tblr\}")
input_re        = re.compile(r"\\input\{([^}]+)\}")
VSPACE_RE       = re.compile(r"\\vspace\{[^}]*\}")

SKIP_PREFIXES = (
    "\\documentclass",
    "\\usepackage",
    "\\newcommand",
    "\\setupcfesheaders",
    "\\tableofcontents",
    "\\newpage",
    "\\noindent\\rule",
    "\\thispagestyle",
    "%",
    "\\begin{tikzpicture}",
    "\\end{tikzpicture}",
    "\\node[",
    "\\node ",
    "}",
    ");",
    "\\begin{minipage}",
    "\\end{minipage}",
    "\\centering",
    "{\\fontsize",
    "\\color{",
    "\\textbf{Revision",
)
SKIP_EXACT = {"\\newpage", "\\vspace{1em}", "\\vspace{0.5em}"}


def clean_text(text: str) -> str:
    """Resolve inline LaTeX markup to plain text."""
    # \textbf{...} → contents
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    # \textit{...} / \emph{...} → contents
    text = re.sub(r"\\(?:textit|emph)\{([^}]*)\}", r"\1", text)
    # \ref{label} → label
    text = re.sub(r"\\ref\{([^}]+)\}", r"\1", text)
    # LaTeX quotes `` and '' → "
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    # \$ → $
    text = text.replace(r"\$", "$")
    # \& → &
    text = text.replace(r"\&", "&")
    # \vspace{...} → ""
    text = VSPACE_RE.sub("", text)
    # \noindent → ""
    text = text.replace(r"\noindent", "")
    # \\ (line break) → " "
    text = text.replace(r"\\", " ")
    # ~ and "\ " (non-breaking spaces) → regular space
    text = text.replace("~", " ")
    text = text.replace(r"\ ", " ")
    # e.g.\ → e.g.
    text = re.sub(r"e\.g\.\\ ", "e.g. ", text)
    # Trailing LaTeX comment
    text = re.sub(r"\s*%.*$", "", text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    return text.strip()


def find_label(lines: list[str], start: int) -> tuple[str | None, int]:
    j = start
    while j < len(lines):
        stripped = lines[j].strip()
        if not stripped:
            j += 1
            continue
        m = label_re.match(stripped)
        if m:
            return m.group(1), j + 1
        break
    return None, start


def resolve_inputs(main_tex: Path) -> list[str]:
    """
    Read main.tex and inline every \\input{} reference.
    Returns a flat list of lines.
    """
    base = main_tex.parent
    result: list[str] = []

    def _load(path: Path):
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                m = input_re.match(line.strip())
                if m:
                    ref = m.group(1)
                    if not ref.endswith(".tex"):
                        ref += ".tex"
                    target = (path.parent / ref).resolve()
                    _load(target)
                else:
                    result.append(line)

    _load(main_tex)
    return result


# ---------------------------------------------------------------------------
# tblr parser — produces a "table" node
# ---------------------------------------------------------------------------

def parse_tblr_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """
    Consume lines from start until \\end{tblr}.
    Each non-empty line is a table row; cells are split on ' & ' and
    terminated by ' \\\\'.
    Returns (rows, next_index).
    """
    rows: list[list[str]] = []
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if end_tblr_re.match(line):
            return rows, i + 1
        if line:
            # Strip trailing \\ and optional trailing spaces
            row_text = re.sub(r"\s*\\\\$", "", line).strip()
            if row_text:
                cells = [clean_text(c.strip()) for c in row_text.split("&")]
                rows.append(cells)
        i += 1
    return rows, i


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_latex(lines: list[str]) -> list:
    root: list = []
    stack: list = []
    current: list = root

    in_document = False
    in_skip_block = False  # for tikzpicture / minipage / center
    paragraph_buffer: list[str] = []

    def flush_paragraph():
        nonlocal paragraph_buffer
        text = " ".join(paragraph_buffer).strip()
        if text:
            current.append({"type": "paragraph", "text": text})
        paragraph_buffer = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # --- Document bounds ---
        if line == "\\begin{document}":
            in_document = True
            i += 1
            continue
        if line == "\\end{document}":
            flush_paragraph()
            in_document = False
            i += 1
            continue
        if not in_document:
            i += 1
            continue

        # --- Skip blocks (tikzpicture, center, minipage) ---
        if line in ("\\begin{tikzpicture}", "\\begin{center}", "\\begin{minipage}") or \
                line.startswith("\\begin{tikzpicture}") or \
                line.startswith("\\begin{minipage}"):
            in_skip_block = True
            i += 1
            continue
        if line in ("\\end{tikzpicture}", "\\end{center}", "\\end{minipage}"):
            in_skip_block = False
            i += 1
            continue
        if in_skip_block:
            i += 1
            continue

        # --- Skip preamble / layout lines ---
        if any(line.startswith(p) for p in SKIP_PREFIXES):
            i += 1
            continue
        if VSPACE_RE.fullmatch(line) or line in SKIP_EXACT:
            i += 1
            continue

        # --- Blank line ---
        if not line:
            flush_paragraph()
            i += 1
            continue

        # --- tblr table ---
        if begin_tblr_re.match(line):
            flush_paragraph()
            rows, i = parse_tblr_rows(lines, i + 1)
            current.append({"type": "table", "rows": rows})
            continue

        # --- Sections ---
        m = section_re.match(line)
        if m:
            flush_paragraph()
            starred = m.group(1) == "*"
            title = clean_text(m.group(2))
            label, i = find_label(lines, i + 1)
            node = {"type": "section", "title": title, "starred": starred,
                    "label": label, "children": []}
            root.append(node)
            stack = [node]
            current = node["children"]
            continue

        m = subsection_re.match(line)
        if m:
            flush_paragraph()
            starred = m.group(1) == "*"
            title = clean_text(m.group(2))
            label, i = find_label(lines, i + 1)
            node = {"type": "subsection", "title": title, "starred": starred,
                    "label": label, "children": []}
            while stack and stack[-1]["type"] not in ("section",):
                stack.pop()
            (stack[-1]["children"] if stack else root).append(node)
            stack.append(node)
            current = node["children"]
            continue

        m = subsubsection_re.match(line)
        if m:
            flush_paragraph()
            starred = m.group(1) == "*"
            title = clean_text(m.group(2))
            label, i = find_label(lines, i + 1)
            node = {"type": "subsubsection", "title": title, "starred": starred,
                    "label": label, "children": []}
            while stack and stack[-1]["type"] not in ("subsection", "section"):
                stack.pop()
            (stack[-1]["children"] if stack else root).append(node)
            stack.append(node)
            current = node["children"]
            continue

        # --- Enumerate ---
        if begin_enum_re.match(line):
            flush_paragraph()
            node = {"type": "enumerate", "items": []}
            current.append(node)
            stack.append(node)
            current = node["items"]
            i += 1
            continue

        if end_enum_re.match(line):
            flush_paragraph()
            while stack and stack[-1]["type"] == "item":
                stack.pop()
            if stack and stack[-1]["type"] == "enumerate":
                stack.pop()
            if stack:
                parent = stack[-1]
                if parent["type"] == "enumerate":
                    current = parent["items"]
                elif parent["type"] == "item":
                    current = parent["children"]
                else:
                    current = parent.get("children", root)
            else:
                current = root
            i += 1
            continue

        # --- Items ---
        m = item_re.match(line)
        if m:
            flush_paragraph()
            while stack and stack[-1]["type"] == "item":
                stack.pop()
            if stack and stack[-1]["type"] == "enumerate":
                current = stack[-1]["items"]
            text = clean_text(m.group(1))
            item_node = {"type": "item", "text": text, "children": []}
            current.append(item_node)
            stack.append(item_node)
            current = item_node["children"]
            i += 1
            continue

        # --- Plain text ---
        paragraph_buffer.append(clean_text(line))
        i += 1

    return root


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
MAIN_TEX = HERE / "../../documents/constitution/main.tex"
OUTPUT_FILE = HERE / "constitution.json"

lines = resolve_inputs(MAIN_TEX.resolve())
parsed = parse_latex(lines)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(parsed, f, indent=2, ensure_ascii=False)

print(f"Parsed {len(parsed)} top-level nodes → {OUTPUT_FILE}")
