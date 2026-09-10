#!/usr/bin/env python3
"""
build_index.py — the content layer for the Victory Content Intelligence demo.

Three real sources, joined. Nothing invented:

  1. 00_READ_ME_BROLL_REC709.md      60 action clips  — name, shot, duration, source id
  2. 00_READ_ME_CEREMONY_CROWD.md    51 ceremony/crowd clips — same shape
  3. VICTORY_FOOTAGE_INDEX.md        EDDIE's camera/card ranges -> session, day, priority

The join is what makes a result row true. A clip's source id (C0760 / D0232) falls
inside exactly one camera-card range in EDDIE's index, and that range names the day,
the session and the call-sheet priority. So "winner arm raised" becomes
"Convention 2026 - Day 3 - Tournament Finals, camera B" without anyone guessing.
"""
import json, re, os, sys

SRC = "/tmp/vci/src"
OUT = "/tmp/vci/build"

# ── EDDIE's index, transcribed as ranges ────────────────────────────────────
# (day_no, date_label, session_label, priority, [(camera, card, lo, hi), ...])
SESSIONS = [
    (1, "Thursday 23 July", "Welcome Center Arrivals",              "standard", [("CAM_D","CARD 1",4130,4186)]),
    (1, "Thursday 23 July", "Masters Training",                     "high",     [("CAM_A","CARD 1",9615,9657)]),
    (1, "Thursday 23 July", "Victory Dinner",                       "high",     [("CAM_A","CARD 1",9658,9697)]),
    (2, "Friday 24 July",   "Instructor Training Certification",    "high",     [("CAM_A","CARD 1",9698,9729),("CAM_A","CARD 3",9730,9732),("CAM_B","CARD 2",347,454),("OSMO","DJI_001",805,857)]),
    (2, "Friday 24 July",   "XMA Seminar Training",                 "low",      [("CAM_B","CARD 4",455,515),("OSMO","DJI_001",859,924)]),
    (2, "Friday 24 July",   "Mass class block",                     "standard", [("CAM_B","CARD 4",516,530),("OSMO","DJI_001",925,929)]),
    (2, "Friday 24 July",   "Victory for Life Reception",           "standard", [("CAM_A","CARD 3",9733,9734),("CAM_B","CARD 4",531,552),("OSMO","DJI_001",930,932)]),
    (3, "Saturday 25 July", "Victory Tournament Finals",            "high",     [("CAM_B","CARD 7",553,816),("OSMO","DJI_001",933,999),("OSMO","DJI_002",1,58),("DRONE","DRONE",49,65)]),
    (3, "Saturday 25 July", "Night of Champions",                   "hero",     [("CAM_A","CARD 10",9735,9735),("CAM_B","CARD 5",818,819),("CAM_B","CARD 7",817,817),("OSMO","DJI_002",59,82)]),
    (3, "Saturday 25 July", "Night of Champions",                   "hero",     [("CAM_A","CARD 10",9736,9736),("CAM_B","CARD 12",820,822),("CAM_C","CARD 11",8,8)]),
    (4, "Sunday 26 July",   "5K Run",                               "low",      [("OSMO","DJI_002",83,96)]),
    (4, "Sunday 26 July",   "Black Belt Testing / Candlelight",     "high",     [("CAM_A","CARD 6",9737,9740),("OSMO","DJI_002",97,213)]),
    (4, "Sunday 26 July",   "Candlelight Finale",                   "hero",     [("CAM_B","CARD 7",847,849),("OSMO","DJI_002",215,239)]),
]

CAMERA_BODY = {"CAM_A":"Sony FX6","CAM_B":"Sony FX3","CAM_C":"Sony FX30",
               "CAM_D":"Sony A7 IV","OSMO":"DJI Osmo (roaming)","DRONE":"DJI drone"}
CAMERA_SHORT = {"CAM_A":"camera A","CAM_B":"camera B","CAM_C":"camera C",
                "CAM_D":"camera D","OSMO":"roaming camera","DRONE":"drone"}


def resolve(source_id):
    """C0760 / D0232 -> the session that owns it. Returns None when genuinely unknown.

    'C' ids are the Sony bodies; 'D' ids are the roaming Osmo. The Osmo used two
    cards whose numbering restarts, so the split is by magnitude: DJI_001 runs
    805-999, DJI_002 runs 001-239. Nothing else overlaps."""
    m = re.match(r"^([CD])(\d{3,4})$", source_id)
    if not m:
        return None
    kind, num = m.group(1), int(m.group(2))
    for day, date, label, prio, ranges in SESSIONS:
        for cam, card, lo, hi in ranges:
            if kind == "D" and cam != "OSMO":
                continue
            if kind == "C" and cam == "OSMO":
                continue
            if kind == "D":
                # magnitude decides the card; the range then decides the session
                want = "DJI_001" if num >= 805 else "DJI_002"
                if card != want:
                    continue
            if lo <= num <= hi:
                return {"day": day, "date": date, "session": label, "priority": prio,
                        "camera": cam, "camera_body": CAMERA_BODY[cam],
                        "camera_short": CAMERA_SHORT[cam], "card": card}
    return None


# ── the two read-mes ────────────────────────────────────────────────────────
ROW = re.compile(r"^\|\s*\\?`?([A-Za-z0-9_\-\.]+\.mp4)\\?`?\s*\|\s*(.+?)\s*\|\s*([\d\.]+)\s*s\s*\|\s*\\?`?([CD]\d{3,4})\\?`?\s*\|")
HEAD = re.compile(r"^\\?#\\?#\s+(.+?)\s*-\s*\d+\s+clips")

CATEGORY_META = {
    "COMPETITION":        ("Competition",          "05 BROLL ACTION/01_COMPETITION",        0.55),
    "WINNING MOMENTS":    ("Winning moments",      "05 BROLL ACTION/02_WINNING_MOMENTS",    0.95),
    "TRAINING / SEMINAR": ("Training & seminar",   "05 BROLL ACTION/03_TRAINING_SEMINAR",   0.35),
    "INSTRUCTOR TRAINING":("Instructor training",  "05 BROLL ACTION/04_INSTRUCTOR_TRAINING",0.35),
    "BELT CEREMONY & RANK PRESENTATION": ("Belt & rank presentation", "06 BROLL CEREMONY & CROWD/06_BELT_CEREMONY", 0.90),
    "BOARD BREAKS":       ("Board breaks",         "06 BROLL CEREMONY & CROWD/07_BOARD_BREAKS", 0.80),
    "CANDLELIGHT CEREMONY":("Candlelight ceremony","06 BROLL CEREMONY & CROWD/08_CANDLELIGHT",  1.00),
    "CROWD & PARENT REACTIONS": ("Crowd & parent reactions","06 BROLL CEREMONY & CROWD/09_CROWD_REACTIONS", 0.75),
}
PRIORITY_WEIGHT = {"hero": 1.00, "high": 0.70, "standard": 0.45, "low": 0.20}


def clean(s):
    return s.replace("\\", "").strip()


def parse_readme(path, fps_note):
    out, current = [], None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        h = HEAD.match(line.strip())
        if h:
            current = clean(h.group(1)).upper().strip()
            continue
        m = ROW.match(line.strip().replace("\\", ""))
        if m and current:
            fname, shot, secs, src = m.group(1), clean(m.group(2)), float(m.group(3)), m.group(4)
            out.append({"file": fname, "shot": shot, "seconds": secs,
                        "source_id": src, "category_raw": current, "fps_note": fps_note})
    return out


def title_case(shot):
    """'winner arm raised' -> 'Winner, arm raised'. Editorial only — the words are
    the editor's own, taken from the read-me, never invented here."""
    words = shot.strip()
    return words[:1].upper() + words[1:]


def build_clips():
    rows = parse_readme(os.path.join(SRC, "readme_broll.md"), "59.94 fps")
    rows += parse_readme(os.path.join(SRC, "readme_ceremony.md"), "23.976 fps")

    ids = {}
    p = os.path.join(SRC, "clip_ids.tsv")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                ids[parts[1]] = parts[2]

    moments, unresolved = [], []
    for r in rows:
        prov = resolve(r["source_id"])
        if not prov:
            unresolved.append(r["source_id"])
        cat_label, folder, cat_weight = CATEGORY_META.get(
            r["category_raw"], (r["category_raw"].title(), "", 0.4))
        base = r["file"][:-4]
        thumb = "thumbs/%s.jpg" % base
        if not os.path.exists(os.path.join("/tmp/vci", thumb)):
            thumb = ""
        prio = prov["priority"] if prov else "standard"
        moments.append({
            "kind": "clip",
            "id": base,
            "title": title_case(r["shot"]),
            "category": cat_label,
            "file": r["file"],
            "folder": folder,
            "drive_id": ids.get(r["file"], ""),
            "thumb": thumb,
            "seconds": r["seconds"],
            "duration": "%dm %02ds" % (int(r["seconds"]) // 60, int(round(r["seconds"])) % 60)
                        if r["seconds"] >= 60 else "0m %02ds" % int(round(r["seconds"])),
            "source_id": r["source_id"],
            "fps": r["fps_note"],
            "day": prov["day"] if prov else None,
            "date": prov["date"] if prov else "Convention 2026",
            "session": prov["session"] if prov else "Session not resolved",
            "camera": prov["camera_short"] if prov else "",
            "camera_body": prov["camera_body"] if prov else "",
            "card": prov["card"] if prov else "",
            "priority": prio,
            "weight": round(0.5 * cat_weight + 0.5 * PRIORITY_WEIGHT[prio], 4),
            "text": " ".join([r["shot"], cat_label, prov["session"] if prov else "",
                              prov["date"] if prov else ""]).lower(),
        })
    return moments, unresolved


if __name__ == "__main__":
    clips, unresolved = build_clips()
    json.dump(clips, open(os.path.join(OUT, "clips.json"), "w"), indent=1)
    print("clips parsed:      %d" % len(clips))
    print("with drive id:     %d" % sum(1 for c in clips if c["drive_id"]))
    print("with thumbnail:    %d" % sum(1 for c in clips if c["thumb"]))
    print("session resolved:  %d" % sum(1 for c in clips if c["day"]))
    print("unresolved ids:    %s" % (sorted(set(unresolved)) or "none"))
    from collections import Counter
    print("\nby session:")
    for k, v in Counter("Day %s · %s" % (c["day"], c["session"]) for c in clips).most_common():
        print("   %-46s %d" % (k, v))
    print("\nby priority:", dict(Counter(c["priority"] for c in clips)))
