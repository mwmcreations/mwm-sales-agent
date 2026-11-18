#!/usr/bin/env python3
"""GATE for PATCH #282 — the Desk report-in: package dropdown + meeting notes →
drafted recap / value / nudge in Michael's voice, stored on the record, shown
on the Desk, sent from info@ with his tap. Prints GATE282 PASS/FAIL."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import pitch_drafts as pd  # noqa: E402
import studio_package as sp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


# ── 1. which words mean which plan ──────────────────────────────────────────
check("kind.ai_pro", pd.kind_for("AI Pro") == "ai_pro" and pd.kind_for("ai pro, $2,497") == "ai_pro")
check("kind.ai_growth", pd.kind_for("AI Growth") == "ai_growth")
check("kind.ai_starter", pd.kind_for("AI Starter") == "ai_starter")
check("kind.real_sets", pd.kind_for("Real Sets") == "real_sets" and pd.kind_for("the real set plan") == "real_sets")
check("kind.roadmap_gold", pd.kind_for("ROADMAP Gold") == "roadmap_gold" and pd.kind_for("roadmap") == "roadmap_gold")
check("kind.roadmap_silver", pd.kind_for("ROADMAP Silver") == "roadmap_silver")
check("kind.roadmap_platinum", pd.kind_for("ROADMAP Platinum") == "roadmap_platinum" and pd.kind_for("platinum, two tracks") == "roadmap_platinum")
check("kind.studio_package_has_its_own_rail", pd.kind_for("Studio Package 3-month ($1,200)") == "")
check("kind.blank_other", pd.kind_for("") == "" and pd.kind_for(None) == "" and pd.kind_for("a custom thing") == "")
check("kind.key_passthrough", pd.kind_for("ai_pro") == "ai_pro")
check("kind.studio_kind_still_studio", sp.pitch_package_kind("Studio Package 3-month ($1,200)") == "studio_3mo")
check("kind.roadmap_is_other_for_280", sp.pitch_package_kind("ROADMAP Gold") == "other")   # #280 halts; #282 drafts
check("plans.facts", pd.PLANS["ai_pro"]["price"] == "$2,497/month" and pd.PLANS["ai_pro"]["regular"] == "$2,997"
      and pd.PLANS["ai_growth"]["price"] == "$1,697/month" and pd.PLANS["ai_starter"]["price"] == "$1,297/month"
      and pd.PLANS["real_sets"]["price"] == "$1,200/month" and pd.PLANS["roadmap_gold"]["price"] == "$2,497/month"
      and pd.PLANS["roadmap_silver"]["price"] == "$1,997/month" and pd.PLANS["roadmap_platinum"]["price"] == "")
check("plans.urls", all(p["url"].startswith("https://mwmcreations.com/") for p in pd.PLANS.values()))
check("name.first", pd.first_name("Dr. Scott Robinson") == "Scott" and pd.first_name("Ayodele Pompey") == "Ayodele" and pd.first_name("") == "there")

# ── 2. the drafts ───────────────────────────────────────────────────────────
NOTES = ("needs about a week for funds. wants stakeholder scenes on the AI wall; principals, teachers, parents. "
         "batch in December for January launch")
d = pd.draft("AI Pro", "Ayodele Pompey", "SmartTerm", NOTES, "he confirms after his deal signs; dates held until Nov 21")
check("draft.three_stages", set(d) == {"recap", "value", "nudge"})
r = d["recap"]
check("draft.recap_subject", r["subject"] == "Ayodele, the AI Pro plan we talked about, in writing", r["subject"])
check("draft.recap_greeting", r["lines"][0] == "Hi Ayodele,")
check("draft.recap_heard_from_notes", any(l.startswith("What I heard from you: You need about a week for funds. You want stakeholder scenes on the AI wall.") for l in r["lines"]), r["lines"])
check("you.pronouns", pd.second_person("he needs a week for funds and his ad manager runs the ads") == "you need a week for funds and your ad manager runs the ads")
check("you.she", pd.second_person("She wants stakeholder scenes; she has a deal pending") == "you want stakeholder scenes; you have a deal pending")
check("you.they", pd.second_person("they confirm after the board meets") == "you confirm after the board meets")
check("you.untouched", pd.second_person("Batch in December for January launch") == "Batch in December for January launch")
check("you.contraction", pd.second_person("he doesn't want ads") == "you don't want ads")
check("draft.recap_notes_kept", any("Batch in December for January launch." in l for l in r["lines"]))
check("draft.recap_plan_line", any(l.startswith("The plan we discussed, AI Pro: 4 AI Wall hours a month plus two Full Immersion videos. $2,497/month (regular $2,997).") for l in r["lines"]), r["lines"])
check("draft.recap_includes", sum(1 for l in r["lines"] if l.startswith("- ")) == 3)
check("draft.recap_terms", any("3-month minimum" in l and "November 30" in l for l in r["lines"]))
check("draft.recap_next_steps", any(l.startswith("Next steps as we agreed: You confirm after your deal signs") for l in r["lines"]), r["lines"])
check("draft.recap_link", any(pd.PLANS_URL in l for l in r["lines"]))
check("draft.recap_signed", r["lines"][-2] == "Michael" and "MWM Creations & Studios" in r["lines"][-1])
check("draft.recap_status", r["status"] == "draft" and r["stage"] == "recap")
check("draft.html_has_link", '<a href="https://mwmcreations.com/book-studio/#st-plans"' in r["html"] and "&bull;" in r["html"])
check("draft.html_escaped", "&amp;" in r["html"] and "<script" not in r["html"])
check("draft.text_matches_lines", r["text"] == "\n".join(r["lines"]))
v = d["value"]
check("draft.value_subject", v["subject"] == "What AI Pro does month after month")
check("draft.value_business", any("for SmartTerm" in l for l in v["lines"]))
n = d["nudge"]
check("draft.nudge_subject", n["subject"] == "Ayodele, still open: AI Pro")
check("draft.nudge_founding", any("founding price holds through November 30" in l for l in n["lines"]))
for stage, st in d.items():
    body = "\n".join(st["lines"]) + st["subject"]
    check(f"draft.{stage}_no_em_dash", "—" not in body and "–" not in body, body[:200])
    check(f"draft.{stage}_first_person", "Michael" in body and "Maya" not in body)

g = pd.draft("ROADMAP Gold", "Mike Martinez", "Zee's Roofing", "burned by agencies before; has an ad manager; drone and on-site footage", "")
check("roadmap.plan_line", any("ROADMAP Gold: 12 strategic campaigns a year, one produced every month. $2,497/month." in l for l in g["recap"]["lines"]), g["recap"]["lines"])
check("roadmap.terms", any("60 days' notice" in l for l in g["recap"]["lines"]))
check("roadmap.first_30", any("brainstorming interview" in l for l in g["recap"]["lines"]))
check("roadmap.links", any(pd.ROADMAP_URL in l and pd.ROADMAP_PLANS_URL in l for l in g["recap"]["lines"]))
check("roadmap.no_next_steps_line", not any(l.startswith("Next steps") for l in g["recap"]["lines"]))
check("roadmap.nudge_no_founding", not any("founding" in l for l in g["nudge"]["lines"]))
check("roadmap.apostrophe_business_escaped", "Zee&#x27;s" in g["value"]["html"] or "Zee's" in g["value"]["text"])
p = pd.draft("ROADMAP Platinum", "Ana Silva", "Clinic", "two tracks; we agreed on $4,297 a month", "")
check("platinum.price_from_notes", any("$4,297/month" in l for l in p["recap"]["lines"]), p["recap"]["lines"])
p2 = pd.draft("roadmap_platinum", "Ana Silva", "Clinic", "two tracks", "")
check("platinum.no_price_no_line", not any("/month" in l for l in p2["recap"]["lines"]) and any("Platinum numbers we discussed" in l for l in p2["recap"]["lines"]))
check("draft.empty_notes_ok", not any(l.startswith("What I heard") for l in pd.draft("ai_growth", "Lu", "", "", "")["recap"]["lines"]))
check("draft.unknown_kind_empty", pd.draft("Studio Package", "X", "", "", "") == {} and pd.draft("", "X") == {})
check("draft.long_business_dropped", not any(" for " + "B" * 60 in l for l in pd.draft("ai_pro", "Lu", "B" * 60, "", "")["value"]["lines"]))
check("summary.line", pd.summary_line(d) == "recap: draft · value: draft · nudge: draft" and pd.summary_line({}) == "no drafts")

# ── 3. app.py pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.import", "import pitch_drafts as _pd" in SRC)
blk = SRC[SRC.index("_studio.start_pitch_sequence(_p39_key, _p39_rec, service=service)   # PATCH #280"):]
blk = blk[:blk.index("if not _sp_found and not test_mode:")]
check("app.drafts_after_280", "_pd_kind = _pd.kind_for(service)" in blk and '_p39_rec["pitch_drafts"] = {' in blk
      and '"stages": _pd.draft(_pd_kind, name, business, notes, next_steps),' in blk)
check("app.drafts_persist", "lead_data[_p39_key] = _p39_rec" in blk)
check("app.drafts_tell_matt_nothing_sent", "DRAFTED" in blk and "nothing sent" in blk and "tap Send" in blk)
check("app.armed_message_kept_for_studio", "Follow-up sequence ARMED for" in blk and blk.index("else:") < blk.index("Follow-up sequence ARMED for"))
check("app.send_fn", "def _desk_pitch_send(key, rec, stage, text=None):" in SRC and 'via=f"pitch_draft_{stage}"' in SRC
      and 'if st.get("status") == "sent":' in SRC and "email_is_suppressed(email)[0]" in SRC[SRC.index("def _desk_pitch_send"):SRC.index("def _desk_actions():")])
check("app.send_marks_sent", 'st["status"] = "sent"' in SRC and 'st["sent_at"] = now.isoformat()' in SRC)
check("app.send_takes_edits", 'st["html"] = _pd.as_html(st["lines"])' in SRC and 'st["edited"] = True' in SRC
      and SRC.index('st["edited"] = True') < SRC.index('res = _email_send(email, st.get("subject", ""), st.get("html", ""), via=f"pitch_draft_{stage}"'))
check("app.send_tells_matt", "Michael sent the *{stage}* email to" in SRC)
check("app.actions_entry", '"pitch_send": _desk_pitch_send,' in SRC)
check("app.once", SRC.count("def _desk_pitch_send(") == 1 and SRC.count("_pd_kind = _pd.kind_for(service)") == 1)
check("app.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)

# ── 4. desk.py + desk.js pins ───────────────────────────────────────────────
DK = open(os.path.join(HERE, "desk.py"), encoding="utf-8").read()
check("desk.view_fn", "def pitch_drafts_view(rec):" in DK and 'v["pitch_drafts"] = pitch_drafts_view(rec)   # PATCH #282' in DK)
check("desk.route", '@app.route("/desk/api/lead/<path:key>/pitch-send", methods=["POST"])' in DK
      and 'if stage not in ("recap", "value", "nudge"):' in DK and 'fn = acts.get("pitch_send")' in DK and 'ok, msg = fn(k, rec, stage, body.get("text"))' in DK)
check("desk.route_auth_first", DK.index('def desk_api_pitch_send(key):') < DK.index('fn = acts.get("pitch_send")')
      and "bad = _need_auth()" in DK[DK.index("def desk_api_pitch_send(key):"):DK.index('fn = acts.get("pitch_send")')])
check("desk.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "desk.py")], capture_output=True).returncode == 0)
import desk  # noqa: E402
pv = desk.pitch_drafts_view({"pitch_drafts": {"kind": "ai_pro", "package": "AI Pro", "created_at": "2026-11-17T20:00:00",
                                              "stages": {"recap": {"subject": "S", "text": "T", "status": "draft"},
                                                         "nudge": {"subject": "N", "text": "X", "status": "sent", "sent_at": "2026-11-18T09:00:00"}}}})
check("desk.view_shape", pv and [s["stage"] for s in pv["stages"]] == ["recap", "nudge"] and pv["stages"][1]["status"] == "sent" and pv["kind"] == "ai_pro", pv)
check("desk.view_none", desk.pitch_drafts_view({}) is None and desk.pitch_drafts_view({"pitch_drafts": "x"}) is None)
JS = open(os.path.join(HERE, "desk_static", "desk.js"), encoding="utf-8").read()
check("js.select", '<select id="rep-service-pick">' in JS and "<option>AI Pro</option>" in JS and "<option>ROADMAP Gold</option>" in JS
      and "<option>Studio Package 3-month ($1,200)</option>" in JS and '<option value="__other">Other (type below)</option>' in JS)
check("js.service_value", 'service: (($("#rep-service-pick") || {}).value && $("#rep-service-pick").value !== "__other") ? $("#rep-service-pick").value : $("#rep-service").value.trim(),' in JS)
check("js.notes_placeholder", "These words go into the recap draft" in JS)
check("js.drafts_section", "<h3>Follow-up emails</h3>" in JS and 'data-act="pitch-view"' in JS and "+ facts + notes + drafts +" in JS)
check("js.sheet", "function pitchSheet(L, stage, withSend)" in JS and 'data-act="pitch-send"' in JS and "Send this email" in JS
      and '<textarea id="pitch-text" class="draft-text"' in JS)
check("js.dispatch", 'else if (act_ === "pitch-view") pitchSheet(L, a.dataset.stage, a.dataset.send === "1");' in JS
      and 'act(leadPath("pitch-send"), { stage: a.dataset.stage, text: tx }, "Sent from info@")' in JS)
check("js.send_needs_email", 'withSend && s.status !== "sent" && L.email' in JS)
CSS = open(os.path.join(HERE, "desk_static", "desk.css"), encoding="utf-8").read()
check("css.draft", ".draft-text{" in CSS and ".note.draft{" in CSS)
check("js.balanced_backticks", JS.count("`") % 2 == 0)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 282) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
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
print("GATE282 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
