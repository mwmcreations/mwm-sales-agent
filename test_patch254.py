"""PATCH #254 gate — a text to Michael at a time he chose (operator_remind.py).
Pure rows/due/mark first, then the sweep + route helpers lifted out of app.py
with pg and operator_alert stubbed, then the wiring. Then runs the #253 gate
(→ 252 → 251 → …)."""
import ast
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import operator_remind as orm     # noqa: E402
import operator_alert as oa       # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


NOW = int(datetime(2026, 10, 18, 14, 50, tzinfo=timezone.utc).timestamp())   # Sun 10:50 ET

# ── 1 · rows ────────────────────────────────────────────────────────────────
row, err = orm.make("Call Michael Gagaoudakis +1 954-830-0030", "2026-10-19T09:00:00-04:00", created_by="DEV", now=NOW)
check("make.ok", err == "" and row["at"] == int(datetime(2026, 10, 19, 13, 0, tzinfo=timezone.utc).timestamp())
      and row["created_by"] == "DEV" and row["sent_at"] is None and row["result"] == "" and len(row["id"]) == 12)
check("make.body_collapsed", orm.make("  a \n  b  ", None, now=NOW)[0]["body"] == "a b")
check("make.empty", orm.make("   ", None, now=NOW) == (None, "body is required"))
check("make.too_long", orm.make("x" * 601, None, now=NOW)[1].startswith("body is 601 chars"))
check("make.bad_time", orm.make("x", "tomorrow-ish", now=NOW)[1].startswith("unreadable time"))
check("make.too_far", orm.make("x", NOW + 61 * 86400, now=NOW)[1] == "more than 60 days out")
check("make.now_when_no_at", orm.make("x", None, now=NOW)[0]["at"] == NOW)
check("make.naive_is_et", orm.make("x", "2026-10-19T09:00:00", now=NOW)[0]["at"] == row["at"])
check("key", orm.key(row) == "operator_text:" + row["id"] and orm.key(row["id"]) == orm.key(row))

past = orm.make("past", NOW - 60, now=NOW - 120)[0]
later = orm.make("later", NOW + 3600, now=NOW)[0]
done = orm.mark(dict(past), "sent", now=NOW - 30)
dead = orm.mark(dict(past, id="dead"), "daily_cap", now=NOW - 30)
check("due.only_pending_past", [r["body"] for r in orm.due([later, past, done, dead, "junk"], NOW)] == ["past"])
check("due.order", [r["at"] for r in orm.due([orm.make("b", NOW - 10, now=NOW - 20)[0], orm.make("a", NOW - 50, now=NOW - 60)[0]], NOW)]
      == [NOW - 50, NOW - 10])
check("mark.sent", done["sent_at"] == NOW - 30 and done["result"] == "sent" and done["attempted_at"] == NOW - 30)
check("mark.failed_not_retried", dead["sent_at"] is None and dead["result"] == "daily_cap" and dead not in orm.due([dead], NOW + 999))
check("fmt_at", orm.fmt_at(row, pytz.timezone("America/New_York")) == "Mon Oct 19, 9:00 AM")
s = orm.summarize([later, past, done, dead], NOW)
check("summarize", s["pending"] == 2 and s["sent"] == 1 and s["failed"] == 1 and s["overdue"] == 1
      and s["next_at"].startswith("2026-10-18T10:49"))
check("alert.kind", oa.KINDS["reminder"] == {"eric": False})

# ── 2 · the sweep and the route helpers, lifted ─────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_operator_remind_rows", "_operator_remind_send", "_operator_remind_once", "_operator_remind_status"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want))
assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_ORM_LAST", "_ORM_CACHE") for t in n.targets)]
check("lift.state", len(assigns) == 2)


class PG:
    def __init__(self): self.d = {}
    def load_prefix(self, prefix, limit=5000): return {k: v for k, v in self.d.items() if k.startswith(prefix)}
    def save_state(self, k, v): self.d[k] = v; return True


pg = PG()
slack, errors, sends = [], [], []


class OA:
    result = "sent"
    def alert(self, kind, body, eric_text=None):
        sends.append((kind, body)); return {"sms": OA.result, "eric": False}


G = dict(_pgs=pg, _orm=orm, _operator_alert=OA(), time=time, datetime=datetime, pytz=pytz, TIMEZONE="America/New_York",
         SLACK_DEV_CHANNEL="#dev", _post_to_slack_async=lambda ch, text, **k: slack.append((ch, text)),
         _report_error=lambda ctx, exc, detail="": errors.append((ctx, str(exc), detail)))
exec(compile(ast.Module(body=assigns + fns, type_ignores=[]), "app_254", "exec"), G)

pg.d[orm.key(later)] = later
pg.d[orm.key(past)] = past
out = G["_operator_remind_once"](NOW)
check("sweep.sends_due_only", out == [(past["id"], "sent")] and sends == [("reminder", "past")])
check("sweep.stamped", pg.d[orm.key(past)]["sent_at"] and pg.d[orm.key(past)]["result"] == "sent" and pg.d[orm.key(later)]["sent_at"] is None)
check("sweep.dev_line", slack and slack[-1][0] == "#dev" and ":alarm_clock: operator reminder" in slack[-1][1] and past["id"] in slack[-1][1])
check("sweep.once", G["_operator_remind_once"](NOW) == [] and len(sends) == 1)
OA.result = "daily_cap"
pg.d[orm.key(later)] = later
out = G["_operator_remind_once"](NOW + 3601)
check("sweep.failure_stamped_not_retried", out == [(later["id"], "daily_cap")] and pg.d[orm.key(later)]["result"] == "daily_cap"
      and pg.d[orm.key(later)]["sent_at"] is None and G["_operator_remind_once"](NOW + 7200) == [])
check("sweep.failure_warned", ":warning: operator reminder" in slack[-1][1] and "daily_cap" in slack[-1][1])
st = G["_operator_remind_status"]()
check("status", st["sent"] == 1 and st["failed"] == 1 and st["pending"] == 0 and st["last_result"] == "daily_cap" and "checked_at" in st)
G["_ORM_CACHE"]["at"] = time.time(); G["_ORM_CACHE"]["rows"] = ["cached"]
check("rows.cache_for_health", G["_operator_remind_rows"](max_age_s=55) == ["cached"] and G["_operator_remind_rows"]() != ["cached"])

# ── 3 · wiring ──────────────────────────────────────────────────────────────
check("wire.thread", 'threading.Thread(target=_operator_remind_loop, daemon=True, name="operator_remind").start()' in SRC
      and '_heartbeat("operator_remind")' in SRC and '"operator_remind": 10,' in SRC)
check("wire.route", "@app.route('/admin/operator-text', methods=['GET', 'POST'])" in SRC and "def admin_operator_text():" in SRC
      and SRC.index("def admin_operator_text():") < SRC.index('if not _admin_secret_ok(request.values.get("secret", "")):\n        return jsonify({"ok": False, "error": "unauthorized"}), 401\n    if request.method == "GET":\n        rows = _operator_remind_rows()'))
check("wire.route_sends_now_when_due", 'if _orm.due([row]):\n        out["result"] = _operator_remind_send(row)' in SRC)
check("wire.health", '"operator_remind": _operator_remind_status(),' in SRC)
check("wire.import_after_alert", SRC.index("import operator_alert as _operator_alert") < SRC.index("import operator_remind as _orm"))
check("wire.sender_kind", '_operator_alert.alert("reminder", row.get("body", ""))' in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch253.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #253 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("253: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE254 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
