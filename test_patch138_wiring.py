"""PATCH #138 wiring — Maya knows clients, personal contacts and leads apart.

Source checks on app.py, then a behavioural run of the new Instagram helpers
(extracted from app.py and executed against stubs)."""
import ast, os, re, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import relationship as _rel
import known_client as _kc
PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
CODE = "\n".join(l for l in SRC.split("\n") if not l.lstrip().startswith("#"))

print("\n== the canned share reply")
wh = SRC.split("def webhook_instagram")[1].split("\ndef ")[0]
ok('Thanks for sharing! How can I help you today?' not in wh,
   "the webhook no longer answers every share itself")
ok("_ig_attachment_only" in wh, "a text-less attachment goes to the relationship check")

print("\n== client mode sees records that already say client")
for part, label in ((SRC.split("PATCH #111: client mode")[1][:900], "WhatsApp"),
                    (SRC.split("PATCH #111: client mode")[2][:900], "Instagram")):
    ok('_cm_why == "already_marked"' in part and "_cm_hit, _cm_rec = True" in part,
       "%s: already_marked switches client mode ON" % label)
ok('rec.get("package") or rec.get("product")' in SRC, "client block reads product when there is no package")

print("\n== Instagram text path")
ig = SRC.split("def _handle_incoming_instagram")[1].split("\ndef _fetch_ig_profile")[0]
i_rel = ig.index("_ig_relationship(sender, sender_id)")
ok(i_rel < ig.index("_post_new_lead_or_existing_client("), "relationship decided before NEW_LEAD")
ok(i_rel < ig.index("_calculate_lead_score("), "before lead scoring")
ok(i_rel < ig.index("process_maya_ig"), "before Maya")
ok("_ig_stay_quiet(" in ig[i_rel:i_rel + 600] and "return" in ig[i_rel:i_rel + 600],
   "a quiet decision returns without Maya")
ok("[Replied to your Instagram story]" in ig[i_rel:i_rel + 600], "a wordless story reply counts as a reaction")

print("\n== profile + sweeps")
pf = SRC.split("def _fetch_ig_profile")[1].split("\ndef ")[0]
ok("_rel.PROFILE_FIELDS" in pf and "_rel.BASIC_FIELDS" in pf, "profile asks for follow fields, falls back")
ok('"we_follow"' in pf, "profile returns the follow flag")
cold = SRC.split("def _cold_lead_checker")[1].split("\ndef ")[0]
ok('data.get("relationship") == _rel.KNOWN' in cold, "cold sweep skips personal contacts")
ok('startswith("skipped:")' in cold, "cold sweep does not card a recognised client Cold")
ok(len(re.findall(r"lead_data\.(?:pop|clear)\(|del lead_data\[", CODE)) == 1,
   "still exactly one place that removes a lead (Patch #127)")

# ── behaviour ────────────────────────────────────────────────────────────
print("\n== behaviour")
tree = ast.parse(SRC)
want = {"_known_client_lookup", "_ig_relationship", "_ig_stay_quiet", "_ig_attachment_only"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
ok(len(fns) == 4, "helpers found")

sent, mirrored, profiles = [], [], {}
class _Tally:
    def bump(self, *a): pass
class _Roster:
    def find(self, cand):
        if (cand.get("ig_username") or "") == "victorymartialarts":
            return True, "instagram", {"name": "Victory Martial Arts", "package": "Studio Package"}
        return False, "no_match", None
G = {"lead_data": {}, "_kc": _kc, "_rel": _rel, "time": __import__("time"),
     "_TALLY": _Tally(), "_CLIENT_ROSTER": _Roster(), "MICHAEL_SLACK_USER_ID": "UMICH",
     "send_instagram_dm": lambda sid, body=None, **k: sent.append((sid, body)),
     "_mirror_to_maya_shadow_async": lambda ident, d, t: mirrored.append((ident, d, t)),
     "_build_ig_sender_identity": lambda sid: {"igsid": sid},
     "_fetch_ig_profile": lambda sid: profiles.get(sid, {"name": "", "username": "", "we_follow": None})}
mod = ast.Module(body=fns, type_ignores=[])
exec(compile(mod, "app_helpers", "exec"), G)

def reset():
    sent.clear(); mirrored.clear(); G["lead_data"].clear()

# 1 · a friend shares a reel -> no bot reply, Michael pinged, remembered, no lead fields
reset(); profiles["111"] = {"name": "Margaret Moraes", "username": "margaret", "we_follow": True}
G["_ig_attachment_only"]("111", "ig_reel")
ok(sent == [], "friend's reel: Maya sends nothing")
ok(len(mirrored) == 1 and "<@UMICH>" in mirrored[0][2] and "[Shared a reel]" in mirrored[0][2],
   "friend's reel: mirrored to #maya-shadow with a ping")
rec = G["lead_data"].get("instagram:111") or {}
ok(rec.get("relationship") == _rel.KNOWN and "last_message_time" not in rec,
   "friend remembered as a personal contact, invisible to the cold sweep")

# 2 · a stranger shares a reel -> exactly the old reply, nothing recorded
reset(); profiles["222"] = {"name": "Some One", "username": "someone", "we_follow": False}
G["_ig_attachment_only"]("222", "share")
ok(sent == [("222", "Thanks for sharing! How can I help you today? 😊")], "stranger: the old reply, unchanged")
ok("instagram:222" not in G["lead_data"] and mirrored == [], "stranger: no record left behind (as before)")

# 3 · a client (roster, by handle) shares -> quiet + ping, even if we do not follow them
reset(); profiles["333"] = {"name": "Victory Martial Arts", "username": "victorymartialarts", "we_follow": False}
G["_ig_attachment_only"]("333", "story_mention")
ok(sent == [] and len(mirrored) == 1 and "current client" in mirrored[0][2],
   "client's story mention: no bot line, Michael pinged")

# 4 · the Jaysee shape: his own record already says client -> client, not lead
reset(); G["lead_data"]["instagram:444"] = {"name": "Bald Hearing Guy", "product": "Studio Package",
                                           "ig_we_follow": False, "ig_follow_checked_ts": G["time"].time()}
k, why = G["_ig_relationship"]("instagram:444", "444")
ok(k == _rel.CLIENT, "a record that already says client is classified client (was: lead)")

# 5 · someone we follow who came from an ad -> lead
reset(); G["lead_data"]["instagram:555"] = {"ig_we_follow": True, "ad_referral": True,
                                           "ig_follow_checked_ts": G["time"].time()}
ok(G["_ig_relationship"]("instagram:555", "555")[0] == _rel.LEAD, "ad arrival stays a lead even if followed")

# 6 · the profile call blows up -> lead (fail open), and the old reply still goes out
reset()
def _boom(sid): raise RuntimeError("graph down")
G["_fetch_ig_profile"] = _boom
G["_ig_attachment_only"]("666", "share")
ok(sent == [("666", "Thanks for sharing! How can I help you today? 😊")], "graph failure: behaves exactly as before #138")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
