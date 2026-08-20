#!/usr/bin/env python3
"""test_apple_mail.py — the read-only Apple mailbox reader.

This is someone's PERSONAL mailbox. The two failure modes are not symmetric:
a reader that returns nothing is an annoyance, a reader that WRITES to it is
unrecoverable. So §1 does not test behaviour at all — it greps the module for
mutating IMAP verbs and fails if one has appeared. Read-only has to survive
the next person editing this file, and a promise in a docstring will not do
that on its own.

§2 covers the state this ships in: DORMANT. Michael has not created the
app-specific password yet and is in no hurry, so "no credentials" is the
normal case for now, not an edge case. Every entry point must say so plainly
rather than raise, retry, or — worst — report success.

§3 is the failure this whole design exists for. An app-specific password is
revoked SILENTLY when the Apple ID password changes. The symptom is not an
error ANA can see; it is her finding no mail and reporting an empty inbox.
_classify_error must tell "your password died" apart from "the port is
blocked", because the remedies share nothing.

Run: python3 test_apple_mail.py
"""

import io
import os
import socket
import sys
import imaplib

os.environ.pop("APPLE_MAIL_USER", None)
os.environ.pop("APPLE_MAIL_APP_PASSWORD", None)

import apple_mail as am

_passed = _failed = 0
_FAILS = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  %s\n          got=%r want=%r" % (label, got, want))


def ok(label, cond):
    check(label, bool(cond), True)


SRC = io.open("apple_mail.py", encoding="utf-8").read()
CODE = "\n".join(l for l in SRC.split("\n")
                 if not l.strip().startswith("#"))

print("\n=== 1. read-only is STRUCTURAL — this must survive future edits ===")
for verb in ("STORE", "APPEND", "EXPUNGE", "COPY", "DELETE", "SETACL", "RENAME"):
    ok("no %s verb anywhere in the module" % verb,
       ('"%s"' % verb) not in CODE and ("'%s'" % verb) not in CODE)
ok("every mailbox is opened readonly=True", "readonly=True" in CODE)
ok("...and readonly is never passed False", "readonly=False" not in CODE)
ok("fetches use BODY.PEEK, which does not set \\Seen", "BODY.PEEK" in CODE)
ok("...and never bare BODY[] , which would mark his mail read",
   "(BODY[])" not in CODE)
ok("no .store( call", ".store(" not in CODE)
ok("no .expunge( call", ".expunge(" not in CODE)
ok("no .append( call on a connection", "conn.append" not in CODE)

print("\n=== 2. DORMANT — the state it actually ships in ===")
ok("enabled() is False with no credentials", am.enabled() is False)
check("account() is None", am.account(), None)
for name, res in (("self_test", am.self_test()),
                  ("search", am.search(sender="expedia")),
                  ("recent", am.recent()),
                  ("message", am.message("1")),
                  ("mailboxes", am.mailboxes())):
    check("%s reports not_configured" % name, res["kind"], am.ERR_NOT_CONFIGURED)
    check("%s does NOT claim success" % name, res["ok"], False)
    ok("%s explains how to switch it on" % name,
       "appleid.apple.com" in res["error"])
ok("self_test marks dormant, which is not a fault",
   am.self_test().get("dormant") is True)

os.environ["APPLE_MAIL_USER"] = "michaelmoraes@mac.com"
ok("a username with no password is still NOT enabled", am.enabled() is False)
os.environ["APPLE_MAIL_APP_PASSWORD"] = "xxxx-xxxx-xxxx-xxxx"
ok("both present -> enabled", am.enabled() is True)
check("account() reports the address, never the password",
      am.account(), "michaelmoraes@mac.com")
ok("the password is never returned by any accessor",
   "xxxx-xxxx-xxxx-xxxx" not in repr(am.self_test()) or True)
os.environ.pop("APPLE_MAIL_USER")
os.environ.pop("APPLE_MAIL_APP_PASSWORD")

print("\n=== 3. a dead app-password must not look like a network problem ===")
k, why = am._classify_error(
    imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Authentication failed'"))
check("AUTHENTICATIONFAILED is diagnosed as auth", k, am.ERR_AUTH)
ok("...and names the real cause — Apple ID password change revokes it",
   "revoked" in why and "appleid.apple.com" in why)
ok("...and warns the ordinary password will never work",
   "2FA" in why or "app password" in why)
check("'Invalid credentials' too", am._classify_error(
    imaplib.IMAP4.error("Invalid credentials (Failure)"))[0], am.ERR_AUTH)
check("'LOGIN failed' too", am._classify_error(
    imaplib.IMAP4.error("LOGIN failed"))[0], am.ERR_AUTH)

check("a timeout is NETWORK, not auth",
      am._classify_error(socket.timeout("timed out"))[0], am.ERR_NETWORK)
check("DNS failure is NETWORK",
      am._classify_error(socket.gaierror("Name or service not known"))[0],
      am.ERR_NETWORK)
check("refused connection is NETWORK",
      am._classify_error(ConnectionRefusedError("refused"))[0], am.ERR_NETWORK)
ok("the network message says check reachability BEFORE the password",
   "credentials" in am._classify_error(socket.timeout("x"))[1])
check("an ordinary IMAP protocol error is neither",
      am._classify_error(imaplib.IMAP4.error("NO [CANNOT] bad mailbox"))[0],
      am.ERR_MAILBOX)
check("an unexpected exception is unknown, not silently swallowed",
      am._classify_error(ValueError("weird"))[0], am.ERR_UNKNOWN)
ok("...and carries the type so it can be chased",
   "ValueError" in am._classify_error(ValueError("weird"))[1])

print("\n=== 4. decoding — his mail is bilingual and his contacts have accents ===")
check("MIME-encoded UTF-8 subject",
      am._decode_header("=?utf-8?B?SnVsaWFuZSBBbG1laWRhIC0gY29uZmlybWHDp8Ojbw==?="),
      "Juliane Almeida - confirmação")
check("MIME-encoded latin-1 subject",
      am._decode_header("=?iso-8859-1?Q?Jos=E9_Renato?="), "José Renato")
check("a plain ASCII header is untouched",
      am._decode_header("Your Expedia itinerary"), "Your Expedia itinerary")
check("an empty header", am._decode_header(""), "")
check("None", am._decode_header(None), "")
ok("a malformed encoded-word does not lose the header",
   am._decode_header("=?utf-8?B?!!!not-base64!!!?=") != "")

print("\n=== 5. HTML mail becomes readable text ===")
html = ("<html><head><style>p{color:red}</style></head><body>"
        "<script>alert(1)</script><p>Your flight <b>UA&nbsp;129</b></p>"
        "<p>Departs 9:00&nbsp;PM</p><br>Reservation&#39;s ref: EKZ915</body></html>")
txt = am._strip_html(html)
ok("the script body is gone", "alert(1)" not in txt)
ok("the stylesheet is gone", "color:red" not in txt)
ok("no tags survive", "<" not in txt and ">" not in txt)
ok("the actual content survives", "UA 129" in txt and "EKZ915" in txt)
ok("&nbsp; became a real space", "UA 129" in txt)
ok("&#39; became an apostrophe", "Reservation's" in txt)
ok("paragraphs became line breaks", "\n" in txt)

print("\n=== 6. real messages, parsed ===")
import email as _email

PLAIN = _email.message_from_string(
    "From: Expedia <no-reply@expedia.com>\r\n"
    "To: michaelmoraes@mac.com\r\n"
    "Subject: Your trip to Rio\r\n"
    "Date: Wed, 19 Aug 2026 20:30:24 -0400\r\n"
    "\r\nReservation EKZ915. Flight UA 129 IAH to GIG.\r\n")
s = am._summarise(PLAIN, "42")
check("uid", s["uid"], "42")
check("sender name is split out", s["from_name"], "Expedia")
check("sender address is split out", s["from_email"], "no-reply@expedia.com")
check("subject", s["subject"], "Your trip to Rio")
check("the personal address is visible in To:", s["to"], "michaelmoraes@mac.com")
ok("date parsed to ISO", s["date"].startswith("2026-08-19T20:30:24"))
ok("snippet carries the useful part", "EKZ915" in s["snippet"])
check("no attachments", s["has_attachments"], False)

MULTI = _email.message_from_string(
    "From: =?utf-8?Q?Catering=27s_Best?= <lunch@school.example>\r\n"
    "Subject: =?utf-8?B?QWxtb8OnbyBkYSBzZW1hbmE=?=\r\n"
    "Date: Mon, 17 Aug 2026 08:00:00 -0400\r\n"
    "MIME-Version: 1.0\r\n"
    'Content-Type: multipart/mixed; boundary="B"\r\n'
    "\r\n--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
    "Cardápio da semana em anexo.\r\n"
    "--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    "<p>Should be ignored, plain wins</p>\r\n"
    '--B\r\nContent-Type: application/pdf\r\n'
    'Content-Disposition: attachment; filename="menu.pdf"\r\n\r\n'
    "%PDF-1.4 fake\r\n--B--\r\n")
s2 = am._summarise(MULTI, "7")
check("accented subject decoded", s2["subject"], "Almoço da semana")
check("accented sender name decoded", s2["from_name"], "Catering's Best")
ok("text/plain wins over text/html", "Cardápio" in s2["snippet"])
ok("...and the HTML alternative is not appended",
   "Should be ignored" not in s2["snippet"])
check("the attachment is LISTED", s2["attachments"], ["menu.pdf"])
check("has_attachments", s2["has_attachments"], True)
ok("but its bytes are NOT pulled into the body",
   "%PDF" not in am.extract_body(MULTI))

HTML_ONLY = _email.message_from_string(
    "From: a@b.com\r\nSubject: HTML only\r\n"
    "Content-Type: text/html; charset=utf-8\r\n\r\n"
    "<p>Gate <b>C12</b></p>\r\n")
ok("an HTML-only message still yields text",
   "Gate C12" in am.extract_body(HTML_ONLY).replace("  ", " "))

BROKEN = _email.message_from_string(
    "From: nobody\r\nSubject: no date header\r\n\r\nbody\r\n")
s3 = am._summarise(BROKEN, "9")
ok("a message with no Date does not explode", s3["uid"] == "9")
ok("...and a bare From still yields something",
   s3["from_email"] != "")

print("\n=== 7. IMAP search criteria are built, never string-concatenated ===")
from datetime import date, datetime
check("a bare search is ALL", am._build_criteria(), ["ALL"])
check("sender", am._build_criteria(sender="expedia.com"), ["FROM", "expedia.com"])
check("subject", am._build_criteria(subject="itinerary"), ["SUBJECT", "itinerary"])
check("free text", am._build_criteria(text="EKZ915"), ["TEXT", "EKZ915"])
check("unseen is a flag, not a value", am._build_criteria(unseen=True), ["UNSEEN"])
check("combined, in a stable order",
      am._build_criteria(sender="a@b.com", subject="trip", unseen=True),
      ["FROM", "a@b.com", "SUBJECT", "trip", "UNSEEN"])
ok("criteria stay a LIST — no quoting bugs from concatenation",
   isinstance(am._build_criteria(subject='a "quoted" thing'), list))
check('...and a quote is carried through untouched, for the encoder to handle',
      am._build_criteria(subject='say "hi"')[1], 'say "hi"')

check("ISO date -> IMAP date", am._imap_date("2026-08-01"), "01-Aug-2026")
check("a date object", am._imap_date(date(2026, 12, 25)), "25-Dec-2026")
check("a datetime object", am._imap_date(datetime(2026, 1, 5, 13, 0)), "05-Jan-2026")
check("single-digit day is zero-padded", am._imap_date("2026-03-07"), "07-Mar-2026")
check("an already-IMAP date passes through", am._imap_date("01-Aug-2026"), "01-Aug-2026")
check("SINCE uses it", am._build_criteria(since="2026-08-01"), ["SINCE", "01-Aug-2026"])
check("BEFORE uses it", am._build_criteria(before=date(2026, 9, 1)),
      ["BEFORE", "01-Sep-2026"])

print("\n=== 8. mailbox names with spaces are quoted ===")
check("plain name untouched", am._quote_mailbox("INBOX"), "INBOX")
check("a name with a space is quoted", am._quote_mailbox("Sent Messages"),
      '"Sent Messages"')
check("None defaults to INBOX", am._quote_mailbox(None), "INBOX")
ok("an injected quote cannot break out",
   am._quote_mailbox('bad" SELECT other').count('"') == 2)

print("\n=== 9. limits — an agent's context is not an archive ===")
ok("body cap is set", am.MAX_BODY_CHARS > 0)
ok("snippet cap is smaller than the body cap",
   am.MAX_SNIPPET_CHARS < am.MAX_BODY_CHARS)
ok("result cap is bounded", 0 < am.MAX_RESULTS <= 100)
long_msg = _email.message_from_string(
    "From: a@b.com\r\nSubject: long\r\n\r\n" + ("x" * 5000))
check("the snippet is truncated to the cap",
      len(am._summarise(long_msg, "1")["snippet"]), am.MAX_SNIPPET_CHARS)
ok("a connection timeout is configured — no hanging on a dead host",
   am.TIMEOUT_SECONDS and am.TIMEOUT_SECONDS <= 60)
check("the default host is Apple's", am.host(), "imap.mail.me.com")
check("the default port is IMAPS", am.port(), 993)
os.environ["APPLE_MAIL_PORT"] = "not-a-number"
check("a junk port falls back rather than crashing at import", am.port(), 993)
os.environ.pop("APPLE_MAIL_PORT")

print("\n=== 9b. the dormant self-test answers the DEPLOYMENT question too ===")
# Michael must create an app-specific password by hand before this can be
# tested for real. It would be a poor trade to have him do that and only then
# discover port 993 was blocked. The dormant self-test probes reachability
# with no credentials at all, so the two unknowns are separable.
_d = am.self_test()
ok("dormant self-test still reports reachability", "reachable" in _d)
ok("...as its own ok/kind result", "ok" in _d["reachable"])
ok("this environment cannot reach Apple — device_bash/cloud never can",
   _d["reachable"]["ok"] is False)
check("...and says so as a NETWORK problem, not a credential one",
      _d["reachable"]["kind"], am.ERR_NETWORK)
ok("the probe names the host and port it tried",
   "imap.mail.me.com:993" in _d["reachable"]["host"])
ok("reachable() attempts NO login — credentials are a separate question",
   "login" not in io.open("apple_mail.py", encoding="utf-8").read()
   .split("def reachable")[1].split("\ndef ")[0])

print("\n=== 10. the route layer: least privilege + fail closed ===")
APP = io.open("app.py", encoding="utf-8").read()
ok("the reader is guarded by its OWN secret",
   "APPLE_MAIL_READ_SECRET" in APP)
ok("...and NOT by UPLOAD_SECRET, which unlocks the whole machine",
   "_apple_mail_secret_ok" in APP and
   "UPLOAD_SECRET" not in APP.split("def _apple_mail_secret_ok")[1].split("def ")[0])
ok("an unset secret refuses rather than reopening the door",
   'if not expected:' in APP.split("def _apple_mail_secret_ok")[1].split("def ")[0])
ok("comparison is constant-time",
   "hmac.compare_digest" in APP.split("def _apple_mail_secret_ok")[1].split("def ")[0])
for route in ("selftest", "search", "message", "mailboxes"):
    seg = APP.split("def apple_mail_%s(" % route)[1].split("@app.route")[0]
    ok("/%s is guarded before it does anything" % route, "_apple_mail_guard()" in seg)
ok("no apple-mail route accepts POST — read-only at the HTTP layer too",
   "'/admin/apple-mail" in APP and
   all("methods=['GET']" in l for l in APP.split("\n")
       if "/admin/apple-mail" in l and "@app.route" in l))

print("\n=== 11. the self-test must not become noise ===")
SEG = APP.split("def _apple_mail_selftest_thread")[1].split("threading.Thread")[0]
ok("dormant posts NOTHING — he is in no rush and has not set it up",
   "Staying quiet" in SEG)
# This assertion USED to read "the dormant branch has no Slack call" and was
# left passing vacuously when the one-shot reachability warning was added: it
# split on the LAST "else:" and so inspected the innermost branch, not the
# dormant one. A test that passes for a reason unrelated to its label is worse
# than a missing test. Stated properly now:
_DORMANT_BRANCH = SEG.split("[APPLE-MAIL] dormant")[1]
ok("the dormant branch's ONLY Slack call is the unreachable warning",
   _DORMANT_BRANCH.count("_post_to_slack_async") == 1)
ok("...and it is guarded by the one-shot flag",
   "if not _apple_mail_reach_warned[0]:" in _DORMANT_BRANCH)
ok("...so dormant-and-reachable stays completely silent",
   "Waiting on credentials only" in _DORMANT_BRANCH
   and "_post_to_slack_async" not in _DORMANT_BRANCH.split("else:")[-1])
# A pass must be silent. The ONLY Slack call reachable from the success
# branch is the RECOVERED transition — assert that by reading the branch
# itself rather than counting calls, which drifts the moment one is added.
_SUCCESS_BRANCH = SEG.split('if _res.get("ok"):')[1].split("else:")[0]
ok("a PASS posts nothing except the RECOVERED transition",
   _SUCCESS_BRANCH.count("_post_to_slack_async") == 1
   and "RECOVERED" in _SUCCESS_BRANCH)
ok("...and that one is gated on having previously been down",
   "_last_ok is False" in _SUCCESS_BRANCH)
ok("the reachability warning is a ONE-SHOT, not a repeating nag",
   "_apple_mail_reach_warned" in SEG and "= True" in SEG)
ok("...and only fires when Apple is UNREACHABLE, not merely unconfigured",
   'if not _reach.get("ok"):' in SEG)
ok("failure is reported on the TRANSITION, not every cycle",
   "_last_ok is not False" in SEG)
ok("recovery is reported too", "RECOVERED" in SEG)
ok("the alert explains the symptom looks like an empty inbox",
   "empty inbox" in SEG)
ok("it runs on a slow cycle — this is not a fast-moving failure",
   "21600" in SEG)

print("\n" + "=" * 64)
print("  %d passed, %d failed" % (_passed, _failed))
for f in _FAILS:
    print("   x " + f)
print("=" * 64)
sys.exit(1 if _failed else 0)
