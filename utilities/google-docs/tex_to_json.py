import re
import json
from pathlib import Path

# --- Regex patterns ---
section_re = re.compile(r"\\section(\*)?\{(.+?)\}")
subsection_re = re.compile(r"\\subsection(\*)?\{(.+?)\}")
subsubsection_re = re.compile(r"\\subsubsection(\*)?\{(.+?)\}")
label_re = re.compile(r"\\label\{(.+?)\}")
begin_enum = re.compile(r"\\begin\{enumerate\}")
end_enum = re.compile(r"\\end\{enumerate\}")
item_re = re.compile(r"\\item\s*(.*)")
signatureline_re = re.compile(r"\\signatureline\{(.+?)\}")

# Lines that should be skipped entirely (preamble / layout commands)
SKIP_PREFIXES = (
    "\\documentclass",
    "\\usepackage",
    "\\newcommand",
    "\\setupcfesheaders",
    "\\newpage",
    "\\noindent\\rule",
    "%",
)
SKIP_EXACT = {"\\newpage", "\\vspace{1em}", "\\vspace{0.5em}"}
VSPACE_RE = re.compile(r"\\vspace\{[^}]*\}")


def clean_text(text: str) -> str:
    """Resolve inline LaTeX markup to plain text."""
    # \ref{label} → label
    text = re.sub(r"\\ref\{([^}]+)\}", r"\1", text)
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
    # e.g.\ → e.g. (escaped space after abbreviation)
    text = re.sub(r"e\.g\.\\ ", "e.g. ", text)
    # Remove remaining stray backslash-space sequences
    text = re.sub(r"\\ ", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    return text.strip()


def find_label(lines: list[str], start: int) -> tuple[str | None, int]:
    """
    Scan forward from `start` (skipping blank lines) to find a \\label{}.
    Returns (label_string_or_None, new_index).
    """
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


def parse_latex(lines: list[str]) -> list:
    root: list = []
    stack: list = []
    current: list = root

    in_document = False
    in_center_block = False
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

        # --- Center block (title) ---
        if line == "\\begin{center}":
            in_center_block = True
            i += 1
            continue
        if line == "\\end{center}":
            in_center_block = False
            i += 1
            continue
        if in_center_block:
            i += 1
            continue

        # --- Skip preamble / layout lines ---
        if any(line.startswith(p) for p in SKIP_PREFIXES):
            i += 1
            continue
        if VSPACE_RE.fullmatch(line) or line in SKIP_EXACT:
            i += 1
            continue

        # --- Blank line: flush paragraph buffer ---
        if not line:
            flush_paragraph()
            i += 1
            continue

        # --- Sections ---
        m = section_re.match(line)
        if m:
            flush_paragraph()
            starred = m.group(1) == "*"
            title = clean_text(m.group(2))
            label, i = find_label(lines, i + 1)
            node = {
                "type": "section",
                "title": title,
                "starred": starred,
                "label": label,
                "children": [],
            }
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
            node = {
                "type": "subsection",
                "title": title,
                "starred": starred,
                "label": label,
                "children": [],
            }
            while stack and stack[-1]["type"] not in ("section",):
                stack.pop()
            if stack:
                stack[-1]["children"].append(node)
            else:
                root.append(node)
            stack.append(node)
            current = node["children"]
            continue

        m = subsubsection_re.match(line)
        if m:
            flush_paragraph()
            starred = m.group(1) == "*"
            title = clean_text(m.group(2))
            label, i = find_label(lines, i + 1)
            node = {
                "type": "subsubsection",
                "title": title,
                "starred": starred,
                "label": label,
                "children": [],
            }
            while stack and stack[-1]["type"] not in ("subsection", "section"):
                stack.pop()
            if stack:
                stack[-1]["children"].append(node)
            else:
                root.append(node)
            stack.append(node)
            current = node["children"]
            continue

        # --- Enumerate ---
        if begin_enum.match(line):
            flush_paragraph()
            node = {"type": "enumerate", "items": []}
            current.append(node)
            stack.append(node)
            current = node["items"]
            i += 1
            continue

        if end_enum.match(line):
            flush_paragraph()
            # Pop any trailing item node(s), then pop the enumerate itself
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
            # Pop any previous item nodes off the stack to get back to the
            # enclosing enumerate, so sibling \items are peers, not children.
            while stack and stack[-1]["type"] == "item":
                stack.pop()
            # Now stack[-1] should be the enumerate node; its items list is current.
            if stack and stack[-1]["type"] == "enumerate":
                current = stack[-1]["items"]
            text = clean_text(m.group(1))
            item_node = {"type": "item", "text": text, "children": []}
            current.append(item_node)
            # Push item onto stack so nested \begin{enumerate} goes into children
            stack.append(item_node)
            current = item_node["children"]
            i += 1
            continue

        # --- Signature line ---
        m = signatureline_re.match(line)
        if m:
            flush_paragraph()
            label = clean_text(m.group(1))
            current.append({"type": "signature", "label": label})
            i += 1
            continue

        # --- Plain text (paragraph continuation) ---
        paragraph_buffer.append(clean_text(line))
        i += 1

    return root


# --- Main ---
HERE = Path(__file__).parent
INPUT_FILE = HERE / "../../documents/agreements/activity-financial-agreement.tex"
OUTPUT_FILE = HERE / "activity-financial-agreement.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

parsed = parse_latex(lines)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(parsed, f, indent=2, ensure_ascii=False)

print(f"Parsed {len(parsed)} top-level nodes → {OUTPUT_FILE}")
