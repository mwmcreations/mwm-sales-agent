"""PATCH #136 — attribution on the first inbound row (pure rules)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attribution_sheet as a

PASS = FAIL = 0


def ok(c, label):
    global PASS, FAIL
    if c:
        PASS += 1; print("  ok   " + label)
    else:
        FAIL += 1; print("  FAIL " + label)


FULL = ["Date", "Time", "Name", "Business", "Phone", "Email", "Service Interest",
        "Status", "Appt", "Notes", "Follow-up", "Transcript", "Source", "Last Contact",
        "Outreach Channel", "Outreach Msg", "WhatsApp Status", "Summary", "Booked",
        "Temp", "Ad ID", "Ad Campaign", "CTWA Click ID"]


def r(phone, u="", v="", w="", n=14):
    row = ["2026-09-20", "10:00 AM", "", "", phone] + [""] * (n - 5)
    if u or v or w:
        row += [""] * (20 - len(row)) + [u, v, w]
    return row


print("\n== attr_cells")
ok(a.attr_cells({"ad_id": "120", "utm_campaign": "AD_R1", "ctwa_clid": "ARx"}) == ["120", "AD_R1", "ARx"], "ad lead -> three cells")
ok(a.attr_cells({"ctwa_clid": "ARx"}) == ["", "", "ARx"], "click id alone still counts")
ok(a.attr_cells({"utm_campaign": "organic?"}) is None, "campaign text without ids is NOT attribution")
ok(a.attr_cells({}) is None and a.attr_cells(None) is None, "organic / missing -> None")

print("\n== keys and row lookup")
ok(a.clean_phone("whatsapp:+14075551234") == "14075551234", "whatsapp sender -> sheet phone")
ok(a.clean_phone("instagram:99") == "instagram:99", "instagram sender kept as-is")
ok(a.candidate_keys("14075551234")[0] == "whatsapp:+14075551234", "WA row -> whatsapp:+ key first")
ok(a.candidate_keys("instagram:99") == ["instagram:99"], "IG row -> its own key only")
ok(a.candidate_keys("") == [], "blank phone -> no keys")
rows = [FULL, r("111"), r("222"), r("111")]
ok(a.find_row(rows, "111") == 3, "last matching row wins (same as log_lead_to_sheets)")
ok(a.find_row([["Phone", "", "", "", "111"]], "111") is None, "header row is never matched")

print("\n== plan_stamp (first inbound)")
up = a.plan_stamp(rows, "222", ["120", "AD_R1", "ARx"])
ok(up == [("U", 3, "120"), ("V", 3, "AD_R1"), ("W", 3, "ARx")], "short 14-col row gets U/V/W")
ok(a.plan_stamp(rows, "333", ["120", "", ""]) == [], "no row yet -> nothing (first-contact write carries it)")
ok(a.plan_stamp(rows, "222", None) == [], "organic -> nothing")
filled = [FULL, r("222", u="999", v="Old", w="Clk")]
ok(a.plan_stamp(filled, "222", ["120", "AD_R1", "ARx"]) == [], "never overwrites existing values")
part = [FULL, r("222", u="999")]
ok(a.plan_stamp(part, "222", ["120", "AD_R1", "ARx"]) == [("V", 2, "AD_R1"), ("W", 2, "ARx")], "fills only the blanks")
ok(a.plan_stamp(rows, "222", ["120", "", ""]) == [("U", 3, "120")], "empty values are not written")

print("\n== plan_backfill")
recs = {"whatsapp:+111": {"ad_id": "120A", "utm_campaign": "AD_R1", "ctwa_clid": "C1"},
        "instagram:77": {"ad_id": "120B", "ctwa_clid": "R7"},
        "whatsapp:+222": {"source": "WhatsApp"}}


def lookup(p):
    for k in a.candidate_keys(p):
        if k in recs:
            return recs[k]
    return None


rows = [FULL, r("111"), r("222"), r("instagram:77"), r("444"), r("111", u="keep")]
up, rep = a.plan_backfill(rows, lookup)
ok(("U", 2, "120A") in up and ("W", 2, "C1") in up, "WA row backfilled from the lead record")
ok(("U", 4, "120B") in up and ("W", 4, "R7") in up, "IG row backfilled")
ok(not any(x[1] == 3 for x in up), "organic record -> row untouched")
ok(not any(x[1] == 5 for x in up), "no record -> row untouched")
ok(not any(x[1] == 6 for x in up), "row with anything already in U/V/W is left alone")
ok(len(rep) == 2 and rep[0]["phone_tail"] == "111" and rep[1]["has_click_id"], "report lists what it would fill")
ok(a.plan_backfill([FULL], lookup) == ([], []), "empty tab -> nothing")

print("\n== header_fix")
ok(a.header_fix(FULL, FULL) is None, "full header -> nothing to do")
ok(a.header_fix(FULL[:20], FULL) == ("U", ["Ad ID", "Ad Campaign", "CTWA Click ID"]), "A:T tab -> append U/V/W")
ok(a.header_fix(FULL[:21], FULL) == ("V", ["Ad Campaign", "CTWA Click ID"]), "stopped at U -> finish V/W")
bad = FULL[:20] + ["Something Else", "x", "y"]
try:
    a.header_fix(bad, FULL); ok(False, "occupied U must refuse")
except ValueError:
    ok(True, "someone else's column at U -> refuses, never overwrites")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
