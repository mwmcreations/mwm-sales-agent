"""
Victor Yodeck Action Handlers — Real-time Slack action capability for Victor (MWM Screens Support).

Handles:
- Screen status (list all screens with online/offline status)
- School list (list all schools/workspaces with assigned/unassigned screen counts)
- Push content (trigger content refresh to specific screen(s))
- Schedule broadcast (set event mode/takeover for all or selected screens)
- Get screen by school (look up screen by school name)
- Reboot screen (remote reboot a specific player)

Uses YODECK_API_KEY from Railway env vars.
Yodeck REST API v1 — https://app.yodeck.com/api/v1/
Auth header: Authorization: Api-Key {token}
"""

import os
import re
import json
from datetime import datetime

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
YODECK_API_KEY = os.getenv("YODECK_API_KEY", "")
YODECK_BASE_URL = "https://app.yodeck.com/api/v1"


def _yodeck_headers():
    """Return auth headers for Yodeck API."""
    return {
        "Authorization": f"Api-Key {YODECK_API_KEY}",
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


def _yodeck_patch(endpoint, data=None):
    """Make a PATCH request to Yodeck API."""
    if not YODECK_API_KEY:
        raise RuntimeError("YODECK_API_KEY not configured")
    url = f"{YODECK_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.patch(url, headers=_yodeck_headers(), json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Intent Detection ────────────────────────────────────────────────
VICTOR_ACTION_INTENTS = {
    "screen_status": [
        r"(?:what|list|show|get|check|pull)\s+(?:screen|device|player)\s*(?:status|state)?",
        r"(?:which|are|what)\s+(?:screens?|devices?|players?)\s+(?:are|is)\s+(?:online|offline|up|down|active)",
        r"screen(?:s)?\s+(?:status|health|overview)",
        r"(?:are|is)\s+(?:all\s+)?(?:screens?|devices?)\s+(?:online|active)",
    ],
    "school_list": [
        r"(?:list|show|get|what|display)\s+(?:schools?|locations?|workspaces?|facilities?)",
        r"(?:what|which)\s+(?:schools?|locations?)\s+(?:do\s+)?(?:we|i)\s+(?:have|operate)",
        r"(?:all|every)\s+(?:schools?|locations?|facilities?)",
        r"schools?\s+(?:list|overview|summary)",
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
        r"(?:what|which|get|find|show)\s+(?:screen|device|player)\s+(?:is\s+)?(?:at|in|for)\s+(.+)",
        r"(?:screen|device|player)\s+(?:at|in|for)\s+(.+?)(?:\s+(?:school|location|facility))?",
        r"look\s+(?:up|for)\s+(?:screen|device|player)\s+(?:at|for)\s+(.+)",
    ],
    "reboot_screen": [
        r"(?:reboot|restart|reset|power\s+cycle)\s+(?:the\s+)?(?:screen|device|player|screen)(?:\s+at)?(?:\s+(.+))?",
        r"(?:reboot|restart)\s+(?:screen|device|player)\s+(?:at|in|for)\s+(.+)",
        r"(?:force\s+)?restart\s+(?:the\s+)?(?:device|screen|player)\s+(.+)",
    ],
}


def _find_school_by_name(schools, search_text):
    """Fuzzy match a school by name.
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
        data = _yodeck_get("/devices", params={"limit": 500})
        devices = data.get("devices", [])

        if not devices:
            return "🖥️ *No screens found in Yodeck.*"

        # Group by status
        online = []
        offline = []
        for device in devices:
            status = device.get("status", "unknown").lower()
            device_info = {
                "id": device.get("id", ""),
                "name": device.get("name", "(unnamed)"),
                "status": status,
            }
            if status in ["online", "active", "ok"]:
                online.append(device_info)
            else:
                offline.append(device_info)

        lines = [f"🖥️ *Screen Status* — {len(devices)} total\n"]
        lines.append(f"🟢 *Online:* {len(online)}")
        for dev in online:
            lines.append(f"  • {dev['name']} (ID: {dev['id']})")

        if offline:
            lines.append(f"\n🔴 *Offline:* {len(offline)}")
            for dev in offline:
                lines.append(f"  • {dev['name']} (ID: {dev['id']})")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] Screen status error: {e}")
        return f"⚠️ Error fetching screen status: {str(e)[:200]}"


def school_list(text):
    """List all schools/workspaces with assigned/unassigned screen counts."""
    try:
        print("[Victor] Fetching schools/workspaces from Yodeck API...")
        # Try /workspaces first, then /groups, then fall back to grouping devices manually
        try:
            data = _yodeck_get("/workspaces", params={"limit": 500})
            workspaces = data.get("workspaces", [])
        except Exception as e:
            print(f"[Victor] /workspaces endpoint failed: {e}, trying /groups...")
            data = _yodeck_get("/groups", params={"limit": 500})
            workspaces = data.get("groups", [])

        if not workspaces:
            # Fallback: group devices by workspace/location field
            print("[Victor] No explicit workspaces, grouping devices manually...")
            device_data = _yodeck_get("/devices", params={"limit": 500})
            devices = device_data.get("devices", [])

            workspace_map = {}
            for dev in devices:
                ws = dev.get("workspace", dev.get("location", "Unassigned"))
                if ws not in workspace_map:
                    workspace_map[ws] = {"name": ws, "screens": []}
                workspace_map[ws]["screens"].append(dev)

            workspaces = list(workspace_map.values())

        if not workspaces:
            return "📍 *No schools/workspaces found in Yodeck.*"

        lines = [f"📍 *Schools/Workspaces* — {len(workspaces)} found\n"]
        total_assigned = 0
        total_unassigned = 0

        for ws in workspaces:
            name = ws.get("name", "(untitled)")
            screens = ws.get("screens", [])
            screen_count = len(screens)
            total_assigned += screen_count

            # Try to fetch unassigned screens for this workspace
            unassigned = ws.get("unassigned_devices", 0)
            total_unassigned += unassigned

            line = f"• *{name}*\n  Screens: {screen_count}"
            if unassigned > 0:
                line += f" (assigned) + {unassigned} (unassigned)"
            lines.append(line)

        lines.append(f"\n📊 *Total:* {total_assigned} assigned, {total_unassigned} unassigned")
        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] School list error: {e}")
        return f"⚠️ Error fetching schools: {str(e)[:200]}"


def push_content(text):
    """Trigger content refresh/update to specific screen(s)."""
    try:
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:push|send|deploy|broadcast|sync|refresh|update)\s+(?:content|media|playlist)?\s+(?:to|on)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip()

        # Extract screen/school name if present
        school_match = re.search(
            r"(?:at|in|for)\s+(.+?)(?:\s+school|\s+location)?$",
            text_clean, re.IGNORECASE
        )
        target_school = None
        if school_match:
            target_school = school_match.group(1).strip()
            text_clean = re.sub(
                r"\s+(?:at|in|for)\s+.+?(?:\s+school|\s+location)?$",
                "", text_clean, flags=re.IGNORECASE
            ).strip()

        # Check if pushing to all screens
        if re.search(r"(?:all|every)\s+(?:screens?|devices?|players?)", text_clean, re.IGNORECASE):
            target_school = None

        if target_school:
            print(f"[Victor] Pushing content to school: {target_school}")
            # Find school/workspace
            try:
                data = _yodeck_get("/workspaces", params={"limit": 500})
                workspaces = data.get("workspaces", [])
            except:
                try:
                    data = _yodeck_get("/groups", params={"limit": 500})
                    workspaces = data.get("groups", [])
                except:
                    workspaces = []

            if workspaces:
                target_ws = _find_school_by_name(workspaces, target_school)
                if not target_ws:
                    return f"🔍 School *{target_school}* not found. Try listing schools first."

                ws_id = target_ws.get("id")
                # Push to all screens in workspace
                try:
                    _yodeck_post(f"/workspaces/{ws_id}/refresh", data={})
                    return f"✅ *Content pushed!*\n• *School:* {target_ws.get('name')}\n• All screens will update shortly."
                except Exception as e:
                    print(f"[Victor] Push content error: {e}")
                    return f"⚠️ Error pushing content: {str(e)[:200]}"
            else:
                return "⚠️ Could not fetch schools. Try again later."
        else:
            print("[Victor] Pushing content to all screens")
            # Push to all devices
            try:
                data = _yodeck_get("/devices", params={"limit": 500})
                devices = data.get("devices", [])
                if not devices:
                    return "⚠️ No screens found to update."

                # Trigger refresh for all
                success_count = 0
                for dev in devices:
                    try:
                        device_id = dev.get("id")
                        _yodeck_post(f"/devices/{device_id}/refresh", data={})
                        success_count += 1
                    except Exception as dev_err:
                        print(f"[Victor] Failed to refresh device {dev.get('id')}: {dev_err}")

                return (
                    f"✅ *Content pushed to all screens!*\n"
                    f"• *Updated:* {success_count}/{len(devices)} screens\n"
                    f"• All screens will sync shortly."
                )
            except Exception as e:
                print(f"[Victor] Push to all error: {e}")
                return f"⚠️ Error pushing content: {str(e)[:200]}"

    except Exception as e:
        print(f"[Victor] Push content error: {e}")
        return f"⚠️ Error pushing content: {str(e)[:200]}"


def schedule_broadcast(text):
    """Schedule broadcast/event mode for all or selected screens."""
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
            print(f"[Victor] Scheduling broadcast for school: {target_school}")
            try:
                data = _yodeck_get("/workspaces", params={"limit": 500})
                workspaces = data.get("workspaces", [])
            except:
                workspaces = []

            if not workspaces:
                return f"⚠️ Could not find school *{target_school}*."

            target_ws = _find_school_by_name(workspaces, target_school)
            if not target_ws:
                return f"🔍 School *{target_school}* not found."

            ws_id = target_ws.get("id")
            try:
                payload = {
                    "mode": "broadcast",
                    "scheduled_for": f"{schedule_date} {schedule_time}",
                }
                _yodeck_post(f"/workspaces/{ws_id}/broadcast", data=payload)
                return (
                    f"📺 *Broadcast scheduled!*\n"
                    f"• *School:* {target_ws.get('name')}\n"
                    f"• *Start:* {schedule_date} at {schedule_time}\n"
                    f"• *Mode:* Event takeover enabled"
                )
            except Exception as e:
                print(f"[Victor] Schedule broadcast error: {e}")
                return f"⚠️ Error scheduling broadcast: {str(e)[:200]}"
        else:
            print("[Victor] Scheduling broadcast for all screens")
            try:
                payload = {
                    "mode": "broadcast",
                    "scheduled_for": f"{schedule_date} {schedule_time}",
                }
                _yodeck_post("/broadcast", data=payload)
                return (
                    f"📺 *Broadcast scheduled for all screens!*\n"
                    f"• *Start:* {schedule_date} at {schedule_time}\n"
                    f"• *Coverage:* All 37 schools"
                )
            except Exception as e:
                print(f"[Victor] Schedule broadcast (all) error: {e}")
                return f"⚠️ Error scheduling broadcast: {str(e)[:200]}"

    except Exception as e:
        print(f"[Victor] Schedule broadcast error: {e}")
        return f"⚠️ Error scheduling broadcast: {str(e)[:200]}"


def get_screen_by_school(text):
    """Look up screen/device by school name."""
    try:
        # Extract school name
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:what|which|get|find|show|look\s+(?:up|for))\s+(?:screen|device|player|the\s+screen)?\s+(?:is\s+)?(?:at|in|for)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which school? Try: *What screen is at Centreville?*"

        print(f"[Victor] Looking up screen for school: {text_clean}")

        # Fetch workspaces
        try:
            data = _yodeck_get("/workspaces", params={"limit": 500})
            workspaces = data.get("workspaces", [])
        except:
            try:
                data = _yodeck_get("/groups", params={"limit": 500})
                workspaces = data.get("groups", [])
            except:
                workspaces = []

        if not workspaces:
            return "⚠️ Could not fetch schools. Try again later."

        target_ws = _find_school_by_name(workspaces, text_clean)
        if not target_ws:
            return f"🔍 School *{text_clean}* not found."

        # Get screens in this workspace
        ws_id = target_ws.get("id")
        try:
            dev_data = _yodeck_get(f"/workspaces/{ws_id}/devices", params={"limit": 100})
            devices = dev_data.get("devices", [])
        except:
            # Fallback: fetch all devices and filter
            dev_data = _yodeck_get("/devices", params={"limit": 500})
            all_devices = dev_data.get("devices", [])
            ws_name = target_ws.get("name", "").lower()
            devices = [d for d in all_devices if ws_name in d.get("workspace", "").lower() or ws_name in d.get("location", "").lower()]

        if not devices:
            return f"🖥️ No screens assigned to *{target_ws.get('name')}* yet."

        lines = [f"🖥️ *Screens at {target_ws.get('name')}* — {len(devices)} found\n"]
        for dev in devices:
            name = dev.get("name", "(unnamed)")
            status = dev.get("status", "unknown").lower()
            status_emoji = "🟢" if status in ["online", "active", "ok"] else "🔴"
            lines.append(f"{status_emoji} *{name}* (ID: {dev.get('id')}) — {status}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Victor] Get screen by school error: {e}")
        return f"⚠️ Error looking up screen: {str(e)[:200]}"


def reboot_screen(text):
    """Remote reboot a specific screen/device."""
    try:
        # Extract school/screen name
        text_clean = re.sub(
            r"^(?:victor[,:\s]*)?(?:reboot|restart|reset|power\s+cycle|force\s+restart)\s+(?:the\s+)?(?:screen|device|player)?\s*(?:at|in|for)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which screen? Try: *Reboot the Centreville screen* or *Restart player at Woodbridge*"

        print(f"[Victor] Rebooting screen: {text_clean}")

        # Find the school/screen
        try:
            data = _yodeck_get("/workspaces", params={"limit": 500})
            workspaces = data.get("workspaces", [])
        except:
            workspaces = []

        target_ws = _find_school_by_name(workspaces, text_clean) if workspaces else None

        if target_ws:
            # Reboot all screens in this workspace
            ws_id = target_ws.get("id")
            try:
                dev_data = _yodeck_get(f"/workspaces/{ws_id}/devices", params={"limit": 100})
                devices = dev_data.get("devices", [])
            except:
                dev_data = _yodeck_get("/devices", params={"limit": 500})
                all_devices = dev_data.get("devices", [])
                ws_name = target_ws.get("name", "").lower()
                devices = [d for d in all_devices if ws_name in d.get("workspace", "").lower()]

            if not devices:
                return f"🖥️ No screens found at *{target_ws.get('name')}* to reboot."

            success_count = 0
            for dev in devices:
                try:
                    device_id = dev.get("id")
                    _yodeck_post(f"/devices/{device_id}/reboot", data={})
                    success_count += 1
                except Exception as dev_err:
                    print(f"[Victor] Failed to reboot device {device_id}: {dev_err}")

            school_name = target_ws.get("name")
            return (
                f"🔄 *Reboot initiated!*\n"
                f"• *School:* {school_name}\n"
                f"• *Screens rebooting:* {success_count}/{len(devices)}\n"
                f"• Players will be back online in ~2-3 minutes."
            )
        else:
            # Try finding by device name directly
            print("[Victor] School not found, searching by device name...")
            dev_data = _yodeck_get("/devices", params={"limit": 500})
            devices = dev_data.get("devices", [])

            # Fuzzy match device name
            search_lower = text_clean.lower()
            target_device = None
            best_score = 0

            for dev in devices:
                dev_name = dev.get("name", "").lower()
                if search_lower in dev_name:
                    target_device = dev
                    break
                # Score based on word overlap
                search_words = [w for w in search_lower.split() if len(w) > 1]
                matches = sum(1 for w in search_words if w in dev_name)
                if matches > 0:
                    score = matches / len(search_words)
                    if score > best_score and score >= 0.5:
                        best_score = score
                        target_device = dev

            if not target_device:
                return f"🔍 Screen *{text_clean}* not found. Try listing screens by school first."

            device_id = target_device.get("id")
            device_name = target_device.get("name", "(unnamed)")

            try:
                _yodeck_post(f"/devices/{device_id}/reboot", data={})
                return (
                    f"🔄 *Reboot initiated!*\n"
                    f"• *Screen:* {device_name}\n"
                    f"• Player will be back online in ~2-3 minutes."
                )
            except Exception as e:
                print(f"[Victor] Reboot device error: {e}")
                return f"⚠️ Error rebooting screen: {str(e)[:200]}"

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
