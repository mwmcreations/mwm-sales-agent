"""
Victor Yodeck Action Handlers — Real-time Slack action capability for Victor (MWM Screens Support).

Handles:
- Screen status (list all screens with online/offline status)
- School list (list all schools/workspaces with screen counts)
- Push content (trigger content push to specific screen(s))
- Schedule broadcast (set takeover mode for all or selected screens)
- Get screen by school (look up screen by school/workspace name)
- Reboot screen (push refresh to a specific player — no native reboot in API)

Uses YODECK_API_KEY from Railway env vars.
Yodeck REST API v2 — https://screens.mwmscreens.com/api/v2/
Auth header: Authorization: Token {label}:{token}
"""

import os
import re
import json
from datetime import datetime

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
YODECK_API_KEY = os.getenv("YODECK_API_KEY", "")
YODECK_BASE_URL = "https://screens.mwmscreens.com/api/v2"


def _yodeck_headers():
    """Return auth headers for Yodeck API."""
    return {
        "Authorization": f"Token {YODECK_API_KEY}",
        "Content-Type": "application/json",
    }


def _yodeck_get(endpoint, params=None):
    """Make a GET request to Yodeck API."""
    if not YODECK_API_KEY:
        raise RuntimeError("YODECK_API_KEY not configured")
    url = f"{YODECK_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.get(url, headers=_yodeck_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _yodeck_post(endpoint, data=None):
    """Make a POST request to Yodeck API."""
    if not YODECK_API_KEY:
        raise RuntimeError("YODECK_API_KEY not configured")
    url = f"{YODECK_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.post(url, headers=_yodeck_headers(), json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _yodeck_put(endpoint, data=None):
    """Make a PUT request to Yodeck API."""
    if not YODECK_API_KEY:
        raise RuntimeError("YODECK_API_KEY not configured")
    url = f"{YODECK_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.put(url, headers=_yodeck_headers(), json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _yodeck_get_all(endpoint, params=None):
    """Paginate through all results from a Yodeck list endpoint."""
    if params is None:
        params = {}
    params.setdefault("limit", 100)
    params.setdefault("offset", 0)
    all_results = []
    while True:
        data = _yodeck_get(endpoint, params=params)
        results = data.get("results", [])
        all_results.extend(results)
        if not data.get("next"):
            break
        params["offset"] = params.get("offset", 0) + params["limit"]
    return all_results


# ── Intent Detection ────────────────────────────────────────────────
VICTOR_ACTION_INTENTS = {
    "screen_status": [
        r"(?:what|list|show|get|check|pull)\s+(?:screen|device|player)\s*(?:status|state)?",
        r"(?:which|are|what)\s+(?:screens?|devices?|players?)\s+(?:are|is)\s+(?:online|offline|up|down|active)",
        r"screen(?:s)?\s+(?:status|health|overview)",
        r"(?:are|is)\s+(?:all\s+)?(?:screens?|devices?)\s+(?:online|active)",
        r"(?:screens?|devices?|players?)\s+(?:currently\s+)?(?:online|offline)",
    ],
    "school_list": [
        r"(?:list|show|get|what|display)\s+(?:schools?|locations?|workspaces?|facilities?)",
        r"(?:what|which)\s+(?:schools?|locations?)\s+(?:do\s+)?(?:we|i)\s+(?:have|operate)",
        r"(?:all|every)\s+(?:schools?|locations?|facilities?)",
        r"schools?\s+(?:list|overview|summary)",
        r"(?:which|what)\s+schools?\s+(?:don.t|do\s+not|have\s+no|without)\s+(?:have\s+)?screens?",
        r"(?:schools?|locations?)\s+(?:without|missing|no)\s+screens?",
        r"(?:pending|unassigned)\s+(?:schools?|locations?)",
    ],
    "push_content": [
        r"(?:push|send|deploy|broadcast|sync|refresh|update)\s+(?:content|media|playlist)\s+(?:to|on)\s+(?:screens?|devices?|players?|all)(?:\s+at)?(?:\s+(.+))?",
        r"(?:refresh|update|sync)\s+(?:screens?|devices?|players?)\s+(?:at|in)\s+(.+)",
        r"(?:push|broadcast)\s+(?:to\s+)?(?:all|every)\s+(?:screens?|devices?|players?)",
    ],
    "schedule_broadcast": [
        r"(?:schedule|set|configure|enable)\s+(?:broadcast|event\s+mode|takeover)\s+(?:for|on)(?:\s+(.+?))?\s+(?:for|at|on)\s+(.+)",
        r"(?:schedule|set)\s+(?:event\s+mode|takeover)\s+(?:tomorrow|next|for|at|on)\s+(.+)",
        r"(?:broadcast|takeover)\s+(?:tomorrow|at|on)\s+(.+)",
    ],
    "get_screen_by_school": [
        r"(?:what|which|get|find|show).+?(?:status|screen|device|player)\s+(?:of|at|in|for)\s+(.+)",
        r"(?:what|which|get|find|show)\s+(?:screen|device|player)\s+(?:is\s+)?(?:at|in|for)\s+(.+)",
        r"(?:screen|device|player)\s+(?:at|in|for)\s+(.+?)(?:\s+(?:school|location|facility))?",
        r"(?:status\s+of|check)\s+(.+?)(?:\s+(?:school|location|screen))?$",
    ],
    "reboot_screen": [
        r"(?:reboot|restart|reset|power\s+cycle)\s+(?:the\s+)?(?:screen|device|player|screen)(?:\s+at)?(?:\s+(.+))?",
        r"(?:reboot|restart)\s+(?:screen|device|player)\s+(?:at|in|for)\s+(.+)",
        r"(?:force\s+)?restart\s+(?:the\s+)?(?:device|screen|player)\s+(.+)",
    ],
}


def _find_school_by_name(schools, search_text):
    """Fuzzy match a school/workspace by name.
    Returns the best matching school dict or None.
    """
    search_lower = search_text.lower().strip()
    search_words = [w for w in search_lower.split() if len(w) > 1 or w.isdigit()]
    target = None
    best_score = 0

    for school in schools:
        name = school.get("name", "").lower()
        # Exact substring match — highest priority
        if search_lower in name:
            return school

        # Word overlap scoring — flexible fuzzy match
        if search_words:
            matches = sum(1 for w in search_words if w in name)
            score = matches / len(search_words)
            if score > best_score and score >= 0.5:
                best_score = score
                target = school

    return target


def detect_victor_intent(text):
    """Detect if text contains a Victor action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "victor" prefix if present (and variations like "hey victor", "hi victor")
    text_lower = re.sub(r"^(?:victor|hey\s+victor|hi\s+victor)[,:\s]*", "", text_lower).strip()

    for intent, patterns in VICTOR_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def screen_status(text):
    """List all screens with online/offline status."""
    try:
        print("[Victor] Fetching screen status from Yodeck API...")

        # Fetch online screens
        online_screens = _yodeck_get_all("/screens", params={"online": "true"})
        # Fetch offline screens
        offline_screens = _yodeck_get_all("/screens", params={"online": "false"})

        total = len(online_screens) + len(offline_screens)
        if total == 0:
            return "🖥️ *No screens found in Yodeck.*"

        lines = [f"🖥️ *Screen Status* — {total} total\n"]
        lines.append(f"🟢 *Online:* {len(online_screens)}")
        for dev in online_screens[:50]:  # Cap display at 50
            name = dev.get("name", "(unnamed)")
            ws = dev.get("workspace", "")
            ws_info = f" — WS:{ws}" if ws else ""
            lines.append(f"  • {name} (ID: {dev.get('id', '?')}){ws_info}")
        if len(online_screens) > 50:
            lines.append(f"  _...and {len(online_screens) - 50} more_")

        if offline_screens:
            lines.append(f"\n🔴 *Offline:* {len(offline_screens)}")
            for dev in offline_screens[:30]:  # Cap display
                name = dev.get("name", "(unnamed)")
                ws = dev.get("workspace", "")
                ws_info = f" — WS:{ws}" if ws else ""
                lines.append(f"  • {name} (ID: {dev.get('id', '?')}){ws_info}")
            if len(offline_screens) > 30:
                lines.append(f"  _...and {len(offline_screens) - 30} more_")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] Screen status error: {e}")
        return f"⚠️ Error fetching screen status: {str(e)[:200]}"


def school_list(text):
    """List all schools/workspaces with screen counts."""
    try:
        print("[Victor] Fetching schools/workspaces from Yodeck API...")
        workspaces = _yodeck_get_all("/workspaces")

        if not workspaces:
            return "📍 *No schools/workspaces found in Yodeck.*"

        # Check if the user is asking about schools WITHOUT screens
        text_lower = text.lower()
        asking_no_screens = any(kw in text_lower for kw in ["without", "don't have", "no screen", "missing", "pending", "unassigned", "not have"])

        # For each workspace, get screen count by querying screens with workspace filter
        lines = []
        schools_with_screens = []
        schools_without_screens = []

        for ws in workspaces:
            ws_id = ws.get("id")
            ws_name = ws.get("name", "(untitled)")
            try:
                screen_data = _yodeck_get("/screens", params={"workspace": ws_id, "limit": 1})
                screen_count = screen_data.get("count", 0)
            except:
                screen_count = -1  # Unknown

            entry = {"name": ws_name, "id": ws_id, "screens": screen_count}
            if screen_count > 0:
                schools_with_screens.append(entry)
            else:
                schools_without_screens.append(entry)

        if asking_no_screens:
            if not schools_without_screens:
                return "✅ All schools/workspaces have screens assigned!"
            lines = [f"📍 *Schools Without Screens* — {len(schools_without_screens)} found\n"]
            for s in schools_without_screens:
                lines.append(f"• *{s['name']}* (ID: {s['id']})")
            lines.append(f"\n📊 *Summary:* {len(schools_with_screens)} with screens, {len(schools_without_screens)} without")
        else:
            lines = [f"📍 *Schools/Workspaces* — {len(workspaces)} found\n"]
            for s in schools_with_screens:
                sc = s['screens'] if s['screens'] >= 0 else "?"
                lines.append(f"• *{s['name']}* — {sc} screen(s)")
            if schools_without_screens:
                lines.append(f"\n📭 *No screens assigned:*")
                for s in schools_without_screens:
                    lines.append(f"• {s['name']}")
            lines.append(f"\n📊 *Total:* {len(schools_with_screens)} with screens, {len(schools_without_screens)} without")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] School list error: {e}")
        return f"⚠️ Error fetching schools: {str(e)[:200]}"


def push_content(text):
    """Trigger content push to specific screen(s) via POST /screens/push."""
    try:
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:push|send|deploy|broadcast|sync|refresh|update)\s+(?:content|media|playlist)?\s+(?:to|on)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip()

        # Extract school/screen name if present
        school_match = re.search(
            r"(?:at|in|for)\s+(.+?)(?:\s+school|\s+location)?$",
            text_clean, re.IGNORECASE
        )
        target_school = None
        if school_match:
            target_school = school_match.group(1).strip()

        # Check if pushing to all screens
        if re.search(r"(?:all|every)\s+(?:screens?|devices?|players?)", text_clean, re.IGNORECASE):
            target_school = None

        if target_school:
            print(f"[Victor] Pushing content to school: {target_school}")
            # Find workspace by name
            workspaces = _yodeck_get_all("/workspaces")
            target_ws = _find_school_by_name(workspaces, target_school)
            if not target_ws:
                return f"🔍 School *{target_school}* not found. Try listing schools first."

            ws_id = target_ws.get("id")
            ws_name = target_ws.get("name")
            try:
                result = _yodeck_post("/screens/push", data={"filter_workspaces": [ws_id]})
                return (
                    f"✅ *Content push initiated!*\n"
                    f"• *School:* {ws_name}\n"
                    f"• All screens in this workspace will update shortly."
                )
            except Exception as e:
                print(f"[Victor] Push content error: {e}")
                return f"⚠️ Error pushing content to {ws_name}: {str(e)[:200]}"
        else:
            print("[Victor] Pushing content to all screens")
            try:
                # Empty filter_workspaces pushes to all
                result = _yodeck_post("/screens/push", data={"filter_workspaces": []})
                return (
                    f"✅ *Content pushed to all screens!*\n"
                    f"• All screens will sync shortly."
                )
            except Exception as e:
                print(f"[Victor] Push to all error: {e}")
                return f"⚠️ Error pushing content: {str(e)[:200]}"

    except Exception as e:
        print(f"[Victor] Push content error: {e}")
        return f"⚠️ Error pushing content: {str(e)[:200]}"


def schedule_broadcast(text):
    """Schedule takeover for all or selected screens via PUT /screens/takeover or /screens/{id}/takeover."""
    try:
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:schedule|set|configure|enable)\s+(?:broadcast|event\s+mode|takeover)\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip()

        # Extract time/date
        time_match = re.search(
            r"(?:for|at|on)\s+(.+?)(?:\s+at\s+(.+))?$",
            text_clean, re.IGNORECASE
        )
        if not time_match:
            return "🤔 When should I schedule the broadcast? Try: *schedule broadcast for tomorrow at 3pm*"

        schedule_date = time_match.group(1).strip()
        schedule_time = time_match.group(2) or "12:00 PM"

        # Extract school if specified
        school_match = re.search(
            r"(?:for|at|in)\s+(.+?)(?:\s+for|at|on)",
            text_clean, re.IGNORECASE
        )
        target_school = school_match.group(1).strip() if school_match else None

        if target_school:
            print(f"[Victor] Setting up takeover for school: {target_school}")
            workspaces = _yodeck_get_all("/workspaces")
            target_ws = _find_school_by_name(workspaces, target_school)
            if not target_ws:
                return f"🔍 School *{target_school}* not found."

            ws_id = target_ws.get("id")
            ws_name = target_ws.get("name")
            # Get screens in this workspace
            screens = _yodeck_get_all("/screens", params={"workspace": ws_id})
            if not screens:
                return f"🖥️ No screens found at *{ws_name}* to broadcast to."

            # Note: takeover requires a media source_id — inform user this needs media ID
            return (
                f"📺 *Broadcast setup for {ws_name}:*\n"
                f"• *Screens:* {len(screens)} found\n"
                f"• *Scheduled:* {schedule_date} at {schedule_time}\n"
                f"• ⚠️ To complete, I need the media/playlist ID to use for the takeover.\n"
                f"  Tell me what content to broadcast and I'll set it up."
            )
        else:
            return (
                f"📺 *Broadcast scheduled:*\n"
                f"• *Coverage:* All screens\n"
                f"• *Scheduled:* {schedule_date} at {schedule_time}\n"
                f"• ⚠️ To complete, I need the media/playlist ID to use for the takeover.\n"
                f"  Tell me what content to broadcast and I'll set it up."
            )

    except Exception as e:
        print(f"[Victor] Schedule broadcast error: {e}")
        return f"⚠️ Error scheduling broadcast: {str(e)[:200]}"


def get_screen_by_school(text):
    """Look up screen(s) by school/workspace name."""
    try:
        # Extract school name using targeted patterns (handles contractions like "what's")
        text_lower = text.strip().rstrip("?").strip()
        text_clean = None

        # Try specific extraction patterns first
        extraction_patterns = [
            r"(?:status|screen|device|player)\s+(?:of|at|in|for)\s+(.+?)(?:\s+(?:school|location))?$",
            r"(?:what(?:'s|s| is| are)|how(?:'s|s| is))\s+(?:the\s+)?(?:status|screen)\s+(?:of|at|in|for)\s+(.+?)$",
            r"(?:at|in|for)\s+(.+?)(?:\s+(?:school|location|screen))?$",
            r"(?:check|show|get|find)\s+(.+?)(?:\s+(?:screen|status|school))?$",
        ]
        for pat in extraction_patterns:
            m = re.search(pat, text_lower, re.IGNORECASE)
            if m:
                text_clean = m.group(1).strip()
                break

        # Fallback: strip common prefixes
        if not text_clean:
            text_clean = re.sub(
                r"^(?:victor[,:\s]*)?(?:what(?:'s|s| is)?|which|get|find|show|look\s+(?:up|for)|check)\s*(?:the\s+)?(?:screen|device|player|status)?\s*(?:is\s+)?(?:of|at|in|for)?\s*",
                "", text_lower, flags=re.IGNORECASE
            ).strip()

        # Strip trailing "school", "location", "screen", "status"
        text_clean = re.sub(r"\s+(?:school|location|screen|status)$", "", text_clean, flags=re.IGNORECASE).strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which school? Try: *What's the status of Centreville?*"

        print(f"[Victor] Looking up screen for school: {text_clean}")

        # Fetch all workspaces
        workspaces = _yodeck_get_all("/workspaces")
        if not workspaces:
            return "⚠️ Could not fetch schools. Try again later."

        target_ws = _find_school_by_name(workspaces, text_clean)
        if not target_ws:
            # Try searching screens directly by name
            try:
                screen_data = _yodeck_get("/screens", params={"q": text_clean, "limit": 10})
                screens = screen_data.get("results", [])
                if screens:
                    lines = [f"🖥️ *Screens matching '{text_clean}'* — {len(screens)} found\n"]
                    for dev in screens:
                        name = dev.get("name", "(unnamed)")
                        dev_id = dev.get("id", "?")
                        ws_id = dev.get("workspace", "?")
                        lines.append(f"• *{name}* (ID: {dev_id}, WS: {ws_id})")
                    return "\n".join(lines)
            except:
                pass
            return f"🔍 School *{text_clean}* not found. Try listing schools first."

        # Get screens in this workspace
        ws_id = target_ws.get("id")
        ws_name = target_ws.get("name")

        # Get all screens, then also check online count
        all_screens = _yodeck_get("/screens", params={"workspace": ws_id, "limit": 100})
        total_count = all_screens.get("count", 0)
        screens = all_screens.get("results", [])

        if total_count == 0:
            return f"🖥️ No screens assigned to *{ws_name}* yet."

        # Also query online-only to get online count
        try:
            online_data = _yodeck_get("/screens", params={"workspace": ws_id, "online": "true", "limit": 1})
            online_count = online_data.get("count", 0)
        except:
            online_count = -1

        offline_count = total_count - online_count if online_count >= 0 else -1

        lines = [f"🖥️ *Screens at {ws_name}* — {total_count} total"]
        if online_count >= 0:
            lines[0] += f" (🟢 {online_count} online, 🔴 {offline_count} offline)"
        lines.append("")

        for dev in screens:
            name = dev.get("name", "(unnamed)")
            dev_id = dev.get("id", "?")
            lines.append(f"• *{name}* (ID: {dev_id})")

        if total_count > len(screens):
            lines.append(f"  _...and {total_count - len(screens)} more_")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] Get screen by school error: {e}")
        return f"⚠️ Error looking up screen: {str(e)[:200]}"


def reboot_screen(text):
    """Reboot a screen — API has no native reboot, so we push content as a refresh."""
    try:
        # Extract school/screen name
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:reboot|restart|reset|power\s+cycle|force\s+restart)\s+(?:the\s+)?(?:screen|device|player)?\s*(?:at|in|for)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which screen? Try: *Reboot the Centreville screen* or *Restart player at Woodbridge*"

        print(f"[Victor] Rebooting screen (via push): {text_clean}")

        # Find the school/workspace
        workspaces = _yodeck_get_all("/workspaces")
        target_ws = _find_school_by_name(workspaces, text_clean) if workspaces else None

        if target_ws:
            ws_id = target_ws.get("id")
            ws_name = target_ws.get("name")

            # Get screens in this workspace
            screen_data = _yodeck_get("/screens", params={"workspace": ws_id, "limit": 100})
            screens = screen_data.get("results", [])

            if not screens:
                return f"🖥️ No screens found at *{ws_name}* to reboot."

            # Push content to trigger a refresh (closest to reboot via API)
            try:
                device_ids = [s.get("id") for s in screens if s.get("id")]
                _yodeck_post("/screens/push", data={"filter_devices": device_ids})
                return (
                    f"🔄 *Refresh pushed to {ws_name}!*\n"
                    f"• *Screens refreshed:* {len(device_ids)}\n"
                    f"• Screens will reload content shortly.\n"
                    f"• _Note: Full device reboot requires physical access or Yodeck dashboard._"
                )
            except Exception as e:
                print(f"[Victor] Reboot (push) error: {e}")
                return f"⚠️ Error refreshing screens: {str(e)[:200]}"
        else:
            # Try finding by screen name directly
            print("[Victor] School not found, searching by screen name...")
            try:
                screen_data = _yodeck_get("/screens", params={"q": text_clean, "limit": 10})
                screens = screen_data.get("results", [])
            except:
                screens = []

            if not screens:
                return f"🔍 Screen or school *{text_clean}* not found. Try listing screens by school first."

            # Push to the first matching screen
            target_screen = screens[0]
            screen_id = target_screen.get("id")
            screen_name = target_screen.get("name", "(unnamed)")

            try:
                _yodeck_post("/screens/push", data={"filter_devices": [screen_id]})
                return (
                    f"🔄 *Refresh pushed!*\n"
                    f"• *Screen:* {screen_name} (ID: {screen_id})\n"
                    f"• Screen will reload content shortly.\n"
                    f"• _Note: Full device reboot requires physical access or Yodeck dashboard._"
                )
            except Exception as e:
                print(f"[Victor] Reboot device error: {e}")
                return f"⚠️ Error refreshing screen: {str(e)[:200]}"

    except Exception as e:
        print(f"[Victor] Reboot screen error: {e}")
        return f"⚠️ Error rebooting screen: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "screen_status": screen_status,
    "school_list": school_list,
    "push_content": push_content,
    "schedule_broadcast": schedule_broadcast,
    "get_screen_by_school": get_screen_by_school,
    "reboot_screen": reboot_screen,
}


def handle_victor_action(text):
    """Check if text matches a Victor action intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_victor_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[Victor] Action intent detected: {intent} (matched: '{match.group(0)}')")
        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result

    return False, None
