"""
LARA Action Handlers — Client & Production Manager Agent.

Handles:
- MWM Clients (Google Sheets) — read/update client production status
- Calendar access (reuses Google Calendar DWD)
- Gmail integration — read/send emails for client communication

Uses GOOGLE_CREDENTIALS_JSON + GOOGLE_DELEGATE_EMAIL (DWD) from Railway env vars.

Session 30.11: The old "Production Tracker" (stored under GOOGLE_SHEETS_PRODUCTION_ID)
is retired. All client data now lives in the MWM Clients tab of the MWM Leads Pipeline
spreadsheet, identified by GOOGLE_SHEETS_LEADS_ID. Same sheet, one source of truth,
shared with Cowork LARA and Michael.
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
# Session 30.11: Unified on SHEETS_LEADS_ID — the old GOOGLE_SHEETS_PRODUCTION_ID
# env var is deprecated (never pointed at a real sheet in production).
LEADS_SHEET_ID = os.getenv("GOOGLE_SHEETS_LEADS_ID", "")
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

# Session 30.11 — MWM Clients canonical 10-column schema
MWM_CLIENTS_TAB = "MWM Clients"
MWM_CLIENTS_TAB_LEGACY = "Client Roster"  # Session 30.10 name, read-only fallback

MWM_CLIENTS_HEADERS = [
    "Name", "Company", "Email", "Phone", "Plan", "Status",
    "Delivered", "Upcoming", "Last Contact", "Notes",
]

# Column letter for each canonical field in the 10-col schema (for update writes).
# Used by update_client_field when the tab is in the new schema.
_MWM_CLIENTS_COL_LETTER = {
    "name": "A",
    "company": "B",
    "email": "C",
    "phone": "D",
    "plan": "E",
    "status": "F",
    "delivered": "G",
    "upcoming": "H",
    "last_contact": "I",
    "notes": "J",
}

# Header → canonical field alias map. Same logic as load_client_roster() in app.py
# so the two loaders agree on how to read rows regardless of which schema the
# sheet is currently in.
_MWM_CLIENTS_HEADER_ALIASES = {
    "name": "name",
    "client": "name",
    "company": "company",
    "business": "company",
    "email": "email",
    "phone": "phone",
    "whatsapp": "phone",
    "plan": "plan",
    "service": "plan",
    "status": "status",
    "content status": "status",
    "delivered": "delivered",
    "produced": "delivered",
    "upcoming": "upcoming",
    "next shoot": "upcoming",
    "shoot date": "upcoming",
    "last contact": "last_contact",
    "last client contact": "last_contact",
    "notes": "notes",
}

# ── LARA Outbound WhatsApp Templates (Session 30.15) ─────────────────────────
# Approved by Meta (UTILITY, pt_BR). Each template has a different number of
# parameters — the mapping below defines them.
#
# Template name              → Variables
# lara_crew_availability     → {{1}}=name, {{2}}=shoot_date
# lara_client_confirmation   → {{1}}=name, {{2}}=shoot_date, {{3}}=location
# lara_shoot_reminder        → {{1}}=name, {{2}}=shoot_date, {{3}}=time
# lara_video_approval        → {{1}}=name
# lara_general_outreach      → {{1}}=name

LARA_TEMPLATES = {
    "lara_crew_availability",
    "lara_client_confirmation",
    "lara_shoot_reminder",
    "lara_video_approval",
    "lara_general_outreach",
}


def send_lara_template(phone, template_name, parameters):
    """Send a LARA outbound WhatsApp template message via Meta Cloud API.

    Args:
        phone: Recipient phone number (any format — digits extracted).
        template_name: One of the LARA_TEMPLATES names.
        parameters: List of strings — positional template variables.
            e.g. ["João", "15 de Abril"] for lara_crew_availability
            e.g. ["Maria", "20 de Abril", "Orlando"] for lara_client_confirmation
            e.g. ["Ana"] for lara_video_approval

    Returns:
        dict with {"ok": True/False, "message_id": "...", "error": "..."}
    """
    import requests as _req

    meta_token = os.getenv("META_ACCESS_TOKEN", "")
    lara_pn_id = os.getenv("LARA_PHONE_NUMBER_ID", "")

    if not meta_token or not lara_pn_id:
        msg = "Cannot send LARA template: missing META_ACCESS_TOKEN or LARA_PHONE_NUMBER_ID"
        print(f"[LARA] {msg}")
        return {"ok": False, "error": msg}

    if template_name not in LARA_TEMPLATES:
        msg = f"Unknown LARA template: {template_name}"
        print(f"[LARA] {msg}")
        return {"ok": False, "error": msg}

    clean_phone = re.sub(r"\D", "", phone.replace("whatsapp:", ""))

    url = f"https://graph.facebook.com/v20.0/{lara_pn_id}/messages"
    headers = {
        "Authorization": f"Bearer {meta_token}",
        "Content-Type": "application/json",
    }

    # Build template components with positional parameters
    body_params = [{"type": "text", "text": str(p)} for p in parameters]
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},
            "components": [
                {
                    "type": "body",
                    "parameters": body_params,
                }
            ] if body_params else [],
        },
    }

    try:
        resp = _req.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        msg_id = resp.json().get("messages", [{}])[0].get("id", "")
        print(f"[LARA] Template '{template_name}' sent to {clean_phone}: {msg_id}")
        return {"ok": True, "message_id": msg_id}
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and e.response is not None:
            err += f" | Response: {e.response.text[:300]}"
        print(f"[LARA] Template send FAILED to {clean_phone}: {err}")
        return {"ok": False, "error": err}


def _normalize_phone_digits(value):
    """Strip all non-digit characters from a phone string."""
    if not value:
        return ""
    return re.sub(r"\D", "", str(value))


def lookup_sender_identity(sender_phone, clients=None):
    """Resolve a WhatsApp sender phone to a known identity.

    Args:
        sender_phone: The WhatsApp sender phone string (may include "whatsapp:" prefix).
        clients: Optional list of client dicts from the Sheet-backed MWM Clients
                 loader (Session 30.11). Each dict has the canonical keys:
                 name, company, email, phone, plan, status, delivered, upcoming,
                 last_contact, notes.
                 If None or empty, falls back to MWM_CLIENTS (empty by default).

    Returns a dict describing who is on the other end of the conversation
    so the LARA system prompt can be grounded properly:

        {
            "role": "michael" | "client" | "unknown",
            "name": str,
            "phone": str,              # original phone
            "is_michael": bool,
            "client_info": dict | None # full client row when role == "client"
        }
    """
    sender_digits = _normalize_phone_digits(sender_phone)
    michael_env = os.getenv("MICHAEL_PHONE", "")
    michael_digits = _normalize_phone_digits(michael_env)

    if sender_digits and michael_digits and sender_digits == michael_digits:
        return {
            "role": "michael",
            "name": "Michael Moraes",
            "phone": sender_phone,
            "is_michael": True,
            "client_info": None,
        }

    # Use Sheet-backed roster if available, otherwise fall back to hardcoded
    roster = clients if clients else MWM_CLIENTS

    for client in roster:
        client_digits = _normalize_phone_digits(client.get("phone", ""))
        if client_digits and client_digits == sender_digits:
            return {
                "role": "client",
                "name": client.get("name") or client.get("company") or "Unknown client",
                "phone": sender_phone,
                "is_michael": False,
                "client_info": client,
            }

    return {
        "role": "unknown",
        "name": "Unknown sender",
        "phone": sender_phone,
        "is_michael": False,
        "client_info": None,
    }


def format_sender_identity_block(identity):
    """Format an identity dict into a system-prompt block for LARA."""
    if not identity:
        return ""
    if identity["role"] == "michael":
        return (
            "SENDER IDENTITY \u2014 CRITICAL:\n"
            "You are talking to Michael Moraes, the owner of MWM Creations & Studios. "
            "This is confirmed by phone number match against MICHAEL_PHONE. "
            "Do NOT ask who is messaging you, do NOT ask which calendar to look at, "
            "do NOT treat him like a client. When he says \"my calendar\" or \"my day\", "
            "that means his MWM Creations calendar (michael@mwmcreations.com). "
            "Be direct, operational, and proactive \u2014 Michael is your boss."
        )
    if identity["role"] == "client":
        client = identity["client_info"] or {}
        name = identity.get("name") or client.get("name") or "this client"
        lines = [
            "SENDER IDENTITY:\n",
            f"You are talking to a known MWM client: *{name}*.\n",
            "Everything below comes from the MWM Clients sheet and is authoritative. "
            "Use it to answer their questions naturally. Do NOT fabricate any detail "
            "not listed here.\n",
        ]
        if client.get("company"):
            lines.append(f"- Company: {client['company']}\n")
        if client.get("email"):
            lines.append(f"- Email: {client['email']}\n")
        if client.get("phone"):
            lines.append(f"- Phone: {client['phone']}\n")
        if client.get("plan"):
            lines.append(f"- Plan: {client['plan']}\n")
        if client.get("status"):
            lines.append(f"- Status: {client['status']}\n")
        if client.get("delivered"):
            lines.append(f"- Delivered so far: {client['delivered']}\n")
        if client.get("upcoming"):
            lines.append(f"- Upcoming: {client['upcoming']}\n")
        if client.get("last_contact"):
            lines.append(f"- Last contact: {client['last_contact']}\n")
        if client.get("notes"):
            lines.append(f"- Notes: {client['notes']}\n")
        lines.append(
            "Be warm, professional, and client-facing. Do NOT share internal production "
            "details unrelated to their project. Switch to Portuguese if they write in Portuguese. "
            "If they ask something you don't have in the fields above, say you'll check with "
            "Michael and follow up \u2014 do NOT invent an answer."
        )
        return "".join(lines)
    return (
        "SENDER IDENTITY:\n"
        f"The sender phone ({identity.get('phone', 'unknown')}) does not match "
        "Michael or any known MWM client in the MWM Clients sheet. Treat them as a "
        "new inquiry \u2014 be warm, professional, and ask who they are and how you "
        "can help."
    )


# MWM CREW ROSTER (added Session 30 — 2026-04-08)
# Contact info provided by Michael. Roles marked "Crew" are placeholders —
# Michael can refine them as needed. Emails not yet collected.
MWM_CREW = [
    {
        "name": "Bruno Neri",
        "role": "Crew",
        "phone": "+15616392905",
        "email": "",
        "notes": "MWM team member",
    },
    {
        "name": "Guga Carvalho",
        "role": "Camera",
        "phone": "+13107397521",
        "email": "",
        "notes": "Camera operator",
    },
    {
        "name": "Asafh Kalebe",
        "role": "Camera",
        "phone": "+18632662266",
        "email": "",
        "notes": "Camera operator",
    },
    {
        "name": "Erika Miyamoto",
        "role": "Crew",
        "phone": "+5511970646093",
        "email": "",
        "notes": "Based in Brazil (+55)",
    },
    {
        "name": "Luis Pereira",
        "role": "Crew",
        "phone": "+14077197716",
        "email": "",
        "notes": "MWM team member",
    },
]


_CREW_NAME_ALIASES = {
    "asaph": "asafh",
    "kalebe": "asafh",
    "neri": "bruno",
    "carvalho": "guga",
    "miyamoto": "erika",
    "pereira": "luis",
}


def find_crew_member(query):
    """Find a crew member by name (partial, case-insensitive), alias, or phone.

    Returns the matching crew dict or None.
    """
    if not query:
        return None
    q_lower = query.lower().strip()
    # Resolve alternate spellings / last names first
    if q_lower in _CREW_NAME_ALIASES:
        q_lower = _CREW_NAME_ALIASES[q_lower]
    q_digits = _normalize_phone_digits(query)

    # Exact-ish phone match first
    if q_digits and len(q_digits) >= 7:
        for crew in MWM_CREW:
            if _normalize_phone_digits(crew["phone"]) == q_digits:
                return crew

    # Name match — first name, last name, or full name substring
    for crew in MWM_CREW:
        name_lower = crew["name"].lower()
        name_parts = name_lower.split()
        if q_lower == name_lower:
            return crew
        if q_lower in name_parts:
            return crew
        if q_lower in name_lower:
            return crew

    return None


# Session 30.11 — the hardcoded MWM_CLIENTS list (originally 11 placeholder
# entries from earlier sessions) is retired. The MWM Clients Google Sheet is
# now the single source of truth. This empty list remains only as a defensive
# fallback: if load_client_roster() fails entirely, lookup_sender_identity()
# will degrade to "unknown" for every sender instead of incorrectly matching
# against fake placeholder numbers.
MWM_CLIENTS = []


# ── Intent Detection ────────────────────────────────────────────────
LARA_ACTION_INTENTS = {
    # ── Broad overviews first ──
    "production_overview": [
        r"(?:production|project|client)\s*(?:status|summary|overview|report|board|tracker)",
        r"how(?:'s| is| are) (?:the |our )?(?:production|projects?|clients?|pipeline)",
        r"(?:show|get|pull|give)\s+(?:me\s+)?(?:the\s+)?(?:production|tracker|project)\s*(?:status|board|overview)?",
        r"what.?s (?:the )?status (?:of |on )?(?:all |our )?(?:productions?|projects?|clients?)",
        r"(?:como\s+est[aá]|status)\s+(?:da|das|dos)?\s*(?:produ[cç][aã]o|projetos?|clientes?)",
    ],
    # ── Specific intents BEFORE client_status (which is a greedy catch-all) ──
    "update_client": [
        r"(?:update|change|set|mark)\s+(.+?)\s+(?:script\s*(?:status)?|shoot\s*(?:date|confirmed)?|content\s*(?:status)?|team\s*(?:briefed)?|confirmed|briefed|status|notes|last\s+contact|contact)\s+(?:to|as|→)\s+(.+)",
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
    "read_emails": [
        r"(?:check|show|read|list|any)\s+(?:my\s+|the\s+)?(?:new\s+)?(?:recent\s+)?(?:emails?|messages?|inbox)\s*(?:from|about)?\s*(.*)",
        r"(?:what|any)\s+(?:new\s+)?(?:emails?|messages?)\s+(?:from|about)\s+(.+)",
        r"(?:inbox|email)\s+(?:status|check|update)",
        r"(?:my|the)\s+(?:emails?|inbox|messages?)",
    ],
    "check_calendar": [
        r"(?:what.?s|check|show|list)\s+(?:on\s+)?(?:the\s+)?(?:calendar|schedule|agenda)\s*(?:for|on|this|next)?\s*(.*)",
        r"(?:am i|is michael|are we)\s+(?:free|available|busy)\s+(.*)",
        r"(?:any|what)\s+(?:meetings?|appointments?|events?)\s+(?:today|tomorrow|this week|next week)",
        # Natural phrasings for "what's my day like"
        r"how(?:'?s|\s+is|\s+are|\s+was|\s+were)?\s+(?:my|the|our|michael'?s)\s+(?:day|morning|afternoon|evening|week|schedule)",
        r"what(?:'?s|\s+is|\s+are)?\s+(?:my|the|our|michael'?s)\s+(?:day|morning|afternoon|evening|week|schedule)(?:\s+look(?:ing)?\s+like)?",
        r"what\s+do\s+(?:i|we|michael)\s+have\s+(?:going on|today|tomorrow|this week|next week|on)",
        r"what.?s?\s+(?:happening|going on|on)\s+(?:today|tomorrow|this week|next week)",
        r"(?:tell|give)\s+me\s+(?:my|the|michael.?s)\s+(?:day|schedule|calendar|agenda)",
        r"(?:my|the|michael.?s)\s+(?:day|schedule|agenda)\s+(?:today|tomorrow|this week|next week)",
        r"(?:what\s+is|what.?s)\s+(?:on\s+)?(?:for\s+)?(?:today|tomorrow|this week|next week)",
        # Portuguese natural phrasings
        r"como\s+(?:est[aá]|vai|fica)\s+(?:meu|o)\s+(?:dia|manh[aã]|tarde|noite|semana)",
        r"(?:o\s+que\s+eu\s+tenho|o\s+que\s+tem)\s+(?:hoje|amanh[aã]|essa\s+semana)",
    ],
    # ── Crew / team queries (BEFORE client_status because it's greedy) ──
    "check_crew": [
        # General crew list / roster queries
        r"(?:show|list|who.?s?|what(?:'s|s)?)\s+(?:on\s+)?(?:the\s+)?(?:crew|team|camera\s+(?:crew|operators?|persons?))",
        r"(?:crew|team)\s+(?:list|roster|members?|info|contacts?)",
        r"(?:the\s+)?(?:mwm\s+)?crew(?:\s+members?)?\s*\??\s*$",
        # Availability of any crew member
        r"(?:is|can|will)\s+(?:any(?:one)?\s+)?(?:of\s+(?:the\s+)?)?crew\s+(?:member\s+)?(?:available|free|busy|working|on|able)",
        r"(?:any|a)\s+crew\s+(?:member\s+)?(?:available|free|for)",
        r"(?:is|will|can)\s+(?:any(?:one)?\s+from\s+)?(?:the\s+)?(?:crew|team)\s+(?:be\s+)?(?:available|free|here|there|on|at)",
        # Availability of a specific known crew member
        r"(?:is|can|will)\s+(?:bruno|guga|asafh|asaph|erika|luis)\s+(?:available|free|busy|working|able|here|there|on|be)",
        r"(?:bruno|guga|asafh|asaph|erika|luis)(?:'s|\s+is)?\s+(?:phone|email|contact|number|availability|schedule)",
        # Contact lookup
        r"(?:contact|phone|email|info|number)\s+(?:info\s+)?(?:for\s+)?(?:bruno|guga|asafh|asaph|erika|luis)",
        r"(?:how\s+do\s+i|how\s+can\s+i)\s+(?:contact|reach|call|text|email)\s+(?:bruno|guga|asafh|asaph|erika|luis)",
        # Portuguese
        r"(?:quem|qual)\s+(?:est[aá])?\s*(?:dispon[ií]vel|livre|na\s+equipe)",
        r"(?:equipe|crew)\s+(?:dispon[ií]vel|hoje|amanh[aã]|lista)",
        r"algu[eé]m\s+(?:da\s+)?(?:equipe|crew)",
    ],
    # ── Google Drive actions (specific keywords: files/footage/folder/share) ──
    "drive_list_footage": [
        # With a client/target: "list footage for Victory MA"
        r"(?:list|show|get|pull|what(?:'s|s)?)\s+(?:me\s+)?(?:the\s+)?(?:footage|raw\s*(?:files|material)?|clips?)\s+(?:for|in|of|from)\s+.+",
        r"(?:footage|raw)\s+(?:folder|files)\s+(?:for|of)\s+.+",
        # Without a client — list the FOOTAGE shared drive root
        r"(?:list|show|get|pull)\s+(?:me\s+)?(?:the\s+)?footage(?:\s+(?:drive|shared\s*drive|folder|files|root))?\s*\??\s*$",
        r"what(?:'s|s)?\s+in\s+(?:the\s+)?footage(?:\s+(?:drive|shared\s*drive|folder))?\s*\??\s*$",
        r"^footage(?:\s+(?:drive|shared\s*drive|folder|files|root))?\s*\??\s*$",
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
        r"search\s+drive\s+(?:for\s+)?.+",
        r"drive\s+search\s+.+",
    ],
    # ── Outbound WhatsApp template messages (Session 30.15) ──
    "send_template": [
        # "send a reminder to João about the shoot"
        r"(?:send|enviar?)\s+(?:a\s+)?(?:reminder|lembrete|shoot\s*reminder)\s+(?:to|para|for)\s+(.+)",
        # "remind João / Maria about the shoot tomorrow"
        r"(?:remind|lembrar?)\s+(.+?)(?:\s+(?:about|sobre|regarding|of|que|da|do))\s+(.+)",
        # "reach out to / contact / message João"
        r"(?:reach\s*out\s+to|contact|message|text|whatsapp|falar?\s+com|mandar?\s+(?:msg|mensagem)\s+(?:para|pro|pra))\s+(.+)",
        # "send crew availability check to Bruno"
        r"(?:send|enviar?)\s+(?:a?\s+)?(?:crew\s+)?(?:availability|disponibilidade)\s+(?:check\s+)?(?:to|para|for)\s+(.+)",
        # "ask João if he's available for the shoot on April 20"
        r"(?:ask|perguntar?)\s+(.+?)\s+(?:if|se)\s+(?:he|she|they|ele|ela).?s?\s+(?:available|free|dispon[ií]vel)",
        # "send video approval to Maria"
        r"(?:send|enviar?)\s+(?:a?\s+)?(?:video|v[ií]deo)\s+(?:approval|aprova[çc][aã]o)\s+(?:to|para|for)\s+(.+)",
        # "confirm shoot with Maria" / "confirmar gravação com Maria"
        r"(?:confirm|confirmar?)\s+(?:the\s+)?(?:shoot|grava[çc][aã]o|session|sess[aã]o)\s+(?:with|com)\s+(.+)",
        # "send template lara_crew_availability to João"
        r"(?:send|enviar?)\s+(?:the\s+)?template\s+(\S+)\s+(?:to|para|for)\s+(.+)",
        # Portuguese: "entrar em contato com João"
        r"entrar?\s+em\s+contato\s+com\s+(.+)",
    ],
    # ── client_status LAST — it's a greedy catch-all with "check/status" ──
    "client_status": [
        r"(?:status|how.?s)\s+(?:on\s+)?(.+?)(?:\s+(?:project|production|status|going))?$",
        r"(?:what.?s|where.?s)\s+(.+?)\s+(?:at|status|standing|project)",
        r"(?:look\s*up|find)\s+(?:client\s+)?(.+?)(?:\s+(?:in|on|from)\s+(?:the\s+)?(?:tracker|sheet|board))?$",
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


# ── MWM Clients Sheet Helpers (Session 30.11) ───────────────────────
def _resolve_mwm_clients_tab(svc):
    """Return whichever of 'MWM Clients' or 'Client Roster' exists in the sheet.
    Preference: new name → legacy → None."""
    if not LEADS_SHEET_ID:
        return None
    meta = svc.spreadsheets().get(spreadsheetId=LEADS_SHEET_ID).execute()
    existing = {s["properties"]["title"] for s in meta["sheets"]}
    if MWM_CLIENTS_TAB in existing:
        return MWM_CLIENTS_TAB
    if MWM_CLIENTS_TAB_LEGACY in existing:
        return MWM_CLIENTS_TAB_LEGACY
    return None


def _get_all_clients():
    """Read all clients from the MWM Clients tab (Session 30.11).

    Returns list of (row_index, client_dict) tuples where client_dict uses the
    canonical lowercase keys: name, company, email, phone, plan, status,
    delivered, upcoming, last_contact, notes.

    Works with both the canonical 10-col schema and the legacy 6-col schema
    via header aliasing.
    """
    if not LEADS_SHEET_ID:
        return []

    svc = _get_sheets_service()
    tab = _resolve_mwm_clients_tab(svc)
    if tab is None:
        return []

    result = svc.spreadsheets().values().get(
        spreadsheetId=LEADS_SHEET_ID,
        range=f"'{tab}'!A1:J",
    ).execute()
    rows = result.get("values", [])
    if len(rows) < 2:
        return []

    # Map row 1 headers to canonical field keys via aliases.
    raw_headers = [h.strip().lower() for h in rows[0]]
    col_to_field = {}  # column index -> canonical key
    for i, h in enumerate(raw_headers):
        canonical = _MWM_CLIENTS_HEADER_ALIASES.get(h)
        if canonical:
            col_to_field[i] = canonical

    clients = []
    for i, row in enumerate(rows[1:], start=2):
        if not any((str(c).strip() for c in row)):
            continue
        client_dict = {k: "" for k in _MWM_CLIENTS_COL_LETTER.keys()}
        for col_idx, canonical in col_to_field.items():
            if col_idx < len(row):
                client_dict[canonical] = str(row[col_idx]).strip()
        if not client_dict["name"] and not client_dict["phone"]:
            continue
        clients.append((i, client_dict))
    return clients


def _find_client(search_term):
    """Find a client by name OR company (fuzzy match).
    Returns (row_index, client_dict) or (None, None).
    """
    clients = _get_all_clients()
    search_lower = search_term.lower().strip()

    # Exact substring match on name or company
    for row_idx, client in clients:
        name = (client.get("name") or "").lower()
        company = (client.get("company") or "").lower()
        if search_lower and (search_lower in name or search_lower in company):
            return row_idx, client
        if name and name in search_lower:
            return row_idx, client
        if company and company in search_lower:
            return row_idx, client

    # Partial word match
    search_words = [w for w in search_lower.split() if w]
    if search_words:
        for row_idx, client in clients:
            name = (client.get("name") or "").lower()
            company = (client.get("company") or "").lower()
            target = f"{name} {company}"
            if all(w in target for w in search_words):
                return row_idx, client

    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def get_production_overview(text):
    """Return a summary of all MWM clients grouped by status."""
    try:
        clients = _get_all_clients()
        if not clients:
            return "📋 *MWM Clients sheet is empty* — no clients found."

        lines = [f"📋 *MWM Clients Overview* — {len(clients)} clients\n"]

        # Group by status column
        status_groups = {}
        for row_idx, client in clients:
            status = (client.get("status") or "").strip() or "unspecified"
            status_groups.setdefault(status, []).append(client)

        # Rough ordering — most active first, then everything else alphabetically
        preferred_order = ["active", "onboarding", "new client", "paused", "at-risk", "unspecified"]
        def _sort_key(item):
            s = item[0].lower()
            for i, p in enumerate(preferred_order):
                if p in s:
                    return (i, s)
            return (len(preferred_order), s)

        status_emoji_map = {
            "active": "🟢",
            "onboarding": "🆕",
            "new": "🆕",
            "paused": "⏸️",
            "at-risk": "⚠️",
            "delivered": "🎉",
        }
        def _emoji_for(status):
            s = status.lower()
            for key, em in status_emoji_map.items():
                if key in s:
                    return em
            return "•"

        for status, group in sorted(status_groups.items(), key=_sort_key):
            emoji = _emoji_for(status)
            names = [(c.get("name") or c.get("company") or "?") for c in group]
            lines.append(f"{emoji} *{status}:* {len(group)} — {', '.join(names)}")

        # Clients with anything in Upcoming — show the top few
        upcoming = [
            (client.get("name") or client.get("company") or "?", client.get("upcoming") or "")
            for _, client in clients
            if (client.get("upcoming") or "").strip()
        ]
        if upcoming:
            lines.append(f"\n📅 *Upcoming:*")
            for name, up_text in upcoming[:5]:
                lines.append(f"  • {name} — {up_text[:120]}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] MWM Clients overview error: {e}")
        return f"⚠️ Error reading MWM Clients sheet: {str(e)[:200]}"


def get_client_status(text):
    """Look up a specific client's status in the MWM Clients sheet."""
    try:
        # Extract client name
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        search = re.sub(
            r"^(?:status|check|update|how.?s|what.?s|where.?s|look\s*up|find)\s+(?:on\s+)?(?:client\s+)?",
            "", text_clean, flags=re.IGNORECASE
        ).strip()
        search = re.sub(r"\s+(?:project|production|status|going|standing|at|in the sheet|in the tracker).*$", "", search, flags=re.IGNORECASE).strip().strip('"\'')

        if not search or len(search) < 2:
            return "🔍 Which client? Give me a name or company like *Juliane Almeida* or *Vida Fit*."

        row_idx, client = _find_client(search)
        if not client:
            return f'🔍 No client found matching *"{search}"*.'

        name = client.get("name") or "(unknown)"
        company = client.get("company") or ""
        header = f"📋 *Client Status: {name}*"
        if company and company.lower() != name.lower():
            header += f" _({company})_"
        lines = [header, ""]
        if client.get("email"):
            lines.append(f"📧 Email: {client['email']}")
        if client.get("phone"):
            lines.append(f"📱 Phone: {client['phone']}")
        if client.get("plan"):
            lines.append(f"🎯 Plan: {client['plan']}")
        if client.get("status"):
            lines.append(f"🔖 Status: {client['status']}")
        if client.get("delivered"):
            lines.append(f"✅ Delivered: {client['delivered'][:300]}")
        if client.get("upcoming"):
            lines.append(f"📅 Upcoming: {client['upcoming'][:300]}")
        if client.get("last_contact"):
            lines.append(f"📞 Last Contact: {client['last_contact']}")
        if client.get("notes"):
            lines.append(f"📝 Notes: {client['notes'][:300]}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Client status error: {e}")
        return f"⚠️ Error looking up client: {str(e)[:200]}"


def update_client_field(text):
    """Update a client's field in the MWM Clients sheet (plan, status, delivered, upcoming, last_contact, notes)."""
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()

        # Parse: "update Victory plan to Gold"
        # or: "update Juliane last contact to 2026-04-09"
        # or: "mark Vida Fit status as active"
        # Keys map to canonical field names (lowercase internal keys).
        field_map = {
            "name": "name",
            "company": "company",
            "business": "company",
            "email": "email",
            "phone": "phone",
            "plan": "plan",
            "service": "plan",  # legacy alias
            "status": "status",
            "delivered": "delivered",
            "produced": "delivered",
            "upcoming": "upcoming",
            "next shoot": "upcoming",
            "shoot date": "upcoming",
            "shoot": "upcoming",
            "last contact": "last_contact",
            "contact": "last_contact",
            "notes": "notes",
        }

        # Try pattern: update [client] [field] to [value]
        match = re.search(
            r"(?:update|change|set|mark)\s+(.+?)\s+(name|company|business|email|phone|plan|service|status|delivered|produced|upcoming|next\s+shoot|shoot\s+date|shoot|last\s+contact|contact|notes)\s+(?:to|as|=|→)\s+(.+)",
            text_clean, re.IGNORECASE
        )
        if not match:
            return "🤔 I need a client name, field, and value. Try: *update Victory plan to Gold* or *update Juliane status to active*"

        client_name = match.group(1).strip().strip('"\'')
        field_key = match.group(2).strip().lower()
        new_value = match.group(3).strip().strip('"\'')

        canonical_field = field_map.get(field_key)
        if not canonical_field:
            return f"🤔 I don't recognize the field *{field_key}*. Try: plan, status, delivered, upcoming, last contact, notes"

        row_idx, client = _find_client(client_name)
        if not client:
            return f'🔍 No client found matching *"{client_name}"*.'

        # Determine which tab and which column letter to write.
        svc = _get_sheets_service()
        tab = _resolve_mwm_clients_tab(svc)
        if tab is None:
            return "⚠️ MWM Clients sheet/tab not found."

        # For the canonical 10-col schema we have a fixed column letter map.
        # For the legacy 6-col schema we need to resolve the column by reading headers.
        result = svc.spreadsheets().values().get(
            spreadsheetId=LEADS_SHEET_ID,
            range=f"'{tab}'!1:1",
        ).execute()
        raw_headers = [h.strip().lower() for h in result.get("values", [[]])[0]]

        # Find the column letter for the requested canonical field
        col_idx = None
        for i, h in enumerate(raw_headers):
            if _MWM_CLIENTS_HEADER_ALIASES.get(h) == canonical_field:
                col_idx = i
                break
        if col_idx is None:
            return f"⚠️ Column for *{canonical_field}* not found in tab '{tab}'. Ask DEV or Cowork LARA to add it."

        col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)

        updates = [
            {"range": f"'{tab}'!{col_letter}{row_idx}", "values": [[new_value]]}
        ]

        # Auto-stamp Last Contact (unless that's the field being updated)
        if canonical_field != "last_contact":
            contact_col_idx = None
            for i, h in enumerate(raw_headers):
                if _MWM_CLIENTS_HEADER_ALIASES.get(h) == "last_contact":
                    contact_col_idx = i
                    break
            if contact_col_idx is not None:
                contact_letter = chr(65 + contact_col_idx) if contact_col_idx < 26 else chr(64 + contact_col_idx // 26) + chr(65 + contact_col_idx % 26)
                now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
                updates.append({"range": f"'{tab}'!{contact_letter}{row_idx}", "values": [[now]]})

        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=LEADS_SHEET_ID,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()

        old_value = client.get(canonical_field, "") or "(empty)"
        display_name = client.get("name") or client.get("company") or client_name
        return (
            f"✅ *Client updated!*\n"
            f"• *Client:* {display_name}\n"
            f"• *{canonical_field}:* {old_value} → *{new_value}*"
        )
    except Exception as e:
        print(f"[LARA] Update client error: {e}")
        return f"⚠️ Error updating client: {str(e)[:200]}"


def get_upcoming_shoots(text):
    """List clients who have anything in their Upcoming column.

    Session 30.11: Upcoming is free-text (e.g. "Apr 15 shoot at studio, 3 eps")
    rather than a structured date, so we can't sort by date — we just list
    every client who has something scheduled.
    """
    try:
        clients = _get_all_clients()
        if not clients:
            return "📅 No clients in MWM Clients sheet."

        with_upcoming = [
            client for _, client in clients
            if (client.get("upcoming") or "").strip()
        ]

        if not with_upcoming:
            return "📅 *No upcoming shoots or deliveries scheduled.*"

        lines = [f"📅 *Upcoming* — {len(with_upcoming)} client(s) with scheduled work\n"]

        for client in with_upcoming:
            name = client.get("name") or client.get("company") or "?"
            company = client.get("company") or ""
            plan = client.get("plan") or ""
            upcoming = (client.get("upcoming") or "").strip()
            header_bits = [f"*{name}*"]
            if company and company.lower() != name.lower():
                header_bits.append(f"_({company})_")
            if plan:
                header_bits.append(f"— {plan}")
            lines.append(" ".join(header_bits))
            lines.append(f"   📅 {upcoming[:300]}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[LARA] Upcoming shoots error: {e}")
        return f"⚠️ Error fetching upcoming: {str(e)[:200]}"


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

        email = (client.get("email") or "").strip()
        display_name = client.get("name") or client.get("company") or client_name
        if not email:
            return f"⚠️ No email on file for *{display_name}*."

        # Build email info for Claude to compose (new 10-col schema)
        plan = client.get("plan") or "N/A"
        status = client.get("status") or "N/A"
        delivered = client.get("delivered") or "—"
        upcoming = client.get("upcoming") or "—"
        return (
            f"📧 *Email Draft Ready*\n"
            f"• *To:* {display_name} ({email})\n"
            f"• *Re:* {subject_hint if subject_hint else 'Follow-up'}\n"
            f"• *Plan:* {plan}\n"
            f"• *Status:* {status}\n"
            f"• *Delivered:* {delivered}\n"
            f"• *Upcoming:* {upcoming}\n\n"
            f"_I've prepared the context. Tell me what to say and I'll send it, or I can draft a professional follow-up based on their current production stage._"
        )
    except Exception as e:
        print(f"[LARA] Send email error: {e}")
        return f"⚠️ Error preparing email: {str(e)[:200]}"


def check_calendar(text, sender_is_michael=False):
    """Check calendar events/availability using ana_calendar.

    When sender_is_michael is True, LARA will pull BOTH the shared MWM
    CREATIONS production calendar and Michael's personal calendar
    (via Domain-Wide Delegation) so "how is my day tomorrow" returns a
    merged view instead of asking which calendar to look at.
    """
    try:
        from ana_calendar import handle_calendar_action
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        handled, result = handle_calendar_action(text_clean, include_personal=sender_is_michael)
        if handled:
            return result
        # Try rephrasing
        handled, result = handle_calendar_action(
            f"what is on my calendar {text_clean}", include_personal=sender_is_michael
        )
        if handled:
            return result
        return "\U0001f914 I couldn't parse the calendar request. Try: *what's on the calendar today?*"
    except Exception as e:
        print(f"[LARA] Calendar check error: {e}")
        return f"\u26a0\ufe0f Error checking calendar: {str(e)[:200]}"


def _format_phone_display(phone):
    """Format +15616392905 as +1 (561) 639-2905 for display."""
    digits = _normalize_phone_digits(phone)
    if len(digits) == 11 and digits.startswith("1"):
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    if len(digits) == 13 and digits.startswith("55"):
        return f"+55 {digits[2:4]} {digits[4:9]}-{digits[9:]}"
    return phone


def check_crew(text):
    """Handle crew-related queries.

    Supports:
    - Crew list / roster ("show me the crew", "who's on the crew")
    - Specific crew member lookup ("is Bruno available", "phone for Guga")
    - Availability queries (deferred: LARA explains she can't auto-check
      personal calendars for crew, and offers to message them directly)
    """
    text_lower = text.lower().strip()

    # Try to find a specific crew member mentioned by name
    known_names = ["bruno", "guga", "asafh", "asaph", "erika", "luis"]
    mentioned = None
    for name in known_names:
        if re.search(rf"\b{name}\b", text_lower):
            mentioned = find_crew_member(name)
            if mentioned:
                break

    # Detect "availability" intent keywords
    availability_keywords = [
        "available", "free", "busy", "dispon", "livre",
        "can", "will", "able", "working", "on shift", "on set",
    ]
    asking_availability = any(kw in text_lower for kw in availability_keywords)

    # Detect "contact/phone/email" intent
    contact_keywords = ["phone", "contact", "email", "number", "info", "reach", "call", "text"]
    asking_contact = any(kw in text_lower for kw in contact_keywords)

    # ── Case 1: Specific crew member mentioned ──
    if mentioned:
        phone_display = _format_phone_display(mentioned["phone"])
        if asking_contact and not asking_availability:
            lines = [
                f"\U0001f464 *{mentioned['name']}* ({mentioned['role']})",
                f"\U0001f4f1 {phone_display}",
            ]
            if mentioned.get("email"):
                lines.append(f"\u2709\ufe0f {mentioned['email']}")
            if mentioned.get("notes"):
                lines.append(f"_{mentioned['notes']}_")
            return "\n".join(lines)

        if asking_availability:
            return (
                f"I don't have direct access to *{mentioned['name']}*'s personal calendar, "
                f"so I can't auto-confirm their availability. Their contact is "
                f"{phone_display} \u2014 want me to draft a quick WhatsApp message to "
                f"ask them about the shoot, or would you rather reach out yourself?"
            )

        # Default: full card
        lines = [
            f"\U0001f464 *{mentioned['name']}* ({mentioned['role']})",
            f"\U0001f4f1 {phone_display}",
        ]
        if mentioned.get("email"):
            lines.append(f"\u2709\ufe0f {mentioned['email']}")
        if mentioned.get("notes"):
            lines.append(f"_{mentioned['notes']}_")
        return "\n".join(lines)

    # ── Case 2: Generic crew list / roster request ──
    lines = [f"\U0001f3ac *MWM Crew* ({len(MWM_CREW)} members)\n"]
    for crew in MWM_CREW:
        phone_display = _format_phone_display(crew["phone"])
        role_tag = f" \u2014 _{crew['role']}_" if crew.get("role") else ""
        lines.append(f"\u2022 *{crew['name']}*{role_tag}")
        lines.append(f"  \U0001f4f1 {phone_display}")
        if crew.get("email"):
            lines.append(f"  \u2709\ufe0f {crew['email']}")

    # If they were asking about availability (no specific name), add a note
    if asking_availability:
        lines.append("")
        lines.append(
            "\u26a0\ufe0f I don't have direct access to crew members' personal calendars, "
            "so for specific availability you'll need to reach out to them directly. "
            "Let me know which crew member and I can draft a WhatsApp message for you."
        )

    return "\n".join(lines)


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
            if client and client.get("email"):
                query += f" from:{client['email']}"
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


# ── Outbound Template Handler (Session 30.15) ───────────────────────

# Map keywords/context → template name for smart template selection.
_TEMPLATE_KEYWORD_MAP = {
    "availability": "lara_crew_availability",
    "disponibilidade": "lara_crew_availability",
    "disponível": "lara_crew_availability",
    "available": "lara_crew_availability",
    "crew": "lara_crew_availability",
    "confirm": "lara_client_confirmation",
    "confirmar": "lara_client_confirmation",
    "confirmation": "lara_client_confirmation",
    "confirmação": "lara_client_confirmation",
    "reminder": "lara_shoot_reminder",
    "lembrete": "lara_shoot_reminder",
    "remind": "lara_shoot_reminder",
    "lembrar": "lara_shoot_reminder",
    "video": "lara_video_approval",
    "vídeo": "lara_video_approval",
    "approval": "lara_video_approval",
    "aprovação": "lara_video_approval",
}


def send_template_to_client(text):
    """Parse a template-send request, look up the client, pick the right template,
    and send it via the Meta Cloud API.

    This handler is triggered by the 'send_template' intent in LARA_ACTION_INTENTS.
    Michael says things like:
    - "send a reminder to João about the shoot on April 20"
    - "reach out to Maria"
    - "confirm shoot with Victory MA at Orlando"
    - "send video approval to Ana"
    """
    try:
        text_clean = re.sub(r"^(?:lara[,:\s]*)?", "", text.strip(), flags=re.IGNORECASE).strip()
        text_lower = text_clean.lower()

        # ── 1. Detect explicit template name (e.g. "send template lara_crew_availability to João")
        explicit_match = re.search(r"template\s+(lara_\w+)\s+(?:to|para|for)\s+(.+)", text_lower)
        if explicit_match:
            template_name = explicit_match.group(1)
            client_search = explicit_match.group(2).strip()
        else:
            template_name = None
            client_search = None

        # ── 2. Extract client name from various patterns
        if not client_search:
            # Try "to/para/for/com <name>" patterns
            name_match = re.search(
                r"(?:to|para|for|com|pra|pro)\s+(.+?)(?:\s+(?:about|sobre|regarding|on|no|na|em|at|às|as)\s+|$)",
                text_lower,
            )
            if name_match:
                client_search = name_match.group(1).strip()
            else:
                # Try "remind/ask <name> ..."
                name_match2 = re.search(
                    r"(?:remind|ask|lembrar?|perguntar?|contact|message|text)\s+(.+?)(?:\s+(?:about|if|se|regarding|of|que)\s+|$)",
                    text_lower,
                )
                if name_match2:
                    client_search = name_match2.group(1).strip()
                else:
                    # Last resort: "contato com <name>"
                    name_match3 = re.search(r"contato\s+com\s+(.+)", text_lower)
                    if name_match3:
                        client_search = name_match3.group(1).strip()

        if not client_search or len(client_search) < 2:
            return "📱 Quem você quer que eu contate? Me diz o nome do cliente ou membro da equipe."

        # Clean up client search — remove trailing noise
        client_search = re.sub(r"\s+(?:please|por favor|obrigad[oa])\s*$", "", client_search).strip()

        # ── 3. Look up client in the MWM Clients sheet
        row_idx, client = _find_client(client_search)
        if not client:
            return f'📱 Não encontrei *"{client_search}"* na planilha de clientes. Confere o nome e tenta de novo?'

        client_phone = client.get("phone", "")
        client_name = client.get("name") or client.get("company") or client_search

        if not client_phone:
            return f"📱 Encontrei *{client_name}*, mas não tem telefone cadastrado na planilha. Adiciona o número primeiro."

        # ── 4. Auto-detect template if not explicitly provided
        if not template_name:
            for keyword, tpl in _TEMPLATE_KEYWORD_MAP.items():
                if keyword in text_lower:
                    template_name = tpl
                    break

        if not template_name:
            # Default: general outreach
            template_name = "lara_general_outreach"

        if template_name not in LARA_TEMPLATES:
            return f"⚠️ Template desconhecido: {template_name}"

        # ── 5. Build parameters based on template
        params = [client_name]  # {{1}} is always the name

        if template_name == "lara_crew_availability":
            # Try to extract a date from the message
            date_match = re.search(
                r"(?:on|para|dia|em|for)\s+(\d{1,2}\s+(?:de\s+)?\w+|\w+\s+\d{1,2}(?:st|nd|rd|th)?)",
                text_clean, re.IGNORECASE,
            )
            params.append(date_match.group(1).strip() if date_match else "a próxima gravação")

        elif template_name == "lara_client_confirmation":
            date_match = re.search(
                r"(?:on|para|dia|em|for)\s+(\d{1,2}\s+(?:de\s+)?\w+|\w+\s+\d{1,2}(?:st|nd|rd|th)?)",
                text_clean, re.IGNORECASE,
            )
            location_match = re.search(
                r"(?:at|em|in|no|na)\s+([A-Z][a-zA-Z\s]+?)(?:\s+(?:on|para|dia|about|$)|\s*$)",
                text_clean,
            )
            params.append(date_match.group(1).strip() if date_match else "a data agendada")
            params.append(location_match.group(1).strip() if location_match else "o local combinado")

        elif template_name == "lara_shoot_reminder":
            date_match = re.search(
                r"(?:on|para|dia|em|for)\s+(\d{1,2}\s+(?:de\s+)?\w+|\w+\s+\d{1,2}(?:st|nd|rd|th)?)",
                text_clean, re.IGNORECASE,
            )
            time_match = re.search(
                r"(?:at|às|as)\s+(\d{1,2}[h:]\d{0,2}\s*(?:am|pm)?)",
                text_clean, re.IGNORECASE,
            )
            params.append(date_match.group(1).strip() if date_match else "a data agendada")
            params.append(time_match.group(1).strip() if time_match else "o horário combinado")

        # lara_video_approval and lara_general_outreach: only {{1}} = name (already set)

        # ── 6. Send it!
        result = send_lara_template(client_phone, template_name, params)

        if result.get("ok"):
            template_label = template_name.replace("lara_", "").replace("_", " ").title()
            return (
                f"✅ Template *{template_label}* enviado para *{client_name}* "
                f"({client_phone}).\n"
                f"Message ID: {result.get('message_id', 'n/a')}"
            )
        else:
            return f"⚠️ Falha ao enviar template para {client_name}: {result.get('error', 'unknown error')}"

    except Exception as e:
        print(f"[LARA] send_template_to_client error: {e}")
        return f"⚠️ Erro ao enviar template: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
def _get_intent_handlers():
    """Build the intent → handler map. Imports lara_drive lazily to avoid
    circular imports since lara_drive.py calls back into lara_actions._get_google_creds.
    """
    handlers = {
        "production_overview": get_production_overview,
        "client_status": get_client_status,
        "update_client": update_client_field,
        "upcoming_shoots": get_upcoming_shoots,
        "send_client_email": send_client_email,
        "check_calendar": check_calendar,
        "read_emails": read_emails,
        "check_crew": check_crew,
        "send_template": send_template_to_client,
    }
    try:
        from lara_drive import DRIVE_HANDLERS
        handlers.update(DRIVE_HANDLERS)
    except Exception as e:
        print(f"[LARA] lara_drive import failed (non-fatal): {e}")
    return handlers


_INTENT_HANDLERS = _get_intent_handlers()


def handle_lara_action(text, sender_is_michael=False):
    """Check if text matches a Lara action intent and execute it.

    Parameters
    ----------
    text : str
        The incoming message text.
    sender_is_michael : bool
        When True, identity-aware handlers (currently check_calendar) will
        pull from Michael's personal calendar in addition to the shared
        MWM production calendar.

    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_lara_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[LARA] Action intent detected: {intent} (matched: '{match.group(0)}', michael={sender_is_michael})")
        handler = _INTENT_HANDLERS[intent]
        # check_calendar is the only handler that currently accepts sender context
        if intent == "check_calendar":
            result = handler(text, sender_is_michael=sender_is_michael)
        else:
            result = handler(text)
        return True, result

    return False, None
