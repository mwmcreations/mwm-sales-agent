"""Standing contacts — the people who must be on a client's mail and invites.

PATCH #115. One map, two rails.

Michael, 2 Sep 2026, about studio client Luzia Costa: "add
Nicole.formore@gmail.com in all e-mails that should be sent to our studio
client Luzia. keep the main e-mail and add this one. for all e-mail
communication." He then added the calendar invites to the same instruction.

Patch #114 put this map inside `susan_gmail.send_gmail`, which is the right
home for MAIL and the wrong home for everything else — a calendar invite is
sent by Google, not by our sender, and would have quietly missed the rule.
So the map moves here, where the mail rail and the event rail can both read
the SAME answer. Two lists that can disagree eventually do.

Keys are recipient addresses; values are the people who ride along with them.
Matching is case- and whitespace-insensitive.

`MWM_STANDING_CONTACTS` (JSON: {"client@x.com": ["copy@y.com"]}) is merged OVER
the built-ins, so the next pair is an env edit rather than a deploy. A
malformed value is ignored and logged: a typo in an env var must never
silently drop the copies that are already correct.
"""

import json
import os
import re

BUILTIN = {
    # Luzia Costa (Studio Package) — Nicole on every email and every invite.
    # Michael, 2 Sep 2026.
    "luziahcosta@hotmail.com": ["Nicole.formore@gmail.com"],
}

ENV_VAR = "MWM_STANDING_CONTACTS"

# Back-compat: #114 shipped reading SUSAN_ALWAYS_CC. Both are honoured, and
# the newer name wins, so a value set during the #114 deploy keeps working.
LEGACY_ENV_VAR = "SUSAN_ALWAYS_CC"


def _clean(value):
    return str(value or "").strip()


def _merge(out, parsed, where):
    if not isinstance(parsed, dict):
        raise ValueError("{} must be a JSON object".format(where))
    for key, val in parsed.items():
        vals = val if isinstance(val, (list, tuple)) else re.split(r"[,;]+", _clean(val))
        out[_clean(key).lower()] = [_clean(a) for a in vals if _clean(a)]


def standing_map():
    """{recipient -> [addresses that always ride along]}, keys lowercased."""
    out = {}
    for key, val in BUILTIN.items():
        out[_clean(key).lower()] = [_clean(a) for a in val if _clean(a)]
    for var in (LEGACY_ENV_VAR, ENV_VAR):
        raw = _clean(os.getenv(var, ""))
        if not raw:
            continue
        try:
            _merge(out, json.loads(raw), var)
        except Exception as exc:
            print("[STANDING] {} ignored — {}".format(var, str(exc)[:120]))
    return {k: v for k, v in out.items() if k and v}


def extras_for(addresses):
    """Everyone who must ride along with `addresses`, minus anyone already there.

    Order is stable and duplicates are impossible: an address already present
    in any casing is never added again.
    """
    mapping = standing_map()
    if not mapping:
        return []
    present = [_clean(a) for a in (addresses or []) if _clean(a)]
    seen = {a.lower() for a in present}
    extras = []
    for addr in present:
        for extra in mapping.get(addr.lower(), []):
            if extra.lower() not in seen:
                seen.add(extra.lower())
                extras.append(extra)
    return extras
