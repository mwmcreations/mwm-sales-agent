#!/usr/bin/env python3
"""GATE for PATCH #277 — an ongoing monthly plan reads as ongoing in the welcome
email (per-month hours, no totals or end dates, monthly billing footer), and an
already-booked first session is the most visible thing in it. Every email that
existed before renders byte-for-byte as it did. Then #276. Prints GATE277."""
import hashlib
import os
import re
import subprocess
import sys
from datetime import date

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


# ── nothing that existed moves by a character (hashes taken before the patch) ──
BEFORE = {
    "studio_3mo": "c89507980d8622cefb6e002eec551a40924ed1fda3b977b48e47fc288e1518b9",
    "studio_trial_1mo": "161c409d875dc9577b1b737bd741cf0bed6d32d251fb5674ce0db6035e231b88",
    "studio_hour_oneoff": "a6bf5a25b459237c886596d378890eff626a5dc8bfd570a2f2f27b493e2cba96",
    "shawnie": "a4c7266335a72f67302ea702f40dd339f43a666265b35d51432c04951a4aaa20",
}
start = date(2026, 11, 6)
for pid, spec in sp.PACKAGES.items():
    term = sp.package_term(spec, start)
    h = hashlib.sha256(sp._welcome_email_html("Ana", "ABC123", spec, term).encode()).hexdigest()
    check(f"unchanged.{spec['kind']}", h == BEFORE[spec["kind"]], h)
spec, term = sp.custom_spec("MWM Partner Plan", 12, start, date(2027, 2, 5),
                            price_label="$350/week × 13 weeks", term_label="3 months",
                            interval="week", cycle_amount=350, cycles=13,
                            pace_note="4 hours a month", includes_note="X",
                            extra_notes=["Partner Program line"])
h = hashlib.sha256(sp._welcome_email_html("Shawnie", "ABC123", spec, term).encode()).hexdigest()
check("unchanged.shawnie", h == BEFORE["shawnie"], h)
check("unchanged.no_new_keys", not any(k in spec for k in ("ongoing", "first_session", "monthly_hours")))
check("pkg.untouched", len(sp.PACKAGES) == 3)

# ── David: ongoing AI Starter with his first shoot already booked ──
FS = {"title": "Your first film shoot is booked", "when": "Friday, November 13",
      "time": "12:30 – 2:30 PM", "place": "MWM Studios · 1500 Park Center Dr, Suite 230",
      "notes": ["Camila hosts this one.", "You're welcome to join <us>."]}
dspec, dterm = sp.custom_spec("AI Starter", 6, date(2026, 10, 16), date(2027, 1, 16),
                              price_label="$1,297/month", interval="month", cycle_amount=1297,
                              cycles=3, pace_note="1 on our real sets and 1 on the AI Wall",
                              includes_note="1 Full Immersion video every month",
                              ongoing=True, monthly_hours=2,
                              footer_note="The first 3 months are the minimum commitment.",
                              first_session=FS)
dh = sp._welcome_email_html("David", "ABC123", dspec, dterm)
check("ongoing.per_month", "2 hours of professional studio time every month" in dh)
check("ongoing.hours_li", "<li>2 studio hours every month (1 on our real sets and 1 on the AI Wall)</li>" in dh)
for bad in ("6 hours", "must be used within", "for 3 months", "total)", "January 16", "next 3"):
    check(f"ongoing.no[{bad}]", bad not in dh)
check("ongoing.includes_kept", "1 Full Immersion video every month" in dh)
check("ongoing.footer_monthly", "$1,297/month</strong>, charged automatically to the card on file on the 16th of each month" in dh)
check("ongoing.footer_note", "The first 3 months are the minimum commitment." in dh)
check("ongoing.footer_terms_link", "Studio Package Terms →" in dh)
check("fs.box_present", "Friday, November 13" in dh and "12:30 – 2:30 PM" in dh and "border:2px solid #C8A96E" in dh)
check("fs.box_before_portal", dh.index("Friday, November 13") < dh.index("1 · Your client portal"))
check("fs.escaped", "&lt;us&gt;" in dh and "<us>" not in dh)
check("fs.section2", "2 · Book your next sessions" in dh and "Book your first session" not in dh)
check("fs.code_kept", "ABC123" in dh and sp.PORTAL_URL in dh)
check("fs.needs_when", "first_session" not in sp.custom_spec("X", 2, date(2026, 1, 1), date(2026, 2, 1),
                                                             first_session={"when": " "})[0])
# a first session without ongoing keeps the old wording otherwise
s2, t2 = sp.custom_spec("X", 4, date(2026, 1, 1), date(2026, 4, 1), first_session=FS)
h2 = sp._welcome_email_html("A", "C", s2, t2)
check("fs.alone", "Friday, November 13" in h2 and "4 hours total across" in h2)
# ordinal suffixes in the footer
for d_, suf in ((1, "1st"), (2, "2nd"), (3, "3rd"), (11, "11th"), (12, "12th"), (13, "13th"), (21, "21st"), (22, "22nd"), (16, "16th")):
    s3, t3 = sp.custom_spec("Y", 2, date(2026, 10, d_), date(2027, 1, d_), interval="month",
                            cycle_amount=100, cycles=3, ongoing=True, monthly_hours=1)
    check(f"ordinal.{d_}", f"on the {suf} of each month" in sp.billing_footer_html(s3, t3))

# provision_custom passes the new fields through (dry; WP probe stubbed)
_orig = sp.provision_portal_client
sp.provision_portal_client = lambda *a, **k: {"status": 200, "existing": False, "raw": {}}
try:
    r = sp.provision_custom("David Rodriguez", "d@x.com", 6, "2026-10-16", "2027-01-16", label="AI Starter",
                            interval="month", cycle_amount=1297, cycles=3, ongoing=True, monthly_hours=2,
                            first_session=FS)
finally:
    sp.provision_portal_client = _orig
check("prov.dry", r.get("ok") and r.get("dry") and "every month" in r.get("welcome_html", ""))
check("prov.first_session_out", (r.get("first_session") or {}).get("when") == "Friday, November 13")

APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
blk = APP[APP.index("def admin_studio_provision_custom():"):APP.index("def admin_studio_provision_custom():") + 2600]
check("app.ongoing", 'ongoing=str(v.get("ongoing") or "") in ("1", "true", "yes")' in blk)
check("app.monthly", 'monthly_hours=v.get("monthly_hours") or 0' in blk and 'footer_note=v.get("footer") or ""' in blk)
check("app.fs", 'if (v.get("fs_when") or "").strip() else None' in blk and 'str(v.get("fs_note") or "").split("|")' in blk)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch276.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #276 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("276: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE277 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
