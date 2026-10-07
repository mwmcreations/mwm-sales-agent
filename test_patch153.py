"""PATCH #153 gate — the startup race, and rebuilding a form record from its row.

7 Oct 19:04 ET (the #152 deploy): "[Startup] Repopulated lead_data with 3
leads from Google Sheets" landed 22 s BEFORE "[PG] State restored — 348
leads". The sheet thread inserted slim rows (name, email, last-contact
date) under keys the table held full records for; the restore skipped those
keys as present; the next sweep wrote the slim rows over the table. Duncan
Wardle's form record went from 1.2 KB to 181 bytes. This gate proves: the
repopulation waits on the restore event and gives up (not proceeds) if it
never comes; the event is set even when the restore raises; a sheet row's
Notes line reads back into the record fields the rail wrote; the restore
route is wired, secret-gated, report-only without apply=1, never re-arms a
chain. Then it runs the #152 gate (which chains #151 → #150 → #148 → #143).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_form as lf   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

# ── the race ─────────────────────────────────────────────────────────────────
check("race.event_defined", "_PG_RESTORED = threading.Event()" in SRC
      and SRC.index("_PG_RESTORED = threading.Event()") > SRC.index("lead_data = _leads_db.LeadData()"))
rep = SRC[SRC.index("def _repopulate_lead_data_from_sheets():"):SRC.index("def _repopulate_lead_data_from_sheets():") + 1500]
check("race.repopulation_waits", "if not _PG_RESTORED.wait(timeout=300):" in rep, rep[:800])
check("race.gives_up_not_proceeds", "sheet repopulation " in rep and "return" in rep[rep.index("_PG_RESTORED.wait"):rep.index("_PG_RESTORED.wait") + 400])
check("race.wait_before_sheet_read", rep.index("_PG_RESTORED.wait") < rep.index("svc = get_sheets_service()"))
check("race.set_in_finally", "try:\n    _restore_state_from_pg()\nfinally:\n    _PG_RESTORED.set()" in SRC)
check("race.thread_starts_before_restore", SRC.index("threading.Thread(target=_repopulate_lead_data_from_sheets") < SRC.index("    _restore_state_from_pg()\nfinally:"),
      "the thread still starts at import — the wait is what orders it")

# ── reading a row back ──────────────────────────────────────────────────────
N_DUNCAN = ("role: owner_/_founder_/_partner · revenue: under_$20k · site/IG: duncanwardle.com · "
            "must understand: we can talk this · sms_consent: no · qualified: studio-hour "
            "(owner + under $20K/month: studio-hour track) · track: studio-hour · company_name: iD8")
n = lf.parse_notes_line(N_DUNCAN)
check("notes.role", n["role_raw"] == "owner_/_founder_/_partner")
check("notes.revenue", n["revenue_raw"] == "under_$20k")
check("notes.site", n["website"] == "duncanwardle.com")
check("notes.must", n["must_understand"] == "we can talk this")
check("notes.consent_no", n["sms_consent_form"] is False and n["sms_consent_ts"] == "")
check("notes.verdict", n["qualified"] == "studio-hour" and n["qualified_reason"] == "owner + under $20K/month: studio-hour track")
check("notes.track", n["track"] == "studio-hour")
check("notes.extra", n["extra"] == {"company_name": "iD8"})
N_DAPH = ("role: marketing_lead · revenue: under_$20k · site/IG: Call · must understand: the products · "
          "sms_consent: yes/lead_form 2026-10-03T17:10:37.439615-04:00 · qualified: no (revenue under $20K/month) · "
          "company_name: bon juice\n[Meeting 10/06] No-Show — Reschedule")
n2 = lf.parse_notes_line(N_DAPH)
check("notes.consent_yes", n2["sms_consent_form"] is True and n2["sms_consent_ts"] == "2026-10-03T17:10:37.439615-04:00")
check("notes.first_line_only", n2["qualified"] == "no" and "Meeting" not in str(n2))
check("notes.not_a_form_row", lf.parse_notes_line("Cancelled: Lead needs to cancel")["qualified"] == "")
check("notes.empty", lf.parse_notes_line("")["qualified"] == "" and lf.parse_notes_line(None)["extra"] == {})

r = lf.record_from_sheet_row({"Name": "Duncan Wardle", "Email": "D@icloud.com", "Business": "iD8",
                              "Ad ID": "120251304671220738", "Ad Campaign": "AD_15 | The room or the brain"}, N_DUNCAN)
check("row.fields", r["name"] == "Duncan Wardle" and r["email"] == "d@icloud.com" and r["business"] == "iD8"
      and r["website"] == "duncanwardle.com" and r["must_understand"] == "we can talk this", r)
check("row.flags", r["meta_lead_ad"] is True and r["source"] == "Meta Lead Ad" and r["channel"] == "Lead Form"
      and r["qualified"] == "studio-hour" and r["track"] == "studio-hour" and r["sms_consent_form"] is False)
check("row.ad", r["ad_id"] == "120251304671220738" and r["utm_campaign"].startswith("AD_15"))
check("row.extra_consumed", r["form_extra"] == {}, r["form_extra"])
r2 = lf.record_from_sheet_row({"Name": "Daphnee Charles", "Email": "x@y.z", "Business": "marketing_lead"}, N_DAPH)
check("row.business_from_extra", r2["business"] == "bon juice" and r2["form_extra"] == {}, r2)
check("row.no_choice_business", "marketing_lead" != r2["business"] and r2["role_raw"] == "marketing_lead")
check("row.disqualified_verdict", r2["qualified"] == "no" and r2["qualified_reason"] == "revenue under $20K/month" and "track" not in r2)
r3 = lf.record_from_sheet_row({"Name": "<test lead: dummy data for full_name>", "Business": "<test lead: dummy data for what_is_your_role_in_the_business?>"},
                              "role: x · revenue: y · sms_consent: no · qualified: no (revenue under $20K/month) · company_name: <test lead: dummy data for company_name>")
check("row.test_business_dropped", r3["business"] == "", r3)
check("row.not_form", lf.record_from_sheet_row({"Name": "x"}, "Cancelled: whatever") == {})

# ── the route ────────────────────────────────────────────────────────────────
check("wire.route", "@app.route('/admin/lead-form-restore', methods=['GET'])" in SRC)
rt = SRC[SRC.index("def admin_lead_form_restore():"):SRC.index("@app.route('/admin/pg-lead'")]
check("wire.secret", '_admin_secret_ok(request.args.get("secret"))' in rt)
check("wire.report_only", 'str(request.args.get("apply") or "") in ("1", "true", "yes")' in rt and 'if _entry["needs_restore"] and _apply:' in rt)
check("wire.uses_parser", "_lf.record_from_sheet_row(_cells, _notes)" in rt)
check("wire.only_flattened", 'bool(_cur and _cur.get("meta_lead_ad"))' in rt and '"needs_restore": _cur is not None and not _is_form' in rt)
check("wire.never_rearms", "STOP_MANUAL" in rt and "STOP_DISQUALIFIED" in rt and "_chase.arm(" not in rt)
check("wire.disqualify_under_budget", "_icp.mark_disqualified(_lr, _icp.REASON_NOT_TARGET_MARKET" in rt)
check("wire.keeps_live_name_email", 'if _lr.get("name"):\n                        _upd["name"] = _lr["name"]' in rt)
check("wire.masks", rt.count("mask_contact(") >= 1)
check("wire.no_record_untouched", "no record in memory at all — not touched" in rt)

print(f"static+behaviour: {passed} passed, {failed} failed")

r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch152.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
