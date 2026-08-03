"""
tex_to_json.py — Parse any CFES LaTeX document into JSON.

Usage:
    python tex_to_json.py <main.tex> <output.json>

Handles:
  - \\section / \\subsection / \\subsubsection (starred variants too)
  - \\label
  - \\begin{enumerate} / \\begin{itemize} and their \\end{} variants (nested)
  - \\item
  - \\begin{tblr} / \\end{tblr}  → "table" node with rows of cells
  - \\textbf{...} / \\textit{...} / \\emph{...} / \\texttt{...} inline → plain text
  - \\paragraph{...} → "paragraph_heading" node (renders as Heading 4 in Google Docs)
  - \\input{} includes resolved recursively
  - Plain paragraph text
"""

import re
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
section_re       = re.compile(r"\\section(\*)?\{(.+?)\}")
subsection_re    = re.compile(r"\\subsection(\*)?\{(.+?)\}")
subsubsection_re = re.compile(r"\\subsubsection(\*)?\{(.+?)\}")
paragraph_re     = re.compile(r"\\paragraph\{(.+?)\}")
label_re         = re.compile(r"\\label\{(.+?)\}")
begin_enum_re    = re.compile(r"\\begin\{(?:enumerate|itemize)\}")
end_enum_re      = re.compile(r"\\end\{(?:enumerate|itemize)\}")
item_re          = re.compile(r"\\item\s*(.*)")
begin_tblr_re    = re.compile(r"\\begin\{(?:tblr|longtblr)\}.*")
end_tblr_re      = re.compile(r"\\end\{(?:tblr|longtblr)\}")
input_re         = re.compile(r"\\input\{([^}]+)\}")
VSPACE_RE        = re.compile(r"\\vspace\{[^}]*\}")

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


def build_label_map(lines):
    """Build a mapping of label → section title by scanning for heading+label pairs."""
    label_map = {}
    heading_patterns = [
        re.compile(r"\\(?:section|subsection|subsubsection|paragraph)(?:\*)?\{(.+?)\}"),
    ]
    last_title = None
    for line in lines:
        s = line.strip()
        # Strip inline \label from the line before matching title
        s_no_label = re.sub(r"\\label\{[^}]*\}", "", s).strip()
        for pat in heading_patterns:
            m = pat.search(s_no_label)
            if m:
                last_title = m.group(1).strip()
                break
        m = label_re.search(s)
        if m and last_title is not None:
            label_map[m.group(1)] = last_title
            last_title = None
    return label_map


_label_map = {}


def clean_text(text: str) -> str:
    """Resolve inline LaTeX markup to plain text."""
    # DOTALL so these match across joined continuation lines
    text = re.sub(r"\\textbf\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\(?:textit|emph)\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\texttt\{(.*?)\}", r"\1", text, flags=re.DOTALL)
    # Resolve \nameref{label} → title from label map, or prettify the label slug
    def resolve_nameref(m):
        label = m.group(1)
        if label in _label_map:
            return clean_text(_label_map[label])
        # Fallback: prettify slug (e.g. "financial-deliverables" → "Financial Deliverables")
        return label.replace("-", " ").title()
    text = re.sub(r"\\nameref\{([^}]+)\}", resolve_nameref, text)
    # Strip "Section~\ref{...}" and bare "\ref{...}" — section numbers are meaningless in Docs
    text = re.sub(r"\(?\s*Section[~\s]*\\ref\{[^}]+\}\s*\)?", "", text)
    text = re.sub(r"\\ref\{([^}]+)\}", r"\1", text)
    text = text.replace("``", "“").replace("''", "”")
    text = re.sub(r"(?<!\\)\s*%.*$", "", text)  # strip LaTeX comments (unescaped % only)
    text = text.replace(r"\textquotesingle{}", "'")
    text = text.replace(r"\textquotesingle", "'")
    text = text.replace(r"\%", "%")
    text = text.replace(r"\_", "_")
    text = text.replace(r"\$", "$")
    text = text.replace(r"\&", "&")
    text = text.replace(r"\{", "{")
    text = text.replace(r"\}", "}")
    # TeX ligatures for dashes. Longest first, so "---" is not eaten as "--"
    # plus a stray hyphen. Without these, "Atlantic -- Provinces of ..." reaches
    # the Doc as a literal double hyphen.
    text = text.replace("---", "—")  # em dash
    text = text.replace("--", "–")   # en dash
    text = VSPACE_RE.sub("", text)
    text = text.replace(r"\noindent", "")
    text = text.replace(r"\\", " ")
    text = text.replace("~", " ")
    text = text.replace(r"\ ", " ")
    text = re.sub(r"e\.g\.\\ ", "e.g. ", text)
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
    """Read main.tex and inline every \\input{} reference recursively."""
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


def skip_tblr_spec(lines: list[str], begin_idx: int) -> int:
    """Skip past the \\begin{tblr}[...]{...} spec preamble (may span many lines).

    Returns the index of the first line after the closing brace of the column
    spec block. Handles both single-line and multi-line begin headers.
    """
    # Count braces/brackets from the begin line onward until the spec {...} closes.
    depth_brace = 0
    depth_brack = 0
    seen_spec = False
    i = begin_idx
    while i < len(lines):
        line = lines[i]
        # On the first line, drop everything up to and including \begin{...}
        if i == begin_idx:
            line = re.sub(r".*\\begin\{(?:tblr|longtblr)\}", "", line)
        for ch in line:
            if ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
            elif ch == "{":
                depth_brace += 1
                seen_spec = True
            elif ch == "}":
                depth_brace -= 1
                if seen_spec and depth_brace == 0 and depth_brack == 0:
                    return i + 1
        i += 1
    return i


def parse_tblr_rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    i = start
    buffer = ""
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if end_tblr_re.match(line):
            return rows, i + 1
        # Skip horizontal rules and other formatting-only commands
        if line in ("\\hline", "\\toprule", "\\midrule", "\\bottomrule") or \
                line.startswith("\\cline") or line.startswith("\\hline"):
            i += 1
            continue
        if line:
            buffer = (buffer + " " + line).strip() if buffer else line
            # A row terminates at \\ ; accumulate continuation lines until then
            if buffer.rstrip().endswith("\\\\"):
                row_text = re.sub(r"\s*\\\\$", "", buffer.strip()).strip()
                if row_text:
                    cells = [clean_text(c.strip()) for c in row_text.split("&")]
                    rows.append(cells)
                buffer = ""
        i += 1
    # Flush any trailing row without a terminating \\
    if buffer.strip():
        row_text = re.sub(r"\s*\\\\$", "", buffer.strip()).strip()
        if row_text:
            rows.append([clean_text(c.strip()) for c in row_text.split("&")])
    return rows, i


def parse_latex(lines: list[str]) -> list:
    root: list = []
    stack: list = []
    current: list = root

    in_document = False
    in_skip_block = False
    paragraph_buffer: list[str] = []

    def flush_paragraph():
        nonlocal paragraph_buffer
        # Join raw lines first so multi-line \emph{...} spans are cleaned as one unit
        raw = " ".join(paragraph_buffer).strip()
        paragraph_buffer = []
        text = clean_text(raw)
        if text:
            current.append({"type": "paragraph", "text": text})

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # --- Join continuation lines for multi-line \section / \subsection / \subsubsection / \paragraph ---
        # e.g. \subsection{Tasks and\n Responsibilities} written across two lines.
        if any(line.startswith(cmd) for cmd in (r"\section", r"\subsection", r"\subsubsection", r"\paragraph")):
            while line.count("{") > line.count("}") and i + 1 < len(lines):
                i += 1
                line = line + " " + lines[i].strip()

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
            row_start = skip_tblr_spec(lines, i)
            rows, i = parse_tblr_rows(lines, row_start)
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

        m = paragraph_re.match(re.sub(r"\\label\{[^}]*\}", "", line))
        if m:
            flush_paragraph()
            title = clean_text(m.group(1))
            node = {"type": "paragraph_heading", "title": title, "children": []}
            while stack and stack[-1]["type"] not in ("paragraph_heading", "subsubsection", "subsection", "section"):
                stack.pop()
            if stack and stack[-1]["type"] == "paragraph_heading":
                stack.pop()
            (stack[-1]["children"] if stack else root).append(node)
            stack.append(node)
            current = node["children"]
            i += 1
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

        # --- Plain text (accumulate raw; clean on flush so multi-line \emph spans work) ---
        paragraph_buffer.append(line)
        i += 1

    return root


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python tex_to_json_constitution.py <main.tex> <output.json>")
        sys.exit(1)

    main_tex = Path(sys.argv[1]).resolve()
    output_file = Path(sys.argv[2])

    lines = resolve_inputs(main_tex)
    globals()["_label_map"] = build_label_map(lines)
    parsed = parse_latex(lines)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    print(f"Parsed {len(parsed)} top-level nodes → {output_file}")
