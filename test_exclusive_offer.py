"""PATCH #132 — Exclusive Video Offer purchase handling + Maya offer context."""
import sys, os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exclusive_offer as xo

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + label)
    else:
        FAIL += 1
        print("  FAIL " + label)


def section(t):
    print("\n== " + t)


ET = timezone(timedelta(hours=-4))
FRI = datetime(2026, 9, 25, 15, 0, tzinfo=ET)   # a Friday


class Wrapped(dict):
    """Stands in for LeadRecord: the store wraps what you set (#56)."""


class Store(dict):
    def __setitem__(self, k, v):
        super().__setitem__(k, Wrapped(v))


def rig(leads=None, slack_fails=False):
    st = {"slack": [], "sheet": [], "pg": {}, "errors": [], "pipe": []}
    store = Store()
    for k, v in (leads or {}).items():
        store[k] = v

    def post(ch, text):
        if slack_fails:
            raise RuntimeError("slack down")
        st["slack"].append((ch, text))

    def by_email(e):
        for k, v in store.items():
            if (v.get("email") or "").lower() == e:
                return k, v
        return None, None

    def by_phone(p):
        d = "".join(c for c in p if c.isdigit())[-10:]
        for k, v in store.items():
            if d and "".join(c for c in str(v.get("phone") or k) if c.isdigit())[-10:] == d:
                return k, v
        return None, None

    def by_name(n):
        hits = [(k, v) for k, v in store.items() if (v.get("name") or "").lower() == n.lower()]
        return hits[0] if len(hits) == 1 else (None, None)

    xo._deps.clear()
    xo.configure(
        report_error=lambda w, e, c="": st["errors"].append((w, str(e), c)),
        post_slack=post,
        pg_load=lambda k, d=None: st["pg"].get(k, d),
        pg_save=lambda k, v: st["pg"].__setitem__(k, v),
        lead_data=store,
        lead_lookup_by_email=by_email,
        lead_lookup_by_phone=by_phone,
        lead_lookup_by_name=by_name,
        update_sheet_status=lambda *a: st["sheet"].append(a),
        pipeline_event=lambda *a, **k: st["pipe"].append((a, k)),
        lara_channel="C_LARA", rob_channel="C_ROB", dev_channel="C_DEV",
        now=lambda: FRI,
    )
    return st, store


def ev(eid="evt_1", sku="exclusive_video_offer", paid=True, email="buyer@acme.com",
       phone="+14075551234", name="Dana Buyer", company="Acme Co", typ="checkout.session.completed"):
    return {"id": eid, "type": typ, "data": {"object": {
        "id": "cs_test_1", "object": "checkout.session",
        "payment_status": "paid" if paid else "unpaid",
        "amount_total": 249700, "payment_link": "plink_1UJEPeDAWlnEb9Rf4lAvkFH5",
        "metadata": {"sku": sku} if sku else {},
        "customer_details": {"email": email, "phone": phone, "name": name,
                             "individual_name": name, "business_name": company},
    }}}


section("routing — only this product's checkout is owned")
st, store = rig()
ok(xo.handle_offer_paid(ev(sku="studio_hour_oneoff")) is None, "another sku is not ours (returns None)")
ok(xo.handle_offer_paid(ev(sku=None)) is None, "no metadata is not ours")
ok(xo.handle_offer_paid(ev(typ="invoice.paid")) is None, "a non-checkout event is not ours")
ok(st["slack"] == [] and len(store) == 0, "...and none of them touched Slack or the store")

section("paid, lead matched by email — marked client, team alerted")
st, store = rig({"whatsapp:+14075550000": {"name": "Dana Buyer", "email": "buyer@acme.com",
                                           "phone": "", "status": "contacted"}})
res = xo.handle_offer_paid(ev())
rec = store["whatsapp:+14075550000"]
ok(res and res["handled"] and res["paid"], "handled and paid")
ok(rec["outcome"] == "Won" and rec["product"] == "Exclusive Video Offer", "outcome Won + product written")
ok(rec["status"] == "client" and rec["relationship"] == "new_client", "status client, relationship new_client (sales rail off)")
ok(rec["booked"] is True, "booked=True — the cold-lead checker skips booked records")
ok(rec["deal_value"] == 2497.0, "deal value $2,497")
ok(rec["exclusive_offer"]["payment_link"] == "plink_1UJEPeDAWlnEb9Rf4lAvkFH5", "payment link recorded on the record")
ok(rec["phone"] == "+14075551234" and rec["business"] == "Acme Co", "blank phone/business filled from checkout")
chans = [c for c, _ in st["slack"]]
ok(chans == ["C_LARA", "C_ROB"], "alert posted to #lara and #rob, nowhere else")
t = st["slack"][0][1]
for frag in ("<@U01N06A8VE1>", "Dana Buyer", "Acme Co", "buyer@acme.com", "+14075551234",
             "$2,497.00", "plink_1UJEPeDAWlnEb9Rf4lAvkFH5", "matched by email", "Mon Sep 28"):
    ok(frag in t, f"alert carries {frag!r}")
ok(st["sheet"] and st["sheet"][0][1] == "Client — Exclusive Video Offer", "sheet status pushed")
ok(st["pipe"] and st["pipe"][0][0][0] == "CLIENT_WON", "CLIENT_WON pipeline event")
ok(st["pg"].get("exclusive_offer_evt:evt_1") is True, "event stamped processed")

section("idempotent on the Stripe event id")
n = len(st["slack"])
res2 = xo.handle_offer_paid(ev())
ok(res2.get("duplicate") is True and len(st["slack"]) == n, "a retried event sends nothing twice")

section("match falls back to phone, then name")
st, store = rig({"14075551234": {"name": "Someone Else", "email": "", "phone": "14075551234"}})
xo.handle_offer_paid(ev(email="new@acme.com"))
ok(store["14075551234"]["outcome"] == "Won", "matched by phone when email misses")
ok("matched by phone" in st["slack"][0][1], "alert says it matched by phone")
st, store = rig({"k1": {"name": "Dana Buyer", "email": "", "phone": ""}})
xo.handle_offer_paid(ev(email="other@x.com", phone=""))
ok(store["k1"]["outcome"] == "Won", "matched by exact full name as last resort")

section("no lead at all — a client record is created (and it is the stored one)")
st, store = rig()
xo.handle_offer_paid(ev(email="fresh@x.com", phone="(407) 555-9999"))
ok("4075559999" in store, "keyed by phone digits")
r = store["4075559999"]
ok(isinstance(r, Wrapped) and r.get("outcome") == "Won" and r.get("booked") is True,
   "fields landed on the STORED (wrapped) object, not an orphan (#56)")
ok(r.get("source") == "Stripe — Exclusive Offer page", "source says where they came from")
ok("new client record created" in st["slack"][0][1], "alert says a record was created")

section("not settled (delayed method) — alert, but do not mark Won")
st, store = rig({"k1": {"name": "Dana Buyer", "email": "buyer@acme.com"}})
res = xo.handle_offer_paid(ev(paid=False))
ok(store["k1"].get("outcome") is None, "lead NOT marked Won before the money settles")
ok("PAYMENT NOT SETTLED" in st["slack"][0][1] and "Do not schedule yet" in st["slack"][0][1],
   "team told not to schedule yet")
ok(st["pipe"] == [], "no CLIENT_WON on an unsettled payment")

section("Slack down — not stamped, so Stripe's retry can deliver the alert")
st, store = rig(slack_fails=True)
xo.handle_offer_paid(ev(eid="evt_9"))
ok("exclusive_offer_evt:evt_9" not in st["pg"], "idempotency stamp withheld when no alert landed")
ok(any(w == "exclusive_offer.no_alert" for w, _, _ in st["errors"]), "the miss is reported loudly")

section("the 1-business-day promise date")
ok(xo.next_business_day(datetime(2026, 9, 25)).weekday() == 0, "Friday → Monday")
ok(xo.next_business_day(datetime(2026, 9, 26)).weekday() == 0, "Saturday → Monday")
ok(xo.next_business_day(datetime(2026, 9, 23)).day == 24, "Wednesday → Thursday")

section("buyer details — both API shapes")
b = xo.buyer_from_session({"collected_information": {"individual_name": "Ana Lima",
                           "business_name": "Lima LLC"},
                           "customer_details": {"email": "ANA@X.COM"}})
ok(b == {"name": "Ana Lima", "company": "Lima LLC", "email": "ana@x.com", "phone": ""},
   "reads collected_information and lowercases email")

section("Maya — offer context only on the offer page")
c = xo.maya_offer_context("https://mwmcreations.com/exclusive-offer/")
ok("$2,497" in c and "up to 6 hours on set" in c, "price and 6 hours are in the context")
ok("never offer a discount" in c, "no-discount rule is in the context (ROB)")
ok("within 1 business day" in c, "same promise as the Stripe confirmation")
ok("/terms/#20" in c and "90 days" in c and "two rounds of revisions" in c, "terms §20 facts are in the context")
ok(xo.maya_offer_context("https://mwmcreations.com/book-studio/") == "", "other pages get nothing")
ok(xo.maya_offer_context("") == "" and xo.maya_offer_context(None) == "", "no URL gets nothing")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
