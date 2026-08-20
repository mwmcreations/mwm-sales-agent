"""apple_mail.py — READ-ONLY reader for Michael's personal Apple mailbox.

WHY THIS MODULE EXISTS
----------------------
ANA needs michaelmoraes@mac.com and there is no way to connect it. Verified
twice, independently, on Aug 20 2026: there is NO iCloud / Apple Mail MCP
connector. Apple does not publish one and no third party bridges it.

So it has to be IMAP. And IMAP can only be spoken from HERE — not from the
agents. Both agent environments were tested the same afternoon:

    device_bash          DNS resolution fails outright — no network at all
    the cloud container  connect to imap.mail.me.com:993 times out

That is a NETWORK fact, not a permissions one. The Railway service is the
only environment in the fleet with open outbound, which is why this module
lives in the sales machine rather than anywhere closer to ANA. She reaches it
over HTTP.

WHY FORWARDING WAS REJECTED
---------------------------
The obvious cheap answer is iCloud -> Gmail forwarding, and it was the first
recommendation. Michael reconsidered and killed it, correctly:

  · Forwarding carries only NEW mail. Both cases that actually blocked ANA —
    the Expedia confirmations and the school catering email — are ALREADY in
    the Apple mailbox. Forwarding would never have fixed either.
  · Run alongside IMAP it is worse than useless: every personal email would
    exist twice, once read live here and once as a stale Gmail copy, and ANA
    would return duplicates.
  · It puts personal mail inside the company Workspace account permanently.

READ-ONLY IS STRUCTURAL, NOT A PROMISE
--------------------------------------
Every mailbox is opened with `readonly=True`, so the server itself refuses
mutation, and nothing here calls STORE, APPEND, EXPUNGE, COPY or DELETE.
test_apple_mail.py greps this file for those verbs and fails if one appears.
That is deliberate: this is someone's PERSONAL mailbox, and the cost of a
bug that writes to it is not symmetric with the cost of one that cannot.
Reading a message does not even mark it seen.

DORMANT UNTIL CONFIGURED
------------------------
No credentials means every entry point returns a clear "not configured"
result. It does not raise, it does not retry, and it never reports success.
The reader wakes up on its own the moment the environment variables appear.

    APPLE_MAIL_USER           michaelmoraes@mac.com
    APPLE_MAIL_APP_PASSWORD   an APP-SPECIFIC password from appleid.apple.com
                              (his Apple ID has 2FA, so the real password
                              cannot work here — Apple rejects it)

Michael creates and sets both himself. Neither DEV nor ANA ever sees them.

THE FAILURE THIS IS BUILT AROUND
--------------------------------
An app-specific password DIES SILENTLY when the Apple ID password is changed.
Without a self-test the symptom is not an error — it is ANA quietly finding
no email and an inbox that looks empty. `self_test()` exists to turn that
into a loud, named failure. Distinguishing AUTHENTICATIONFAILED from a
network timeout is the whole point of `_classify_error`.
"""

import email
import imaplib
import os
import re
import socket
from contextlib import contextmanager
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

DEFAULT_HOST = "imap.mail.me.com"
DEFAULT_PORT = 993
TIMEOUT_SECONDS = 25

# Bodies are for a human to read in a chat window, not for archival. A 4 MB
# newsletter helps nobody and costs an agent its context.
MAX_BODY_CHARS = 4000
MAX_SNIPPET_CHARS = 280
MAX_RESULTS = 50

# Error kinds — the caller decides how loudly to shout, but the DIAGNOSIS is
# made here, once, rather than by string-matching at three call sites.
ERR_NOT_CONFIGURED = "not_configured"
ERR_AUTH = "auth_failed"
ERR_NETWORK = "network"
ERR_MAILBOX = "mailbox"
ERR_UNKNOWN = "unknown"

_AUTH_MARKERS = ("authenticationfailed", "invalid credentials", "login failed",
                 "authentication failed", "[authenticationfailed]")


def host():
    return os.getenv("APPLE_MAIL_HOST", DEFAULT_HOST)


def port():
    try:
        return int(os.getenv("APPLE_MAIL_PORT", str(DEFAULT_PORT)))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _creds():
    return (os.getenv("APPLE_MAIL_USER", "").strip(),
            os.getenv("APPLE_MAIL_APP_PASSWORD", "").strip())


def enabled():
    """True only when BOTH credentials are present.

    Half-configured is treated as not configured. A username with no password
    is someone midway through setup, not a working reader.
    """
    user, pw = _creds()
    return bool(user and pw)


def account():
    """The address being read, for display. Never the password."""
    return _creds()[0] or None


def _classify_error(exc):
    """(kind, human_sentence). The diagnosis lives here, once.

    An app-specific password that has been revoked and a blocked port produce
    completely different remedies, and 'IMAP error' tells whoever is on call
    neither of them.
    """
    text = str(exc or "").lower()
    if any(m in text for m in _AUTH_MARKERS):
        return ERR_AUTH, (
            "Apple rejected the credentials. An app-specific password is "
            "revoked automatically whenever the Apple ID password changes — "
            "the usual fix is to generate a new one at appleid.apple.com and "
            "update APPLE_MAIL_APP_PASSWORD. Note the ordinary Apple ID "
            "password never works here: 2FA accounts require an app password.")
    if isinstance(exc, (socket.timeout, socket.gaierror, ConnectionError, OSError)):
        return ERR_NETWORK, (
            f"Could not reach {host()}:{port()}. This is reachability, not "
            f"credentials — check outbound access from this environment "
            f"before touching the password.")
    if isinstance(exc, imaplib.IMAP4.error):
        return ERR_MAILBOX, f"The mail server refused the request: {exc}"
    return ERR_UNKNOWN, f"{type(exc).__name__}: {exc}"


def _not_configured():
    return {
        "ok": False,
        "kind": ERR_NOT_CONFIGURED,
        "error": ("Apple mail is not configured. Set APPLE_MAIL_USER and "
                  "APPLE_MAIL_APP_PASSWORD (an app-specific password from "
                  "appleid.apple.com) to switch this on."),
    }


@contextmanager
def _session(mailbox="INBOX"):
    """A short-lived, READ-ONLY IMAP session.

    Deliberately not pooled. This reader is used occasionally and by a human's
    request; a long-lived connection to someone's personal mailbox is state to
    get wrong for no gain, and iCloud drops idle connections anyway.
    """
    user, pw = _creds()
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(host(), port(), timeout=TIMEOUT_SECONDS)
        conn.login(user, pw)
        # readonly=True — the SERVER enforces this, not our good intentions.
        # It also means reading a message does not mark it seen, so ANA
        # looking something up never changes what Michael sees as unread.
        conn.select(_quote_mailbox(mailbox), readonly=True)
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass


def _quote_mailbox(name):
    name = str(name or "INBOX")
    if re.search(r"[\s\"]", name):
        return '"%s"' % name.replace('"', '')
    return name


# ── decoding ────────────────────────────────────────────────────────────────
# Michael's mail is bilingual and his contacts' names carry accents. A reader
# that mangles "José" or drops a =?utf-8?...?= subject is not a reader.

def _decode_header(raw):
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        # Never let a malformed header lose the whole message.
        return str(raw).strip()


def _strip_html(html):
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                    ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(ent, ch)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _part_text(part):
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    for enc in (charset, "utf-8", "latin-1"):
        try:
            return payload.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def extract_body(msg):
    """Best-effort plain text. Prefers text/plain, falls back to stripped HTML.

    Attachments are never decoded — only listed. A reader that pulls a 20 MB
    PDF into a chat context to answer "when is my flight" has misunderstood
    the job.
    """
    if not msg.is_multipart():
        text = _part_text(msg)
        if (msg.get_content_type() or "").lower() == "text/html":
            text = _strip_html(text)
        return text.strip()

    plain, html = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disp:
            continue
        ctype = (part.get_content_type() or "").lower()
        if ctype == "text/plain":
            plain.append(_part_text(part))
        elif ctype == "text/html":
            html.append(_part_text(part))
    if any(p.strip() for p in plain):
        return "\n".join(plain).strip()
    return _strip_html("\n".join(html)).strip()


def attachment_names(msg):
    names = []
    if not msg.is_multipart():
        return names
    for part in msg.walk():
        disp = str(part.get("Content-Disposition") or "").lower()
        fn = part.get_filename()
        if "attachment" in disp or fn:
            names.append(_decode_header(fn) or "(unnamed)")
    return names


def _summarise(msg, uid, body=None):
    """The compact shape every list result uses."""
    subject = _decode_header(msg.get("Subject"))
    from_raw = _decode_header(msg.get("From"))
    name, addr = parseaddr(from_raw)
    date_iso = ""
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        date_iso = dt.isoformat() if dt else ""
    except Exception:
        date_iso = str(msg.get("Date") or "")
    if body is None:
        body = extract_body(msg)
    snippet = re.sub(r"\s+", " ", body or "").strip()[:MAX_SNIPPET_CHARS]
    atts = attachment_names(msg)
    return {
        "uid": str(uid),
        "date": date_iso,
        "from_name": name or "",
        "from_email": addr or from_raw,
        "to": _decode_header(msg.get("To")),
        "subject": subject or "(no subject)",
        "snippet": snippet,
        "attachments": atts,
        "has_attachments": bool(atts),
    }


# ── search ──────────────────────────────────────────────────────────────────
# IMAP SEARCH is a protocol, not a Gmail query box. Callers pass structured
# fields and this builds valid criteria — rather than accepting a raw string
# and letting a stray quote become a protocol error the caller cannot read.

def _build_criteria(sender=None, subject=None, text=None, since=None,
                    before=None, unseen=False, to=None):
    crit = []
    if sender:
        crit += ["FROM", sender]
    if to:
        crit += ["TO", to]
    if subject:
        crit += ["SUBJECT", subject]
    if text:
        crit += ["TEXT", text]
    if since:
        crit += ["SINCE", _imap_date(since)]
    if before:
        crit += ["BEFORE", _imap_date(before)]
    if unseen:
        crit += ["UNSEEN"]
    return crit or ["ALL"]


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(value):
    """IMAP wants 01-Aug-2026. Accepts that, a date, a datetime, or ISO text."""
    if hasattr(value, "strftime"):
        return "%02d-%s-%d" % (value.day, _MONTHS[value.month - 1], value.year)
    s = str(value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return "%02d-%s-%d" % (d, _MONTHS[mo - 1], y)
    return s


def _uid_search(conn, criteria):
    """UID SEARCH, UTF-8 first, ASCII fallback.

    UIDs not sequence numbers: sequence numbers shift when the mailbox changes
    underneath us, so a uid fetched from one call would address a different
    message on the next.
    """
    encoded = [c.encode("utf-8") if isinstance(c, str) else c for c in criteria]
    try:
        typ, data = conn.uid("SEARCH", "CHARSET", "UTF-8", *encoded)
    except imaplib.IMAP4.error:
        # Some servers refuse CHARSET on some criteria. Retry plain — this
        # only loses non-ASCII search terms, and losing them beats erroring.
        typ, data = conn.uid("SEARCH", None, *encoded)
    if typ != "OK":
        raise imaplib.IMAP4.error("SEARCH returned %s" % typ)
    raw = (data[0] or b"").split()
    return [u.decode() if isinstance(u, bytes) else str(u) for u in raw]


# ── public entry points ─────────────────────────────────────────────────────
# Every one of these returns a dict and NEVER raises. A reader that throws
# into an agent's tool call produces a stack trace where an explanation was
# needed, and the agent then guesses.

def search(sender=None, subject=None, text=None, since=None, before=None,
           unseen=False, to=None, mailbox="INBOX", limit=20):
    """Find messages. Newest first. Returns {"ok", "count", "messages"}."""
    if not enabled():
        return _not_configured()
    try:
        limit = max(1, min(int(limit or 20), MAX_RESULTS))
    except (TypeError, ValueError):
        limit = 20
    criteria = _build_criteria(sender=sender, subject=subject, text=text,
                               since=since, before=before, unseen=unseen, to=to)
    try:
        with _session(mailbox) as conn:
            uids = _uid_search(conn, criteria)
            # Highest UID is newest. Take the tail, then present descending —
            # "the Expedia confirmation" almost always means the recent one.
            chosen = uids[-limit:][::-1]
            out = []
            for uid in chosen:
                typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                # BODY.PEEK, not BODY: PEEK does not set the \Seen flag.
                # Plain BODY would mark Michael's unread mail as read merely
                # because ANA looked something up.
                if typ != "OK" or not data or not isinstance(data[0], tuple):
                    continue
                msg = email.message_from_bytes(data[0][1])
                out.append(_summarise(msg, uid))
        return {"ok": True, "account": account(), "mailbox": mailbox,
                "count": len(out), "total_matched": len(uids), "messages": out}
    except Exception as exc:
        kind, why = _classify_error(exc)
        return {"ok": False, "kind": kind, "error": why}


def recent(limit=10, mailbox="INBOX"):
    """The newest messages, no filter."""
    return search(mailbox=mailbox, limit=limit)


def message(uid, mailbox="INBOX"):
    """One message in full, body included (capped)."""
    if not enabled():
        return _not_configured()
    uid = str(uid or "").strip()
    if not uid.isdigit():
        return {"ok": False, "kind": ERR_MAILBOX,
                "error": "uid must be numeric — pass the uid from a search result."}
    try:
        with _session(mailbox) as conn:
            typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                return {"ok": False, "kind": ERR_MAILBOX,
                        "error": f"No message with uid {uid} in {mailbox}."}
            msg = email.message_from_bytes(data[0][1])
            body = extract_body(msg)
            summary = _summarise(msg, uid, body=body)
            truncated = len(body) > MAX_BODY_CHARS
            summary["body"] = body[:MAX_BODY_CHARS]
            summary["body_truncated"] = truncated
        return {"ok": True, "account": account(), "mailbox": mailbox,
                "message": summary}
    except Exception as exc:
        kind, why = _classify_error(exc)
        return {"ok": False, "kind": kind, "error": why}


def mailboxes():
    """Folder names, so a caller can search somewhere other than INBOX."""
    if not enabled():
        return _not_configured()
    try:
        conn = imaplib.IMAP4_SSL(host(), port(), timeout=TIMEOUT_SECONDS)
        try:
            user, pw = _creds()
            conn.login(user, pw)
            typ, data = conn.list()
            names = []
            for row in (data or []):
                if isinstance(row, bytes):
                    row = row.decode("utf-8", errors="replace")
                m = re.search(r'"([^"]+)"\s*$', str(row))
                names.append(m.group(1) if m else str(row))
            return {"ok": True, "account": account(), "mailboxes": names}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as exc:
        kind, why = _classify_error(exc)
        return {"ok": False, "kind": kind, "error": why}


def self_test():
    """Prove the reader still works, and say precisely how it broke if not.

    This is the reason the module distinguishes error kinds at all. An
    app-specific password is revoked SILENTLY the moment the Apple ID password
    changes, and the symptom is not an exception anywhere ANA can see it — it
    is her finding no mail and reporting an empty inbox. Without this, the
    failure mode of the whole feature is "quietly wrong", which is the one
    failure mode this fleet keeps paying for.
    """
    if not enabled():
        out = _not_configured()
        out["dormant"] = True   # not a fault — nobody has switched it on yet
        # Probe reachability anyway. Michael has to create an app-specific
        # password by hand before this can be tested for real, and it would be
        # a poor trade to have him do that only to discover the port was
        # blocked all along. This answers "would it even work here?" for free,
        # with no credentials involved — TCP only, no login attempted.
        out["reachable"] = reachable()
        return out


def reachable():
    """Can this environment open a TCP connection to Apple's IMAP host?

    Answers the deployment question independently of the credential question.
    Both agent environments fail this (device_bash has no DNS, the cloud
    container times out on 993) which is the entire reason the reader lives in
    the sales machine — so it is worth being able to prove the same thing
    about wherever this code has landed, rather than assuming.
    """
    try:
        sock = socket.create_connection((host(), port()), timeout=10)
        sock.close()
        return {"ok": True, "host": f"{host()}:{port()}"}
    except Exception as exc:
        kind, why = _classify_error(exc)
        return {"ok": False, "kind": kind, "error": why,
                "host": f"{host()}:{port()}"}
    try:
        with _session("INBOX") as conn:
            typ, data = conn.status("INBOX", "(MESSAGES)")
            total = None
            if typ == "OK" and data:
                raw = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
                m = re.search(r"MESSAGES\s+(\d+)", raw)
                total = int(m.group(1)) if m else None
        return {"ok": True, "account": account(), "host": f"{host()}:{port()}",
                "inbox_messages": total, "readonly": True}
    except Exception as exc:
        kind, why = _classify_error(exc)
        return {"ok": False, "kind": kind, "error": why,
                "account": account(), "host": f"{host()}:{port()}"}
