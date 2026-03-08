"""
constitution_to_docs.py — Write constitution.json to a Google Doc.

Usage:
    python constitution_to_docs.py <DOCUMENT_ID>
    # or:
    GOOGLE_DOC_ID=<id> python constitution_to_docs.py

Prerequisites:
    - credentials.json (Google service-account key) in this directory
    - The target Google Doc must be empty before running
    - The service account must have editor access to the document
    - pip install -r requirements.txt
"""

import json
import os
import sys
from pathlib import Path

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# --- Config ---
SCOPES = ["https://www.googleapis.com/auth/documents"]
HERE = Path(__file__).parent
SERVICE_ACCOUNT_FILE = HERE / "credentials.json"
INPUT_FILE = HERE / "constitution.json"


def get_document_id() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    doc_id = os.environ.get("GOOGLE_DOC_ID", "")
    if doc_id:
        return doc_id
    print(
        "Error: no document ID supplied.\n"
        "  Usage:  python constitution_to_docs.py <DOCUMENT_ID>\n"
        "     or:  GOOGLE_DOC_ID=<id> python constitution_to_docs.py"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Low-level request builders
# ---------------------------------------------------------------------------

def insert_text(index: int, text: str) -> dict:
    return {"insertText": {"location": {"index": index}, "text": text}}


def style_paragraph(start: int, end: int, named_style: str) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": named_style},
            "fields": "namedStyleType",
        }
    }


def create_bullets(start: int, end: int) -> dict:
    return {
        "createParagraphBullets": {
            "range": {"startIndex": start, "endIndex": end},
            "bulletPreset": "NUMBERED_DECIMAL_NESTED",
        }
    }


def indent_paragraph(start: int, end: int, nesting_level: int) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentFirstLine": {"magnitude": 0, "unit": "PT"},
                "indentStart": {"magnitude": nesting_level * 18, "unit": "PT"},
            },
            "fields": "indentFirstLine,indentStart",
        }
    }


def make_bold(start: int, end: int) -> dict:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {"bold": True},
            "fields": "bold",
        }
    }


# ---------------------------------------------------------------------------
# High-level node handlers
# ---------------------------------------------------------------------------

def handle_heading(node: dict, index: int, requests: list) -> int:
    level = {"section": 1, "subsection": 2, "subsubsection": 3}[node["type"]]
    text = node["title"] + "\n"
    requests.append(insert_text(index, text))
    requests.append(style_paragraph(index, index + len(text), f"HEADING_{level}"))
    index += len(text)
    index = handle_nodes(node.get("children", []), index, requests, list_level=0)
    return index


def handle_paragraph(node: dict, index: int, requests: list) -> int:
    text = node["text"] + "\n"
    requests.append(insert_text(index, text))
    requests.append(style_paragraph(index, index + len(text), "NORMAL_TEXT"))
    index += len(text)
    return index


def handle_enumerate(node: dict, index: int, requests: list, list_level: int) -> int:
    return handle_nodes(node["items"], index, requests, list_level=list_level + 1)


def handle_item(node: dict, index: int, requests: list, list_level: int) -> int:
    children = node.get("children", [])
    item_text = node["text"]
    remaining_children = children

    # If item text is empty and first child is a paragraph, promote it
    if not item_text and children and children[0]["type"] == "paragraph":
        item_text = children[0]["text"]
        remaining_children = children[1:]

    text = item_text + "\n"
    requests.append(insert_text(index, text))
    requests.append(create_bullets(index, index + len(text)))
    requests.append(indent_paragraph(index, index + len(text), list_level))
    index += len(text)
    index = handle_nodes(remaining_children, index, requests, list_level=list_level)
    return index


def handle_table(node: dict, index: int, requests: list) -> int:
    """
    Render a tblr table as tab-separated lines of normal text.
    The first row (bold terms) is rendered with bold text styling.
    """
    rows = node.get("rows", [])
    for row_idx, cells in enumerate(rows):
        line = "  ".join(cells) + "\n"
        requests.append(insert_text(index, line))
        requests.append(style_paragraph(index, index + len(line), "NORMAL_TEXT"))
        # Bold the first cell (the term) for definition tables
        if cells:
            term = cells[0]
            if term:
                requests.append(make_bold(index, index + len(term)))
        index += len(line)
    return index


def handle_nodes(nodes: list, index: int, requests: list, list_level: int = 0) -> int:
    for node in nodes:
        node_type = node.get("type")

        if node_type in ("section", "subsection", "subsubsection"):
            index = handle_heading(node, index, requests)
        elif node_type == "paragraph":
            index = handle_paragraph(node, index, requests)
        elif node_type == "enumerate":
            index = handle_enumerate(node, index, requests, list_level)
        elif node_type == "item":
            index = handle_item(node, index, requests, list_level)
        elif node_type == "table":
            index = handle_table(node, index, requests)
        else:
            print(f"Warning: unknown node type '{node_type}', skipping.")

    return index


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    document_id = get_document_id()

    credentials = Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    service = build("docs", "v1", credentials=credentials)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    requests = []
    handle_nodes(data, index=1, requests=requests)

    if not requests:
        print("No requests generated — is the JSON file empty?")
        return

    print(f"Sending {len(requests)} requests to document {document_id} …")
    result = (
        service.documents()
        .batchUpdate(documentId=document_id, body={"requests": requests})
        .execute()
    )
    print("Document updated successfully!")
    print(f"  Revision: {result.get('writeControl', {})}")


if __name__ == "__main__":
    main()
