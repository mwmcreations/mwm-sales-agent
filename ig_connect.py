"""Patch #243 - connect @mwm.creations to the app with Business Login for Instagram.

Why: the IG token only carries the DM permission. ERIC's publisher needs
instagram_business_content_publish + instagram_business_manage_insights, and
the new token must ALSO keep instagram_business_manage_messages or Maya's DMs
stop. Nobody copies or pastes a token: Michael opens /admin/ig-connect, signs
in on Instagram's own page, taps Allow, and the server swaps the token itself.

Pure helpers here (no network, no Flask) so the gate can test them. The routes
live in app.py. Safety rules this module enforces:
  * the state nonce is single-use and expires (STATE_TTL_S);
  * a token missing ANY required scope is refused - the old token stays;
  * a token for a different Instagram account is refused - the old token stays.
"""
import hmac
import secrets
import time
from urllib.parse import urlencode

IG_APP_ID_DEFAULT = "1673074373983477"          # "MWM Messaging-IG" (public id, not a secret)
CALLBACK_PATH = "/auth/instagram/callback"
# Meta matches the redirect URI byte for byte; RAILWAY_PUBLIC_DOMAIN is the custom
# VI domain, so the registered Railway origin is pinned here (env can override).
REDIRECT_BASE_DEFAULT = "https://mwm-sales-agent-production.up.railway.app"
AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
CODE_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
STATE_TTL_S = 900
STATE_PG_KEY = "ig_oauth_state"
SCOPES_PG_KEY = "ig_token_scopes"
EXPECTED_USERNAME_DEFAULT = "mwm.creations"

REQUIRED_SCOPES = (
    "instagram_business_basic",
    "instagram_business_manage_messages",       # Maya's DMs - must never be dropped
    "instagram_business_content_publish",       # ERIC's publisher
    "instagram_business_manage_insights",       # ERIC's Monday report
)


def new_state(now=None):
    return {"nonce": secrets.token_urlsafe(24), "at": float(now if now is not None else time.time())}


def state_ok(stored, got, now=None):
    """True only for the nonce we issued, inside the TTL."""
    if not isinstance(stored, dict) or not got or not stored.get("nonce"):
        return False
    try:
        age = float(now if now is not None else time.time()) - float(stored.get("at", 0))
    except (TypeError, ValueError):
        return False
    if age < 0 or age > STATE_TTL_S:
        return False
    return hmac.compare_digest(str(stored["nonce"]), str(got))


def authorize_url(app_id, redirect_uri, nonce):
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(REQUIRED_SCOPES),
        "state": nonce,
        "enable_fb_login": "0",
        "force_reauth": "true",
    }
    return AUTHORIZE_URL + "?" + urlencode(params)


def _as_list(perms):
    if perms is None:
        return []
    if isinstance(perms, str):
        return [p.strip() for p in perms.split(",") if p.strip()]
    if isinstance(perms, (list, tuple, set)):
        return [str(p).strip() for p in perms if str(p).strip()]
    return []


def parse_code_response(data):
    """Instagram has answered both {"data":[{...}]} and a flat object.
    Returns (short_token, user_id, permissions_list); token None on failure."""
    if not isinstance(data, dict):
        return None, None, []
    row = data
    if isinstance(data.get("data"), list) and data["data"]:
        row = data["data"][0] if isinstance(data["data"][0], dict) else {}
    tok = row.get("access_token")
    if not tok:
        return None, None, []
    uid = row.get("user_id")
    return tok, (str(uid) if uid is not None else None), _as_list(row.get("permissions"))


def missing_scopes(perms):
    have = set(_as_list(perms))
    return [s for s in REQUIRED_SCOPES if s not in have]


def same_account(old_me, new_me, expected_username=EXPECTED_USERNAME_DEFAULT):
    """old_me/new_me: dicts from graph.instagram.com/me?fields=user_id,username
    (empty dict when the call failed). Returns (ok, reason)."""
    new_me = new_me or {}
    old_me = old_me or {}
    if not new_me.get("user_id") and not new_me.get("username"):
        return False, "could not read the new token's account"
    if old_me.get("user_id"):
        if str(old_me["user_id"]) == str(new_me.get("user_id")):
            return True, "same account as the current token"
        return False, "a different Instagram account than the one Maya uses"
    want = (expected_username or "").lstrip("@").lower()
    got = str(new_me.get("username") or "").lstrip("@").lower()
    if want and got == want:
        return True, "matches @" + want
    return False, "account @%s is not @%s" % (got or "?", want or "?")


def result_page(title, lines):
    """Tiny HTML page for Michael's browser. Never pass a token in here."""
    import html as _h
    body = "".join("<p>%s</p>" % _h.escape(str(x)) for x in lines)
    return ("<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s</title><body style='font-family:-apple-system,system-ui,sans-serif;"
            "max-width:560px;margin:40px auto;padding:0 16px;line-height:1.5'>"
            "<h2>%s</h2>%s</body>" % (_h.escape(title), _h.escape(title), body))
