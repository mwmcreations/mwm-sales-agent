"""PATCH #136 — ad attribution on the FIRST inbound row of the leads sheet.

ERIC, Sep 23/25: `Ad ID` / `Ad Campaign` / `CTWA Click ID` (columns U/V/W of
"Maya Leads Report") were filled on almost no rows. His theory: they were only
written on full capture. Confirmed from the code:

  * the first-contact row (`log_new_contact_to_sheets`) wrote A..N only;
  * U/V/W were written only by `log_lead_to_sheets`, which runs on
    [LEAD CAPTURED] (name + service), so ~80% of leads never got them;
  * on WhatsApp the first-contact row is written BEFORE the referral payload is
    parsed, so even a same-turn write had nothing to put there.

The referral itself WAS being kept on the lead record (and so in Postgres),
which is what makes a backfill possible.

This module is pure (no Sheets, no Flask) so the rules can be tested. Rules:
  * never overwrite a non-empty cell; only fill blanks;
  * never reorder or rename columns; header repair only APPENDS missing names
    to the right, and refuses if something else already sits where they go;
  * organic leads (no ad_id and no click id) are left untouched.
"""

ATTR_HEADERS = ["Ad ID", "Ad Campaign", "CTWA Click ID"]
COL_U = 20   # 0-based index of column U
COLS = ("U", "V", "W")


def attr_cells(rec):
    """[ad_id, campaign, ctwa_clid] from a lead record, or None if organic."""
    if not isinstance(rec, dict):
        return None
    ad_id = str(rec.get("ad_id") or "").strip()
    ctwa = str(rec.get("ctwa_clid") or "").strip()
    if not ad_id and not ctwa:
        return None
    camp = str(rec.get("utm_campaign") or "").strip()
    return [ad_id, camp, ctwa]


def clean_phone(sender):
    return str(sender or "").replace("whatsapp:", "").replace("+", "")


def candidate_keys(phone_cell):
    """Lead-record keys that can own a sheet row's Phone cell."""
    p = str(phone_cell or "").strip()
    if not p:
        return []
    if p.startswith("instagram:"):
        return [p]
    keys = [f"whatsapp:+{p}", p, f"+{p}", f"whatsapp:{p}"]
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return out


def find_row(rows, phone):
    """0-based index of the LAST row whose Phone (col E) equals `phone`."""
    hit = None
    for i, row in enumerate(rows or []):
        if i == 0:
            continue  # header
        if len(row) >= 5 and str(row[4]) == str(phone):
            hit = i
    return hit


def _cell(row, idx):
    return str(row[idx]).strip() if len(row) > idx and row[idx] is not None else ""


def plan_stamp(rows, phone, cells):
    """Updates [(A1 col letter, row_number, value)] to stamp one lead.

    Empty list when: no attribution, no row for this phone yet, or every
    target cell is already filled.
    """
    if not cells:
        return []
    i = find_row(rows, phone)
    if i is None:
        return []
    row = rows[i]
    out = []
    for k, (col, val) in enumerate(zip(COLS, cells)):
        if val and not _cell(row, COL_U + k):
            out.append((col, i + 1, val))
    return out


def plan_backfill(rows, lookup):
    """Fill U/V/W on rows where ALL THREE are blank and the lead record has
    attribution. `lookup(phone_cell)` returns a lead record or None.
    Returns (updates, report) — report is one dict per filled row."""
    updates, report = [], []
    for i, row in enumerate(rows or []):
        if i == 0 or len(row) < 5:
            continue
        if any(_cell(row, COL_U + k) for k in range(3)):
            continue  # partly/fully filled: leave it alone
        rec = lookup(row[4])
        cells = attr_cells(rec)
        if not cells:
            continue
        for col, val in zip(COLS, cells):
            if val:
                updates.append((col, i + 1, val))
        report.append({"row": i + 1, "date": _cell(row, 0), "name": _cell(row, 2),
                       "phone_tail": str(row[4])[-4:], "ad_id": cells[0],
                       "campaign": cells[1], "has_click_id": bool(cells[2])})
    return updates, report


def header_fix(header_row, full_headers):
    """(start_col_letter, names_to_append) or None if nothing to do.
    Raises ValueError if U/V/W are occupied by other names (never overwrite)."""
    header = [str(h) for h in (header_row or [])]
    n = len(header)
    if n >= len(full_headers):
        for k, name in enumerate(ATTR_HEADERS):
            got = header[COL_U + k] if len(header) > COL_U + k else ""
            if got and got != name:
                raise ValueError(f"column {COLS[k]} holds {got!r}, expected {name!r}")
        return None
    for k in range(min(n, len(full_headers))):
        if header[k] and header[k] != full_headers[k] and k >= COL_U:
            raise ValueError(f"column {chr(65 + k)} holds {header[k]!r}")
    if n > 25:
        raise ValueError("header wider than Z; refusing")
    return chr(65 + n), list(full_headers[n:])
