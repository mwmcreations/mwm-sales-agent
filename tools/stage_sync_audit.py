"""Stage-sync reconciler (Jul 8 2026, Bug #1 follow-through).

Scans every monthly tab for rows where the booking flag and the Status column
disagree ("Appointment Booked: Y" but Status still in a pre-booking stage),
prints a discrepancy report, and optionally repairs.

INVARIANT: never writes a Client stage — lead->Client happens ONLY via the
Stripe webhook (Michael, Jul 8 2026).

Usage:
    GOOGLE_SERVICE_ACCOUNT_JSON=... GOOGLE_SHEETS_ID=... python3 tools/stage_sync_audit.py           # report only
    ... python3 tools/stage_sync_audit.py --repair                                                    # report + fix
"""
import json, os, sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

STALE_STATUSES = {
    "", "interested — no booking yet", "interested - no booking yet",
    "new lead", "contacted", "warm", "hot", "qualified", "follow-up needed",
}
BOOKED_STATUS = "✅ Studio Visit Booked"
CLIENT_MARKERS = ("client",)  # never touch anything already in a client stage


def main():
    repair = "--repair" in sys.argv
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "") or os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    sheet_id = os.getenv("GOOGLE_SHEETS_ID", "") or os.getenv("SHEETS_LEADS_ID", "")
    if not creds_json or not sheet_id:
        sys.exit("Set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEETS_ID")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_json), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    svc = build("sheets", "v4", credentials=creds)

    meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
    tabs = [s["properties"]["title"] for s in meta["sheets"]]
    total_rows = 0
    discrepancies = []

    for tab in tabs:
        try:
            rows = svc.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=f"'{tab}'!A:T").execute().get("values", [])
        except Exception:
            continue
        if not rows:
            continue
        headers = rows[0]
        try:
            name_i = headers.index("Name")
            status_i = headers.index("Status")
            appt_i = headers.index("Appointment Booked")
        except ValueError:
            continue  # not a lead tab
        for rn, row in enumerate(rows[1:], start=2):
            total_rows += 1
            get = lambda i: row[i].strip() if len(row) > i else ""
            if get(appt_i).upper() not in ("Y", "YES"):
                continue
            status = get(status_i)
            sl = status.lower()
            if any(m in sl for m in CLIENT_MARKERS):
                continue  # client stages are Stripe-owned; leave alone
            if sl in STALE_STATUSES or "no booking" in sl:
                discrepancies.append((tab, rn, get(name_i), status or "(blank)"))

    print(f"Scanned {total_rows} lead rows across {len(tabs)} tabs")
    print(f"DISCREPANCIES (Booked:Y but stale Status): {len(discrepancies)}")
    for tab, rn, name, status in discrepancies:
        print(f"  {tab} row {rn}: {name!r} — Status={status!r}")

    if repair and discrepancies:
        data = [{"range": f"'{t}'!H{rn}", "values": [[BOOKED_STATUS]]} for t, rn, _, _ in discrepancies]
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW", "data": data}).execute()
        print(f"REPAIRED {len(data)} rows -> {BOOKED_STATUS!r}")
    elif discrepancies:
        print("(report-only — re-run with --repair to fix)")


if __name__ == "__main__":
    main()
