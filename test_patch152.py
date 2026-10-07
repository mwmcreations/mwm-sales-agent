"""PATCH #152 gate — no raw form value ever reaches a lead (ERIC, 7 Oct 2026).

Duncan Wardle (AD_15, studio-hour track) received: "owner_/_founder_/_partner
does not need a big program to start. You wrote: \"we can talk this\"." The
live form's keys, in order: full_name · email · phone_number ·
what_is_your_role_in_the_business? · company_name ·
what_is_your_business's_monthly_revenue? · your_website_or_instagram? ·
what_do_customers_need_to_understand_before_they_buy_from_you?. This gate
proves: the matcher places every slot correctly on THAT form (and on the
Sep form, and on a form where the name question comes first); a choice value
never lands in the business slot; a record built by the old matcher can be
repaired from its `extra`; every template prints a clean name or a clean
fallback; a short or unclear answer is not quoted back; Maya's contexts and
the room lines never carry a raw value; the repair route is wired. Prints
"N passed, M failed", then runs the #151 gate (which chains #150 → #148 → #143).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_form as lf      # noqa: E402
import studio_visit as sv   # noqa: E402
import sms_copy as sc       # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


RAW = ("owner_/_founder_/_partner", "marketing_lead", "under_$20k", "$20k_to_$50k",
       "employee", "freelancer_/_creator_/_artist")

# ── the live form, in its real order (Duncan's answers) ─────────────────────
DUNCAN = [{"name": "full_name", "values": ["Duncan Wardle"]},
          {"name": "email", "values": ["duncan@example.com"]},
          {"name": "phone_number", "values": [""]},
          {"name": "what_is_your_role_in_the_business?", "values": ["owner_/_founder_/_partner"]},
          {"name": "company_name", "values": ["iD8"]},
          {"name": "what_is_your_business's_monthly_revenue?", "values": ["under_$20k"]},
          {"name": "your_website_or_instagram?", "values": ["duncanwardle.com"]},
          {"name": "what_do_customers_need_to_understand_before_they_buy_from_you?", "values": ["we can talk this"]}]
f = lf.parse_field_data(DUNCAN)
r = lf.extract(f)
check("live.business", r["business"] == "iD8", r)
check("live.role", r["role_raw"] == "owner_/_founder_/_partner", r)
check("live.revenue", r["revenue_raw"] == "under_$20k", r)
check("live.website", r["website"] == "duncanwardle.com", r)
check("live.must", r["must_understand"] == "we can talk this", r)
check("live.nothing_unplaced", r["extra"] == {}, r["extra"])
check("live.verdict", lf.qualify(r["role_raw"], r["revenue_raw"])[0] == lf.Q_STUDIO_HOUR)

# the same form with Daphnee's answers (marketing lead, bon juice)
DAPH = [dict(x) for x in DUNCAN]
DAPH[0] = {"name": "full_name", "values": ["Daphnee Charles"]}
DAPH[3] = {"name": "what_is_your_role_in_the_business?", "values": ["marketing_lead"]}
DAPH[4] = {"name": "company_name", "values": ["bon juice"]}
DAPH[7] = {"name": "what_do_customers_need_to_understand_before_they_buy_from_you?", "values": ["the products"]}
r2 = lf.extract(lf.parse_field_data(DAPH))
check("live.daphnee", r2["business"] == "bon juice" and r2["role_raw"] == "marketing_lead" and r2["extra"] == {}, r2)

# the Sep form (snake keys) and a form where the name question comes FIRST
SEP = [{"name": "full_name", "values": ["Ana Souza"]}, {"name": "email", "values": ["a@b.co"]},
       {"name": "phone_number", "values": ["+14075551234"]}, {"name": "business_name", "values": ["Smile Dental"]},
       {"name": "website_or_instagram", "values": ["@smiledental"]}, {"name": "role", "values": ["Owner / Founder / Partner"]},
       {"name": "monthly_revenue", "values": ["$50–150K"]}, {"name": "what_customers_must_understand", "values": ["that implants are safe"]}]
r3 = lf.extract(lf.parse_field_data(SEP))
check("sep.form", r3["business"] == "Smile Dental" and r3["role_raw"].startswith("Owner") and r3["website"] == "@smiledental"
      and r3["revenue_raw"] == "$50–150K" and r3["extra"] == {}, r3)
FIRST = [{"name": "What's the name of your business?", "values": ["Enzo Auto"]},
         {"name": "What is your role in the business?", "values": ["marketing_lead"]},
         {"name": "What is your business's monthly revenue?", "values": ["$20k_to_$50k"]},
         {"name": "full_name", "values": ["Rodolfo"]}]
r4 = lf.extract(lf.parse_field_data(FIRST))
check("first.form", r4["business"] == "Enzo Auto" and r4["role_raw"] == "marketing_lead" and r4["revenue_raw"] == "$20k_to_$50k", r4)
# a form with NO name question: the role never fills the slot, the key stays in extra
NONAME = [x for x in DUNCAN if x["name"] != "company_name"]
r5 = lf.extract(lf.parse_field_data(NONAME))
check("noname.empty_business", r5["business"] == "" and r5["role_raw"] == "owner_/_founder_/_partner", r5)
# a choice value under a business-looking key is still refused and kept for the sheet
CHOICE = [{"name": "full_name", "values": ["X"]}, {"name": "business_type", "values": ["restaurant_/_cafe"]},
          {"name": "company_name", "values": ["marketing_lead"]}]
r6 = lf.extract(lf.parse_field_data(CHOICE))
check("choice.refused", r6["business"] == "" and r6["extra"].get("company_name") == "marketing_lead", r6)

# ── the shape test and the words ─────────────────────────────────────────────
for v in RAW:
    if "_" in v:
        check(f"choice.{v}", lf.looks_like_choice(v) is True)
check("choice.bare_role_word", lf.looks_like_choice("employee") is False and sv.clean_business("employee") == "")
for v in ("iD8", "bon juice", "Smile Dental", "Owner / Founder / Partner", "$50–150K", "my_shop Orlando", ""):
    check(f"not_choice.{v!r}", lf.looks_like_choice(v) is False)
check("pretty.role", lf.pretty("owner_/_founder_/_partner") == "owner / founder / partner")
check("pretty.rev", lf.pretty("under_$20k") == "under $20k" and lf.pretty("$20k_to_$50k") == "$20k to $50k")
check("pretty.passthrough", lf.pretty("Smile Dental") == "Smile Dental" and lf.pretty("") == "")
n = lf.notes_line({"role_raw": "owner_/_founder_/_partner", "revenue_raw": "under_$20k", "extra": {}}, False, "", lf.Q_STUDIO_HOUR, "r")
check("notes.words", "role: owner / founder / partner" in n and "revenue: under $20k" in n and "_/_" not in n, n)

# ── repairing a record the old matcher built ─────────────────────────────────
OLD = {"name": "Duncan Wardle", "business": "owner_/_founder_/_partner",
       "role_raw": "owner_/_founder_/_partner", "form_extra": {"company_name": "iD8"}}
check("recover.from_extra", lf.recover_business(OLD) == "iD8")
check("recover.keeps_good", lf.recover_business({"business": "Smile Dental", "form_extra": {"company_name": "x"}}) == "Smile Dental")
check("recover.nothing", lf.recover_business({"business": "marketing_lead", "form_extra": {}}) == "")
check("recover.no_choice", lf.recover_business({"business": "", "form_extra": {"company_name": "under_$20k"}}) == "")

# ── templates: clean name or clean fallback, never a raw value ────────────────
for v in RAW:
    check(f"clean.{v}", sv.clean_business(v) == "", sv.clean_business(v))
check("clean.names", sv.clean_business("iD8") == "iD8" and sv.clean_business("  bon   juice ") == "bon juice")
check("clean.role_word", sv.clean_business("Owner") == "" and sv.clean_business("N/A") == "")
check("clean.email_url", sv.clean_business("a@b.co") == "" and sv.clean_business("https://x.com") == "")
check("clean.too_long", sv.clean_business("x" * 61) == "" and sv.clean_business("x" * 60) == "x" * 60)

slots = [{"display": "Mon Oct 12, 10am"}, {"display": "Tue Oct 13, 11am"}]
for fn_ in (sv.sh_first_touch_email, sv.form_first_touch_email):
    for biz in RAW + ("", "iD8"):
        subj, html, text = fn_("Duncan Wardle", biz, "we can talk this", ai=False, slots=slots, sms_sent=False)
        check(f"{fn_.__name__}.no_raw {biz!r}", not any(x in text for x in RAW) and "_/_" not in text and "You wrote" not in text, text[:300])
        check(f"{fn_.__name__}.readable {biz!r}", ("iD8" in text) if biz == "iD8" else ("Your business" in text or "You do not need a big program" in text), text[:300])
    s_ok, _, t_ok = fn_("Ana", "Lima Dental", "Why building and owning a service business is one of the best opportunities right now", slots=slots)
    check(f"{fn_.__name__}.quotes_sentence", 'You wrote: "Why building and owning a service business' in t_ok, t_ok[:400])
for step in (1, 2, 3, 4, 5):
    for fn_ in (sv.chase_email, sv.sh_chase_email):
        s_, h_, t_ = fn_(step, "Duncan", "owner_/_founder_/_partner", "we can talk this", ai=False)
        check(f"{fn_.__name__}.{step}.no_raw", not any(x in (s_ + t_) for x in RAW) and "_/_" not in s_ + t_, s_ + " | " + t_[:200])
s3, _, _ = sv.sh_chase_email(3, "Duncan", "owner_/_founder_/_partner", "")
check("chase3.subject_fallback", s3 == "The three videos every business needs before the customer buys", s3)
s3b, _, _ = sv.sh_chase_email(3, "Duncan", "iD8", "")
check("chase3.subject_name", s3b == "The three videos every iD8 needs before the customer buys", s3b)
check("disq.text", "marketing_lead" not in sv.disqualify_text("Daphnee", "marketing_lead") and "sounds great" not in sv.disqualify_text("Daphnee", "marketing_lead"))
_, _, dt = sv.disqualify_email("Daphnee", "marketing_lead")
check("disq.email", "marketing_lead" not in dt and "_/_" not in dt)
check("industry.raw", sv.industry_word("owner_/_founder_/_partner") == "business")
_, _, pv = sv.post_visit_email(1, "Ana", "under_$20k", "")
check("post_visit.no_raw", "under_$20k" not in pv)

# ── the quote rule ───────────────────────────────────────────────────────────
for frag in ("we can talk this", "the products", "x", "", "five words is not enough", "owner_/_founder_/_partner",
             "https://example.com/what-we-do-for-you-now", "a@b.co and more words here ok"):
    check(f"quote.drop {frag[:24]!r}", sv.quotable(frag) == "", sv.quotable(frag))
check("quote.sentence", sv.quotable("that implants are safe and worth the price.") == "that implants are safe and worth the price.")
check("quote.long_no_punct", sv.quotable("Why building and owning a service business is one of the best opportunities right now").startswith("Why building"))
check("quote.seven_words_no_punct", sv.quotable("that implants are safe and worth it") == "")
long = " ".join(["word"] * 80) + "."
q = sv.quotable(long)
check("quote.capped", len(q) <= 244 and q.endswith("..."), q[-20:])
check("quote.min_words_const", sv.QUOTE_MIN_WORDS == 6)

# ── wiring (static) ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ctx = SRC[SRC.index("def _sms_lead_context(rec):"):SRC.index("def _sms_lead_context(rec):") + 2200]
check("wire.sms_context_business", 'bits.append(f"Business: {_sv.clean_business(rec.get(\'business\'))}")' in ctx, ctx[:600])
check("wire.sms_context_words", "_lf.pretty(rec['role_raw'])" in ctx and "_lf.pretty(rec['revenue_raw'])" in ctx)
check("wire.sms_context_quote_rule", "do not quote it back unless it" in ctx)
check("wire.room_lines", "{_sv.clean_business(rec['business']) or 'no business'}" in SRC and "{_lf.pretty(rec['role_raw']) or '?'}" in SRC)
check("wire.maya_line", "Business: {_sv.clean_business(rec['business']) or 'N/A'}" in SRC)
check("wire.sheet_context", 'if data.get("Business") and not _lf.looks_like_choice(data["Business"]):' in SRC)
check("wire.reengage_context", "if _re_biz and not _lf.looks_like_choice(_re_biz):" in SRC)
check("wire.repair_route", "@app.route('/admin/lead-form-repair', methods=['GET'])" in SRC and "_lf.recover_business(_r)" in SRC)
rep = SRC[SRC.index("def admin_lead_form_repair():"):SRC.index("@app.route('/admin/pg-lead'")]
check("wire.repair_secret", '_admin_secret_ok(request.args.get("secret"))' in rep)
check("wire.repair_report_only", 'str(request.args.get("apply") or "") in ("1", "true", "yes")' in rep and "if _row[\"needs_fix\"] and _apply:" in rep)
check("wire.repair_sheet", 'update_lead_columns(_k, {"Business": _new or ""})' in rep)
check("wire.repair_stop_manual", '_st["stopped"] = _chase.STOP_MANUAL' in rep and "stop_chase" in rep)
check("wire.repair_masks", rep.count("mask_contact(") >= 3)
check("wire.templates_clean", open(os.path.join(HERE, "studio_visit.py"), encoding="utf-8").read().count("biz = clean_business(business)") == 7)
check("wire.templates_quote", open(os.path.join(HERE, "studio_visit.py"), encoding="utf-8").read().count("mu = quotable(must_understand)") == 2)
check("wire.lead_form_doc", "PATCH #152" in open(os.path.join(HERE, "lead_form.py"), encoding="utf-8").read())

print(f"static+behaviour: {passed} passed, {failed} failed")

# the whole rail still passes (#151 gate chains #150 -> #148 -> #143)
r = subprocess.run([sys.executable, os.path.join(HERE, "test_patch151.py")], capture_output=True, text=True)
tail = (r.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r.stdout[-1500:]); print(r.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
