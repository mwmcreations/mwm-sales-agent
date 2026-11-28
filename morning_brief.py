"""PATCH #295 — the morning brief: one text to Michael at 7:00 ET and one page
on the Desk, built only from what the machine already knows.

Michael, Sat 28 Nov 2026 00:35 ("Yes" to the scope) and 00:45 ("1 yes, 2 text
plus desk table, 3 do 1 and 2 after"): one summary across everything, with the
decisions that wait on him in one place.

Pure module: no Flask, no network, no clock of its own. app.py collects the
facts (leads from the Desk's read model, today's MWM calendar, the open
decisions) and hands them in; this file only decides what the text and the
page say. Step 1 has three sections:

  LAST 24H   new leads, how many got an answer, who did not, who booked
  TODAY      business events on the MWM calendar (family events never show)
  NEEDS YOU  the open numbered decisions, answered by text ("D7 yes")

Rules:
  - nothing is invented: an empty section says so in plain words;
  - the text fits operator_alert.SMS_MAX (640) and is cut by dropping detail
    lines, never mid-word, and never the NEEDS YOU count;
  - a lead who wrote and got no answer is named, because that is the one
    line Michael must not miss.
"""
import html as _html
import re
from datetime import timedelta

SEND_HOUR = 7            # 7:00 ET
CATCH_UP_UNTIL_HOUR = 10  # a restart at 7:20 still sends; after 10:00 the day is skipped
WINDOW_H = 24
SMS_MAX = 640
MAX_EVENTS_SMS = 6
MAX_DECISIONS_SMS = 4
DECISION_SMS_CHARS = 70
KIND = "brief"

_LEAD_TRIM = re.compile(r"^[^\w(]+", re.UNICODE)


def clean_title(summary):
    """A calendar title without its leading emoji/marks, one line."""
    s = re.sub(r"\s+", " ", str(summary or "")).strip()
    s = _LEAD_TRIM.sub("", s).strip()
    return s or "(no title)"


def title_name(summary):
    """The person a hand-made event is about: 'Studio Visit: Ruben Von Schmeling
    (Victory)' -> 'Ruben Von Schmeling (Victory)'. '' when the title names nobody."""
    s = clean_title(summary)
    for sep in (":", " - ", " — ", " – "):
        if sep in s:
            tail = s.split(sep, 1)[1].strip()
            if tail and re.search(r"[A-Za-zÀ-ÿ]{2}", tail):
                return tail[:80]
    return ""


def clock(dt):
    """'10:00 AM' — no leading zero, the way he reads a schedule."""
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def day_line(now):
    return f"{now.strftime('%a')} {now.strftime('%b')} {now.day}"


def window(now, hours=WINDOW_H):
    return now - timedelta(hours=hours), now


def due(now, last_sent_day, live):
    """True when the brief should go now: switch on, inside 7:00-9:59 ET, not sent today."""
    if not live:
        return False
    if not (SEND_HOUR <= now.hour < CATCH_UP_UNTIL_HOUR):
        return False
    return str(last_sent_day or "") != now.strftime("%Y-%m-%d")


def lead_stats(leads, now):
    """leads: [{name, first_seen (aware datetime or None), answered (bool),
    booked_at (datetime or None), booked_when (str), source (str), test (bool)}].
    Returns the LAST 24H facts."""
    start, end = window(now)
    new, unanswered, booked = [], [], []
    for l in leads or []:
        if not isinstance(l, dict) or l.get("test"):
            continue
        fs = l.get("first_seen")
        if fs is not None and start <= fs <= end:
            new.append(l)
            if not l.get("answered"):
                unanswered.append(l)
        b = l.get("booked_at")
        if b is not None and start <= b <= end:
            booked.append(l)
    return {"new": new, "answered": len(new) - len(unanswered), "unanswered": unanswered, "booked": booked}


def today_events(events, now):
    """events: [{summary, start (aware datetime or None for all-day), personal (bool)}].
    Business events that start today, in order. All-day and family events are left out."""
    out = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("personal"):
            continue
        st = e.get("start")
        if st is None or st.date() != now.date():
            continue
        out.append({"at": st, "title": clean_title(e.get("summary"))})
    out.sort(key=lambda x: x["at"])
    return out


def decision_line(d, chars=DECISION_SMS_CHARS):
    owners = "+".join(str(o) for o in (d.get("owners") or []) if o) or "TEAM"
    body = re.sub(r"\s+", " ", str(d.get("text") or "")).strip()
    if len(body) > chars:
        cut = body[:chars - 1]
        if " " in cut[chars // 2:]:
            cut = cut[:cut.rfind(" ")]
        body = cut.rstrip(" ,;:.") + "..."
    return f"D{int(d['id'])} {owners}: {body}"


def open_decisions(decisions):
    rows = [d for d in (decisions or []) if isinstance(d, dict) and d.get("status") in ("open", "later")]
    rows.sort(key=lambda d: int(d.get("id") or 0))
    return rows


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def last24_line(stats):
    n = len(stats["new"])
    if not n and not stats["booked"]:
        return "No new leads, no new bookings"
    parts = []
    if n:
        parts.append(_plural(n, "new lead"))
        parts.append(f"{stats['answered']} answered")
    else:
        parts.append("No new leads")
    if stats["booked"]:
        parts.append(f"{len(stats['booked'])} booked")
    return ", ".join(parts)


def sms(now, stats, events, decisions, link="", errors=()):
    """The 7:00 text. Plain ASCII-friendly lines; fits SMS_MAX. `errors` names the
    sources that could not be read ("leads", "calendar", "decisions"): the text
    says so instead of reporting an empty day."""
    dec = open_decisions(decisions)
    errors = set(errors or ())

    def build(n_events, n_dec, with_booked, with_link):
        L = [f"MWM, {day_line(now)}", "", "LAST 24H",
             "Leads could not be read" if "leads" in errors else last24_line(stats)]
        if stats["unanswered"]:
            names = ", ".join(str(l.get("name") or "?") for l in stats["unanswered"][:3])
            more = len(stats["unanswered"]) - 3
            L.append(f"NOT ANSWERED: {names}" + (f" +{more}" if more > 0 else ""))
        if with_booked:
            for l in stats["booked"][:2]:
                L.append(f"Booked: {l.get('name') or '?'}" + (f", {l.get('booked_when')}" if l.get("booked_when") else ""))
        L += ["", "TODAY"]
        if "calendar" in errors:
            L.append("Calendar could not be read")
        elif events:
            for e in events[:n_events]:
                L.append(f"{clock(e['at'])} {e['title'][:48]}")
            if len(events) > n_events:
                L.append(f"+{len(events) - n_events} more")
        else:
            L.append("Nothing on the studio calendar")
        L += ["", f"NEEDS YOU ({len(dec)})"]
        if "decisions" in errors:
            L.append("Decisions could not be read")
        elif dec:
            for d in dec[:n_dec]:
                L.append(decision_line(d))
            if len(dec) > n_dec:
                L.append(f"+{len(dec) - n_dec} more on the page")
            L.append(f"Reply like: D{int(dec[0]['id'])} yes")
        else:
            L.append("Nothing waiting on you")
        if with_link and link:
            L += ["", f"Full page: {link}"]
        return "\n".join(L)

    tries = [(MAX_EVENTS_SMS, MAX_DECISIONS_SMS, True, True), (4, 3, True, True), (3, 2, False, True),
             (2, 1, False, True), (1, 1, False, True), (1, 0, False, True), (0, 0, False, False)]
    text = ""
    for n_e, n_d, wb, wl in tries:
        text = build(n_e, n_d, wb, wl)
        if len(text) <= SMS_MAX:
            return text
    return text[:SMS_MAX]


def _e(v):
    return _html.escape(str(v if v is not None else ""))


def page(now, stats, events, decisions, sent_day="", live=False, errors=()):
    """The Desk page: the same three sections as tables, readable on a phone."""
    dec = open_decisions(decisions)
    errors = set(errors or ())

    def table(head, rows, empty):
        if not rows:
            return f'<p class="empty">{_e(empty)}</p>'
        th = "".join(f"<th>{_e(h)}</th>" for h in head)
        tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'

    lead_rows = []
    seen = set()
    for l in stats["new"] + stats["booked"]:
        k = id(l)
        if k in seen:
            continue
        seen.add(k)
        ans = '<span class="ok">answered</span>' if l.get("answered") else '<span class="bad">NOT answered</span>'
        fs = l.get("first_seen")
        lead_rows.append([_e(l.get("name") or "?"), _e(l.get("source") or ""),
                          _e(f"{fs.strftime('%a')} {clock(fs)}" if fs else ""), ans,
                          _e(l.get("booked_when") or ("booked" if l.get("booked_at") else ""))])
    ev_rows = [[_e(clock(e["at"])), _e(e["title"])] for e in events]
    dec_rows = [[f"<b>D{int(d['id'])}</b>", _e("+".join(str(o) for o in (d.get('owners') or []) if o) or "TEAM"),
                 _e(re.sub(r"\s+", " ", str(d.get("text") or "")).strip()),
                 _e("parked" if d.get("status") == "later" else "open")] for d in dec]
    status = ("The 7:00 AM text is ON." if live else "The 7:00 AM text is OFF (waiting for Michael's word).")
    if sent_day:
        status += f" Last sent: {_e(sent_day)}."
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MWM Morning Brief</title>
<style>
:root{{--bg:#0f1115;--card:#181b22;--ink:#eef0f4;--mut:#9aa3b2;--line:#2a2f3a;--ok:#4ade80;--bad:#f87171;--acc:#f5b942}}
@media (prefers-color-scheme: light){{:root{{--bg:#f5f6f8;--card:#fff;--ink:#15171c;--mut:#5b6472;--line:#e3e6ec;--ok:#15803d;--bad:#b91c1c;--acc:#b45309}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:20px 16px 48px}}h1{{font-size:22px;margin:0 0 2px}}
.sub{{color:var(--mut);font-size:14px;margin:0 0 18px}}section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 14px 10px;margin:0 0 14px}}
h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:0 0 8px}}h2 b{{color:var(--acc)}}
.big{{font-size:18px;margin:0 0 10px}}.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:15px}}
th{{text-align:left;color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;padding:6px 8px;border-bottom:1px solid var(--line)}}
td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}td:first-child{{white-space:nowrap}}tr:last-child td{{border-bottom:0}}
.ok{{color:var(--ok)}}.bad{{color:var(--bad);font-weight:700}}.empty{{color:var(--mut);margin:4px 0 8px}}
.how{{color:var(--mut);font-size:14px;margin:8px 0 4px}}a{{color:var(--acc)}}
</style></head><body><main>
<h1>Morning brief</h1><p class="sub">{_e(now.strftime('%A, %B'))} {now.day} · built {_e(clock(now))} ET · <a href="/desk/">back to the Desk</a></p>
<section><h2>Needs you <b>({len(dec)})</b></h2>
{table(["#", "From", "Question", "Status"], dec_rows, "Decisions could not be read just now." if "decisions" in errors else "Nothing is waiting on you.")}
<p class="how">Answer by text to the MWM number: <b>D7 yes</b>, <b>D7 no</b>, <b>D7 later</b>, or D7 followed by your answer.</p></section>
<section><h2>Last 24 hours</h2><p class="big">{_e("Leads could not be read" if "leads" in errors else last24_line(stats))}</p>
{table(["Lead", "Source", "Came in", "Answered", "Booked"], lead_rows, "Leads could not be read just now." if "leads" in errors else "No new leads and no new bookings since yesterday morning.")}</section>
<section><h2>Today</h2>
{table(["Time", "What"], ev_rows, "The calendar could not be read just now." if "calendar" in errors else "Nothing on the studio calendar today.")}</section>
<p class="sub">{status}</p>
</main></body></html>"""


_TAGS = re.compile(r"<[^>]+>")


def meeting_briefing(minutes_until, time_str, lead_name="", lead_biz="", lead_email="", lead_phone="",
                     booked_via="", conv_summary="", summary="", description=""):
    """The 1-hour pre-meeting text. Michael, Wed 25 Nov 2026 08:51, on a visit LARA
    put on the calendar by hand: "the info is there and Maya did not see". A
    hand-made event has no lead facts, so the name comes from the title and the
    event's own notes ride along. Nothing is guessed: no 'Unknown', no
    'Not specified', and a source only when the booking recorded one."""
    known = bool(str(lead_name or "").strip())
    name = str(lead_name or "").strip() or title_name(summary) or clean_title(summary)
    L = [f"MEETING BRIEFING - {int(minutes_until)} min", "", name]
    if str(lead_biz or "").strip():
        L.append(str(lead_biz).strip())
    if lead_email and str(lead_email).lower() not in ("not provided", "n/a"):
        L.append(str(lead_email))
    if lead_phone:
        L.append(str(lead_phone))
    L.append(f"{time_str} ET")
    if str(booked_via or "").strip():
        L.append(f"Source: {str(booked_via).strip()}")
    if conv_summary:
        L += ["", "Recent conversation:", conv_summary]
    notes = re.sub(r"\s+", " ", _TAGS.sub(" ", str(description or ""))).strip()
    if not known and notes:
        if len(notes) > 300:
            cut = notes[:299]
            notes = (cut[:cut.rfind(" ")] if " " in cut[150:] else cut).rstrip(" ,;:.") + "..."
        L += ["", "Notes: " + notes]
    L += ["", "Good luck!"]
    return "\n".join(L)
