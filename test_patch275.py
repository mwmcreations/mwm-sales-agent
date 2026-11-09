#!/usr/bin/env python3
"""GATE for PATCH #275 — the re-engagement copy Michael OK'd (9 Nov 06:47) and the
stored switches. Pure checks on the copy tables, the switch helper lifted into a
harness, source pins, then the #274 gate. Prints GATE275 PASS/FAIL."""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
MA_SRC = open(os.path.join(HERE, "maya_actions.py"), encoding="utf-8").read()
tree = ast.parse(SRC)


def _assign(name):
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise KeyError(name)


# ── 1. the SMS copy ──────────────────────────────────────────────────────────
SMS = _assign("SMS_REENGAGEMENT_MESSAGES")
GSM = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
check("sms.seven", sorted(SMS) == [f"T{i}" for i in range(1, 8)])
for k, v in SMS.items():
    t = v.format(name="Samantha")
    check(f"sms.{k}.one_segment", len(t) <= 160, len(t))
    check(f"sms.{k}.gsm_only", all(c in GSM for c in t), [c for c in t if c not in GSM])
    check(f"sms.{k}.shape", v.startswith("MWM Creations: Hi {name}, ") and v.endswith(" Reply STOP to opt out."), v)
    check(f"sms.{k}.no_old_words", "amazing" not in v and "brainstorm" not in v and "awareness" not in v)
check("sms.visit_named", "Studio Strategy Visit" in SMS["T1"] and "Studio Strategy Visit" in SMS["T3"])
check("sms.t5_video_call", "15-minute video call" in SMS["T5"] and "VIDEO" in SMS["T5"])
check("sms.t7_last", SMS["T7"].startswith("MWM Creations: Hi {name}, last note from Maya."))
check("sms.distinct", len(set(SMS.values())) == 7)

# ── 2. the Instagram T1 ─────────────────────────────────────────────────────
IG = _assign("IG_REENGAGEMENT_MESSAGES")
check("ig.t1", "Maya from Michael Moraes' team at MWM Studios" in IG["T1"] and "free 30-minute Studio Strategy Visit" in IG["T1"]
      and IG["T1"].endswith("Which day this week works for you?"), IG["T1"])
check("ig.t1_no_emoji", all(ord(c) < 0x2600 for c in IG["T1"]))
check("ig.t1_has_name", "{name}" in IG["T1"] and IG["T1"].format(name="Carla").startswith("Hi Carla,"))
check("ig.others_present", all(f"T{i}" in IG for i in range(2, 8)))

# ── 3. the WhatsApp v3 table ────────────────────────────────────────────────
MA_TREE = ast.parse(MA_SRC)


def _ma_assign(name):
    for n in MA_TREE.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise KeyError(name)


V3 = _ma_assign("REENGAGEMENT_TEMPLATES_V3")
OLD = _ma_assign("REENGAGEMENT_TEMPLATES")
H = _ma_assign("REENGAGEMENT_TEMPLATE_HEADERS")
check("wa.v3_seven", sorted(V3) == [f"T{i}" for i in range(1, 8)] and all(v == f"maya_reengage_v3_t{k[1]}" for k, v in V3.items()), V3)
check("wa.old_untouched", OLD["T1"] == "maya_reengagement_1" and OLD["T7"] == "maya_reengagement_3")
check("wa.v3_headers", all(v in H for v in V3.values()) and H["maya_reengage_v3_t2"] == "video" and H["maya_reengage_v3_t4"] == "video"
      and H["maya_reengage_v3_t5"] == "image" and H["maya_reengage_v3_t6"] == "image"
      and all(H[f"maya_reengage_v3_t{i}"] is None for i in (1, 3, 7)), {k: H.get(k) for k in V3.values()})
_media = MA_SRC[MA_SRC.index("REENGAGEMENT_MEDIA_URLS = {"):MA_SRC.index("REENGAGEMENT_CADENCE = {")]
check("wa.v3_media_keys", all(f'"maya_reengage_v3_t{i}": os.getenv("REENGAGEMENT_T{i}_' in _media for i in (2, 4, 5, 6)) and "maya_reengage_v3_t1" not in _media, _media[-400:])
check("wa.v3_media_same_env", '"maya_reengage_v3_t2": os.getenv("REENGAGEMENT_T2_VIDEO_URL", "")' in _media and '"maya_reengage_v3_t6": os.getenv("REENGAGEMENT_T6_IMAGE_URL", "")' in _media)

# ── 4. the switches, lifted ─────────────────────────────────────────────────
want = {"_switch_on", "_ig_chase_live", "_wa_reengage_v3"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SWITCHES" for t in n.targets)]
check("lift.found", len(fns) == 3 and len(consts) == 1)
STORE = {}


class PG:
    def load_state(self, k, d=None): return STORE.get(k, d)
    def save_state(self, k, v): STORE[k] = v; return True


G = dict(os=os, _pgs=PG())
exec(compile(ast.Module(body=consts + fns, type_ignores=[]), "app_275", "exec"), G)
for e in ("IG_CHASE_LIVE", "WA_REENGAGE_V3"):
    os.environ.pop(e, None)
check("switch.names", set(G["SWITCHES"]) == {"ig_chase_live", "wa_reengage_v3"})
check("switch.dark", G["_ig_chase_live"]() is False and G["_wa_reengage_v3"]() is False)
STORE["switch:ig_chase_live"] = True
check("switch.stored_on", G["_ig_chase_live"]() is True and G["_wa_reengage_v3"]() is False)
STORE["switch:ig_chase_live"] = False
os.environ["WA_REENGAGE_V3"] = "1"
check("switch.env_on", G["_wa_reengage_v3"]() is True and G["_ig_chase_live"]() is False)
os.environ.pop("WA_REENGAGE_V3", None)
check("switch.unknown_false", G["_switch_on"]("nope") is False)


class PGDown:
    def load_state(self, k, d=None): raise RuntimeError("down")


G["_pgs"] = PGDown()
check("switch.store_down_is_off", G["_ig_chase_live"]() is False)

# ── 5. source pins ──────────────────────────────────────────────────────────
check("app.admin_switch", '@app.route("/admin/switch", methods=["GET", "POST"])' in SRC and 'if name not in SWITCHES:' in SRC
      and '_pgs.save_state(f"switch:{name}", on)' in SRC and '_admin_secret_ok(request.values.get("secret", ""))' in SRC[SRC.index('def admin_switch'):SRC.index('def admin_switch') + 400])
check("app.checker_v3", "_tmpl = (_maya_actions_mod.REENGAGEMENT_TEMPLATES_V3 if _wa_reengage_v3()" in SRC and "else REENGAGEMENT_TEMPLATES)[next_stage]" in SRC)
check("app.checker_old_line_gone", "_tmpl = REENGAGEMENT_TEMPLATES[next_stage]" not in SRC)
check("app.maya_tool_v3", "template_name = (REENGAGEMENT_TEMPLATES_V3 if _wa_reengage_v3() else REENGAGEMENT_TEMPLATES).get(template_key)" in SRC)
check("app.wa_buttons", 'if _msg_lower in ("not right now", "not now"):   # PATCH #275' in SRC and 'elif _msg_lower in ("visit the studio", "pick a day"):   # PATCH #275' in SRC)
check("app.ig_buttons", 'if _msg_lower in ("not right now", "not now"):   # PATCH #275\n        send_instagram_dm(' in SRC and 'elif _msg_lower in ("visit the studio", "pick a day"):   # PATCH #275\n' in SRC)
check("app.health", '"switches": {n: _switch_on(n) for n in SWITCHES},' in SRC)
check("app.ig_live_uses_switch", 'def _ig_chase_live():\n    return _switch_on("ig_chase_live")' in SRC)
check("app.274_intact", "_ig_arm_email_chase(phone, name, now)" in SRC and "IG_T1_HOURS = int(" in SRC)
check("app.old_sms_gone", "still thinking about your video project?" not in SRC)
check("app.old_ig_t1_gone", "Just checking in — you seemed interested" not in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch274.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #274 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("274: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE275 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
