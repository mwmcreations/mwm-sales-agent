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
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")  # S0.1
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
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")  # S0.1
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


# ══════════════════════════════════════════════════════════════════════
# PATCH #44A · DO-NOT-CONTACT, ENFORCED WHERE THE SENDS ACTUALLY HAPPEN
#
# Patch #38 (Aug 1) added `email_is_suppressed()` and enforced it at
# /api/send-email with a 409. That is the endpoint a HUMAN or an agent calls
# by token. It is not the path the machine uses.
#
# Verified in app.py on Aug 3: five call sites reach send_gmail() directly —
# 4390 (Maya email tool), 8871 (S-6 confirmation fallback), 8991 (cold-lead
# farewell), 13330 (welcome email), and 15819 (the studio pitch sequence dep).
# NONE of them checked suppression. The Marcia Cardim failure class was closed
# on the manual door and left open on every automatic one.
#
# The guard belongs HERE, at the single point every send converges on, so that
# a future caller cannot reintroduce the bypass merely by not knowing it exists.
#
# FAIL CLOSED. If app.py has not installed the predicate, we refuse to send at
# all rather than resume emailing people who asked us to stop. A wiring
# regression must be total and loud, never a quiet resumption.
# ══════════════════════════════════════════════════════════════════════

_SUPPRESSION_HOOK = None


def configure_suppression(fn):
    """Install the do-not-contact predicate: fn(addr) -> (blocked: bool, reason: str).

    app.py calls this once at import, next to where `email_is_suppressed` is
    defined. One predicate, shared — two lists that can disagree WILL disagree.
    """
    global _SUPPRESSION_HOOK
    _SUPPRESSION_HOOK = fn


def suppression_configured():
    """True once app.py has wired the predicate. app.py self-checks this at boot."""
    return _SUPPRESSION_HOOK is not None


def _suppressed(addr):
    """(blocked, reason). Every failure mode returns BLOCKED."""
    if _SUPPRESSION_HOOK is None:
        return True, "suppression hook not configured — failing closed"
    try:
        blocked, reason = _SUPPRESSION_HOOK(addr)
        return bool(blocked), str(reason or "")
    except Exception as exc:
        # A suppression check that raises must not quietly allow the send.
        return True, "suppression check raised: {}".format(str(exc)[:120])


# ══════════════════════════════════════════════════════════════════════
# PATCH #68 — THE OPERATOR EXEMPTION LIVES HERE, WHERE SENDING HAPPENS.
#
# #66 tried to reach Michael by calling send_gmail() directly, skipping
# app.py's `_email_send` wrapper and therefore its lead-suppression check.
# It still failed:
#
#     operator.boot_check failed: could not email the operator at
#     michael@mwmcreations.com: suppressed: internal address
#
# Because suppression is enforced TWICE on purpose — once in the wrapper and
# once here, so a caller that forgets the wrapper is still caught. That design
# is correct and it worked. #66 simply bypassed the layer it knew about and
# walked into the one it did not.
#
# So the exemption cannot live in app.py. It has to be a first-class argument
# to the sender, guarded by its OWN allow-list, right where the decision to
# transmit is made. `operator=True` is visible in the signature, greppable, and
# impossible to reach by accident from a lead-facing path.
#
# Deny-by-default is preserved twice over: the operator predicate must be
# wired (or the send fails closed), AND the address must be on the operator
# list. DNC still outranks both — that check lives inside the predicate app.py
# installs, so a do-not-contact address can never be an operator.
# ══════════════════════════════════════════════════════════════════════

_OPERATOR_HOOK = None


def configure_operators(fn):
    """Install the operator predicate: fn(addr) -> (allowed: bool, reason: str).

    Separate from the suppression hook on purpose. Suppression answers "must I
    NOT send to this lead?"; this answers "is this one of the two or three
    addresses that belong to the people who run the business?". Conflating
    them is what produced a three-day silent outage.
    """
    global _OPERATOR_HOOK
    _OPERATOR_HOOK = fn


def operators_configured():
    """True once app.py has wired the operator predicate."""
    return _OPERATOR_HOOK is not None


def _operator_ok(addr):
    """(allowed, reason). Every failure mode returns NOT ALLOWED."""
    if _OPERATOR_HOOK is None:
        return False, "operator predicate not configured — failing closed"
    try:
        allowed, reason = _OPERATOR_HOOK(addr)
        return bool(allowed), str(reason or "")
    except Exception as exc:
        return False, "operator check raised: {}".format(str(exc)[:120])


_TRANSACTIONAL_HOOK = None


def configure_transactional(fn):
    """Install the client-transactional predicate.

    fn(addr) -> ("allow" | "block" | "default", reason). See
    event_rail.transactional_allowed for why the answer is three-way.
    """
    global _TRANSACTIONAL_HOOK
    _TRANSACTIONAL_HOOK = fn


def transactional_configured():
    return _TRANSACTIONAL_HOOK is not None


def _transactional_decision(addr):
    """("allow"|"block"|"default", reason). Any failure degrades to "default",
    which means the ordinary suppression guard decides — the safe direction."""
    if _TRANSACTIONAL_HOOK is None:
        return "default", "transactional predicate not configured"
    try:
        decision, reason = _TRANSACTIONAL_HOOK(addr)
        decision = str(decision or "default")
        return (decision if decision in ("allow", "block", "default") else "default",
                str(reason or ""))
    except Exception as exc:
        return "default", "transactional check raised: {}".format(str(exc)[:120])


def _recipients(to, cc):
    """Every address this message would reach — CC included.

    A DNC address in CC is still a DNC address receiving mail.
    """
    out = [str(to or "").strip()]
    for part in re.split(r"[,;]+", str(cc or "")):
        part = part.strip()
        if part:
            out.append(part)
    return [a for a in out if a]


# ══════════════════════════════════════════════════════════════════════
# PATCH #114 · STANDING CC — WHEN A SECOND PERSON MUST SEE A CLIENT'S MAIL
#
# Michael, 2 Sep 2026: "add Nicole.formore@gmail.com in all e-mails that
# should be sent to our studio client Luzia. keep the main e-mail and add
# this one. for all e-mail communication."
#
# "All" is the whole instruction. A rule applied at one call site holds only
# until somebody writes the next call site — and that has already happened in
# this exact file: Patch #38 enforced do-not-contact at the endpoint a human
# calls, and five automated senders walked straight past it. So the standing
# CC lives at the chokepoint every send converges on, where a sending path
# written next month inherits it without knowing it exists.
#
# It is applied BEFORE the recipient guard, deliberately. A standing CC is a
# real person receiving real mail, and it gets the same do-not-contact and
# never-contact scrutiny as the TO. A CC that could skip the guard would be a
# hole shaped exactly like the one #44A closed.
#
# Operator mail is excluded: #68 refuses CC on operator sends outright, and
# operator mail is not client communication.
# ══════════════════════════════════════════════════════════════════════

# Built-in map. Keys and values are plain addresses; keys match case-insensitively.
_ALWAYS_CC = {
    # Luzia Costa (Studio Package) — Nicole is copied on everything. Michael, 2 Sep 2026.
    "luziahcosta@hotmail.com": ["Nicole.formore@gmail.com"],
}


def _always_cc_map():
    """{recipient -> [addresses always copied]}, keys lowercased.

    SUSAN_ALWAYS_CC — JSON, {"client@x.com": ["copy@y.com"]} — is merged OVER
    the built-in map, so adding or removing a standing copy is an env edit
    rather than a deploy. A malformed value is ignored and logged: a typo in
    an env var must not silently drop the copies that are already correct.
    """
    out = {}
    for k, v in _ALWAYS_CC.items():
        out[str(k).strip().lower()] = [str(a).strip() for a in v if str(a).strip()]
    raw = (os.getenv("SUSAN_ALWAYS_CC", "") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("SUSAN_ALWAYS_CC must be a JSON object")
            for k, v in parsed.items():
                key = str(k).strip().lower()
                vals = v if isinstance(v, (list, tuple)) else re.split(r"[,;]+", str(v or ""))
                out[key] = [str(a).strip() for a in vals if str(a).strip()]
        except Exception as exc:
            print("[GMAIL] SUSAN_ALWAYS_CC ignored — {}".format(str(exc)[:120]))
    return {k: v for k, v in out.items() if k and v}


def _apply_always_cc(to, cc):
    """Return `cc` with every standing copy for these recipients added once.

    Never duplicates an address already in TO or CC, in any casing, and never
    removes anything the caller asked for.
    """
    mapping = _always_cc_map()
    if not mapping:
        return cc
    current = _recipients(to, cc)
    seen = {a.strip().lower() for a in current}
    additions = []
    for addr in current:
        for extra in mapping.get(addr.strip().lower(), []):
            if extra.lower() not in seen:
                seen.add(extra.lower())
                additions.append(extra)
    if not additions:
        return cc
    existing = [p.strip() for p in re.split(r"[,;]+", str(cc or "")) if p.strip()]
    out = ", ".join(existing + additions)
    print("[GMAIL] standing CC applied for {}: +{}".format(to, ", ".join(additions)))
    return out


# ── Core: Send Email with Optional Attachment ───────────────────────

def send_gmail(to, subject, body_html, drive_file_id=None, filename=None, cc=None,
               operator=False, transactional=False):
    """
    Send an email via Gmail as info@mwmcreations.com.

    Args:
        to: Recipient email address
        subject: Email subject line
        body_html: HTML body content
        drive_file_id: (optional) Google Drive file ID to attach
        filename: (optional) Display filename for the attachment
        cc: (optional) comma-separated CC addresses

    Returns:
        dict with 'ok' bool and 'message_id' or 'error' string.
        Patch #44A: a suppressed recipient returns ok=False with suppressed=True
        and NOTHING is sent. Callers must test result["ok"] — the dict is truthy
        either way, which is exactly the bug #44A2 fixes at the call sites.
    """
    # PATCH #68 — OPERATOR MAIL. A different question, so a different gate.
    # Not a bypass: the address must be ON the operator list, CC is refused
    # outright so the blast radius is exactly one known address, and an
    # unconfigured predicate fails closed like everything else here.
    if operator:
        if cc:
            print("[GMAIL] BLOCKED — operator sends may not carry CC")
            return {"ok": False, "suppressed": True,
                    "error": "operator send refused: CC not permitted"}
        _allowed, _why_op = _operator_ok(to)
        if not _allowed:
            print("[GMAIL] BLOCKED — not an operator address {}: {}".format(to, _why_op))
            return {"ok": False, "suppressed": True,
                    "blocked_address": str(to or ""),
                    "error": "operator refused: {}".format(_why_op)}
        print("[GMAIL] operator send permitted to {}".format(to))
    else:
        # PATCH #114 — standing CC first, so a copied address faces the same
        # guard as the recipient it is copied on. Never before an operator
        # send: #68 refuses CC there, and operator mail is not client mail.
        cc = _apply_always_cc(to, cc)

        # PATCH #44A — before the service, before the MIME, before anything.
        # PATCH #69 — with one narrow exception: CLIENT TRANSACTIONAL mail.
        # A client who is on the lead-DNC list (because they must not receive
        # marketing) still has to receive the confirmation for the booking
        # they made. The exception is per-address and allow-listed; the
        # never-contact tier still refuses, and anything not explicitly
        # excepted falls through to the ordinary guard unchanged.
        for _addr in _recipients(to, cc):
            if transactional:
                _dec, _twhy = _transactional_decision(_addr)
                if _dec == "block":
                    print("[GMAIL] BLOCKED — transactional refused for {}: {}".format(_addr, _twhy))
                    return {"ok": False, "suppressed": True,
                            "blocked_address": _addr,
                            "error": "transactional refused: {}".format(_twhy)}
                if _dec == "allow":
                    print("[GMAIL] transactional exception for {}: {}".format(_addr, _twhy))
                    continue
            _blocked, _why = _suppressed(_addr)
            if _blocked:
                print("[GMAIL] BLOCKED — refusing send to {}: {}".format(_addr, _why))
                return {"ok": False, "suppressed": True,
                        "blocked_address": _addr,
                        "error": "suppressed: {}".format(_why)}
    try:
        gmail = _get_gmail_service()

        if drive_file_id:
            # ── multipart/mixed with attachment ──
            message = MIMEMultipart("mixed")
            message["to"] = to
            if cc:
                message["cc"] = cc
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
            if cc:
                message["cc"] = cc
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
