"""PATCH #259 gate — the calendar-sync deletion question is posted WITHOUT link
previews (Oct 21 2026, booking #107 / Jonathan Pineda: Slack's link previewer
fetched "No, put it back" 7 s after the question, the deleted event came back
with a fresh invite, and Michael's "Yes" link was dead before he saw it).

1. post_to_slack / _post_to_slack_async accept `unfurl`; `unfurl=False` puts
   unfurl_links=False + unfurl_media=False in the payload; default payload is
   unchanged.
2. calendar_sync._slack forwards `unfurl` and falls back when the injected
   poster has no such kwarg; _handle_deletion posts its question with
   unfurl=False and the copy says the button is the answer.
Then runs the #258 gate (→ 257 → …)."""
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
CS = open(os.path.join(HERE, "calendar_sync.py"), encoding="utf-8").read()

# ── 1 · post_to_slack lifted with a fake requests ─────────────────────────
tree = ast.parse(SRC)
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"post_to_slack", "_post_to_slack_async"}]
check("lift.found", len(fns) == 2)
sent = []


class _Resp:
    def raise_for_status(self): pass
    def json(self): return {"ok": True, "ts": "1.2"}


class _Req:
    def post(self, url, json=None, headers=None, timeout=None):
        sent.append(json); return _Resp()


class _Thread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}
    def start(self): self._t(*self._a, **self._k)


G = dict(SLACK_BOT_TOKEN="xoxb-test", http_requests=_Req(), threading=type("T", (), {"Thread": _Thread})(), print=lambda *a, **k: None)
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_259", "exec"), G)
G["post_to_slack"]("C1", "hello")
check("payload.default_unchanged", sent[-1] == {"channel": "C1", "text": "hello"})
G["post_to_slack"]("C1", "hello", unfurl=False)
check("payload.unfurl_false", sent[-1].get("unfurl_links") is False and sent[-1].get("unfurl_media") is False)
G["post_to_slack"]("C1", "hello", unfurl=True)
check("payload.unfurl_true_is_default", "unfurl_links" not in sent[-1])
G["_post_to_slack_async"]("C2", "x", unfurl=False)
check("async.forwards", sent[-1]["channel"] == "C2" and sent[-1].get("unfurl_links") is False)
G["_post_to_slack_async"]("C2", "y")
check("async.default", sent[-1] == {"channel": "C2", "text": "y"})
check("async.signature_kept", "def _post_to_slack_async(channel, text, blocks=None, unfurl=None):" in SRC)

# ── 2 · calendar_sync._slack + the question ───────────────────────────────
import calendar_sync as cs  # noqa: E402
calls = []


def poster(ch, text, unfurl=None):
    calls.append((ch, text, unfurl))


def old_poster(ch, text):
    calls.append((ch, text, "old"))


cs._deps.clear()
cs._deps.update({"post_slack": poster, "matt_channel": "CM"})
cs._slack("matt_channel", "a")
cs._slack("matt_channel", "b", unfurl=False)
check("slack.default_no_kwarg", calls[0] == ("CM", "a", None))
check("slack.unfurl_forwarded", calls[1] == ("CM", "b", False))
cs._deps["post_slack"] = old_poster
cs._slack("matt_channel", "c", unfurl=False)
check("slack.old_poster_fallback", calls[2] == ("CM", "c", "old"))

# _handle_deletion: drive it to the "ask" branch with fake deps
store = {}
cs._deps.clear()
cs._deps.update({
    "post_slack": poster, "matt_channel": "CM",
    "pg_load": lambda k, d=None: store.get(k, d), "pg_save": lambda k, v: store.__setitem__(k, v),
    "wp_post": lambda payload: {"ok": True, "state": "ask", "question": "Booking #107 · Jonathan Pineda",
                                "yes_url": "https://mwmcreations.com/?a=yes", "no_url": "https://mwmcreations.com/?a=no"},
    "report_error": lambda *a, **k: None,
})
store[cs.KEY_EVENT + "evt1"] = {"booking_id": 107}
store[cs.KEY_CURRENT + "107"] = {"event_id": "evt1"}
calls.clear()
summary = {"skipped": 0, "wp_calls": 0, "failed": 0, "asked": 0}
cs._handle_deletion("evt1", summary)
check("question.asked", summary["asked"] == 1 and len(calls) == 1, f"{summary} {len(calls)}")
ch, text, unf = calls[0] if calls else ("", "", None)
check("question.no_unfurl", unf is False)
check("question.links_kept", "?a=yes|✅ Yes, cancel it>" in text and "?a=no|↩️ No, put it back>" in text)
check("question.button_copy", "the button is the answer" in text)
check("question.source", 'unfurl=False)' in CS[CS.index("def _handle_deletion"):CS.index("def sync_once")])

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch258.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #258 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("258: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE259 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
