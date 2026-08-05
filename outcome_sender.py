#!/usr/bin/env python3
"""PATCH #44B — the sender for the sequences Patch #39 arms.

WHY THIS FILE EXISTS
====================
Patch #39 (Aug 3, 2026) restructured the event-report buttons so that every
outcome carries automation, which is what Michael asked for:

    "I would love to all buttons instead of the not interested ... should do
     an automated task"

#39 did the policy half well. `outcome_plan()` computes the touch schedule and
`meeting_report_submit` stores it on the lead record as `outcome_seq`, with a
comment promising that "the sender (Patch #40)" would consume it. Patch #40
turned out to be the lead-resolution fix. **The sender was never written.**

Verified Aug 3, 2026 across the whole repo: `outcome_seq` is written in exactly
one place and read in zero. So for every outcome except `studio_package_pitched`
— which has its own sender in studio_package.py — the sequence was described in
Slack, saved to the record, and then silently did nothing. Follow-up nudges,
no-show rebooks, the day-7 review ask, and every email-capture step have been
dead since #39 shipped.

This is the sixth "an assignment is not an invocation" defect on this board.
The pattern is always the same: something is computed and stored, the storing
is mistaken for the doing, and the Slack message describes an intention as an
outcome.

DESIGN NOTES
============
* Mirrors `studio_package.py`, which is the one sequence rail that has worked
  in production. Same `configure(**deps)` shape, same hourly-ish loop, same
  heartbeat contract. Proven patterns beat novel ones at 11pm.
* All timing and stop logic lives in `event_rail.py` so it is unit-testable
  without a network, a database, or a clock.
* Every email goes through the injected `send_email` dep, which app.py wires to
  `_email_send` — so do-not-contact, the send stamp, and the honest `ok` check
  all apply. Nothing here calls send_gmail directly. That is the whole point
  of Patch #44A.
* A step that cannot be delivered (CH_UNKNOWN) is NOT silently dropped: it goes
  to the plan's named owner in Slack with the lead, the reason, and the message
  we would have sent. An unreachable step that looks scheduled is worse than
  one that never armed.
"""

from datetime import datetime, timedelta

from event_rail import (CH_INSTAGRAM, CH_UNKNOWN, CH_WEB, CH_WHATSAPP,
                        STEP_EMAIL_ASK, STEP_NUDGE, STEP_REBOOK, STEP_RECAP,
                        STEP_REVIEW, STEP_VALUE, next_due_step,
                        seq_should_close, seq_stop_reason, within_send_window,
                        sibling_stop_reason)

HEARTBEAT_NAME = "outcome_sender"
CYCLE_SECONDS = 20 * 60          # 20 min: finest step granularity is 0h (no-show)
MAX_SENDS_PER_PASS = 12          # blast radius cap; a runaway loop stays small

BOOK_URL = "https://mwmcreations.com/book-studio/"
STUDIO_ADDRESS = "1500 Park Center Dr, Suite 230, Orlando, FL 32835"

_deps = {}


def configure(**kwargs):
    """Inject app.py's collaborators.

    Required: report_error, post_slack, send_email, send_whatsapp,
              send_instagram, pg_load, pg_save, heartbeat, lead_data,
              matt_channel, maya_channel, dev_channel
    """
    _deps.update(kwargs)


def _report(ctx, exc, detail=""):
    fn = _deps.get("report_error")
    if fn:
        try:
            fn("outcome_sender." + ctx, exc, detail)
            return
        except Exception:
            pass
    print(f"[OUTCOME SEQ] {ctx}: {exc} {detail}")


def _slack(channel_key, text):
    fn = _deps.get("post_slack")
    ch = _deps.get(channel_key)
    if fn and ch:
        try:
            fn(ch, text)
        except Exception as exc:
            print(f"[OUTCOME SEQ] slack post failed: {exc}")


def _first_name(name):
    n = str(name or "").strip()
    if not n:
        return "there"
    # Patch #42 taught us records can hold two people: "Krista Neeley (with
    # Michael Neeley)". Greet the first one, never the parenthetical.
    n = n.split("(")[0].strip()
    return n.split()[0] if n.split() else "there"


# ══════════════════════════════════════════════════════════════════════════
# COPY
#
# Written to be sendable as-is. Michael's constraints, stated repeatedly:
# warm, never pushy, never a chase, and it must not read as a machine. Every
# message gives the lead an easy way out, because #39's whole premise is that
# a sequence with an ending outperforms one that hounds.
# ══════════════════════════════════════════════════════════════════════════

def _escape(text):
    """Minimal HTML escape. `agreed_next` is free text Michael typed into a
    form and it is about to appear inside a client-facing email body."""
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _short_business(business):
    """Just the company name. Lead records carry descriptors after a dash —
    "Nest Seekers — Luxury Real Estate Advisor" — and the whole string reads
    badly mid-sentence in a client email."""
    b = str(business or "").strip()
    for sep in ("—", " - ", "|", "("):
        if sep in b:
            b = b.split(sep)[0].strip()
            break
    return b


def _email_copy(kind, first, business="", agreed_next=""):
    """(subject, html) for an email step."""
    biz = f" for {_short_business(business)}" if str(business or "").strip() else ""
    sign = ("<p>— Michael<br>"
            "<span style=\"color:#666\">MWM Creations &amp; Studios · Orlando</span></p>")

    if kind == STEP_NUDGE:
        # PATCH #46A — when the report recorded a concrete agreed next step,
        # say THAT. Rodolfo Silva agreed to send a script on Aug 7 and book an
        # hour the same day; the old copy would have asked him on Aug 6
        # whether he was "still thinking it over", which reads as though we
        # had forgotten our own meeting.
        if agreed_next:
            # DO NOT QUOTE THE NOTE. Caught in preview before shipping: Michael
            # writes his report notes in the THIRD PERSON about the client —
            # "he will send his script for my approval". Pasting that into an
            # email to that same client is worse than the generic copy it was
            # meant to improve. The note changes the FRAME of the message; it
            # never becomes the message. Michael's actual words stay internal.
            return (
                f"{first} — a nudge on our next step",
                f"<p>Hi {first},</p>"
                f"<p>Just a gentle nudge on the next step we agreed — whenever "
                f"you're ready, no rush at all.</p>"
                f"<p>If you need more time, tell me and I'll move it. If you're "
                f"set, reply and we'll get it moving.</p>" + sign)
        # PATCH #46A — the default no longer PRESUMES indecision. "Still
        # thinking it over?" only fits a lead who is undecided; to one who has
        # already committed it is mildly insulting. "Checking in" fits both.
        return (
            f"{first} — checking in",
            f"<p>Hi {first},</p>"
            f"<p>Great talking with you. Just checking in to see where things "
            f"stand{biz} — no pressure either way.</p>"
            f"<p>If the timing isn't right, tell me and I'll stop following up. "
            f"If it is, reply and I'll hold a slot for you.</p>" + sign)

    if kind == STEP_RECAP:
        return (
            f"{first} — a quick recap of what we discussed",
            f"<p>Hi {first},</p>"
            f"<p>Putting our conversation in writing so you have it in one place{biz}.</p>"
            f"<p>We film at our Orlando studio — {STUDIO_ADDRESS} — with cinema "
            f"cameras, broadcast lighting and professional audio, and you leave "
            f"with footage the same day.</p>"
            f"<p>Anything I've missed or got wrong, just reply and I'll fix it.</p>"
            + sign)

    if kind == STEP_VALUE:
        return (
            f"What a session in the studio actually looks like",
            f"<p>Hi {first},</p>"
            f"<p>One note and then I'll leave you be.</p>"
            f"<p>Most people come in for one shoot and leave with a month of "
            f"content — the long piece, plus the short cuts that come out of it. "
            f"That's usually the part that surprises them{biz}.</p>"
            f"<p>If you'd like to see the space before deciding, a studio visit "
            f"is free and takes twenty minutes: <a href=\"{BOOK_URL}\">{BOOK_URL}</a></p>"
            + sign)

    if kind == STEP_REBOOK:
        return (
            f"{first} — want to grab another time?",
            f"<p>Hi {first},</p>"
            f"<p>We missed each other today — no problem at all, it happens.</p>"
            f"<p>Pick any time that suits you here and I'll be there: "
            f"<a href=\"{BOOK_URL}\">{BOOK_URL}</a></p>"
            f"<p>Or just reply with a couple of times that work and I'll set it up.</p>"
            + sign)

    if kind == STEP_REVIEW:
        return (
            f"{first}, how did we do?",
            f"<p>Hi {first},</p>"
            f"<p>It was a pleasure having you in the studio{biz}. Hope you're happy "
            f"with how it turned out.</p>"
            f"<p>If you have two minutes, a short review genuinely helps a small "
            f"studio like ours — and if anything fell short instead, I'd rather "
            f"hear it from you directly. Just reply.</p>" + sign)

    if kind == STEP_EMAIL_ASK:
        # Only ever sent on a NON-email channel — asking for an email address
        # by email is the kind of thing that makes a system look unattended.
        return (
            f"{first} — best email for you?",
            f"<p>Hi {first},</p><p>What's the best email to reach you on?</p>" + sign)

    return (f"{first} — following up", f"<p>Hi {first},</p><p>Following up.</p>" + sign)


def _short_copy(kind, first, business="", agreed_next=""):
    """One-message text for WhatsApp / Instagram. Short on purpose: a DM that
    reads like an email is the fastest way to get muted."""
    if kind == STEP_NUDGE:
        # PATCH #46A — same rule as email: reference the agreed step when we
        # have one. Trimmed harder here; a DM carrying a 300-character quote
        # of Michael's own internal note is not a DM anyone reads.
        if agreed_next:
            # Same rule as the email: the internal note sets the FRAME, it is
            # never pasted to the client. See _email_copy for why.
            return (f"Hi {first}! Michael from MWM Creations 🙂 Just a nudge on the "
                    f"next step we agreed — no rush at all, and if you need more "
                    f"time just tell me and I'll move it.")
        return (f"Hi {first}! Michael from MWM Creations. Just checking in to see "
                f"where things stand — no pressure either way. If the timing isn't "
                f"right, tell me and I'll stop following up 🙂")
    if kind == STEP_REBOOK:
        return (f"Hi {first}, we missed each other today — no problem at all. "
                f"Want to grab another time? You can pick any slot here: {BOOK_URL} "
                f"— or just send me a couple of times that work.")
    if kind == STEP_RECAP:
        return (f"Hi {first}! Quick recap of what we talked about: we film at our "
                f"Orlando studio, cinema cameras and pro audio, and you leave with "
                f"your footage the same day. Anything I got wrong, just tell me.")
    if kind == STEP_VALUE:
        return (f"Hi {first} — one note and then I'll leave you be. Most people "
                f"come in for one shoot and leave with a month of content. If you'd "
                f"like to see the space first, a studio visit is free: {BOOK_URL}")
    if kind == STEP_REVIEW:
        return (f"Hi {first}! Hope you're happy with how the shoot turned out. If "
                f"you have two minutes, a short review really helps us — and if "
                f"anything fell short instead, I'd rather hear it from you directly.")
    if kind == STEP_EMAIL_ASK:
        return (f"Hi {first}! What's the best email for you? I'd like to send this "
                f"over properly rather than in a chat window.")
    return f"Hi {first}, following up from MWM Creations."


# ══════════════════════════════════════════════════════════════════════════
# DELIVERY
# ══════════════════════════════════════════════════════════════════════════

def _deliver(channel, kind, rec, key, seq):
    """(ok, note). Never raises — a bad step must not stop the pass."""
    first = _first_name(rec.get("name"))
    business = str(rec.get("business") or "").strip()
    email = str(seq.get("email") or rec.get("email") or "").strip()
    # PATCH #46A — sequences armed before #46 have no `agreed_next`; they fall
    # through to the neutral copy, which is why that default had to be fixed
    # too rather than only adding the context-aware branch.
    agreed = str(seq.get("agreed_next") or "").strip()

    if channel == CH_WEB:
        if not email:
            return False, "no email on record"
        subject, html = _email_copy(kind, first, business, agreed)
        res = _deps["send_email"](email, subject, html)
        if isinstance(res, dict):
            if res.get("suppressed"):
                # The DNC list working as designed. Stop the sequence — this
                # lead must not receive the remaining steps either.
                return False, f"SUPPRESSED: {res.get('error', '')}"
            return bool(res.get("ok")), str(res.get("error") or "")
        return bool(res), ""

    if channel == CH_WHATSAPP:
        phone = "".join(ch for ch in str(rec.get("phone") or key or "") if ch.isdigit())
        if not phone:
            return False, "no phone on record"
        res = _deps["send_whatsapp"](phone, _short_copy(kind, first, business, agreed))
        return bool(res), "" if res else "whatsapp send returned nothing"

    if channel == CH_INSTAGRAM:
        igsid = str(rec.get("igsid") or key or "").strip()
        if not igsid:
            return False, "no IGSID on record"
        res = _deps["send_instagram"](igsid, _short_copy(kind, first, business, agreed))
        # Outside the 24h window Meta returns a 403 and this comes back None.
        # #39 already routes around a known-closed window; this catches the
        # case where the window closed between arming and sending.
        return bool(res), "" if res else "IG send failed (24h window likely closed)"

    return False, f"unroutable channel {channel!r}"


def _escalate(key, rec, seq, kind, why):
    """No machine path can reach this lead. Hand it to a named human WITH the
    message, so the fallback costs them ten seconds rather than a decision."""
    first = _first_name(rec.get("name"))
    owner = (seq.get("owner") or "MAYA").upper()
    channel_key = "maya_channel" if owner == "MAYA" else "matt_channel"
    _slack(channel_key, (
        f":warning: *Sequence step needs a human — {rec.get('name') or key}*\n"
        f"*Outcome:* {seq.get('outcome')} · *Step:* {kind}\n"
        f"*Why the machine can't send it:* {why}\n"
        f"*Suggested message:*\n>{_short_copy(kind, first, rec.get('business') or '')}\n"
        f"_Patch #44B — armed by the event report, undeliverable on every "
        f"automated channel. Marked handled so the sequence does not retry._"))


# ══════════════════════════════════════════════════════════════════════════
# THE PASS
# ══════════════════════════════════════════════════════════════════════════

def _pass(now=None):
    """One scan over lead_data. Returns a summary dict for logging/tests."""
    lead_data = _deps.get("lead_data") or {}
    now = now or datetime.now()
    out = {"sent": 0, "closed": 0, "stopped": 0, "escalated": 0,
           "stale": 0, "waiting": 0, "failed": 0, "held_quiet_hours": 0}

    # QUIET HOURS. Bookkeeping (closing finished sequences, honouring stop
    # reasons) still runs — only client-facing sends are held until morning.
    _sendable = within_send_window(now)

    for key, rec in list(lead_data.items()):
        if out["sent"] >= MAX_SENDS_PER_PASS:
            break
        try:
            seq = rec.get("outcome_seq")
            if not isinstance(seq, dict):
                continue
            # PATCH #49C — undo the specific damage #48B did. Between its
            # deploy and #49 it closed sequences on the strength of a
            # duplicate's historical booking flag, which was never a valid
            # signal. The predicate is EXACT — only that reason, not "anything
            # ever stopped" — so this repairs a known bug rather than
            # resurrecting decisions that were made correctly.
            if seq.get("done") and str(seq.get("closed_reason") or "") == (
                    "a duplicate record for this person has a booking"):
                seq["done"] = False
                seq["closed_reason"] = ""
                seq.setdefault("reopened", []).append(
                    {"why": "closed by the #48B duplicate-booking rule, which "
                            "read a historical flag as a current commitment",
                     "at": now.isoformat()})
                _report("reopened", "sequence reopened by #49C",
                        f"lead={rec.get('name') or key}")
            if seq.get("done"):
                continue

            # PATCH #48B — a booking recorded on a DUPLICATE record has to
            # stop this sequence too. Matching on email is deliberate: it is
            # the field the sequence already sends to, so if two records share
            # it they are the same inbox and therefore the same person.
            _my_email = str(seq.get("email") or rec.get("email") or "").strip().lower()
            _sibs = []
            if _my_email:
                for _ok, _orec in lead_data.items():
                    if _ok == key or not isinstance(_orec, dict):
                        continue
                    if str(_orec.get("email") or "").strip().lower() == _my_email:
                        _sibs.append(_orec)
            stop = (seq_stop_reason(rec, seq)
                    or sibling_stop_reason(rec, _sibs, seq.get("armed_at")))
            if stop:
                seq["done"] = True
                seq["closed_reason"] = stop
                out["stopped"] += 1
                continue

            try:
                armed = datetime.fromisoformat(str(seq.get("armed_at")))
            except Exception:
                seq["done"] = True
                seq["closed_reason"] = "unparseable armed_at"
                _report("armed_at", "unparseable", f"lead={key}")
                continue
            if armed.tzinfo is not None:
                armed = armed.replace(tzinfo=None)

            elapsed_h = (now - armed).total_seconds() / 3600.0

            if seq_should_close(seq, elapsed_h / 24.0):
                seq["done"] = True
                seq["closed_reason"] = "reached close_after_days"
                out["closed"] += 1
                continue

            idx, step, status = next_due_step(seq, elapsed_h)
            if status == "finished":
                seq["done"] = True
                seq["closed_reason"] = "all steps sent"
                out["closed"] += 1
                continue
            if status == "waiting":
                out["waiting"] += 1
                continue

            _after, channel, kind = step

            if status == "stale":
                # Do not send a same-day rebook four days late. Skip forward
                # and say so — silence here would look like a working rail.
                seq["next_step"] = idx + 1
                seq.setdefault("skipped", []).append(
                    {"step": kind, "why": "stale", "at": now.isoformat()})
                out["stale"] += 1
                _report("stale_step", "skipped a step whose window had passed",
                        f"lead={key} step={kind} armed={seq.get('armed_at')}")
                continue

            if not _sendable:
                # Due, but it is the middle of the night. Hold — do not skip.
                out["held_quiet_hours"] += 1
                continue

            if channel == CH_UNKNOWN:
                _escalate(key, rec, seq, kind, "no reachable channel (CH_UNKNOWN)")
                seq["next_step"] = idx + 1
                seq.setdefault("escalated", []).append(kind)
                out["escalated"] += 1
                continue

            ok, note = _deliver(channel, kind, rec, key, seq)

            if ok:
                seq["next_step"] = idx + 1
                seq.setdefault("sent", []).append(
                    {"step": kind, "channel": channel, "at": now.isoformat()})
                out["sent"] += 1
                try:
                    _deps["pg_save"]("outcome_seq:" + str(key), seq)
                except Exception:
                    pass
                print(f"[OUTCOME SEQ] {kind} -> {channel} -> {key}")
            elif note.startswith("SUPPRESSED"):
                # Do-not-contact. Kill the whole sequence, not just this step.
                seq["done"] = True
                seq["closed_reason"] = note
                out["stopped"] += 1
            else:
                # One failure is not a reason to abandon a lead, but it IS a
                # reason to escalate rather than retry the same wall forever.
                _escalate(key, rec, seq, kind, note or "send failed")
                seq["next_step"] = idx + 1
                out["failed"] += 1
        except Exception as exc:
            _report("pass", exc, f"lead={key}")

    return out


def loop():
    """Background thread. Heartbeat name: outcome_sender."""
    import time as _time
    print(f"[OUTCOME SEQ] Started — {CYCLE_SECONDS // 60} min cycle "
          f"(Patch #44B: executes the sequences #39 arms)")
    hb = _deps.get("heartbeat")
    while True:
        try:
            if hb:
                hb(HEARTBEAT_NAME)
            summary = _pass()
            if any(summary[k] for k in ("sent", "closed", "escalated", "stale", "failed")):
                print(f"[OUTCOME SEQ] {summary}")
        except Exception as exc:
            _report("loop", exc)
        _time.sleep(CYCLE_SECONDS)
