"""
client_roster.py — PATCH #111. Know who already pays us.

WHAT THIS FIXES
───────────────
Patch #110 stopped announcing a paying client as a new lead, but it built its
picture of "who is a client" out of lead_data — that is, only the clients this
machine personally watched convert. Anyone who bought through Stripe, or was
created straight in the portal, or signed up before the machine existed, was
invisible to it. On 29 Aug that was luck rather than design: Jaysee Soto
happened to be a record the machine had seen.

Michael, 29 Aug: "sometimes on other clients, they mark us on Instagram, and
because of the bot, it always kinda try to schedule a studio visit even though
they are already clients. It's kinda awkward."

The authoritative list has existed the whole time — the studio portal's client
table, already reachable through studio_package.wp_list_clients(). This holds
it in memory, refreshes it on a timer, and hands it to known_client.

TWO DESIGN CHOICES WORTH DEFENDING
──────────────────────────────────
1. A FAILED REFRESH KEEPS THE OLD ROSTER. WordPress being briefly unreachable
   must not make fourteen clients look like strangers for fifteen minutes.
   Staleness is nearly harmless here — people do not stop being clients on a
   short timescale — while emptiness is exactly the bug we are fixing.

2. AN EXPIRED CONTRACT STAYS ON THE ROSTER, MARKED EXPIRED. Someone whose term
   ran out is a renewal conversation, not a stranger who has never seen the
   room. Selling to them is right; pitching them a first-time studio visit is
   not. Only the caller can tell those apart, so the distinction is preserved
   rather than resolved here.
"""

import threading
import time

import known_client as _kc

DEFAULT_TTL_S = 900.0   # 15 minutes


def normalize_row(row):
    """One portal row -> the shape the rest of the machine reads."""
    if not isinstance(row, dict):
        return None
    email = _kc.normalize_email(row.get("email"))
    name = str(row.get("name") or "").strip()
    if not email and not name:
        return None

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    total = _num(row.get("contract_hours"))
    used = _num(row.get("hours_used"))
    active = str(row.get("active", "1")).strip() not in ("0", "", "false", "False")
    return {
        "id": row.get("id"),
        "name": name,
        "email": email,
        "phone": str(row.get("phone") or ""),
        "business": str(row.get("company") or row.get("business") or ""),
        "package": str(row.get("package_name") or "").strip(),
        "contract_hours": total,
        "hours_used": used,
        "hours_left": max(0.0, total - used),
        "contract_end": str(row.get("contract_end_date") or "").strip(),
        "active": active,
        # Every roster entry is a client by definition — it is the paying-
        # clients table. Saying so explicitly lets known_client index it
        # without having to infer anything.
        "outcome": "Won",
    }


class Roster:
    """Thread-safe cache of the portal's client list."""

    def __init__(self, ttl_s=DEFAULT_TTL_S):
        self._lock = threading.Lock()
        self._rows = []
        self._index = _kc.build_client_index([])
        self._fetched_at = 0.0
        self._last_error = ""
        self._ttl = float(ttl_s)

    # ── state ──────────────────────────────────────────────────────────
    def age_s(self, now=None):
        if not self._fetched_at:
            return None
        return (now if now is not None else time.time()) - self._fetched_at

    def is_stale(self, now=None):
        age = self.age_s(now)
        return age is None or age > self._ttl

    def rows(self):
        with self._lock:
            return list(self._rows)

    def index(self):
        with self._lock:
            return self._index

    # ── refresh ────────────────────────────────────────────────────────
    def refresh(self, fetch, now=None):
        """fetch() -> list of portal rows, or None on failure.

        Returns (ok, count, reason). On failure the previous roster is kept —
        see design note 2 at the top of this file."""
        try:
            raw = fetch()
        except Exception as e:
            with self._lock:
                self._last_error = "fetch raised: %s" % e
            return False, len(self._rows), "exception"
        if raw is None:
            with self._lock:
                self._last_error = "portal unreachable"
            return False, len(self._rows), "unreachable"
        if not isinstance(raw, (list, tuple)):
            with self._lock:
                self._last_error = "unexpected payload type %s" % type(raw).__name__
            return False, len(self._rows), "bad_payload"

        rows = [r for r in (normalize_row(x) for x in raw) if r]
        if not rows and self._rows:
            # An empty list from a healthy-looking call is far more likely to be
            # a broken query than fourteen clients resigning at once.
            with self._lock:
                self._last_error = "refused an empty roster over %d held" % len(self._rows)
            return False, len(self._rows), "empty_refused"

        index = _kc.build_client_index(rows)
        with self._lock:
            self._rows = rows
            self._index = index
            self._fetched_at = (now if now is not None else time.time())
            self._last_error = ""
        return True, len(rows), "ok"

    # ── lookup ─────────────────────────────────────────────────────────
    def find(self, candidate):
        """(matched, reason, row_or_None) for one lead-shaped dict."""
        rows = self.rows()
        if not rows:
            return False, "roster_empty", None
        matched, reason = _kc.match_known_client(candidate, self.index())
        if not matched:
            return False, reason, None
        for row in rows:
            hit, _ = _kc.match_known_client(candidate, _kc.build_client_index([row]))
            if hit:
                return True, reason, row
        # Matched the combined index but no single row owns it. Report the
        # match without a record rather than guessing which client it was.
        return True, reason, None

    def summary(self, now=None):
        with self._lock:
            active = sum(1 for r in self._rows if r.get("active"))
            return {
                "clients": len(self._rows),
                "active": active,
                "expired": len(self._rows) - active,
                "age_s": None if not self._fetched_at
                         else round((now if now is not None else time.time())
                                    - self._fetched_at, 1),
                "stale": self.is_stale(now),
                "last_error": self._last_error,
            }
