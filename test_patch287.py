#!/usr/bin/env python3
"""GATE for PATCH #287 — every studio package is an ongoing subscription: the
$1,200 price is the Real Sets plan whatever link it came through; a plan bought
on an account whose window had closed gets a fresh start with a NEW code in a
full welcome; a prepaid 3-month bucket is covered until its deadline and the
first charge after it converts the record; register-client takes plan kinds.
Prints GATE287 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

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


# ── 1. the $1,200 price is the Real Sets plan, full stop ────────────────────
check("spec.plain_is_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID)["kind"] == "plan_real_sets")
check("spec.sku_still_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID, "plan_studio_only_4h")["kind"] == "plan_real_sets")
check("spec.link_still_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID, "", "plink_1UR148DAWlnEb9RfffEDwxut")["kind"] == "plan_real_sets")
check("spec.real_sets_is_founding_1200", sp.resolve_spec(sp.STUDIO_PRICE_ID)["mrr"] == 1200 and sp.resolve_spec(sp.STUDIO_PRICE_ID)["founding"] is True)
check("spec.real_sets_ongoing", sp.resolve_spec(sp.STUDIO_PRICE_ID)["ongoing"] is True and sp.resolve_spec(sp.STUDIO_PRICE_ID)["plan"] == "monthly"
      and sp.resolve_spec(sp.STUDIO_PRICE_ID)["monthly_hours"] == 4 and sp.resolve_spec(sp.STUDIO_PRICE_ID)["cap_hours"] == 8)
check("spec.packages_untouched", len(sp.PACKAGES) == 3 and sp.PACKAGES[sp.STUDIO_PRICE_ID]["kind"] == "studio_3mo")
check("spec.other_plans_unchanged", sp.resolve_spec("price_1UR13hDAWlnEb9Rfv3SarAEu")["kind"] == "plan_ai_growth"
      and sp.resolve_spec("price_nope") is None)
for _k, _n in (("plan_real_sets", "Real Sets Plan"), ("plan_ai_starter", "AI Starter Plan"),
               ("plan_ai_growth", "AI Growth Plan"), ("plan_ai_pro", "AI Pro Plan")):
    _s = sp.spec_by_kind(_k)
    check(f"kind.{_k}", _s and _s["name"] == _n and _s["plan"] == "monthly" and _s["ongoing"] is True and _s.get("founding") is True, _s)
check("kind.real_sets_founding_mrr", sp.spec_by_kind("plan_real_sets")["mrr"] == 1200)
check("kind.ai_growth_founding_mrr", sp.spec_by_kind("plan_ai_growth")["mrr"] == 1697)
check("kind.package", sp.spec_by_kind("studio_3mo") is sp.PACKAGES[sp.STUDIO_PRICE_ID])
check("kind.unknown", sp.spec_by_kind("nope") is None and sp.spec_by_kind("") is None and sp.spec_by_kind(None) is None)
check("cadence.constants", (sp.PLAN_CAP_MONTHS, sp.PLAN_FIRST_WINDOW_DAYS, sp.PLAN_TOPUP_WINDOW_DAYS) == (2, 60, 30))

# ── 2. invoice lines carry the period start ─────────────────────────────────
ln = sp._invoice_lines({"lines": {"data": [{"price": {"id": "p1"}, "quantity": 2, "period": {"start": 100, "end": 200}}]}})
check("lines.four_tuple", ln == [("p1", 2, 200, 100)], ln)
ln2 = sp._invoice_lines({"lines": {"data": [{"pricing": {"price_details": {"price": "p2"}}, "period": {"end": 5}}]}})
check("lines.new_shape_no_start", ln2 == [("p2", 1, 5, None)], ln2)

# ── 3. the webhook, end to end (WP, Stripe, mail, Slack stubbed) ────────────
STORE, POSTS, MAILS, SLACK = {}, [], [], []
WP = {"existing": False, "found": True, "fresh": False}
LEADS = {}


class R:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self._b = body

    def json(self):
        return self._b


def fake_post(url, data=None, headers=None, timeout=None):
    POSTS.append(dict(data or {}))
    a = (data or {}).get("action")
    if a == "mwm_studio_provision_client":
        if WP["existing"]:
            if (data or {}).get("rotate_code") == "1":
                return R({"success": True, "data": {"existing": True, "access_code": "ROT456"}})
            return R({"success": True, "data": {"existing": True, "access_code": None}})
        return R({"success": True, "data": {"existing": False, "access_code": "NEW123"}})
    if a == "mwm_studio_topup_client":
        if not WP["found"]:
            return R({"success": True, "data": {"found": False}})
        return R({"success": True, "data": {"found": True, "duplicate": False, "added": 4, "available": 4,
                                            "fresh_start": WP["fresh"], "end_after": data.get("contract_end")}})
    return R({"success": False})


LINES = {}


def fake_stripe_get(ep, params=None):
    if ep.startswith("checkout/sessions/") and ep.endswith("/line_items"):
        return {"data": LINES.get(ep.split("/")[2], [])}
    return {"data": []}


def lookup(email):
    for k, r in LEADS.items():
        if str(r.get("email") or "").lower() == str(email or "").lower():
            return k, r
    return None, None


sp.http_requests.post = fake_post
sp.configure(pg_load=lambda k, d: STORE.get(k, d), pg_save=lambda k, v: STORE.__setitem__(k, v),
             post_slack=lambda ch, t: SLACK.append((ch, t)), pipeline_event=lambda *a, **k: None,
             send_email=lambda to, subj, html: MAILS.append((to, subj, html)) or True,
             stripe_get=fake_stripe_get, lead_lookup_by_email=lookup,
             lead_lookup_by_name=lambda n: (None, None), update_sheet_status=lambda *a: None,
             report_error=lambda *a: None, matt_channel="M", lara_channel="L",
             invoice_defer_seconds=0, lead_data=LEADS)

# a plain $1,200 checkout (no link, no sku) is the rolling Real Sets plan with a code
LINES["cs_plain"] = [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_plain", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_plain", "customer_details": {"email": "new@x.com", "name": "New Client"}}}})
prov = [p for p in POSTS if p.get("action") == "mwm_studio_provision_client"][-1]
check("co.plain_is_rolling", r.get("package") == "plan_real_sets" and prov["contract_hours"] == "4" and prov.get("monthly_hours") == "4", (r, prov))
check("co.plain_welcome_ongoing", MAILS[-1][1] == "Welcome to MWM Studios — your Real Sets Plan is active 🎬"
      and "NEW123" in MAILS[-1][2] and "renewed every month" in MAILS[-1][2]   # #289
      and "3-month minimum" in MAILS[-1][2] and "12 hours" not in MAILS[-1][2], MAILS[-1][1:2])
check("co.plain_no_rotate", "rotate_code" not in prov)

# an existing account whose window had closed buys a plan: fresh start → NEW code in a full welcome
WP["existing"] = True
WP["fresh"] = True
n0, m0 = len(POSTS), len(MAILS)
LINES["cs_back"] = [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_back", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_back", "customer_details": {"email": "camila@x.com", "name": "Camila Back"}}}})
provs = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_provision_client"]
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("back.topup_then_rotate", len(tops) == 1 and len(provs) == 2 and provs[0].get("rotate_code") is None and provs[1].get("rotate_code") == "1", (provs, tops))
check("back.welcome_with_new_code", len(MAILS) == m0 + 1 and MAILS[-1][1] == "Welcome to MWM Studios — your Real Sets Plan is active 🎬"
      and "ROT456" in MAILS[-1][2] and "being generated" not in MAILS[-1][2], MAILS[-1][1])
check("back.handled", r.get("handled") and r.get("package") == "plan_real_sets", r)

# an existing ACTIVE account buys a plan: hours added, code kept, no rotation
WP["fresh"] = False
n0, m0 = len(POSTS), len(MAILS)
LINES["cs_add"] = [{"price": {"id": "price_1UR13hDAWlnEb9Rfv3SarAEu"}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_add", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_add", "customer_details": {"email": "david@x.com", "name": "David Active"}}}})
provs = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_provision_client"]
check("active.no_rotate", len(provs) == 1 and "rotate_code" not in provs[0])
check("active.hours_added_mail", MAILS[-1][1] == "MWM Studios — your AI Growth Plan hours are in your portal 🎬" and "code you already have" in MAILS[-1][2], MAILS[-1][1])
WP["existing"] = False

# ── 4. the prepaid 3-month bucket ───────────────────────────────────────────
tz = pytz.timezone("US/Eastern")


def epoch(y, m, d):
    return int(tz.localize(datetime(y, m, d, 9, 0)).timestamp())


def inv(iid, price, start_epoch, email):
    line = {"price": {"id": price}, "quantity": 1, "period": {"start": start_epoch, "end": start_epoch + 30 * 86400}}
    o = {"id": iid, "billing_reason": "subscription_cycle", "customer_email": email, "customer_name": "Camila S",
         "lines": {"data": [line]}, "subscription": "sub_c", "subscription_details": {"metadata": {}}}
    return {"id": "evt_" + iid, "type": "invoice.paid", "data": {"object": o}}


LEADS["whatsapp:+1407"] = {"name": "Camila Silveira", "email": "camila@x.com", "product": "Studio Package",
                           "studio_package": {"variant": "studio_3mo", "package_name": "Studio Package", "hours": 12,
                                              "term_days": 90, "recurring": True, "mrr": 1200,
                                              "booking_deadline": "2027-02-15"}}
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_dec", sp.STUDIO_PRICE_ID, epoch(2026, 12, 17), "camila@x.com"))
check("bucket.dec_covered", r.get("handled") and r.get("covered_until") == "2027-02-15" and len(POSTS) == n0, r)
check("bucket.dec_told_matt", any("covered by their prepaid 12-hour package until Feb 15, 2027" in t for _, t in SLACK[s0:]), SLACK[s0:])
check("bucket.record_untouched", LEADS["whatsapp:+1407"]["studio_package"]["variant"] == "studio_3mo")
r = sp.handle_stripe_event(inv("in_jan", sp.STUDIO_PRICE_ID, epoch(2027, 1, 17), "camila@x.com"))
check("bucket.jan_covered", r.get("handled") and r.get("covered_until") == "2027-02-15" and len(POSTS) == n0, r)
n0, s0 = len(POSTS), len(SLACK)
r = sp.handle_stripe_event(inv("in_feb", sp.STUDIO_PRICE_ID, epoch(2027, 2, 17), "camila@x.com"))
tops = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("bucket.feb_rolls", r.get("handled") and len(tops) == 1 and tops[0]["add_hours"] == "4" and tops[0]["cap_hours"] == "8"
      and tops[0]["email"] == "camila@x.com", (r, tops))
spr = LEADS["whatsapp:+1407"]["studio_package"]
check("bucket.record_converted", spr["variant"] == "plan_real_sets" and spr["model"] == "rolling" and spr["bucket_deadline"] == "2027-02-15"
      and spr["mrr"] == 1200 and spr["package_name"] == "Real Sets Plan" and LEADS["whatsapp:+1407"]["product"] == "Real Sets Plan", spr)
check("bucket.convert_told_matt", any("prepaid 12-hour package finished" in t for _, t in SLACK[s0:]), SLACK[s0:])
n0 = len(POSTS)
r = sp.handle_stripe_event(inv("in_mar", sp.STUDIO_PRICE_ID, epoch(2027, 3, 17), "camila@x.com"))
check("bucket.after_conversion_normal", r.get("handled") and len([p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]) == 1, r)
# a lead with no bucket: untouched path
n0 = len(POSTS)
r = sp.handle_stripe_event(inv("in_other", "price_1UR13kDAWlnEb9RfxUYIOCE0", epoch(2026, 12, 17), "nobody@x.com"))
check("bucket.no_record_normal", r.get("handled") and len([p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]) == 1, r)
check("bucket.helper_empty_without_record", sp._prepaid_bucket_covers("nobody@x.com", epoch(2026, 12, 17)) == {})
check("bucket.helper_empty_after_conversion", sp._prepaid_bucket_covers("camila@x.com", None) == {})
LEADS["whatsapp:+1999"] = {"name": "Maria J", "email": "maria@x.com", "studio_package": {"variant": "studio_3mo", "hours": 12, "booking_deadline": "2027-02-15"}}
check("bucket.helper_no_period_uses_today", sp._prepaid_bucket_covers("maria@x.com", None).get("covered") is True)
check("bucket.helper_bad_deadline", sp._prepaid_bucket_covers("maria@x.com", "garbage") == {})

# ── 5. app.py + the #278 pins ───────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.register_uses_spec_by_kind", "_spec = _studio.spec_by_kind(_variant)   # PATCH #287" in SRC and "for _sp in _studio.PACKAGES.values():\n        if _sp[\"kind\"] == _variant:" not in SRC)
check("app.register_mrr_override", '"mrr": (float(_p.get("mrr")) if str(_p.get("mrr") or "").strip() else _spec["mrr"]),' in SRC)
check("app.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)
SP = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.rotate_param", "rotate_code: bool = False) -> dict:" in SP and 'payload["rotate_code"] = "1"' in SP)
check("sp.fresh_welcome", 'if topup is not None and not topup.get("welcome"):' in SP and "_rot = provision_portal_client(name, email, spec, start=start, rotate_code=True)" in SP)
check("sp.helpers", "def _prepaid_bucket_covers(email, period_start_epoch):" in SP and "def _convert_bucket_record(key, rec, spec):" in SP)
check("sp.covered_before_topup", SP.index("_cov = _prepaid_bucket_covers(email, pstart)") < SP.index('res = topup_portal_client(email, spec["monthly_hours"] * qty'))
T278 = open(os.path.join(HERE, "test_patch278.py"), encoding="utf-8").read()
check("t278.pins_turned", "shared.plain_is_real_sets" in T278 and "co.old_link_is_real_sets_now" in T278 and "cycle.old_price_rolls_now" in T278
      and "shared.plain_is_package" not in T278)
PHP = open(os.path.join(HERE, "wordpress", "wp-snippet-15-provisioning-endpoint.php"), encoding="utf-8").read()
check("php.topup_action_in_repo", "mwm_studio_topup_client" in PHP and "rotate_code" in PHP and "fresh_start" in PHP)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 287) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
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
print("GATE287 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
