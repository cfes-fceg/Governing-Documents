"""
json_to_docs.py — Write any CFES JSON document to a Google Doc.

Usage:
    python json_to_docs.py <DOCUMENT_ID> <input.json>
    # or set GOOGLE_DOC_ID environment variable:
    GOOGLE_DOC_ID=<id> python json_to_docs.py <input.json>

Prerequisites:
    - credentials.json (Google service-account key) in this directory
    - The service account must have editor access to the document
    - The document will be cleared automatically before writing
    - pip install -r requirements.txt

Styling:
    - Headings numbered manually: 1, 1.1, 1.1.1  styled as HEADING_1/2/3
    - Enumerate items use manual labels with indentation:
        level 1 → 1.  2.  3.
        level 2 → (a) (b) (c)
        level 3 → i.  ii. iii.
    - All text is set in Nunito font
"""

import json
import os
import sys
from pathlib import Path

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/documents"]
HERE = Path(__file__).parent
SERVICE_ACCOUNT_FILE = HERE / "credentials.json"

FONT = "Nunito"
HEADING_SIZES = {1: 16, 2: 13, 3: 11, 4: 10}
BODY_SIZE = 10
INDENT_STEP = 18  # pt per nesting level


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_args() -> tuple[str, Path]:
    args = sys.argv[1:]
    doc_id = os.environ.get("GOOGLE_DOC_ID", "")

    if len(args) == 2:
        doc_id, json_path = args[0], Path(args[1])
    elif len(args) == 1 and doc_id:
        json_path = Path(args[0])
    else:
        print(
            "Error: missing arguments.\n"
            "  Usage:  python json_to_docs.py <DOCUMENT_ID> <input.json>\n"
            "     or:  GOOGLE_DOC_ID=<id> python json_to_docs.py <input.json>"
        )
        sys.exit(1)

    if not doc_id:
        print("Error: no document ID supplied.")
        sys.exit(1)

    return doc_id, json_path


# ---------------------------------------------------------------------------
# UTF-16 length (Docs API counts indices in UTF-16 code units)
# ---------------------------------------------------------------------------

def utf16len(text: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


# ---------------------------------------------------------------------------
# Low-level request builders
# ---------------------------------------------------------------------------

def req_insert(index: int, text: str) -> dict:
    return {"insertText": {"location": {"index": index}, "text": text}}


def req_paragraph_style(start: int, end: int, named_style: str) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": named_style},
            "fields": "namedStyleType",
        }
    }


def req_text_style(start: int, end: int, bold: bool = False,
                   font: str = FONT, size_pt: int = BODY_SIZE) -> dict:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {
                "bold": bold,
                "weightedFontFamily": {"fontFamily": font},
                "fontSize": {"magnitude": size_pt, "unit": "PT"},
            },
            "fields": "bold,weightedFontFamily,fontSize",
        }
    }


def req_indent(start: int, end: int, indent_start_pt: float, indent_first_line_pt: float = None) -> dict:
    """Set paragraph indentation.
    indent_start_pt      — left margin for wrapped lines (indentStart)
    indent_first_line_pt — absolute left margin for the first line; defaults to indent_start_pt
    """
    if indent_first_line_pt is None:
        indent_first_line_pt = indent_start_pt
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentFirstLine": {"magnitude": indent_first_line_pt, "unit": "PT"},
                "indentStart": {"magnitude": indent_start_pt, "unit": "PT"},
            },
            "fields": "indentFirstLine,indentStart",
        }
    }


def req_space_before(start: int, end: int, pt: float) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"spaceAbove": {"magnitude": pt, "unit": "PT"}},
            "fields": "spaceAbove",
        }
    }


def req_border_bottom(start: int, end: int) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "borderBottom": {
                    "color": {"color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 0.0}}},
                    "width": {"magnitude": 1, "unit": "PT"},
                    "padding": {"magnitude": 1, "unit": "PT"},
                    "dashStyle": "SOLID",
                }
            },
            "fields": "borderBottom",
        }
    }


# ---------------------------------------------------------------------------
# Enumerate label helpers
# ---------------------------------------------------------------------------

def _to_roman(n: int) -> str:
    vals = [1000,900,500,400,100,90,50,40,10,9,5,4,1]
    syms = ["m","cm","d","cd","c","xc","l","xl","x","ix","v","iv","i"]
    out = ""
    for v, s in zip(vals, syms):
        while n >= v:
            out += s
            n -= v
    return out


def _to_alpha(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord('a') + rem) + out
    return out


def item_label(counter: int, depth: int) -> str:
    if depth == 1:
        return f"{counter}."
    elif depth == 2:
        return f"({_to_alpha(counter)})"
    else:
        return f"{_to_roman(counter)}."


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class State:
    def __init__(self):
        self.section_counters = [0, 0, 0]
        # Stack of per-enumerate item counters
        self.enum_stack: list[int] = []
        # Tables awaiting a second-phase text fill (in document order)
        self.tables: list[dict] = []

    @property
    def enum_depth(self) -> int:
        return len(self.enum_stack)

    def heading_prefix(self, level: int) -> str:
        idx = level - 1
        self.section_counters[idx] += 1
        for j in range(idx + 1, len(self.section_counters)):
            self.section_counters[j] = 0
        return ".".join(str(p) for p in self.section_counters[:level])

    def push_enum(self):
        self.enum_stack.append(0)

    def pop_enum(self):
        if self.enum_stack:
            self.enum_stack.pop()

    def next_item_label(self) -> str:
        self.enum_stack[-1] += 1
        return item_label(self.enum_stack[-1], self.enum_depth)


# ---------------------------------------------------------------------------
# Node handlers
# ---------------------------------------------------------------------------

def handle_heading(node: dict, idx: int, reqs: list, state: State) -> int:
    level = {"section": 1, "subsection": 2, "subsubsection": 3}[node["type"]]
    size = HEADING_SIZES[level]
    prefix = state.heading_prefix(level)
    text = f"{prefix}  {node['title']}\n"
    n = utf16len(text)

    reqs.append(req_insert(idx, text))
    reqs.append(req_paragraph_style(idx, idx + n, f"HEADING_{level}"))
    reqs.append(req_text_style(idx, idx + n, bold=True, size_pt=size))
    if level == 1:
        reqs.append(req_space_before(idx, idx + n, 14))
    idx += n

    idx = handle_nodes(node.get("children", []), idx, reqs, state)
    return idx


def handle_paragraph_heading(node: dict, idx: int, reqs: list, state: State) -> int:
    text = f"{node['title']}\n"
    n = utf16len(text)

    reqs.append(req_insert(idx, text))
    reqs.append(req_paragraph_style(idx, idx + n, "HEADING_4"))
    reqs.append(req_text_style(idx, idx + n, bold=True, size_pt=HEADING_SIZES[4]))
    idx += n

    idx = handle_nodes(node.get("children", []), idx, reqs, state)
    return idx


def handle_paragraph(node: dict, idx: int, reqs: list, state: State) -> int:
    text = node["text"] + "\n"
    n = utf16len(text)

    reqs.append(req_insert(idx, text))
    reqs.append(req_paragraph_style(idx, idx + n, "NORMAL_TEXT"))
    reqs.append(req_text_style(idx, idx + n))
    idx += n
    return idx


def handle_enumerate(node: dict, idx: int, reqs: list, state: State) -> int:
    state.push_enum()
    idx = handle_nodes(node["items"], idx, reqs, state)
    state.pop_enum()
    return idx


def handle_item(node: dict, idx: int, reqs: list, state: State) -> int:
    children = node.get("children", [])

    item_text = node["text"]
    remaining = children
    if not item_text and children and children[0]["type"] == "paragraph":
        item_text = children[0]["text"]
        remaining = children[1:]

    if state.enum_depth == 0:
        state.push_enum()

    label = state.next_item_label()
    depth = state.enum_depth
    # Wrapped lines align at depth * INDENT_STEP.
    # First line (label) starts at (depth-1) * INDENT_STEP so the label is
    # visually at the outer level and the text body is indented under it.
    indent_start     = depth * INDENT_STEP
    indent_first_line = (depth - 1) * INDENT_STEP

    text = f"{label} {item_text}\n"
    n = utf16len(text)

    reqs.append(req_insert(idx, text))
    reqs.append(req_paragraph_style(idx, idx + n, "NORMAL_TEXT"))
    reqs.append(req_text_style(idx, idx + n))
    reqs.append(req_indent(idx, idx + n, indent_start, indent_first_line))
    idx += n

    idx = handle_nodes(remaining, idx, reqs, state)
    return idx


def handle_signature(node: dict, idx: int, reqs: list, state: State) -> int:
    rule_text = "\n"
    n = utf16len(rule_text)
    reqs.append(req_insert(idx, rule_text))
    reqs.append(req_border_bottom(idx, idx + n))
    idx += n

    label_text = node["label"] + "\n"
    n = utf16len(label_text)
    reqs.append(req_insert(idx, label_text))
    reqs.append(req_paragraph_style(idx, idx + n, "NORMAL_TEXT"))
    reqs.append(req_text_style(idx, idx + n))
    idx += n
    return idx


def handle_table(node: dict, idx: int, reqs: list, state: State) -> int:
    """Insert an empty Google Docs table and record it for a later text pass.

    The single-batch index model breaks down for tables: cell paragraph indices
    only become known after the table exists in the document. So here we only
    emit the `insertTable` request (which has a deterministic *outer* length)
    and register the table+rows in `state.tables`. A second phase, run after the
    structural batch is applied, re-fetches the real cell indices and fills text.
    """
    rows = node.get("rows", [])
    if not rows:
        return idx
    n_rows = len(rows)
    n_cols = max(len(r) for r in rows)
    rows = [list(r) + [""] * (n_cols - len(r)) for r in rows]

    reqs.append({
        "insertTable": {
            "location": {"index": idx},
            "rows": n_rows,
            "columns": n_cols,
        }
    })

    # Record this table so a later pass can fill it. We identify it by the
    # insertion index; after the batch applies, tables appear in document order,
    # so we match them sequentially.
    state.tables.append({"rows": rows, "n_rows": n_rows, "n_cols": n_cols})

    # Outer length consumed by one `insertTable` call, measured empirically
    # against the Docs API: the API inserts a leading paragraph (+1) before the
    # table, the table body spans R*(1 + 2*C) + 2 indices (per-cell empty
    # paragraph + row/cell boundaries). Total = R*(1 + 2*C) + 3.
    idx += n_rows * (1 + n_cols * 2) + 3
    return idx


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def handle_nodes(nodes: list, idx: int, reqs: list, state: State) -> int:
    for node in nodes:
        t = node.get("type")
        if t in ("section", "subsection", "subsubsection"):
            idx = handle_heading(node, idx, reqs, state)
        elif t == "paragraph_heading":
            idx = handle_paragraph_heading(node, idx, reqs, state)
        elif t == "paragraph":
            idx = handle_paragraph(node, idx, reqs, state)
        elif t == "enumerate":
            idx = handle_enumerate(node, idx, reqs, state)
        elif t == "item":
            idx = handle_item(node, idx, reqs, state)
        elif t == "signature":
            idx = handle_signature(node, idx, reqs, state)
        elif t == "table":
            idx = handle_table(node, idx, reqs, state)
        else:
            print(f"Warning: unknown node type '{t}', skipping.")
    return idx


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def fill_tables(service, document_id: str, tables: list[dict]):
    """Phase 2: read the real cell indices of each inserted table and fill text.

    Tables are matched to `tables` in document order. Within each table, cell
    text is inserted in reverse index order so earlier cells' indices stay valid.
    """
    if not tables:
        return

    doc = service.documents().get(documentId=document_id).execute()
    doc_tables = [el["table"] for el in doc["body"]["content"] if "table" in el]
    if len(doc_tables) != len(tables):
        print(f"Warning: found {len(doc_tables)} tables in doc but expected "
              f"{len(tables)}; filling the ones that match by order.")

    reqs: list = []
    for spec, dtable in zip(tables, doc_tables):
        rows = spec["rows"]
        inserts = []  # (start_index, text, bold)
        for r, drow in enumerate(dtable["tableRows"]):
            for c, dcell in enumerate(drow["tableCells"]):
                if r >= len(rows) or c >= len(rows[r]):
                    continue
                txt = rows[r][c]
                if not txt:
                    continue
                # Each empty cell holds one empty paragraph; its content start
                # index is where we insert the cell's text.
                start = dcell["content"][0]["startIndex"]
                bold = (r == 0) or (c == 0)
                inserts.append((start, txt, bold))

        # Reverse order: inserting at a higher index never shifts a lower one.
        for start, txt, bold in sorted(inserts, key=lambda x: -x[0]):
            n = utf16len(txt)
            reqs.append(req_insert(start, txt))
            reqs.append(req_text_style(start, start + n, bold=bold))

    if not reqs:
        return
    print(f"Filling {len(tables)} table(s) with {len(reqs)} requests …")
    service.documents().batchUpdate(
        documentId=document_id, body={"requests": reqs}
    ).execute()


def main():
    document_id, input_file = get_args()

    credentials = Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    service = build("docs", "v1", credentials=credentials)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Clear document before writing
    doc = service.documents().get(documentId=document_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]
    if end_index > 2:
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}]}
        ).execute()
        print(f"Cleared document ({end_index - 1} characters).")

    reqs: list = []
    state = State()
    handle_nodes(data, idx=1, reqs=reqs, state=state)

    if not reqs:
        print("No requests generated — is the JSON file empty?")
        return

    print(f"Sending {len(reqs)} requests to document {document_id} …")
    result = (
        service.documents()
        .batchUpdate(documentId=document_id, body={"requests": reqs})
        .execute()
    )
    print("Document updated successfully!")
    print(f"  Revision: {result.get('writeControl', {})}")

    # Phase 2: fill table cell text now that real cell indices are known.
    fill_tables(service, document_id, state.tables)


if __name__ == "__main__":
    main()
