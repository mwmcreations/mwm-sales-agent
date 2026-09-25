"""PATCH #136 wiring — attribution on the first inbound row (app.py).

Runs the real function bodies from app.py against a fake Sheets service.
"""
import ast, os, sys, re
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attribution_sheet as _attr_sheet

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
PASS = FAIL = 0


def ok(c, label):
    global PASS, FAIL
    if c:
        PASS += 1; print("  ok   " + label)
    else:
        FAIL += 1; print("  FAIL " + label)


def fn_src(name):
    for n in TREE.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            n2 = ast.FunctionDef(**{**n.__dict__, "decorator_list": []})
            return ast.unparse(n2)
    raise KeyError(name)


print("\n== static wiring")
ok("import attribution_sheet as _attr_sheet" in SRC, "module imported")
ok(SRC.count("_stamp_attribution_async(") == 3, "stamp called from WA + IG (plus its def)")
wa_first = SRC.index("log_new_contact_to_sheets(sender)\n            except Exception as e:\n                print(f\"\\u26a0")
wa_ref = SRC.index("_stamp_attribution_async(sender)   # PATCH #136")
ok(wa_ref > wa_first, "WA: stamp runs AFTER the first-contact row is written")
blk = SRC[SRC.index("if _wa_referral:\n                lead_data[sender][\"utm_source\"]"):wa_ref]
ok("except" not in blk, "WA: stamp sits inside the `if _wa_referral:` block")
ig_ref = SRC.index("_stamp_attribution_async(_ig_sender)")
ig_blk = SRC[SRC.rindex("if _ig_ref and", 0, ig_ref):ig_ref]
ok("lead_data[_ig_sender][\"ctwa_clid\"]" in ig_blk, "IG: stamp runs after the referral is stored")
ok("@app.route('/admin/attribution-backfill', methods=['GET'])" in SRC, "backfill endpoint registered")
ok(re.search(r"def log_lead_to_sheets\(lead_info: str, sender: str, history: list = None\):", SRC) is not None,
   "log_lead_to_sheets signature untouched")

# ---- fakes ---------------------------------------------------------------
ET = timezone(timedelta(hours=-4))


class _Exec:
    def __init__(self, fn): self.fn = fn
    def execute(self, num_retries=0): return self.fn()


class FakeSheets:
    def __init__(self, rows, fail=False):
        self.rows = rows; self.fail = fail
        self.updates, self.batches, self.appends = [], [], []
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, spreadsheetId, range):
        if self.fail:
            return _Exec(lambda: (_ for _ in ()).throw(RuntimeError("403 sheets")))
        return _Exec(lambda: {"values": [list(r) for r in self.rows]})
    def update(self, spreadsheetId, range, valueInputOption, body):
        self.updates.append((range, body["values"][0])); return _Exec(lambda: {})
    def batchUpdate(self, spreadsheetId, body):
        self.batches.append(body["data"]); return _Exec(lambda: {})
    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        self.appends.append(body["values"][0]); return _Exec(lambda: {})


class Tally:
    def __init__(self): self.b = []
    def bump(self, k, v=""): self.b.append(k)


import pytz as _pytz_real  # noqa: E402  (present wherever app.py runs)

HDR = ["Date", "Time", "Name", "Business", "Phone", "Email", "Service Interest", "Status",
       "Appt Date & Time", "Notes", "Follow-up", "Transcript", "Source", "Last Contact Date",
       "Outreach Channel", "Outreach Message Sent", "WhatsApp Status", "Conversation Summary",
       "Appointment Booked", "Lead Temperature", "Ad ID", "Ad Campaign", "CTWA Click ID"]


def ns(svc, leads, errors):
    return {
        "_attr_sheet": _attr_sheet, "SHEETS_LEADS_ID": "sheet1", "lead_data": leads,
        "datetime": datetime, "pytz": _pytz_real, "TIMEZONE": "America/New_York",
        "get_sheets_service": lambda: svc, "ensure_monthly_tab": lambda *a: 1,
        "SHEET_HEADERS": HDR, "_TALLY": Tally(),
        "_report_error": lambda w, e, d="": errors.append((w, str(e))),
        "_lead_source_for": lambda s: "WhatsApp", "print": lambda *a, **k: None,
        "_LEAD_ROW_CONFIG_ALERTED": True,
    }


def load(name, g):
    exec(fn_src(name), g)
    return g[name]


print("\n== stamp_attribution_in_sheets")
tab_rows = [HDR, ["2026-09-25", "7:00 PM", "", "", "14075551234", "", "", "New Lead", "", "", "", "",
                  "WhatsApp", "2026-09-25"]]
svc = FakeSheets(tab_rows); errs = []
leads = {"whatsapp:+14075551234": {"ad_id": "120251044980110738", "utm_campaign": "Business Owners 25+",
                                   "ctwa_clid": "ARAkLx"}}
g = ns(svc, leads, errs); stamp = load("stamp_attribution_in_sheets", g)
res = stamp("whatsapp:+14075551234")
ok(res == {"ok": True, "stamped": 3}, "ad lead: three cells stamped")
data = svc.batches[0]
tab = datetime.now(ET).strftime("%b %Y")
ok(data[0]["range"] == f"'{tab}'!U2" and data[0]["values"] == [["120251044980110738"]], "Ad ID -> U on the lead's own row")
ok(data[2]["range"].endswith("W2") and data[2]["values"] == [["ARAkLx"]], "click id -> W")
ok("sheets.attr_stamped" in g["_TALLY"].b, "counter bumped for /health")
ok(svc.updates == [], "full header -> no header write")

svc = FakeSheets(tab_rows); g = ns(svc, {"whatsapp:+14075551234": {"source": "WhatsApp"}}, errs)
ok(load("stamp_attribution_in_sheets", g)("whatsapp:+14075551234") == {"ok": True, "why": "organic"}
   and svc.batches == [], "organic lead: no Sheets call at all")

short_hdr = [HDR[:20]] + tab_rows[1:]
svc = FakeSheets(short_hdr); g = ns(svc, leads, errs)
load("stamp_attribution_in_sheets", g)("whatsapp:+14075551234")
ok(svc.updates and svc.updates[0][0].endswith("!U1") and svc.updates[0][1] == ["Ad ID", "Ad Campaign", "CTWA Click ID"],
   "A:T tab: header repaired by appending U/V/W, nothing reordered")

svc = FakeSheets(tab_rows, fail=True); errs = []; g = ns(svc, leads, errs)
r = load("stamp_attribution_in_sheets", g)("whatsapp:+14075551234")
ok(r["ok"] is False and errs and "PATCH #136" in errs[0][0], "Sheets failure reported, never raised")

print("\n== first-contact row")


class SQ:
    OP_CREATE = "create"
    def enqueue(self, *a, **k): pass


for label, recs, want in (("ad lead", leads, 23), ("organic lead", {}, 14)):
    svc = FakeSheets([HDR]); g = ns(svc, recs, [])
    g.update({"_sq": SQ(), "_sq_alert": None, "_sq_persist": lambda: None})
    load("log_new_contact_to_sheets", g)("whatsapp:+14075551234")
    row = svc.appends[0] if svc.appends else []
    ok(len(row) == want, f"{label}: first-contact row is {want} columns")
    if want == 23:
        ok(row[20:] == ["120251044980110738", "Business Owners 25+", "ARAkLx"] and row[14:20] == [""] * 6,
           "U/V/W filled, O..T left blank")

print("\n== /admin/attribution-backfill")


class Req:
    def __init__(self, args): self.args = args


def jsonify(d): return d


def run_bf(args, rows, recs):
    svc = FakeSheets(rows); saved = {}
    g = ns(svc, recs, [])
    g.update({"request": Req(args), "jsonify": jsonify, "_admin_secret_ok": lambda s: s == "k",
              "_pg": type("P", (), {"save_state": staticmethod(lambda k, v: saved.__setitem__(k, v))})})
    out = load("admin_attribution_backfill", g)()
    return out, svc, saved


rows = [HDR,
        ["2026-09-10", "", "", "", "14070000001"],
        ["2026-09-14", "", "Ana", "", "14075551234"],
        ["2026-09-15", "", "", "", "instagram:77"] + [""] * 15 + ["keep", "", ""]]
recs = {"whatsapp:+14070000001": {"ad_id": "OLD"}, "whatsapp:+14075551234": leads["whatsapp:+14075551234"],
        "instagram:77": {"ad_id": "IG1"}}
out, svc, saved = run_bf({"secret": "nope"}, rows, recs)
ok(out[1] == 401 and svc.batches == [], "wrong secret -> 401, nothing read or written")
out, svc, saved = run_bf({"secret": "k", "tab": "Sep 2026", "since": "2026-09-12"}, rows, recs)
body = out[0]
ok(body["applied"] is False and svc.batches == [] and saved == {}, "dry run by default: nothing written")
ok(body["rows_to_fill"] == 1 and body["rows"][0]["row"] == 3, "since= filter drops the Sep 10 row; filled IG row skipped")
out, svc, saved = run_bf({"secret": "k", "tab": "Sep 2026", "since": "2026-09-12", "apply": "1"}, rows, recs)
ok(out[0]["applied"] and len(svc.batches[0]) == 3 and all("!" in d["range"] and d["range"].endswith("3") for d in svc.batches[0]),
   "apply=1 writes only that row's three cells")
ok(list(saved.values())[0]["cells"][0][:2] == ["U", 3], "undo record saved in pg before writing")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
