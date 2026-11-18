#!/usr/bin/env python3
"""GATE for PATCH #290 — the portal's 'Refreshes on …' date travels with every
charge (provision, purchase top-up, cycle top-up, and a 0-hour touch for a
covered prepaid bucket). Prints GATE290 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import date, datetime

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


# ── harness ─────────────────────────────────────────────────────────────────
STORE, POSTS, MAILS, SLACK, LEADS = {}, [], [], [], {}
WP = {"existing": False}


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
            return R({"success": True, "data": {"existing": True, "access_code": None}})
        return R({"success": True, "data": {"existing": False, "access_code": "NEW123"}})
    if a == "mwm_studio_topup_client":
        return R({"success": True, "data": {"found": True, "duplicate": False, "added": float(data["add_hours"]),
                                            "available": 4, "fresh_start": False, "end_after": data.get("contract_end")}})
    return R({"success": False})


LINES = {}


def lookup(email):
    for k, r in LEADS.items():
        if str(r.get("email") or "").lower() == str(email or "").lower():
            return k, r
    return None, None


sp.http_requests.post = fake_post
sp.configure(pg_load=lambda k, d: STORE.get(k, d), pg_save=lambda k, v: STORE.__setitem__(k, v),
             post_slack=lambda ch, t: SLACK.append((ch, t)), pipeline_event=lambda *a, **k: None,
             send_email=lambda to, subj, html: MAILS.append((to, subj, html)) or True,
             stripe_get=lambda ep, params=None: {"data": LINES.get(ep.split("/")[2], [])} if ep.startswith("checkout/sessions/") else {"data": []},
             lead_lookup_by_email=lookup, lead_lookup_by_name=lambda n: (None, None),
             update_sheet_status=lambda *a: None, report_error=lambda *a: None,
             matt_channel="M", lara_channel="L", invoice_defer_seconds=0, lead_data=LEADS)

tz = pytz.timezone("US/Eastern")


def epoch(y, m, d):
    return int(tz.localize(datetime(y, m, d, 9, 0)).timestamp())


# ── 1. the helper ───────────────────────────────────────────────────────────
check("helper.plain", sp.next_refresh_date(date(2026, 11, 18)) == date(2026, 12, 18))
check("helper.clamp", sp.next_refresh_date(date(2027, 1, 31)) == date(2027, 2, 28))
check("helper.datetime", sp.next_refresh_date(tz.localize(datetime(2026, 11, 17, 14, 5))) == date(2026, 12, 17))

# ── 2. provision: monthly plans carry next_refresh, others do not ───────────
growth = sp.spec_by_kind("plan_ai_growth")
start = tz.localize(datetime(2026, 11, 18, 10, 0))
POSTS.clear()
sp.provision_portal_client("Ana", "ana@x.com", growth, start=start)
check("prov.monthly_next_refresh", POSTS[-1].get("next_refresh") == "2026-12-18" and POSTS[-1].get("monthly_hours") == "4", POSTS[-1])
sp.provision_portal_client("Ana", "ana@x.com", growth, start=start, next_refresh=date(2026, 12, 20))
check("prov.explicit_wins", POSTS[-1].get("next_refresh") == "2026-12-20")
sp.provision_portal_client("Ana", "ana@x.com", sp.PLANS["price_1UR0ixDAWlnEb9Rfw5I1cFJX"], start=start)
check("prov.oneoff_none", "next_refresh" not in POSTS[-1])
sp.provision_portal_client("Ana", "ana@x.com", sp.PLANS["price_1UZaCCDAWlnEb9RfKpoeJTAI"], start=start)
check("prov.annual_none", "next_refresh" not in POSTS[-1])
sp.provision_portal_client("Ana", "ana@x.com", sp.PACKAGES[sp.STUDIO_PRICE_ID], start=start)
check("prov.package_none", "next_refresh" not in POSTS[-1])

# ── 3. top-up payload ───────────────────────────────────────────────────────
POSTS.clear()
sp.topup_portal_client("ana@x.com", 4, cap_hours=8, ref="t1", next_refresh=date(2026, 12, 18))
check("topup.next_refresh", POSTS[-1].get("next_refresh") == "2026-12-18" and POSTS[-1]["add_hours"] == "4")
sp.topup_portal_client("ana@x.com", 4, cap_hours=8, ref="t2")
check("topup.absent_when_not_given", "next_refresh" not in POSTS[-1])
sp.topup_portal_client("ana@x.com", 0, ref="touch", next_refresh="2026-12-18")
check("topup.touch_zero_hours", POSTS[-1]["add_hours"] == "0" and POSTS[-1]["next_refresh"] == "2026-12-18")

# ── 4. a new plan purchase (checkout) provisions with the date ──────────────
POSTS.clear()
LINES["cs_new"] = [{"price": {"id": "price_1UR13hDAWlnEb9Rfv3SarAEu"}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_new290", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_new", "customer_details": {"email": "new290@x.com", "name": "New Client"}}}})
prov = [p for p in POSTS if p.get("action") == "mwm_studio_provision_client"][-1]
today_next = sp.next_refresh_date(datetime.now(tz)).isoformat()
check("buy.new_has_next_refresh", r.get("handled") and prov.get("next_refresh") == today_next, (r, prov))

# an existing account buying a monthly plan: the top-up carries the date too
WP["existing"] = True
POSTS.clear()
LINES["cs_exist"] = [{"price": {"id": "price_1UR13hDAWlnEb9Rfv3SarAEu"}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_exist290", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_exist", "customer_details": {"email": "exist290@x.com", "name": "Existing Client"}}}})
tops = [p for p in POSTS if p.get("action") == "mwm_studio_topup_client"]
check("buy.existing_topup_next_refresh", r.get("handled") and len(tops) == 1 and tops[0].get("next_refresh") == today_next
      and tops[0]["add_hours"] == "4", (r, tops))
WP["existing"] = False

# ── 5. the monthly cycle: next_refresh = the period end (the next charge) ───
def inv(iid, price, start_epoch, email, days=30):
    line = {"price": {"id": price}, "quantity": 1, "period": {"start": start_epoch, "end": start_epoch + days * 86400}}
    o = {"id": iid, "billing_reason": "subscription_cycle", "customer_email": email, "customer_name": "Someone",
         "lines": {"data": [line]}, "subscription": "sub_x", "subscription_details": {"metadata": {}}}
    return {"id": "evt_" + iid, "type": "invoice.paid", "data": {"object": o}}


POSTS.clear()
r = sp.handle_stripe_event(inv("in_cycle290", "price_1UR13hDAWlnEb9Rfv3SarAEu", epoch(2026, 12, 18), "roll@x.com", days=31))
tops = [p for p in POSTS if p.get("action") == "mwm_studio_topup_client"]
check("cycle.next_refresh_is_period_end", r.get("handled") and len(tops) == 1 and tops[0].get("next_refresh") == "2027-01-18"
      and tops[0]["add_hours"] == "4", (r, tops))

# ── 6. a covered prepaid bucket: a 0-hour touch moves the date, adds nothing ─
LEADS["whatsapp:+1407"] = {"name": "Camila Silveira", "email": "camila@x.com", "product": "AI Growth Plan",
                           "studio_package": {"variant": "studio_3mo", "hours": 12, "mrr": 1200,
                                              "courtesy_plan": "plan_ai_growth", "booking_deadline": "2027-02-15"}}
POSTS.clear()
r = sp.handle_stripe_event(inv("in_dec290", sp.STUDIO_PRICE_ID, epoch(2026, 12, 17), "camila@x.com", days=31))
tops = [p for p in POSTS if p.get("action") == "mwm_studio_topup_client"]
check("covered.touch_only", r.get("handled") and r.get("covered_until") == "2027-02-15" and len(tops) == 1
      and tops[0]["add_hours"] == "0" and tops[0]["next_refresh"] == "2027-01-17" and tops[0]["ref"] == "refresh:in_dec290", (r, tops))
check("covered.no_hours_added", all(p.get("add_hours") == "0" for p in tops))

# ── 7. pins ─────────────────────────────────────────────────────────────────
SP = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.helper_def", "def next_refresh_date(start):" in SP)
check("sp.covered_touch", 'topup_portal_client(email, 0, ref=f"refresh:{inv_id}",' in SP)
check("sp.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "studio_package.py")], capture_output=True).returncode == 0)
PHP = open(os.path.join(HERE, "wordpress", "wp-snippet-15-provisioning-endpoint.php"), encoding="utf-8").read()
check("php.v3", PHP.count("next_refresh_date") >= 3 and "( 0 == $add && ! $next_refresh )" in PHP and "'next_refresh_date'   => $next_refresh ? $next_refresh : null," in PHP)
for t in ("test_patch287.py", "test_patch288.py"):
    check(f"pins.{t}", 'p.get("add_hours") != "0"] == []' in open(os.path.join(HERE, t), encoding="utf-8").read())

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 290) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
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
print("GATE290 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
