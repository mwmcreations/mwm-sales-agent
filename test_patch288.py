#!/usr/bin/env python3
"""GATE for PATCH #288 — a courtesy upgrade is the plan the client was GIVEN,
at the price they pay (Michael, 18 Nov 09:51: Camila bought Real Sets, holds
AI Growth, pays $1,200). The record rolls into the courtesy plan when the
prepaid bucket ends; the monthly hours come from the plan on record;
register-client takes courtesy_plan. Prints GATE288 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import studio_package as sp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


# ── harness (WP, Slack stubbed) ─────────────────────────────────────────────
STORE, POSTS, MAILS, SLACK, LEADS = {}, [], [], [], {}


class R:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self._b = body

    def json(self):
        return self._b


def fake_post(url, data=None, headers=None, timeout=None):
    POSTS.append(dict(data or {}))
    if (data or {}).get("action") == "mwm_studio_topup_client":
        return R({"success": True, "data": {"found": True, "duplicate": False, "added": float(data["add_hours"]),
                                            "available": float(data["add_hours"]), "fresh_start": False,
                                            "end_after": data.get("contract_end")}})
    return R({"success": True, "data": {"existing": False, "access_code": "NEW123"}})


def lookup(email):
    for k, r in LEADS.items():
        if str(r.get("email") or "").lower() == str(email or "").lower():
            return k, r
    return None, None


sp.http_requests.post = fake_post
sp.configure(pg_load=lambda k, d: STORE.get(k, d), pg_save=lambda k, v: STORE.__setitem__(k, v),
             post_slack=lambda ch, t: SLACK.append((ch, t)), pipeline_event=lambda *a, **k: None,
             send_email=lambda to, subj, html: MAILS.append((to, subj, html)) or True,
             stripe_get=lambda ep, params=None: {"data": []}, lead_lookup_by_email=lookup,
             lead_lookup_by_name=lambda n: (None, None), update_sheet_status=lambda *a: None,
             report_error=lambda *a: None, matt_channel="M", lara_channel="L",
             invoice_defer_seconds=0, lead_data=LEADS)

tz = pytz.timezone("US/Eastern")


def epoch(y, m, d):
    return int(tz.localize(datetime(y, m, d, 9, 0)).timestamp())


def inv(iid, price, start_epoch, email):
    line = {"price": {"id": price}, "quantity": 1, "period": {"start": start_epoch, "end": start_epoch + 30 * 86400}}
    o = {"id": iid, "billing_reason": "subscription_cycle", "customer_email": email, "customer_name": "Camila S",
         "lines": {"data": [line]}, "subscription": "sub_c", "subscription_details": {"metadata": {}}}
    return {"id": "evt_" + iid, "type": "invoice.paid", "data": {"object": o}}


REAL = sp.resolve_spec(sp.STUDIO_PRICE_ID)
GROWTH = sp.spec_by_kind("plan_ai_growth")
STARTER = sp.spec_by_kind("plan_ai_starter")

# ── 1. _record_plan ─────────────────────────────────────────────────────────
check("rp.no_record_is_price", sp._record_plan("nobody@x.com", REAL) is REAL)
LEADS["whatsapp:+1407"] = {"name": "Camila Silveira", "email": "camila@x.com", "product": "AI Growth Plan",
                           "studio_package": {"variant": "studio_3mo", "package_name": "AI Growth Plan", "hours": 12,
                                              "term_days": 90, "recurring": True, "mrr": 1200,
                                              "courtesy_plan": "plan_ai_growth",
                                              "courtesy_note": "pays Real Sets $1,200 (Michael 18 Nov 09:51)",
                                              "booking_deadline": "2027-02-15"}}
check("rp.courtesy_wins", sp._record_plan("camila@x.com", REAL)["kind"] == "plan_ai_growth")
LEADS["whatsapp:+1999"] = {"name": "Maria J", "email": "maria@x.com",
                           "studio_package": {"variant": "studio_3mo", "hours": 12, "booking_deadline": "2027-02-15"}}
check("rp.no_courtesy_is_price", sp._record_plan("maria@x.com", REAL) is REAL)
LEADS["whatsapp:+1000"] = {"name": "Bad", "email": "bad@x.com",
                           "studio_package": {"variant": "studio_3mo", "courtesy_plan": "ai_wall_hour", "booking_deadline": "2027-02-15"}}
check("rp.non_plan_courtesy_ignored", sp._record_plan("bad@x.com", REAL) is REAL)
LEADS["whatsapp:+1002"] = {"name": "Bad3", "email": "bad3@x.com",
                           "studio_package": {"variant": "studio_3mo", "courtesy_plan": "f10_ai_growth", "booking_deadline": "2027-02-15"}}
check("rp.annual_courtesy_ignored", sp._record_plan("bad3@x.com", REAL) is REAL)
LEADS["whatsapp:+1001"] = {"name": "Bad2", "email": "bad2@x.com",
                           "studio_package": {"variant": "studio_3mo", "courtesy_plan": "no_such_plan", "booking_deadline": "2027-02-15"}}
check("rp.unknown_courtesy_ignored", sp._record_plan("bad2@x.com", REAL) is REAL)

# ── 2. Camila: covered, then rolls into AI GROWTH at the Real Sets price ────
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_dec", sp.STUDIO_PRICE_ID, epoch(2026, 12, 17), "camila@x.com"))
check("cam.dec_covered", r.get("handled") and r.get("covered_until") == "2027-02-15"
      and [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client" and p.get("add_hours") != "0"] == [], r)   # #290
r = sp.handle_stripe_event(inv("in_jan", sp.STUDIO_PRICE_ID, epoch(2027, 1, 17), "camila@x.com"))
check("cam.jan_covered", r.get("handled") and r.get("covered_until") == "2027-02-15"
      and [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client" and p.get("add_hours") != "0"] == [], r)   # #290
spr = LEADS["whatsapp:+1407"]["studio_package"]
check("cam.record_kept", spr["variant"] == "studio_3mo" and spr["courtesy_plan"] == "plan_ai_growth"
      and LEADS["whatsapp:+1407"]["product"] == "AI Growth Plan", spr)
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_feb", sp.STUDIO_PRICE_ID, epoch(2027, 2, 17), "camila@x.com"))
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("cam.feb_rolls_growth_hours", r.get("handled") and len(tops) == 1 and tops[0]["add_hours"] == "4"
      and tops[0]["cap_hours"] == "8" and tops[0]["email"] == "camila@x.com", (r, tops))
spr = LEADS["whatsapp:+1407"]["studio_package"]
check("cam.converted_to_growth", spr["variant"] == "plan_ai_growth" and spr["package_name"] == "AI Growth Plan"
      and spr["model"] == "rolling" and spr["bucket_deadline"] == "2027-02-15" and spr["booking_deadline"] == ""
      and spr["courtesy_plan"] == "plan_ai_growth", spr)
check("cam.price_kept", spr["mrr"] == 1200 and spr["hours"] == 4, spr)
check("cam.product_growth", LEADS["whatsapp:+1407"]["product"] == "AI Growth Plan")
check("cam.matt_told_courtesy", any("rolling *AI Growth Plan*" in t and "courtesy upgrade, pays the Real Sets Plan price" in t
                                    for _, t in SLACK[s0:]), SLACK[s0:])
check("cam.renewal_line_growth", any("*AI Growth Plan* renewed" in t and "holds up to 8h" in t for _, t in SLACK[s0:]), SLACK[s0:])
check("cam.helper_empty_after", sp._prepaid_bucket_covers("camila@x.com", None) == {})
n0 = len(POSTS)
r = sp.handle_stripe_event(inv("in_mar", sp.STUDIO_PRICE_ID, epoch(2027, 3, 17), "camila@x.com"))
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("cam.mar_growth_hours", r.get("handled") and len(tops) == 1 and tops[0]["add_hours"] == "4" and tops[0]["cap_hours"] == "8", tops)
check("cam.mar_package_growth", r.get("package") == "plan_ai_growth", r)

# ── 3. a courtesy plan with OTHER hours drives the top-up (Starter: 2h, holds 4h) ──
LEADS["whatsapp:+1500"] = {"name": "Two Hours", "email": "two@x.com", "product": "AI Starter Plan",
                           "studio_package": {"variant": "plan_real_sets", "package_name": "AI Starter Plan", "mrr": 1200,
                                              "courtesy_plan": "plan_ai_starter", "model": "rolling"}}
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_two", sp.STUDIO_PRICE_ID, epoch(2026, 12, 17), "two@x.com"))
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("other.starter_hours", r.get("handled") and len(tops) == 1 and tops[0]["add_hours"] == "2" and tops[0]["cap_hours"] == "4", tops)
check("other.starter_named", any("*AI Starter Plan* renewed" in t for _, t in SLACK[s0:]), SLACK[s0:])

# ── 4. no courtesy: exactly the #287 behaviour (Maria rolls into Real Sets) ──
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_mfeb", sp.STUDIO_PRICE_ID, epoch(2027, 2, 17), "maria@x.com"))
spr = LEADS["whatsapp:+1999"]["studio_package"]
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("maria.rolls_real_sets", spr["variant"] == "plan_real_sets" and spr["package_name"] == "Real Sets Plan"
      and LEADS["whatsapp:+1999"]["product"] == "Real Sets Plan" and len(tops) == 1 and tops[0]["add_hours"] == "4", spr)
check("maria.no_courtesy_wording", any("rolling *Real Sets Plan*" in t and "courtesy" not in t for _, t in SLACK[s0:]), SLACK[s0:])


# ── 4b. a purchase matched by NAME keeps the payer's email on the record ────
LEADS["whatsapp:+1600"] = {"name": "Nina Byname", "email": "", "status": "lead"}
LINES = {"cs_name": [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]}
sp._deps["stripe_get"] = lambda ep, params=None: {"data": LINES.get(ep.split("/")[2], [])} if ep.startswith("checkout/sessions/") else {"data": []}
sp._deps["lead_lookup_by_name"] = lambda n: next(((k, r) for k, r in LEADS.items() if str(r.get("name") or "").lower() == str(n or "").lower()), (None, None))
r = sp.handle_stripe_event({"id": "evt_name", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_name", "customer_details": {"email": "nina@x.com", "name": "Nina Byname"}}}})
check("link.email_written", r.get("handled") and LEADS["whatsapp:+1600"]["email"] == "nina@x.com"
      and LEADS["whatsapp:+1600"]["outcome"] == "Won", (r, LEADS["whatsapp:+1600"]))
check("link.found_by_email_now", sp._record_plan("nina@x.com", REAL) is REAL and lookup("nina@x.com")[0] == "whatsapp:+1600")
LEADS["whatsapp:+1601"] = {"name": "Owen Hasmail", "email": "owen.real@x.com", "status": "lead"}
LINES["cs_owen"] = [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_owen", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_owen", "customer_details": {"email": "owen.other@x.com", "name": "Owen Hasmail"}}}})
check("link.existing_email_kept", r.get("handled") and LEADS["whatsapp:+1601"]["email"] == "owen.real@x.com", LEADS["whatsapp:+1601"])

# ── 5. app.py pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.courtesy_parsed", '_court = _studio.spec_by_kind(str(_p.get("courtesy_plan")).strip())' in SRC
      and 'if _court is None or _court.get("plan") != "monthly":' in SRC and "_shown = _court or _spec" in SRC)
check("app.courtesy_parsed_before_dup_check", SRC.index("_shown = _court or _spec") < SRC.index("_existing_key, _existing = _find_lead_by_email(_email)\n    if not _existing_key and _phone_digits:"))
check("app.box_courtesy", '"package_name": _shown["name"],' in SRC and '"courtesy_plan": (_court["kind"] if _court else ""),' in SRC
      and '"courtesy_note": str(_p.get("courtesy_note") or "").strip(),' in SRC)
check("app.product_shown", '_rec["product"] = _shown["name"]   # PATCH #288' in SRC and '_rec["product"] = _spec["name"]\n    _rec["outcome"]' not in SRC)
check("app.verify_shown", '_verified = (_stored.get("product") == _shown["name"]' in SRC)
check("app.sheet_shown", 'service=_shown["name"],' in SRC and "courtesy upgrade from {_spec['name']}, pays ${_box['mrr']:,.0f}/mo" in SRC)
check("app.slack_price_paid", "format(_box['mrr'], ',.0f') + '/mo'" in SRC)
check("app.keeps_purchase_time", '_bought_src = str(_existing["studio_package"].get("purchased") or "").strip()' in SRC
      and "_bought = datetime.fromisoformat(_bought_src)" in SRC)
check("app.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)
SP = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.record_plan_def", "def _record_plan(email, spec):" in SP and 'spec = _record_plan(email, spec)   # PATCH #288' in SP)
check("sp.record_plan_after_convert", SP.index('_convert_bucket_record(_cov["key"], _cov["rec"], spec)\n') < SP.index('spec = _record_plan(email, spec)   # PATCH #288')
      < SP.index('res = topup_portal_client(email, spec["monthly_hours"] * qty'))
check("sp.convert_uses_plan", 'plan = court if (court and court.get("plan") == "monthly") else spec' in SP and 'rec["product"] = plan["name"]' in SP)
check("sp.link_email_pin", 'if _matched_on == "name" and email and not str(rec.get("email") or "").strip():\n                rec["email"] = email' in SP)
check("sp.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "studio_package.py")], capture_output=True).returncode == 0)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 288) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE288 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
