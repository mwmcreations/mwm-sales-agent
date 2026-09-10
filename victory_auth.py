"""victory_auth.py — Phase 2: the door.

Victory staff are never going to hold an admin secret, so Phase 1's
fail-closed admin gate was always a placeholder. This is the real one: a
sign-in link emailed to an address at a domain we trust.

WHY A LINK AND NOT A PASSWORD
    We hold no passwords, so we cannot leak any, and there is nothing for a
    school director to forget or reuse. Control of a @victoryma.com mailbox IS
    the credential — which is exactly the permission model we want, and Victory
    already administers it. Nothing to provision on our side.

THE RULES THIS FILE ENFORCES
    * Only addresses at an allowed domain are ever sent a link.
    * A link is single-use and short-lived.
    * Tokens are stored HASHED. Someone reading the table gets no working link.
    * Comparison is constant time.
    * A request for a link always answers the same way, whether or not the
      address is known — otherwise the form becomes a way to enumerate who
      works at Victory.
    * A signed-in person who has not been given a role sees NOTHING. Access is
      granted by Michael, never inferred from an email address.

Everything here is pure: no Flask, no database, no network. That is what makes
it testable, and this is the file where a mistake is expensive.
"""
import re
import hmac
import time
import base64
import hashlib
import secrets

# ── who may ask for a link ─────────────────────────────────────────────────
# victoryma.com is the client. mwmcreations.com is us. Nothing else, ever —
# and note this only decides who may RECEIVE a link, not what they can see.
ALLOWED_DOMAINS = ("victoryma.com", "mwmcreations.com")
CLIENT_DOMAIN = "victoryma.com"
HOME_DOMAIN = "mwmcreations.com"

# Roles. 'pending' is the deliberate default for a Victory address we have not
# been told about: they can sign in, and they see nothing until Michael says
# otherwise. Access is a decision, not a side effect of owning a mailbox.
ROLE_MWM = "mwm"          # us — everything
ROLE_HQ = "hq"            # Victory HQ — everything Victory
ROLE_SCHOOL = "school"    # one school — its own material and the convention
ROLE_PENDING = "pending"  # signed in, granted nothing
ROLES = (ROLE_MWM, ROLE_HQ, ROLE_SCHOOL, ROLE_PENDING)

CAN_SEARCH = (ROLE_MWM, ROLE_HQ, ROLE_SCHOOL)

LINK_TTL_SECONDS = 15 * 60          # a sign-in link
SESSION_TTL_SECONDS = 14 * 24 * 3600  # a signed-in session

# Rate limits, per window, so the form cannot be used to mailbomb anyone.
LINK_MAX_PER_EMAIL = 5
LINK_MAX_PER_IP = 15
LINK_WINDOW_SECONDS = 3600

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── addresses ──────────────────────────────────────────────────────────────
def normalize_email(raw):
    """Lowercase and trim. Returns '' for anything that is not an address.

    Deliberately does NOT strip +tags or dots: those are Gmail conventions and
    treating 'a.b@victoryma.com' as 'ab@victoryma.com' would silently merge two
    people who may be two people.
    """
    e = (raw or "").strip().lower()
    if not _EMAIL_RE.match(e):
        return ""
    return e


def domain_of(email):
    e = normalize_email(email)
    return e.split("@", 1)[1] if e else ""


def is_allowed(email):
    """May this address be sent a sign-in link at all?"""
    return domain_of(email) in ALLOWED_DOMAINS


def default_role(email):
    """The role an address gets when we have never seen it before.

    Ours is trusted. Victory's is admitted but empty-handed.
    """
    d = domain_of(email)
    if d == HOME_DOMAIN:
        return ROLE_MWM
    if d == CLIENT_DOMAIN:
        return ROLE_PENDING
    return ""


def can_search(role):
    return role in CAN_SEARCH


# ── sign-in tokens ─────────────────────────────────────────────────────────
def new_token():
    """A fresh sign-in token. Returns (token, token_hash).

    The token goes in the email and is never stored. The hash is what the
    database holds, so a dump of vi_magic_link yields nothing usable.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token):
    return hashlib.sha256(("vi-magic-link:" + (token or "")).encode("utf-8")).hexdigest()


def token_matches(token, stored_hash):
    """Constant-time comparison, so timing cannot be used to guess a token."""
    return hmac.compare_digest(hash_token(token), str(stored_hash or ""))


def link_expired(issued_at, now=None, ttl=LINK_TTL_SECONDS):
    now = time.time() if now is None else now
    return (now - float(issued_at or 0)) > ttl


# ── sessions ───────────────────────────────────────────────────────────────
# A session is the signed string "email|role|school|issued_at". No database
# read is needed to trust it, and nothing secret travels in it.
_SEP = "|"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(txt):
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def sign_session(email, role, school, secret, issued_at=None):
    """Build a signed session value. Returns '' when there is no secret.

    Failing closed matters here: an unsigned session would be a session anyone
    could write for themselves.
    """
    if not secret:
        return ""
    email = normalize_email(email)
    if not email or role not in ROLES:
        return ""
    issued_at = int(time.time() if issued_at is None else issued_at)
    payload = _SEP.join([email, role, str(school or ""), str(issued_at)])
    body = _b64(payload.encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                   hashlib.sha256).hexdigest()[:32]
    return body + "." + sig


def verify_session(value, secret, now=None, ttl=SESSION_TTL_SECONDS):
    """Signed value -> {email, role, school, issued_at}, or None.

    Returns None for anything wrong: no secret, wrong shape, bad signature,
    expired, unknown role. Never raises — a malformed cookie is a normal event,
    not an error, and it must not be able to take a request down.
    """
    if not secret or not value or "." not in str(value):
        return None
    try:
        body, sig = str(value).rsplit(".", 1)
        expect = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                          hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        parts = _unb64(body).decode("utf-8").split(_SEP)
        if len(parts) != 4:
            return None
        email, role, school, issued = parts
        if role not in ROLES:
            return None
        issued_at = int(issued)
        now = time.time() if now is None else now
        if now - issued_at > ttl:
            return None
        if now + 300 < issued_at:      # issued in the future: a forged clock
            return None
        return {"email": email, "role": role,
                "school": school or "", "issued_at": issued_at}
    except Exception:
        return None


# ── rate limiting ──────────────────────────────────────────────────────────
class RateLimiter(object):
    """A fixed-window counter, in memory.

    Deliberately simple and deliberately per-process: it exists to stop the
    sign-in form being used to mailbomb someone, not to be a distributed quota.
    Worst case with several workers, the effective limit is a small multiple of
    the configured one, which is still far below abuse.
    """

    def __init__(self, window=LINK_WINDOW_SECONDS):
        self.window = window
        self._hits = {}

    def _prune(self, key, now):
        cutoff = now - self.window
        kept = [t for t in self._hits.get(key, ()) if t > cutoff]
        if kept:
            self._hits[key] = kept
        else:
            self._hits.pop(key, None)
        return kept

    def allow(self, key, limit, now=None):
        """Record an attempt. True if it is within the limit."""
        if not key:
            return True
        now = time.time() if now is None else now
        kept = self._prune(key, now)
        if len(kept) >= limit:
            return False
        self._hits.setdefault(key, []).append(now)
        return True

    def count(self, key, now=None):
        return len(self._prune(key, time.time() if now is None else now))

    def reset(self):
        self._hits.clear()


# ── what a link email says ─────────────────────────────────────────────────
LINK_SUBJECT = "Your Victory Intelligence sign-in link"


def link_email_text(url, minutes=None):
    """Plain text. Short on purpose: a login mail that reads like marketing is
    a login mail people learn to ignore."""
    minutes = int((LINK_TTL_SECONDS if minutes is None else minutes) // 60)
    return (
        "Here is your sign-in link for Victory Intelligence.\n\n"
        "%s\n\n"
        "It works once and expires in %d minutes.\n\n"
        "If you did not ask for this, you can ignore it — the link is useless "
        "without this mailbox.\n\n"
        "MWM Creations & Studios\n" % (url, minutes)
    )


def link_email_html(url, minutes=None):
    minutes = int((LINK_TTL_SECONDS if minutes is None else minutes) // 60)
    return (
        '<div style="font:16px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,'
        'Helvetica,Arial,sans-serif;color:#14171a;max-width:520px">'
        '<p>Here is your sign-in link for <strong>Victory Intelligence</strong>.</p>'
        '<p style="margin:26px 0"><a href="%s" '
        'style="background:#14171a;color:#fff;text-decoration:none;'
        'padding:13px 22px;border-radius:3px;display:inline-block;'
        'font-weight:600">Sign in</a></p>'
        '<p style="color:#767d85;font-size:14px">It works once and expires in '
        '%d minutes. If you did not ask for this, you can ignore it — the link '
        'is useless without this mailbox.</p>'
        '<p style="color:#767d85;font-size:13px;border-top:1px solid #e2e5e9;'
        'padding-top:14px;margin-top:26px">MWM Creations &amp; Studios</p>'
        '</div>' % (url, minutes)
    )
