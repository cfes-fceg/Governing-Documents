"""
normalize-headings.py — Post-process .tex files to enforce heading conventions:

1. Join \\section / \\subsection / \\subsubsection titles that span multiple lines
   onto a single line.
2. Ensure \\label immediately following a heading is on the next line (not on
   the same line as the heading).

Usage:
    python3 normalize-headings.py <file.tex> [<file.tex> ...]
"""

import re
import sys
from pathlib import Path

HEADING_START = re.compile(r"^(\\(?:sub)*section\*?)\{")


def normalize(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n")

        # --- Step 1: join multi-line heading titles ---
        if HEADING_START.match(stripped.lstrip()):
            indent = len(stripped) - len(stripped.lstrip())
            joined = stripped.lstrip()
            while joined.count("{") > joined.count("}") and i + 1 < len(lines):
                i += 1
                joined = joined.rstrip() + " " + lines[i].strip()
            stripped = " " * indent + joined

        # --- Step 2: split \label off the same line as a heading ---
        # e.g. \subsection{Foo}\label{bar}  →  \subsection{Foo}\n\label{bar}
        if HEADING_START.match(stripped.lstrip()):
            # Find a \label{...} that follows the closing } of the heading
            m = re.match(
                r"^(\s*\\(?:sub)*section\*?\{[^}]*\})(\\label\{[^}]*\})(.*)$",
                stripped,
            )
            if m:
                heading_part = m.group(1)
                label_part   = m.group(2)
                remainder    = m.group(3).strip()
                out.append(heading_part + "\n")
                out.append(label_part + "\n")
                if remainder:
                    out.append(remainder + "\n")
                i += 1
                continue

        out.append(stripped + "\n")
        i += 1

    return out


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    result = normalize(lines)
    new_text = "".join(result)
    if new_text != original:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 normalize-headings.py <file.tex> [...]")
        sys.exit(1)

    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"Warning: {p} not found, skipping.")
            continue
        changed = process_file(p)
        if changed:
            print(f"  normalized: {p}")
