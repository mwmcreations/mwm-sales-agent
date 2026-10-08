"""PATCH #155 gate — info@ deliveries: several TO, a working CC, replies in
the client's thread (Michael via LARA, 8 Oct 2026).

LARA's only info@ door, /api/send-email, took ONE recipient, read no `cc`
at all (the sender honoured it; the endpoint never passed it — 200 and
nobody copied), and never threaded (no In-Reply-To / References, no
threadId). This gate drives susan_gmail with a fake Gmail service and
proves: TO may be a list; CC reaches the MIME; a reply looks the thread up
in the mailbox that holds it, copies the Message-ID into In-Reply-To /
References, keeps the subject ("Re: " once), sends from that mailbox with
threadId; a raw in_reply_to works without a lookup; a new conversation
still needs a subject; every address (TO and CC) faces the guard; the
endpoint and /api/find-thread are wired. Prints "N passed, M failed", then
runs the existing send-guard test and the #154 gate.
"""
import base64
import email
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import susan_gmail as sg   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ── a fake Gmail API ─────────────────────────────────────────────────────────
STATE = {"sent": [], "impersonated": [], "threads": {}, "messages": {}}


class _Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        if isinstance(self.v, Exception):
            raise self.v
        return self.v


class _Messages:
    def send(self, userId, body):
        STATE["sent"].append(body)
        return _Exec({"id": "sent-%d" % len(STATE["sent"]), "threadId": body.get("threadId", "new-thread")})

    def get(self, userId, id, format=None, metadataHeaders=None):
        m = STATE["messages"].get(id)
        return _Exec(m if m else Exception("404 message %s" % id))

    def list(self, userId, q, maxResults):
        return _Exec({"messages": [{"id": mid, "threadId": m["threadId"]}
                                   for mid, m in STATE["messages"].items() if q.split(":")[1].split(" ")[0] in str(m)]})


class _Threads:
    def get(self, userId, id, format=None, metadataHeaders=None):
        t = STATE["threads"].get(id)
        return _Exec(t if t else Exception("404 thread %s" % id))


class _Users:
    def messages(self):
        return _Messages()

    def threads(self):
        return _Threads()


class FakeService:
    def __init__(self, who):
        self.who = who

    def users(self):
        return _Users()


def _hdrs(**kw):
    return [{"name": k.replace("_", "-"), "value": v} for k, v in kw.items()]


STATE["threads"]["T1"] = {"id": "T1", "messages": [
    {"id": "m0", "threadId": "T1", "payload": {"headers": _hdrs(Message_ID="<m0@client>", Subject="Your delivery", From="client@x.com", To="info@mwmcreations.com", Date="Mon")}},
    {"id": "m1", "threadId": "T1", "payload": {"headers": _hdrs(Message_ID="<m1@client>", References="<m0@client>", Subject="Re: Your delivery", From="client@x.com", To="info@mwmcreations.com", Date="Tue")}},
]}
STATE["messages"]["m1"] = {"id": "m1", "threadId": "T1", "payload": STATE["threads"]["T1"]["messages"][1]["payload"], "snippet": "client@x.com"}

sg._get_gmail_service = lambda: (STATE["impersonated"].append("michael@mwmcreations.com") or FakeService("michael"))
sg._thread_service = lambda addr: (STATE["impersonated"].append(addr) or FakeService(addr))
sg.configure_suppression(lambda a: (a.strip().lower() in ("blocked@x.com",), "do-not-contact list" if a.strip().lower() == "blocked@x.com" else ""))


def reset():
    STATE["sent"].clear(); STATE["impersonated"].clear()


def last_mime():
    raw = STATE["sent"][-1]["raw"]
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


# ── recipients ───────────────────────────────────────────────────────────────
check("recipients.multi_to", sg._recipients("a@x.com, b@y.com", "c@z.com") == ["a@x.com", "b@y.com", "c@z.com"])
check("recipients.single", sg._recipients("a@x.com", None) == ["a@x.com"])

# ── a plain send with two TO and a CC ────────────────────────────────────────
reset()
r = sg.send_gmail("a@x.com, b@y.com", "Hello", "<p>hi</p>", cc="c@z.com")
m = last_mime()
check("multi.ok", r.get("ok") is True and r.get("thread_id") == "new-thread", r)
check("multi.to", m["to"] == "a@x.com, b@y.com", m["to"])
check("multi.cc", m["cc"] == "c@z.com", m["cc"])
check("multi.from", m["from"] == sg.SUSAN_SEND_AS)
check("multi.no_thread", "threadId" not in STATE["sent"][-1] and m["In-Reply-To"] is None)
check("multi.impersonates_michael", STATE["impersonated"] == ["michael@mwmcreations.com"], STATE["impersonated"])

# ── a blocked CC stops the whole send ────────────────────────────────────────
reset()
r = sg.send_gmail("a@x.com", "Hello", "<p>hi</p>", cc="blocked@x.com")
check("guard.cc", r.get("ok") is False and r.get("suppressed") and r.get("blocked_address") == "blocked@x.com" and not STATE["sent"], r)
reset()
r = sg.send_gmail("a@x.com, blocked@x.com", "Hello", "<p>hi</p>")
check("guard.second_to", r.get("ok") is False and r.get("blocked_address") == "blocked@x.com" and not STATE["sent"], r)

# ── a reply by thread id: lookup, headers, subject, threadId, mailbox ────────
reset()
r = sg.send_gmail("client@x.com", "", "<p>here it is</p>", thread={"mailbox": "info", "thread_id": "T1"})
m = last_mime()
check("reply.ok", r.get("ok") is True and r.get("thread_id") == "T1", r)
check("reply.in_reply_to", m["In-Reply-To"] == "<m1@client>", m["In-Reply-To"])
check("reply.references", m["References"] == "<m0@client> <m1@client>", m["References"])
check("reply.subject", m["subject"] == "Re: Your delivery", m["subject"])
check("reply.threadId", STATE["sent"][-1].get("threadId") == "T1")
check("reply.from_info_mailbox", STATE["impersonated"] == ["info@mwmcreations.com"], STATE["impersonated"])
check("reply.from_header", m["from"] == "info@mwmcreations.com")
check("reply.replied_in", r.get("replied_in") == {"mailbox": "info@mwmcreations.com", "thread_id": "T1", "in_reply_to": "<m1@client>"}, r.get("replied_in"))

# the caller's own subject is kept when given
reset()
sg.send_gmail("client@x.com", "Your files, as promised", "<p>x</p>", thread={"thread_id": "T1"})
check("reply.caller_subject", last_mime()["subject"] == "Your files, as promised")
check("reply.default_mailbox_info", STATE["impersonated"] == ["info@mwmcreations.com"])

# by Gmail message id, in michael@'s mailbox
reset()
r = sg.send_gmail("client@x.com", "", "<p>x</p>", thread={"mailbox": "michael", "message_id": "m1"})
check("reply.by_message_id", r.get("ok") and STATE["sent"][-1].get("threadId") == "T1" and last_mime()["In-Reply-To"] == "<m1@client>", r)
check("reply.michael_mailbox", STATE["impersonated"] == ["michael@mwmcreations.com"], STATE["impersonated"])

# a raw Message-ID: headers only, no lookup, no threadId
reset()
r = sg.send_gmail("client@x.com", "Re: Your delivery", "<p>x</p>", thread={"in_reply_to": "<abc@client>", "references": "<zzz@client>"})
m = last_mime()
check("reply.raw", r.get("ok") and m["In-Reply-To"] == "<abc@client>" and m["References"] == "<zzz@client> <abc@client>" and "threadId" not in STATE["sent"][-1], (r, m["References"]))

# with an attachment the headers still ride along
reset()
sg._get_drive_service = lambda: None
import types as _t
_fake_drive = _t.SimpleNamespace()
check("reply.attachment_path_exists", "for _hk, _hv in _reply_headers.items():" in open(os.path.join(HERE, "susan_gmail.py"), encoding="utf-8").read().split("multipart/mixed with attachment")[1][:900])

# a missing thread fails honestly; a new conversation needs a subject
reset()
r = sg.send_gmail("client@x.com", "", "<p>x</p>", thread={"thread_id": "NOPE"})
check("reply.missing_thread", r.get("ok") is False and "404" in r.get("error", "") and not STATE["sent"], r)
reset()
r = sg.send_gmail("client@x.com", "", "<p>x</p>")
check("new.needs_subject", r.get("ok") is False and "subject" in r.get("error", "") and not STATE["sent"], r)
reset()
r = sg.send_gmail("client@x.com", "x", "<p>x</p>", thread={"mailbox": "bogus", "thread_id": "T1"})
check("reply.bad_mailbox", r.get("ok") is False and "mailbox" in r.get("error", ""), r)

# ── helpers ──────────────────────────────────────────────────────────────────
check("subject.re_once", sg.reply_subject("Re: X") == "Re: X" and sg.reply_subject("RE: X") == "RE: X" and sg.reply_subject("X") == "Re: X" and sg.reply_subject("") == "")
check("mailbox.map", sg._mailbox_address("info") == "info@mwmcreations.com" and sg._mailbox_address("") == "info@mwmcreations.com"
      and sg._mailbox_address("michael") == "michael@mwmcreations.com" and sg._mailbox_address("INFO@MWMCREATIONS.COM") == "info@mwmcreations.com")
try:
    sg._mailbox_address("someone@gmail.com"); check("mailbox.rejects_foreign", False)
except ValueError:
    check("mailbox.rejects_foreign", True)
reset()
th = sg.find_threads("client@x.com", mailbox="info", limit=5)
check("find.threads", len(th) == 1 and th[0]["thread_id"] == "T1" and th[0]["last_message_id"] == "m1" and th[0]["subject"] == "Re: Your delivery", th)
check("find.readonly_scope", "gmail.readonly" in " ".join(sg.SCOPES_GMAIL_THREAD) and sg.SCOPES_GMAIL == ["https://www.googleapis.com/auth/gmail.send"])
try:
    sg.find_threads("not-an-email"); check("find.needs_email", False)
except ValueError:
    check("find.needs_email", True)

# ── wiring (static) ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
rt = SRC[SRC.index("def api_send_email():"):SRC.index("def api_find_thread():")]
check("wire.to_list", 'to_list = _addr_list(data.get("to", ""))' in rt and 'to_email = ", ".join(to_list)' in rt)
check("wire.cc_read", 'cc_list = _addr_list(data.get("cc", ""))' in rt and "cc=(cc_email or None)" in rt)
check("wire.thread_params", 'data.get("thread_id")' in rt and 'data.get("reply_to_message_id")' in rt and 'data.get("in_reply_to")' in rt and "thread=_thread" in rt)
check("wire.subject_optional_for_reply", 'if not subject and not (_thread and (_thread.get("thread_id") or _thread.get("message_id"))):' in rt)
check("wire.guard_every_address", "for _addr in to_list + cc_list:" in rt and rt.index("for _addr in to_list + cc_list:") < rt.index("_email_send(to_email"))
check("wire.fold_every_address", "for _lst in (to_list, cc_list):" in rt)
check("wire.409_from_sender", 'if result.get("suppressed"):' in rt and "409" in rt[rt.index('if result.get("suppressed"):'):rt.index('if result.get("suppressed"):') + 300])
check("wire.response_lists", '"to": to_list,' in rt and '"cc": cc_list,' in rt and '"thread_id": result.get("thread_id", "")' in rt)
check("wire.find_thread_route", "@app.route('/api/find-thread', methods=['GET', 'POST'])" in SRC and "_susan_gmail_mod.find_threads(_email, mailbox=_mailbox, limit=_limit)" in SRC)
ft = SRC[SRC.index("def api_find_thread():"):SRC.index("def api_find_thread():") + 2600]
check("wire.find_thread_auth", "_api_auth_token(data)" in ft and "mailbox must be 'info' or 'michael'" in ft)
es = SRC[SRC.index("def _email_send("):SRC.index("def email_ok(")]
check("wire.email_send_thread", "thread=None" in es and '_kw["thread"] = thread' in es)
check("wire.email_send_each_to", 'for _one in [a.strip() for a in re.split(r"[,;]+", _to) if a.strip()] or [_to]:' in es)
check("wire.stamp_each_to", 'for _one in [a.strip().lower() for a in re.split(r"[,;]+", _to) if a.strip()] or [_to.lower()]:' in es)

print(f"static+behaviour: {passed} passed, {failed} failed")

# the existing send guard still holds, then the whole rail (#154 → … → #143)
for gate in ("test_send_guard.py", "test_patch154.py"):
    r_ = subprocess.run([sys.executable, os.path.join(HERE, gate)], capture_output=True, text=True)
    lines = r_.stdout.strip().splitlines() or [""]
    tail = next((ln for ln in reversed(lines) if re.search(r"(\d+) passed, (\d+) failed", ln)), lines[-1])
    m_ = re.search(r"(\d+) passed, (\d+) failed", tail)
    if r_.returncode != 0:
        print(r_.stdout[-1500:]); print(r_.stderr[-800:])
        failed += 1; print(f"FAIL {gate} did not pass")
    elif m_:
        passed += int(m_.group(1)); failed += int(m_.group(2))
        print(f"{gate}: {tail}")
    else:
        passed += 1                      # test_send_guard prints "TOTAL: ALL PASS"
        print(f"{gate}: {tail}")
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
