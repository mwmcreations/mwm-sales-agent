#!/usr/bin/env python3
"""Patch #53 — more than one studio package.

The assertion this file exists for: a checkout for the NEW price must provision
4 hours over exactly 30 days, and the welcome email must state the same
deadline that was written into WordPress.

Two things made that non-obvious, and both are pinned below.

1. Detection was `price_id == STUDIO_PRICE_ID` returning a bool. A different
   price answered "other-product", so the money landed and nothing was
   provisioned — no portal account, no email, no alert. Silent, in the
   expensive direction. A test that only checked the happy path for the
   3-month package would still pass while the trial quietly did nothing.

2. The 3-month path sends WordPress `contract_end = term end + 30 days grace`,
   because WP enforces that single field as the hard stop on booking. Copying
   that shape would have given a 30-day package SIXTY days of booking — twice
   what Michael quoted the client. There is a test below whose only job is to
   fail if grace ever leaks into the trial.
"""
import re
import sys
from datetime import date, datetime, timedelta

import studio_package as sp

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  {}".format(label))
    else:
        FAIL += 1
        print("  FAIL  {}".format(label))


def section(t):
    print("\n" + "=" * 62 + "\n  {}\n".format(t) + "=" * 62)


TRIAL = sp.PACKAGES[sp.TRIAL_PRICE_ID]
PKG = sp.PACKAGES[sp.STUDIO_PRICE_ID]


# ══════════════════════════════════════════════════════════════════
section("THE TERM — 30 days means 30 days, not 30 plus grace")
# ══════════════════════════════════════════════════════════════════
start = date(2026, 8, 5)
t_trial = sp.package_term(TRIAL, start)
t_pkg = sp.package_term(PKG, start)

ok(t_trial["term_end"] == date(2026, 9, 4), "trial term ends 30 days out")
ok(t_trial["booking_deadline"] == date(2026, 9, 4),
   "trial booking deadline IS the term end — no grace")
ok((t_trial["booking_deadline"] - start).days == 30,
   "trial gives exactly 30 bookable days, which is what the client was quoted")
ok(TRIAL["grace_days"] == 0, "the trial's grace is zero, explicitly")

# the regression this file exists to catch
ok((t_trial["booking_deadline"] - start).days != 60,
   "the trial does NOT get 60 days (grace leaking in is the bug)")

# and the existing package is untouched
ok(t_pkg["term_end"] == date(2026, 11, 3), "3-month term still ends at 90 days")
ok(t_pkg["booking_deadline"] == date(2026, 12, 3),
   "3-month booking deadline is still term + 30 days grace")
ok((t_pkg["booking_deadline"] - start).days == 120,
   "3-month package still gets 120 bookable days — unchanged by this patch")

ok(sp.package_term(TRIAL, datetime(2026, 8, 5, 23, 59))["term_end"] == date(2026, 9, 4),
   "a datetime is accepted as well as a date")
ok(sp.package_term({}, start)["term_end"] == start, "an empty spec degrades to zero days")

ok(sp.term_phrase(TRIAL) == "30 days", "the trial is described in days")
ok(sp.term_phrase(PKG) == "3 months", "the package is described in months")


# ══════════════════════════════════════════════════════════════════
section("DETECTION — a second price must be recognised, not ignored")
# ══════════════════════════════════════════════════════════════════
ok(sp.package_for_price(sp.TRIAL_PRICE_ID) is TRIAL, "the trial price resolves")
ok(sp.package_for_price(sp.STUDIO_PRICE_ID) is PKG, "the package price resolves")
ok(sp.package_for_price("price_somethingelse") is None, "an unrelated price does not")
ok(sp.package_for_price("") is None and sp.package_for_price(None) is None,
   "empty and None resolve to nothing")
ok(sp.package_for_price("  " + sp.TRIAL_PRICE_ID + "  ") is TRIAL,
   "whitespace around a price id is tolerated")

ok(sp.TRIAL_PRICE_ID != sp.STUDIO_PRICE_ID, "the two price ids are actually different")
ok(len(PACKAGE_KEYS := set(s["kind"] for s in sp.PACKAGES.values())) == len(sp.PACKAGES),
   "every package has a distinct kind")
ok(len(set(s["name"] for s in sp.PACKAGES.values())) == len(sp.PACKAGES),
   "every package has a distinct name — package_by_name must be unambiguous")

for spec in sp.PACKAGES.values():
    ok(sp.package_by_name(spec["name"]) is spec,
       "{}: resolves back from its name".format(spec["kind"]))
ok(sp.package_by_name("STUDIO TRIAL — 1 MONTH") is TRIAL, "name lookup is case-insensitive")
ok(sp.package_by_name("") is None, "a blank name resolves to nothing")


# ══════════════════════════════════════════════════════════════════
section("END TO END — the trial webhook, with every dep mocked")
# ══════════════════════════════════════════════════════════════════
SENT = {"wp": [], "emails": [], "slack": [], "sheet": [], "pipeline": [], "errors": []}
LEADS = {"marcus@webbmedia.com": {"name": "Marcus Webb", "email": "marcus@webbmedia.com"}}


class FakeResp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        return {"success": True, "data": {"access_code": "K7M2QX", "existing": False}}


def fake_post(url, data=None, headers=None, timeout=None):
    SENT["wp"].append(dict(data or {}))
    return FakeResp()


sp.http_requests.post = fake_post

sp.configure(
    report_error=lambda ctx, exc, detail="": SENT["errors"].append((ctx, str(exc), detail)),
    post_slack=lambda ch, txt: SENT["slack"].append((ch, txt)),
    pipeline_event=lambda et, **kw: SENT["pipeline"].append((et, kw)),
    send_email=lambda to, subj, html: (SENT["emails"].append((to, subj, html)) or True),
    stripe_get=lambda ep, params=None: {
        "data": [{"price": {"id": sp.TRIAL_PRICE_ID}}]},
    pg_load=lambda k, d=None: {} if k == "stripe_events_processed" else d,
    pg_save=lambda k, v: None,
    lead_lookup_by_email=lambda e: (e, LEADS[e]) if e in LEADS else (None, None),
    lead_lookup_by_name=lambda n: (None, None),
    update_sheet_status=lambda n, s: SENT["sheet"].append((n, s)),
    heartbeat=lambda n: None,
    matt_channel="#matt", lara_channel="#lara", dev_channel="#dev",
    lead_data=LEADS,
)

res = sp.handle_stripe_event({
    "id": "evt_trial_test_1",
    "type": "checkout.session.completed",
    "data": {"object": {
        "id": "cs_test_trial",
        "customer_details": {"email": "marcus@webbmedia.com", "name": "Marcus Webb"},
        "amount_total": 140000,
    }},
})

ok(res.get("handled") is True, "the trial checkout is HANDLED, not ignored: {}".format(res))
ok(res.get("package") == "studio_trial_1mo", "and identified as the trial")
ok(SENT["errors"] == [], "no errors raised: {}".format(SENT["errors"]))

# --- what WordPress was actually told ---
ok(len(SENT["wp"]) == 1, "exactly one provisioning call")
wp = SENT["wp"][0] if SENT["wp"] else {}
ok(wp.get("contract_hours") == "4", "WP was told 4 hours, not 12 (got {!r})"
   .format(wp.get("contract_hours")))
ok(wp.get("package") == "Studio Trial — 1 Month", "WP was told the trial package name")
ok(wp.get("email") == "marcus@webbmedia.com", "WP got the payer's email")
try:
    _cs = datetime.strptime(wp.get("contract_start", ""), "%Y-%m-%d").date()
    _ce = datetime.strptime(wp.get("contract_end", ""), "%Y-%m-%d").date()
    _span = (_ce - _cs).days
except Exception:
    _cs = _ce = None
    _span = -1
ok(_span == 30, "WP's booking window is exactly 30 days (got {})".format(_span))
ok(_span != 60, "and specifically NOT 60 — grace did not leak in")

# --- the welcome email ---
ok(len(SENT["emails"]) == 1, "exactly one welcome email")
to, subj, html = SENT["emails"][0] if SENT["emails"] else ("", "", "")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
ok(to == "marcus@webbmedia.com", "sent to the payer")
ok("Studio Trial" in subj, "the subject names the trial, not the package: {!r}".format(subj))
ok("4 hours" in text, "the body says 4 hours")
ok("12 hours" not in text, "the body does NOT say 12 hours")
ok("30 days" in text, "the body says 30 days")
ok("3 months" not in text, "the body does NOT say 3 months")
ok("stay bookable for 30 days after" not in text,
   "the body does NOT promise grace the portal will not honour")
ok("K7M2QX" in html, "the access code is in the email")

# THE COUPLING THAT MATTERS: the date in the email is the date in WordPress.
if _ce:
    ok(_ce.strftime("%B %d, %Y") in text,
       "the deadline in the email is the exact date written to WP ({})"
       .format(_ce.strftime("%B %d, %Y")))
    ok("last day you can book" in text, "and it is labelled as the booking deadline")

# --- the lead record ---
rec = LEADS["marcus@webbmedia.com"]
ok(rec.get("product") == "Studio Trial — 1 Month", "product names the trial")
ok(rec.get("outcome") == "Won", "the lead is marked Won")
box = rec.get("studio_package") or {}
ok(box.get("variant") == "studio_trial_1mo", "the record carries the variant")
ok(box.get("hours") == 4, "the record carries 4 hours")
ok(box.get("term_days") == 30, "the record carries a 30-day term")
ok(box.get("recurring") is False, "the record says this is NOT recurring")
ok(box.get("mrr") == 0, "the record contributes ZERO MRR")
ok(box.get("one_off") == 1400, "the record carries the $1,400 one-off")
ok(box.get("booking_deadline", "")[:10] == (_ce.isoformat() if _ce else "?"),
   "the record's deadline matches WordPress")
ok(box.get("stripe_event") == "evt_trial_test_1", "the stripe event is recorded")
ok(SENT["sheet"] and SENT["sheet"][0][1] == "Client — Studio Trial (1 month)",
   "the sheet status distinguishes a trial: {}".format(SENT["sheet"]))

# --- what the team was told ---
matt = " ".join(t for ch, t in SENT["slack"] if ch == "#matt")
ok("not the 3-month package" in matt.lower() or "not the 3-month" in matt.lower(),
   "#matt is told explicitly this is the trial")
ok("not MRR" in matt or "NOT MRR" in matt, "#matt is told it is not recurring revenue")
ok("$1,400" in matt, "#matt sees the real amount")
ok("$1,200" not in matt, "#matt is NOT shown the package price")
lara = " ".join(t for ch, t in SENT["slack"] if ch == "#lara")
ok("4h" in lara or "4 h" in lara, "#lara is told the hours")
ok("30 days" in lara, "#lara is told the term")

# --- an unrelated product is still ignored ---
sp._deps["stripe_get"] = lambda ep, params=None: {"data": [{"price": {"id": "price_other"}}]}
res2 = sp.handle_stripe_event({
    "id": "evt_other_1", "type": "checkout.session.completed",
    "data": {"object": {"id": "cs_other",
                        "customer_details": {"email": "x@y.com", "name": "X"}}}})
ok(res2.get("handled") is False and res2.get("reason") == "other-product",
   "an unrelated price is still ignored, not mis-provisioned")
ok(len(SENT["wp"]) == 1, "...and provisioned nothing")


# ══════════════════════════════════════════════════════════════════
section("#54 — editing is included, and the $1,400 buys no credit")
# ══════════════════════════════════════════════════════════════════
ok(TRIAL["includes_note"] == "Post-production editing is included",
   "the trial records that editing is included")
ok(PKG["includes_note"] == "",
   "the 3-month package adds nothing — its live email is unchanged")
ok(TRIAL["credits_toward_contract"] is False,
   "the trial buys NO credit toward a 3-month contract")
ok(PKG["credits_toward_contract"] is False, "and neither does the package")
ok(all(s["credits_toward_contract"] is False for s in sp.PACKAGES.values()),
   "nothing in the system may imply a credit — a fresh contract starts at full price")

# the trial email must say it; the package email must not have grown a line
_tt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
      sp._welcome_email_html("X", "ABC123", TRIAL, sp.package_term(TRIAL, start))))
_pt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
      sp._welcome_email_html("X", "ABC123", PKG, sp.package_term(PKG, start))))
ok("editing is included" in _tt, "the trial email states editing is included")
ok("editing" not in _pt,
   "the package email is untouched — no deliverables line appeared in it")

_th = sp._welcome_email_html("X", "ABC123", TRIAL, sp.package_term(TRIAL, start))
_ph = sp._welcome_email_html("X", "ABC123", PKG, sp.package_term(PKG, start))
ok(_ph.count("<li>") == 5, "the package email still has exactly 5 bullets")
ok(_th.count("<li>") == 6, "the trial email has 6 — the editing line")
ok(_th.count("<li>") == _th.count("</li>"), "the trial email's list tags balance")
ok(_ph.count("<li>") == _ph.count("</li>"), "the package email's list tags balance")

# do not invent deliverables he never named
for invented in ("short-form", "captions", "logo animation", "short cuts"):
    ok(invented not in _tt.lower(),
       "the trial email does NOT promise {!r} — he said 'editing'".format(invented))


# ══════════════════════════════════════════════════════════════════
section("REGRESSION — the 3-month flow must be untouched")
# ══════════════════════════════════════════════════════════════════
# This matters more than the new feature. The 3-month package is live and
# earning; a refactor that quietly changed its hours, its grace period or its
# email would be a far worse outcome than the trial not working.
for k in SENT:
    SENT[k] = []
LEADS2 = {"dana@example.com": {"name": "Dana Reed", "email": "dana@example.com"}}
sp._deps["lead_data"] = LEADS2
sp._deps["lead_lookup_by_email"] = lambda e: (e, LEADS2[e]) if e in LEADS2 else (None, None)
sp._deps["stripe_get"] = lambda ep, params=None: {
    "data": [{"price": {"id": sp.STUDIO_PRICE_ID}}]}

res3 = sp.handle_stripe_event({
    "id": "evt_pkg_regression_1", "type": "checkout.session.completed",
    "data": {"object": {"id": "cs_pkg",
                        "customer_details": {"email": "dana@example.com",
                                             "name": "Dana Reed"},
                        "amount_total": 120000}}})

ok(res3.get("handled") is True, "the 3-month checkout is still handled")
ok(res3.get("package") == "studio_3mo", "and identified as the package")
wp3 = SENT["wp"][0] if SENT["wp"] else {}
ok(wp3.get("contract_hours") == "12", "WP is still told 12 hours (got {!r})"
   .format(wp3.get("contract_hours")))
ok(wp3.get("package") == "Studio Package", "WP is still told 'Studio Package'")
try:
    _s3 = datetime.strptime(wp3.get("contract_start", ""), "%Y-%m-%d").date()
    _e3 = datetime.strptime(wp3.get("contract_end", ""), "%Y-%m-%d").date()
    _sp3 = (_e3 - _s3).days
except Exception:
    _sp3 = -1
ok(_sp3 == 120, "the 3-month booking window is still 120 days (90 + 30 grace), got {}"
   .format(_sp3))

_, subj3, html3 = SENT["emails"][0] if SENT["emails"] else ("", "", "")
text3 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html3))
ok(subj3 == "Welcome to MWM Studios — your Studio Package is active 🎬",
   "the 3-month subject line is byte-identical to before: {!r}".format(subj3))
ok("12 hours of professional studio time" in text3, "the body still says 12 hours")
ok("3 months" in text3, "the body still says 3 months")
ok("stay bookable for 30 days after" in text3, "the grace sentence is still there")
ok("4 hours of professional studio time" not in text3,
   "no trial hours language leaked into the package email")
ok("must be used within 30 days" not in text3,
   "no trial deadline language leaked into the package email")
ok("last day you can book" not in text3,
   "the package email still has no hard booking date (it has grace instead)")

rec3 = LEADS2["dana@example.com"]
ok(rec3.get("product") == "Studio Package", "product is still 'Studio Package'")
ok(rec3.get("outcome") == "Won", "still marked Won")
box3 = rec3.get("studio_package") or {}
ok(box3.get("variant") == "studio_3mo", "the record names the 3-month variant")
ok(box3.get("recurring") is True, "recorded as recurring")
ok(box3.get("mrr") == 1200, "recorded at $1,200 MRR")
ok(SENT["sheet"] and SENT["sheet"][0][1] == "Client — Studio Package",
   "the sheet status is unchanged: {}".format(SENT["sheet"]))
matt3 = " ".join(x for ch, x in SENT["slack"] if ch == "#matt")
ok("not MRR" not in matt3, "the package alert does NOT carry the trial warning")
ok("$1,200/mo" in matt3, "the package alert shows the recurring price")


# ══════════════════════════════════════════════════════════════════
section("REVENUE — a $1,400 one-off is not $1,200 of MRR")
# ══════════════════════════════════════════════════════════════════
P, T = PKG["name"], TRIAL["name"]
ok(sp.revenue_split([{"package_name": P}] * 3) == (3, 3600, 0, 0),
   "three packages are $3,600 MRR")
ok(sp.revenue_split([{"package_name": P}] * 3 + [{"package_name": T}]) == (3, 3600, 1, 1400),
   "adding a trial does NOT change MRR, and is reported separately")
ok(sp.revenue_split([{"package_name": T}] * 2) == (0, 0, 2, 2800),
   "trials alone are zero MRR")
ok(sp.revenue_split([{"package_name": ""}, {"package_name": None}]) == (2, 2400, 0, 0),
   "legacy rows with no package name still count as the 3-month package")
ok(sp.revenue_split([{"package_name": "Podcast Pro"}]) == (1, 1200, 0, 0),
   "an unknown package name falls back to the historical default")
ok(sp.revenue_split([None, "junk", 7]) == (0, 0, 0, 0), "malformed rows are skipped")
ok(sp.revenue_split([]) == (0, 0, 0, 0) and sp.revenue_split(None) == (0, 0, 0, 0),
   "empty and None are safe")

ok(TRIAL["mrr"] == 0, "the trial spec declares zero MRR")
ok(TRIAL["recurring"] is False, "the trial spec declares itself non-recurring")
ok(PKG["mrr"] == 1200 and PKG["recurring"] is True, "the package spec is unchanged")
ok(TRIAL["one_off"] == 1400, "the trial one-off is $1,400 — the price Michael quoted")


# ══════════════════════════════════════════════════════════════════
section("A TRIAL CLIENT IS A CLIENT — stop pitching them")
# ══════════════════════════════════════════════════════════════════
ok(TRIAL["name"] in sp.PACKAGE_NAMES, "the trial counts as a purchased package")
ok(PKG["name"] in sp.PACKAGE_NAMES, "so does the package")
ok(len(sp.PACKAGE_NAMES) == len(sp.PACKAGES), "every package is in PACKAGE_NAMES")
for nm in sp.PACKAGE_NAMES:
    ok({"product": nm}.get("product") in sp.PACKAGE_NAMES,
       "{!r} stops the cold pitch sequence".format(nm))
ok("Podcast Pro" not in sp.PACKAGE_NAMES,
   "an unrelated product does NOT stop the pitch sequence")


# ══════════════════════════════════════════════════════════════════
section("#55 — registering a client who paid with no lead record")
# ══════════════════════════════════════════════════════════════════
# Real case: Gema Hiatt / HIS Agents booked herself through Calendly for the
# MWM ROADMAP 15-min call, so no lead record was ever created — not at booking,
# not when she cancelled two minutes before start, not when she paid $1,400.
# The PAID CLIENT NOT LINKED alarm has existed since #34 and told Michael to
# act; there was no route that could.
#
# These pin the pure parts the route depends on. The route itself is exercised
# against production, not here — but the term maths and the variant lookup are
# what decide whether the record agrees with WordPress and with the email the
# client already has in their inbox.
_kinds = {s["kind"]: s for s in sp.PACKAGES.values()}
ok("studio_trial_1mo" in _kinds, "the route can resolve the trial by kind")
ok("studio_3mo" in _kinds, "and the package by kind")
ok(len(_kinds) == len(sp.PACKAGES), "kind lookup is unambiguous")

# a record registered for the Aug 5 purchase must land on the SAME deadline the
# client was already told in their welcome email
_bought = datetime(2026, 8, 5, 13, 29)
_t55 = sp.package_term(_kinds["studio_trial_1mo"], _bought)
ok(_t55["booking_deadline"] == date(2026, 9, 4),
   "a record registered from the real purchase date lands on Sep 4 — the date "
   "already in the client's inbox")
ok(_t55["booking_deadline"].strftime("%B %d, %Y") == "September 04, 2026",
   "and formats identically to the email")

# registering must never make a converted client look sellable
ok(_kinds["studio_trial_1mo"]["recurring"] is False,
   "the trial is non-recurring, so the route marks them new_client")
ok(_kinds["studio_trial_1mo"]["name"] in sp.PACKAGE_NAMES,
   "and their product stops the cold pitch sequence")
ok(_kinds["studio_trial_1mo"]["sheet_status"] == "Client — Studio Trial (1 month)",
   "the sheet status names the trial")

# a backdated registration must not silently extend the term
_late = sp.package_term(_kinds["studio_trial_1mo"], datetime(2026, 8, 20))
ok(_late["booking_deadline"] == date(2026, 9, 19),
   "registering later moves the deadline with the purchase date, not with today")
ok(_late["booking_deadline"] != _t55["booking_deadline"],
   "...so a backdated purchase cannot quietly gain extra days")


# ══════════════════════════════════════════════════════════════════
section("#56 — lead_data WRAPS what you assign to it")
# ══════════════════════════════════════════════════════════════════
# The bug #55A shipped, pinned so it cannot come back. LeadData.__setitem__
# wraps a plain dict in a LeadRecord, so `lead_data[k] = d` does NOT store `d`.
# Mutating `d` afterwards writes to an orphan: no reader sees it, no flusher
# persists it, and nothing raises. #55A did that, then reported the unstored
# values in its own success response — Gema Hiatt's record read back with
# outcome="" and booked=false while the API had answered ok:true with a product.
#
# The rule this encodes: after assigning into lead_data, RE-FETCH by key before
# mutating, and answer from the store rather than from intent.
import leads_db

_ld = leads_db.LeadData()
_plain = {"name": "Wrap Test", "email": "w@example.com"}
_ld["wrapkey"] = _plain

ok(not (_ld["wrapkey"] is _plain),
   "lead_data[k] = d does NOT store the same object — it wraps it")
ok(isinstance(_ld["wrapkey"], leads_db.LeadRecord),
   "what is stored is a LeadRecord")

# the exact mistake
_plain["product"] = "Studio Trial — 1 Month"
_plain["booked"] = True
ok(_ld["wrapkey"].get("product") is None,
   "mutating the ORIGINAL dict after assignment is silently lost (the #55A bug)")
ok(not _ld["wrapkey"].get("booked"), "...including booked, exactly as seen in production")

# the fix
_fetched = _ld["wrapkey"]
_fetched["product"] = "Studio Trial — 1 Month"
_fetched["booked"] = True
ok(_ld["wrapkey"].get("product") == "Studio Trial — 1 Month",
   "re-fetching by key first makes the write land")
ok(_ld["wrapkey"].get("booked") is True, "...and booked lands too")

# a record taken OUT of the store is safe to mutate directly — which is why the
# original purchase path never hit this
_ld["existing"] = {"name": "Already There"}
_out = _ld["existing"]
_out["outcome"] = "Won"
ok(_ld["existing"].get("outcome") == "Won",
   "mutating a record read out of the store works — the purchase path's pattern")

# and the verification idea itself: intent must be checked against the store
_intended = {"product": "Studio Trial — 1 Month", "outcome": "Won", "booked": True}
_ld["verify"] = {"name": "V"}
ok(any(_ld["verify"].get(k) != v for k, v in _intended.items()),
   "an unverified write is detectable by reading the store back")
_vr = _ld["verify"]
for _k, _v in _intended.items():
    _vr[_k] = _v
ok(all(_ld["verify"].get(k) == v for k, v in _intended.items()),
   "...and a verified write reads back identical to the intent")


# ══════════════════════════════════════════════════════════════════════
# #62 — the signature that broke /admin/register-client
#
# On Aug 5 a real paying client (Gema Hiatt) was registered twice and the
# Leads-sheet write failed both times:
#
#   _update_lead_sheet_status() missing 3 required positional arguments:
#   'notes', 'service', 'next_steps'
#
# app.py cannot be imported from a test harness — it builds a Flask app and
# starts background threads at import time, which is precisely why a plain
# signature mismatch reached production twice. So this reads the SOURCE. An
# AST check is not a substitute for running the code, but it is exactly the
# right shape of test for "the caller and the callee disagree", and it costs
# nothing.
print("\n" + "=" * 62)
print("  #62 — _update_lead_sheet_status: callers must satisfy the callee")
print("=" * 62)
import ast as _ast62

_tree62 = _ast62.parse(open("app.py").read())
_fn62 = None
for _n in _ast62.walk(_tree62):
    if isinstance(_n, _ast62.FunctionDef) and _n.name == "_update_lead_sheet_status":
        _fn62 = _n
        break

ok(_fn62 is not None, "_update_lead_sheet_status is defined in app.py")
if _fn62 is not None:
    _params62 = [a.arg for a in _fn62.args.args]
    _required62 = len(_params62) - len(_fn62.args.defaults)
    ok(_params62[:2] == ["name", "outcome"],
       "name and outcome are still the leading, required arguments")
    ok(_required62 == 2,
       "notes/service/next_steps are OPTIONAL — a caller that omits them "
       "must not raise ({} required)".format(_required62))

    _sites62, _short62 = 0, []
    for _n in _ast62.walk(_tree62):
        if isinstance(_n, _ast62.Call) and getattr(_n.func, "id", "") == "_update_lead_sheet_status":
            _sites62 += 1
            _given = len(_n.args) + len(_n.keywords)
            if _given < _required62:
                _short62.append((_n.lineno, _given))
    ok(_sites62 >= 4, "every call site is being checked ({} found)".format(_sites62))
    ok(not _short62,
       "no call site passes fewer arguments than the signature requires{}".format(
           "" if not _short62 else " — offenders: {}".format(_short62)))

    # The register-client site specifically: it must say what was bought.
    _reg62 = [_n for _n in _ast62.walk(_tree62)
              if isinstance(_n, _ast62.Call)
              and getattr(_n.func, "id", "") == "_update_lead_sheet_status"
              and any(_k.arg == "service" for _k in _n.keywords)]
    ok(len(_reg62) >= 1,
       "the paid-client path names the SERVICE on the sheet row, not just a status")


# ── PATCH #70 — AD_09's $349 hour is a THIRD product ────────────────────
#
# Rob created the Stripe price on Aug 8. For a stretch after that, the price
# existed, the payment link was live, and paying it provisioned NOTHING —
# package_for_session() returned None and the handler answered "other-product".
# That is the #53 failure recurring, because PACKAGES is keyed by price ID in
# CODE and a new Stripe product does not register itself. These tests exist so
# the next product cannot repeat it silently.
section("#70 — the $349 one-off hour")

_p70 = sp.package_for_price("price_1U2Gz7DAWlnEb9Rfhl5nA8t0")
ok(_p70 is not None,
   "the AD_09 price resolves to a package (None here = money taken, nothing given)")

if _p70:
    ok(_p70["hours"] == 1, "one hour, not four and not twelve")
    ok(_p70["term_days"] == 30, "30-day term")
    ok(_p70["grace_days"] == 0,
       "ZERO grace — grace would silently double the window the ad implied")
    ok(_p70["recurring"] is False, "one-off, never a subscription")
    ok(_p70["mrr"] == 0,
       "a $349 one-off must NOT inflate MRR (the #53 lesson, restated)")
    ok(_p70["one_off"] == 349, "counted as $349 of one-off revenue")

    # The window WordPress actually enforces (S8.5 reads contract_end_date).
    _t70 = sp.package_term(_p70, date(2026, 8, 8))
    ok((_t70["booking_deadline"] - _t70["start"]).days == 30,
       "booking deadline is exactly 30 days out, not 60")

# Two products must never be mistaken for each other. Michael's ruling is that
# AD_09 leads are never offered the trial or the package, so the labels that
# drive that decision have to stay distinct.
_names70 = [x["name"] for x in sp.PACKAGES.values()]
_status70 = [x["sheet_status"] for x in sp.PACKAGES.values()]
ok(len(set(_names70)) == len(_names70), "no two packages share a product name")
ok(len(set(_status70)) == len(_status70), "no two packages share a sheet status")
ok(sp.package_for_price(sp.TRIAL_PRICE_ID)["kind"] == "studio_trial_1mo",
   "the trial still resolves to the trial (the new entry did not shadow it)")
ok(sp.package_by_name(sp.HOUR_ONEOFF_NAME)["kind"] == "studio_hour_oneoff",
   "the portal ledger can classify a one-off hour by NAME, not just price id")

# Revenue reporting: adding this product must not move MRR by a cent.
_rec70, _mrr70, _one70, _tot70 = sp.revenue_split([
    {"package_name": sp.PACKAGE_NAME},
    {"package_name": sp.HOUR_ONEOFF_NAME},
    {"package_name": sp.TRIAL_NAME},
])
ok(_mrr70 == sp.PACKAGE_MRR,
   "MRR counts only the recurring package — the $349 and the $1,400 stay out")
ok(_tot70 == 1749, "one-off revenue is $349 + $1,400 = $1,749")

# The word "trial" belongs to the OTHER product. If it ever appears in this
# one's client-facing strings, a cold AD_09 buyer gets told they are on a trial.
if _p70:
    _txt70 = " ".join(str(_p70.get(k, "")) for k in
                      ("name", "price_label", "pace_note", "includes_note",
                       "sheet_status")).lower()
    ok("trial" not in _txt70,
       "no client-facing string on the $349 product says 'trial'")
    ok("month" not in _txt70 and "/mo" not in _txt70 and "recurring" not in _txt70,
       "nothing on the $349 product reads as monthly or recurring")

print("\nPATCH70_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))


print("\n" + "=" * 62)
print("  STUDIO PACKAGES (#53): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
