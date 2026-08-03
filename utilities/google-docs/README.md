# LaTeX → Google Docs pipeline

Converts any CFES LaTeX document into a formatted Google Doc via the Docs API.

## Files

| File | Purpose |
|---|---|
| `tex_to_json.py` | Parse any LaTeX source (with `\input{}` resolution) → JSON |
| `json_to_docs.py` | Send the JSON to a Google Doc via the Docs API |
| `enum_trial.py` | Standalone proof of the native-numbering approach, on synthetic content. Useful for isolating a numbering or spacing question without a real document in the way. |
| `requirements.txt` | Python dependencies |
| `credentials.json` | (**not committed**) Google service-account key |

`fonttools` is used to read Nunito's glyph widths, for sizing table columns and
aligning heading numbers. The script still runs without it, falling back to a
flat per-character estimate that sizes columns slightly less accurately.

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

The script verifies itself as it finishes, checking every heading's number, level
and title against independently computed expectations, plus the list-item count
and that no indented paragraph was left unbulleted. A clean run ends with
`OK`; anything else prints the specific mismatches.

#### Iterating on formatting

A full policy-manual run is several minutes. To check formatting quickly, write
only the first N articles — starred sections (the constitution's
`Terms & Definitions` table) are skipped, since they say nothing about how the
numbered articles are laid out:

```bash
python json_to_docs.py <DOCUMENT_ID> constitution.json --articles=2
```

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

Numbering is **native**: heading numbers (1 / 1.1 / 1.1.1) and list numbers
(1. / a. / i.) are real Docs list glyphs, not typed text, so the document
renumbers itself when edited.

The document is cleared automatically at the start of each run, so re-running is
safe and idempotent.

Hard-won specifics, all verified against the live API — see the module docstring
in `json_to_docs.py` for the full detail:

- **`spacingMode` must be `NEVER_COLLAPSE`.** `spaceAbove`/`spaceBelow` are
  silently ignored on list items under the default `COLLAPSE_LISTS`, and with
  native numbering every heading and every item *is* a list item. The API stores
  and reports the magnitudes faithfully either way, so reading the document back
  will not reveal the problem — only the editor shows it.
- **Never verify layout through an export.** The PDF and HTML exports each render
  spacing differently from the editor and from each other. Use exports for
  content checks only (text present, numbering sequence, table structure).
- **Counters live on a list, and `createParagraphBullets` cannot join an existing
  list.** So all headings are inserted contiguously and bulleted in one call;
  content is spliced in afterwards, bottom-up.
- **A list item's nesting level is inferred from its indent at bullet-creation
  time**, using Docs' own 36pt-per-level geometry. A final pass tightens the
  indent to the width we actually want, which is safe because the level is
  already frozen.
- **Cumulative numbering is only available END-aligned**, which right-aligns the
  numbers. Setting `indentFirstLine` per paragraph to that number's own rendered
  width puts every left edge at the margin instead.
- **The quota limits `batchUpdate` *calls*, not the requests inside them**
  (measured: 800 requests in 8 calls is instant; 62 single-request calls earns a
  429 at ~60 calls/minute). Batch aggressively; pace the calls.
- **Starred sections (`\section*`) are excluded from the heading list.** Docs has
  no unnumbered-heading concept, so leaving them in would consume a number and
  shift every section after them.
- Glyph widths for column sizing and number alignment are read from the Nunito
  font via `fontTools`, since Docs exposes no text-measurement API.
