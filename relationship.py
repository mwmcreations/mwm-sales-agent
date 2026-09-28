"""
relationship.py — PATCH #138. Know who you are talking to before you sell.

WHAT HAPPENED (28 Sep 2026)
───────────────────────────
Michael: "She will treat a lead the same way she would treat a client or a
friend or someone that has been a client."  The @mwm.creations inbox, that
morning:

  · Margaret ❤️, Rose Lopes, Claudio De Los Santos, Frederico Souza Bento Neto,
    Wikle Earl, Alma Gonzalez Aleman, Andino Films, Matheus Santos — each
    shared a post or a reel and got the same canned bot line:
    "Thanks for sharing! How can I help you today? 😊"
    That line is hard-coded in the IG webhook and fires for ANY attachment
    without text, before anything checks who the sender is.
  · Victory Martial Arts — one of our biggest clients — replied to a story
    and Maya answered "Anything I can help you with — maybe video content for
    the academy?"  The client roster could not see them, and nothing else
    said "we know these people".
  · Paying clients whose own record already says client got NO client mode,
    because _known_client_lookup() returns (False, "already_marked") for them
    — a guard written for the pipeline card (don't re-announce) that the
    Patch #111 client-mode branch then read as "not a client".

THE RULE
────────
Three kinds of person write to @mwm.creations:

  client          a paying (or past) client — roster / client index / record.
                  Maya answers as client service (Patch #111 block). A bare
                  share or reaction from a client gets NO bot reply; it goes
                  to Michael.
  known_personal  someone @mwm.creations FOLLOWS on Instagram (Graph API
                  is_business_follow_user). Friends, family, partners,
                  colleagues. Maya stays QUIET. The message is mirrored to
                  #maya-shadow with a ping so Michael answers personally in
                  the thread. They never enter the lead pipeline.
  lead            everyone else. Unchanged.

An ad click outranks a follow: someone who arrives from one of our ads is
treated as a lead even if we follow them (they asked about the offer).

The bias, as with known_client.py: when a signal is missing or failed, the
answer is "lead" — the machine keeps working as it did before this patch.
"""

CLIENT = "client"
KNOWN = "known_personal"
LEAD = "lead"

# How long a follow check stays fresh before we ask Instagram again.
FOLLOW_TTL_S = 7 * 24 * 3600

# Graph API fields. The follow fields exist on the Instagram User Profile API
# (IGSID lookups). Some tokens / API versions refuse them, so callers must be
# ready to fall back to BASIC_FIELDS.
PROFILE_FIELDS = "name,username,is_business_follow_user,is_user_follow_business"
BASIC_FIELDS = "name,username"


def follow_flags(profile_json):
    """Graph API profile -> (we_follow, they_follow). None when unknown.

    Only a literal JSON true/false counts. Missing, null or anything else is
    "unknown" (None), never False — unknown must not look like "not a friend"
    in logs, and never like "friend" in decisions."""
    if not isinstance(profile_json, dict):
        return None, None

    def _b(v):
        return v if isinstance(v, bool) else None

    return (_b(profile_json.get("is_business_follow_user")),
            _b(profile_json.get("is_user_follow_business")))


def follow_check_due(rec, now_ts):
    """True when this record's follow flag is missing or stale."""
    if not isinstance(rec, dict):
        return True
    ts = rec.get("ig_follow_checked_ts")
    try:
        return (now_ts - float(ts)) > FOLLOW_TTL_S
    except (TypeError, ValueError):
        return True


def classify(rec, client_hit=False):
    """(kind, why) for one sender.

    rec          the sender's lead_data record (dict)
    client_hit   the result of the client lookup (roster / index / own record)
    """
    rec = rec if isinstance(rec, dict) else {}
    if client_hit:
        return CLIENT, "client"
    if rec.get("ad_referral") or rec.get("ad_id"):
        return LEAD, "ad_referral"
    if rec.get("ig_we_follow") is True:
        return KNOWN, "we_follow_on_instagram"
    return LEAD, "no_relationship_signal"


_ATT_LABELS = {
    "share": "shared a post",
    "ig_reel": "shared a reel",
    "reel": "shared a reel",
    "story_mention": "mentioned us in their story",
    "image": "sent a photo",
    "video": "sent a video",
    "audio": "sent a voice message",
    "file": "sent a file",
    "animated_image": "sent a GIF",
    "like_heart": "sent a ❤️",
}


def attachment_text(att_type):
    """The line that stands in for a text-less attachment, e.g.
    '[Shared a reel]'. Used for history and the #maya-shadow mirror."""
    label = _ATT_LABELS.get(str(att_type or "").strip().lower(), "sent an attachment")
    return "[%s]" % (label[:1].upper() + label[1:])


def quiet_note(kind, michael_slack_id=""):
    """The line added under the mirrored inbound message when Maya stays
    quiet, so the ping says what happened and what to do."""
    who = {
        CLIENT: "a current client",
        KNOWN: "someone @mwm.creations follows (personal contact)",
    }.get(kind, "a known contact")
    ping = ("<@%s> " % michael_slack_id) if michael_slack_id else ""
    return ("\n\n:handshake: %s_This is %s. Maya did NOT reply._ "
            "Reply in this thread to answer them yourself." % (ping, who))


def should_stay_quiet(kind, attachment_only):
    """Maya stays out of it for personal contacts always, and for clients
    when there is nothing to answer (a share, a reaction, a story mention)."""
    if kind == KNOWN:
        return True
    if kind == CLIENT and attachment_only:
        return True
    return False
