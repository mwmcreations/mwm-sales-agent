#!/usr/bin/env python3
"""Patch #44A — behavioural tests for the do-not-contact guard.

These test the ONE thing Patch #38 believed it had already done: that a lead on
the do-not-contact list cannot be emailed. #38 enforced it at /api/send-email,
which is the endpoint a human calls. Five automated call sites went straight to
send_gmail() and were never checked. These tests pin the guard at the chokepoint
so that bypass cannot come back.

Run: python3 test_send_guard.py
"""
import json
import os
import sys

import susan_gmail as sg

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok else f"\n          got={got!r}\n         want={want!r}"))
    if not ok:
        FAILS.append(label)


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


# ══════════════════════════════════════════════════════════════════════
section("1 · unconfigured hook must FAIL CLOSED")
# If app.py never wires the predicate, the safe posture is to send NOTHING.
# The opposite default — send everything — is how a wiring regression turns
# into quietly emailing people who asked us to stop.
sg._SUPPRESSION_HOOK = None
check("suppression_configured() is False", sg.suppression_configured(), False)
check("_suppressed blocks when unconfigured", sg._suppressed("a@b.com")[0], True)
_r = sg.send_gmail("a@b.com", "s", "<p>x</p>")
check("send_gmail refuses", _r.get("ok"), False)
check("...and marks it suppressed", _r.get("suppressed"), True)
check("...and never reached Gmail", "message_id" in _r, False)


# ══════════════════════════════════════════════════════════════════════
section("2 · configured hook — allow the clean, block the listed")
sg.configure_suppression(lambda a: (str(a).strip().lower() == "dnc@x.com",
                                    "do-not-contact list"))
check("suppression_configured() is True", sg.suppression_configured(), True)
check("clean address passes the predicate", sg._suppressed("ok@x.com")[0], False)
check("listed address is blocked", sg._suppressed("dnc@x.com")[0], True)
check("blocking is case-insensitive", sg._suppressed("DNC@X.com")[0], True)
check("...and whitespace-insensitive", sg._suppressed("  dnc@x.com ")[0], True)

_r = sg.send_gmail("dnc@x.com", "s", "<p>x</p>")
check("send to a listed address is refused", _r.get("ok"), False)
check("...and names which address", _r.get("blocked_address"), "dnc@x.com")
check("...with a human-readable reason",
      "do-not-contact" in _r.get("error", ""), True)


# ══════════════════════════════════════════════════════════════════════
section("3 · CC is a recipient too")
# A DNC address in CC is still a DNC address receiving mail. The welcome-email
# path (app.py:13330) passes cc=, so this is a live shape, not a hypothetical.
check("comma-separated cc parsed",
      sg._recipients("a@x.com", "b@x.com, c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])
check("semicolon-separated cc parsed",
      sg._recipients("a@x.com", "b@x.com; c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])
check("empty cc ignored", sg._recipients("a@x.com", ""), ["a@x.com"])
check("None cc ignored", sg._recipients("a@x.com", None), ["a@x.com"])
check("blank fragments dropped",
      sg._recipients("a@x.com", "b@x.com,,  ,c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])

_r = sg.send_gmail("ok@x.com", "s", "<p>x</p>", cc="dnc@x.com")
check("a listed CC blocks the WHOLE send", _r.get("ok"), False)
check("...and names the CC address", _r.get("blocked_address"), "dnc@x.com")


# ══════════════════════════════════════════════════════════════════════
section("4 · a predicate that RAISES must fail closed")
# Postgres down, import error, anything. An exception is not permission.
def _boom(_addr):
    raise RuntimeError("pg down")


sg.configure_suppression(_boom)
check("raising predicate blocks", sg._suppressed("ok@x.com")[0], True)
check("...with the cause in the reason",
      "raised" in sg._suppressed("ok@x.com")[1], True)
check("raising predicate refuses the send",
      sg.send_gmail("ok@x.com", "s", "x").get("ok"), False)


# ══════════════════════════════════════════════════════════════════════
section("5 · a predicate returning junk must fail closed")
sg.configure_suppression(lambda a: None)          # not a 2-tuple
check("None return blocks", sg._suppressed("ok@x.com")[0], True)
sg.configure_suppression(lambda a: (0, ""))       # falsy but well-formed
check("well-formed falsy allows", sg._suppressed("ok@x.com")[0], False)


# ══════════════════════════════════════════════════════════════════════
section("6 · the truthiness trap that made this invisible")
# send_gmail returns a dict on success AND failure, and BOTH are truthy.
# app.py:8871 and the studio-pitch dep both wrote `if send_gmail(...):`, so a
# refused send was recorded as delivered and the error branch was unreachable.
# This is the assertion that would have caught it.
sg.configure_suppression(lambda a: (True, "blocked"))
_blocked = sg.send_gmail("anyone@x.com", "s", "x")
check("the refusal dict is TRUTHY (the trap)", bool(_blocked), True)
check("...so callers must read ['ok'], which is False", _blocked.get("ok"), False)


# ══════════════════════════════════════════════════════════════════════
section("#68 — the operator channel: a second gate, not a hole in the first")
#
# Patch #58 built a door for "Maya needs to ask Michael". It never opened once
# in three days: MICHAEL_EMAIL is michael@mwmcreations.com and the guard above
# refuses that whole domain as internal. #66 tried to fix it by calling
# send_gmail directly, skipping app.py's wrapper — and hit the SECOND copy of
# the guard, which lives here. That belt-and-braces design worked exactly as
# written. The exemption therefore has to be a first-class argument to the
# sender, with its own allow-list.
import event_rail as _er68

_OPS68 = {"michael@mwmcreations.com"}
_DNC68 = {"yasminfmoraes@icloud.com", "ediasm@icloud.com"}


def _suppress68(a):
    e = str(a or "").strip().lower()
    if not e or "@" not in e:
        return True, "unparseable"
    if e in _DNC68:
        return True, "do-not-contact list"
    if e.endswith("@mwmcreations.com"):
        return True, "internal address"
    return False, ""


# ── fail closed before anything is wired ──
sg.configure_operators(None)
_r = sg.send_gmail("michael@mwmcreations.com", "s", "x", operator=True)
check("an UNCONFIGURED operator predicate refuses the send", _r.get("ok"), False)
check("...and says the predicate is missing rather than inventing a reason",
      "not configured" in _r.get("error", ""), True)

sg.configure_suppression(_suppress68)
sg.configure_operators(lambda a: _er68.operator_allowed(a, _OPS68, _DNC68))

# ── THE BUG, pinned. Michael without the flag must still be refused, because
#    that path is lead mail and the domain rule is correct for lead mail. ──
_r = sg.send_gmail("michael@mwmcreations.com", "s", "x")
check("Michael WITHOUT operator=True is still suppressed (this was the outage)",
      _r.get("ok"), False)
check("...for the internal-address reason specifically",
      "internal address" in _r.get("error", ""), True)

# ── the operator path clears BOTH gates and reaches the sender ──
_reached = {"v": False}
_real_service = sg._get_gmail_service


def _boom():
    _reached["v"] = True
    raise RuntimeError("reached the sender")


sg._get_gmail_service = _boom
try:
    sg.send_gmail("michael@mwmcreations.com", "s", "x", operator=True)
    check("operator=True gets PAST the guard to the actual send", _reached["v"], True)

    # ── and the gate is deny-by-default, not a hole ──
    _reached["v"] = False
    _r = sg.send_gmail("lead@gmail.com", "s", "x", operator=True)
    check("a LEAD cannot ride the operator flag", _r.get("ok"), False)
    check("...refused by the allow-list, not by a blocklist",
          "allow-list" in _r.get("error", ""), True)
    check("...and never reached the sender", _reached["v"], False)

    for _d in sorted(_DNC68):
        _reached["v"] = False
        _r = sg.send_gmail(_d, "s", "x", operator=True)
        check(f"{_d} is refused on the operator path too", _r.get("ok"), False)
        check("...because DNC outranks the operator list",
              "do-not-contact" in _r.get("error", ""), True)
        check("...and never reached the sender", _reached["v"], False)

    # ── CC would widen the blast radius past the one vetted address ──
    _reached["v"] = False
    _r = sg.send_gmail("michael@mwmcreations.com", "s", "x",
                       cc="someone@else.com", operator=True)
    check("an operator send carrying CC is refused outright", _r.get("ok"), False)
    check("...and never reached the sender", _reached["v"], False)

    # ── ordinary lead sending must be completely unaffected ──
    _reached["v"] = False
    sg.send_gmail("ok@gmail.com", "s", "x")
    check("a normal permitted lead send still reaches the sender", _reached["v"], True)
finally:
    sg._get_gmail_service = _real_service

check("operators_configured() reports the wire", sg.operators_configured(), True)
sg.configure_operators(None)
check("...and reports it missing once cleared", sg.operators_configured(), False)


# ══════════════════════════════════════════════════════════════════════
section("#69 — a client is not a lead: transactional mail vs marketing")
#
# Marcia Cardim booked a studio session for Aug 12 through the portal. She is
# on EMAIL_DNC because she became a CLIENT and must not receive lead
# follow-ups. Her four booking reminders route through the same guard, so all
# four would have been refused — and nobody would have known until she failed
# to show. Third audience the one blocklist was silently answering for.
_NEVER69 = {"yasminfmoraes@icloud.com"}          # test lead — never, by any path
_TXOK69 = {"ediasm@icloud.com"}                  # client — transactional only


def _sup69(a):
    e = str(a or "").strip().lower()
    if not e or "@" not in e:
        return True, "unparseable"
    if e in ("yasminfmoraes@icloud.com", "ediasm@icloud.com"):
        return True, "do-not-contact list"
    if e.endswith("@mwmcreations.com"):
        return True, "internal address"
    return False, ""


sg.configure_suppression(_sup69)
sg.configure_transactional(lambda a: _er68.transactional_allowed(a, _TXOK69, _NEVER69))

_hit69 = {"v": False}
_real69 = sg._get_gmail_service


def _boom69():
    _hit69["v"] = True
    raise RuntimeError("reached sender")


def _try69(**kw):
    _hit69["v"] = False
    try:
        sg.send_gmail(**kw)
    except RuntimeError:
        pass
    return _hit69["v"]


sg._get_gmail_service = _boom69
try:
    # THE BUG: the client's own booking reminder must now get through.
    check("a client on DNC RECEIVES transactional mail",
          _try69(to="ediasm@icloud.com", subject="s", body_html="h",
                 transactional=True), True)
    # ...and marketing to that same client must still be refused.
    check("...but marketing to that same client is still refused",
          _try69(to="ediasm@icloud.com", subject="s", body_html="h"), False)

    # THE HARD TIER: a test lead is unreachable by every path, flag or no flag.
    check("a never-contact address is refused even as transactional",
          _try69(to="yasminfmoraes@icloud.com", subject="s", body_html="h",
                 transactional=True), False)
    check("...and refused as ordinary mail",
          _try69(to="yasminfmoraes@icloud.com", subject="s", body_html="h"), False)
    check("...and refused when hidden in CC of a transactional send",
          _try69(to="ok@gmail.com", cc="yasminfmoraes@icloud.com", subject="s",
                 body_html="h", transactional=True), False)

    # The exception is per-address, not a mode. Everyone else is unaffected.
    check("an ordinary lead is unaffected by the transactional flag",
          _try69(to="ok@gmail.com", subject="s", body_html="h",
                 transactional=True), True)
    check("an internal address is STILL refused as transactional",
          _try69(to="someone@mwmcreations.com", subject="s", body_html="h",
                 transactional=True), False)
    check("an allow-listed client in CC is permitted",
          _try69(to="ok@gmail.com", cc="ediasm@icloud.com", subject="s",
                 body_html="h", transactional=True), True)

    # Fail-safe direction: an unconfigured predicate must not open a hole.
    sg.configure_transactional(None)
    check("with NO transactional predicate, a DNC client stays blocked",
          _try69(to="ediasm@icloud.com", subject="s", body_html="h",
                 transactional=True), False)
finally:
    sg._get_gmail_service = _real69

# The predicate's three-way answer, on its own.
check("allow-listed client -> allow",
      _er68.transactional_allowed("ediasm@icloud.com", _TXOK69, _NEVER69)[0], "allow")
check("never-contact -> block",
      _er68.transactional_allowed("yasminfmoraes@icloud.com", _TXOK69, _NEVER69)[0], "block")
check("anyone else -> default (ordinary rules decide)",
      _er68.transactional_allowed("someone@gmail.com", _TXOK69, _NEVER69)[0], "default")
check("unparseable -> block",
      _er68.transactional_allowed("", _TXOK69, _NEVER69)[0], "block")
check("never-contact outranks being on BOTH lists",
      _er68.transactional_allowed("yasminfmoraes@icloud.com",
                                  _TXOK69 | _NEVER69, _NEVER69)[0], "block")
check("case and whitespace do not smuggle past the hard tier",
      _er68.transactional_allowed("  YasminFMoraes@iCloud.com ",
                                  _TXOK69, _NEVER69)[0], "block")


# ══════════════════════════════════════════════════════════════════════
section("#114 — the standing CC: a second person on a client's mail")
#
# Michael asked for Nicole to be copied on everything sent to Luzia Costa.
# The failure this pins is not "the CC is missing" — it is the OTHER two:
# a copied address that skips the do-not-contact guard, and a standing CC
# leaking onto the operator path, which refuses CC outright and would start
# rejecting mail to Michael himself.
_LUZIA114 = "luziahcosta@hotmail.com"
_NICOLE114 = "Nicole.formore@gmail.com"

os.environ.pop("SUSAN_ALWAYS_CC", None)

check("the client is in the built-in map",
      _NICOLE114 in sg._always_cc_map().get(_LUZIA114, []), True)
check("a send to the client gains the standing CC",
      sg._apply_always_cc(_LUZIA114, None), _NICOLE114)
check("...matched case-insensitively on the client address",
      sg._apply_always_cc("LuziaHCosta@Hotmail.COM", None), _NICOLE114)
check("...and with surrounding whitespace",
      sg._apply_always_cc("  luziahcosta@hotmail.com ", None), _NICOLE114)
check("an existing CC is kept, not replaced",
      sg._apply_always_cc(_LUZIA114, "someone@else.com"),
      "someone@else.com, " + _NICOLE114)
check("never added twice when already on the mail",
      sg._apply_always_cc(_LUZIA114, _NICOLE114), _NICOLE114)
check("...in any casing",
      sg._apply_always_cc(_LUZIA114, "nicole.formore@GMAIL.com"),
      "nicole.formore@GMAIL.com")
check("a standing CC keyed on a CC'd address still fires",
      sg._apply_always_cc("other@x.com", _LUZIA114),
      _LUZIA114 + ", " + _NICOLE114)
check("everyone else is untouched", sg._apply_always_cc("ok@gmail.com", None), None)
check("...including their existing CC",
      sg._apply_always_cc("ok@gmail.com", "a@b.com"), "a@b.com")

# The env override — a change should not need a deploy.
os.environ["SUSAN_ALWAYS_CC"] = json.dumps({"someone@new.com": ["watcher@x.com"]})
check("env adds a pair", sg._apply_always_cc("someone@new.com", None), "watcher@x.com")
check("...without dropping the built-in", sg._apply_always_cc(_LUZIA114, None), _NICOLE114)
os.environ["SUSAN_ALWAYS_CC"] = json.dumps({_LUZIA114: []})
check("env can clear one pair", sg._apply_always_cc(_LUZIA114, None), None)
os.environ["SUSAN_ALWAYS_CC"] = "{not json"
check("malformed env is ignored, built-ins survive",
      sg._apply_always_cc(_LUZIA114, None), _NICOLE114)
os.environ.pop("SUSAN_ALWAYS_CC", None)

# ── the part that matters: a copied address is still a recipient ──
_real114 = sg._get_gmail_service
_sent114 = {"cc": None, "reached": False}


class _Exec114:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Msg114:
    def send(self, userId=None, body=None):
        _sent114["reached"] = True
        import base64 as _b64, email as _em
        raw = _b64.urlsafe_b64decode(body["raw"].encode())
        _sent114["cc"] = _em.message_from_bytes(raw).get("cc")
        return _Exec114({"id": "fake114"})


class _Users114:
    def messages(self):
        return _Msg114()


class _Svc114:
    def users(self):
        return _Users114()


try:
    sg._get_gmail_service = lambda: _Svc114()
    sg.configure_suppression(lambda a: (str(a).strip().lower() == _NICOLE114.lower(),
                                        "do-not-contact list"))
    _r = sg.send_gmail(_LUZIA114, "s", "<p>x</p>")
    check("a SUPPRESSED standing CC blocks the whole send", _r.get("ok"), False)
    check("...and names the copied address, not the client",
          (_r.get("blocked_address") or "").lower(), _NICOLE114.lower())
    check("...and nothing was transmitted", _sent114["reached"], False)

    sg.configure_suppression(lambda a: (False, ""))
    _r = sg.send_gmail(_LUZIA114, "s", "<p>x</p>")
    check("with everyone clear, the send goes", _r.get("ok"), True)
    check("...and the CC header actually carries Nicole", _sent114["cc"], _NICOLE114)

    # The operator path refuses CC. If the standing map leaked into it, mail to
    # Michael would start bouncing off his own guard.
    sg.configure_operators(lambda a: (True, "operator"))
    _r = sg.send_gmail(_LUZIA114, "s", "x", operator=True)
    check("an operator send to a MAPPED address is not given a CC",
          _r.get("ok"), True)
    check("...so #68's no-CC rule never trips on it",
          "CC not permitted" in (_r.get("error") or ""), False)
finally:
    sg._get_gmail_service = _real114
    sg.configure_operators(None)


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
if FAILS:
    for f in FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
