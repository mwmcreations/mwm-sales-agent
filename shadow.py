#!/usr/bin/env python3
"""
shadow.py — PATCH #95. Making a shadow conversation findable by a human.

WHAT WENT WRONG
---------------
On 26 Aug 2026 Michael went looking in #maya-shadow for the conversation that
had just booked a studio visit, and could not find it. It was there. Three
things hid it:

1. THE THREAD NEVER EXPIRES. One Slack thread per phone number, forever, and
   the map is persisted in Postgres — so a lead who returns after seven weeks
   has today's conversation posted as replies under a parent from 5 July.
   The channel timeline shows NOTHING for today. Michael scrolled, saw an empty
   day, and was right to.

2. THE CARD IS NAMED ONCE, WHEN WE KNOW NOTHING. The header is written on the
   first inbound, where the name is usually "Unknown" and there is no email and
   no company. Five minutes later the lead gives all three — and the card still
   says "Conversation with Unknown". Even scrolling to the right day could not
   have identified it.

3. (not fixed here, but stated) Instagram page-scoped IDs are rendered with a
   leading "+" so they read as phone numbers, which buries the real ones.

THE RULES
---------
· A conversation that resumes after a quiet gap gets a NEW card, so the channel
  reads as a timeline of what happened when.
· A card is renamed the moment we learn who it is.
· Neither rule may ever prevent the message from being mirrored. A shadow log
  is a convenience; losing a line of it must never cost a reply to a lead.

KEY: a log nobody can find is not a log.
"""

import os

# A conversation picked up after this long is a new episode to a human reading
# the channel, so it gets its own card.
SHADOW_THREAD_MAX_IDLE_DAYS = float(os.getenv("SHADOW_THREAD_MAX_IDLE_DAYS", "3"))

DAY_SECONDS = 86400.0

# Names that carry no information — a card wearing one of these should be
# renamed as soon as anything better arrives.
PLACEHOLDER_NAMES = ("", "unknown", "unknown lead", "there", "none", "null", "lead")


def is_placeholder_name(name):
    """True when `name` tells a human nothing about who this is."""
    return str(name or "").strip().lower() in PLACEHOLDER_NAMES


def idle_days(last_epoch, now_epoch):
    """Days since the last message on a thread. None when we have no record."""
    if not last_epoch:
        return None
    return max(0.0, (float(now_epoch) - float(last_epoch)) / DAY_SECONDS)


def should_start_new_thread(thread_ts, last_epoch, now_epoch,
                            max_idle_days=None):
    """
    Start a fresh card when there is no thread yet, or when the existing one has
    been quiet longer than the window.

    A thread with no recorded last-activity is treated as STALE: it predates
    this patch, which means it is exactly the months-old kind that caused the
    problem.
    """
    if not thread_ts:
        return True
    if max_idle_days is None:
        max_idle_days = SHADOW_THREAD_MAX_IDLE_DAYS
    d = idle_days(last_epoch, now_epoch)
    if d is None:
        return True
    return d > float(max_idle_days)


def header_text(name, pretty_phone, email="", role="", resumed_after_days=None,
                business=""):
    """The card that sits at the top of a shadow thread."""
    shown = name if not is_placeholder_name(name) else "Unknown"
    lines = ["📱 *Conversation with %s* — `%s`" % (shown, pretty_phone)]
    if business:
        lines.append("🏢 %s" % business)
    if email:
        lines.append("✉️ %s" % email)
    if role:
        lines.append("👤 Role: %s" % role)
    if resumed_after_days is not None and resumed_after_days >= 1:
        n = int(round(resumed_after_days))
        lines.append("🔁 Returning lead — first message in %d day%s"
                     % (n, "" if n == 1 else "s"))
    return "\n".join(lines)


def better_name(old_name, new_name):
    """
    The name a card should carry now, or None when it should be left alone.

    Only ever replaces a placeholder with something real — it never overwrites
    a name a human may have come to recognise.
    """
    if is_placeholder_name(new_name):
        return None
    if not is_placeholder_name(old_name):
        return None
    return str(new_name).strip()


def should_rename(old_name, new_name, old_email="", new_email=""):
    """True when the card is carrying less than we now know."""
    if better_name(old_name, new_name):
        return True
    return bool(new_email) and not old_email
