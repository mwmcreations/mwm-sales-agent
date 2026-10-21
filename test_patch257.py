"""PATCH #257 gate — an empty inbound never reaches Claude, and a history
that already carries one is repaired before the call (Melina Wiebusch,
+1 786…4823, Tue 20 Oct 13:26: a message with no text → '' in the history
→ the API refuses empty content → three retries → "Sorry, I'm having a
technical issue right now", and the empty turn stayed in her history).

1. _history_needs_repair (pure) + _normalize_history in place inside
   get_claude_reply (lifted with a fake client), so the poisoned turn is
   dropped and the call goes through.
2. The webhook reads button / contacts / location / request_welcome
   instead of passing ''.
3. _handle_incoming answers an empty message itself (voice note that
   transcribed to nothing, unknown kind) and returns before the history.
4. The fallback reply reports to the error rail (#dev), on WhatsApp and IG.
Then runs the #256 gate (→ 255 → …)."""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_history_needs_repair", "_normalize_history", "get_claude_reply"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want))

calls, tally = [], []


class Tally:
    def bump(self, *a): tally.append(a)


class Block:
    def __init__(self, text): self.type = "text"; self.text = text


class Resp:
    def __init__(self, text): self.stop_reason = "end_turn"; self.content = [Block(text)]


class Msgs:
    def create(self, **kw):
        calls.append(dict(kw, messages=[dict(m) for m in kw["messages"]]))   # a copy: the caller appends to its list after
        for m in kw["messages"]:
            c = m["content"]
            if (isinstance(c, str) and not c.strip()) or (isinstance(c, list) and not c):
                raise RuntimeError("400 messages: text content blocks must be non-empty")
        return Resp("Oi! Como posso ajudar?")


class Client:
    messages = Msgs()


G = dict(client=Client(), MODEL_MAIN="m", TOOLS=[], get_system_prompt=lambda: "sys", lead_data={},
         _lf=type("LF", (), {"TRACK_STUDIO_HOUR": "studio-hour"})(), _sv=type("SV", (), {"STUDIO_HOUR_RULE": ""})(),
         _TALLY=Tally(), json=__import__("json"), handle_tool_call=lambda *a, **k: {}, _serialize_content_blocks=lambda c: c)
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_257", "exec"), G)
nr = G["_history_needs_repair"]

# ── 1 · repair ──────────────────────────────────────────────────────────────
check("needs.clean", nr([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]) is False)
check("needs.empty_str", nr([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "x"}, {"role": "user", "content": ""}]) is True)
check("needs.whitespace", nr([{"role": "user", "content": "   "}]) is True)
check("needs.empty_list", nr([{"role": "user", "content": []}]) is True)
check("needs.empty_text_block", nr([{"role": "user", "content": [{"type": "text", "text": ""}]}]) is True)
check("needs.tool_blocks_ok", nr([{"role": "user", "content": "hi"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "x", "input": {}}]},
                                  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "{}"}]}]) is False)
check("needs.junk", nr([{"role": "user", "content": "hi"}, "junk"]) is True and nr("x") is True and nr([{"role": "system", "content": "x"}]) is True)

hist = [{"role": "user", "content": "Bom dia!!!"}, {"role": "assistant", "content": "Bom dia! Me conta"},
        {"role": "user", "content": ""}, {"role": "assistant", "content": "Sorry, I'm having a technical issue right now. Please try again in a moment."},
        {"role": "user", "content": "Oi, ainda tem horário?"}]
reply, out = G["get_claude_reply"](hist, sender="whatsapp:+17864034823")
check("repair.call_went_through", reply == "Oi! Como posso ajudar?" and len(calls) == 1)
sent = calls[0]["messages"]
check("repair.empty_turn_dropped", all(str(m["content"]).strip() for m in sent) and sent[0]["content"] == "Bom dia!!!"
      and "technical issue" in sent[-2]["content"] and sent[-1]["content"].startswith("Oi, ainda"))
check("repair.in_place", out is hist and hist[-1]["role"] == "assistant" and hist[-1]["content"] == "Oi! Como posso ajudar?"
      and not any(isinstance(m.get("content"), str) and not m["content"].strip() for m in hist))
check("repair.tallied", ("maya.history_repaired", "4823") in tally)
calls.clear(); tally.clear()
clean = [{"role": "user", "content": "hi"}]
G["get_claude_reply"](clean, sender="whatsapp:+1")
check("repair.clean_untouched", not tally and calls[0]["messages"][0]["content"] == "hi")

# ── 2 · webhook kinds ───────────────────────────────────────────────────────
i = SRC.index('elif msg_type == "reaction":')
blk = SRC[i:i + 2400]
check("webhook.button", 'elif msg_type == "button":' in blk and '(msg.get("button") or {}).get("text")' in blk)
check("webhook.contacts", 'elif msg_type == "contacts":' in blk and "[shared a contact card:" in blk)
check("webhook.location", 'elif msg_type == "location":' in blk and "[shared a location:" in blk)
check("webhook.request_welcome", 'elif msg_type == "request_welcome":' in blk and "greet them]" in blk)
check("webhook.after_interactive", blk.index('elif msg_type == "interactive":') < blk.index('elif msg_type == "button":'))

# ── 3 · the empty-inbound door ─────────────────────────────────────────────
j = SRC.index('if not str(incoming_msg or "").strip():\n        _TALLY.bump("maya.empty_inbound"')
check("door.before_history", SRC.index("Thanks for the file! How can I help you today?") < j
      < SRC.index('conversation_history[sender].append({"role": "user", "content": incoming_msg})'))
door = SRC[j:j + 900]
check("door.replies_and_returns", "could you type it for me?" in door and "could you send it as text?" in door
      and "send_whatsapp_meta(sender, body=(" in door and door.count("return") >= 1)
check("door.audio_branch", '"audio" if was_audio else (content_type or "no-text")' in door)

# ── 4 · the fallback is no longer silent ────────────────────────────────────
check("fallback.wa_reported", '_report_error("maya.reply_fallback", e, f"{sndr}' in SRC
      and SRC.index('print(f"\\u274c Maya error: {e}")') < SRC.index('_report_error("maya.reply_fallback"'))
check("fallback.ig_reported", '_report_error("maya.ig_reply_fallback", e, f"{sndr}' in SRC
      and SRC.index('print(f"❌ IG DM Maya error: {e}")') < SRC.index('_report_error("maya.ig_reply_fallback"'))
check("fallback.text_kept", SRC.count("Sorry, I'm having a technical issue right now. Please try again in a moment.") >= 2)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch256.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #256 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("256: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE257 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
