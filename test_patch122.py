#!/usr/bin/env python3
"""
test_patch122.py — we cold-pitched three paying clients in one week.

2 Sep · Gisele Kolbrich, 24h after she paid for a studio session, mid-story:
        "are you looking to use video to bring in more listings and buyers?"
2 Sep · Philip Kolbrich, her partner, the same afternoon we apologised.
4 Sep · Luzia Costa, while she was IN THE ROOM recording, having just posted a
        story of our own control room with the ON AIR sign lit:
        "Ainda quer marcar aquela visita ao estudio?"

The client guard (#110/#111) was not missing and did not error. It could not
SEE them. It identifies people by business, email and phone; on Instagram we
hold none of the three. What we do hold — and have held all along — is the
display name, which `_fetch_ig_profile` writes onto the lead before Maya ever
answers. The index simply never looked at a person's name.

Run: python3 test_patch122.py
"""
import io
import known_client as K

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


CLIENT = {"name": "Gisele Kolbrich", "email": "gisele@topfloridahomes.com",
          "business": "Top Florida Homes", "client_won": True,
          "product": "Studio Package"}
LUZIA = {"name": "Luzia Costa", "email": "luziahcosta@hotmail.com",
         "client_won": True, "product": "Studio Package"}
IDX = K.build_client_index([CLIENT, LUZIA])


# ── 1 · normalisation: a name, or nothing ─────────────────────────────────
ok(K.normalize_person_name("Gisele Kolbrich") == "gisele kolbrich", "a full name normalises")
ok(K.normalize_person_name("Luzia  Costa \U0001f3ac") == "luzia costa",
   "emoji and runs of whitespace do not defeat it — IG names carry both")
ok(K.normalize_person_name("Gisèle Kölbrich") == "gisele kolbrich",
   "accents fold, so the same person spelled properly still matches")
for thin in ("Gisele", "@giselek", "\U0001f525\U0001f525", "", None, "Dr", "The Team"):
    ok(K.normalize_person_name(thin) == "",
       "%r is not a person's name and normalises to nothing" % (thin,))


# ── 2 · THE FIX · the three real cases now land in client mode ────────────
ok(K.match_known_client({"name": "Gisele Kolbrich", "phone": "instagram:7788991"},
                        IDX) == (True, "person_name:gisele kolbrich"),
   "Gisele, DMing from Instagram with nothing but her name, IS a client")
ok(K.match_known_client({"name": "Luzia Costa", "phone": "instagram:1296182"},
                        IDX)[0] is True,
   "Luzia, tagging us from the studio floor, IS a client")


# ── 3 · and the guards that make that safe ────────────────────────────────
ok(K.match_known_client({"name": "Gisele"}, IDX)[0] is False,
   "a bare first name is still not evidence")
ok(K.match_known_client({"name": "Gisele Kolbrich",
                         "email": "stranger@elsewhere.com"}, IDX)[0] is False,
   "a stranger's email OUTRANKS a matching name — suppressing a real lead is "
   "the failure nobody would ever notice")
ok(K.match_known_client({"name": "Gisele Kolbrich", "phone": "+14075550123"},
                        IDX)[0] is False,
   "so does a phone number we have never seen")
TWINS = K.build_client_index([
    dict(CLIENT), {"name": "Gisele Kolbrich", "email": "other@example.com",
                   "client_won": True, "product": "Studio Package"}])
ok("gisele kolbrich" in TWINS["ambiguous_names"], "two clients, one name = ambiguous")
ok(K.match_known_client({"name": "Gisele Kolbrich"}, TWINS)[0] is False,
   "and an ambiguous name never matches anyone")


# ── 4 · the Instagram handle is a first-class identifier now ──────────────
HIDX = K.build_client_index([dict(CLIENT, ig_username="@giselek")])
ok(K.match_known_client({"ig_username": "giselek"}, HIDX)[0] is True,
   "a known handle matches even with no name at all")
ok(K.match_known_client({"phone": "instagram:5551212"},
                        K.build_client_index([dict(CLIENT, instagram_id="5551212")]))[0] is True,
   "and so does a learned IGSID arriving as the sender key")
ok(K.instagram_key("ab") == "", "a two-character handle is not an identifier")


# ── 5 · the wiring: the name is on the lead BEFORE the guard reads it ─────
APP = io.open("app.py", encoding="utf-8").read()
IG = APP.split("def _handle_incoming_instagram(")[1].split("\ndef ")[0]
ok(IG.index("_fetch_ig_profile(") < IG.index("_known_client_lookup(sender)"),
   "the IG profile is fetched BEFORE the client-mode check — otherwise the "
   "name the fix depends on is not there yet")
ok('lead_data[sender]["name"] = _ig_profile["name"]' in IG,
   "and the fetched name is written where _known_client_lookup will read it")
ok('lead_data[sender]["ig_username"]' in IG, "the handle is stored too")


print("\n" + "=" * 60)
print("  PATCH #122: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
