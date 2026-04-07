"""
ANA â Google Calendar Integration for Slack (Phase 1)
Provides intent detection + calendar action execution for ANA's Slack handler.
"""

import re
import os
from datetime import datetime, timedelta

import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ââ Configuration (shared with app.py) ââââââââââââââââââââââââââââââââ
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "c_03s30bthurplevpk6a264h7n34@group.calendar.google.com")
TIMEZONE = "America/New_York"
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]

# ââ Intent Detection Patterns ââââââââââââââââââââââââââââââââââââââââââ
ANA_CALENDAR_INTENTS = {
    "list_events": [
        r"what.?s on (?:my |the )?calendar",
        r"(?:show|list|get|check) (?:my |the )?(?:events|appointments|schedule|calendar)",
        r"what (?:do i have|is scheduled|meetings)",
        r"(?:today|tomorrow|this week|next week).?s? (?:schedule|calendar|events|appointments)",
        r"any(?:thing)? (?:on|scheduled)",
        r"my (?:schedule|calendar|events|agenda)",
    ],
    "check_availability": [
        r"(?:am i |are we |is .+ )?(?:free|available|open) (?:on|at|this|next|tomorrow)",
        r"check (?:my |the )?availability",
        r"(?:can i|can we) (?:do|meet|schedule|book) (?:something |a meeting )?(?:on|at|this|next|tomorrow)",
        r"(?:is|are) there (?:any )?(?:openings|slots|availability)",
        r"(?:do i have|is there) (?:anything|something) (?:on|at|scheduled)",
    ],
    "create_event": [
        r"(?:add|create|schedule|book|set up|put|block) (?:a |an )?(?:event|meeting|appointment|block|session|call|reminder)",
        r"block (?:off|out) ",
        r"(?:add|put) .+ (?:on|to) (?:my |the )?calendar",
        r"(?:schedule|book|set) .+ (?:for|on|at) ",
    ],
    "find_free_time": [
        r"(?:find|when is|when am i) (?:the next |my next )?(?:free|available|open)",
        r"(?:find|show|get) (?:me )?(?:free|open|available) (?:time|slots|windows)",
        r"when can (?:i|we) (?:meet|schedule|do|book)",
        r"next (?:available|free|open) (?:slot|time|window)",
    ],
    "delete_event": [
        r"(?:delete|remove|cancel|drop) (?:the |my |that )?(?:event|meeting|appointment|session|call)",
        r"take .+ off (?:the )?calendar",
        r"cancel .+ (?:on|at|for) ",
    ],
    "update_event": [
        r"(?:update|change|modify|reschedule|move|push|shift) (?:the |my |that )?(?:event|meeting|appointment|session|call)",
        r"(?:push|move|shift) .+ to ",
        r"reschedule ",
    ],
}


# ââ Helper: Calendar Service ââââââââââââââââââââââââââââââââââââââââââ
def _get_cal_service(impersonate=None):
    """Get Google Calendar service using the shared service account credentials.

    If impersonate is set, uses Domain-Wide Delegation to act as that user.
    Write operations should pass impersonate=GOOGLE_DELEGATE_EMAIL to bypass
    Workspace external sharing restrictions on group calendars.
    """
    import json
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        # When impersonating via DWD, only request scopes authorized in Workspace Admin.
        # DWD config only has calendar scope â requesting spreadsheets scope too would
        # cause unauthorized_client / access_denied.
        cal_only_scopes = ["https://www.googleapis.com/auth/calendar"]
        scopes = cal_only_scopes if impersonate else SCOPES
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=scopes
        )
        if impersonate:
            creds = creds.with_subject(impersonate)
            print(f"[ANA] Using DWD as: {impersonate} (calendar-only scope)")
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set")


# ââ Intent Detection âââââââââââââââââââââââââââââââââââââââââââââââââ
def detect_calendar_intent(text):
    """Detect if text contains a calendar-related intent. Returns (intent, match) or (None, None)."""
    text_lower = text.lower().strip()
    for intent, patterns in ANA_CALENDAR_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return intent, match.group(0)
    return None, None


# ââ Date Parsing âââââââââââââââââââââââââââââââââââââââââââââââââââââ
def _parse_date_range(text):
    """Parse natural-language date references into (start_dt, end_dt) in EDT."""
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    text_lower = text.lower()

    if "tomorrow" in text_lower:
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif "next week" in text_lower:
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        start = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=5)
    elif "this week" in text_lower:
        start = now
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.weekday() == 4:
            days_until_friday = 0
        end = (now + timedelta(days=max(days_until_friday, 0) + 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        # Check for day-of-week names first
        _DAY_NAMES_R = {
            "monday": 0, "mon": 0, "segunda": 0,
            "tuesday": 1, "tue": 1, "tues": 1, "terça": 1, "terca": 1,
            "wednesday": 2, "wed": 2, "quarta": 2,
            "thursday": 3, "thu": 3, "thurs": 3, "quinta": 3,
            "friday": 4, "fri": 4, "sexta": 4,
            "saturday": 5, "sat": 5, "sábado": 5, "sabado": 5,
            "sunday": 6, "sun": 6, "domingo": 6,
        }
        day_match = re.search(
            r"\b(monday|mon|tuesday|tue(?:s)?|wednesday|wed|thursday|thu(?:rs)?|friday|fri|saturday|sat|sunday|sun|segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)\b",
            text_lower,
        )
        parsed = False
        if day_match:
            target_weekday = _DAY_NAMES_R[day_match.group(1)]
            current_weekday = now.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7
            start = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            parsed = True

        # Then check explicit date formats
        if not parsed:
            date_patterns = [
                (r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", "month_day"),
                (r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", "slash_date"),
            ]
            for pat, fmt in date_patterns:
                m = re.search(pat, text)
                if m:
                    try:
                        if fmt == "month_day":
                            month_str, day_str = m.group(1), m.group(2)
                            year = int(m.group(3)) if m.group(3) else now.year
                            date_str = f"{month_str} {day_str} {year}"
                            parsed_date = datetime.strptime(date_str, "%B %d %Y")
                            start = tz.localize(parsed_date)
                            end = start + timedelta(days=1)
                            parsed = True
                        elif fmt == "slash_date":
                            month, day = int(m.group(1)), int(m.group(2))
                            year = int(m.group(3)) if m.group(3) else now.year
                            if year < 100:
                                year += 2000
                            start = tz.localize(datetime(year, month, day))
                            end = start + timedelta(days=1)
                            parsed = True
                    except (ValueError, AttributeError):
                        continue
                    if parsed:
                        break
        if not parsed:
            start = now
            end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end


def _parse_event_details(text):
    """Parse event creation details from natural language."""
    details = {
        "title": None,
        "date": None,
        "start_time": None,
        "end_time": None,
        "duration_hours": 1,
        "description": "",
        "location": None,
        "reminder_minutes": 30,
    }
    text_lower = text.lower()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    # Extract title from quotes (preferred)
    title_match = re.search(r'"([^"]+)"', text)
    if title_match:
        details["title"] = title_match.group(1)
    else:
        # Try "called/named/titled X"
        title_match = re.search(
            r"(?:called|named|titled)\s+(.+?)(?:\s+(?:on|at|for|from|tomorrow|today|next))",
            text, re.IGNORECASE,
        )
        if title_match:
            details["title"] = title_match.group(1).strip()
        else:
            # Try to extract subject after scheduling verbs:
            # "schedule a Team Meeting for..." / "book a meeting with the editor for..."
            # "marca uma Reunião para..." / "agendar Treino para..."
            title_match = re.search(
                r"(?:schedule|book|create|add|set up|marca[r]?|agenda[r]?|cria[r]?)\s+(?:a |an |uma |um )?(.+?)(?:\s+(?:for|on|at|tomorrow|today|next|para|na|no|segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b)",
                text, re.IGNORECASE,
            )
            if title_match:
                candidate = title_match.group(1).strip().rstrip(",. ")
                # Only use if it's not too short or too generic
                if len(candidate) > 2 and candidate.lower() not in {"it", "this", "that", "one", "event", "something"}:
                    details["title"] = candidate

    # Extract date
    if "tomorrow" in text_lower:
        details["date"] = (now + timedelta(days=1)).date()
    elif "today" in text_lower:
        details["date"] = now.date()
    else:
        # Check for day-of-week names (Monday, Tuesday, ..., Sunday)
        _DAY_NAMES = {
            "monday": 0, "mon": 0, "segunda": 0,
            "tuesday": 1, "tue": 1, "tues": 1, "terça": 1, "terca": 1,
            "wednesday": 2, "wed": 2, "quarta": 2,
            "thursday": 3, "thu": 3, "thurs": 3, "quinta": 3,
            "friday": 4, "fri": 4, "sexta": 4,
            "saturday": 5, "sat": 5, "sábado": 5, "sabado": 5,
            "sunday": 6, "sun": 6, "domingo": 6,
        }
        day_match = re.search(
            r"\b(monday|mon|tuesday|tue(?:s)?|wednesday|wed|thursday|thu(?:rs)?|friday|fri|saturday|sat|sunday|sun|segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)\b",
            text_lower,
        )
        if day_match:
            target_weekday = _DAY_NAMES[day_match.group(1)]
            current_weekday = now.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7  # If same day, assume next week
            details["date"] = (now + timedelta(days=days_ahead)).date()

        # Check for explicit month + day (e.g., "April 10th", "January 3")
        if not details["date"]:
            date_match = re.search(
                r"(?:on\s+)?(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?",
                text, re.IGNORECASE,
            )
            if date_match:
                try:
                    month_str = date_match.group(1)
                    day = int(date_match.group(2))
                    year = int(date_match.group(3)) if date_match.group(3) else now.year
                    parsed = datetime.strptime(f"{month_str} {day} {year}", "%B %d %Y")
                    details["date"] = parsed.date()
                except ValueError:
                    pass
        # Check for slash format (e.g., "4/10" or "4/10/2026")
        if not details["date"]:
            slash_match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text)
            if slash_match:
                try:
                    month = int(slash_match.group(1))
                    day = int(slash_match.group(2))
                    year = int(slash_match.group(3)) if slash_match.group(3) else now.year
                    if year < 100:
                        year += 2000
                    details["date"] = datetime(year, month, day).date()
                except ValueError:
                    pass
    if not details["date"]:
        details["date"] = (now + timedelta(days=1)).date()

    # Extract time
    time_match = re.search(r"(?:at|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        details["start_time"] = f"{hour:02d}:{minute:02d}"

    end_match = re.search(r"(?:to|until|till)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
    if end_match:
        hour = int(end_match.group(1))
        minute = int(end_match.group(2) or 0)
        ampm = end_match.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        details["end_time"] = f"{hour:02d}:{minute:02d}"

    duration_match = re.search(r"(\d+)\s*(?:hour|hr|h)", text_lower)
    if duration_match:
        details["duration_hours"] = int(duration_match.group(1))

    if not details["start_time"]:
        details["start_time"] = "10:00"

    # Extract location â addresses, "at [place]" patterns, or "location: ..."
    # Try explicit "location:" or "address:" prefix first
    loc_match = re.search(
        r"(?:location|address|local|endere[cÃ§]o)[:\s]+(.+?)(?:\s*\.|$)",
        text, re.IGNORECASE,
    )
    if loc_match:
        details["location"] = loc_match.group(1).strip()
    else:
        # Try to match a US street address pattern (e.g. "4868 E Colonial Dr" or "123 Main St, City, ST 12345")
        # Stop at "with", "and", "reminder" etc. to avoid leaking other parts of the message
        addr_match = re.search(
            r"(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road|Ln|Lane|Way|Ct|Court|Pl|Place|Pkwy|Parkway|Cir|Circle|Hwy|Highway)(?:[,\s]+[\w]+)*?(?:\s+\d{5}(?:-\d{4})?)?)"
            r"(?:\s+(?:with|and|remind|for|from|at\s+\d|$))",
            text, re.IGNORECASE,
        )
        if addr_match:
            details["location"] = addr_match.group(1).strip().rstrip(",. ")
        else:
            # Try "at [Location Name]" but avoid matching time expressions like "at 3pm"
            at_match = re.search(
                r"\bat\s+(?!(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)|\d{1,2}(?::\d{2})?(?:\s|$)))([A-Z][\w\s&'.-]+?)(?:\s+(?:on|at|from|for|tomorrow|today|next)\b|\.|,|$)",
                text,
            )
            if at_match:
                loc_candidate = at_match.group(1).strip()
                # Only use if it looks like a place name (starts with capital, not a common word)
                skip_words = {"a", "an", "the", "my", "our", "this", "that", "it", "its"}
                if loc_candidate.split()[0].lower() not in skip_words and len(loc_candidate) > 2:
                    details["location"] = loc_candidate

    # Extract reminder override (e.g. "remind me 15 minutes before" or "with a 1 hour reminder")
    reminder_match = re.search(
        r"(?:remind(?:er|me)?|with\s+(?:a\s+)?)\s*(\d+)\s*(?:min|minute|hour|hr|h)\w*\s*(?:before|prior|early|reminder)?",
        text_lower,
    )
    if reminder_match:
        val = int(reminder_match.group(1))
        if "hour" in reminder_match.group(0) or "hr" in reminder_match.group(0):
            val *= 60
        details["reminder_minutes"] = val

    return details


# ââ Calendar Action Executors ââââââââââââââââââââââââââââââââââââââââââ
def _list_events(text):
    """List events from the MWM CREATIONS calendar for a date range."""
    try:
        service = _get_cal_service()
        start_dt, end_dt = _parse_date_range(text)
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f"\U0001f4c5 *No events found* for {start_dt.strftime('%b %d')} \u2014 {end_dt.strftime('%b %d %Y')}."

        lines = [f"\U0001f4c5 *Calendar \u2014 {start_dt.strftime('%b %d')} to {end_dt.strftime('%b %d %Y')}*\n"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            summary = ev.get("summary", "(no title)")
            if "T" in start:
                dt = datetime.fromisoformat(start)
                time_str = dt.strftime("%-I:%M %p")
                date_str = dt.strftime("%a %b %-d")
                lines.append(f"\u2022 *{time_str}* \u2014 {summary} ({date_str})")
            else:
                lines.append(f"\u2022 \U0001f4cc *All day* \u2014 {summary} ({start})")
        return "\n".join(lines)
    except Exception as e:
        print(f"[ANA] Error listing events: {e}")
        return f"\u26a0\ufe0f Couldn't fetch calendar events: {str(e)[:200]}"


def _check_availability(text):
    """Check if a specific time/date is available on the calendar."""
    try:
        service = _get_cal_service()
        start_dt, end_dt = _parse_date_range(text)
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        timed_events = [e for e in events if "dateTime" in e.get("start", {})]

        date_label = start_dt.strftime("%A, %b %-d")
        if not timed_events:
            return f"\u2705 *You're free* on {date_label} \u2014 no timed events found."
        else:
            busy_times = []
            for ev in timed_events:
                s = datetime.fromisoformat(ev["start"]["dateTime"])
                e = datetime.fromisoformat(ev["end"]["dateTime"])
                busy_times.append(
                    f"\u2022 {s.strftime('%-I:%M %p')} \u2013 {e.strftime('%-I:%M %p')}: {ev.get('summary', '(no title)')}"
                )
            return (
                f"\U0001f4cb *{date_label}* \u2014 {len(timed_events)} event(s) found:\n"
                + "\n".join(busy_times)
                + "\n\n_You're busy during the times above. Other times appear open._"
            )
    except Exception as e:
        print(f"[ANA] Error checking availability: {e}")
        return f"\u26a0\ufe0f Couldn't check availability: {str(e)[:200]}"


def _create_event(text):
    """Create a new event on the MWM CREATIONS calendar."""
    try:
        details = _parse_event_details(text)

        # Try DWD first; fall back to direct service account if DWD fails
        delegate = os.getenv("GOOGLE_DELEGATE_EMAIL")
        try:
            service = _get_cal_service(impersonate=delegate) if delegate else _get_cal_service()
            if delegate:
                # Quick test to verify DWD credentials work
                service.calendarList().list(maxResults=1).execute()
                print(f"[ANA] _create_event using DWD as {delegate}")
        except Exception as dwd_err:
            if "unauthorized_client" in str(dwd_err) or "invalid_grant" in str(dwd_err) or "access_denied" in str(dwd_err):
                print(f"[ANA] DWD failed ({dwd_err}), falling back to direct service account")
                service = _get_cal_service()  # no DWD
            else:
                raise

        tz = pytz.timezone(TIMEZONE)
        if not details["title"]:
            details["title"] = "New Event (via ANA)"

        start_hour, start_min = map(int, details["start_time"].split(":"))
        start_dt = tz.localize(
            datetime.combine(details["date"], datetime.min.time().replace(hour=start_hour, minute=start_min))
        )
        if details["end_time"]:
            end_hour, end_min = map(int, details["end_time"].split(":"))
            end_dt = tz.localize(
                datetime.combine(details["date"], datetime.min.time().replace(hour=end_hour, minute=end_min))
            )
        else:
            end_dt = start_dt + timedelta(hours=details["duration_hours"])

        event_body = {
            "summary": details["title"],
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        }
        if details["description"]:
            event_body["description"] = details["description"]
        if details["location"]:
            event_body["location"] = details["location"]
        if details.get("reminder_minutes") is not None:
            event_body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": details["reminder_minutes"]},
                ],
            }

        # Create event on MWM CREATIONS calendar ONLY (no fallback to invisible primary)
        try:
            created = service.events().insert(
                calendarId=CALENDAR_ID,
                body=event_body,
                sendUpdates="none"
            ).execute()
            print(f"[ANA] Event created on MWM CREATIONS calendar: {created.get('htmlLink', 'N/A')}")
        except Exception as insert_err:
            print(f"[ANA] Insert failed on MWM CREATIONS: {repr(insert_err)}")
            if hasattr(insert_err, 'resp'):
                print(f"[ANA] HTTP {insert_err.resp.status}: {insert_err.content}")
            if '403' in str(insert_err) or 'requiredAccessLevel' in str(insert_err):
                return (
                    "\u26a0\ufe0f *Calendar write failed \u2014 permission error.*\n"
                    "The service account does not have write access to the MWM CREATIONS calendar.\n"
                    "Michael needs to re-grant `Make changes to events` permission to "
                    "`maya-calendar@astral-volt-489505-i4.iam.gserviceaccount.com` "
                    "in MWM CREATIONS calendar sharing settings."
                )
            raise insert_err

        response_lines = [
            f"\u2705 *Event created!*",
            f"\u2022 *Title:* {details['title']}",
            f"\u2022 *Date:* {start_dt.strftime('%A, %b %-d %Y')}",
            f"\u2022 *Time:* {start_dt.strftime('%-I:%M %p')} \u2013 {end_dt.strftime('%-I:%M %p')}",
        ]
        if details["location"]:
            response_lines.append(f"\u2022 *Location:* {details['location']}")
        response_lines.append(
            f"\u2022 *Calendar:* {created.get('organizer', {}).get('displayName', 'MWM CREATIONS')}"
        )
        response_lines.append(f"\u2022 *Link:* {created.get('htmlLink', 'N/A')}")
        return "\n".join(response_lines)

    except Exception as e:
        import traceback
        print(f"[ANA] Error creating event: {repr(e)}")
        print(f"[ANA] Traceback: {traceback.format_exc()}")
        return f"\u26a0\ufe0f Couldn't create the event: {str(e)[:200]}"


def _find_free_time(text):
    """Find the next available free time slots on the calendar."""
    try:
        service = _get_cal_service()
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        window_end = now + timedelta(days=7)

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])

        timed_events = [e for e in events if "dateTime" in e.get("start", {})]
        busy = []
        for ev in timed_events:
            s = datetime.fromisoformat(ev["start"]["dateTime"])
            e_end = datetime.fromisoformat(ev["end"]["dateTime"])
            busy.append((s, e_end))

        free_slots = []
        for day_offset in range(7):
            day = now.date() + timedelta(days=day_offset)
            if day.weekday() >= 5:
                continue
            day_start = tz.localize(datetime.combine(day, datetime.min.time().replace(hour=9)))
            day_end = tz.localize(datetime.combine(day, datetime.min.time().replace(hour=18)))
            if day == now.date():
                day_start = max(day_start, now)
            current = day_start
            day_busy = sorted([(s, e) for s, e in busy if s.date() == day])
            for bs, be in day_busy:
                if current < bs and (bs - current).total_seconds() / 3600 >= 1:
                    free_slots.append((current, bs))
                current = max(current, be)
            if current < day_end and (day_end - current).total_seconds() / 3600 >= 1:
                free_slots.append((current, day_end))
            if len(free_slots) >= 5:
                break

        if not free_slots:
            return "\U0001f62c *No free time found* in the next 7 days during business hours (9 AM \u2013 6 PM)."

        lines = ["\U0001f550 *Next available free time slots:*\n"]
        for start, end in free_slots[:5]:
            duration = (end - start).total_seconds() / 3600
            lines.append(
                f"\u2022 *{start.strftime('%A, %b %-d')}*: {start.strftime('%-I:%M %p')} \u2013 {end.strftime('%-I:%M %p')} ({duration:.1f}h free)"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[ANA] Error finding free time: {e}")
        return f"\u26a0\ufe0f Couldn't find free time: {str(e)[:200]}"


def _delete_event(text):
    """Delete/cancel an event by searching for a matching title."""
    try:
        delegate = os.getenv("GOOGLE_DELEGATE_EMAIL")
        try:
            service = _get_cal_service(impersonate=delegate) if delegate else _get_cal_service()
            if delegate:
                service.calendarList().list(maxResults=1).execute()
        except Exception as dwd_err:
            if "unauthorized_client" in str(dwd_err) or "invalid_grant" in str(dwd_err) or "access_denied" in str(dwd_err):
                print(f"[ANA] DWD failed, falling back to direct service account")
                service = _get_cal_service()
            else:
                raise

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        search_term = None
        q_match = re.search(r'"([^"]+)"', text)
        if q_match:
            search_term = q_match.group(1)
        else:
            d_match = re.search(
                r"(?:cancel|delete|remove|drop)\s+(?:the|my|that)?\s*(.+?)(?:\s+(?:on|at|from|for)|$)",
                text, re.IGNORECASE,
            )
            if d_match:
                search_term = d_match.group(1).strip()

        if not search_term:
            return '\U0001f914 I need to know which event to delete. Try: *delete "Event Name"* or *cancel the meeting on Tuesday*'

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=30)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            q=search_term,
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f'\U0001f50d No upcoming events found matching *"{search_term}"*.'

        ev = events[0]
        service.events().delete(calendarId=CALENDAR_ID, eventId=ev["id"], sendUpdates="none").execute()
        start = ev["start"].get("dateTime", ev["start"].get("date", ""))
        if "T" in start:
            dt = datetime.fromisoformat(start)
            time_str = f"{dt.strftime('%A, %b %-d')} at {dt.strftime('%-I:%M %p')}"
        else:
            time_str = start

        return (
            f"\U0001f5d1\ufe0f *Event deleted:*\n"
            f"\u2022 *{ev.get('summary', '(no title)')}*\n"
            f"\u2022 Was scheduled: {time_str}"
        )
    except Exception as e:
        print(f"[ANA] Error deleting event: {e}")
        return f"\u26a0\ufe0f Couldn't delete the event: {str(e)[:200]}"


def _update_event(text):
    """Update/reschedule an event."""
    try:
        delegate = os.getenv("GOOGLE_DELEGATE_EMAIL")
        try:
            service = _get_cal_service(impersonate=delegate) if delegate else _get_cal_service()
            if delegate:
                service.calendarList().list(maxResults=1).execute()
        except Exception as dwd_err:
            if "unauthorized_client" in str(dwd_err) or "invalid_grant" in str(dwd_err) or "access_denied" in str(dwd_err):
                print(f"[ANA] DWD failed, falling back to direct service account")
                service = _get_cal_service()
            else:
                raise

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        search_term = None
        q_match = re.search(r'"([^"]+)"', text)
        if q_match:
            search_term = q_match.group(1)
        else:
            u_match = re.search(
                r"(?:update|change|modify|reschedule|move|push|shift)\s+(?:the|my|that)?\s*(.+?)(?:\s+(?:to|from|on|at)|$)",
                text, re.IGNORECASE,
            )
            if u_match:
                search_term = u_match.group(1).strip()

        if not search_term:
            return '\U0001f914 I need to know which event to update. Try: *reschedule "Meeting" to 3pm tomorrow*'

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=30)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            q=search_term,
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f'\U0001f50d No upcoming events found matching *"{search_term}"*.'

        ev = events[0]
        new_details = _parse_event_details(text)

        start_hour, start_min = map(int, new_details["start_time"].split(":"))
        new_start = tz.localize(
            datetime.combine(new_details["date"], datetime.min.time().replace(hour=start_hour, minute=start_min))
        )
        if new_details["end_time"]:
            end_hour, end_min = map(int, new_details["end_time"].split(":"))
            new_end = tz.localize(
                datetime.combine(new_details["date"], datetime.min.time().replace(hour=end_hour, minute=end_min))
            )
        else:
            orig_start = datetime.fromisoformat(ev["start"].get("dateTime", ev["start"].get("date")))
            orig_end = datetime.fromisoformat(ev["end"].get("dateTime", ev["end"].get("date")))
            duration = orig_end - orig_start
            new_end = new_start + duration

        ev["start"] = {"dateTime": new_start.isoformat(), "timeZone": TIMEZONE}
        ev["end"] = {"dateTime": new_end.isoformat(), "timeZone": TIMEZONE}

        # Update location if provided in the update request
        if new_details.get("location"):
            ev["location"] = new_details["location"]

        updated = service.events().update(calendarId=CALENDAR_ID, eventId=ev["id"], body=ev, sendUpdates="none").execute()

        return (
            f"\u270f\ufe0f *Event updated:*\n"
            f"\u2022 *{ev.get('summary', '(no title)')}*\n"
            f"\u2022 *New time:* {new_start.strftime('%A, %b %-d')} at {new_start.strftime('%-I:%M %p')} \u2013 {new_end.strftime('%-I:%M %p')}\n"
            f"\u2022 *Link:* {updated.get('htmlLink', 'N/A')}"
        )
    except Exception as e:
        print(f"[ANA] Error updating event: {e}")
        return f"\u26a0\ufe0f Couldn't update the event: {str(e)[:200]}"


# ââ Intent Router ââââââââââââââââââââââââââââââââââââââââââââââââââââ
_INTENT_HANDLERS = {
    "list_events": _list_events,
    "check_availability": _check_availability,
    "create_event": _create_event,
    "find_free_time": _find_free_time,
    "delete_event": _delete_event,
    "update_event": _update_event,
}


def handle_calendar_action(text):
    """
    Check if text matches a calendar intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_calendar_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[ANA] Calendar intent detected: {intent} (matched: '{match}')")
        result = _INTENT_HANDLERS[intent](text)
        return True, result
    return False, None
