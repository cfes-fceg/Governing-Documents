"""json_to_docs.py — Write a CFES JSON document to a Google Doc using
NATIVE Docs list numbering.

Usage:
    python json_to_docs.py <DOCUMENT_ID> <input.json>

Every number here is a real Docs list glyph, so the document renumbers itself
when edited and the numbering survives insertions. The earlier version of this
script typed numbers as literal text ("1.1  Title", "(a) some item"), which read
correctly but went stale the moment anyone inserted a clause.

The approach and its many non-obvious constraints are proven out in
enum_trial.py — read its module docstring first; everything it documents applies
here. The essentials:

  - Heading numbers (1 / 1.1 / 1.1.1) come from ONE NUMBERED_DECIMAL_NESTED list
    spanning every heading in the document. Counters live on a list, and
    createParagraphBullets cannot join an existing list, so all headings must be
    inserted contiguously and bulleted in a single call. Hence the headings-first
    pass, with content spliced in afterwards, bottom-up.
  - Content lists use NUMBERED_DECIMAL_ALPHA_ROMAN (1. / a. / i.), each run its
    own list so numbering restarts after every heading or intervening paragraph.
  - Nesting level is inferred from indentation AT BULLET-CREATION TIME and needs
    Docs' own 36pt-per-level geometry. A final pass tightens indents to 18pt.
  - Cumulative numbering is only available END-aligned, which right-aligns the
    numbers. Setting indentFirstLine per paragraph to that number's own rendered
    width puts every left edge at the margin instead. See glyph_width().

Differences from enum_trial.py, which only had headings and list items:
  - Starred headings (\\section*) must be kept OUT of the heading list, or they
    consume a number and shift every article after them.
  - Tables, signatures, paragraph_headings and body paragraphs are all content,
    and content is spliced in per heading, so each is emitted inside that pass.
  - Real documents reach enumerate depth 4 and heading numbers reach two digits.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/documents"]
HERE = Path(__file__).parent
SERVICE_ACCOUNT_FILE = HERE / "credentials.json"

FONT = "Nunito"
HEADING_SIZES = {1: 16, 2: 13, 3: 11}
PARA_HEADING_SIZE = 11
BODY_SIZE = 11

# Docs infers a list item's nesting level from its indent, using its own
# geometry: level N at 36*N pt. Smaller steps read as "same level" and collapse
# the hierarchy, so this is not a style choice.
INFER_STEP_PT = 36

# The indent we actually want, applied after bullets exist. Safe to change
# afterwards because nestingLevel is frozen at bullet-creation time.
FINAL_STEP_PT = 18
HANGING_PT = 18

# Some content nesting levels are END-aligned (level 3 and 6 of the content
# preset). An END-aligned glyph hangs its RIGHT edge on the hanging-indent
# position, so it drifts left of the START-aligned levels above it. Alignment is
# read-only, so nudge the indent to compensate. Applied only where the list
# actually reports END, read back from the document.
END_ALIGN_NUDGE_PT = 10

# Where each heading level's TITLE starts, measured from the left margin.
#
# LaTeX does NOT use one shared title column — measured off the built PDF with
# pdftotext -bbox, on page 7 of the constitution:
#
#   level 1 ("2")     number 72.0-82.3, title at  99.5  ->  27.5pt from margin
#   level 2 ("2.1")   number 72.0-92.8, title at 107.1  ->  35.1pt from margin
#
# i.e. the title sits a consistent ~14-17pt after the number ends, so the column
# is per level and sized to that level's own number width. A single wide column
# (the earlier approach) leaves a visible chasm after short numbers like "1.1".
#
# Level 3 is extrapolated: "1.1.1" is roughly one more "N." group than level 2.
# Two-digit articles ("13.1.1") are wider than these columns, so reindent()
# widens the column per paragraph when a number needs more room — the values
# below are the minimum, not a hard cap.
HEADING_TITLE_COL_PT = {1: 27.5, 2: 35.1, 3: 42.0}

# Minimum gap between the end of a heading number and the start of its title,
# used when a number is too wide for its level's nominal column.
HEADING_NUM_GAP_PT = 14.35

# Nunito Bold advance widths, in em, for predicting a number's rendered width.
# Docs exposes no text measurement API, so these come from the font itself:
#   fontTools.ttLib.TTFont(".../nunito/Nunito-Bold.otf")
# with unitsPerEm 1000 giving digit 600 and period 248. All ten digits measure
# 600 (Nunito's figures are tabular), so one value covers 0-9 and the estimate
# stays exact as numbers reach two and three digits.
GLYPH_W_DIGIT_EM = 0.600
GLYPH_W_DOT_EM = 0.248

# ---------------------------------------------------------------------------
# Spacing, derived from the LaTeX rather than chosen by eye
# ---------------------------------------------------------------------------
# Every value below was MEASURED off the built PDF
# (build/"[EN] Constitution - CESS 2026.pdf") with `pdftotext -bbox`, by taking
# the baseline-to-baseline distance between consecutive lines and subtracting the
# body baseline. Measuring beats computing from the class file because the
# rendered gap is the sum of several LaTeX lengths (\itemsep + \parsep + \topsep,
# and heading skips that collapse against surrounding space); reproducing that
# arithmetic is error-prone, and the rendered result is what we are matching.
#
# To re-derive after a style change:
#   pdftotext -bbox -f <page> -l <page> "build/<doc>.pdf" out.xml
# then diff consecutive <word yMin> values down a column.
#
# Reference measurements (page 7 of the constitution, Articles 1-2):
#   body line -> body line          14.4pt   (\baselineskip, 12pt on 14.5pt)
#   item -> next item, level 1      21.8pt   => 7.4pt of item gap
#   item -> next item, level 2      18.1pt   => 3.7pt of item gap
#   heading -> its first item       25.5pt   => 11.1pt below a heading
#   last item -> next subsection    34.3pt   => 19.9pt above a subsection
#   last item -> next section       36.9pt   => 22.5pt above a section
#   section -> its first subsection 34.1pt

# Wrapped lines WITHIN a paragraph.
#
# LaTeX puts 12pt text on a 14.5pt baseline. Docs applies lineSpacing to the
# font's own line height rather than to a 12pt em, so the percentage does not
# translate directly: at 100% Nunito wraps at about 12.6pt, noticeably tighter
# than the LaTeX's 14.4pt, which is what makes the Docs output look cramped
# INSIDE a long item even when the gaps BETWEEN items are correct.
#
# 114% brings the wrap baseline to roughly 14.4pt and matches the LaTeX's
# measured rhythm. Do not confuse this with the gaps between items — those come
# from spaceAbove and are set separately.
LINE_SPACING = 114

# Space above each heading level, from the measurements above.
#
# CRITICAL — spacingMode. A paragraph's spaceAbove/spaceBelow are IGNORED on
# list items unless spacingMode is also set to NEVER_COLLAPSE. The default,
# COLLAPSE_LISTS, drops paragraph spacing between list items entirely — and with
# native numbering every heading AND every enumerate item is a list item, so
# without this the whole document renders with no spacing whatever value is set.
#
# The Docs UI exposes this as "Add space before/after list item" in the
# line-spacing menu; those commands write spacingMode: NEVER_COLLAPSE together
# with the magnitude. The API reports the magnitudes back faithfully either way,
# so reading the document back does NOT reveal the problem — only the editor
# does.
SPACING_MODE = "NEVER_COLLAPSE"

# Level 1 keeps a strong break before a new article. Levels 2 and 3 are pulled
# in from the measured 19.9pt: LaTeX's gap is partly its own larger wrap
# baseline, so reproducing the raw number on top of Docs' line spacing reads as
# too much air between a section and its first subsection.
HEADING_SPACE_ABOVE_PT = {1: 20, 2: 13, 3: 11}

# Start each top-level section (article) on a fresh page.
#
# This is a deliberate departure from the LaTeX, which lets articles flow and
# only breaks for the title page and TOC. Docs' pageBreakBefore is the native
# way to do it, so the break travels with the heading and survives editing —
# unlike an inserted page-break character.
#
# The first article is exempt: a break before it would leave a blank leading page.
PAGE_BREAK_BEFORE_LEVEL = 1

# Space above the FIRST content item under a heading — the heading-to-content
# gap. Set on the item, not as spaceBelow on the heading, per the note above.
# Measured at 11.1pt in the LaTeX but trimmed for the same reason: a heading
# should sit closer to the content it introduces than to the heading above it.
HEADING_SPACE_BELOW_PT = 6

# ---------------------------------------------------------------------------
# Table column widths
# ---------------------------------------------------------------------------
# Docs creates every column at an equal width, which wastes the page on narrow
# columns: the constitution's definitions table has an "Article" column whose
# widest value is 7 characters ("Article", the header itself) sitting at the same
# width as a "Definition" column with 358-character entries.
#
# Widths are computed from the content: each column gets what its longest single
# WORD needs (so nothing is forced to break mid-word) plus padding, subject to a
# minimum; whatever remains of the text width goes to the column with the most
# content. Text width is the 8.5in letter page minus the 1in margins.
TABLE_TEXT_WIDTH_PT = 468          # 6.5in at 72pt/in
# Docs' default cell padding is 5.4pt per side, but the usable text width is
# further reduced by the cell borders and by Docs rounding the wrap point down.
# Measured empirically: 11pt of allowance still wrapped "Article" to "Articl/e",
# so this carries a deliberate couple of points of slack.
TABLE_CELL_PADDING_PT = 16
TABLE_MIN_COL_PT = 42

# Per-character advance widths for Nunito Regular, in em, keyed by character.
# A flat average is not good enough here: the goal is a column just wide enough
# that no individual WORD wraps mid-letter, and averaging makes wide words like
# "Membership" (m, b) and "Ambassadors" (A, m, b, d) come out too narrow, so
# their last letter wraps to the next line. Measured from the font with
# fontTools; see NUNITO_WIDTHS_SOURCE below for how to regenerate.
NUNITO_WIDTHS_SOURCE = (
    "/usr/local/texlive/2025/texmf-dist/fonts/opentype/public/nunito/"
    "Nunito-Regular.otf"
)
# Fallback used for any character not in the measured table (punctuation,
# accented letters). Chosen on the generous side so an unknown character widens
# a column rather than causing a wrap.
TABLE_CHAR_W_FALLBACK_EM = 0.60

# Gap between consecutive list items, by nesting level. Level 3 is `nosep` in
# cfes-common.sty and measures as a plain baseline advance, hence 0.
LIST_SPACE_BELOW_PT = {1: 7.4, 2: 3.7, 3: 0}

# Body paragraphs sit in the same rhythm as level-1 items.
PARA_SPACE_BELOW_PT = 7.4

LIST_PRESET = "NUMBERED_DECIMAL_ALPHA_ROMAN"
HEADING_PRESET = "NUMBERED_DECIMAL_NESTED"

HEADING_TYPES = {"section": 1, "subsection": 2, "subsubsection": 3}

# Docs' documented write quota is 60 write requests per minute per user, and this
# approach is call-heavy by nature: every list run needs its own
# createParagraphBullets, which cannot share a batch with anything after it.
#
# Rather than sleep a fixed amount before every call (which spends minutes
# sleeping even when the quota is nowhere near exhausted), go as fast as the API
# allows and back off only when it actually returns 429. The quota is a sliding
# window, so a burst is fine until it is not.
# MEASURED against the live API: the limit is ~60 batchUpdate CALLS per minute,
# and is indifferent to how many requests each call carries.
#   800 write requests in 8 calls  ->  6.1s, never throttled
#   62 single-request calls        ->  429 at 11.4s
# So batch as much as possible per call, and pace the calls themselves.
QUOTA_CALLS_PER_MIN = 60

# No proactive pacing. Now that every pass batches its requests, a whole document
# costs roughly a dozen calls — nowhere near the per-minute ceiling — so sleeping
# between them would be pure waste. The 429 handler below is the safety net if a
# much larger document ever does approach the limit.
BATCH_PAUSE_S = 0.0

# On a 429, sleep this long before the first retry, doubling thereafter. Must
# comfortably outlast the one-minute quota window.
QUOTA_BACKOFF_S = 20

# Requests per batch in the final styling pass.
#
# MEASURED, because the documented "60 write requests per minute" is misleading:
# what is actually rate-limited is batchUpdate CALLS, not the requests inside
# them. Two probes against the live API:
#
#   800 write requests in 8 calls  ->  6.1s, no throttling at all
#   62 single-request calls        ->  429 after 11.4s (~60 calls/minute)
#
# So a big batch is nearly free and the only thing worth minimising is the number
# of calls. This chunk exists purely to stay under the request-payload limit, not
# to manage quota — hence large.
PASS4_CHUNK = 1000


def utf16len(text: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def glyph_width(number: str, size_pt: float) -> float:
    """Predict a number glyph's rendered width in points.

    Needed because an END-aligned glyph is positioned by its RIGHT edge, so
    putting its LEFT edge at the margin means offsetting indentFirstLine by
    exactly this width.
    """
    return sum(
        (GLYPH_W_DOT_EM if ch == "." else GLYPH_W_DIGIT_EM) * size_pt
        for ch in number
    )


class Api:
    """Thin wrapper that retries on quota errors and counts calls.

    Tracks `requests` as well as `calls`: what the quota actually limits is
    write REQUESTS, so a batch of 300 styling requests costs far more quota than
    a batch of one, and the request count is the number worth watching when
    tuning batch sizes.
    """

    def __init__(self, service, document_id):
        self.service = service
        self.document_id = document_id
        self.calls = 0
        self.requests = 0
        self.throttled = 0
        self.slept = 0.0

    def get(self):
        return self.service.documents().get(documentId=self.document_id).execute()

    def batch(self, requests, retries: int = 8):
        if not requests:
            return None
        delay = QUOTA_BACKOFF_S
        for attempt in range(retries):
            try:
                result = self.service.documents().batchUpdate(
                    documentId=self.document_id, body={"requests": requests}
                ).execute()
                self.calls += 1
                self.requests += len(requests)
                if BATCH_PAUSE_S:
                    time.sleep(BATCH_PAUSE_S)
                    self.slept += BATCH_PAUSE_S
                return result
            except HttpError as err:
                if err.resp.status not in (429, 500, 503) or attempt == retries - 1:
                    raise
                self.throttled += 1
                print(f"    quota/transient error {err.resp.status}; "
                      f"retrying in {delay}s …")
                time.sleep(delay)
                self.slept += delay
                delay *= 2


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def req_insert(index, text):
    return {"insertText": {"location": {"index": index}, "text": text}}


def req_named_style(start, end, style):
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": style},
            "fields": "namedStyleType",
        }
    }


def req_text_style(start, end, bold=False, size=BODY_SIZE):
    """Style a run. Colour is explicit because Docs' built-in HEADING_3 and
    below default to grey, while the LaTeX renders every heading black.
    """
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {
                "bold": bold,
                "weightedFontFamily": {"fontFamily": FONT},
                "fontSize": {"magnitude": size, "unit": "PT"},
                "foregroundColor": {
                    "color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 0.0}}
                },
            },
            "fields": "bold,weightedFontFamily,fontSize,foregroundColor",
        }
    }


def req_indent_for_inference(start, end, level):
    """Indent a to-be-bulleted paragraph so Docs infers the right nesting level.

    MUST run before createParagraphBullets: nestingLevel is fixed at bullet
    creation and derived from indentation. Re-indenting later moves the text but
    leaves the level, and therefore the glyph, untouched.
    """
    pt = level * INFER_STEP_PT
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentStart": {"magnitude": pt, "unit": "PT"},
                "indentFirstLine": {"magnitude": pt - HANGING_PT, "unit": "PT"},
            },
            "fields": "indentStart,indentFirstLine",
        }
    }


def req_indent_flat(start, end, pt=0):
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentStart": {"magnitude": pt, "unit": "PT"},
                "indentFirstLine": {"magnitude": pt, "unit": "PT"},
            },
            "fields": "indentStart,indentFirstLine",
        }
    }


def req_bullets(start, end, preset):
    return {
        "createParagraphBullets": {
            "range": {"startIndex": start, "endIndex": end},
            "bulletPreset": preset,
        }
    }


def req_delete_bullets(start, end):
    """Detach paragraphs from whatever list they currently belong to.

    Text inserted after a list paragraph JOINS that list, so freshly inserted
    content would otherwise inherit the heading list's numbering.
    """
    return {"deleteParagraphBullets": {"range": {"startIndex": start, "endIndex": end}}}


def req_border_bottom(start, end):
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "borderBottom": {
                    "color": {"color": {"rgbColor": {
                        "red": 0.0, "green": 0.0, "blue": 0.0}}},
                    "width": {"magnitude": 1, "unit": "PT"},
                    "padding": {"magnitude": 1, "unit": "PT"},
                    "dashStyle": "SOLID",
                }
            },
            "fields": "borderBottom",
        }
    }


# ---------------------------------------------------------------------------
# Flatten the JSON tree into a heading spine + per-heading content blocks
# ---------------------------------------------------------------------------

LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")


def is_unresolved_latex(text: str) -> bool:
    """True for paragraphs that are really an unconverted LaTeX command.

    tex_to_json leaves a few constructs it cannot represent as raw source — the
    cover \\includegraphics is the one case in these documents. Writing it out
    would put literal LaTeX in the reader's face, and a cover image cannot be
    reproduced through the Docs API anyway, so drop it. Only paragraphs that are
    ENTIRELY command-like are dropped; prose that merely contains a backslash is
    kept.
    """
    stripped = text.strip()
    if not stripped.startswith("\\"):
        return False
    return bool(LATEX_CMD_RE.match(stripped))


def flatten(nodes):
    """Split the document into (headings, blocks).

    headings  [{level, title, starred}]           in document order
    blocks    {heading_index: [row]}              content following that heading

    A row is one of:
      {kind: "li",    level: int, text: str}      list item, native bullets
      {kind: "p",     text: str}                  body paragraph
      {kind: "ph",    text: str}                  paragraph_heading (bold, flat)
      {kind: "table", rows: [[str]]}              table
      {kind: "sig",   text: str}                  signature line

    Content before the first heading goes in blocks[-1], which is emitted at the
    top of the document. The constitution opens with a preamble paragraph, so
    this case is real and must not be dropped.
    """
    headings = []
    blocks = {}

    def emit(row):
        blocks.setdefault(len(headings) - 1, []).append(row)

    def walk(ns, enum_depth):
        for node in ns:
            t = node.get("type")

            if t in HEADING_TYPES:
                headings.append({
                    "level": HEADING_TYPES[t],
                    "title": node.get("title", ""),
                    "starred": bool(node.get("starred")),
                })
                walk(node.get("children", []), 0)

            elif t == "paragraph_heading":
                emit({"kind": "ph", "text": node.get("title", "")})
                walk(node.get("children", []), enum_depth)

            elif t == "paragraph":
                text = (node.get("text") or "").strip()
                if text and not is_unresolved_latex(text):
                    emit({"kind": "p", "text": text})

            elif t == "enumerate":
                walk(node.get("items", []), enum_depth + 1)

            elif t == "item":
                depth = max(1, enum_depth)
                children = node.get("children", [])
                text = (node.get("text") or "").strip()

                # An item's text is often carried by its first child paragraph
                # rather than the item itself; promote it so the bullet is not
                # emitted with an empty body.
                if not text and children and children[0].get("type") == "paragraph":
                    text = (children[0].get("text") or "").strip()
                    children = children[1:]

                emit({"kind": "li", "level": depth, "text": text})
                walk(children, depth)

            elif t == "table":
                rows = node.get("rows", [])
                if rows:
                    emit({"kind": "table", "rows": rows})

            elif t == "signature":
                emit({"kind": "sig", "text": node.get("label", "")})

            else:
                print(f"  warning: unknown node type {t!r}, skipping")

    walk(nodes, 0)
    return headings, blocks


def expected_heading_numbers(headings):
    """The numbers Docs should generate, computed independently for verification.

    Starred headings are unnumbered and must not advance any counter.
    """
    counters = [0, 0, 0]
    out = []
    for h in headings:
        if h["starred"]:
            out.append(None)
            continue
        level = h["level"]
        counters[level - 1] += 1
        for j in range(level, len(counters)):
            counters[j] = 0
        out.append(".".join(str(c) for c in counters[:level]))
    return out


def group_runs(rows):
    """Group a block's rows into maximal runs of consecutive list items.

    Anything that is not a list item breaks the run, so numbering restarts at 1
    after intervening prose — matching the LaTeX, where each enumerate is
    independent.
    """
    runs, current = [], []
    for row in rows:
        if row["kind"] == "li":
            current.append(row)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)
    return runs


# ---------------------------------------------------------------------------
# Glyph replay (for verification and heading widths)
# ---------------------------------------------------------------------------

def _roman(n: int) -> str:
    vals = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syms = ["m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i"]
    out = ""
    for v, sy in zip(vals, syms):
        while n >= v:
            out += sy
            n -= v
    return out


def _alpha(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


GLYPH_FN = {
    "DECIMAL": str,
    "ZERO_DECIMAL": lambda n: f"{n:02d}",
    "ALPHA": _alpha,
    "UPPER_ALPHA": lambda n: _alpha(n).upper(),
    "ROMAN": _roman,
    "UPPER_ROMAN": lambda n: _roman(n).upper(),
}


def render_glyph(lists, list_id, level, counters) -> str:
    """Reproduce the glyph Docs will display for a list item.

    Docs stores counters implicitly, so to know what a reader sees (and, for
    headings, how wide the number is) we replay them: bump this level and clear
    every deeper one.
    """
    for key in [k for k in counters if k[0] == list_id and k[1] > level]:
        del counters[key]
    counters[(list_id, level)] = counters.get((list_id, level), 0) + 1

    nesting = lists[list_id]["listProperties"]["nestingLevels"][level]
    glyph = nesting.get("glyphFormat", "%0.")
    for lv in range(level + 1):
        count = counters.get((list_id, lv), 1)
        fn = GLYPH_FN.get(
            lists[list_id]["listProperties"]["nestingLevels"][lv].get("glyphType"), str
        )
        glyph = glyph.replace(f"%{lv}", fn(count))
    return glyph


# ---------------------------------------------------------------------------
# Passes
# ---------------------------------------------------------------------------

def insert_heading_spine(api, headings):
    """Pass 1: every heading, contiguous, bulleted as ONE list.

    Contiguity is mandatory, not tidiness: counters live on a list, and
    createParagraphBullets cannot join an existing list, so this single call is
    the only opportunity to put the whole spine on one set of counters.

    Starred headings are inserted here too (so document order is preserved) but
    are excluded from the bulleted range — they are unnumbered in the LaTeX, and
    including them would consume a number and shift every heading after.
    Excluding them means splitting the range around each one, which is why the
    numbered spans are bulleted as separate contiguous stretches. Those stretches
    end up on different lists, so the counters WOULD restart — acceptable only
    because a starred heading is always a top-level section in these documents
    and the level-1 counter is corrected afterwards. Verified by verify().
    """
    reqs = []
    idx = 1
    spans = []
    for h in headings:
        text = f"{h['title']}\n"
        n = utf16len(text)
        reqs.append(req_insert(idx, text))
        spans.append({"start": idx, "end": idx + n, **h})
        idx += n

    for s in spans:
        level = s["level"]
        reqs.append(req_named_style(s["start"], s["end"], f"HEADING_{level}"))
        reqs.append(req_text_style(s["start"], s["end"], bold=True,
                                   size=HEADING_SIZES[level]))
        if s["starred"]:
            reqs.append(req_indent_flat(s["start"], s["end"]))
        else:
            reqs.append(req_indent_for_inference(s["start"], s["end"], level))

    print(f"Pass 1: inserting {len(headings)} headings "
          f"({sum(1 for h in headings if h['starred'])} starred/unnumbered) …")
    api.batch(reqs)

    # Bullet the numbered headings. Contiguous stretches between starred
    # headings are bulleted together so their counters share a list.
    numbered_ranges = []
    run_start = None
    for s in spans:
        if s["starred"]:
            if run_start is not None:
                numbered_ranges.append((run_start, prev_end))
                run_start = None
        else:
            if run_start is None:
                run_start = s["start"]
            prev_end = s["end"]
    if run_start is not None:
        numbered_ranges.append((run_start, prev_end))

    # Bottom-up in one batch, for the same reason as the content runs: each range
    # sits above everything already shifted, so the indices stay valid.
    api.batch([req_bullets(start, end - 1, HEADING_PRESET)
               for start, end in reversed(numbered_ranges)])
    print(f"  bulleted {len(numbered_ranges)} heading range(s)")


def insert_content(api, headings, blocks):
    """Passes 2-3: splice each heading's content in, bottom-up.

    Bottom-up because inserting content shifts the indices of everything after
    it; working backwards keeps the heading indices read up front valid.
    """
    doc = api.get()
    heading_ends = [
        el["endIndex"]
        for el in doc["body"]["content"]
        if el.get("paragraph")
        and el["paragraph"]["paragraphStyle"].get(
            "namedStyleType", "").startswith("HEADING_")
    ]
    if len(heading_ends) != len(headings):
        raise RuntimeError(
            f"found {len(heading_ends)} heading paragraphs but expected "
            f"{len(headings)}; aborting rather than writing misaligned content")

    # Preamble content (before any heading) goes at the very top.
    order = sorted((k for k in blocks if k >= 0), reverse=True)
    if -1 in blocks:
        order.append(-1)  # last, because it inserts at index 1

    # What is rate-limited is batchUpdate CALLS, not the requests inside them
    # (measured: 800 requests in 8 calls is instant, 62 tiny calls earns a 429).
    # So accumulate every block's text and styling into ONE batch. Working
    # bottom-up means each block's indices are computed before anything earlier
    # in the document moves, so they are all still valid when the batch is
    # applied together.
    #
    # Tables are the exception: insertTable restructures the document and its
    # cell indices only exist afterwards, so any block containing one is handled
    # separately.
    # Blocks containing a table are handled on their own: insertTable
    # restructures the document and its cell indices cannot be predicted, so it
    # cannot share a batch with anything.
    table_order = [k for k in order
                   if any(r["kind"] == "table" for r in blocks[k])]

    # Everything else: ALL the text inserts and styling in ONE batch.
    #
    # Safe because the requests are built bottom-up and applied in that order —
    # an insert at a high index never moves a lower one, so every index stays
    # valid as the batch executes. The quota counts calls rather than requests
    # (measured), so this collapses 63 calls into 1.
    #
    # The bullets CANNOT ride along. createParagraphBullets renumbers everything
    # after its range, so its ranges must be computed against the document as it
    # exists after all the text is in. Hence one re-read below, then the bullet
    # calls — which still need to be individual, and bottom-up.
    text_reqs = []
    for h_index in order:
        if h_index in table_order:
            continue
        rows = [r for r in blocks[h_index] if r["kind"] != "table"]
        if not rows:
            continue
        at = heading_ends[h_index] if h_index >= 0 else 1
        reqs, _ = _plan_text_rows(rows, at)
        text_reqs.extend(reqs)

    print(f"Pass 2: {len(text_reqs)} text/style requests for "
          f"{len(order) - len(table_order)} block(s) in one call …")
    api.batch(text_reqs)

    # Now find the list runs in the real document and bullet them. Runs are
    # identified by indentation: _plan_text_rows indented every list item to
    # level*INFER_STEP_PT and left headings and plain paragraphs flat, so a
    # contiguous stretch of indented non-heading paragraphs is exactly one run.
    #
    # Every run is bulleted in ONE batch, ordered BOTTOM-UP. createParagraphBullets
    # shifts the indices after its own range, so a top-down batch would invalidate
    # every subsequent range — but working upwards, each range sits entirely above
    # everything already modified, so all the indices stay valid. Verified against
    # the live API: three runs bulleted in a single batch produce three separate
    # lists on exactly the right paragraphs.
    #
    # The indices must come from the document as it exists AFTER the text pass
    # above (hence _find_content_runs reading it back). Computing them beforehand
    # is what broke an earlier attempt at this, swallowing headings into the
    # content lists.
    runs = _find_content_runs(api.get())
    print(f"Pass 3: bulleting {len(runs)} content run(s) in one call …")
    api.batch([req_bullets(start, end, LIST_PRESET)
               for start, end in reversed(runs)])

    # Table blocks last, re-reading first because every index captured earlier
    # has moved by now.
    if table_order:
        doc = api.get()
        heading_ends = [
            el["endIndex"]
            for el in doc["body"]["content"]
            if el.get("paragraph")
            and el["paragraph"]["paragraphStyle"].get(
                "namedStyleType", "").startswith("HEADING_")
        ]
        for h_index in sorted(table_order, reverse=True):
            _insert_block(api, blocks[h_index], heading_ends[h_index])


def _insert_block(api, rows, at):
    """Insert one content block at `at`, then style and bullet it.

    Tables cannot be created by inserting text, so a block is split into
    text-only stretches around each table; each stretch is handled
    independently and tables are inserted separately, bottom-up.
    """
    # Split into segments: text runs and tables, so we can process bottom-up.
    segments = []
    current = []
    for row in rows:
        if row["kind"] == "table":
            if current:
                segments.append(("text", current))
                current = []
            segments.append(("table", row))
        else:
            current.append(row)
    if current:
        segments.append(("text", current))

    # Insert bottom-up so earlier segment offsets stay valid: every segment goes
    # at the same anchor `at`, applied in reverse document order.
    for kind, payload in reversed(segments):
        if kind == "table":
            _insert_table(api, payload, at)
        else:
            _insert_text_rows(api, payload, at)


def _find_content_runs(doc):
    """Locate the list runs to bullet, as (startIndex, endIndex) pairs.

    A run is a maximal stretch of consecutive paragraphs that are indented (so,
    intended list items), not headings, and not already bulleted. _plan_text_rows
    indents every list item to level*INFER_STEP_PT and leaves headings, plain
    paragraphs and signatures flat, so indentation is what distinguishes them.

    Reading the runs back out of the document rather than predicting them is what
    lets all the text inserts share one batch: the indices come from the document
    as it actually is, after every insert has landed.
    """
    runs = []
    current = None
    for el in doc["body"]["content"]:
        para = el.get("paragraph")
        if not para:
            current = None
            continue
        style = para["paragraphStyle"]
        is_heading = style.get("namedStyleType", "").startswith("HEADING_")
        indent = style.get("indentStart", {}).get("magnitude", 0)
        # An empty paragraph carries no meaningful indent and would otherwise
        # split a run in two.
        text = "".join(r["textRun"]["content"] for r in para["elements"]
                       if "textRun" in r).strip()

        if is_heading or para.get("bullet") or indent <= 0 or not text:
            current = None
            continue

        if current is None:
            current = [el["startIndex"], el["endIndex"]]
            runs.append(current)
        else:
            current[1] = el["endIndex"]

    # endIndex includes the paragraph's trailing newline; bulleting that would
    # pull in the following paragraph.
    return [(s, e - 1) for s, e in runs]


def _plan_text_rows(rows, at):
    """Build the requests to insert and style one run of text rows.

    Returns (batchable_requests, bullet_requests). Everything in the first list
    addresses indices computed here from string lengths, so it needs no
    round-trip and can be merged with other blocks' requests into one call. The
    bullet requests must each go in their own call, bottom-up, because
    createParagraphBullets renumbers everything after its range.

    Mutates each row with its start/end indices, which group_runs then uses.
    """
    body = "".join(f"{r['text']}\n" for r in rows)
    if not body:
        return [], []

    # Text inserted after a list paragraph joins that list, so the detach is
    # bundled in right behind the insert. Without it the content renders as a
    # continuation of the heading numbering and the headings above lose their
    # HEADING_N styles.
    reqs = [req_insert(at, body),
            req_delete_bullets(at, at + utf16len(body))]

    cursor = at
    for row in rows:
        n = utf16len(f"{row['text']}\n")
        row["start"], row["end"] = cursor, cursor + n
        kind = row["kind"]

        if kind == "ph":
            reqs.append(req_named_style(cursor, cursor + n, "NORMAL_TEXT"))
            reqs.append(req_text_style(cursor, cursor + n, bold=True,
                                       size=PARA_HEADING_SIZE))
            reqs.append(req_indent_flat(cursor, cursor + n))
        elif kind == "li":
            reqs.append(req_named_style(cursor, cursor + n, "NORMAL_TEXT"))
            reqs.append(req_text_style(cursor, cursor + n))
            reqs.append(req_indent_for_inference(cursor, cursor + n, row["level"]))
        elif kind == "sig":
            reqs.append(req_named_style(cursor, cursor + n, "NORMAL_TEXT"))
            reqs.append(req_text_style(cursor, cursor + n))
            reqs.append(req_indent_flat(cursor, cursor + n))
            reqs.append(req_border_bottom(cursor, cursor + n))
        else:  # plain paragraph
            reqs.append(req_named_style(cursor, cursor + n, "NORMAL_TEXT"))
            reqs.append(req_text_style(cursor, cursor + n))
            reqs.append(req_indent_flat(cursor, cursor + n))
        cursor += n

    bullets = [req_bullets(run[0]["start"], run[-1]["end"] - 1, LIST_PRESET)
               for run in group_runs(rows)]
    return reqs, bullets


def _insert_text_rows(api, rows, at):
    """Insert and bullet one run of text rows immediately.

    Used for blocks that must be applied on their own — currently only those
    containing a table, since insertTable's result indices are unpredictable.
    Everything else goes through _plan_text_rows and is batched in bulk.
    """
    reqs, bullets = _plan_text_rows(rows, at)
    if not reqs:
        return
    api.batch(reqs)
    for req in reversed(bullets):
        api.batch([req])


def _load_char_widths(path):
    """Advance width per character, in em, read from a font file.

    Returns {} if the font or fontTools is unavailable, in which case
    text_width_pt falls back to a flat per-character estimate.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return {}
    try:
        font = TTFont(path)
    except Exception:
        return {}
    upm = font["head"].unitsPerEm
    glyphs = font.getGlyphSet()
    cmap = font["cmap"].getBestCmap()
    widths = {}
    for code, name in cmap.items():
        try:
            widths[chr(code)] = glyphs[name].width / upm
        except Exception:
            continue
    return widths


CHAR_WIDTHS = _load_char_widths(NUNITO_WIDTHS_SOURCE)
# The header row is rendered bold and bold glyphs are wider, so measuring it with
# regular widths under-sizes the column — which is exactly what wrapped the
# "Article" header to "Articl/e".
CHAR_WIDTHS_BOLD = _load_char_widths(
    NUNITO_WIDTHS_SOURCE.replace("Nunito-Regular", "Nunito-Bold"))


def text_width_pt(text: str, size_pt: float, bold: bool = False) -> float:
    """Rendered width of a string in points, from real glyph advances."""
    table = (CHAR_WIDTHS_BOLD or CHAR_WIDTHS) if bold else CHAR_WIDTHS
    return sum(
        table.get(ch, TABLE_CHAR_W_FALLBACK_EM) * size_pt for ch in text
    )


def compute_column_widths(rows, n_cols):
    """Proportional column widths in points, sized to the content.

    Narrow columns get exactly enough width that their widest single WORD fits on
    one line — measured with real glyph advances, because an averaged
    per-character estimate makes wide words ("Membership", "Ambassadors") come
    out narrow enough to wrap their last letter. The column carrying the most
    text absorbs whatever page width is left.

    Returns a list of widths in points, summing to TABLE_TEXT_WIDTH_PT.
    """
    def widest_word_pt(col):
        widest = 0.0
        for i, r in enumerate(rows):
            cell = r[col] if col < len(r) else ""
            # Row 0 is the header and is rendered bold — measure it that way, or
            # the column comes out too narrow and the header wraps.
            bold = (i == 0)
            for word in (cell or "").split():
                widest = max(widest, text_width_pt(word, BODY_SIZE, bold=bold))
        return widest + TABLE_CELL_PADDING_PT

    total_chars = [
        sum(len(r[c]) if c < len(r) else 0 for r in rows) for c in range(n_cols)
    ]
    # The column with the most text is the one worth giving the slack to.
    main = total_chars.index(max(total_chars)) if any(total_chars) else 0

    widths = [0.0] * n_cols
    for c in range(n_cols):
        if c == main:
            continue
        # Cap narrow columns at half the page so one very long word cannot
        # squeeze the main column out.
        widths[c] = max(TABLE_MIN_COL_PT,
                        min(widest_word_pt(c), TABLE_TEXT_WIDTH_PT / 2))

    widths[main] = TABLE_TEXT_WIDTH_PT - sum(widths[c]
                                             for c in range(n_cols) if c != main)
    # The main column must still fit its own widest word, or it will wrap
    # mid-word — the very thing this function exists to prevent.
    need = widest_word_pt(main)
    if widths[main] < need:
        deficit = need - widths[main]
        # Take the shortfall from the widest narrow column, down to the minimum.
        for c in sorted((c for c in range(n_cols) if c != main),
                        key=lambda c: -widths[c]):
            give = min(deficit, widths[c] - TABLE_MIN_COL_PT)
            if give <= 0:
                continue
            widths[c] -= give
            widths[main] += give
            deficit -= give
            if deficit <= 0:
                break
    if widths[main] < TABLE_MIN_COL_PT:
        return [TABLE_TEXT_WIDTH_PT / n_cols] * n_cols
    return widths


def _insert_table(api, row, at):
    """Insert a table and fill its cells.

    Cell indices only exist once the table does, so this is inherently two
    round-trips: create, then re-read and fill. Cells are filled in reverse
    index order so earlier insertions do not shift later targets.

    insertTable claims a paragraph at its insertion point, and if that point is
    the boundary right after a heading, the paragraph it claims INHERITS that
    heading's HEADING_N style and its list membership. The result is an empty
    numbered heading that consumes a number and shifts every heading after it.

    So a plain NORMAL_TEXT paragraph is created first and the table is inserted
    AT it (not after it), giving insertTable a neutral, already-detached
    paragraph to claim instead of manufacturing one from the heading.
    """
    rows = row["rows"]
    n_rows = len(rows)
    n_cols = max(len(r) for r in rows)
    rows = [list(r) + [""] * (n_cols - len(r)) for r in rows]

    # The anchor paragraph and its cleanup all use known indices, so they ride in
    # one batch. insertTable must follow separately: it restructures the document
    # and the cell indices only exist afterwards.
    api.batch([req_insert(at, "\n"),
               req_delete_bullets(at, at + 1),
               req_named_style(at, at + 1, "NORMAL_TEXT"),
               req_indent_flat(at, at + 1)])

    api.batch([{"insertTable": {
        "location": {"index": at}, "rows": n_rows, "columns": n_cols}}])

    # Re-read to find this table: it is the first table at or after `at`.
    doc = api.get()
    target = None
    table_start = None
    for el in doc["body"]["content"]:
        if "table" in el and el["startIndex"] >= at:
            target = el["table"]
            table_start = el["startIndex"]
            break
    if target is None:
        print(f"  warning: could not locate inserted table at {at}")
        return

    # Size the columns before filling them. Docs makes every column equal, which
    # leaves a 7-character "Article" column as wide as a 358-character
    # "Definition" one.
    widths = compute_column_widths(rows, n_cols)
    reqs = [{
        "updateTableColumnProperties": {
            "tableStartLocation": {"index": table_start},
            "columnIndices": [c],
            "tableColumnProperties": {
                "widthType": "FIXED_WIDTH",
                "width": {"magnitude": widths[c], "unit": "PT"},
            },
            "fields": "widthType,width",
        }
    } for c in range(n_cols)]
    print("    column widths: "
          + ", ".join(f"{w:.0f}pt" for w in widths))

    # Cell text goes in the SAME batch as the column widths. Both were computed
    # from the single api.get() above, and column widths do not move text
    # indices. Cells are filled in reverse index order so an earlier insertion
    # never shifts a later target.
    # Columns holding nothing but short cross-references ("1.1", "13.2.3") read
    # better centred than ragged along a wide-ish column. Detected from content
    # rather than hard-coded to an index, so it holds for any table: a column
    # qualifies when every non-empty body cell is a bare section number.
    centred = set()
    for c in range(n_cols):
        body = [(r[c] or "").strip() for r in rows[1:] if c < len(r)]
        filled = [v for v in body if v]
        if filled and all(re.fullmatch(r"\d+(\.\d+)*", v) for v in filled):
            centred.add(c)
    if centred:
        print(f"    centred column(s): {sorted(centred)}")

    inserts = []
    for r, drow in enumerate(target["tableRows"]):
        for c, dcell in enumerate(drow["tableCells"]):
            if r >= len(rows) or c >= len(rows[r]):
                continue
            txt = (rows[r][c] or "").strip()
            if not txt:
                continue
            start = dcell["content"][0]["startIndex"]
            inserts.append((start, txt, r == 0))
            if c in centred:
                # Alignment is a paragraph property, so it can be set on the
                # cell's existing empty paragraph before the text lands in it.
                reqs.append({"updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": start + 1},
                    "paragraphStyle": {"alignment": "CENTER"},
                    "fields": "alignment"}})

    for start, txt, bold in sorted(inserts, key=lambda x: -x[0]):
        reqs.append(req_insert(start, txt))
        reqs.append(req_text_style(start, start + utf16len(txt), bold=bold))
    api.batch(reqs)


def _spacing_requests(doc, first_section_start):
    """Line spacing for EVERY paragraph, including table cells.

    Separate from the indent pass because that one only visits bulleted
    paragraphs, whereas Docs' loose 1.15 default applies everywhere — body
    paragraphs and table cells included — and is the single biggest reason the
    generated Doc runs much longer than the LaTeX PDF.
    """
    reqs = []

    def walk(content, in_table=False):
        for el in content:
            para = el.get("paragraph")
            if para:
                style = {"lineSpacing": LINE_SPACING}
                fields = ["lineSpacing"]
                named = para["paragraphStyle"].get("namedStyleType", "")
                is_heading = named.startswith("HEADING_")
                if in_table:
                    pass  # table cells stay tight against the cell border
                elif is_heading and not para.get("bullet"):
                    # An UNBULLETED heading is a starred (unnumbered) one. The
                    # indent pass only visits bulleted paragraphs, so without
                    # this the sole starred heading in the constitution would be
                    # the one heading in the document with no spacing at all.
                    level = int(named[-1])
                    style["spaceAbove"] = {
                        "magnitude": HEADING_SPACE_ABOVE_PT.get(level, 8),
                        "unit": "PT"}
                    style["spaceBelow"] = {
                        "magnitude": HEADING_SPACE_BELOW_PT, "unit": "PT"}
                    style["spacingMode"] = SPACING_MODE
                    fields += ["spaceAbove", "spaceBelow", "spacingMode"]
                    # A starred section is still a top-level section, so it takes
                    # a page of its own too — unless it opens the document, which
                    # is exactly where the constitution's one starred section
                    # sits.
                    if level == PAGE_BREAK_BEFORE_LEVEL:
                        style["pageBreakBefore"] = (
                            el["startIndex"] != first_section_start)
                        fields.append("pageBreakBefore")
                elif not para.get("bullet") and not is_heading:
                    # Body paragraph. Bulleted paragraphs and numbered headings
                    # get their spacing in the indent pass below.
                    style["spaceAbove"] = {"magnitude": 0, "unit": "PT"}
                    style["spaceBelow"] = {
                        "magnitude": PARA_SPACE_BELOW_PT, "unit": "PT"}
                    style["spacingMode"] = SPACING_MODE
                    fields += ["spaceAbove", "spaceBelow", "spacingMode"]
                reqs.append({"updateParagraphStyle": {
                    "range": {"startIndex": el["startIndex"],
                              "endIndex": el["endIndex"]},
                    "paragraphStyle": style,
                    "fields": ",".join(fields)}})
            elif el.get("table"):
                for row in el["table"]["tableRows"]:
                    for cell in row["tableCells"]:
                        walk(cell["content"], in_table=True)

    walk(doc["body"]["content"])
    return reqs


def reindent(api):
    """Final pass: tighten indents, left-align heading numbers, fix spacing.

    Runs last, and reads nestingLevel back from the document rather than
    recomputing it, so the indent always matches the glyph Docs actually
    assigned. Safe after the fact because nestingLevel is already frozen.
    """
    doc = api.get()
    lists = doc.get("lists", {})
    heading_counters: dict = {}

    # Line spacing for every paragraph, keyed by start index so the per-bullet
    # styling below can MERGE into the same request instead of emitting a second
    # updateParagraphStyle for the same range. The quota counts write requests,
    # not batches, so collapsing two requests per paragraph into one is a direct
    # halving of the most expensive pass in the run.
    # Which top-level heading comes FIRST in the document? That one gets no page
    # break; every other one does.
    #
    # This has to be decided up front by scanning the document, not by a counter
    # threaded through the two styling paths. Those paths do not run in document
    # order relative to each other — _spacing_requests walks everything while the
    # loop below visits only bulleted paragraphs — so a shared counter gets
    # claimed by whichever path happens to run first and inverts the result.
    first_section_start = None
    for el in doc["body"]["content"]:
        p = el.get("paragraph")
        if not p:
            continue
        if p["paragraphStyle"].get("namedStyleType", "") == \
                f"HEADING_{PAGE_BREAK_BEFORE_LEVEL}":
            text = "".join(r["textRun"]["content"] for r in p["elements"]
                           if "textRun" in r).strip()
            if text:
                first_section_start = el["startIndex"]
                break

    spacing_by_start = {}
    for req in _spacing_requests(doc, first_section_start):
        ups = req["updateParagraphStyle"]
        spacing_by_start[ups["range"]["startIndex"]] = ups

    reqs = []
    warned = set()

    # Which content items START a list run? Those carry the heading-to-content
    # gap, since spacing must be expressed as space ABOVE a paragraph (spaceBelow
    # is ignored on list items — see the note by HEADING_SPACE_ABOVE_PT).
    paras = [el for el in doc["body"]["content"] if el.get("paragraph")]

    def is_content_item(el):
        p = el["paragraph"]
        return bool(p.get("bullet")) and not p["paragraphStyle"].get(
            "namedStyleType", "").startswith("HEADING_")

    starts_run = set()
    for i, el in enumerate(paras):
        if not is_content_item(el):
            continue
        this_list = el["paragraph"]["bullet"]["listId"]
        prev = paras[i - 1] if i > 0 else None
        if (prev is None or not is_content_item(prev)
                or prev["paragraph"]["bullet"]["listId"] != this_list):
            starts_run.add(el["startIndex"])

    for el in doc["body"]["content"]:
        para = el.get("paragraph")
        if not para or not para.get("bullet"):
            continue
        start, end = el["startIndex"], el["endIndex"]
        named = para["paragraphStyle"].get("namedStyleType", "")
        is_heading = named.startswith("HEADING_")

        style = {}
        fields = ["indentStart", "indentFirstLine"]
        bullet = para["bullet"]

        if is_heading:
            level = int(named[-1])
            # Numbers flush left at the margin, titles in one shared column.
            # indentFirstLine is per-paragraph, so setting it to this number's
            # own width cancels the forced END alignment. See glyph_width().
            number = render_glyph(lists, bullet["listId"],
                                  bullet.get("nestingLevel", 0), heading_counters)
            first_line = glyph_width(number, HEADING_SIZES.get(level, 11))
            # Per-level title column, as LaTeX does it. A number wider than its
            # level's nominal column (a two-digit article, say) pushes its own
            # title right rather than being crowded — so the gap after the
            # number never collapses, at the cost of that one title starting
            # slightly later than its siblings.
            indent_start = max(HEADING_TITLE_COL_PT.get(level, 42),
                               first_line + HEADING_NUM_GAP_PT)
            style["spaceAbove"] = {
                "magnitude": HEADING_SPACE_ABOVE_PT.get(level, 8), "unit": "PT"}
            style["spaceBelow"] = {"magnitude": 0, "unit": "PT"}
            # Without NEVER_COLLAPSE the two above are silently discarded,
            # because a numbered heading is a list item. See SPACING_MODE.
            style["spacingMode"] = SPACING_MODE
            fields += ["spaceAbove", "spaceBelow", "spacingMode"]

            # Each article starts a new page, except the first — a break there
            # would open the document with a blank page. Set explicitly on every
            # heading (False for deeper levels) so a re-run cannot leave a stale
            # break behind from an earlier structure.
            style["pageBreakBefore"] = (level == PAGE_BREAK_BEFORE_LEVEL
                                        and start != first_section_start)
            fields.append("pageBreakBefore")
        else:
            level = bullet.get("nestingLevel", 0) + 1
            indent_start = level * FINAL_STEP_PT
            first_line = indent_start - HANGING_PT
            # Compensate for END-aligned content levels, read from the list
            # itself so a preset change cannot silently misalign a level.
            nls = (lists.get(bullet["listId"], {})
                   .get("listProperties", {}).get("nestingLevels", []))
            i = level - 1
            if i < len(nls) and nls[i].get("bulletAlignment") == "END":
                first_line += END_ALIGN_NUDGE_PT
            # The first item of a run carries the heading-to-content gap; the
            # rest get the LaTeX's small itemsep.
            above = (HEADING_SPACE_BELOW_PT if start in starts_run
                     else LIST_SPACE_BELOW_PT.get(level, 0))
            style["spaceAbove"] = {"magnitude": above, "unit": "PT"}
            style["spaceBelow"] = {"magnitude": 0, "unit": "PT"}
            style["spacingMode"] = SPACING_MODE
            fields += ["spaceAbove", "spaceBelow", "spacingMode"]

        style["indentStart"] = {"magnitude": indent_start, "unit": "PT"}
        style["indentFirstLine"] = {"magnitude": first_line, "unit": "PT"}

        # Fold this paragraph's line spacing in rather than sending it
        # separately. Any field set here wins over the spacing pass's value,
        # which only ever sets lineSpacing on a bulleted paragraph.
        pending = spacing_by_start.pop(start, None)
        if pending:
            merged = dict(pending["paragraphStyle"])
            merged.update(style)
            style = merged
            fields = sorted(set(fields) | set(pending["fields"].split(",")))

        reqs.append({"updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": style,
            "fields": ",".join(fields)}})

        # The number glyph carries its own text style, separate from the
        # paragraph's, so heading numbers stay grey without this.
        if is_heading:
            reqs.append(req_text_style(start, end, bold=True,
                                       size=HEADING_SIZES.get(level, 11)))

    # Whatever did not merge — body paragraphs and table cells, which the bullet
    # loop never visits — still needs its line spacing.
    reqs.extend({"updateParagraphStyle": ups} for ups in spacing_by_start.values())

    print(f"Pass 4: final indent/style, {len(reqs)} requests …")
    for i in range(0, len(reqs), PASS4_CHUNK):
        api.batch(reqs[i:i + PASS4_CHUNK])


def verify(api, headings, blocks):
    """Read the document back and check the heading numbers Docs generated.

    Heading numbers are compared against independently computed expectations, so
    a silently restarted counter is caught rather than assumed correct.
    """
    doc = api.get()
    lists = doc.get("lists", {})
    counters: dict = {}

    actual = []
    for el in doc["body"]["content"]:
        p = el.get("paragraph")
        if not p:
            continue
        named = p["paragraphStyle"].get("namedStyleType", "")
        if not named.startswith("HEADING_"):
            continue
        txt = "".join(r["textRun"]["content"] for r in p["elements"]
                      if "textRun" in r).rstrip("\n")
        bullet = p.get("bullet")
        glyph = (render_glyph(lists, bullet["listId"],
                              bullet.get("nestingLevel", 0), counters)
                 if bullet else None)
        actual.append((int(named[-1]), txt, glyph))

    expected = expected_heading_numbers(headings)
    print("\n=== Heading verification ===")
    problems = []

    # Structural mismatches are reported FIRST and separately from numbering.
    # A single stray heading paragraph shifts every position after it, so
    # comparing purely by index turns one bug into hundreds of misleading
    # "mismatch" lines and buries the actual cause.
    if len(actual) != len(headings):
        problems.append(
            f"STRUCTURAL: document has {len(actual)} heading paragraphs but the "
            f"source has {len(headings)}")
        blanks = [i for i, (_, t, _) in enumerate(actual) if not t.strip()]
        if blanks:
            problems.append(
                f"STRUCTURAL: {len(blanks)} EMPTY heading paragraph(s) at "
                f"position(s) {blanks[:10]} — these consume numbers")

    for i, (h, want) in enumerate(zip(headings, expected)):
        if i >= len(actual):
            problems.append(f"missing heading: {h['title'][:50]}")
            continue
        got_level, got_txt, got_glyph = actual[i]
        want_glyph = None if want is None else f"{want}."
        if got_txt != h["title"]:
            problems.append(
                f"text at {i}: got {got_txt[:40]!r}, want {h['title'][:40]!r}")
        elif got_level != h["level"]:
            problems.append(
                f"level at {i} ({h['title'][:35]}): got H{got_level}, "
                f"want H{h['level']}")
        elif got_glyph != want_glyph:
            problems.append(
                f"number at {i} ({h['title'][:35]}): got {got_glyph}, "
                f"want {want_glyph}")

    # Content check. The heading spine can verify perfectly while the content is
    # silently wrong: an unbulleted run just reads as ordinary prose. Run
    # detection is the most fragile step now that the text inserts share a single
    # batch, so it gets its own assertion rather than being eyeballed.
    want_items = sum(1 for rows in blocks.values()
                     for r in rows if r["kind"] == "li")
    got_items = unbulleted = 0
    for el in doc["body"]["content"]:
        p = el.get("paragraph")
        if not p:
            continue
        text = "".join(r["textRun"]["content"] for r in p["elements"]
                       if "textRun" in r).strip()
        if not text or p["paragraphStyle"].get(
                "namedStyleType", "").startswith("HEADING_"):
            continue
        if p.get("bullet"):
            got_items += 1
        elif p["paragraphStyle"].get("indentStart", {}).get("magnitude", 0) > 0:
            unbulleted += 1

    if got_items != want_items:
        problems.append(f"CONTENT: {got_items} bulleted list items in the "
                        f"document but {want_items} in the source")
    if unbulleted:
        problems.append(f"CONTENT: {unbulleted} indented paragraph(s) never got "
                        f"bullets — a list run was missed")

    if problems:
        print(f"  {len(problems)} problem(s):")
        for p in problems[:25]:
            print(f"    FAIL {p}")
        if len(problems) > 25:
            print(f"    … and {len(problems) - 25} more")
    else:
        print(f"  all {len(headings)} headings correct "
              f"(numbers, levels, titles) and {got_items} list items bulleted")
    return not problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    doc_id = os.environ.get("GOOGLE_DOC_ID", "")
    if len(args) == 2:
        doc_id, json_path = args[0], Path(args[1])
    elif len(args) == 1 and doc_id:
        json_path = Path(args[0])
    else:
        print("Usage: python json_to_docs.py <DOCUMENT_ID> <input.json> "
              "[--articles=N]")
        sys.exit(1)

    # --articles=N writes only the first N top-level sections. A full policy
    # manual run is hundreds of API calls paced against a 60/minute quota, so
    # checking formatting against the whole document is a slow way to iterate.
    limit = None
    for f in flags:
        if f.startswith("--articles="):
            limit = int(f.split("=", 1)[1])

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if limit is not None:
        # Starred sections are dropped entirely here. In the constitution that is
        # "Terms & Definitions", which is one large table and tells you nothing
        # about how the numbered articles are laid out — the point of --articles
        # is a fast formatting check.
        kept, seen = [], 0
        for node in data:
            if node.get("type") == "section":
                if node.get("starred"):
                    continue
                seen += 1
                if seen > limit:
                    break
            kept.append(node)
        data = kept
        print(f"--articles={limit}: keeping {len(data)} top-level node(s), "
              f"starred sections skipped")

    creds = Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    api = Api(build("docs", "v1", credentials=creds), doc_id)

    headings, blocks = flatten(data)
    n_rows = sum(len(v) for v in blocks.values())
    print(f"{json_path.name}: {len(headings)} headings, {n_rows} content rows")

    doc = api.get()
    end_index = doc["body"]["content"][-1]["endIndex"]
    if end_index > 2:
        api.batch([{"deleteContentRange": {
            "range": {"startIndex": 1, "endIndex": end_index - 1}}}])
        print(f"Cleared {end_index - 1} characters.")

    insert_heading_spine(api, headings)
    insert_content(api, headings, blocks)
    reindent(api)
    ok = verify(api, headings, blocks)

    print(f"\n{api.calls} API calls, {api.requests} write requests, "
          f"{api.throttled} throttled, {api.slept:.0f}s sleeping. "
          f"{'OK' if ok else 'PROBLEMS ABOVE'}")
    print(f"  https://docs.google.com/document/d/{doc_id}/edit")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
