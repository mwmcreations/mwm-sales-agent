"""
lead_watch.py — PATCH #128. Nobody was counting the leads.

WHAT HAPPENED
─────────────
Around 03:20 ET on 1 September 2026, eight booked lead records stopped existing.
Nothing alerted. Nothing logged it. The first anyone knew was a health check
noticing the pipeline looked thinner than it had the day before, and by then
there was no way to tell what had gone or why.

On 5 September the mechanism was found: `/webhook-test` accepted an arbitrary
`sender` from an unauthenticated POST, ran the pipeline as that person, and
then called `lead_data.pop(...)` — which leads_db turns into a real DELETE
within 15 seconds. Patch #127 closed it with three locks.

On 8 September we went looking for proof in Railway's logs. They were gone —
a removed deployment keeps its logs for far less time than its entry stays in
the deploy list. **The question is now permanently unanswerable.**

WHY THIS FILE EXISTS
────────────────────
Closing the hole was necessary and is not sufficient. If leads vanished again
tonight — from a bug nobody has found yet, a bad restore, a Postgres incident,
or a path that does not exist today — we would be exactly as blind, and we
would again reach for logs that turn out not to exist.

**Archaeology cannot be made reliable. Noticing can.** This module notices.

DESIGN NOTES
────────────
* Pure logic. No network, no database, no clock, no imports beyond stdlib —
  so the rule can be tested without any of them, the way loop_guard and slots
  are. app.py owns the thread, the alert and the persistence.
* **Alerts on a NET COUNT DROP, not on a missing key.** leads_db._promote can
  rename a lead's key when a better identifier arrives (an Instagram lead who
  finally gives a phone number). That retires one key and creates another, and
  a key-based rule would cry wolf every time it happened. A rename does not
  change the count; a deletion does.
* Synthetic keys are excluded by prefix. The smoke test creates and deletes
  `smoke_test_*` by design, and after #127 it cannot be called anything else.
* Warms up before it judges. lead_data is restored from Postgres over the first
  seconds of a boot, so the earliest samples are legitimately small.
* Says it once. A drop that stays dropped is one message, not one a minute. It
  re-arms when the count recovers, and announces the recovery.
* Fails towards silence on nonsense input, never towards a false accusation.
  Wrongly claiming leads were deleted would burn the alarm's credibility, and
  an alarm nobody believes is worse than no alarm.
"""

OK = "ok"
DROP = "drop"
WARMING = "warming"
RECOVERED = "recovered"

SYNTHETIC_PREFIXES = ("smoke_test_", "test_000", "__probe__")

DEFAULTS = {
    "warmup_samples": 3,   # boot restore is async — do not judge the first ticks
    "min_drop": 1,         # one real lead is a client. There is no safe drop.
    "name_cap": 15,        # how many keys the alert may name before it says "and N more"
}


def _cfg(cfg=None):
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        out.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    return out


def is_synthetic(key):
    """True for keys the machine creates and deletes on purpose."""
    k = str(key or "")
    return any(k.startswith(p) for p in SYNTHETIC_PREFIXES)


def real_keys(mapping):
    """The lead keys that represent an actual person."""
    try:
        return set(k for k in mapping.keys() if not is_synthetic(k))
    except Exception:
        return set()


def new_state():
    return {"keys": set(), "count": 0, "db": None,
            "samples": 0, "alerted": False, "peak": 0}


def observe(state, mapping, db_count=None, cfg=None):
    """One sample. Returns (verdict, detail).

    detail always carries `before`, `after` and `missing` so the caller can
    write an alert that names names instead of reporting a number.
    """
    c = _cfg(cfg)
    if not isinstance(state, dict):
        return OK, {}
    keys = real_keys(mapping)
    prev_keys = state.get("keys") or set()
    before = len(prev_keys)
    after = len(keys)
    db_before = state.get("db")
    detail = {
        "before": before, "after": after,
        "db_before": db_before, "db_after": db_count,
        "missing": sorted(prev_keys - keys)[:c["name_cap"]],
        "missing_total": len(prev_keys - keys),
        "peak": max(state.get("peak", 0), after),
    }

    state["samples"] = state.get("samples", 0) + 1
    warming = state["samples"] <= c["warmup_samples"]

    # A DB count of -1 means leads_db could not answer. Unknown is not zero.
    db_known = isinstance(db_count, int) and db_count >= 0
    db_dropped = (db_known and isinstance(db_before, int) and db_before >= 0
                  and (db_before - db_count) >= c["min_drop"])
    mem_dropped = (before - after) >= c["min_drop"]

    verdict = OK
    if warming:
        verdict = WARMING
    elif mem_dropped or db_dropped:
        verdict = OK if state.get("alerted") else DROP
        state["alerted"] = True
    elif state.get("alerted") and after >= state.get("peak", 0):
        verdict = RECOVERED
        state["alerted"] = False

    state["keys"] = keys
    state["count"] = after
    if db_known:
        state["db"] = db_count
    state["peak"] = detail["peak"]
    return verdict, detail


def describe(detail):
    """One human sentence for Slack. Names the leads, because a number is not
    actionable and a name is."""
    if not isinstance(detail, dict):
        return "lead count changed"
    before = detail.get("before", 0)
    after = detail.get("after", 0)
    lost = before - after
    bits = []
    if lost > 0:
        bits.append("lead_data fell from {} to {} ({} gone)".format(before, after, lost))
    db_b, db_a = detail.get("db_before"), detail.get("db_after")
    if isinstance(db_b, int) and isinstance(db_a, int) and db_b > db_a:
        bits.append("the leads table fell from {} to {}".format(db_b, db_a))
    if not bits:
        bits.append("lead count moved unexpectedly")
    names = detail.get("missing") or []
    if names:
        more = detail.get("missing_total", len(names)) - len(names)
        bits.append("gone: " + ", ".join(names) + (" and {} more".format(more) if more > 0 else ""))
    return " · ".join(bits)
