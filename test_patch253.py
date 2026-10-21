"""PATCH #253 gate — ONE email per form lead (Michael, 18 Oct 10:38: "two
emails in less than two minutes — not okay"), and that one email is the
branded first touch with the real slots (Michael, 10:40: "combine both").

1. The generic welcome never fires on top of the form rail: the rail marks
   the address handled, the WhatsApp / Instagram "email captured" upgrades
   treat an address already on the record as not captured, and the sender
   itself refuses an address the rail owns or has already welcomed.
2. The first-touch emails (both tracks) carry the welcome's chrome, the slots
   as a box, the house footer; the plain text is unchanged.
Then runs the #252 gate (→ 251 → 250 → …)."""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_visit as sv         # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
SLOTS = [{"id": "2026-10-20T15:00:00-04:00", "display": "Tuesday, October 20 at 03:00 PM EST"},
         {"id": "2026-10-21T15:00:00-04:00", "display": "Wednesday, October 21 at 03:00 PM EST"}]

# ── 1 · the branded first touch ─────────────────────────────────────────────
for fn_ in (sv.sh_first_touch_email, sv.form_first_touch_email):
    subj, html, text = fn_("Michael Gagaoudakis", "Orlando Lifestyle Dentistry", "Product, People, Price",
                           ai=False, slots=SLOTS, sms_sent=True)
    n = fn_.__name__
    check(f"{n}.chrome", sv.BRAND_LOGO in html and "<!DOCTYPE html>" in html and html.count(sv.BRAND_DARK) >= 4)
    check(f"{n}.greeting_once", html.count("Hi Michael,") == 1)
    check(f"{n}.slots_box", "MICHAEL HAS THESE TIMES OPEN" in html.upper() and "Tue Oct 20, 3pm" in html and "Wed Oct 21, 3pm" in html
          and html.index("Tue Oct 20, 3pm") < html.index("Wed Oct 21, 3pm"))
    check(f"{n}.box_instruction", "Reply to this email with the one you want, or a better time, and I will book it." in html)
    check(f"{n}.slot_sentence_not_doubled", html.count("Tue Oct 20, 3pm") == 1)
    check(f"{n}.body_words", "Thanks for applying for the Studio Strategy Visit." in html and "30-minute" in html
          and sv.CREDITS in html and sv.WE_DO in html)
    check(f"{n}.sms_line", "I also sent you a text" in html and "Maya answers at" not in html)
    check(f"{n}.cta_and_footer", sv.MAYA_WA_LINK in html and "Text Maya on WhatsApp" in html
          and "1500 Park Center Dr, Suite 230" in html and "info@mwmcreations.com" in html
          and "Michael Moraes&#x27; team" in html or "Michael Moraes' team" in html)
    check(f"{n}.signoff", html.count(">Maya</p>") == 1
          and html.index(">Maya</p>") < html.index("Michael Moraes' team &middot; MWM Creations &amp; Studios"))
    check(f"{n}.no_welcome_words", "Thank you for reaching out" not in html and "A member of our team" not in html
          and "within 24 hours" not in html)
    check(f"{n}.text_unchanged_shape", text.startswith("Hi Michael,\n\n") and "Michael has Tue Oct 20, 3pm or Wed Oct 21, 3pm. Which works?" in text
          and text.rstrip().endswith("1500 Park Center Dr, Suite 230, Orlando, FL") and "<" not in text)
    check(f"{n}.subject", subj == "Michael, your Studio Strategy Visit with Michael Moraes")
    # no slots, no sms: the box asks for a day, the tail offers the number
    _, h2, t2 = fn_("Ana Souza", "Smile Dental", "", ai=False, slots=None, sms_sent=False)
    check(f"{n}.no_slots_box", "Reply to this email with a day that works this week and I will book it." in h2
          and "Tue Oct" not in h2 and f"Maya answers at {sv.MAYA_WA}" in h2)
    # escaping: a business name with markup cannot inject
    _, h3, _ = fn_("Ana", "Smile <b>Dental</b> & Co", "", ai=False, slots=SLOTS, sms_sent=True)
    check(f"{n}.escaped", "<b>Dental</b>" not in h3 and "&lt;b&gt;" in h3 and "&amp; Co" in h3)

h = sv.branded_email_html("Lia", ["One.", "", "Two."], slots=SLOTS, sms_sent=False, box_title="Pick one", signoff="Maya")
check("branded.paragraphs", h.count("<p style=\"margin:0 0 16px") == 2 and "PICK ONE" in h.upper())
check("branded.one_slot", sv.branded_email_html("Lia", ["x"], slots=SLOTS[:1]).count("<tr><td style=\"padding:8px 0") == 1)
check("branded.three_slots_capped", sv.branded_email_html("Lia", ["x"], slots=SLOTS + [{"id": "2026-10-22T15:00:00-04:00"}]).count("<tr><td style=\"padding:8px 0") == 2)
check("branded.no_name", "Hi there," in sv.branded_email_html("", ["x"]))

# ── 2 · the welcome guard, lifted out of app.py ─────────────────────────────
tree = ast.parse(SRC)
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_welcome_email_blocked"]
check("lift.guard", len(fns) == 1)
G = {"lead_data": {}}
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_253", "exec"), G)
blocked = G["_welcome_email_blocked"]
LEADS = {
    "whatsapp:+19548300030": {"email": "Mikedoesdentistry@gmail.com", "meta_lead_ad": True, "first_touch_email_at": "2026-10-18T10:30:28-04:00"},
    "instagram:1": {"email": "ig@example.com"},
    "whatsapp:+14075550001": {"email": "rail@example.com", "first_touch_email_at": "2026-10-18T09:00:00-04:00"},
    "junk": "x",
}
pg = {"welcome_email_at:old@example.com": "2026-10-01T10:00:00-04:00"}
check("guard.form_lead", blocked("mikedoesdentistry@gmail.com", LEADS, pg.get) == (True, "form rail owns the first touch"))
check("guard.rail_first_touch", blocked("RAIL@example.com", LEADS, pg.get)[0] is True)
check("guard.already_welcomed", blocked("old@example.com", LEADS, pg.get) == (True, "welcome already sent"))
check("guard.fresh_address", blocked("ig@example.com", LEADS, pg.get) == (False, ""))
check("guard.unknown_address", blocked("new@example.com", LEADS, pg.get) == (False, ""))
check("guard.empty", blocked("", LEADS, pg.get)[0] is True)
check("guard.pg_error_opens", blocked("new@example.com", LEADS, lambda k, d=None: (_ for _ in ()).throw(RuntimeError("pg"))) == (False, ""))

# ── 3 · wiring ──────────────────────────────────────────────────────────────
check("wire.rail_marks_email", "        if email:\n            upd[\"_email_notified\"] = True" in SRC
      and SRC.index("upd[\"_email_notified\"] = True") < SRC.index("_capi_stage(sender_key, lr, _capi.STAGE_LEAD"))
check("wire.wa_capture_checks_record", "_email_on_record = str(lead_data[sndr].get(\"email\") or \"\").strip()" in SRC
      and SRC.count("or bool(_email_on_record)") == 2
      and SRC.count("_TALLY.bump(\"welcome_email.skipped_known_address\"") == 2)
check("wire.wa_capture_order", SRC.index("_email_on_record = str(lead_data[sndr].get(\"email\") or \"\").strip()\n                            lead_data[sndr].update(")
      < SRC.index("_had_email_before = bool(lead_data[sndr].get(\"_email_notified\")) or bool(_email_on_record)"))
check("wire.ig_capture_order", SRC.index("_email_on_record = str(lead_data[sndr].get(\"email\") or \"\").strip()   # PATCH #253")
      < SRC.index("_had_email_before = bool(lead_data[sndr].get(\"_email_notified\")) or bool(_email_on_record) \\\n                            or bool(lead_data[sndr].get(\"meta_lead_ad\"))   # PATCH #253"))
check("wire.sender_guard", "_blocked, _why = _welcome_email_blocked(to_email)" in SRC
      and SRC.index("def _welcome_email_blocked(") < SRC.index("def _send_welcome_email_async(")
      and SRC.index("_blocked, _why = _welcome_email_blocked(to_email)") < SRC.index("html = _build_welcome_email_html(lead_name)"))
check("wire.154_guard_kept", "_is_form_lead = bool(_ld.get(\"meta_lead_ad\") or _ld.get(\"linked_form_key\"))" in SRC   # widened by #256
      and "if _has_email and not _is_form_lead:" in SRC)
check("wire.rail_still_sends_first_touch", "_ft_email = _sv.sh_first_touch_email if sh else _sv.form_first_touch_email" in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch252.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #252 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("252: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE253 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
