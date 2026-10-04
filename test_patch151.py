"""PATCH #151 gate — Postgres reconnect-and-retry, one connection per flush.

ERIC, 4 Oct 2026: three "server closed the connection unexpectedly" alerts
from leads_db.upsert_lead in two days. The database never restarted; the
private network blinked while the app was opening one connection per lead.
This gate proves, without a database: a connection-level failure is retried
and recovers; a SQL/value error is NOT retried and does not block the rest
of a batch; a flush writes every dirty lead over ONE connection; the stats
/health reads tell the two stories apart; DATABASE_URL never leaks past its
hostname; the admin route and /health are wired. Prints "N passed, M failed".
"""
import os
import re
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# A stand-in psycopg2 so leads_db can be driven with no server at all.
fake = types.ModuleType("psycopg2")


class OperationalError(Exception):
    pass


class InterfaceError(Exception):
    pass


class DataError(Exception):
    pass


fake.OperationalError = OperationalError
fake.InterfaceError = InterfaceError
fake.DataError = DataError

PLAN = {"fail_connects": 0, "fail_execute_once_for": None, "connects": 0, "executes": [],
        "closed": 0, "commits": 0, "rollbacks": 0}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        key = (params or {}).get("lead_key") if isinstance(params, dict) else None
        PLAN["executes"].append(key or sql.strip().split()[0])
        if key and PLAN["fail_execute_once_for"] == key:
            PLAN["fail_execute_once_for"] = None
            raise DataError(f"bad value for {key}")
        if "SELECT count" in sql:
            self._rows = [(7,)]
        elif "SELECT lead_key, data" in sql:
            self._rows = [("whatsapp:+10000000001", {"name": "A"})]
        elif "FROM leads" in sql and "WHERE lead_key" in sql:
            self._rows = [("whatsapp:+18133702511", "Jorge Pabon", "JP Missions", "booked",
                           "whatsapp", True, None, None, None, 1234)]

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        PLAN["commits"] += 1

    def rollback(self):
        PLAN["rollbacks"] += 1

    def close(self):
        PLAN["closed"] += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def connect(url, **kw):
    PLAN["connects"] += 1
    PLAN.setdefault("kwargs", kw)
    if PLAN["fail_connects"] > 0:
        PLAN["fail_connects"] -= 1
        raise OperationalError('connection to server at "postgres.railway.internal" '
                               '(fd12::1), port 5432 failed: server closed the connection unexpectedly')
    return FakeConn()


fake.connect = connect
sys.modules["psycopg2"] = fake

os.environ["DATABASE_URL"] = "postgresql://railway:SECRETPASSWORD@postgres.railway.internal:5432/railway"
import leads_db as ldb   # noqa: E402

ldb.CONN_BACKOFF_S = (0.0, 0.0)     # no sleeping in a gate
REPORTS = []
ldb.set_error_reporter(lambda ctx, exc, detail="": REPORTS.append((ctx, str(exc), detail)))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


def reset(**kw):
    PLAN.update({"fail_connects": 0, "fail_execute_once_for": None, "connects": 0,
                 "executes": [], "closed": 0, "commits": 0, "rollbacks": 0})
    PLAN.update(kw)
    del REPORTS[:]


# ── the host never leaks the password ────────────────────────────────────────
check("host.only", ldb.db_host() == "postgres.railway.internal", ldb.db_host())
check("host.no_secret", "SECRET" not in ldb.db_host() and "railway:" not in ldb.db_host())
check("keepalives", True)  # exercised below once a connect happens

# ── one blip, one retry, recovered: no report at all ─────────────────────────
reset(fail_connects=1)
s0 = ldb.conn_stats()
ok = ldb.upsert_lead("whatsapp:+18133702511", {"name": "Jorge Pabon", "phone": "+18133702511"})
s1 = ldb.conn_stats()
check("blip.ok", ok is True)
check("blip.two_connects", PLAN["connects"] == 2, PLAN["connects"])
check("blip.no_report", REPORTS == [], REPORTS)
check("blip.retries+1", s1["retries"] - s0["retries"] == 1, (s0, s1))
check("blip.recovered+1", s1["recovered"] - s0["recovered"] == 1)
check("blip.gave_up+0", s1["gave_up"] == s0["gave_up"])
check("blip.last_error", "server closed the connection" in s1["last_error"] and "SECRET" not in s1["last_error"])
check("blip.last_recovered_at", bool(s1["last_recovered_at"]))
check("blip.closed", PLAN["closed"] >= 1)
check("keepalives.set", PLAN.get("kwargs", {}).get("keepalives") == 1 and PLAN["kwargs"].get("connect_timeout") == 10, PLAN.get("kwargs"))

# ── two blips in a row still recover (three attempts) ────────────────────────
reset(fail_connects=2)
ok = ldb.upsert_lead("instagram:2081889655867824", {"name": "IG lead"})
check("two_blips.ok", ok is True and PLAN["connects"] == 3 and REPORTS == [], (ok, PLAN["connects"], REPORTS))

# ── three blips: give up, report ONCE with the old context, caller requeues ──
reset(fail_connects=3)
s0 = ldb.conn_stats()
ok = ldb.upsert_lead("whatsapp:+12674237318", {"name": "Third"})
s1 = ldb.conn_stats()
check("down.false", ok is False)
check("down.three_connects", PLAN["connects"] == 3, PLAN["connects"])
check("down.one_report", len(REPORTS) == 1 and REPORTS[0][0] == "leads_db.upsert_lead", REPORTS)
check("down.report_detail", "lead=whatsapp:+12674237318" in REPORTS[0][2] and "3 attempt" in REPORTS[0][2], REPORTS)
check("down.gave_up+1", s1["gave_up"] - s0["gave_up"] == 1)
check("down.retries+2", s1["retries"] - s0["retries"] == 2, (s0["retries"], s1["retries"]))

# ── a value error is not retried and does not block the batch ────────────────
reset(fail_execute_once_for="whatsapp:+10000000002")
written, failed_keys = ldb.upsert_many([
    ("whatsapp:+10000000001", {"name": "one"}),
    ("whatsapp:+10000000002", {"name": "two"}),
    ("whatsapp:+10000000003", {"name": "three"}),
])
check("value.one_connect", PLAN["connects"] == 1, PLAN["connects"])
check("value.written", written == ["whatsapp:+10000000001", "whatsapp:+10000000003"], written)
check("value.failed", failed_keys == ["whatsapp:+10000000002"], failed_keys)
check("value.rollback", PLAN["rollbacks"] == 1 and PLAN["commits"] == 2, (PLAN["rollbacks"], PLAN["commits"]))
check("value.reported_once", len(REPORTS) == 1 and "lead=whatsapp:+10000000002" in REPORTS[0][2], REPORTS)

# ── a blip MID-batch: reconnect, resume from the record in flight ────────────
reset()
calls = {"n": 0}
_orig_execute = FakeCursor.execute


def _execute_drop_second(self, sql, params=None):
    calls["n"] += 1
    if calls["n"] == 2:
        raise OperationalError("server closed the connection unexpectedly")
    return _orig_execute(self, sql, params)


FakeCursor.execute = _execute_drop_second
written, failed_keys = ldb.upsert_many([("a:1", {}), ("a:2", {}), ("a:3", {})])
FakeCursor.execute = _orig_execute
check("mid.all_written", written == ["a:1", "a:2", "a:3"] and failed_keys == [], (written, failed_keys))
check("mid.two_connects", PLAN["connects"] == 2, PLAN["connects"])
check("mid.resumed", calls["n"] == 4 and PLAN["executes"] == ["a:1", "a:2", "a:3"], (calls, PLAN["executes"]))
check("mid.no_report", REPORTS == [], REPORTS)

# ── flush: every dirty lead over ONE connection; a failure requeues ALL ───────
reset()
ld = ldb.LeadData()
for i in range(5):
    ld[f"whatsapp:+1000000000{i}"] = {"name": f"L{i}"}
n = ldb.flush(ld)
check("flush.five", n == 5, n)
check("flush.one_connect", PLAN["connects"] == 1, PLAN["connects"])
check("flush.one_batch", ldb.conn_stats()["batches"] >= 1)
check("flush.dirty_cleared", not ldb._dirty, ldb._dirty)

reset(fail_connects=3)
r0 = ldb.requeue_stats()["upsert"]
ld["whatsapp:+10000000001"]["name"] = "L1b"
ld["whatsapp:+10000000002"]["name"] = "L2b"
n = ldb.flush(ld)
check("flush.down.zero", n == 0, n)
check("flush.down.requeued_two", ldb.requeue_stats()["upsert"] - r0 == 2, ldb.requeue_stats())
check("flush.down.dirty_back", ldb._dirty == {"whatsapp:+10000000001", "whatsapp:+10000000002"}, ldb._dirty)
ctxs = [r[0] for r in REPORTS]
check("flush.down.reports", ctxs.count("leads_db.upsert_lead") == 1 and "leads_db.upsert_requeued" in ctxs, ctxs)
reset()
n = ldb.flush(ld)
check("flush.recovered.drains", n == 2 and not ldb._dirty, (n, ldb._dirty))

# ── the reads retry too ──────────────────────────────────────────────────────
reset(fail_connects=1)
check("count.retry", ldb.count() == 7 and PLAN["connects"] == 2, (ldb.count(), PLAN["connects"]))
reset(fail_connects=1)
check("load_all.retry", ldb.load_all() == {"whatsapp:+10000000001": {"name": "A"}} and REPORTS == [])
reset(fail_connects=1)
check("delete.retry", ldb.delete_lead("x:1") is True and PLAN["connects"] == 2 and REPORTS == [])
reset()
rows = ldb.find_rows(["whatsapp:+18133702511", "(813) 370-2511"])
check("find.rows", rows["whatsapp:+18133702511"][0]["name"] == "Jorge Pabon"
      and rows["whatsapp:+18133702511"][0]["data_bytes"] == 1234, rows)
check("find.digits", rows["(813) 370-2511"] and rows["(813) 370-2511"][0]["lead_key"] == "whatsapp:+18133702511")
reset(fail_connects=3)
rows = ldb.find_rows(["nobody"])
check("find.unreachable_is_none", rows == {"nobody": None} and REPORTS and REPORTS[0][0] == "leads_db.find_rows", (rows, REPORTS))

# ── wiring in app.py (static) ────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("wire.health", '"leads_db": {' in SRC and '"conn": _leads_db.conn_stats()' in SRC
      and '"requeued": _leads_db.requeue_stats()' in SRC and '"host": _leads_db.db_host()' in SRC)
check("wire.health_private", '"private_network": _leads_db.db_host().endswith(".railway.internal")' in SRC)
check("wire.route", "@app.route('/admin/pg-lead', methods=['GET'])" in SRC)
check("wire.route_secret", "def admin_pg_lead():" in SRC
      and SRC.index('_admin_secret_ok(request.args.get("secret"))', SRC.index("def admin_pg_lead():"))
      < SRC.index("_leads_db.find_rows(_terms)"))
check("wire.route_masks", SRC.count("mask_contact(", SRC.index("def admin_pg_lead():"),
                                    SRC.index("def admin_lead_seq():")) >= 3)
check("wire.route_readonly", "upsert" not in SRC[SRC.index("def admin_pg_lead():"):SRC.index("def admin_lead_seq():")]
      and "delete" not in SRC[SRC.index("def admin_pg_lead():"):SRC.index("def admin_lead_seq():")].lower())
check("wire.module_doc", "PATCH #151" in open(os.path.join(HERE, "leads_db.py"), encoding="utf-8").read())

print(f"static+behaviour: {passed} passed, {failed} failed")

# the whole rail still passes (#150 gate chains #148 -> #143)
r = subprocess.run([sys.executable, os.path.join(HERE, "test_patch150.py")], capture_output=True, text=True)
tail = (r.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r.stdout[-1500:]); print(r.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
