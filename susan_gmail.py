"""
Susan Gmail Action Handlers — Gmail send with attachment support.

Handles:
- Send plain/HTML email via Gmail (as info@mwmcreations.com)
- Attach files from Google Drive to outgoing emails
- multipart/mixed MIME construction for PDF attachments

Uses GOOGLE_CREDENTIALS_JSON (DWD service account) from Railway env vars.
Impersonates info@mwmcreations.com for sending.

Session 31 — built per MATT ticket: Susan needs to send proposals w/ PDF attachments.
"""

import os
import re
import io
import json
import base64
import traceback

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ── Config ──────────────────────────────────────────────────────────
SUSAN_SEND_AS = os.getenv("SUSAN_GMAIL_SEND_AS", "info@mwmcreations.com")
TIMEZONE = "America/New_York"

SCOPES_GMAIL = ["https://www.googleapis.com/auth/gmail.send"]
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

# Central agent uploads folder on Google Drive: My Drive > _AGENTS > UPLOADS
# ALL agents save documents here; Susan (and others) grab files from here for email attachments.
# Standing rule from Michael — this is the single source of truth for all agent document uploads.
DRIVE_PROPOSALS_FOLDER_ID = os.getenv("SUSAN_DRIVE_PROPOSALS_FOLDER_ID", "128krn55oBdymptDD_8QD5dK_hnbp9peY")


# ── Service Builders ────────────────────────────────────────────────

def _get_google_creds(scopes, subject="michael@mwmcreations.com"):
    """Build DWD credentials. Always impersonate michael@ (the actual Workspace user).
    info@ is a send-as alias, not a user account — cannot be impersonated directly."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set")
    from google.oauth2 import service_account as _sa
    info = json.loads(creds_json)
    creds = _sa.Credentials.from_service_account_info(info, scopes=scopes)
    return creds.with_subject(subject)


def _get_gmail_service():
    """Gmail API client — impersonates michael@ (DWD), sends as info@ via MIME 'from' header."""
    return build("gmail", "v1", credentials=_get_google_creds(SCOPES_GMAIL), cache_discovery=False)


def _get_drive_service():
    """Drive API client for reading attachments."""
    # Drive uses michael@mwmcreations.com impersonation (file owner)
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set")
    from google.oauth2 import service_account as _sa
    info = json.loads(creds_json)
    creds = _sa.Credentials.from_service_account_info(
        info, scopes=SCOPES_DRIVE
    )
    creds = creds.with_subject("michael@mwmcreations.com")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Smart File Search on Google Drive ───────────────────────────────

def search_drive_file(filename_query):
    """
    Search Google Drive for a file by name (fuzzy match).

    Tries exact name first, then contains-match. If DRIVE_PROPOSALS_FOLDER_ID
    is set, searches that folder first before searching all of Drive.

    Args:
        filename_query: Filename or partial filename to search for

    Returns:
        dict with 'id', 'name', 'mimeType' or None if not found
    """
    try:
        drive = _get_drive_service()

        # Clean up the query
        query_clean = filename_query.strip().strip('"\'')

        # Build search queries (try exact first, then contains)
        search_queries = [
            f"name = '{query_clean}' and trashed = false",
            f"name contains '{query_clean}' and trashed = false",
        ]

        # If we don't have an exact extension, also try with .pdf
        if '.' not in query_clean:
            search_queries.insert(1, f"name = '{query_clean}.pdf' and trashed = false")
            search_queries.append(f"name contains '{query_clean}' and mimeType = 'application/pdf' and trashed = false")

        for sq in search_queries:
            # If proposals folder is set, search there first
            if DRIVE_PROPOSALS_FOLDER_ID:
                folder_query = f"{sq} and '{DRIVE_PROPOSALS_FOLDER_ID}' in parents"
                results = drive.files().list(
                    q=folder_query,
                    fields="files(id, name, mimeType, modifiedTime)",
                    pageSize=5,
                    orderBy="modifiedTime desc",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                files = results.get("files", [])
                if files:
                    best = files[0]
                    print(f"[SUSAN DRIVE] Found in proposals folder: {best['name']} ({best['id']})")
                    return best

            # Search all of Drive
            results = drive.files().list(
                q=sq,
                fields="files(id, name, mimeType, modifiedTime)",
                pageSize=5,
                orderBy="modifiedTime desc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files = results.get("files", [])
            if files:
                best = files[0]
                print(f"[SUSAN DRIVE] Found on Drive: {best['name']} ({best['id']})")
                return best

        print(f"[SUSAN DRIVE] No file found matching: {query_clean}")
        return None

    except Exception as e:
        print(f"[SUSAN DRIVE] Search error: {e}")
        traceback.print_exc()
        return None


# ── Core: Send Email with Optional Attachment ───────────────────────

def send_gmail(to, subject, body_html, drive_file_id=None, filename=None):
    """
    Send an email via Gmail as info@mwmcreations.com.

    Args:
        to: Recipient email address
        subject: Email subject line
        body_html: HTML body content
        drive_file_id: (optional) Google Drive file ID to attach
        filename: (optional) Display filename for the attachment

    Returns:
        dict with 'ok' bool and 'message_id' or 'error' string
    """
    try:
        gmail = _get_gmail_service()

        if drive_file_id:
            # ── multipart/mixed with attachment ──
            message = MIMEMultipart("mixed")
            message["to"] = to
            message["from"] = SUSAN_SEND_AS
            message["subject"] = subject

            # HTML body part
            body_part = MIMEText(body_html, "html")
            message.attach(body_part)

            # Download file from Google Drive
            drive = _get_drive_service()
            file_meta = drive.files().get(fileId=drive_file_id, fields="name,mimeType").execute()
            actual_filename = filename or file_meta.get("name", "attachment")
            mime_type = file_meta.get("mimeType", "application/octet-stream")

            request = drive.files().get_media(fileId=drive_file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            file_data = fh.getvalue()

            # Build attachment MIME part
            maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(file_data)
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition", "attachment",
                filename=actual_filename
            )
            message.attach(attachment)

            print(f"[SUSAN GMAIL] Sending to {to} with attachment: {actual_filename} ({len(file_data)} bytes)")
        else:
            # ── Simple HTML email (no attachment) ──
            message = MIMEText(body_html, "html")
            message["to"] = to
            message["from"] = SUSAN_SEND_AS
            message["subject"] = subject
            print(f"[SUSAN GMAIL] Sending to {to} (no attachment)")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = gmail.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        msg_id = result.get("id", "")
        print(f"[SUSAN GMAIL] Sent successfully — messageId: {msg_id}")
        return {"ok": True, "message_id": msg_id}

    except Exception as e:
        print(f"[SUSAN GMAIL] Error: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)[:500]}


# ── Action Handler (called from app.py) ─────────────────────────────

def handle_susan_gmail_action(text):
    """
    Parse and handle Susan's Gmail send commands.

    Supported patterns:
    - "send email to <email> subject <subject> body <body>"
    - "send email to <email> subject <subject> body <body> attach drive:<file_id>"
    - "gmail send <email> ..."

    Returns:
        (handled: bool, result: str)
    """
    text_lower = text.lower().strip()

    # Check if this is a Gmail send action
    gmail_triggers = [
        "send email to", "send gmail to", "gmail send",
        "email to", "send a email to", "send an email to",
        "send proposal to", "send the proposal to",
        "send pdf to", "attach and send",
    ]

    is_gmail_action = any(t in text_lower for t in gmail_triggers)
    if not is_gmail_action:
        return False, ""

    try:
        # Extract recipient email
        email_match = re.search(
            r'(?:to|recipient|for)\s+(\S+@\S+\.\S+)',
            text, re.IGNORECASE
        )
        if not email_match:
            return True, "⚠️ I need a recipient email address. Try: *send email to name@example.com subject ... body ...*"

        to_email = email_match.group(1).strip().strip('"\'<>')

        # Extract subject
        subject_match = re.search(
            r'subject[:\s]+["\']?(.+?)["\']?\s*(?:body|attach|drive:|$)',
            text, re.IGNORECASE
        )
        subject = subject_match.group(1).strip() if subject_match else "Message from MWM Creations"

        # Extract body
        body_match = re.search(
            r'body[:\s]+["\']?(.+?)(?:["\']?\s*(?:attach|drive:)|$)',
            text, re.IGNORECASE | re.DOTALL
        )
        body_html = body_match.group(1).strip() if body_match else ""

        if not body_html:
            return True, (
                f"📧 *Gmail Ready*\n"
                f"• *To:* {to_email}\n"
                f"• *Subject:* {subject}\n\n"
                f"I need the email body. Tell me what to say, or ask me to draft something based on context."
            )

        # Extract attachment reference (optional)
        # Supports: "attach drive:<file_id>", "attach <filename>", "attach Proposta_RBL.pdf"
        drive_file_id = None
        filename = None
        found_file_name = None

        attach_match = re.search(
            r'attach(?:ment)?[:\s]+(.+?)(?:\s*$)',
            text, re.IGNORECASE
        )
        if attach_match:
            attach_ref = attach_match.group(1).strip().strip('"\'')

            # Option 1: Explicit Drive file ID or URL
            id_from_url = re.search(r'/d/([a-zA-Z0-9_-]+)', attach_ref)
            if id_from_url:
                drive_file_id = id_from_url.group(1)
            elif attach_ref.startswith("drive:"):
                drive_file_id = attach_ref.replace("drive:", "").strip()
            elif len(attach_ref) > 20 and re.match(r'^[a-zA-Z0-9_-]+$', attach_ref):
                # Looks like a raw file ID (long alphanumeric string)
                drive_file_id = attach_ref
            else:
                # Option 2: Search Drive by filename (the smart path)
                print(f"[SUSAN GMAIL] Searching Drive for: {attach_ref}")
                found = search_drive_file(attach_ref)
                if found:
                    drive_file_id = found["id"]
                    found_file_name = found["name"]
                    print(f"[SUSAN GMAIL] Found file: {found_file_name} (ID: {drive_file_id})")
                else:
                    return True, (
                        f"⚠️ *File not found on Google Drive*\n"
                        f"I searched for *\"{attach_ref}\"* but couldn't find it.\n\n"
                        f"Make sure the file is saved in your Google Drive folder "
                        f"(it syncs automatically from your Mac). "
                        f"Then try again — I'll find it by name."
                    )

        # Extract custom filename override
        fn_match = re.search(r'filename[:\s]+["\']?(.+?\.\w+)', text, re.IGNORECASE)
        if fn_match:
            filename = fn_match.group(1).strip()

        # Send it
        result = send_gmail(to_email, subject, body_html, drive_file_id, filename)

        if result["ok"]:
            attachment_note = ""
            if drive_file_id:
                display_name = filename or found_file_name or "file from Drive"
                attachment_note = f"\n• *Attachment:* {display_name} ✅"
            return True, (
                f"✅ *Email Sent Successfully*\n"
                f"• *To:* {to_email}\n"
                f"• *From:* {SUSAN_SEND_AS}\n"
                f"• *Subject:* {subject}{attachment_note}\n"
                f"• *Message ID:* `{result['message_id']}`"
            )
        else:
            return True, f"⚠️ Email send failed: {result['error']}"

    except Exception as e:
        print(f"[SUSAN GMAIL] Action handler error: {e}")
        traceback.print_exc()
        return True, f"⚠️ Error processing email request: {str(e)[:300]}"
