"""
LARA Drive Actions — Google Drive read/write for client production files.

Handles:
- _CLIENTS folder tree (deliverables, scripts, call sheets, roadmaps)
- FOOTAGE Shared Drive (raw footage for editing team)

Uses the same Google auth as lara_actions.py (DWD impersonating michael@mwmcreations.com).
Requires `drive` scope in DWD config (Workspace Admin → API Controls → Domain-wide delegation).

Env vars:
- LARA_DRIVE_CLIENTS_FOLDER_ID   (My Drive folder ID of _CLIENTS)
- LARA_DRIVE_FOOTAGE_DRIVE_ID    (Shared Drive ID of FOOTAGE)

Safety model:
- READS (list, search, read) → autonomous
- WRITES (upload, create folder) → two-step approval (draft → confirm)
- PERMISSION CHANGES (share) → two-step approval with explicit email echo
"""

import os
import re
import io
from datetime import datetime
import pytz

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ── Config ──────────────────────────────────────────────────────────
TIMEZONE = "America/New_York"
CLIENTS_FOLDER_ID = os.getenv("LARA_DRIVE_CLIENTS_FOLDER_ID", "")
FOOTAGE_DRIVE_ID = os.getenv("LARA_DRIVE_FOOTAGE_DRIVE_ID", "")

SCOPES_DRIVE = [
    "https://www.googleapis.com/auth/drive",
]


# ── Service Builder ─────────────────────────────────────────────────
def _get_drive_service():
    """Get authenticated Google Drive service using DWD."""
    # Lazy import to avoid circular dependency with lara_actions.py
    from lara_actions import _get_google_creds
    return build(
        "drive", "v3",
        credentials=_get_google_creds(SCOPES_DRIVE, use_dwd=True),
        cache_discovery=False,
    )


# ── Folder Resolution ───────────────────────────────────────────────
def _list_immediate_children(parent_id, drive=None, is_shared_drive_root=False):
    """List immediate children of a folder or Shared Drive root.
    Returns list of {id, name, mimeType} dicts.
    """
    drive = drive or _get_drive_service()
    results = []
    page_token = None

    # For Shared Drive root, parent_id IS the drive ID itself
    query = f"'{parent_id}' in parents and trashed=false"

    while True:
        kwargs = {
            "q": query,
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)",
            "pageSize": 100,
            "pageToken": page_token,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            "orderBy": "name",
        }
        if is_shared_drive_root:
            kwargs["corpora"] = "drive"
            kwargs["driveId"] = parent_id

        resp = drive.files().list(**kwargs).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def _resolve_client_folder(client_name, root_id, is_shared_drive=False):
    """Find a client subfolder inside the _CLIENTS or FOOTAGE root by fuzzy name match.
    Returns (folder_dict, all_candidates) where folder_dict is the best match or None.
    """
    if not root_id:
        return None, []

    drive = _get_drive_service()
    # List top-level subfolders under the root
    children = _list_immediate_children(root_id, drive, is_shared_drive_root=is_shared_drive)
    folders = [f for f in children if f["mimeType"] == "application/vnd.google-apps.folder"]

    search_lower = client_name.lower().strip()

    # Try exact/substring match
    for f in folders:
        name_lower = f["name"].lower()
        if search_lower == name_lower:
            return f, folders
    for f in folders:
        name_lower = f["name"].lower()
        if search_lower in name_lower or name_lower in search_lower:
            return f, folders

    # Word-by-word fuzzy
    search_words = search_lower.split()
    for f in folders:
        name_lower = f["name"].lower()
        if all(w in name_lower for w in search_words):
            return f, folders

    return None, folders


# ── Helpers ─────────────────────────────────────────────────────────
def _human_size(bytes_val):
    if not bytes_val:
        return ""
    try:
        bytes_val = int(bytes_val)
    except (ValueError, TypeError):
        return ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.0f} {unit}" if unit == "B" else f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def _mime_emoji(mime_type):
    if "folder" in mime_type:
        return "📁"
    if "document" in mime_type:
        return "📄"
    if "spreadsheet" in mime_type:
        return "📊"
    if "presentation" in mime_type:
        return "🎞️"
    if "pdf" in mime_type:
        return "📕"
    if "video" in mime_type:
        return "🎬"
    if "image" in mime_type:
        return "🖼️"
    if "audio" in mime_type:
        return "🎵"
    if "zip" in mime_type or "archive" in mime_type:
        return "🗜️"
    return "📎"


def _format_file_line(f):
    emoji = _mime_emoji(f.get("mimeType", ""))
    name = f.get("name", "(unnamed)")
    size = _human_size(f.get("size"))
    size_str = f" · {size}" if size else ""
    link = f.get("webViewLink", "")
    if link:
        return f"{emoji} <{link}|{name}>{size_str}"
    return f"{emoji} {name}{size_str}"


# ── Action: List Client Files (_CLIENTS tree) ───────────────────────
def list_client_files(text):
    """List files inside a client's folder in _CLIENTS."""
    try:
        if not CLIENTS_FOLDER_ID:
            return "⚠️ `LARA_DRIVE_CLIENTS_FOLDER_ID` not set — can't access _CLIENTS."

        # Extract client name
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        match = re.search(
            r"(?:list|show|get|pull|what)(?:\s+me)?\s+(?:the\s+)?(?:files|documents|deliverables|content|stuff)\s+(?:for|in|of|from)\s+(.+?)(?:\s+(?:folder|drive|client))?$",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"(?:client|deliverable)\s+(?:files|folder|content)\s+(?:for|of)\s+(.+)",
                text_clean, re.IGNORECASE
            )
        if not match:
            # Fallback: strip leading verb and use the rest
            search = re.sub(
                r"^(?:list|show|get|pull|what(?:\'s|s)?)\s+(?:me\s+)?(?:the\s+)?(?:files?|documents?|deliverables?)\s+(?:for|in|of|from)?\s*",
                "", text_clean, flags=re.IGNORECASE
            ).strip()
        else:
            search = match.group(1).strip().strip('"\'')

        if not search or len(search) < 2:
            return "🔍 Which client's files? Try: *list files for Victory MA*"

        folder, all_folders = _resolve_client_folder(search, CLIENTS_FOLDER_ID, is_shared_drive=False)
        if not folder:
            sample = ", ".join(f["name"] for f in all_folders[:6]) if all_folders else "(none)"
            return (
                f'🔍 No _CLIENTS folder found matching *"{search}"*.\n'
                f"_Available:_ {sample}{'...' if len(all_folders) > 6 else ''}"
            )

        # List children of the matched client folder
        children = _list_immediate_children(folder["id"])
        if not children:
            return f"📁 *{folder['name']}* is empty."

        lines = [f"📁 *_CLIENTS / {folder['name']}* — {len(children)} items\n"]
        for f in children[:30]:
            lines.append(_format_file_line(f))
        if len(children) > 30:
            lines.append(f"\n_...and {len(children) - 30} more._")
        lines.append(f"\n<{folder.get('webViewLink', '#')}|Open folder>")
        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Drive list client files error: {e}")
        return f"⚠️ Error listing client files: {str(e)[:200]}"


# ── Action: List Footage Files (FOOTAGE Shared Drive) ───────────────
def list_footage_files(text):
    """List files in the FOOTAGE Shared Drive — root if no client given, client folder if specified."""
    try:
        if not FOOTAGE_DRIVE_ID:
            return "⚠️ `LARA_DRIVE_FOOTAGE_DRIVE_ID` not set — can't access FOOTAGE."

        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        # Try: "list footage for <client>"
        match = re.search(
            r"(?:list|show|get|pull|what)(?:\s+me)?\s+(?:the\s+)?(?:footage|raw\s*(?:files|material)?|videos?|clips?)\s+(?:for|in|of|from)\s+(.+?)(?:\s+(?:folder|drive|client))?$",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"(?:footage|raw)\s+(?:folder|files)\s+(?:for|of)\s+(.+)",
                text_clean, re.IGNORECASE
            )

        # Fallback: no client specified → list the Shared Drive root
        if not match:
            root_children = _list_immediate_children(
                FOOTAGE_DRIVE_ID, is_shared_drive_root=True
            )
            if not root_children:
                return "🎬 *FOOTAGE* Shared Drive is empty."
            # Sort folders first, then files
            root_children.sort(key=lambda f: (
                0 if f.get("mimeType") == "application/vnd.google-apps.folder" else 1,
                f.get("name", "").lower()
            ))
            lines = [f"🎬 *FOOTAGE Shared Drive root* — {len(root_children)} items\n"]
            for f in root_children[:40]:
                lines.append(_format_file_line(f))
            if len(root_children) > 40:
                lines.append(f"\n_...and {len(root_children) - 40} more._")
            lines.append(f"\n<https://drive.google.com/drive/folders/{FOOTAGE_DRIVE_ID}|Open FOOTAGE drive>")
            return "\n".join(lines)

        # Client-specific lookup
        search = match.group(1).strip().strip('"\'')
        folder, all_folders = _resolve_client_folder(search, FOOTAGE_DRIVE_ID, is_shared_drive=True)
        if not folder:
            sample = ", ".join(f["name"] for f in all_folders[:6]) if all_folders else "(none)"
            return (
                f'🔍 No FOOTAGE folder found matching *"{search}"*.\n'
                f"_Available:_ {sample}{'...' if len(all_folders) > 6 else ''}"
            )

        children = _list_immediate_children(folder["id"])
        if not children:
            return f"🎬 *{folder['name']}* (FOOTAGE) is empty."

        lines = [f"🎬 *FOOTAGE / {folder['name']}* — {len(children)} items\n"]
        for f in children[:30]:
            lines.append(_format_file_line(f))
        if len(children) > 30:
            lines.append(f"\n_...and {len(children) - 30} more._")
        lines.append(f"\n<{folder.get('webViewLink', '#')}|Open folder>")
        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Drive list footage error: {e}")
        return f"⚠️ Error listing footage: {str(e)[:200]}"


# ── Action: Search Drive ────────────────────────────────────────────
def search_drive(text):
    """Full-text search across _CLIENTS + FOOTAGE trees."""
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        # Require explicit "in drive/folder" context OR "search for" phrasing
        match = re.search(
            r"(?:find|locate|look\s*for)\s+(?:the\s+)?(.+?)\s+(?:in\s+)?(?:drive|google\s*drive|_?clients|footage|folder)\b",
            text_clean, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r"search\s+(?:drive\s+)?(?:for\s+)?(.+?)(?:\s+(?:in|on)\s+(?:drive|folder))?$",
                text_clean, re.IGNORECASE
            )
        if not match:
            return "🔍 What should I search for? Try: *find Victory script in drive*"

        query_term = match.group(1).strip().strip('"\'')
        if len(query_term) < 2:
            return "🔍 Search term too short. Give me at least 2 characters."

        drive = _get_drive_service()
        # Escape single quotes in search term
        safe_term = query_term.replace("'", "\\'")
        query = f"name contains '{safe_term}' and trashed=false"

        resp = drive.files().list(
            q=query,
            fields="files(id, name, mimeType, modifiedTime, size, webViewLink, parents)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = resp.get("files", [])

        if not files:
            return f'🔍 No files found matching *"{query_term}"*.'

        lines = [f"🔍 *Search results for \"{query_term}\"* — {len(files)} hits\n"]
        for f in files[:20]:
            lines.append(_format_file_line(f))
        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Drive search error: {e}")
        return f"⚠️ Error searching Drive: {str(e)[:200]}"


# ── Action: Create Client Folder (two-step approval) ───────────────
def create_client_folder(text):
    """Create a new client folder in _CLIENTS (and optionally FOOTAGE).
    Two-step flow: prep draft unless 'confirm' keyword present.
    """
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        has_confirm = bool(re.search(r"\b(confirm|go\s*ahead|do\s*it|yes\s+create)\b", text_clean, re.IGNORECASE))

        match = re.search(
            r"(?:create|make|add|new)\s+(?:a\s+)?(?:folder|client\s*folder)\s+(?:for\s+)?(.+?)(?:\s+(?:in|on)\s+(?:drive|clients?|_clients))?$",
            text_clean, re.IGNORECASE
        )
        if not match:
            return "🤔 Try: *create folder for [Client Name]*"

        client_name = match.group(1).strip().strip('"\'').rstrip(",")
        # Strip trailing "confirm" etc
        client_name = re.sub(r"\s*(?:confirm|go\s*ahead|do\s*it|yes)\b.*$", "", client_name, flags=re.IGNORECASE).strip()

        if not client_name:
            return "🤔 I need a client name. Try: *create folder for New Client Name*"

        if not has_confirm:
            return (
                f"📁 *Create Client Folder — Draft*\n"
                f"• *Client name:* {client_name}\n"
                f"• *In:* _CLIENTS/ (My Drive)\n"
                f"• *Action:* Create new subfolder named `{client_name}`\n\n"
                f"_To confirm, reply:_ `LARA confirm create folder for {client_name}`"
            )

        # Execute
        if not CLIENTS_FOLDER_ID:
            return "⚠️ `LARA_DRIVE_CLIENTS_FOLDER_ID` not set — can't create folder."

        drive = _get_drive_service()
        metadata = {
            "name": client_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [CLIENTS_FOLDER_ID],
        }
        new_folder = drive.files().create(
            body=metadata,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()

        return (
            f"✅ *Folder created!*\n"
            f"• *Name:* {new_folder['name']}\n"
            f"• *Location:* _CLIENTS/\n"
            f"• <{new_folder.get('webViewLink', '#')}|Open folder>"
        )
    except Exception as e:
        print(f"[LARA] Create folder error: {e}")
        return f"⚠️ Error creating folder: {str(e)[:200]}"


# ── Action: Share Client Deliverable (two-step approval) ───────────
def share_with_external(text):
    """Share a client folder with an external email.
    Two-step flow: requires 'confirm' keyword to execute.
    Handles both _CLIENTS (share with client) and FOOTAGE (share with editor).
    """
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        has_confirm = bool(re.search(r"\b(confirm|go\s*ahead|do\s*it)\b", text_clean, re.IGNORECASE))

        # Parse: "share [client] [folder|footage] with [email]"
        #     or "share [client] with [email]"
        match = re.search(
            r"share\s+(?:the\s+)?(.+?)\s+(?:(footage|raw\s*files?|deliverables?|files?|folder)\s+)?(?:with|to)\s+(\S+@\S+)",
            text_clean, re.IGNORECASE
        )
        if not match:
            return (
                "🤔 Try: *share Victory MA with brian@victoryma.com*\n"
                "Or: *share Victory MA footage with editor@example.com*"
            )

        client_name = match.group(1).strip().strip('"\'').rstrip(",")
        folder_type = (match.group(2) or "").strip().lower()
        target_email = match.group(3).strip().rstrip(".,;")

        # Strip potential "confirm" trailing in client name
        client_name = re.sub(r"\s*(?:confirm|go\s*ahead|do\s*it)\b.*$", "", client_name, flags=re.IGNORECASE).strip()

        is_footage = "footage" in folder_type or "raw" in folder_type
        root_id = FOOTAGE_DRIVE_ID if is_footage else CLIENTS_FOLDER_ID
        root_label = "FOOTAGE" if is_footage else "_CLIENTS"

        if not root_id:
            return f"⚠️ `LARA_DRIVE_{'FOOTAGE_DRIVE_ID' if is_footage else 'CLIENTS_FOLDER_ID'}` not set."

        folder, _ = _resolve_client_folder(client_name, root_id, is_shared_drive=is_footage)
        if not folder:
            return f'🔍 No {root_label} folder found matching *"{client_name}"*.'

        # Validate email format (very light)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", target_email):
            return f"⚠️ *{target_email}* doesn't look like a valid email address."

        if not has_confirm:
            return (
                f"🔴 *PERMISSION CHANGE — Draft*\n\n"
                f"• *Action:* Grant *Editor* access\n"
                f"• *Folder:* {root_label} / *{folder['name']}*\n"
                f"• *Recipient:* `{target_email}`\n"
                f"• *Scope:* This folder and all its contents\n\n"
                f"⚠️ _This is a permission change. It cannot be easily undone by LARA._\n\n"
                f"_To confirm, reply exactly:_\n"
                f"`LARA confirm share {client_name}{' footage' if is_footage else ''} with {target_email}`"
            )

        # Execute
        drive = _get_drive_service()
        permission = {
            "type": "user",
            "role": "writer",
            "emailAddress": target_email,
        }
        result = drive.permissions().create(
            fileId=folder["id"],
            body=permission,
            fields="id, emailAddress, role",
            sendNotificationEmail=True,
            supportsAllDrives=True,
        ).execute()

        # Audit log to Production Tracker (best-effort)
        _audit_log_share(
            folder_name=folder["name"],
            folder_type=root_label,
            folder_id=folder["id"],
            recipient=target_email,
            role="writer",
        )

        return (
            f"✅ *Shared!*\n"
            f"• *Folder:* {root_label} / {folder['name']}\n"
            f"• *With:* {target_email}\n"
            f"• *Role:* Editor\n"
            f"• Notification email sent by Google\n\n"
            f"_Audit logged to Production Tracker._"
        )
    except Exception as e:
        print(f"[LARA] Share error: {e}")
        return f"⚠️ Error sharing folder: {str(e)[:200]}"


# ── Audit Log ───────────────────────────────────────────────────────
def _audit_log_share(folder_name, folder_type, folder_id, recipient, role):
    """Append a row to the LARA_Share_Audit_Log tab in the Production Tracker."""
    try:
        from lara_actions import _get_sheets_service, PRODUCTION_SHEET_ID
        if not PRODUCTION_SHEET_ID:
            return
        svc = _get_sheets_service()
        now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        row = [now, folder_type, folder_name, folder_id, recipient, role, "LARA"]

        # Try append to existing tab; if missing, create it
        try:
            svc.spreadsheets().values().append(
                spreadsheetId=PRODUCTION_SHEET_ID,
                range="LARA_Share_Audit_Log!A:G",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
        except Exception:
            # Tab doesn't exist — create it
            svc.spreadsheets().batchUpdate(
                spreadsheetId=PRODUCTION_SHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": "LARA_Share_Audit_Log"}}}]},
            ).execute()
            header = ["Timestamp", "Folder Type", "Folder Name", "Folder ID", "Recipient", "Role", "Actor"]
            svc.spreadsheets().values().update(
                spreadsheetId=PRODUCTION_SHEET_ID,
                range="LARA_Share_Audit_Log!A1:G1",
                valueInputOption="RAW",
                body={"values": [header]},
            ).execute()
            svc.spreadsheets().values().append(
                spreadsheetId=PRODUCTION_SHEET_ID,
                range="LARA_Share_Audit_Log!A:G",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
    except Exception as e:
        print(f"[LARA] Audit log error (non-fatal): {e}")


# ── Intent Patterns ─────────────────────────────────────────────────
LARA_DRIVE_INTENTS = {
    "drive_list_footage": [
        r"(?:list|show|get|pull|what(?:'s|s)?)\s+(?:me\s+)?(?:the\s+)?(?:footage|raw\s*(?:files|material)?|clips?)\s+(?:for|in|of|from)\s+.+",
        r"(?:footage|raw)\s+(?:folder|files)\s+(?:for|of)\s+.+",
    ],
    "drive_list_client": [
        r"(?:list|show|get|pull|what(?:'s|s)?)\s+(?:me\s+)?(?:the\s+)?(?:files|documents|deliverables|content|stuff)\s+(?:for|in|of|from)\s+.+",
        r"(?:client|deliverable)\s+(?:files|folder|content)\s+(?:for|of)\s+.+",
    ],
    "drive_create_folder": [
        r"(?:create|make|add|new)\s+(?:a\s+)?(?:folder|client\s*folder)\s+(?:for\s+)?.+",
    ],
    "drive_share": [
        r"share\s+(?:the\s+)?.+?\s+(?:with|to)\s+\S+@\S+",
    ],
    "drive_search": [
        r"(?:find|locate|look\s*for)\s+(?:the\s+)?.+?\s+(?:in\s+)?(?:drive|google\s*drive|_?clients|footage|folder)\b",
        r"search\s+(?:drive\s+)?(?:for\s+)?.+?(?:\s+(?:in|on)\s+(?:drive|folder))?$",
        r"drive\s+search\s+.+",
    ],
}


DRIVE_HANDLERS = {
    "drive_list_footage": list_footage_files,
    "drive_list_client": list_client_files,
    "drive_create_folder": create_client_folder,
    "drive_share": share_with_external,
    "drive_search": search_drive,
}
