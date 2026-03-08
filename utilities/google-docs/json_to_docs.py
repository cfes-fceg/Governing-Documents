"""
json_to_docs.py — Write activity-financial-agreement.json to a Google Doc.

Usage:
    python json_to_docs.py <DOCUMENT_ID>
    # or set GOOGLE_DOC_ID environment variable and run without args:
    GOOGLE_DOC_ID=<id> python json_to_docs.py

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
INPUT_FILE = HERE / "activity-financial-agreement.json"


def get_document_id() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    doc_id = os.environ.get("GOOGLE_DOC_ID", "")
    if doc_id:
        return doc_id
    print(
        "Error: no document ID supplied.\n"
        "  Usage:  python json_to_docs.py <DOCUMENT_ID>\n"
        "     or:  GOOGLE_DOC_ID=<id> python json_to_docs.py"
    )
    sys.exit(1)


# --- Low-level request builders ---

def insert_text_request(index: int, text: str) -> dict:
    return {"insertText": {"location": {"index": index}, "text": text}}


def update_paragraph_style_request(start: int, end: int, named_style: str) -> dict:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": named_style},
            "fields": "namedStyleType",
        }
    }


def create_numbered_bullet_request(start: int, end: int) -> dict:
    return {
        "createParagraphBullets": {
            "range": {"startIndex": start, "endIndex": end},
            "bulletPreset": "NUMBERED_DECIMAL_NESTED",
        }
    }


def update_indent_request(start: int, end: int, nesting_level: int) -> dict:
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


def border_bottom_request(start: int, end: int) -> dict:
    """Apply a bottom border to simulate a horizontal rule."""
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "borderBottom": {
                    "color": {
                        "color": {
                            "rgbColor": {"red": 0.0, "green": 0.0, "blue": 0.0}
                        }
                    },
                    "width": {"magnitude": 1, "unit": "PT"},
                    "padding": {"magnitude": 1, "unit": "PT"},
                    "dashStyle": "SOLID",
                }
            },
            "fields": "borderBottom",
        }
    }


# --- High-level node handlers ---

def handle_heading(node: dict, index: int, requests: list) -> int:
    level = {"section": 1, "subsection": 2, "subsubsection": 3}[node["type"]]
    text = node["title"] + "\n"
    requests.append(insert_text_request(index, text))
    requests.append(update_paragraph_style_request(index, index + len(text), f"HEADING_{level}"))
    index += len(text)
    index = handle_nodes(node.get("children", []), index, requests, list_level=0)
    return index


def handle_paragraph(node: dict, index: int, requests: list) -> int:
    text = node["text"] + "\n"
    requests.append(insert_text_request(index, text))
    requests.append(update_paragraph_style_request(index, index + len(text), "NORMAL_TEXT"))
    index += len(text)
    return index


def handle_enumerate(node: dict, index: int, requests: list, list_level: int) -> int:
    # Recurse into items, incrementing nesting level
    index = handle_nodes(node["items"], index, requests, list_level=list_level + 1)
    return index


def handle_item(node: dict, index: int, requests: list, list_level: int) -> int:
    children = node.get("children", [])

    # The LaTeX source puts \item on its own line and the text on the next.
    # When that happens, node["text"] is "" and the first child is a paragraph
    # node holding the actual item text. Promote it so the bullet has content.
    item_text = node["text"]
    remaining_children = children
    if not item_text and children and children[0]["type"] == "paragraph":
        item_text = children[0]["text"]
        remaining_children = children[1:]

    text = item_text + "\n"
    requests.append(insert_text_request(index, text))
    requests.append(create_numbered_bullet_request(index, index + len(text)))
    requests.append(update_indent_request(index, index + len(text), list_level))
    index += len(text)
    # Recurse into remaining children (nested enumerates, continuation paragraphs)
    index = handle_nodes(remaining_children, index, requests, list_level=list_level)
    return index


def handle_signature(node: dict, index: int, requests: list) -> int:
    # Blank line with bottom border = visual horizontal rule
    rule_text = "\n"
    requests.append(insert_text_request(index, rule_text))
    requests.append(border_bottom_request(index, index + len(rule_text)))
    index += len(rule_text)

    # Label text on the next line
    label_text = node["label"] + "\n"
    requests.append(insert_text_request(index, label_text))
    requests.append(update_paragraph_style_request(index, index + len(label_text), "NORMAL_TEXT"))
    index += len(label_text)
    return index


# --- Dispatcher ---

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

        elif node_type == "signature":
            index = handle_signature(node, index, requests)

        else:
            print(f"Warning: unknown node type '{node_type}', skipping.")

    return index


# --- Entry point ---

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
