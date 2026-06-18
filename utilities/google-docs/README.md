# LaTeX → Google Docs pipeline

Converts any CFES LaTeX document into a formatted Google Doc via the Docs API.

## Files

| File | Purpose |
|---|---|
| `tex_to_json.py` | Parse any LaTeX source (with `\input{}` resolution) → JSON |
| `json_to_docs.py` | Send the JSON to a Google Doc via the Docs API |
| `requirements.txt` | Python dependencies |
| `credentials.json` | (**not committed**) Google service-account key |

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Google service-account credentials

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   reuse a project and enable the **Google Docs API**.
2. Create a **Service Account** and download its JSON key.
3. Save the key as `utilities/google-docs/credentials.json`
   (it is already `.gitignore`d).
4. Share the target Google Doc with the service account's email address
   (give it **Editor** access):
   `latex-to-docs-converter@cfes-admin-controller.iam.gserviceaccount.com`

### 3. Prepare a blank Google Doc

The script clears the document automatically before writing. Create a Google Doc and copy its ID from the URL:

```
https://docs.google.com/document/d/<DOCUMENT_ID>/edit
```

---

## Usage

### Step 1 — Parse LaTeX to JSON

```bash
cd utilities/google-docs

# Constitution (English)
python tex_to_json.py ../../documents/constitution/main.tex constitution.json

# Constitution (French)
python tex_to_json.py ../../documents/constitution-fr/main.tex constitution-fr.json

# Policy manual (English)
python tex_to_json.py ../../documents/policies/main.tex policies.json

# Policy manual (French)
python tex_to_json.py ../../documents/policies-fr/main.tex policies-fr.json
```

Inspect the output with:

```bash
python -m json.tool policies.json | less
```

### Step 2 — Write to Google Docs

```bash
# Pass the document ID as a positional argument …
python json_to_docs.py <DOCUMENT_ID> policies.json

# … or set an environment variable
export GOOGLE_DOC_ID=<DOCUMENT_ID>
python json_to_docs.py policies.json
```

Open the document in your browser to verify formatting.

---

## JSON intermediate format

```
Root: list of nodes. Every node has a "type" field.

section / subsection / subsubsection
  { type, title, starred (bool), label (str|null), children: [node] }

enumerate
  { type: "enumerate", items: [item_node] }

item
  { type: "item", text: str, children: [node] }

paragraph
  { type: "paragraph", text: str }

table
  { type: "table", rows: [[cell, cell, ...], ...] }

signature
  { type: "signature", label: str }
```

---

## Google Docs API notes

- The API uses **character-based indices** that advance as text is inserted.
  All requests must be sent in a **single `batchUpdate` call**; splitting
  into multiple calls would invalidate the indices.
- `createParagraphBullets` must follow `insertText` for the same range.
- The document must be **empty** before running `json_to_docs.py`; re-running
  will append a duplicate copy rather than replacing content.
- Starred sections (`\section*`) are written with the same `HEADING_N` style
  as numbered sections (the Docs API has no concept of unnumbered headings).
