"""S8.3 regression tests — the Jul 6 duplicate-send incident, simulated.

Run: python3 tests/test_reengagement_guard.py  (stdlib only, no pytest needed)
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reengagement_guard import ReengagementGuard, guarded_send


class Cell:
    """Fake sheet cell for one stage stamp."""
    def __init__(self):
        self.value = ""
        self.fail_writes = False
        self.writes = []
    def write(self, v):
        if self.fail_writes:
            raise RuntimeError("simulated Sheets batchUpdate failure")
        self.value = v
        self.writes.append(v)


def run_touch(cell, send_results, sends, guard=None, key=None, now=0):
    """One checker touch using the S8.3 order, mirroring app.py's call site."""
    if guard is not None and not guard.claim(key, now):
        return "claim-refused"
    def send():
        sends.append(1)
        r = send_results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    reports = []
    res = guarded_send(
        write_pending=lambda: cell.write("2026-07-06 20:15 PENDING"),
        send=send,
        finalize=lambda: cell.write("2026-07-06 20:15"),
        rollback=lambda: cell.write(""),
        report=lambda m, e: reports.append((m, e)),
    )
    if res in ("blocked", "failed") and guard is not None:
        guard.release(key)
    return res


def test_incident_replay_stamp_write_fails_no_resend():
    """THE Jul 6 bug: send ok, stamp write fails silently -> old code re-sent
    next cycle. New order: stamp write fails BEFORE send -> send never happens."""
    cell, sends = Cell(), []
    cell.fail_writes = True
    res = run_touch(cell, [True], sends)
    assert res == "blocked", res
    assert sends == [], "send must NOT be attempted when the stamp can't be written"


def test_success_path_finalizes_stamp():
    cell, sends = Cell(), []
    res = run_touch(cell, [True], sends)
    assert res == "sent" and sends == [1]
    assert cell.value == "2026-07-06 20:15"
    assert cell.writes == ["2026-07-06 20:15 PENDING", "2026-07-06 20:15"]


def test_send_failure_rolls_back_for_retry():
    cell, sends = Cell(), []
    res = run_touch(cell, [False], sends)
    assert res == "failed" and cell.value == ""  # cleared -> retry next cycle


def test_send_ok_finalize_fails_pending_still_blocks():
    """Success but finalize write fails -> PENDING stamp remains; a PENDING
    stamp is truthy + carries a parseable timestamp, so the next poll's
    'unsent' check AND the 24h throttle both see it -> no duplicate."""
    cell, sends = Cell(), []
    def send():
        sends.append(1)
        cell.fail_writes = True  # break writes AFTER the send succeeds
        return True
    reports = []
    res = guarded_send(
        write_pending=lambda: cell.write("2026-07-06 20:15 PENDING"),
        send=send,
        finalize=lambda: cell.write("2026-07-06 20:15"),
        rollback=lambda: cell.write(""),
        report=lambda m, e: reports.append((m, e)),
    )
    assert res == "sent" and sends == [1]
    assert cell.value == "2026-07-06 20:15 PENDING"  # retained -> blocks re-send


def test_send_fails_and_rollback_fails_no_retry():
    cell, sends = Cell(), []
    def send():
        sends.append(1)
        cell.fail_writes = True
        return False
    reports = []
    res = guarded_send(
        write_pending=lambda: cell.write("2026-07-06 20:15 PENDING"),
        send=send,
        finalize=lambda: cell.write("2026-07-06 20:15"),
        rollback=lambda: cell.write(""),
        report=lambda m, e: reports.append((m, e)),
    )
    assert res == "failed-noretry"
    assert cell.value == "2026-07-06 20:15 PENDING"  # fail-safe: no retry
    assert any("rollback failed" in m for m, _ in reports)


def test_guard_claim_blocks_same_cycle_race():
    g = ReengagementGuard()
    key = ("13525305561", "T7")
    assert g.claim(key, 1000) is True
    assert g.claim(key, 1000 + 26 * 60) is False   # 26 min later (the incident gap)
    assert g.claim(key, 1000 + 25 * 3600) is True  # TTL expired


def test_guard_release_allows_retry():
    g = ReengagementGuard()
    key = ("13525305561", "T7")
    assert g.claim(key, 1000)
    g.release(key)
    assert g.claim(key, 1001)


def test_claim_refused_end_to_end():
    g = ReengagementGuard()
    cell, sends = Cell(), []
    key = ("15614267216", "T7")
    assert run_touch(cell, [True], sends, guard=g, key=key, now=1000) == "sent"
    assert run_touch(cell, [True], sends, guard=g, key=key, now=2000) == "claim-refused"
    assert sends == [1], "second same-stage touch must not send"


if __name__ == "__main__":
    fails = 0
    for n, f in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            f()
            print(f"PASS {n}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {n}: {e}")
    sys.exit(1 if fails else 0)
