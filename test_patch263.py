"""PATCH #263 gate — agents talk to each other; the app runs the rounds.
(Mon 2 Nov 2026, #dev tests #1/#2: scheduled-task workers took 3–6 min a
round on the biggest model, one forgot to ring its partner, one ran without
the Mac and so without memory, and Michael's "not yet" by text landed in
Maya's command mode.)

1. agent_talk (pure): kickoff and reply parsing, turn order, the app owning
   the hand-over, model mix (Haiku routine / Sonnet money), cost at today's
   prices, prompt contract (memory line numbers, ending lines, word limit),
   memory requests + verification, spend and cap, scorecard.
2. Decisions: two-segment SMS, numbered; Michael's text answers (yes / no /
   not yet / D2 / free text to a question) matched before command mode;
   receipts; re-text schedule; expiry.
3. app.py wiring: the Slack-events hook in agent channels, the SMS hook
   before _oc.is_confirmation, the loop thread + stale override, the admin
   routes, /health, operator_alert "decision" kind (Michael only).
4. agent_memory_bridge: file-name allow-list, head/match/tail excerpt with
   real line numbers, never another file.
Then runs the #262 gate (→ 261 → …)."""
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agent_talk as at          # noqa: E402
import operator_alert as oa      # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
KICK = ("📋 JOINT ASSIGNMENT — Owners: ROB + DEV — *Masterclass USA (Giselle Gartzke) [test]*\n"
        "• ROB: payment history on the $6,000 package, the failed Nov 1 charge.\n"
        "• DEV: the Mux 1080p live-input rate, venue upload, 720p fallback.\n"
        "_(max 3 rounds each)_ — DEV\n*Sent using* Claude [Michael <michael@mwmcreations.com>]")
R_ROB = ('ROB.md line 17327: "Paid $6,000 = Stripe 5×$1,000 … PAID IN FULL."\n\nRound 1 — ROB.\n(a) Yes: cancel …\n'
         "— ROB (round 1)\n→ DEV, your turn")
R_DEV_AGREED = ('DEV.md line 11374: "MASTERCLASS USA … PREVIEW LIVE"\n\nMux 1080p $0.03125/min …\n— DEV (round 1)\n'
                "AGREED — for Michael:\n• Cancel the sub and void 0006 before Nov 4; then one $1,500 invoice.\n"
                "• 1080p inside the $1,500.\n• Margin $1,446 @50 · $2,472 @300.")

# ── 1 · kickoff + replies + turns ───────────────────────────────────────────
p = at.parse_assignment(KICK)
check("kick.owners_author_last", p and p["owners"] == ["ROB", "DEV"] and p["author"] == "DEV", p)
check("kick.test_and_rounds", p and p["test"] is True and p["max_rounds"] == 3, p)
check("kick.single_owner", at.parse_assignment("ASSIGNMENT — Owner: LARA — put Shawnie on the calendar") == {"owners": ["LARA"], "author": "", "test": False, "max_rounds": 4})
check("kick.not_an_assignment", at.parse_assignment("DONE #262 is live — DEV") is None and at.parse_assignment("Owners: ROB + DEV, status?") is None)
check("kick.unknown_owner_ignored", at.parse_assignment("ASSIGNMENT Owners: BOB + ROB")["owners"] == ["ROB"])
check("kick.no_known_owner", at.parse_assignment("ASSIGNMENT Owners: BOB") is None)
check("strip.tail_and_links", at.strip_tail("see <https://x.y/z|the site> now\n*Sent using* Claude") == "see the site (https://x.y/z) now")

r = at.parse_reply(R_ROB)
check("reply.rob_turn", r["agent"] == "ROB" and r["round"] == 1 and r["end"] == "turn" and r["next"] == "DEV", r)
check("reply.memory_cites", r["memory"] == [("ROB", 17327)], r)
r2 = at.parse_reply(R_DEV_AGREED)
check("reply.dev_agreed", r2["agent"] == "DEV" and r2["end"] == "agreed" and r2["memory"] == [("DEV", 11374)], r2)
check("reply.needs", at.parse_reply("… — ROB (round 2)\n⏸ NEEDS MICHAEL: pay plan or not?")["end"] == "needs")
check("reply.done", at.parse_reply("… — LARA (round 1)\n✅ DONE — for Michael: event created")["end"] == "done")
check("reply.worker_signature_too", at.parse_reply("x\n— ROB (worker, round 2)\n→ DEV, your turn")["round"] == 2)
check("reply.no_ending", at.parse_reply("just words — DEV (round 1)")["end"] is None)
check("section.agreed", at.section_after(R_DEV_AGREED, "agreed").startswith("Cancel the sub and void 0006")
      and "Margin $1,446" in at.section_after(R_DEV_AGREED, "agreed"))

conv = at.new_conversation("C0AR7NY6SHF", "1793655072.227919", KICK, p, now=1000.0)
check("conv.first_speaker_not_author", conv["turn"] == "ROB" and conv["status"] == "open" and conv["id"] == "C0AR7NY6SHF:1793655072.227919")
check("conv.key", at.key("C", "1.2") == "agent_talk:C:1.2")
st = at.apply_reply(conv, "ROB", at.parse_reply(R_ROB), now=1010.0)
check("turn.handover_to_dev", st == "open" and conv["turn"] == "DEV" and conv["rounds"] == {"ROB": 1, "DEV": 0})
bad = at.parse_reply("… — DEV (round 1)\n→ ROB, your turn")   # DEV handing to ROB is fine; but a reply naming ITSELF:
c2 = at.new_conversation("C", "1", KICK, p)
at.apply_reply(c2, "ROB", {"end": "turn", "next": "ROB", "memory": []})
check("turn.app_owns_handover_self", c2["turn"] == "DEV", c2["turn"])
c3 = at.new_conversation("C", "1", KICK, p)
at.apply_reply(c3, "ROB", {"end": None, "next": "", "memory": []})
check("turn.app_owns_handover_missing", c3["turn"] == "DEV")
c4 = at.new_conversation("C", "1", KICK, dict(p, max_rounds=1))
at.apply_reply(c4, "ROB", {"end": "turn", "next": "DEV", "memory": []})
check("turn.rounds_available_for_partner", c4["turn"] == "DEV" and c4["status"] == "open")
at.apply_reply(c4, "DEV", {"end": "turn", "next": "ROB", "memory": []})
check("turn.limit_closes_as_rounds", c4["status"] == "closed" and c4["close_reason"] == "rounds")
st2 = at.apply_reply(conv, "DEV", r2, now=1020.0)
check("turn.agreed_closes", st2 == "closed" and conv["close_reason"] == "agreed" and conv["turn"] == "")
c5 = at.new_conversation("C", "1", "ASSIGNMENT Owner: LARA — check the calendar", at.parse_assignment("ASSIGNMENT Owner: LARA — check the calendar"))
at.apply_reply(c5, "LARA", {"end": None, "next": "", "memory": []})
check("turn.single_owner_closes_done", c5["status"] == "closed" and c5["close_reason"] == "done")
check("turn.next_speaker_round_robin", at.next_speaker({"owners": ["A", "B", "C"]}, "C") == "A")

# ── model mix + cost ────────────────────────────────────────────────────────
check("model.rob_is_sonnet", at.model_for("ROB", "status?", "") == "sonnet")
check("model.dev_routine_is_haiku", at.model_for("DEV", "[test] memory ping: cite one line of your file", "") == "haiku")
check("model.dev_money_is_sonnet", at.model_for("DEV", KICK, "") == "sonnet")
check("model.partner_money_is_sonnet", at.model_for("DEV", "status?", "what is the price per seat") == "sonnet")
check("model.closing_is_sonnet", at.model_for("LARA", "status?", "", closing=True) == "sonnet")
check("cost.sonnet_round", abs(at.cost_usd("sonnet", 8100, 500) - 0.0212) < 1e-6)
check("cost.haiku_round", abs(at.cost_usd("haiku", 8100, 500) - 0.00106) < 1e-6)
check("cost.prices_match_pricing_page", at.PRICES["haiku"] == {"in": 0.10, "out": 0.50} and at.PRICES["sonnet"] == {"in": 2.00, "out": 10.00})
check("cost.default_models", at.MODEL_IDS_DEFAULT == {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"})
sp = at.spend_add({}, 0.0212, "sonnet")
sp = at.spend_add(sp, 0.00106, "haiku")
check("spend.adds", sp["rounds"] == 2 and abs(sp["usd"] - 0.02226) < 1e-6 and sp["by_tier"] == {"sonnet": 1, "haiku": 1})
check("spend.cap", at.capped({"usd": 3.0}, 3.0) and not at.capped({"usd": 2.99}, 3.0) and not at.capped({}, 3.0))
check("spend.key", at.spend_key("2026-11-02") == "agent_talk_spend:2026-11-02")

# ── prompt contract ─────────────────────────────────────────────────────────
thread = [{"who": "DEV (session)", "text": KICK}, {"who": "ROB", "text": R_ROB}]
system, msgs = at.build_prompt(conv, "DEV", thread, "11374: MASTERCLASS USA … PREVIEW LIVE\n11375: next line", 1)
check("prompt.identity_lane", "You are DEV" in system and at.AGENTS["DEV"]["lane"] in system)
check("prompt.rules", "never message clients or crew" in system and "final decision" in system and "credentials" in system)
check("prompt.memory_line_rule", 'quoted as "DEV.md line N: ..."' in system and "11374: MASTERCLASS" in system)
check("prompt.endings", at.TURN_LINE.format(name="ROB") in system and at.AGREED_LINE in system and at.NEEDS_LINE in system)
check("prompt.word_limit_and_signature", f"at most {at.REPLY_WORDS_MAX} words" in system and '"— DEV (round 1)"' in system)
check("prompt.thread_in_user_turn", len(msgs) == 1 and msgs[0]["role"] == "user" and "[KICKOFF · DEV (session)]" in msgs[0]["content"]
      and "[REPLY · ROB]" in msgs[0]["content"] and "write your round 1 reply now" in msgs[0]["content"])
check("prompt.tail_stripped", "Sent using" not in msgs[0]["content"])
sys_last, _ = at.build_prompt(dict(conv, max_rounds=1), "DEV", thread, "", 1, memory_note="bridge down")
check("prompt.last_round_must_close", "LAST allowed round" in sys_last)
check("prompt.no_memory_is_said", "not available for this round (bridge down)" in sys_last and "unavailable this round" in sys_last)
sys_single, _ = at.build_prompt(c5, "LARA", [{"who": "Michael", "text": "ASSIGNMENT Owner: LARA — check"}], "", 1)
check("prompt.single_owner_done_line", at.DONE_LINE in sys_single and "your turn" not in sys_single)

body, end, nxt = at.enforce_ending("facts facts", "DEV", 1, ["ROB"], False)
check("enforce.adds_signature_and_turn", body.endswith("— DEV (round 1)\n→ ROB, your turn") and end == "turn" and nxt == "ROB")
body, end, nxt = at.enforce_ending("facts", "DEV", 3, ["ROB"], True)
check("enforce.last_round_needs", end == "needs" and at.NEEDS_LINE in body)
body, end, nxt = at.enforce_ending(R_DEV_AGREED, "DEV", 1, ["ROB"], False)
check("enforce.keeps_agreed", end == "agreed" and body == at.strip_tail(R_DEV_AGREED))
check("header", at.reply_header("ROB", 2) == "*ROB* · round 2")

# ── memory ──────────────────────────────────────────────────────────────────
kw = at.keywords(KICK)
check("memory.keywords_names_first", kw[:2] == ["masterclass", "giselle"] and "owners" not in kw and "assignment" not in kw, kw)
req = at.memory_request(conv, "ROB", now=5.0)
check("memory.request_shape", req["agent"] == "ROB" and req["file"] == "ROB.md" and req["head"] == 30 and req["tail"] == 20
      and req["match_lines"] == 30 and req["served"] is None and len(req["id"]) == 12)
lines = at.excerpt_lines("17327: Paid $6,000\n17419: FAILED Nov 1\nnot a line")
check("memory.excerpt_lines", lines == {17327: "Paid $6,000", 17419: "FAILED Nov 1"})
check("memory.verified", at.memory_verified(at.parse_reply(R_ROB), "ROB", lines) == (True, True))
check("memory.quoted_not_served", at.memory_verified(at.parse_reply(R_ROB), "ROB", {1: "x"}) == (True, False))
check("memory.partner_file_does_not_count", at.memory_verified(at.parse_reply(R_ROB), "DEV", lines) == (False, False))
tm = at.thread_messages([{"text": KICK, "user": "U1"}, {"text": "🤝 conversation open", "bot_id": "B"},
                         {"text": "*ROB* · round 1\n" + R_ROB, "bot_id": "B"}, {"text": "fine by me", "user": "U1"}])
check("thread.labels", [m["who"] for m in tm] == ["DEV (session)", "ROB", "Michael"], [m["who"] for m in tm])

# ── scorecard ───────────────────────────────────────────────────────────────
conv["log"] = [{"tier": "sonnet", "mem_quoted": True, "mem_verified": True}, {"tier": "haiku", "mem_quoted": True, "mem_verified": False}]
conv["usd"] = 0.0223
f = at.footer(conv)
check("footer", f.startswith("⏱ 2 rounds · 0m 20s · $0.022 (1 Haiku, 1 Sonnet) · memory quoted 2/2, verified 1/2 · AGREED"), f)

# ── 2 · decisions ───────────────────────────────────────────────────────────
agreed = at.section_after(R_DEV_AGREED, "agreed")
d1 = at.new_decision(1, conv, agreed, now=100.0)
check("decision.sms_two_segments", len(d1["sms"]) <= at.DECISION_SMS_MAX and d1["sms"].startswith("MWM decision 1: Cancel the sub")
      and d1["sms"].endswith("Reply YES 1, NO 1 or LATER 1."), d1["sms"])
long = at.decision_text(7, "word " * 200)
check("decision.sms_cut_at_word", len(long) <= at.DECISION_SMS_MAX and "…" in long and long.endswith("Reply YES 7, NO 7 or LATER 7."))
check("decision.row", d1["status"] == "open" and d1["next_text"] == 100.0 + 24 * 3600 and d1["owners"] == ["ROB", "DEV"] and d1["kind"] == "agreed")
dq = at.new_decision(2, conv, "Pay plan for Giselle or not?", kind="needs", now=100.0)
check("decision.question_sms", dq["sms"] == "MWM question 2 (agents need you): Pay plan for Giselle or not? Reply starting with D2.")

check("owner.not_yet_is_later", at.owner_reply("1) not yet 2) not yet", [d1])[1] == "later")
check("owner.yes", at.owner_reply("YES", [d1])[1] == "yes" and at.owner_reply("yes 1", [d1])[0]["id"] == 1)
check("owner.no", at.owner_reply("No.", [d1])[1] == "no" and at.owner_reply("não", [d1])[1] == "no")
check("owner.portuguese_yes", at.owner_reply("sim, pode", [d1])[1] == "yes")
check("owner.mixed_is_refused", at.owner_reply("yes and no", [d1]) == (None, "mixed"))
check("owner.no_verdict_falls_through", at.owner_reply("what time is the shoot?", [d1]) == (None, "no_verdict"))
check("owner.none_open", at.owner_reply("yes", []) == (None, "none_open"))
check("owner.several_need_a_number", at.owner_reply("yes", [d1, dq]) == (None, "which"))
check("owner.number_picks", at.owner_reply("D1 yes", [d1, dq])[0]["id"] == 1 and at.owner_reply("later 1", [d1, dq])[1] == "later")
check("owner.question_gets_a_note", at.owner_reply("D2 yes, offer 750 + 750", [d1, dq])[1] == "note"
      and at.owner_reply("D2: no plan, full amount", [d1, dq])[1] == "note")
check("owner.unknown_number", at.owner_reply("yes 9", [d1, dq])[1] == "unknown_number")
check("owner.which_receipt", at.which_receipt([d1, dq]) == "Which decision? Open: D1, D2. Reply like 'YES D1'.")
check("owner.amount_is_not_a_number", at.owner_reply("yes, $1,500 is fine", [d1, dq]) == (None, "which"))
at.apply_answer(d1, "later", "not yet", now=200.0)
check("answer.later_parks", d1["status"] == "later" and d1["next_text"] == 200.0 + 24 * 3600 and d1["answer_text"] == "not yet")
check("receipt.later", "parked" in at.owner_receipt(d1, "later") and "24 hours" in at.owner_receipt(d1, "later"))
d3 = at.new_decision(3, conv, "x", now=100.0)
at.apply_answer(d3, "yes", "yes 3", now=150.0)
check("answer.yes_closes", d3["status"] == "yes" and d3["next_text"] is None and "YES recorded" in at.owner_receipt(d3, "yes"))
at.apply_answer(dq, "note", "D2 no plan", now=150.0)
check("answer.note", dq["status"] == "answered")
# re-texts: open at 24h and 72h, then expiry; parked every 24h
d4 = at.new_decision(4, conv, "y", now=0.0)
d4["texted"] = [{"at": 0.0}]
check("retext.not_yet_due", at.retext_due(d4, now=23 * 3600) == "")
t1 = at.retext_due(d4, now=25 * 3600)
check("retext.24h", t1.startswith("Reminder (25h, no answer yet) — MWM decision 4:") and d4["next_text"] == 72 * 3600, (t1, d4["next_text"]))
d4["texted"].append({"at": 25 * 3600})
check("retext.quiet_until_72h", at.retext_due(d4, now=50 * 3600) == "")
t2 = at.retext_due(d4, now=73 * 3600)
d4["texted"].append({"at": 73 * 3600})
check("retext.72h", t2.startswith("Reminder (73h") and d4["status"] == "open")
t3 = at.retext_due(d4, now=74 * 3600)
check("retext.expires_after_last", t3 == "" and d4["status"] == "expired" and d4["next_text"] is None, (t3, d4["status"]))
d5 = at.new_decision(5, conv, "z", now=0.0)
at.apply_answer(d5, "later", "later", now=0.0)
check("retext.parked_24h", at.retext_due(d5, now=23 * 3600) == "" and at.retext_due(d5, now=25 * 3600).startswith("MWM decision 5 is still parked:")
      and d5["next_text"] == 25 * 3600 + 24 * 3600)

# ── 3 · app wiring ──────────────────────────────────────────────────────────
check("app.imports_module", "\nimport agent_talk as _at\n" in SRC)
ev = SRC[SRC.index('        elif channel_id in AGENT_CHANNELS and text.strip():'):SRC.index('        elif channel_id in AGENT_CHANNELS and text.strip():') + 900]
check("app.events_hook_before_old_path", '_agent_talk_maybe_start(channel_id, text, user_id, event.get("ts", ""), thread_ts)' in ev
      and ev.index("_agent_talk_maybe_start") < ev.index("_handle_slack_agent_message"))
sms = SRC[SRC.index("def _handle_michael_sms(frm, body):"):SRC.index("def _handle_incoming_sms(frm, body):")]
check("app.sms_hook_before_command_mode", '_at_hook = globals().get("_agent_talk_owner_text")' in sms and "if _at_hook and _at_hook(frm, text):" in sms
      and sms.index("_agent_talk_owner_text") < sms.index("_oc.is_confirmation(text)") < sms.index("get_command_reply(snap)"))
check("app.loop_thread", 'threading.Thread(target=_agent_talk_loop, daemon=True, name="agent_talk").start()' in SRC
      and '_THREAD_STALE_OVERRIDES["agent_talk"] = 5' in SRC)
for route in ("/admin/agent-talk", "/admin/agent-talk/start", "/admin/agent-talk/memory-requests",
              "/admin/agent-talk/memory", "/admin/agent-talk/decide", "/admin/agent-talk/mode"):
    check(f"app.route {route}", f"@app.route('{route}'" in SRC)
blk = SRC[SRC.index("def _agent_talk_maybe_start("):SRC.index("# S7 — STUDIO PACKAGE AUTOMATION WIRING")]
check("app.routes_fail_closed", blk.count("_admin_secret_ok(") >= 6)
check("app.mode_gate", 'if mode == "off":' in blk and 'if mode == "test" and not parsed.get("test") and via != "admin":' in blk)
check("app.cap_checked_before_round", "if _at.capped(spend, AGENT_TALK_CAP_USD):" in blk and '_agent_talk_close(conv, "capped")' in blk)
check("app.one_call_helper", blk.count("resp = _agent_talk_call(model, system, messages, tier)") == 1
      and "def _agent_talk_call(model, system, messages, tier):" in blk and 'fallback = MODEL_FAST if tier == "haiku" else MODEL_MAIN' in blk)
check("app.thinking_minimum_per_model", 'AGENT_TALK_THINKING = {"haiku": {"type": "disabled"}, "sonnet": {"type": "between_tools"}}' in SRC
      and 'client.messages.create(extra_body=steer, **kw)' in blk and '"output_config": {"effort": AGENT_TALK_EFFORT.get(tier, "low")}' in blk
      and 'if "thinking" in msg or "effort" in msg or "output_config" in msg:' in blk and 'os.getenv("AGENT_TALK_MAX_TOKENS", "1500")' in SRC
      and '"think": think_tok' in blk)
check("app.text_blocks_only_and_empty_is_failure", 'if getattr(b, "type", "") == "text")' in blk
      and 'raise RuntimeError(f"empty reply (stop={stop}, blocks={kinds}, out={out_tok})")' in blk and '"stop": stop, "blocks": kinds' in blk)
check("app.model_from_tier", "model = AGENT_TALK_MODELS[tier]" in blk and 'tier = _at.model_for(agent, conv.get("kickoff", ""), partner_text, closing=closing)' in blk)
check("app.meters_tokens", '"in": in_tok,' in blk and '"out": out_tok, "think": think_tok, "usd": usd, "secs": secs' in blk and "_at.spend_add(_at_spend_today(), usd, tier)" in blk)
check("app.memory_verified_logged", '"mem_quoted": mem_quoted' in blk and '"mem_verified": mem_verified' in blk)
check("app.app_hands_over", "status = _at.apply_reply(conv, agent, parsed)" in blk and "_at.enforce_ending(text, agent, round_n, partners, closing)" in blk)
check("app.decision_texted_michael_only", '_operator_alert.alert("decision", row["sms"])' in blk and oa.KINDS.get("decision") == {"eric": False})
check("app.done_is_not_a_decision", 'if reason in ("agreed", "needs", "rounds"):' in blk and 'elif reason == "done":' in blk)
check("app.owners_channels_told", "for o in conv[\"owners\"]:" in blk and "_at.AGENTS.get(o, {}).get(\"channel\")" in blk)
check("app.memory_stall_escalates", "_at.MEMORY_WAIT_STALL_S" in blk and "memory bridge is not answering" in blk and "this round runs without it" in blk)
check("app.memory_retry_nudge", "_at.MEMORY_WAIT_RETRY_S" in blk)
check("app.retexts_in_loop", "txt = _at.retext_due(d, now)" in blk and "expired unanswered after 72 h" in blk)
check("app.cap_alert_once_a_day", "_at_cap_alerted" in blk and "def _at_cap_alert_once" in blk)
check("app.health", '"agent_talk": _agent_talk_status(),' in SRC)
check("app.bridge_seen", '_at_save(_AT_BRIDGE, {"last_seen": time.time()' in blk)
check("app.excerpt_capped", "if len(lines) > 60000:" in blk)
check("app.default_mode_test", 'os.getenv("AGENT_TALK_MODE", "test")' in SRC)
check("app.default_cap_3", "DAILY_CAP_DEFAULT_USD = 3.00" in open(os.path.join(HERE, "agent_talk.py"), encoding="utf-8").read())
check("app.no_username_impersonation", '"username"' not in blk and "icon_emoji" not in blk)
check("oa.reply_unchanged", oa.KINDS.get("reply") == {"eric": True})

# ── 4 · the Mac bridge ──────────────────────────────────────────────────────
BR = open(os.path.join(HERE, "agent_memory_bridge.py"), encoding="utf-8").read()
check("bridge.setsid_first", BR.index("os.setsid()") < BR.index("import json"))
check("bridge.lock_and_linger", "agent_bridge.lock" in BR and "LINGER" in BR and "time.time() - started < LINGER" in BR)
_doc_end = BR.index('"""', BR.index('"""') + 3)
check("bridge.secret_from_env_only", 'os.environ.get("AT_SECRET", "")' in BR and ".mwm_upload_secret" not in BR[_doc_end:])
check("bridge.routes", "/admin/agent-talk/memory-requests" in BR and "/admin/agent-talk/memory" in BR)
ns = {}
src_fn = BR[BR.index("def excerpt_for(req):"):BR.index("def main():")]
exec("import os, re\nLINE_MAX = 400\nALLOWED_FILE = re.compile(r'^[A-Z]{2,8}\\.md$')\n" + src_fn, ns)
with tempfile.TemporaryDirectory() as td:
    ns["MEMORY_DIR"] = td
    with open(os.path.join(td, "ROB.md"), "w", encoding="utf-8") as f:
        for i in range(1, 101):
            f.write(f"line {i} " + ("giselle paid" if i in (40, 55, 70) else "nothing") + ("x" * 500 if i == 55 else "") + "\n")
    res = ns["excerpt_for"]({"file": "ROB.md", "keywords": ["giselle", "zzz"], "head": 3, "tail": 2, "match_lines": 2})
    got = at.excerpt_lines(res["lines"])
    check("bridge.head_match_tail", res["ok"] and sorted(got) == [1, 2, 3, 55, 70, 99, 100] and res["matched"] == 3 and res["file_lines"] == 100, sorted(got))
    check("bridge.line_truncated", got[55].endswith("…") and len(got[55]) == 400)
    check("bridge.real_numbers", got[70].startswith("line 70 giselle"))
    check("bridge.refuses_other_files", ns["excerpt_for"]({"file": "../secrets.md"})["ok"] is False
          and ns["excerpt_for"]({"file": "_HANDOFF.md"})["ok"] is False and ns["excerpt_for"]({"file": "rob.md"})["ok"] is False)
    check("bridge.missing_file", ns["excerpt_for"]({"file": "LARA.md"})["error"].startswith("no such memory file"))

# ── 5 · a round, end to end, with stubs (T1b: a NameError after the post looped a round forever) ──
import ast
import types
tree = ast.parse(SRC)
NAMES = {"_agent_talk_run_round", "_agent_talk_run_round_inner", "_agent_talk_close", "_agent_talk_decision",
         "_at_conv_key", "_at_spend_today", "_at_cap_alert_once", "_agent_talk_advance", "_at_index_drop",
         "_at_index_add", "_at_open_conversations", "_at_load", "_at_save"}
code5 = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES)


class _Blk:
    def __init__(self, t, text=""):
        self.type, self.text = t, text


class _Resp:
    def __init__(self, text, out=300):
        self.content = [_Blk("thinking", ""), _Blk("text", text)]
        self.stop_reason = "end_turn"
        self.usage = types.SimpleNamespace(input_tokens=8000, output_tokens=out)


def _harness(reply_text, raise_api=False):
    PG = {}
    posts = []
    alerts = []
    errors = []

    class _PG:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def save_state(k, v):
            PG[k] = json.loads(json.dumps(v, default=str))
            return True

        @staticmethod
        def load_state(k, default=None):
            return json.loads(json.dumps(PG.get(k, default)))

    class _T:
        def __init__(self, target=None, args=(), daemon=True, name=""):
            self.target, self.args = target, args

        def start(self):
            pass

    def _call(model, system, messages, tier):
        if raise_api:
            raise RuntimeError("boom")
        return _Resp(reply_text)

    G = {"_pg": _PG, "_at": at, "time": time, "json": json, "threading": types.SimpleNamespace(Thread=_T),
         "_report_error": lambda c, e, d="": errors.append((c, str(e), d)),
         "_at_read_thread": lambda ch, ts: [{"text": KICK, "user": "U1"}],
         "_at_post": lambda ch, text, thread_ts=None: (posts.append((ch, text, thread_ts)) or "1.1"),
         "_agent_talk_call": _call, "AGENT_TALK_MODELS": {"haiku": "h", "sonnet": "s"}, "AGENT_TALK_CAP_USD": 3.0,
         "_TALLY": types.SimpleNamespace(bump=lambda *a, **k: None), "_at_today": lambda: "2026-11-02",
         "_operator_alert": types.SimpleNamespace(alert=lambda k, t, eric_text=None: (alerts.append((k, t)) or {"sms": "sent"})),
         "_AT_INDEX": "agent_talk_index", "_AT_DECISIONS": "agent_decisions", "_at_round_guard": {},
         "_at_cap_alerted": {"day": ""}, "_at_lock": __import__("threading").Lock(), "datetime": __import__("datetime").datetime,
         "print": lambda *a, **k: None}
    exec(code5, G)
    conv = at.new_conversation("C0AR7NY6SHF", "1.0", KICK, at.parse_assignment(KICK))
    conv["memreq"] = {"id": "r1", "agent": "ROB", "served": {"ok": True, "lines": "17419: Giselle paid in full", "served": 1}}
    conv["status"] = "open"
    PG["agent_talk:C0AR7NY6SHF:1.0"] = json.loads(json.dumps(conv))
    PG["agent_talk_index"] = ["C0AR7NY6SHF:1.0"]
    return G, PG, posts, alerts, errors


import json
G, PG, posts, alerts, errors = _harness('ROB.md line 17419: "Giselle paid in full"\nfacts\n— ROB (round 1)\n→ DEV, your turn')
G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0")
c = PG["agent_talk:C0AR7NY6SHF:1.0"]
check("round.posted_once", len(posts) == 1 and posts[0][1].startswith("*ROB* · round 1\nROB.md line 17419") and posts[0][2] == "1.0", posts)
check("round.state_saved", c["rounds"] == {"ROB": 1, "DEV": 0} and c["turn"] == "DEV" and c["status"] == "open" and c["memreq"] is None, (c["rounds"], c["turn"], c["status"]))
check("round.log_and_cost", len(c["log"]) == 1 and c["log"][0]["tier"] == "sonnet" and c["log"][0]["mem_verified"] is True
      and c["log"][0]["stop"] == "end_turn" and c["log"][0]["blocks"] == ["thinking", "text"] and abs(c["usd"] - at.cost_usd("sonnet", 8000, 300)) < 1e-9, c["log"])
check("round.spend_saved", PG.get("agent_talk_spend:2026-11-02", {}).get("rounds") == 1 and PG["agent_talk_spend:2026-11-02"]["by_tier"] == {"sonnet": 1})
check("round.no_errors", errors == [], errors)
G, PG, posts, alerts, errors = _harness("", raise_api=True)
G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0")
c = PG["agent_talk:C0AR7NY6SHF:1.0"]
check("round.api_failure_is_a_stall_not_a_post", posts == [] and c["stalls"] == 1 and c["status"] == "open" and c["memreq"] is not None
      and errors and errors[0][0] == "agent_talk.api", (posts, c.get("stalls"), errors))
G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0"); G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0")
c = PG["agent_talk:C0AR7NY6SHF:1.0"]
check("round.three_stalls_close", c["status"] == "closed" and c["close_reason"] == "stalled" and any("API refused 3 times" in p[1] for p in posts), (c["status"], posts))
G, PG, posts, alerts, errors = _harness('x\n— ROB (round 1)\n→ DEV, your turn')
G["_at_save"] = lambda k, v: False     # pg refusing every save: the guard must still stop the loop
for _ in range(12):
    G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0")
check("round.guard_stops_a_runaway", len(posts) == 3 * 2 + 2 + 1 and sum("round guard" in p[1] for p in posts) == 1, len(posts))
G, PG, posts, alerts, errors = _harness('DEV.md line 1: x\n— DEV (round 1)\nAGREED — for Michael:\n• one line\n• two')
c0 = PG["agent_talk:C0AR7NY6SHF:1.0"]; c0["turn"] = "DEV"; c0["memreq"]["agent"] = "DEV"
G["_agent_talk_run_round"]("C0AR7NY6SHF:1.0")
c = PG["agent_talk:C0AR7NY6SHF:1.0"]
check("round.agreed_makes_a_decision", c["status"] == "closed" and c["close_reason"] == "agreed" and c["decision_id"] == 1
      and PG["agent_decision:1"]["sms"].startswith("MWM decision 1: one line two") and alerts and alerts[0][0] == "decision"
      and any("⏱ 1 round" in p[1] for p in posts), (c["status"], alerts, [p[1][:40] for p in posts]))
check("app.stop_route", "@app.route('/admin/agent-talk/stop'" in SRC and '_agent_talk_close(conv, "stopped"' in SRC)
check("app.save_false_is_reported", '_report_error("agent_talk.pg_save", "save_state returned False", k)' in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch262.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #262 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("262: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE263 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
