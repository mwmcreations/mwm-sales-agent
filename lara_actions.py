"""
LARA Action Handlers — Client & Production Manager Agent.

Handles:
- Production Tracker (Google Sheets) — read/update client production status
- Calendar access (reuses Google Calendar DWD)
- Gmail integration — read/send emails for client communication

Uses GOOGLE_CREDENTIALS_JSON + GOOGLE_DELEGATE_EMAIL (DWD) from Railway env vars.
Production Tracker sheet ID stored in GOOGLE_SHEETS_PRODUCTION_ID.
"""

import os
import re
import json
import pytz
from datetime import datetime, timedelta
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── Config ──────────────────────────────────────────────────────────
TIMEZONE = "America/New_York"
PRODUCTION_SHEET_ID = os.getenv("GOOGLE_SHEETS_PRODUCTION_ID", "")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "c_03s30bthurplevpk6a264h7n34@group.calendar.google.com")
DELEGATE_EMAIL = os.getenv("GOOGLE_DELEGATE_EMAIL", "michael@mwmcreations.com")

SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets",
]

SCOPES_CALENDAR = [
    "https://www.googleapis.com/auth/calendar",
]

SCOPES_GMAIL = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

PRODUCTION_HEADERS = [
    "Client", "Email", "Phone", "Service",
    "Script Status", "Shoot Date", "Shoot Confirmed",
    "Team Briefed", "Last Client Contact", "Content Status",
    "Notes",
]

# 11 MWM clients
MWM_CLIENTS = [
    {"name": "Victory Martial Arts", "email": "brian@victoryma.com", "phone": "+14075551001", "service": "Video Pro Plan"},
    {"name": "Green Rest Mattress", "email": "info@greenrestmattress.com", "phone": "+14075551002", "service": "Video Production"},
    {"name": "One Stop Financial", "email": "info@onestopfinancial.com", "phone": "+14075551003", "service": "ROADMAP"},
    {"name": "Dr. Phillips Chiropractic", "email": "office@drphillipschiro.com", "phone": "+14075551004", "service": "Video Pro Plan"},
    {"name": "Orlando Dance Academy", "email": "info@orlandodanceacademy.com", "phone": "+14075551005", "service": "Content Package"},
    {"name": "Sunshine Pediatrics", "email": "admin@sunshinepediatrics.com", "phone": "+14075551006", "service": "Video Pro Plan"},
    {"name": "Lake Nona Realty", "email": "contact@lakenonarealty.com", "phone": "+14075551007", "service": "ROADMAP"},
    {"name": "FitLife Gym Orlando", "email": "manager@fitlifegym.com", "phone": "+14075551008", "service": "Video Production"},
    {"name": "Bella Cucina Restaurant", "email": "info@bellacucinaorl.com", "phone": "+14075551009", "service": "Content Package"},
    {"name": "TechStart Academy", "email": "hello@techstartacademy.com", "phone": "+14075551010", "service": "ROADMAP"},
    {"name": "Prestige Auto Detailing", "email": "book@prestigeautodetail.com", "phone": "+14075551011", "service": "Video Production"},
]


# ── Intent Detection ────────────────────────────────────────────────
LARA_ACTION_INTENTS = {
    "production_overview": [
        r"(?:production|project|client)\s*(?:status|summary|overview|report|board|tracker)",
        r"how(?:'s| is| are) (?:the |our )?(?:production|projects?|clients?|pipeline)",
        r"(?:show|get|pull|give)\s+(?:me\s+)?(?:the\s+)?(?:production|tracker|project)\s*(?:status|board|overview)?",
        r"what.?s (?:the )?status (?:of |on )?(?:all |our )?(?:productions?|projects?|clients?)",
        r"(?:como\s+est[aá]|status)\s+(?:da|das|dos)?\s*(?:produ[cç][aã]o|projetos?|clientes?)",
    ],
    "client_status": [
        r"(?:status|check|update|how.?s)\s+(?:on\s+)?(.+?)(?:\s+(?:project|production|status|going))?$",
        r"(?:what.?s|where.?s)\s+(.+?)\s+(?:at|status|standing|project)",
        r"(?:look\s*up|find|check)\s+(?:client\s+)?(.+?)(?:\s+(?:in|on|from)\s+(?:the\s+)?(?:tracker|sheet|board))?$",
    ],
    "update_client": [
        r"(?:update|change|set|mark)\s+(.+?)\s+(?:script|shoot|content|team|status)\s+(?:to|as|→)\s+(.+)",
        r"(?:update|change|set)\s+(.+?)\s+(.+?)\s+(?:to|as|→)\s+(.+)",
        r"(.+?)\s+script\s+(?:is|now)\s+(.*)",
        r"(.+?)\s+shoot\s+(?:is|confirmed|scheduled)\s*(.*)",
    ],
    "upcoming_shoots": [
        r"(?:what|any|show|list)\s+(?:upcoming|next|scheduled)\s+(?:shoots?|sessions?|recordings?)",
        r"(?:when|what).?s (?:the )?next\s+(?:shoot|session|recording|gravação)",
        r"(?:shoots?|sessions?|recordings?)\s+(?:this|next)\s+(?:week|month)",
        r"(?:próxim[ao]s?|agenda)\s+(?:gravações?|sessões?|shoots?)",
    ],
    "send_client_email": [
        r"(?:send|write|draft|email|message)\s+(?:an?\s+)?(?:email|message)\s+(?:to|for)\s+(.+)",
        r"(?:email|contact|reach out to|message)\s+(.+?)(?:\s+(?:about|regarding|re|saying|to tell|to let))\s+(.+)",
    ],
    "check_calendar": [
        r"(?:what.?s|check|show|list)\s+(?:on\s+)?(?:the\s+)?(?:calendar|schedule|agenda)\s*(?:for|on|this|next)?\s*(.*)",
        r"(?:am i|is michael|are we)\s+(?:free|available|busy)\s+(.*)",
        r"(?:any|what)\s+(?:meetings?|appointments?|events?)\s+(?:today|tomorrow|this week|next week)",
    ],
    "read_emails": [
        r"(?:check|show|read|list|any)\s+(?:new\s+)?(?:emails?|messages?|inbox)\s*(?:from|about)?\s*(.*)",
        r"(?:what|any)\s+(?:new\s+)?(?:emails?|messages?)\s+(?:from|about)\s+(.+)",
        r"(?:inbox|email)\s+(?:status|check|update)",
    ],
}


def detect_lara_intent(text):
    """Detect if text contains a Lara action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "lara" prefix if present
    text_lower = re.sub(r"^(?:lara|hey\s+lara|hi\s+lara|oi\s+lara)[,:\s]*", "", text_lower).strip()

    for intent, patterns in LARA_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Google Services ─────────────────────────────────────────────────
def _get_google_creds(scopes, use_dwd=True):
    """Get authenticated Google credentials.

    use_dwd=True  → impersonate DELEGATE_EMAIL (needs scope authorized in Workspace Admin)
    use_dwd=False → service account direct access (sheet must be shared with SA email)
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set")
    creds_dict = json.loads(creds_json)
    sa_email = creds_dict.get("client_email", "unknown")
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
    if use_dwd and DELEGATE_EMAIL:
        creds = creds.with_subject(DELEGATE_EMAIL)
        print(f"[LARA] Google auth: DWD as {DELEGATE_EMAIL}, scopes={scopes}")
    else:
        print(f"[LARA] Google auth: direct SA ({sa_email}), scopes={scopes}")
    return creds


def _get_sheets_service():
    """Get authenticated Google Sheets service.
    Uses service account directly (NO DWD) — sheet must be shared with the SA email.
    Spreadsheets scope is NOT authorized for DWD in Google Workspace Admin.
    """
    return build("sheets", "v4", credentials=_get_google_creds(SCOPES_SHEETS, use_dwd=False), cache_discovery=False)


def _get_calendar_service():
    """Get authenticated Google Calendar service.
    Uses DWD with calendar-only scope (authorized in Workspace Admin).
    """
    return build("calendar", "v3", credentials=_get_google_creds(SCOPES_CALENDAR, use_dwd=True), cache_discovery=False)


def _get_gmail_service():
    """Get authenticated Gmail service (requires Gmail DWD scopes — NOT YET authorized)."""
    return build("gmail", "v1", credentials=_get_google_creds(SCOPES_GMAIL, use_dwd=True), cache_discovery=False)


# ── Production Tracker Helpers ──────────────────────────────────────
def _get_all_clients():
    """Read all clients from the Production Tracker sheet.
    Returns list of (row_index, row_dict) tuples.
    """
    if not PRODUCTION_SHEET_ID:
        return []

    svc = _get_sheets_service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=PRODUCTION_SHEET_ID,
        range="Production!A1:K",
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return []

    headers = rows[0]
    clients = []
    for i, row in enumerate(rows[1:], start=2):
        row_dict = {}
        for j, h in enumerate(headers):
            row_dict[h] = row[j] if j < len(row) else ""
        clients.append((i, row_dict))
    return clients


def _find_client(search_term):
    """Find a client by name (fuzzy match).
    Returns (row_index, client_dict) or (None, None).
    """
    clients = _get_all_clients()
    search_lower = search_term.lower().strip()

    # Exact substring match first
    for row_idx, client in clients:
        name = client.get("Client", "").lower()
        if search_lower in name or name in search_lower:
            return row_idx, client

    # Partial word match
    search_words = search_lower.split()
    for row_idx, client in clients:
        name = client.get("Client", "").lower()
        if all(w in name for w in search_words):
            return row_idx, client

    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def get_production_overview(text):
    """Return a summary of all client production statuses."""
    try:
        clients = _get_all_clients()
        if not clients:
            return "📋 *Production Tracker is empty* — no clients found."

        lines = [f"📋 *Production Overview* — {len(clients)} clients\n"]

        # Group by content status
        status_groups = {}
        for row_idx, client in clients:
            status = client.get("Content Status", "").strip() or "Not Started"
            if status not in status_groups:
                status_groups[status] = []
            status_groups[status].append(client)

        status_emoji = {
            "Not Started": "⬜", "Script Phase": "📝", "Script Approved": "✅",
            "Shoot Scheduled": "📅", "Shoot Complete": "🎬", "In Post-Production": "🎞️",
            "Review": "👀", "Delivered": "🎉", "On Hold": "⏸️",
        }

        for status, group in sorted(status_groups.items(), key=lambda x: list(status_emoji.keys()).index(x[0]) if x[0] in status_emoji else 99):
            emoji = status_emoji.get(status, "•")
            names = [c.get("Client", "?") for c in group]
            lines.append(f"{emoji} *{status}:* {len(group)} — {', '.join(names)}")

        # Upcoming shoots
        upcoming = []
        for row_idx, client in clients:
            shoot_date = client.get("Shoot Date", "").strip()
            if shoot_date:
                try:
                    dt = datetime.strptime(shoot_date, "%Y-%m-%d")
                    if dt.date() >= datetime.now(pytz.timezone(TIMEZONE)).date():
                        upcoming.append((dt, client))
                except ValueError:
                    pass

        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            lines.append(f"\n📅 *Upcoming Shoots:*")
            for dt, client in upcoming[:5]:
                confirmed = "✅" if client.get("Shoot Confirmed", "").lower() in ("yes", "true", "confirmed") else "⏳"
                lines.append(f"  {confirmed} {client.get('Client', '?')} — {dt.strftime('%b %d, %Y')}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Production overview error: {e}")
        return f"⚠️ Error reading production tracker: {str(e)[:200]}"


def get_client_status(text):
    """Look up a specific client's production status."""
    try:
        # Extract client name
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        search = re.sub(
            r"^(?:status|check|update|how.?s|what.?s|where.?s|look\s*up|find)\s+(?:on\s+)?(?:client\s+)?",
            "", text_clean, flags=re.IGNORECASE
        ).strip()
        search = re.sub(r"\s+(?:project|production|status|going|standing|at|in the tracker).*$", "", search, flags=re.IGNORECASE).strip().strip('"\'')

        if not search or len(search) < 2:
            return "🔍 Which client? Give me a name like *Victory Martial Arts* or *Green Rest*."

        row_idx, client = _find_client(search)
        if not client:
            return f'🔍 No client found matching *"{search}"*.'

        name = client.get("Client", "(unknown)")
        lines = [f"📋 *Client Status: {name}*\n"]
        lines.append(f"📧 Email: {client.get('Email', 'N/A')}")
        lines.append(f"📱 Phone: {client.get('Phone', 'N/A')}")
        lines.append(f"🎯 Service: {client.get('Service', 'N/A')}")
        lines.append(f"📝 Script: {client.get('Script Status', 'N/A')}")
        lines.append(f"📅 Shoot Date: {client.get('Shoot Date', 'Not scheduled')}")

        confirmed = client.get("Shoot Confirmed", "")
        lines.append(f"✅ Shoot Confirmed: {confirmed if confirmed else 'No'}")
        lines.append(f"👥 Team Briefed: {client.get('Team Briefed', 'No')}")
        lines.append(f"📞 Last Contact: {client.get('Last Client Contact', 'N/A')}")
        lines.append(f"🎬 Content Status: {client.get('Content Status', 'Not Started')}")

        notes = client.get("Notes", "")
        if notes:
            lines.append(f"📝 Notes: {notes[:200]}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Client status error: {e}")
        return f"⚠️ Error looking up client: {str(e)[:200]}"


def update_client_field(text):
    """Update a client's production field (script status, shoot date, etc.)."""
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Parse: "update Victory script to Approved"
        # or: "update Victory shoot date to 2026-04-15"
        # or: "mark Victory team briefed as Yes"
        field_map = {
            "script": "Script Status",
            "script status": "Script Status",
            "shoot date": "Shoot Date",
            "shoot": "Shoot Date",
            "shoot confirmed": "Shoot Confirmed",
            "confirmed": "Shoot Confirmed",
            "team briefed": "Team Briefed",
            "team": "Team Briefed",
            "briefed": "Team Briefed",
            "content status": "Content Status",
            "content": "Content Status",
            "status": "Content Status",
            "notes": "Notes",
            "last contact": "Last Client Contact",
            "contact": "Last Client Contact",
        }

        # Try pattern: update [client] [field] to [value]
        match = re.search(
            r"(?:update|change|set|mark)\s+(.+?)\s+(script\s*(?:status)?|shoot\s*(?:date|confirmed)?|content\s*(?:status)?|team\s*(?:briefed)?|confirmed|briefed|status|notes|last\s+contact|contact)\s+(?:to|as|→)\s+(.+)",
            text_clean, re.IGNORECASE
        )
        if not match:
            return "🤔 I need a client name, field, and value. Try: *update Victory script to Approved*"

        client_name = match.group(1).strip().strip('"\'')
        field_key = match.group(2).strip().lower()
        new_value = match.group(3).strip().strip('"\'')

        sheet_field = field_map.get(field_key)
        if not sheet_field:
            return f"🤔 I don't recognize the field *{field_key}*. Try: script, shoot date, shoot confirmed, team briefed, content status, notes"

        row_idx, client = _find_client(client_name)
        if not client:
            return f'🔍 No client found matching *"{client_name}"*.'

        # Write update
        svc = _get_sheets_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=PRODUCTION_SHEET_ID,
            range="Production!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]

        if sheet_field not in headers:
            return f"⚠️ Column *{sheet_field}* not found in tracker."

        col_idx = headers.index(sheet_field)
        col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)

        # Also update Last Client Contact timestamp
        updates = [
            {"range": f"Production!{col_letter}{row_idx}", "values": [[new_value]]}
        ]
        if sheet_field != "Last Client Contact" and "Last Client Contact" in headers:
            contact_idx = headers.index("Last Client Contact")
            contact_letter = chr(65 + contact_idx) if contact_idx < 26 else chr(64 + contact_idx // 26) + chr(65 + contact_idx % 26)
            now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
            updates.append({"range": f"Production!{contact_letter}{row_idx}", "values": [[now]]})

        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=PRODUCTION_SHEET_ID,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()

        old_value = client.get(sheet_field, "(empty)")
        return (
            f"✅ *Client updated!*\n"
            f"• *Client:* {client.get('Client', client_name)}\n"
            f"• *{sheet_field}:* {old_value} → *{new_value}*"
        )
    except Exception as e:
        print(f"[LARA] Update client error: {e}")
        return f"⚠️ Error updating client: {str(e)[:200]}"


def get_upcoming_shoots(text):
    """List upcoming shoot dates sorted by date."""
    try:
        clients = _get_all_clients()
        if not clients:
            return "📅 No clients in production tracker."

        now = datetime.now(pytz.timezone(TIMEZONE))
        upcoming = []

        for row_idx, client in clients:
            shoot_date = client.get("Shoot Date", "").strip()
            if shoot_date:
                try:
                    dt = datetime.strptime(shoot_date, "%Y-%m-%d")
                    if dt.date() >= now.date():
                        upcoming.append((dt, client))
                except ValueError:
                    pass

        if not upcoming:
            return "📅 *No upcoming shoots scheduled.*"

        upcoming.sort(key=lambda x: x[0])
        lines = [f"📅 *Upcoming Shoots* — {len(upcoming)} scheduled\n"]

        for dt, client in upcoming:
            confirmed = "✅" if client.get("Shoot Confirmed", "").lower() in ("yes", "true", "confirmed") else "⏳ Unconfirmed"
            team = "👥 Team briefed" if client.get("Team Briefed", "").lower() in ("yes", "true") else "⚠️ Team not briefed"
            days_until = (dt.date() - now.date()).days
            urgency = "🔴" if days_until <= 2 else "🟡" if days_until <= 7 else "🟢"

            lines.append(f"{urgency} *{client.get('Client', '?')}* — {dt.strftime('%b %d, %Y')} ({days_until}d)")
            lines.append(f"   {confirmed} | {team} | Script: {client.get('Script Status', '?')}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Upcoming shoots error: {e}")
        return f"⚠️ Error fetching shoots: {str(e)[:200]}"


def send_client_email(text):
    """Draft or send an email to a client."""
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Extract client and message
        match = re.search(
            r"(?:send|write|draft|email|message)\s+(?:an?\s+)?(?:email|message)\s+(?:to|for)\s+(.+?)(?:\s+(?:about|regarding|re|saying|to tell|to let)\s+(.+))?$",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"(?:email|contact|reach out to|message)\s+(.+?)(?:\s+(?:about|regarding|re|saying|to tell|to let))\s+(.+)",
                text_clean, re.IGNORECASE
            )
        if not match:
            return "🤔 I need a client name and subject. Try: *email Victory about the shoot schedule*"

        client_name = match.group(1).strip().strip('"\'')
        subject_hint = match.group(2).strip() if match.lastindex >= 2 and match.group(2) else ""

        row_idx, client = _find_client(client_name)
        if not client:
            return f'🔍 No client found matching *"{client_name}"*.'

        email = client.get("Email", "").strip()
        if not email:
            return f"⚠️ No email on file for *{client.get('Client', client_name)}*."

        # Build email info for Claude to compose
        return (
            f"📧 *Email Draft Ready*\n"
            f"• *To:* {client.get('Client', client_name)} ({email})\n"
            f"• *Re:* {subject_hint if subject_hint else 'Follow-up'}\n"
            f"• *Service:* {client.get('Service', 'N/A')}\n"
            f"• *Content Status:* {client.get('Content Status', 'N/A')}\n"
            f"• *Script:* {client.get('Script Status', 'N/A')}\n\n"
            f"_I've prepared the context. Tell me what to say and I'll send it, or I can draft a professional follow-up based on their current production stage._"
        )
    except Exception as e:
        print(f"[LARA] Send email error: {e}")
        return f"⚠️ Error preparing email: {str(e)[:200]}"


def check_calendar(text):
    """Check calendar events/availability using ana_calendar."""
    try:
        from ana_calendar import handle_calendar_action
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        handled, result = handle_calendar_action(text_clean)
        if handled:
            return result
        # Try rephrasing
        handled, result = handle_calendar_action(f"what is on my calendar {text_clean}")
        if handled:
            return result
        return "🤔 I couldn't parse the calendar request. Try: *what's on the calendar today?*"
    except Exception as e:
        print(f"[LARA] Calendar check error: {e}")
        return f"⚠️ Error checking calendar: {str(e)[:200]}"


def read_emails(text):
    """Read recent emails from Gmail."""
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Extract optional filter (from/about)
        from_filter = ""
        match = re.search(r"(?:from|about)\s+(.+?)$", text_clean, re.IGNORECASE)
        if match:
            from_filter = match.group(1).strip()

        gmail = _get_gmail_service()
        query = "is:inbox"
        if from_filter:
            # Check if it's a client name
            _, client = _find_client(from_filter)
            if client and client.get("Email"):
                query += f" from:{client['Email']}"
            else:
                query += f" {from_filter}"

        results = gmail.users().messages().list(
            userId="me", q=query, maxResults=10
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"📧 *No emails found*" + (f" matching *{from_filter}*" if from_filter else " in inbox") + "."

        lines = [f"📧 *Recent Emails* — {len(messages)} shown\n"]

        for msg_info in messages[:10]:
            msg = gmail.users().messages().get(
                userId="me", id=msg_info["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers_dict = {}
            for h in msg.get("payload", {}).get("headers", []):
                headers_dict[h["name"]] = h["value"]

            from_addr = headers_dict.get("From", "Unknown")
            subject = headers_dict.get("Subject", "(no subject)")
            date = headers_dict.get("Date", "")
            # Simplify date
            if date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(date)
                    date = dt.strftime("%b %d, %I:%M %p")
                except Exception:
                    date = date[:20]

            # Shorten from address
            from_short = re.sub(r"<.*>", "", from_addr).strip() or from_addr
            if len(from_short) > 30:
                from_short = from_short[:30] + "..."

            snippet = msg.get("snippet", "")[:80]
            lines.append(f"• *{subject}*")
            lines.append(f"  From: {from_short} | {date}")
            if snippet:
                lines.append(f"  _{snippet}_")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Read emails error: {e}")
        return f"⚠️ Error reading emails: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "production_overview": get_production_overview,
    "client_status": get_client_status,
    "update_client": update_client_field,
    "upcoming_shoots": get_upcoming_shoots,
    "send_client_email": send_client_email,
    "check_calendar": check_calendar,
    "read_emails": read_emails,
}


def handle_lara_action(text):
    """Check if text matches a Lara action intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_lara_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[LARA] Action intent detected: {intent} (matched: '{match.group(0)}')")
        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result

    return False, None
