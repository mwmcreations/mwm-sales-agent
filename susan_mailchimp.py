"""
Susan Mailchimp Action Handlers — Real-time Slack action capability for Susan (Email Marketing Agent).

Handles:
- List campaigns (drafts, scheduled, sent)
- Get campaign stats (open rate, click rate, sends)
- Pause/cancel a scheduled campaign
- Schedule a draft campaign
- Update campaign subject line or preview text
- Send a test email
- List audiences/lists

Uses MAILCHIMP_API_KEY from Railway env vars.
Mailchimp Marketing API v3 — REST-based, no SDK needed.
"""

import os
import re
import json
import pytz
from datetime import datetime

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY", "")
# Mailchimp API key format: "key-us14" — server prefix is after the dash
MAILCHIMP_SERVER = MAILCHIMP_API_KEY.split("-")[-1] if "-" in MAILCHIMP_API_KEY else ""
MAILCHIMP_BASE_URL = f"https://{MAILCHIMP_SERVER}.api.mailchimp.com/3.0" if MAILCHIMP_SERVER else ""
TIMEZONE = "America/New_York"


def _mc_headers():
    """Return auth headers for Mailchimp API."""
    return {
        "Authorization": f"Bearer {MAILCHIMP_API_KEY}",
        "Content-Type": "application/json",
    }


def _mc_get(endpoint, params=None):
    """Make a GET request to Mailchimp API."""
    if not MAILCHIMP_BASE_URL:
        raise RuntimeError("MAILCHIMP_API_KEY not configured")
    url = f"{MAILCHIMP_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.get(url, headers=_mc_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _mc_post(endpoint, data=None):
    """Make a POST request to Mailchimp API."""
    if not MAILCHIMP_BASE_URL:
        raise RuntimeError("MAILCHIMP_API_KEY not configured")
    url = f"{MAILCHIMP_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.post(url, headers=_mc_headers(), json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _mc_patch(endpoint, data=None):
    """Make a PATCH request to Mailchimp API."""
    if not MAILCHIMP_BASE_URL:
        raise RuntimeError("MAILCHIMP_API_KEY not configured")
    url = f"{MAILCHIMP_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.patch(url, headers=_mc_headers(), json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Intent Detection ────────────────────────────────────────────────
SUSAN_ACTION_INTENTS = {
    "list_campaigns": [
        r"(?:list|show|get|pull|what)\s*(?:are\s+)?(?:the\s+|my\s+|our\s+)?(?:campaigns?|emails?|drafts?|sends?)",
        r"(?:what|which)\s+(?:campaigns?|emails?)\s+(?:do\s+)?(?:we|i)\s+have",
        r"(?:campaign|email)\s*(?:list|status|overview|summary)",
        r"(?:any|all)\s+(?:draft|scheduled|sent)\s+(?:campaigns?|emails?)",
    ],
    "campaign_stats": [
        r"(?:stats?|statistics?|metrics?|performance|results?|numbers?)\s+(?:for|on|of)\s+(.+)",
        r"(?:open|click)\s*(?:rate|through)\s+(?:for|on|of)\s+(.+)",
        r"(?:how\s+(?:did|is|was))\s+(.+?)\s+(?:do(?:ing)?|perform(?:ing)?)",
        r"(?:what(?:'s| is| are)\s+the)\s+(?:stats?|open rate|click rate|results?)\s+(?:for|on)\s+(.+)",
    ],
    "pause_campaign": [
        r"(?:pause|stop|cancel|hold|unschedule)\s+(?:the\s+)?(?:campaign|email|send)\s*(?:for|called|named)?\s*(.+)?",
        r"(?:pause|stop|cancel|hold)\s+(.+?)(?:\s+campaign|\s+email)?$",
    ],
    "schedule_campaign": [
        r"(?:schedule|send|queue)\s+(?:the\s+)?(?:campaign|email|draft)\s*(?:for|called|named)?\s*(.+?)\s+(?:for|at|on)\s+(.+)",
        r"(?:schedule|send|queue)\s+(.+?)\s+(?:for|at|on)\s+(.+)",
    ],
    "update_campaign": [
        r"(?:update|change|edit|modify)\s+(?:the\s+)?(?:subject|subject\s+line|preview|preview\s+text)\s+(?:on|for|of)\s+(.+?)\s+to\s+(.+)",
        r"(?:change|update)\s+(.+?)(?:'s|s)?\s+(?:subject|subject\s+line|preview)\s+to\s+(.+)",
    ],
    "send_test_email": [
        r"(?:send|fire)\s+(?:me\s+)?(?:a\s+)?(?:test|preview)\s+(?:email\s+)?(?:for|of)\s+(.+)",
        r"(?:test|preview)\s+(?:the\s+)?(?:campaign|email)\s+(.+)",
        r"(?:send|fire)\s+(?:me\s+)?(?:a\s+)?(?:test|preview)\s+(?:to\s+.+?\s+)?(?:for|of)\s+(.+)",
    ],
    "list_audiences": [
        r"(?:list|show|get|what)\s*(?:are\s+)?(?:the\s+|my\s+|our\s+)?(?:audiences?|lists?|segments?|subscribers?)",
        r"(?:how\s+many)\s+(?:subscribers?|contacts?|people)",
    ],
}


def _find_campaign_by_name(campaigns, search_text):
    """Fuzzy match a campaign by name against title and subject line.
    Returns the best matching campaign dict or None.
    """
    search_lower = search_text.lower().strip()
    search_words = [w for w in search_lower.split() if len(w) > 1]
    target = None
    best_score = 0

    for c in campaigns:
        title = c.get("settings", {}).get("title", "").lower()
        subject = c.get("settings", {}).get("subject_line", "").lower()
        combined = f"{title} {subject}"

        # Exact substring match — highest priority
        if search_lower in title or search_lower in subject:
            return c

        # Word overlap scoring — flexible fuzzy match
        if search_words:
            matches = sum(1 for w in search_words if w in combined)
            score = matches / len(search_words)
            if score > best_score and score >= 0.5:
                best_score = score
                target = c

    return target


def detect_susan_intent(text):
    """Detect if text contains a Susan action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "susan" prefix if present
    text_lower = re.sub(r"^(?:susan|hey\s+susan|hi\s+susan)[,:\s]*", "", text_lower).strip()

    for intent, patterns in SUSAN_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def list_campaigns(text):
    """List campaigns with optional status filter."""
    try:
        # Check for status filter
        text_lower = text.lower()
        status_filter = None
        if "draft" in text_lower:
            status_filter = "save"
        elif "schedul" in text_lower:
            status_filter = "schedule"
        elif "sent" in text_lower or "send" in text_lower:
            status_filter = "sent"

        params = {"count": 20, "sort_field": "send_time", "sort_dir": "DESC"}
        if status_filter:
            params["status"] = status_filter

        data = _mc_get("/campaigns", params=params)
        campaigns = data.get("campaigns", [])

        if not campaigns:
            filter_text = f" with status '{status_filter}'" if status_filter else ""
            return f"📧 *No campaigns found{filter_text}.*"

        status_emoji = {
            "save": "📝", "paused": "⏸️", "schedule": "📅",
            "sending": "📤", "sent": "✅",
        }

        lines = [f"📧 *Mailchimp Campaigns* — {len(campaigns)} found\n"]
        for c in campaigns:
            emoji = status_emoji.get(c.get("status", ""), "•")
            title = c.get("settings", {}).get("title", "(untitled)")
            subject = c.get("settings", {}).get("subject_line", "")
            status = c.get("status", "unknown")
            send_time = c.get("send_time", "")
            list_name = c.get("recipients", {}).get("list_name", "")

            line = f"{emoji} *{title}*"
            if subject and subject != title:
                line += f" — _{subject}_"
            line += f"\n  Status: {status}"
            if send_time:
                line += f" | Sent: {send_time[:16]}"
            if list_name:
                line += f" | Audience: {list_name}"
            lines.append(line)

        return "\n".join(lines)
    except Exception as e:
        print(f"[Susan] List campaigns error: {e}")
        return f"⚠️ Error listing campaigns: {str(e)[:200]}"


def get_campaign_stats(text):
    """Get stats for a specific campaign."""
    try:
        # Extract campaign name from text
        text_clean = re.sub(
            r"^(?:susan[,:\s]*)?(?:stats?|statistics?|metrics?|performance|results?|numbers?|open\s*rate|click\s*rate|how\s+(?:did|is|was))\s+(?:for|on|of|the)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip().strip('"\'')

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which campaign? Give me a name or part of the subject line."

        # Search campaigns to find a match
        data = _mc_get("/campaigns", params={"count": 50, "sort_field": "send_time", "sort_dir": "DESC"})
        campaigns = data.get("campaigns", [])
        target = _find_campaign_by_name(campaigns, text_clean)

        if not target:
            return f'🔍 No campaign found matching *"{text_clean}"*. Try listing all campaigns first to see exact names.'

        campaign_id = target["id"]
        title = target.get("settings", {}).get("title", "(untitled)")
        subject = target.get("settings", {}).get("subject_line", "")
        status = target.get("status", "unknown")

        # Only sent campaigns have report stats
        if status != "sent":
            return (
                f"📧 *{title}*\n"
                f"  Subject: _{subject}_\n"
                f"  Status: {status}\n"
                f"  _Stats are only available for sent campaigns._"
            )

        # Fetch report
        report = _mc_get(f"/reports/{campaign_id}")
        opens = report.get("opens", {})
        clicks = report.get("clicks", {})
        emails_sent = report.get("emails_sent", 0)
        bounces = report.get("bounces", {})
        unsubscribes = report.get("unsubscribed", 0)

        open_rate = opens.get("open_rate", 0) * 100
        click_rate = clicks.get("click_rate", 0) * 100
        unique_opens = opens.get("unique_opens", 0)
        unique_clicks = clicks.get("unique_clicks", 0)
        hard_bounces = bounces.get("hard_bounces", 0)
        soft_bounces = bounces.get("soft_bounces", 0)

        return (
            f"📊 *Campaign Stats: {title}*\n"
            f"  Subject: _{subject}_\n\n"
            f"  📨 *Sent:* {emails_sent:,}\n"
            f"  📬 *Opens:* {unique_opens:,} ({open_rate:.1f}%)\n"
            f"  🖱️ *Clicks:* {unique_clicks:,} ({click_rate:.1f}%)\n"
            f"  ↩️ *Bounces:* {hard_bounces + soft_bounces} (hard: {hard_bounces}, soft: {soft_bounces})\n"
            f"  🚫 *Unsubscribes:* {unsubscribes}"
        )
    except Exception as e:
        print(f"[Susan] Campaign stats error: {e}")
        return f"⚠️ Error getting campaign stats: {str(e)[:200]}"


def pause_campaign(text):
    """Pause/cancel a scheduled campaign."""
    try:
        text_clean = re.sub(
            r"^(?:susan[,:\s]*)?(?:pause|stop|cancel|hold|unschedule)\s+(?:the\s+)?(?:campaign|email|send)?\s*(?:for|called|named)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().strip('"\'')

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which campaign should I pause? Give me a name."

        # Find the campaign
        data = _mc_get("/campaigns", params={"count": 50})
        campaigns = data.get("campaigns", [])
        target = _find_campaign_by_name(campaigns, text_clean)

        if not target:
            return f'🔍 No campaign found matching *"{text_clean}"*.'

        campaign_id = target["id"]
        title = target.get("settings", {}).get("title", "(untitled)")
        status = target.get("status", "")

        if status != "schedule":
            return f"⏸️ *{title}* is currently `{status}` — can only pause scheduled campaigns."

        # Unschedule it
        http_requests.post(
            f"{MAILCHIMP_BASE_URL}/campaigns/{campaign_id}/actions/unschedule",
            headers=_mc_headers(),
            timeout=15,
        ).raise_for_status()

        return f"⏸️ *Campaign paused!*\n• *Name:* {title}\n• *Status:* scheduled → paused (draft)"
    except Exception as e:
        print(f"[Susan] Pause campaign error: {e}")
        return f"⚠️ Error pausing campaign: {str(e)[:200]}"


def schedule_campaign(text):
    """Schedule a draft campaign to send at a specific time."""
    try:
        text_clean = re.sub(
            r"^(?:susan[,:\s]*)?(?:schedule|send|queue)\s+(?:the\s+)?(?:campaign|email|draft)?\s*(?:for|called|named)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip()

        # Try to extract name and datetime
        match = re.search(
            r"(.+?)\s+(?:for|at|on)\s+(.+)",
            text_clean, re.IGNORECASE
        )
        if not match:
            return "🤔 I need a campaign name and a time. Try: *schedule Email 1 for tomorrow at 10am*"

        campaign_name = match.group(1).strip().strip('"\'')
        datetime_text = match.group(2).strip()

        # Find the campaign
        data = _mc_get("/campaigns", params={"count": 50})
        campaigns = data.get("campaigns", [])
        target = _find_campaign_by_name(campaigns, campaign_name)

        if not target:
            return f'🔍 No campaign found matching *"{campaign_name}"*.'

        campaign_id = target["id"]
        title = target.get("settings", {}).get("title", "(untitled)")
        status = target.get("status", "")

        if status != "save":
            return f"📅 *{title}* is currently `{status}` — can only schedule draft campaigns."

        # Parse datetime (basic parsing)
        from ana_calendar import parse_event_details
        details = parse_event_details(f"something {datetime_text}")
        if not details.get("start_date") or not details.get("start_time"):
            return f"🤔 Couldn't parse the schedule time from *\"{datetime_text}\"*. Try: *tomorrow at 10am* or *April 10 at 2pm*"

        # Build UTC datetime for Mailchimp
        tz = pytz.timezone(TIMEZONE)
        local_dt = datetime.strptime(
            f"{details['start_date']} {details['start_time']}", "%Y-%m-%d %H:%M"
        )
        local_dt = tz.localize(local_dt)
        utc_dt = local_dt.astimezone(pytz.UTC)
        schedule_time = utc_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Schedule it
        http_requests.post(
            f"{MAILCHIMP_BASE_URL}/campaigns/{campaign_id}/actions/schedule",
            headers=_mc_headers(),
            json={"schedule_time": schedule_time},
            timeout=15,
        ).raise_for_status()

        local_str = local_dt.strftime("%b %d, %Y at %I:%M %p %Z")
        return (
            f"📅 *Campaign scheduled!*\n"
            f"• *Name:* {title}\n"
            f"• *Send time:* {local_str}\n"
            f"• *Status:* draft → scheduled"
        )
    except Exception as e:
        print(f"[Susan] Schedule campaign error: {e}")
        return f"⚠️ Error scheduling campaign: {str(e)[:200]}"


def update_campaign(text):
    """Update a campaign's subject line or preview text."""
    try:
        text_clean = re.sub(
            r"^(?:susan[,:\s]*)?",
            "", text.strip(), flags=re.IGNORECASE
        ).strip()

        # Detect what to update
        updating_subject = bool(re.search(r"subject", text_clean, re.IGNORECASE))
        updating_preview = bool(re.search(r"preview", text_clean, re.IGNORECASE))

        # Extract campaign name and new value
        match = re.search(
            r"(?:update|change|edit|modify)\s+(?:the\s+)?(?:subject(?:\s+line)?|preview(?:\s+text)?)\s+(?:on|for|of)\s+(.+?)\s+to\s+(.+)",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"(?:change|update)\s+(.+?)(?:'s|s)?\s+(?:subject(?:\s+line)?|preview(?:\s+text)?)\s+to\s+(.+)",
                text_clean, re.IGNORECASE
            )
        if not match:
            return "🤔 I need a campaign name and the new text. Try: *update subject on Email 1 to New Subject Line*"

        campaign_name = match.group(1).strip().strip('"\'')
        new_value = match.group(2).strip().strip('"\'')

        # Find the campaign
        data = _mc_get("/campaigns", params={"count": 50})
        campaigns = data.get("campaigns", [])
        target = _find_campaign_by_name(campaigns, campaign_name)

        if not target:
            return f'🔍 No campaign found matching *"{campaign_name}"*.'

        campaign_id = target["id"]
        title = target.get("settings", {}).get("title", "(untitled)")

        # Build update payload
        settings_update = {}
        if updating_subject:
            settings_update["subject_line"] = new_value
        elif updating_preview:
            settings_update["preview_text"] = new_value
        else:
            settings_update["subject_line"] = new_value  # default to subject

        _mc_patch(f"/campaigns/{campaign_id}", data={"settings": settings_update})

        field = "subject line" if updating_subject or not updating_preview else "preview text"
        return (
            f"✅ *Campaign updated!*\n"
            f"• *Name:* {title}\n"
            f"• *{field.title()}:* {new_value}"
        )
    except Exception as e:
        print(f"[Susan] Update campaign error: {e}")
        return f"⚠️ Error updating campaign: {str(e)[:200]}"


def send_test_email(text):
    """Send a test email for a campaign to michael@mwmcreations.com."""
    try:
        text_clean = re.sub(
            r"^(?:susan[,:\s]*)?(?:send|fire)\s+(?:me\s+)?(?:a\s+)?(?:test|preview)\s+(?:email\s+)?(?:to\s+\S+\s+)?(?:for|of)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().strip('"\'')

        if not text_clean:
            text_clean = re.sub(
                r"^(?:susan[,:\s]*)?(?:test|preview)\s+(?:the\s+)?(?:campaign|email)\s*",
                "", text.strip(), flags=re.IGNORECASE
            ).strip().strip('"\'')

        # Fallback: if text_clean still has action words, try extracting after "for/of"
        if text_clean and re.match(r"(?:send|fire|test|preview|me|a|the|email)\b", text_clean, re.IGNORECASE):
            for_match = re.search(r"\b(?:for|of)\s+(.+)", text.strip(), re.IGNORECASE)
            if for_match:
                text_clean = for_match.group(1).strip().strip('"\'')


        if not text_clean or len(text_clean) < 2:
            return "🤔 Which campaign should I send a test for? Give me a name."

        # Find the campaign — try drafts first, then all statuses
        data = _mc_get("/campaigns", params={"count": 50, "status": "save"})
        campaigns = data.get("campaigns", [])
        target = _find_campaign_by_name(campaigns, text_clean)

        if not target:
            # Broaden to all statuses
            data = _mc_get("/campaigns", params={"count": 50})
            campaigns = data.get("campaigns", [])
            target = _find_campaign_by_name(campaigns, text_clean)

        if not target:
            return f'🔍 No campaign found matching *"{text_clean}"*.'

        campaign_id = target["id"]
        title = target.get("settings", {}).get("title", "(untitled)")
        status = target.get("status", "unknown")

        # Mailchimp only allows test sends for draft (save) or paused campaigns
        if status == "sent":
            return f"📧 *{title}* has already been sent — test emails are only available for draft campaigns."

        # Send test email
        test_emails = ["michael@mwmcreations.com"]
        resp = http_requests.post(
            f"{MAILCHIMP_BASE_URL}/campaigns/{campaign_id}/actions/test",
            headers=_mc_headers(),
            json={"test_emails": test_emails, "send_type": "html"},
            timeout=15,
        )
        if not resp.ok:
            error_detail = resp.text[:200] if resp.text else f"HTTP {resp.status_code}"
            return f"⚠️ Mailchimp error sending test for *{title}* (status: {status}): {error_detail}"

        return (
            f"✅ *Test email sent!*\n"
            f"• *Campaign:* {title}\n"
            f"• *Sent to:* michael@mwmcreations.com\n"
            f"• Check your inbox!"
        )
    except Exception as e:
        print(f"[Susan] Send test email error: {e}")
        return f"⚠️ Error sending test email: {str(e)[:200]}"


def list_audiences(text):
    """List Mailchimp audiences/lists with subscriber counts."""
    try:
        data = _mc_get("/lists", params={"count": 20})
        lists = data.get("lists", [])

        if not lists:
            return "📋 *No audiences found in Mailchimp.*"

        lines = [f"📋 *Mailchimp Audiences* — {len(lists)} found\n"]
        for lst in lists:
            name = lst.get("name", "(untitled)")
            member_count = lst.get("stats", {}).get("member_count", 0)
            unsubscribe_count = lst.get("stats", {}).get("unsubscribe_count", 0)
            open_rate = lst.get("stats", {}).get("open_rate", 0) * 100

            lines.append(
                f"• *{name}*\n"
                f"  👥 {member_count:,} subscribers | "
                f"📬 {open_rate:.1f}% avg open rate | "
                f"🚫 {unsubscribe_count:,} unsubscribes"
            )

        return "\n".join(lines)
    except Exception as e:
        print(f"[Susan] List audiences error: {e}")
        return f"⚠️ Error listing audiences: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "list_campaigns": list_campaigns,
    "campaign_stats": get_campaign_stats,
    "pause_campaign": pause_campaign,
    "schedule_campaign": schedule_campaign,
    "update_campaign": update_campaign,
    "send_test_email": send_test_email,
    "list_audiences": list_audiences,
}


def handle_susan_action(text):
    """Check if text matches a Susan action intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_susan_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[Susan] Action intent detected: {intent} (matched: '{match.group(0)}')")
        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result

    return False, None
