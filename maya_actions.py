"""
Maya Action Handlers — Real-time Slack action capability for Maya (Sales Agent).

Handles:
- Google Sheets read/write (lead tracker)
- ANA handoff (structured message to #ana)
- Calendar availability check (reuses ana_calendar.py)

Uses the same service account (maya-calendar@...) and GOOGLE_CREDENTIALS_JSON
already configured in Railway.
"""

import os
import re
import json
import pytz
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── Config ──────────────────────────────────────────────────────────
TIMEZONE = "America/New_York"
SHEETS_LEADS_ID = os.getenv("GOOGLE_SHEETS_LEADS_ID", "")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.readonly",
]

SHEET_HEADERS = [
    "Date", "Time", "Name", "Business", "Phone", "Email",
    "Service Interest", "Status", "Appt Date & Time", "Notes", "Follow-up →", "Transcript",
    "Source", "Last Contact Date", "Outreach Channel",
    "Outreach Message Sent", "WhatsApp Status",
    "Conversation Summary", "Appointment Booked", "Lead Temperature",
]


# ── Intent Detection ────────────────────────────────────────────────
MAYA_ACTION_INTENTS = {
    "pipeline_summary": [
        r"(?:pipeline|lead)\s*(?:status|summary|overview|report|numbers|stats|count)",
        r"how(?:'s| is| are) (?:the |my |our )?(?:pipeline|leads|prospects)",
        r"(?:show|get|pull|give)\s+(?:me\s+)?(?:the\s+)?pipeline",
        r"(?:quantos|como\s+est[aá])\s+(?:os\s+)?leads?",
    ],
    "lookup_lead": [
        r"(?:look\s*up|find|search|check|pull\s+up|who\s+is)\s+(.+?)(?:\s+(?:in|on|from)\s+(?:the\s+)?(?:sheet|tracker|pipeline)|$)",
        r"(?:what(?:'s| is| do)\s+(?:we\s+)?(?:have|know)\s+(?:on|about))\s+(.+)",
        r"(?:info|details|data)\s+(?:on|about|for)\s+(.+)",
    ],
    "update_lead_status": [
        r"(?:update|change|set|mark|move)\s+(.+?)\s+(?:to|as|→)\s+(hot|warm|cold|new lead|qualified|booked|closed|lost|follow.?up)",
        r"(.+?)\s+(?:is|are)\s+(?:now\s+)?(hot|warm|cold|qualified|booked|closed|lost)",
    ],
    "log_outreach": [
        r"(?:log|record|note|track)\s+(?:that\s+)?(?:i\s+|we\s+)?(?:sent|made|did|had)\s+(?:a\s+)?(.+?)(?:\s+to\s+)(.+?)(?:\s+(?:today|yesterday|on)|$)",
        r"(?:log|record)\s+(?:outreach|contact|message|dm|email|call)\s+(?:to|for|with)\s+(.+)",
    ],
    "add_lead": [
        r"(?:add|create|new)\s+(?:a\s+)?(?:lead|contact|prospect)\s*[:\-]?\s*(.+)",
        r"(?:add|put)\s+(.+?)\s+(?:as|to)\s+(?:a\s+)?(?:lead|the\s+pipeline|the\s+tracker)",
    ],
    "handoff_to_ana": [
        r"(?:hand\s*off?|transfer|pass|send|give)\s+(.+?)\s+(?:to|over\s+to|for)\s+ana",
        r"(?:hand\s*off?|transfer|pass)\s+(.+?)\s+(?:to|for)\s+(?:booking|scheduling|calendar)",
        r"ana[,:]?\s+(?:book|schedule|take\s+care\s+of)\s+(.+)",
    ],
    "check_availability": [
        r"(?:is|are)\s+(?:michael|we|i)\s+(?:free|available|open)\s+(.+)",
        r"(?:check|what.?s)\s+(?:michael.?s\s+)?(?:availability|schedule|calendar)\s*(?:for|on|at)?\s*(.+)?",
        r"(?:can\s+(?:we|michael)\s+(?:do|meet|book))\s+(.+)",
    ],
}


def detect_maya_intent(text):
    """Detect if text contains a Maya action intent.
    Returns (intent, match_groups) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "maya" prefix if present
    text_lower = re.sub(r"^(?:maya|hey\s+maya|hi\s+maya)[,:\s]*", "", text_lower).strip()

    for intent, patterns in MAYA_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Sheets Service ──────────────────────────────────────────────────
def _get_sheets_service():
    """Get authenticated Google Sheets service."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set")


def _get_all_leads():
    """Read all leads from all monthly tabs, newest first.
    Returns list of (tab_name, row_index, row_dict) tuples.
    """
    if not SHEETS_LEADS_ID:
        return []

    svc = _get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEETS_LEADS_ID).execute()
    tabs = [s["properties"]["title"] for s in meta["sheets"]]

    # Sort tabs by date (newest first)
    month_order = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                   "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}

    def tab_sort_key(t):
        parts = t.split()
        if len(parts) == 2 and parts[0] in month_order:
            return (int(parts[1]), month_order[parts[0]])
        return (0, 0)

    tabs.sort(key=tab_sort_key, reverse=True)

    all_leads = []
    for tab in tabs:
        try:
            result = svc.spreadsheets().values().get(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab}'!A1:T",
            ).execute()
            rows = result.get("values", [])
            if not rows:
                continue
            headers = rows[0]
            for i, row in enumerate(rows[1:], start=2):
                row_dict = {}
                for j, h in enumerate(headers):
                    row_dict[h] = row[j] if j < len(row) else ""
                all_leads.append((tab, i, row_dict))
        except Exception as e:
            print(f"[Maya] Error reading tab {tab}: {e}")
            continue

    return all_leads


# ── Action Handlers ─────────────────────────────────────────────────

def get_pipeline_summary(text):
    """Return a summary of leads grouped by status."""
    try:
        leads = _get_all_leads()
        if not leads:
            return "📊 *Pipeline is empty* — no leads found in the tracker."

        # Group by status
        by_status = {}
        total = 0
        for tab, row_idx, lead in leads:
            status = lead.get("Status", "Unknown").strip() or "Unknown"
            # Normalize
            status_key = status.lower()
            if status_key not in by_status:
                by_status[status_key] = {"label": status, "count": 0, "names": []}
            by_status[status_key]["count"] += 1
            name = lead.get("Name", "").strip() or lead.get("Phone", "?")
            by_status[status_key]["names"].append(name)
            total += 1

        # Build response
        emoji_map = {
            "hot": "🔥", "warm": "🟡", "cold": "🧊", "new lead": "🆕",
            "qualified": "✅", "booked": "📅", "closed": "💰", "lost": "❌",
            "follow-up": "🔄", "follow up": "🔄",
        }

        lines = [f"📊 *Maya Pipeline Summary* — {total} total leads\n"]
        # Sort: hot first, then warm, cold, etc.
        priority = ["hot", "warm", "qualified", "booked", "new lead", "follow-up", "follow up", "cold", "lost", "closed"]
        sorted_statuses = sorted(by_status.keys(), key=lambda s: priority.index(s) if s in priority else 99)

        for s in sorted_statuses:
            info = by_status[s]
            emoji = emoji_map.get(s, "•")
            names_preview = ", ".join(info["names"][:5])
            if len(info["names"]) > 5:
                names_preview += f" (+{len(info['names']) - 5} more)"
            lines.append(f"{emoji} *{info['label']}:* {info['count']} — {names_preview}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Maya] Pipeline summary error: {e}")
        return f"⚠️ Error reading pipeline: {str(e)[:200]}"


def lookup_lead(text):
    """Look up a lead by name or phone number."""
    try:
        # Extract search term — strip the intent verbs
        search = re.sub(
            r"^(?:maya[,:\s]*)?(?:look\s*up|find|search|check|pull\s+up|who\s+is|what(?:'s| is| do)\s+(?:we\s+)?(?:have|know)\s+(?:on|about)|info|details|data)\s+(?:on|about|for)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().strip('"\'')

        if not search or len(search) < 2:
            return "🔍 Who should I look up? Give me a name or phone number."

        leads = _get_all_leads()
        search_lower = search.lower()
        matches = []

        for tab, row_idx, lead in leads:
            name = lead.get("Name", "").strip().lower()
            business = lead.get("Business", "").strip().lower()
            phone = re.sub(r"\D", "", lead.get("Phone", ""))
            search_digits = re.sub(r"\D", "", search)

            if (search_lower in name or search_lower in business or
                    (search_digits and len(search_digits) >= 4 and search_digits in phone)):
                matches.append((tab, lead))

        if not matches:
            return f'🔍 No leads found matching *"{search}"*.'

        # Show top match(es)
        lines = [f'🔍 *Found {len(matches)} lead(s) matching "{search}":*\n']
        for tab, lead in matches[:3]:
            name = lead.get("Name", "(no name)") or "(no name)"
            biz = lead.get("Business", "")
            phone = lead.get("Phone", "")
            status = lead.get("Status", "?")
            service = lead.get("Service Interest", "")
            temp = lead.get("Lead Temperature", "")
            last_contact = lead.get("Last Contact Date", "")
            notes = lead.get("Notes", "")

            lines.append(f"*{name}*" + (f" — {biz}" if biz else ""))
            if phone:
                lines.append(f"  📱 {phone}")
            lines.append(f"  📌 Status: {status}" + (f" | Temp: {temp}" if temp else ""))
            if service:
                lines.append(f"  🎯 Interest: {service}")
            if last_contact:
                lines.append(f"  📅 Last contact: {last_contact}")
            if notes:
                lines.append(f"  📝 {notes[:100]}")
            lines.append(f"  📂 Tab: {tab}")
            lines.append("")

        if len(matches) > 3:
            lines.append(f"_...and {len(matches) - 3} more matches._")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Maya] Lookup error: {e}")
        return f"⚠️ Error looking up lead: {str(e)[:200]}"


def update_lead_status(text):
    """Update a lead's status (Hot/Warm/Cold/etc.)."""
    try:
        # Extract name and new status
        text_clean = re.sub(r"^(?:maya[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        match = re.search(
            r"(?:update|change|set|mark|move)\s+(.+?)\s+(?:to|as|→)\s+(hot|warm|cold|new lead|qualified|booked|closed|lost|follow.?up)",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"(.+?)\s+(?:is|are)\s+(?:now\s+)?(hot|warm|cold|qualified|booked|closed|lost)",
                text_clean, re.IGNORECASE
            )
        if not match:
            return "🤔 I need a name and status. Try: *update [Name] to Hot*"

        search_name = match.group(1).strip().strip('"\'')
        new_status = match.group(2).strip().title()

        # Find the lead
        leads = _get_all_leads()
        search_lower = search_name.lower()
        target = None

        for tab, row_idx, lead in leads:
            name = lead.get("Name", "").strip().lower()
            business = lead.get("Business", "").strip().lower()
            if search_lower in name or search_lower in business:
                target = (tab, row_idx, lead)
                break

        if not target:
            return f'🔍 No lead found matching *"{search_name}"*. Check the name and try again.'

        tab, row_idx, lead = target
        old_status = lead.get("Status", "?")

        # Write the update
        svc = _get_sheets_service()
        # Find Status column index
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab}'!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]

        updates = {"Status": new_status}
        # Also update Lead Temperature to match
        temp_map = {"Hot": "Hot", "Warm": "Warm", "Cold": "Cold", "Qualified": "Hot",
                    "Booked": "Hot", "Closed": "Hot", "Lost": "Cold"}
        if new_status in temp_map:
            updates["Lead Temperature"] = temp_map[new_status]

        # Update Last Contact Date
        now = datetime.now(pytz.timezone(TIMEZONE))
        updates["Last Contact Date"] = now.strftime("%Y-%m-%d")

        data = []
        for col_name, value in updates.items():
            if col_name in headers:
                col_idx = headers.index(col_name)
                col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)
                data.append({"range": f"'{tab}'!{col_letter}{row_idx}", "values": [[value]]})

        if data:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()

        lead_name = lead.get("Name", search_name)
        return (
            f"✅ *Lead updated!*\n"
            f"• *Name:* {lead_name}\n"
            f"• *Status:* {old_status} → *{new_status}*\n"
            f"• *Tab:* {tab}"
        )
    except Exception as e:
        print(f"[Maya] Update status error: {e}")
        return f"⚠️ Error updating lead: {str(e)[:200]}"


def log_outreach(text):
    """Log an outreach activity for a lead."""
    try:
        text_clean = re.sub(r"^(?:maya[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Try to extract: channel/method + lead name
        # "log that I sent a LinkedIn DM to Jeremy Tucker today"
        # "log email to One Stop Financial"
        match = re.search(
            r"(?:log|record|note|track)\s+(?:that\s+)?(?:i\s+|we\s+)?(?:sent|made|did|had)\s+(?:a\s+)?(.+?)\s+to\s+(.+?)(?:\s+(?:today|yesterday|on)|$)",
            text_clean, re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"(?:log|record)\s+(?:outreach|contact|message|dm|email|call)\s+(?:to|for|with)\s+(.+)",
                text_clean, re.IGNORECASE,
            )
            if match:
                # Only captured the name, channel is unknown
                channel = "Slack"
                lead_name = match.group(1).strip().strip('"\'')
            else:
                return "🤔 I need more details. Try: *log LinkedIn DM to [Name]*"
        else:
            channel = match.group(1).strip()
            lead_name = match.group(2).strip().strip('"\'')

        # Find the lead
        leads = _get_all_leads()
        search_lower = lead_name.lower()
        target = None

        for tab, row_idx, lead in leads:
            name = lead.get("Name", "").strip().lower()
            business = lead.get("Business", "").strip().lower()
            if search_lower in name or search_lower in business:
                target = (tab, row_idx, lead)
                break

        if not target:
            return f'🔍 No lead found matching *"{lead_name}"*. Check the name and try again.'

        tab, row_idx, lead = target
        now = datetime.now(pytz.timezone(TIMEZONE))

        # Update outreach columns
        svc = _get_sheets_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab}'!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]

        updates = {
            "Last Contact Date": now.strftime("%Y-%m-%d"),
            "Outreach Channel": channel,
            "Outreach Message Sent": f"{channel} — {now.strftime('%b %d, %Y %I:%M %p')}",
        }

        data = []
        for col_name, value in updates.items():
            if col_name in headers:
                col_idx = headers.index(col_name)
                col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)
                data.append({"range": f"'{tab}'!{col_letter}{row_idx}", "values": [[value]]})

        if data:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()

        return (
            f"✅ *Outreach logged!*\n"
            f"• *Lead:* {lead.get('Name', lead_name)}\n"
            f"• *Channel:* {channel}\n"
            f"• *Date:* {now.strftime('%b %d, %Y')}\n"
            f"• *Tab:* {tab}"
        )
    except Exception as e:
        print(f"[Maya] Log outreach error: {e}")
        return f"⚠️ Error logging outreach: {str(e)[:200]}"


def add_new_lead(text):
    """Add a new lead to the tracker."""
    try:
        text_clean = re.sub(r"^(?:maya[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Try to extract lead details
        # "add lead: John Smith, 555-1234, interested in studio booking"
        # "add John Smith as a lead — interested in ROADMAP"
        info = re.sub(
            r"(?:add|create|new)\s+(?:a\s+)?(?:lead|contact|prospect)\s*[:\-—]?\s*",
            "", text_clean, flags=re.IGNORECASE
        ).strip()

        if not info:
            info = re.sub(
                r"(?:add|put)\s+(.+?)\s+(?:as|to)\s+(?:a\s+)?(?:lead|the\s+pipeline|the\s+tracker)",
                r"\1", text_clean, flags=re.IGNORECASE
            ).strip()

        if not info or len(info) < 2:
            return "🤔 I need at least a name. Try: *add lead: John Smith, 555-1234, interested in studio*"

        # Parse comma-separated fields
        parts = [p.strip() for p in info.split(",")]
        name = parts[0] if parts else ""
        phone = ""
        service = ""

        for p in parts[1:]:
            if re.search(r"\d{3}", p):
                phone = p.strip()
            elif re.search(r"(?:interested|want|need|looking)", p, re.IGNORECASE):
                service = re.sub(r"(?:interested\s+in|wants?|needs?|looking\s+for)\s*", "", p, flags=re.IGNORECASE).strip()
            elif not service:
                service = p.strip()

        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")

        svc = _get_sheets_service()

        # Ensure tab exists (reuse pattern from app.py)
        meta = svc.spreadsheets().get(spreadsheetId=SHEETS_LEADS_ID).execute()
        existing_tabs = {s["properties"]["title"] for s in meta["sheets"]}
        if tab_name not in existing_tabs:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"requests": [{"addSheet": {"properties": {"title": tab_name, "gridProperties": {"frozenRowCount": 1}}}}]}
            ).execute()
            svc.spreadsheets().values().update(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab_name}'!A1",
                valueInputOption="RAW",
                body={"values": [SHEET_HEADERS]},
            ).execute()

        row = [
            now.strftime("%Y-%m-%d"),   # Date
            now.strftime("%I:%M %p"),   # Time
            name,                        # Name
            "",                          # Business
            phone,                       # Phone
            "",                          # Email
            service,                     # Service Interest
            "New Lead",                  # Status
            "",                          # Appt Date & Time
            f"Added via Slack by Maya",  # Notes
            "",                          # Follow-up →
            "",                          # Transcript
            "Slack",                     # Source
            now.strftime("%Y-%m-%d"),   # Last Contact Date
            "",                          # Outreach Channel
            "",                          # Outreach Message Sent
            "",                          # WhatsApp Status
            "",                          # Conversation Summary
            "",                          # Appointment Booked
            "Warm",                      # Lead Temperature
        ]

        svc.spreadsheets().values().append(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        lines = [
            f"✅ *New lead added!*",
            f"• *Name:* {name}",
        ]
        if phone:
            lines.append(f"• *Phone:* {phone}")
        if service:
            lines.append(f"• *Interest:* {service}")
        lines.append(f"• *Status:* New Lead")
        lines.append(f"• *Tab:* {tab_name}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Maya] Add lead error: {e}")
        return f"⚠️ Error adding lead: {str(e)[:200]}"


def handoff_to_ana(text):
    """Generate a structured handoff message for posting to #ana.
    Returns (handoff_message, lead_name) or (error_message, None).
    """
    try:
        text_clean = re.sub(r"^(?:maya[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Extract lead name
        match = re.search(
            r"(?:hand\s*off?|transfer|pass|send|give)\s+(.+?)\s+(?:to|over\s+to|for)\s+(?:ana|booking|scheduling)",
            text_clean, re.IGNORECASE,
        )
        if not match:
            match = re.search(r"(?:hand\s*off?|transfer|pass)\s+(.+?)$", text_clean, re.IGNORECASE)
        if not match:
            return "🤔 Who should I hand off to ANA? Try: *hand off [Name] to ANA*", None

        lead_name = match.group(1).strip().strip('"\'').rstrip(" —-–")
        # Remove trailing context like "he's ready to book"
        lead_name = re.sub(r"\s*[-—–]\s*.*$", "", lead_name).strip()

        # Look up lead details
        leads = _get_all_leads()
        search_lower = lead_name.lower()
        lead_data = None

        for tab, row_idx, lead in leads:
            name = lead.get("Name", "").strip().lower()
            business = lead.get("Business", "").strip().lower()
            if search_lower in name or search_lower in business:
                lead_data = lead
                break

        # Build handoff message
        if lead_data:
            name = lead_data.get("Name", lead_name) or lead_name
            phone = lead_data.get("Phone", "")
            service = lead_data.get("Service Interest", "")
            business = lead_data.get("Business", "")
            status = lead_data.get("Status", "")

            handoff_msg = f"🔥 *Hot Lead Handoff from Maya*\n"
            handoff_msg += f"*Name:* {name}"
            if business:
                handoff_msg += f" ({business})"
            handoff_msg += "\n"
            if phone:
                handoff_msg += f"*Phone:* {phone}\n"
            if service:
                handoff_msg += f"*Interested in:* {service}\n"
            handoff_msg += f"*Status:* {status}\n"
            handoff_msg += f"*Action:* Please book a 15-min ROADMAP™ call via Calendly."
        else:
            handoff_msg = (
                f"🔥 *Hot Lead Handoff from Maya*\n"
                f"*Name:* {lead_name}\n"
                f"*Action:* Please book a 15-min ROADMAP™ call via Calendly.\n"
                f"_(Lead not found in tracker — may need to be added)_"
            )

        return handoff_msg, lead_name
    except Exception as e:
        print(f"[Maya] Handoff error: {e}")
        return f"⚠️ Error creating handoff: {str(e)[:200]}", None


def check_availability(text):
    """Check calendar availability. Reuses ana_calendar.py's check function."""
    try:
        from ana_calendar import handle_calendar_action
        # Rewrite as an availability check
        text_clean = re.sub(r"^(?:maya[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        handled, result = handle_calendar_action(text_clean)
        if handled:
            return result
        # Try rephrasing for ana_calendar
        handled, result = handle_calendar_action(f"am I free {text_clean}")
        if handled:
            return result
        return "🤔 I couldn't parse the availability request. Try: *is Michael free Thursday at 2pm?*"
    except Exception as e:
        print(f"[Maya] Availability check error: {e}")
        return f"⚠️ Error checking availability: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "pipeline_summary": get_pipeline_summary,
    "lookup_lead": lookup_lead,
    "update_lead_status": update_lead_status,
    "log_outreach": log_outreach,
    "add_lead": add_new_lead,
    "handoff_to_ana": None,  # Special handling — needs Slack posting
    "check_availability": check_availability,
}


def handle_maya_action(text):
    """Check if text matches a Maya action intent and execute it.
    Returns (handled: bool, response: str or None, handoff_msg: str or None).
    handoff_msg is only set for handoff_to_ana intents.
    """
    intent, match = detect_maya_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[Maya] Action intent detected: {intent} (matched: '{match.group(0)}')")

        if intent == "handoff_to_ana":
            handoff_msg, lead_name = handoff_to_ana(text)
            if lead_name:
                return True, f"✅ *Handoff sent to ANA!*\nI've posted a structured lead handoff for *{lead_name}* to #ana.", handoff_msg
            else:
                return True, handoff_msg, None

        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result, None

    return False, None, None


# ══════════════════════════════════════════════════════════════════════
# RE-ENGAGEMENT QUEUE — Session 30.13
# Tracks leads who went silent after initial Maya conversation.
# Templates: maya_reengagement_1 (24h), maya_reengagement_2 (4d),
#            maya_reengagement_3 (7d). All approved MARKETING category.
# ══════════════════════════════════════════════════════════════════════

import requests as http_requests

REENGAGEMENT_TAB = "Re-engagement Queue"
REENGAGEMENT_HEADERS = [
    "Phone", "Name", "Business", "Added", "Last Inbound",
    "T1 Sent", "T2 Sent", "T3 Sent", "Status", "Notes",
]

# Template names — must match what Meta approved
REENGAGEMENT_TEMPLATES = {
    "T1": "maya_reengagement_1",
    "T2": "maya_reengagement_2",
    "T3": "maya_reengagement_3",
}

# Cadence: hours since last INBOUND message from the lead
REENGAGEMENT_CADENCE = {
    "T1": 24,    # 24 hours  (1 day)
    "T2": 96,    # 96 hours  (4 days)
    "T3": 168,   # 168 hours (7 days)
}

# Days after T3 with no reply before marking Cold
REENGAGEMENT_COLD_DAYS = 7


def _ensure_reengagement_tab():
    """Create the Re-engagement Queue tab if it doesn't exist."""
    if not SHEETS_LEADS_ID:
        return
    svc = _get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEETS_LEADS_ID).execute()
    existing = {s["properties"]["title"] for s in meta["sheets"]}
    if REENGAGEMENT_TAB not in existing:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=SHEETS_LEADS_ID,
            body={"requests": [{"addSheet": {"properties": {
                "title": REENGAGEMENT_TAB,
                "gridProperties": {"frozenRowCount": 1},
            }}}]},
        ).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{REENGAGEMENT_TAB}'!A1",
            valueInputOption="RAW",
            body={"values": [REENGAGEMENT_HEADERS]},
        ).execute()
        print(f"[Maya] Created '{REENGAGEMENT_TAB}' tab with headers")


def get_reengagement_queue():
    """Read all rows from the Re-engagement Queue tab.
    Returns list of (row_index, row_dict) tuples.
    """
    if not SHEETS_LEADS_ID:
        return []
    try:
        _ensure_reengagement_tab()
        svc = _get_sheets_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{REENGAGEMENT_TAB}'!A1:J",
        ).execute()
        rows = result.get("values", [])
        if len(rows) < 2:
            return []
        headers = rows[0]
        entries = []
        for i, row in enumerate(rows[1:], start=2):
            row_dict = {}
            for j, h in enumerate(headers):
                row_dict[h] = row[j] if j < len(row) else ""
            if not row_dict.get("Phone", "").strip():
                continue
            entries.append((i, row_dict))
        return entries
    except Exception as e:
        print(f"[Maya] Error reading re-engagement queue: {e}")
        return []


def add_to_reengagement_queue(phone, name="", business="", last_inbound=None):
    """Add a lead to the re-engagement queue if not already Active there.
    Returns True if added, False if skipped or error.
    """
    if not SHEETS_LEADS_ID:
        return False
    try:
        existing = get_reengagement_queue()
        phone_clean = re.sub(r"\D", "", phone.replace("whatsapp:", ""))
        for _, entry in existing:
            entry_digits = re.sub(r"\D", "", entry.get("Phone", ""))
            if entry_digits == phone_clean and entry.get("Status", "") == "Active":
                print(f"[Maya] {phone} already in re-engagement queue (Active)")
                return False

        _ensure_reengagement_tab()
        svc = _get_sheets_service()
        now = datetime.now(pytz.timezone(TIMEZONE))
        row = [
            phone,                                                  # Phone
            name,                                                   # Name
            business,                                               # Business
            now.strftime("%Y-%m-%d %H:%M"),                        # Added
            last_inbound or now.strftime("%Y-%m-%d %H:%M"),        # Last Inbound
            "",                                                     # T1 Sent
            "",                                                     # T2 Sent
            "",                                                     # T3 Sent
            "Active",                                               # Status
            "",                                                     # Notes
        ]
        svc.spreadsheets().values().append(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{REENGAGEMENT_TAB}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        print(f"[Maya] Added {phone} ({name}) to re-engagement queue")
        return True
    except Exception as e:
        print(f"[Maya] Error adding to re-engagement queue: {e}")
        return False


def update_reengagement_row(row_index, updates):
    """Update specific columns in a re-engagement queue row.
    updates: dict of {column_name: value}
    """
    if not SHEETS_LEADS_ID:
        return
    try:
        svc = _get_sheets_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{REENGAGEMENT_TAB}'!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]

        data = []
        for col_name, value in updates.items():
            if col_name in headers:
                col_idx = headers.index(col_name)
                col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)
                data.append({"range": f"'{REENGAGEMENT_TAB}'!{col_letter}{row_index}", "values": [[value]]})

        if data:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()
    except Exception as e:
        print(f"[Maya] Error updating re-engagement row {row_index}: {e}")


def send_reengagement_template(phone, name, template_name):
    """Send a Maya re-engagement template via Meta WhatsApp Cloud API.
    Returns True if sent successfully, False otherwise.
    """
    meta_token = os.getenv("META_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")

    if not meta_token or not phone_number_id:
        print("[Maya] Cannot send template: missing META_ACCESS_TOKEN or META_PHONE_NUMBER_ID")
        return False

    clean_phone = re.sub(r"\D", "", phone.replace("whatsapp:", ""))
    first_name = (name or "there").split()[0]

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {meta_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": first_name}],
                }
            ],
        },
    }

    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        msg_id = resp.json().get("messages", [{}])[0].get("id", "")
        print(f"[Maya] Re-engagement template '{template_name}' sent to {clean_phone} (name={first_name}): {msg_id}")
        return True
    except Exception as e:
        print(f"[Maya] Re-engagement template send FAILED for {clean_phone}: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"   Response: {e.response.text}")
        return False


def mark_reengagement_replied(phone):
    """When a lead in the re-engagement queue replies, mark them as Replied.
    Returns True if a matching Active entry was found and updated.
    """
    try:
        queue = get_reengagement_queue()
        phone_clean = re.sub(r"\D", "", phone.replace("whatsapp:", ""))
        for row_idx, entry in queue:
            entry_digits = re.sub(r"\D", "", entry.get("Phone", ""))
            if entry_digits == phone_clean and entry.get("Status", "") == "Active":
                now = datetime.now(pytz.timezone(TIMEZONE))
                update_reengagement_row(row_idx, {
                    "Status": "Replied",
                    "Notes": f"Lead replied {now.strftime('%Y-%m-%d %H:%M')}",
                })
                print(f"[Maya] Re-engagement: {phone} marked as Replied")
                return True
        return False
    except Exception as e:
        print(f"[Maya] Error marking lead replied: {e}")
        return False


def mark_reengagement_opted_out(phone):
    """When a lead clicks 'Not right now', mark them as Opted Out."""
    try:
        queue = get_reengagement_queue()
        phone_clean = re.sub(r"\D", "", phone.replace("whatsapp:", ""))
        for row_idx, entry in queue:
            entry_digits = re.sub(r"\D", "", entry.get("Phone", ""))
            if entry_digits == phone_clean and entry.get("Status", "") == "Active":
                now = datetime.now(pytz.timezone(TIMEZONE))
                update_reengagement_row(row_idx, {
                    "Status": "Opted Out",
                    "Notes": f"Clicked 'Not right now' {now.strftime('%Y-%m-%d %H:%M')}",
                })
                print(f"[Maya] Re-engagement: {phone} opted out")
                return True
        return False
    except Exception as e:
        print(f"[Maya] Error marking lead opted out: {e}")
        return False


def is_in_active_reengagement(phone):
    """Check if a phone number has an Active entry in the re-engagement queue."""
    try:
        queue = get_reengagement_queue()
        phone_clean = re.sub(r"\D", "", phone.replace("whatsapp:", ""))
        for _, entry in queue:
            entry_digits = re.sub(r"\D", "", entry.get("Phone", ""))
            if entry_digits == phone_clean and entry.get("Status", "") == "Active":
                return True
        return False
    except Exception:
        return False
