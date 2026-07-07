"""S8.3 — re-engagement send guard (Jul 6 incident: duplicate T7 wave).

Root cause of the Jul 6 duplicate blast: the checker sent FIRST and stamped
after ("send -> if ok: update row"), and update_reengagement_row swallowed
Sheets batchUpdate failures as prints. A send that succeeded whose stamp
write silently failed looked un-sent on the next 25-min poll -> re-send to
the same lead (the 16:38 / 17:04 pair, one poll cycle apart).

This module inverts the order and makes every failure mode fail-SAFE
(worst case = a missed touch, never a duplicate send):

  1. claim(key)            in-process idempotency lock per (phone, stage)
  2. write_pending()       stamp "<ts> PENDING" BEFORE the send; if this
                           write does not land, the send is BLOCKED
  3. send()
  4a. success -> finalize() best-effort (PENDING already blocks re-send,
                 so a failed finalize is cosmetic)
  4b. failure -> rollback() clears the stamp so the touch retries next
                 cycle; if rollback ALSO fails the PENDING stamp stays
                 (no retry — fail-safe) and the error bus is told

Pure stdlib; no Google/Meta imports so it unit-tests anywhere.
"""

import threading

CLAIM_TTL_SECONDS = 24 * 3600  # mirrors the S6.1 one-touch-per-24h throttle


class ReengagementGuard:
    """In-process idempotency claims per (lead, stage)."""

    def __init__(self, ttl_seconds=CLAIM_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._claims = {}
        self._lock = threading.Lock()

    def claim(self, key, now_ts):
        """Try to claim key at epoch-seconds now_ts.
        Returns True if claimed; False if an unexpired claim exists."""
        with self._lock:
            prev = self._claims.get(key)
            if prev is not None and (now_ts - prev) < self._ttl:
                return False
            self._claims[key] = now_ts
            # opportunistic prune so the dict can't grow unbounded
            if len(self._claims) > 5000:
                cutoff = now_ts - self._ttl
                for k in [k for k, t in self._claims.items() if t < cutoff]:
                    del self._claims[k]
            return True

    def release(self, key):
        with self._lock:
            self._claims.pop(key, None)


def guarded_send(write_pending, send, finalize, rollback, report):
    """Run one stamp-before-send touch. All args are 0-arg callables except
    report(msg, exc).

    Returns one of:
      "blocked"        pre-send stamp write failed -> send NOT attempted
      "sent"           send succeeded (finalize best-effort)
      "failed"         send failed, stamp rolled back -> retry next cycle
      "failed-noretry" send failed AND rollback failed -> PENDING stamp
                       retained on purpose; touch will NOT retry (fail-safe)
    """
    try:
        write_pending()
    except Exception as e:
        report("pre-send stamp write failed — send BLOCKED", e)
        return "blocked"

    ok = False
    try:
        ok = bool(send())
    except Exception as e:
        report("send raised", e)
        ok = False

    if ok:
        try:
            finalize()
        except Exception:
            pass  # PENDING stamp already blocks re-send
        return "sent"

    try:
        rollback()
        return "failed"
    except Exception as e:
        report("rollback failed — PENDING stamp retained, touch will not retry (fail-safe)", e)
        return "failed-noretry"
