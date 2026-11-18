#!/usr/bin/env python3
"""GATE for PATCH #278 — the four plans and the one-time services on
/book-studio provision the portal and send the right email; monthly plans top
up on every renewal (roll-over capped at 2 months' worth); one-time services
add 1 hour per item for 60 days; Founding 10 annual loads the whole year.
Real Sets on the shared $1,200 price is told apart from the old 3-month
package by its link/sku. Maya says Real Sets and points at /book-studio.
Then #277 (which re-checks every existing email byte-for-byte). Prints GATE278."""
import os
import re
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_package as sp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


# ── the table matches the website ──
WEB = {  # price: (kind, monthly hours, cap, $)
    "price_1UR0ipDAWlnEb9RfSTYiE4VE": ("plan_ai_starter", 2, 4, 1297),
    "price_1UXJwTDAWlnEb9RfgKs5wyxQ": ("plan_ai_starter", 2, 4, 1497),
    "price_1UR13hDAWlnEb9Rfv3SarAEu": ("plan_ai_growth", 4, 8, 1697),
    "price_1UXJwSDAWlnEb9Rfs9ZM5Xah": ("plan_ai_growth", 4, 8, 1997),
    "price_1UR13kDAWlnEb9RfxUYIOCE0": ("plan_ai_pro", 4, 8, 2497),
    "price_1UXJwTDAWlnEb9Rf3b0RwJQf": ("plan_ai_pro", 4, 8, 2997),
    "price_1UXJwUDAWlnEb9RfLIi8E2ea": ("plan_real_sets", 4, 8, 1497),
}
for pid, (k, m, cap, amt) in WEB.items():
    s_ = sp.resolve_spec(pid)
    check(f"plan.{pid}", s_ and s_["kind"] == k and s_["monthly_hours"] == m and s_["cap_hours"] == cap
          and s_["mrr"] == amt and s_["recurring"] and s_.get("ongoing"), s_)
check("plan.founding_flag", sp.PLANS["price_1UR0ipDAWlnEb9RfSTYiE4VE"]["founding"]
      and not sp.PLANS["price_1UXJwTDAWlnEb9RfgKs5wyxQ"]["founding"])
for pid, k, amt in (("price_1UR0ixDAWlnEb9Rfw5I1cFJX", "ai_wall_hour", 599),
                    ("price_1UR9slDAWlnEb9RfwuwNC0ac", "full_immersion", 997),
                    ("price_1ULR8vDAWlnEb9RfJrE5OJcI", "full_immersion_pack", 1497)):
    s_ = sp.resolve_spec(pid)
    check(f"oneoff.{k}", s_ and s_["kind"] == k and s_["hours"] == 1 and s_["term_days"] == 60
          and not s_["recurring"] and s_["mrr"] == 0 and s_["one_off"] == amt, s_)
for pid, k, m, amt in (("price_1UZaCHDAWlnEb9RfBQNh2P83", "f10_real_sets", 4, 13473),
                       ("price_1UZaCEDAWlnEb9RfuTxbrbfW", "f10_ai_starter", 2, 13473),
                       ("price_1UZaCCDAWlnEb9RfKpoeJTAI", "f10_ai_growth", 4, 17973),
                       ("price_1UZaCGDAWlnEb9RfRvBAb8Vn", "f10_ai_pro", 4, 26973)):
    s_ = sp.resolve_spec(pid)
    check(f"annual.{k}", s_ and s_["kind"] == k and s_["hours"] == 12 * m and s_["term_days"] == 365
          and s_["one_off"] == amt and s_["mrr"] == 0, s_)
check("pkg.untouched", len(sp.PACKAGES) == 3 and sp.package_for_price(sp.STUDIO_PRICE_ID)["kind"] == "studio_3mo")
check("shared.plain_is_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID)["kind"] == "plan_real_sets")   # #287: the 3-month package is retired
check("shared.sku_is_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID, "plan_studio_only_4h")["kind"] == "plan_real_sets")
check("shared.link_is_real_sets", sp.resolve_spec(sp.STUDIO_PRICE_ID, "", "plink_1UR148DAWlnEb9RfffEDwxut")["kind"] == "plan_real_sets")
check("unknown.none", sp.resolve_spec("price_nope") is None and sp.resolve_spec("price_1ULR8tDAWlnEb9RfzcUb3YgJ") is None)
fi3 = sp._per_unit(sp.PLANS["price_1UR9slDAWlnEb9RfwuwNC0ac"], 3)
check("per_unit.3", fi3["hours"] == 3 and fi3["one_off"] == 2991 and sp.PLANS["price_1UR9slDAWlnEb9RfwuwNC0ac"]["hours"] == 1)
check("per_unit.monthly_ignores_qty", sp._per_unit(sp.PLANS["price_1UR0ipDAWlnEb9RfSTYiE4VE"], 2)["hours"] == 2)
check("by_name", sp.package_by_name("AI Starter")["kind"] == "plan_ai_starter"
      and sp.package_by_name("AI Growth Plan")["founding"] and sp.package_by_name("Real Sets")["kind"] == "plan_real_sets"
      and sp.package_by_name("Studio Package")["kind"] == "studio_3mo")
rn, mrr, on, ot = sp.revenue_split([{"package_name": "AI Starter Plan"}, {"package_name": "AI Wall Hour"},
                                    {"package_name": "Studio Package"}])
check("revenue_split", (rn, mrr, on, ot) == (2, 1297 + 1200, 1, 599), (rn, mrr, on, ot))

# ── emails ──
today = datetime.now(sp.pytz.timezone("America/New_York")).date()
st = sp.PLANS["price_1UR0ipDAWlnEb9RfSTYiE4VE"]
h = sp._welcome_email_html("Ana", "ABC123", st, sp.package_term(st, today))
check("mail.monthly.per_month", "Your <strong>AI Starter Plan</strong> is active — 2 hours of professional studio time every month" in h)
check("mail.monthly.pace", "<li>2 studio hours every month (1 on our real sets, 1 on the AI Wall)</li>" in h)
check("mail.monthly.rollover", "you can hold up to 4 hours at a time" in h)
check("mail.monthly.fi", "Your plan includes 1 Full Immersion video" in h and "up to 10 edited short videos" in h)
for bad in ("must be used within", "total across", "next 60 days", "60 days"):
    check(f"mail.monthly.no[{bad}]", bad not in h)
nxt = sp._add_calendar_month(today, 1)
check("mail.monthly.footer", "$1,297/month</strong>, charged automatically" in h
      and f"next charge: <strong style=\"color:#666;\">{nxt.strftime('%B')} {nxt.day}</strong>" in h, h[-700:])
check("mail.monthly.minimum", "3-month minimum" in h and "Founding price stays locked" in h)
rs_reg = sp.PLANS["price_1UXJwUDAWlnEb9RfLIi8E2ea"]
hr = sp._welcome_email_html("Ana", "ABC123", rs_reg, sp.package_term(rs_reg, today))
check("mail.regular.no_founding_line", "Founding price stays locked" not in hr and "$1,497/month" in hr)
wh = sp.PLANS["price_1UR0ixDAWlnEb9Rfw5I1cFJX"]
wt = sp.package_term(wh, date(2026, 11, 9))
h = sp._welcome_email_html("Ana", "ABC123", wh, wt)
check("mail.oneoff", "Your <strong>AI Wall Hour</strong> is confirmed: 1 studio hour ready to book" in h
      and "Book any time in the next 60 days: the last day you can book is <strong>Friday, January 08, 2027</strong>" in h
      and "Up to 3 AI worlds" in h and "1 hours" not in h, h)
check("mail.oneoff.no_billing", "charged automatically" not in h)
h3 = sp._welcome_email_html("Ana", "ABC123", fi3, sp.package_term(fi3, date(2026, 11, 9)))
check("mail.oneoff.qty", "3 studio hours ready to book" in h3)
an = sp.PLANS["price_1UZaCCDAWlnEb9RfKpoeJTAI"]
h = sp._welcome_email_html("Ana", "ABC123", an, sp.package_term(an, date(2026, 11, 9)))
check("mail.annual", "4 hours of professional studio time every month for the next 12 months" in h
      and "All 48 hours of your year are already in your portal" in h and "November 09, 2027" in h
      and "charged automatically" not in h, h)

# ── the webhook, end to end (WP and email stubbed) ──
STORE, POSTS, MAILS, SLACK = {}, [], [], []
WP = {"existing": False, "found": True}


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
        if not WP["found"]:
            return R({"success": True, "data": {"found": False}})
        return R({"success": True, "data": {"found": True, "duplicate": False, "added": 2, "available": 4,
                                            "end_after": data.get("contract_end")}})
    return R({"success": False})


LINES, SESSIONS = {}, {}


def fake_stripe_get(ep, params=None):
    if ep.startswith("checkout/sessions/") and ep.endswith("/line_items"):
        return {"data": LINES.get(ep.split("/")[2], [])}
    if ep == "checkout/sessions":
        return {"data": SESSIONS.get((params or {}).get("subscription"), [])}
    return {}


sp.http_requests.post = fake_post
sp.configure(pg_load=lambda k, d: STORE.get(k, d), pg_save=lambda k, v: STORE.__setitem__(k, v),
             post_slack=lambda ch, t: SLACK.append((ch, t)), pipeline_event=lambda *a, **k: None,
             send_email=lambda to, subj, html: MAILS.append((to, subj, html)) or True,
             stripe_get=fake_stripe_get, lead_lookup_by_email=lambda e: (None, None),
             lead_lookup_by_name=lambda n: (None, None), update_sheet_status=lambda *a: None,
             report_error=lambda *a: None, matt_channel="M", lara_channel="L",
             invoice_defer_seconds=0)

# new client, Real Sets link on the shared $1,200 price
LINES["cs_rs"] = [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_rs", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_rs", "payment_link": "plink_1UR148DAWlnEb9RfffEDwxut", "metadata": {"sku": "plan_studio_only_4h"},
    "customer_details": {"email": "Rita@X.com", "name": "Rita Lopes"}}}})
prov = [p for p in POSTS if p.get("action") == "mwm_studio_provision_client"][-1]
check("co.real_sets", r.get("package") == "plan_real_sets", r)
check("co.provision_payload", prov["package"] == "Real Sets Plan" and prov["contract_hours"] == "4"
      and prov["monthly_hours"] == "4", prov)
check("co.welcome", MAILS[-1][1] == "Welcome to MWM Studios — your Real Sets Plan is active 🎬" and "NEW123" in MAILS[-1][2])
check("co.marked", "rita@x.com|plan_real_sets" in STORE.get(sp._CHECKOUT_KEY, {}))
check("co.slack_terms", any("4h/month, ongoing (rolls over, holds up to 8h)" in t for _, t in SLACK)
      and not any("1-month trial" in t for _, t in SLACK if "Rita" in t))
# the old 3-month package checkout: same price, no link/sku -> unchanged path (no monthly_hours)
LINES["cs_old"] = [{"price": {"id": sp.STUDIO_PRICE_ID}, "quantity": 1}]
r = sp.handle_stripe_event({"id": "evt_old", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_old", "customer_details": {"email": "old@x.com", "name": "Old Client"}}}})
prov = [p for p in POSTS if p.get("action") == "mwm_studio_provision_client"][-1]
check("co.old_link_is_real_sets_now", r.get("package") == "plan_real_sets" and prov.get("monthly_hours") == "4"
      and prov["contract_hours"] == "4", (r, prov))   # #287: every $1,200 checkout is the rolling Real Sets plan
# existing portal client buys 2 Full Immersion videos -> top-up, hours-added email
WP["existing"] = True
LINES["cs_fi"] = [{"price": {"id": "price_1UR9slDAWlnEb9RfwuwNC0ac"}, "quantity": 2}]
n0 = len(POSTS)
r = sp.handle_stripe_event({"id": "evt_fi", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_fi", "customer_details": {"email": "david@x.com", "name": "David R"}}}})
tp = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("co.existing.topup", len(tp) == 1 and tp[0]["add_hours"] == "2" and tp[0]["cap_hours"] == "0"
      and tp[0]["ref"] == "buy:evt_fi" and "package" not in tp[0], tp)
check("co.existing.mail", MAILS[-1][1] == "MWM Studios — your Full Immersion hours are in your portal 🎬"
      and "access code you already have" in MAILS[-1][2] and "4 hours</strong> available" in MAILS[-1][2]
      and "being generated" not in MAILS[-1][2], MAILS[-1][1])
# existing client upgrades to AI Growth -> package + monthly hours + cap sent
LINES["cs_gr"] = [{"price": {"id": "price_1UR13hDAWlnEb9Rfv3SarAEu"}, "quantity": 1}]
n0 = len(POSTS)
sp.handle_stripe_event({"id": "evt_gr", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_gr", "customer_details": {"email": "ana@x.com", "name": "Ana"}}}})
tp = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("co.upgrade", tp and tp[0]["package"] == "AI Growth Plan" and tp[0]["monthly_hours"] == "4"
      and tp[0]["cap_hours"] == "8" and tp[0]["add_hours"] == "4", tp)
check("co.upgrade.mail", "This month's hours are already in your portal" in MAILS[-1][2]
      and "$1,697/month" in MAILS[-1][2])
WP["existing"] = False

# ── invoice.paid: the monthly renewal ──
pe = int(datetime(2026, 12, 16, 12, tzinfo=sp.pytz.utc).timestamp())


def inv(iid, reason, price, sku="", sub="sub_1", new_shape=False, email="david@x.com"):
    line = ({"pricing": {"price_details": {"price": price}}} if new_shape else {"price": {"id": price}})
    line.update({"quantity": 1, "period": {"end": pe}})
    o = {"id": iid, "billing_reason": reason, "customer_email": email, "customer_name": "David R",
         "lines": {"data": [line]}}
    if new_shape:
        o["parent"] = {"subscription_details": {"subscription": sub, "metadata": {"sku": sku}}}
    else:
        o["subscription"] = sub
        o["subscription_details"] = {"metadata": {"sku": sku}}
    return {"id": "evt_" + iid, "type": "invoice.paid", "data": {"object": o}}


n0 = len(POSTS); nm = len(MAILS)
r = sp.handle_stripe_event(inv("in_1", "subscription_cycle", "price_1UR0ipDAWlnEb9RfSTYiE4VE"))
tp = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("cycle.topup", r.get("handled") and len(tp) == 1 and tp[0]["add_hours"] == "2" and tp[0]["cap_hours"] == "4"
      and tp[0]["contract_end"] == "2027-01-15" and tp[0]["ref"] == "invoice:in_1", (r, tp))
check("cycle.no_email", len(MAILS) == nm)
check("cycle.slack", any("AI Starter Plan* renewed" in t and "+2h" in t for _, t in SLACK))
r = sp.handle_stripe_event(inv("in_1", "subscription_cycle", "price_1UR0ipDAWlnEb9RfSTYiE4VE"))
check("cycle.duplicate", r.get("reason") == "duplicate")
r = sp.handle_stripe_event(inv("in_2", "subscription_cycle", "price_1UR13kDAWlnEb9RfxUYIOCE0", new_shape=True))
tp = [p for p in POSTS if p.get("action") == "mwm_studio_topup_client"][-1]
check("cycle.new_api_shape", r.get("handled") and tp["ref"] == "invoice:in_2" and tp["cap_hours"] == "8", (r, tp))
n0 = len(POSTS)
r = sp.handle_stripe_event(inv("in_3", "subscription_cycle", sp.STUDIO_PRICE_ID))
tp = [p for p in POSTS[n0:] if p.get("action") == "mwm_studio_topup_client"]
check("cycle.old_price_rolls_now", r.get("handled") and len(tp) == 1 and tp[0]["add_hours"] == "4" and tp[0]["cap_hours"] == "8", r)   # #287
r = sp.handle_stripe_event(inv("in_4", "subscription_cycle", sp.STUDIO_PRICE_ID, sku="plan_studio_only_4h", new_shape=True))
tp = [p for p in POSTS if p.get("action") == "mwm_studio_topup_client"][-1]
check("cycle.real_sets_by_sku", r.get("handled") and tp["add_hours"] == "4" and tp["cap_hours"] == "8", r)
WP["found"] = False
r = sp.handle_stripe_event(inv("in_5", "subscription_cycle", "price_1UR0ipDAWlnEb9RfSTYiE4VE", email="ghost@x.com"))
check("cycle.no_portal_alert", any("NO portal account" in t and "ghost@x.com" in t for _, t in SLACK))
WP["found"] = True

# ── invoice.paid: first invoice / manual invoice ──
SESSIONS["sub_co"] = [{"id": "cs_x"}]
n0 = len(POSTS)
r = sp.handle_stripe_event(inv("in_6", "subscription_create", "price_1UR13hDAWlnEb9Rfv3SarAEu", sub="sub_co", email="new1@x.com"))
check("create.checkout_owns", r.get("reason") == "checkout-handled" and len(POSTS) == n0, r)
r = sp.handle_stripe_event(inv("in_7", "subscription_create", "price_1UR13hDAWlnEb9Rfv3SarAEu", sub="sub_hand", email="new2@x.com"))
check("create.by_hand_provisions", r.get("handled") and r.get("via") == "invoice"
      and POSTS[-1].get("action") == "mwm_studio_provision_client" and POSTS[-1]["monthly_hours"] == "4", r)
r = sp.handle_stripe_event(inv("in_7", "subscription_create", "price_1UR13hDAWlnEb9Rfv3SarAEu", sub="sub_hand", email="new2@x.com"))
check("create.duplicate", r.get("reason") == "duplicate", r)
r = sp.handle_stripe_event(inv("in_8", "manual", "price_1UZaCEDAWlnEb9RfuTxbrbfW", sub="", email="f10@x.com"))
check("manual.annual", r.get("handled") and POSTS[-1]["contract_hours"] == "24"
      and MAILS[-1][1] == "Welcome to MWM Studios — your AI Starter Plan · Founding Year is active 🎬", r)
sp._mark_checkout("rita@x.com", "plan_ai_growth")
r = sp.handle_stripe_event(inv("in_10", "manual", "price_1UR13hDAWlnEb9Rfv3SarAEu", sub="", email="rita@x.com"))
check("manual.after_checkout", r.get("reason") == "checkout-handled", r)
r = sp.handle_stripe_event({"id": "evt_x", "type": "invoice.paid", "data": {"object": {
    "id": "in_x", "billing_reason": "subscription_cycle", "customer_email": "s@x.com",
    "lines": {"data": [{"price": {"id": "price_1UYwVNDAWlnEb9RfR8wALArN"}, "quantity": 1}]}}}})
check("invoice.shawnie_ignored", r.get("reason") == "not-a-plan", r)

# ── WP snippet 15 (repo copy) ──
PHP = open(os.path.join(HERE, "wordpress", "wp-snippet-15-provisioning-endpoint.php"), encoding="utf-8").read()
check("wp.topup_action", "add_action( 'wp_ajax_nopriv_mwm_studio_topup_client', 'mwm_s7_topup_client' );" in PHP)
check("wp.cap_rule", "$after = min( $after, max( $before, $used + $cap ) );" in PHP)
check("wp.end_only_later", "$end_in > (string) $old_end" in PHP and "'mwm_portal_topup_refs'" in PHP)
check("wp.counts_like_portal", "status IN ('confirmed','completed','cancelled_late')" in PHP)
check("wp.monthly_param", "isset( $_POST['monthly_hours'] ) ? max( 0, (float) $_POST['monthly_hours'] ) : 4" in PHP)
check("wp.auth", PHP.count("hash_equals( $expected, $given )") == 3)

# ── Maya / app ──
APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
AIS = open(os.path.join(HERE, "ai_studio.py"), encoding="utf-8").read()
check("maya.no_3mo_package", "12 hours of professional studio time over 3 months" not in APP
      and "Purchase page: mwmcreations.com/studio-package/" not in APP)
check("maya.real_sets", APP.count("The Real Sets plan (PATCH #278") == 2 and "unused hours roll over, up to 8 hours" in APP)
check("maya.book_studio", "mwmcreations.com/book-studio/#hybrid-ai" in APP and "full list is on mwmcreations.com/ai-studio." not in APP)
check("maya.196_kept", APP.count("$196") >= 6)
check("ai.no_studio_only_line", "- Studio Only:" not in AIS and "- Real Sets: $1,200/month founding price (regular $1,497)" in AIS
      and '"Studio Only" (the name until 8 Nov 2026) = Real Sets.' in AIS)
import ai_studio as ai  # noqa: E402
check("ai.book_studio_is_ai_page", ai.on_ai_page("https://mwmcreations.com/book-studio/#hybrid-ai")
      and ai.on_ai_page("https://mwmcreations.com/ai-studio/") and not ai.on_ai_page("https://mwmcreations.com/"))
os.environ["AI_STUDIO_PAGE_LIVE"] = "1"
check("ai.link", "https://mwmcreations.com/book-studio/#hybrid-ai" in ai.maya_ai_context("", "asked"))
os.environ.pop("AI_STUDIO_PAGE_LIVE", None)
blk = APP[APP.index("def admin_studio_topup():"):APP.index("def admin_studio_topup():") + 2200]
check("app.topup_route", "@app.route('/admin/studio-topup'" in APP and "_admin_secret_ok" in blk
      and "dry_run=not apply" in blk)
check("app.webhook_unchanged", "_sw_res = _studio.handle_stripe_event(ev)" in APP)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch277.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #277 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("277: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE278 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
