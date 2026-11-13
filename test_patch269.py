"""PATCH #269 gate — a custom deal runs through the STANDARD studio-client
pipeline (portal account, the regular welcome email, lead record, alerts) on a
spec built from its own terms, never a new package. Weekly billing in the
footer, the deal's words for the term, extra lines in the written record;
the three packages' emails and dates do not move by a character. Then #267."""
import os
import re
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_package as sp       # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


mo3 = sp.PACKAGES[sp.STUDIO_PRICE_ID]
trial = sp.PACKAGES[sp.TRIAL_PRICE_ID]
hour = sp.PACKAGES[sp.HOUR_ONEOFF_PRICE_ID]
start = date(2026, 11, 6)
end = date(2027, 2, 5)
SHAWNIE = dict(label="MWM Partner Plan", hours=12, start=start, end=end,
               price_label="$350/week × 13 weeks", term_label="3 months", interval="week",
               cycle_amount=350, cycles=13, pace_note="4 hours a month",
               includes_note="Your monthly strategy session with Michael, and the editing of your story film, podcast episodes and short clips from those hours — ready to post",
               extra_notes=["Partner Program: every business owner you introduce who signs a plan adds studio hours to your account, on top of these, at no extra cost"])

# ── no new package ─────────────────────────────────────────────────────────
check("pkg.untouched", len(sp.PACKAGES) == 3 and sorted(s["kind"] for s in sp.PACKAGES.values())
      == ["studio_3mo", "studio_hour_oneoff", "studio_trial_1mo"] and len(sp.PACKAGE_NAMES) == 3)
check("pkg.values", mo3["hours"] == 12 and mo3["term_days"] == 90 and mo3["mrr"] == 1200 and mo3["grace_days"] == 0
      and trial["hours"] == 4 and trial["term_days"] == 30 and hour["hours"] == 1)

# ── the spec from the deal's own terms ─────────────────────────────────────
spec, t = sp.custom_spec(**SHAWNIE)
check("spec.shape", spec["kind"] == "custom" and spec["custom"] is True and spec["name"] == "MWM Partner Plan"
      and spec["hours"] == 12 and spec["term_days"] == 91 and spec["grace_days"] == 0
      and spec["recurring"] is True and spec["interval"] == "week" and spec["cycles"] == 13
      and spec["cycle_amount"] == 350 and spec["mrr"] == 1517 and spec["one_off"] == 0
      and spec["sheet_status"] == "Client — MWM Partner Plan" and spec["price_label"] == "$350/week × 13 weeks", str(spec)[:300])
check("spec.not_registered", sp.package_by_name("MWM Partner Plan") is None and "MWM Partner Plan" not in sp.PACKAGE_NAMES)
check("spec.term", t["start"] == start and t["term_end"] == end and t["booking_deadline"] == end, str(t))
s_m, _ = sp.custom_spec("Thing", 6, start, date(2027, 2, 6), interval="month", cycle_amount=600, cycles=3)
check("spec.monthly", s_m["recurring"] is True and s_m["mrr"] == 600 and s_m["interval"] == "month" and s_m["term_label"] == "")
s_o, _ = sp.custom_spec("One-off", 2, start, date(2026, 12, 6), cycle_amount=700)
check("spec.oneoff", s_o["recurring"] is False and s_o["mrr"] == 0 and s_o["one_off"] == 700 and s_o["interval"] == "none" and s_o["cycles"] == 0)
try:
    sp.custom_spec("X", 12, end, start); check("spec.order", False)
except ValueError:
    check("spec.order", True)
try:
    sp.custom_spec("X", 0, start, end); check("spec.hours", False)
except ValueError:
    check("spec.hours", True)

# ── words and dates ────────────────────────────────────────────────────────
check("term.phrase", sp.term_phrase(spec) == "3 months" and sp.term_phrase(s_m) == "92 days")
check("term.phrase_pkgs", sp.term_phrase(mo3) == "3 months" and sp.term_phrase(trial) == "30 days" and sp.term_phrase(hour) == "30 days")
bd = sp.billing_dates(spec, start)
check("billing.weekly", len(bd) == 13 and bd[0] == start and bd[-1] == date(2027, 1, 29)
      and all(d.weekday() == 4 for d in bd) and all((bd[i + 1] - bd[i]).days == 7 for i in range(12)), str(bd))
check("billing.monthly_untouched", sp.billing_dates(mo3, start) == [date(2026, 11, 6), date(2026, 12, 6), date(2027, 1, 6)]
      and sp.billing_dates(s_m, start) == [date(2026, 11, 6), date(2026, 12, 6), date(2027, 1, 6)]
      and sp.billing_dates(trial, start) == [] and sp.billing_dates(hour, start) == [] and sp.billing_dates(s_o, start) == [])
check("billing.by_month", sp._dates_by_month(bd) == "November 6, 13, 20, 27; December 4, 11, 18, 25; January 1, 8, 15, 22, 29", sp._dates_by_month(bd))
ft = sp.billing_footer_html(spec, t)
check("footer.weekly", "$350/week for 13 weeks" in ft and "$4,550 total" in ft and "every Friday" in ft
      and "November 6, 13, 20, 27; December 4, 11, 18, 25; January 1, 8, 15, 22, 29" in ft
      and "review the results together" in ft and "/month" not in ft, ft[:300])
fm = sp.billing_footer_html(mo3, sp.package_term(mo3, start))
check("footer.monthly_untouched", "$1,200/month for 3 months" in fm and "($3,600 total)" in fm
      and "November 6, December 6, January 6" in fm and "/week" not in fm, fm[:300])
check("footer.oneoffs_empty", sp.billing_footer_html(trial, sp.package_term(trial, start)) == ""
      and sp.billing_footer_html(hour, sp.package_term(hour, start)) == ""
      and sp.billing_footer_html(s_o, sp.package_term(s_o, start)) == "")

# ── the standard welcome email, on the custom spec ─────────────────────────
html = sp._welcome_email_html("Shawnie", "ABC123", spec, t)
check("welcome.headline", "Your <strong>MWM Partner Plan</strong> is active — 12 hours of professional studio time to use over the next 3 months." in html)
check("welcome.total", "<li>12 hours total across 3 months (4 hours a month)</li>" in html)
check("welcome.deadline", "All 12 hours must be used within 3 months — the last day you can book is <strong>Friday, February 05, 2027</strong>" in html)
check("welcome.includes", "<li>Your monthly strategy session with Michael, and the editing of your story film, podcast episodes and short clips from those hours — ready to post</li>" in html)
check("welcome.extra", "<li>Partner Program: every business owner you introduce who signs a plan adds studio hours to your account, on top of these, at no extra cost</li>" in html)
check("welcome.standard_parts", "ABC123" in html and "https://mwmcreations.com/studio-portal/" in html and "$350/week" in html
      and "Welcome to MWM Studios" in html and "Cancellations need at least 24 hours" in html and html.count("<li>") == 7)
h3 = sp._welcome_email_html("Ana", "XYZ789", mo3, sp.package_term(mo3, start))
check("welcome.3mo_untouched", "12 hours total across 3 months (≈4h/month pace)" in h3 and "Partner Program" not in h3
      and "strategy session" not in h3 and h3.count("<li>") == 5)
ht = sp._welcome_email_html("Ana", "XYZ789", trial, sp.package_term(trial, start))
check("welcome.trial_untouched", "Post-production editing is included" in ht and "Partner Program" not in ht and ht.count("<li>") == 6)

# ── provisioning, stubbed ──────────────────────────────────────────────────
calls = []


class _Resp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


def _fake_post(url, data=None, headers=None, timeout=None):
    calls.append({"url": url, "data": dict(data or {}), "headers": dict(headers or {})})
    if data.get("dry_run"):
        return _Resp({"success": True, "data": {"existing": False, "dry_run": True, "would_create": data.get("email")}})
    return _Resp({"success": True, "data": {"existing": False, "access_code": "K7PQ2M", "client_id": 77}})


_real_post = sp.http_requests.post
sp.http_requests.post = _fake_post
try:
    r = sp.provision_portal_client("Shawnie Whitaker", "x@example.com", spec, dry_run=True, start=start)
    p = calls[-1]["data"]
    check("prov.payload", p["action"] == "mwm_studio_provision_client" and p["contract_hours"] == "12"
          and p["contract_start"] == "2026-11-06" and p["contract_end"] == "2027-02-05"
          and p["package"] == "MWM Partner Plan" and p["dry_run"] == "1", str(p))
    check("prov.headers", "X-MWM-Portal-Secret" in calls[-1]["headers"] and calls[-1]["headers"]["User-Agent"] == sp.WP_UA)
    check("prov.term_back", r["term"]["booking_deadline"] == end and r["ok"] is True and r["existing"] is False)
    r0 = sp.provision_portal_client("Ana", "y@example.com", mo3, dry_run=True)
    check("prov.default_start_is_today", r0["term"]["start"] == datetime.now(sp.pytz.timezone(sp.TIMEZONE)).date())

    store = {}
    sp._deps.update({
        "pg_load": lambda k, d=None: store.get(k, {} if d is None else d),
        "pg_save": lambda k, v: store.__setitem__(k, v),
        "report_error": lambda *a, **k: None,
    })
    kw = dict(SHAWNIE); kw["start"] = "2026-11-06"; kw["end"] = "2027-02-05"; kw["hours"] = "12"
    n_before = len(calls)
    d = sp.provision_custom("Shawnie  Whitaker", "X@Example.com", apply=False, **kw)
    check("hand.dry", d["ok"] is True and d["dry"] is True and d["email"] == "x@example.com" and d["name"] == "Shawnie Whitaker"
          and d["booking_deadline"] == "2027-02-05" and d["term_start"] == "2026-11-06"
          and len(d["billing_dates"]) == 13 and d["billing_dates"][-1] == "2027-01-29"
          and d["subject"] == "Welcome to MWM Studios — your MWM Partner Plan is active 🎬"
          and d["wp"]["existing"] is False and "marker" not in d and d["spec"]["mrr"] == 1517
          and "Hi Shawnie," in d["welcome_html"] and "XXXXXX" in d["welcome_html"]
          and "Partner Program" in d["welcome_html"], str({k: v for k, v in d.items() if k != "welcome_html"})[:400])
    check("hand.dry_probed_wp_only", len(calls) == n_before + 1 and calls[-1]["data"].get("dry_run") == "1")
    check("hand.bad_dates", sp.provision_custom("A", "a@b.co", 12, "11/06/2026", "2027-02-05")["ok"] is False
          and sp.provision_custom("A", "a@b.co", 12, "2027-02-05", "2026-11-06")["ok"] is False)
    check("hand.bad_hours", sp.provision_custom("A", "a@b.co", "x", "2026-11-06", "2027-02-05")["ok"] is False
          and sp.provision_custom("A", "a@b.co", 0, "2026-11-06", "2027-02-05")["ok"] is False)
    check("hand.no_email", sp.provision_custom("A", "", 12, "2026-11-06", "2027-02-05")["ok"] is False)
    o = sp.provision_custom("A", "a@b.co", 2, "2026-11-06", "2026-12-06")
    check("hand.plain_oneoff", o["ok"] is True and o["spec"]["name"] == "Custom studio plan" and o["billing_dates"] == []
          and o["spec"]["recurring"] is False and "/week" not in o["welcome_html"] and "/month" not in o["welcome_html"])

    ran = []
    _real_on = sp._on_package_purchased
    sp._on_package_purchased = lambda name, email, event_id, spec=None, start=None: (
        ran.append((name, email, event_id, spec["name"], spec["hours"], start))
        or {"portal_ok": True, "welcome_email": True, "code_issued": True, "existing": False})
    try:
        a1 = sp.provision_custom("Shawnie Whitaker", "x@example.com", apply=True, **kw)
        a2 = sp.provision_custom("Shawnie Whitaker", "x@example.com", apply=True, **kw)
    finally:
        sp._on_package_purchased = _real_on
    check("hand.apply_once", a1["ok"] is True and a1["dry"] is False and a1["marker"] == "manual:x@example.com:2026-11-06"
          and a1["result"]["welcome_email"] is True and "welcome_html" not in a1 and len(ran) == 1
          and ran[0] == ("Shawnie Whitaker", "x@example.com", "manual:x@example.com:2026-11-06", "MWM Partner Plan", 12, start), str(a1)[:300])
    check("hand.duplicate", a2["ok"] is False and a2["error"] == "duplicate" and len(ran) == 1, str(a2)[:200])
    check("hand.marker_stored", "manual:x@example.com:2026-11-06" in (store.get(sp._PROCESSED_KEY) or {}))
finally:
    sp.http_requests.post = _real_post

# ── app wiring (static) ────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.route", "@app.route('/admin/studio-provision-custom', methods=['GET', 'POST'])" in SRC)
blk = SRC[SRC.index("def admin_studio_provision_custom():"):SRC.index("def admin_studio_provision_custom():") + 3600]   # #280: the call grew in #277
check("app.secret", '_admin_secret_ok(request.values.get("secret", ""))' in blk and '"unauthorized"' in blk)
check("app.dry_default", 'apply = str(v.get("apply") or "") in ("1", "true", "yes")' in blk)
check("app.fields", "_studio.provision_custom(" in blk and 'hours=v.get("hours") or 0' in blk and 'end=v.get("end") or ""' in blk
      and 'interval=v.get("interval") or "none"' in blk and 'cycle_amount=v.get("amount") or 0' in blk
      and 'extra_notes=[s for s in str(v.get("extra") or "").split("|") if s.strip()]' in blk and ("apply=apply)" in blk or "apply=apply," in blk))   # #280: more keyword args follow since #277
check("app.status_codes", "return jsonify(res), (200 if res.get(\"ok\") else 400)" in blk)
SPSRC = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.purchased_passes_start", "prov = provision_portal_client(name, email, spec, start=start)" in SPSRC
      and "def _on_package_purchased(name: str, email: str, event_id: str, spec: dict = None,\n                          start=None):" in SPSRC)
check("sp.no_new_package", "PARTNER_PLAN" not in SPSRC and SPSRC.count("PACKAGES = {") == 1)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch267.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #267 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("267: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE269 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
