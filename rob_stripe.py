"""
ROB Stripe Action Handlers — Real-time Slack action capability for ROB (Financial Advisor).

Handles:
- Get Stripe balance (available + pending)
- List recent charges with amount, status, customer email, description
- List active subscriptions with customer, amount, billing interval
- Get customer by email lookup with subscriptions
- List recent invoices with status, amount, customer

Uses STRIPE_SECRET_KEY from Railway env vars.
Stripe REST API v1 — https://api.stripe.com/v1
Auth: Basic auth with secret key as username, empty password
"""

import os
import re
import json
from datetime import datetime
from base64 import b64encode

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_BASE_URL = "https://api.stripe.com/v1"


def _stripe_headers():
    """Return auth headers for Stripe API."""
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    # Basic auth: secret_key as username, empty password
    auth_str = b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
    return {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _stripe_get(endpoint, params=None):
    """Make a GET request to Stripe API."""
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    url = f"{STRIPE_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.get(url, headers=_stripe_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _stripe_post(endpoint, data=None):
    """Make a POST request to Stripe API."""
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    url = f"{STRIPE_BASE_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.post(url, headers=_stripe_headers(), data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Intent Detection ────────────────────────────────────────────────
ROB_ACTION_INTENTS = {
    "get_stripe_balance": [
        r"(?:what|check|get|show|display)\s+(?:(?:our|the|my)\s+)?(?:stripe\s+)?balance",
        r"(?:how\s+)?(?:much\s+)?(?:money|funds?)\s+(?:do|have|does)\s+(?:we|i)\s+(?:have|need)",
        r"stripe\s+(?:balance|account\s+balance|funds?)",
        r"(?:available|pending)\s+(?:balance|funds?|money)",
        r"(?:account\s+)?balance\s+(?:check|status)",
    ],
    "list_recent_charges": [
        r"(?:show|list|display|get|what)\s+(?:recent\s+)?(?:charges|payments|transactions)",
        r"(?:what\s+)?(?:charges|payments|transactions)\s+(?:came\s+in|did\s+we\s+receive|came\s+through)",
        r"(?:list|show|get)\s+(?:last|recent|latest)\s+(?:charges|payments)",
        r"recent\s+(?:charges|activity|transactions)",
        r"(?:stripe\s+)?(?:charges|payments)\s+(?:list|summary)",
    ],
    "list_active_subscriptions": [
        r"(?:show|list|display|get|what)\s+(?:active\s+)?(?:subscriptions?|subs)",
        r"(?:who|which)\s+(?:customers?|users?)\s+(?:are\s+)?(?:subscribed|active)",
        r"(?:list|show|get|display)\s+(?:all\s+)?(?:our\s+)?(?:subscriptions|active\s+subs)",
        r"(?:how\s+many\s+)?(?:subscriptions?|subscribers?)\s+(?:do|have|does)\s+(?:we|i)\s+(?:have)",
        r"(?:active\s+)?subscriptions?\s+(?:list|summary|count)",
    ],
    "get_customer_by_email": [
        r"(?:look\s+up|find|get|show|who\s+is|search\s+for)\s+(?:customer|user)\s+(?:by\s+)?(?:email\s+)?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+)",
        r"(?:customer|user|person)\s+(?:named|called|email|for)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+)",
        r"(?:who\s+is|what|find)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+)",
        r"customer\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+)",
    ],
    "list_invoices": [
        r"(?:show|list|display|get|what)\s+(?:recent\s+)?(?:invoices?|billing)",
        r"(?:list|show|get)\s+(?:unpaid|outstanding|draft)\s+(?:invoices?|bills?)",
        r"(?:any\s+)?(?:unpaid|outstanding|draft)\s+(?:invoices?|bills?)",
        r"(?:invoices?|billing)\s+(?:list|summary|status)",
        r"(?:show|list|get)\s+(?:all\s+)?(?:invoices?|bills?)",
    ],
}


def detect_rob_intent(text):
    """Detect if text contains a ROB action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "rob" prefix if present (and variations like "hey rob", "hi rob")
    text_lower = re.sub(r"^(?:rob|hey\s+rob|hi\s+rob)[,:\s]*", "", text_lower).strip()

    for intent, patterns in ROB_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def get_stripe_balance(text):
    """Get current Stripe balance (available + pending)."""
    try:
        print("[ROB] Fetching Stripe balance...")

        balance = _stripe_get("/balance")

        available = balance.get("available", [])
        pending = balance.get("pending", [])

        # Group by currency
        avail_by_currency = {}
        for item in available:
            currency = item.get("currency", "unknown").upper()
            amount = item.get("amount", 0) / 100  # Convert cents to dollars
            avail_by_currency[currency] = amount

        pending_by_currency = {}
        for item in pending:
            currency = item.get("currency", "unknown").upper()
            amount = item.get("amount", 0) / 100
            pending_by_currency[currency] = amount

        if not avail_by_currency and not pending_by_currency:
            return "💰 *Stripe Balance* — No balance information available."

        lines = ["💰 *Stripe Account Balance*\n"]

        all_currencies = set(avail_by_currency.keys()) | set(pending_by_currency.keys())
        for currency in sorted(all_currencies):
            avail = avail_by_currency.get(currency, 0)
            pend = pending_by_currency.get(currency, 0)
            total = avail + pend

            lines.append(f"*{currency}*")
            lines.append(f"  • Available: ${avail:,.2f}")
            if pend > 0:
                lines.append(f"  • Pending: ${pend:,.2f}")
            lines.append(f"  • Total: ${total:,.2f}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[ROB] Balance fetch error: {e}")
        return f"⚠️ Error fetching Stripe balance: {str(e)[:200]}"


def list_recent_charges(text):
    """List recent charges with amount, status, customer email, description."""
    try:
        print("[ROB] Fetching recent charges...")

        charges = _stripe_get("/charges", params=[
            ("limit", 20),
            ("expand[]", "data.customer"),
        ])

        charge_list = charges.get("data", [])

        if not charge_list:
            return "📊 *Recent Charges* — No charges found."

        lines = [f"📊 *Recent Charges* — {len(charge_list)} shown\n"]

        for charge in charge_list[:20]:
            amount = charge.get("amount", 0) / 100
            currency = charge.get("currency", "usd").upper()
            status = charge.get("status", "unknown")
            description = charge.get("description", "(no description)")
            created = charge.get("created", 0)

            # Get customer info
            customer_obj = charge.get("customer")
            customer_email = "(no email)"
            if isinstance(customer_obj, dict):
                customer_email = customer_obj.get("email", "(no email)")
            elif customer_obj and isinstance(customer_obj, str):
                # If it's just an ID string, we can't get email without another API call
                customer_email = f"(ID: {customer_obj})"

            # Format timestamp
            date_str = datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")

            # Status emoji
            status_emoji = "✅" if status == "succeeded" else "⏳" if status == "pending" else "❌"

            lines.append(f"{status_emoji} *${amount:,.2f} {currency}* — {description}")
            lines.append(f"   Customer: {customer_email} | Status: {status} | {date_str}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[ROB] Charges fetch error: {e}")
        return f"⚠️ Error fetching charges: {str(e)[:200]}"


def list_active_subscriptions(text):
    """List all active subscriptions with customer, amount, billing interval."""
    try:
        print("[ROB] Fetching active subscriptions...")

        subscriptions = _stripe_get("/subscriptions", params=[
            ("status", "active"),
            ("limit", 50),
            ("expand[]", "data.customer"),
            ("expand[]", "data.items.data.price"),
        ])

        sub_list = subscriptions.get("data", [])

        if not sub_list:
            return "📅 *Active Subscriptions* — No active subscriptions found."

        lines = [f"📅 *Active Subscriptions* — {len(sub_list)} active\n"]

        for sub in sub_list:
            sub_id = sub.get("id", "?")

            # Get customer info
            customer_obj = sub.get("customer")
            customer_email = "Unknown"
            if isinstance(customer_obj, dict):
                customer_email = customer_obj.get("email", "Unknown")

            # Get pricing info from items
            items = sub.get("items", {}).get("data", [])
            prices_info = []

            for item in items:
                price_obj = item.get("price")
                if isinstance(price_obj, dict):
                    amount = price_obj.get("unit_amount", 0) / 100
                    currency = price_obj.get("currency", "usd").upper()
                    interval = price_obj.get("recurring", {}).get("interval", "unknown")
                    product_name = price_obj.get("product", "Product")
                    if isinstance(product_name, dict):
                        product_name = product_name.get("name", "Product")
                    prices_info.append(f"${amount:,.2f} {currency}/{interval}")

            price_str = " + ".join(prices_info) if prices_info else "Price unavailable"
            status = sub.get("status", "unknown")
            created = sub.get("created", 0)
            date_str = datetime.fromtimestamp(created).strftime("%Y-%m-%d")

            lines.append(f"✅ *{customer_email}*")
            lines.append(f"   Amount: {price_str} | Status: {status} | Since: {date_str}")

        if len(sub_list) > 20:
            lines.append(f"\n_Showing first 20 of {len(sub_list)} subscriptions_")

        return "\n".join(lines)
    except Exception as e:
        print(f"[ROB] Subscriptions fetch error: {e}")
        return f"⚠️ Error fetching subscriptions: {str(e)[:200]}"


def get_customer_by_email(text):
    """Look up a customer by email, return their info + subscriptions."""
    try:
        # Extract email from text
        email_match = re.search(
            r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            text, re.IGNORECASE
        )

        if not email_match:
            return "🤔 Which customer email? Try: *Look up customer john@example.com*"

        customer_email = email_match.group(1).lower()
        print(f"[ROB] Looking up customer by email: {customer_email}")

        # Search for customer by email
        customers = _stripe_get("/customers", params=[
            ("email", customer_email),
            ("limit", 1),
            ("expand[]", "data.subscriptions"),
        ])

        customer_list = customers.get("data", [])

        if not customer_list:
            return f"🔍 Customer *{customer_email}* not found in Stripe."

        customer = customer_list[0]
        customer_id = customer.get("id", "?")
        customer_name = customer.get("name", "(no name)")
        created = customer.get("created", 0)
        date_str = datetime.fromtimestamp(created).strftime("%Y-%m-%d")

        lines = [f"👤 *Customer: {customer_name}*"]
        lines.append(f"   Email: {customer_email} | ID: {customer_id} | Created: {date_str}")

        # Get subscriptions
        subscriptions_obj = customer.get("subscriptions", {})
        subs_list = subscriptions_obj.get("data", []) if isinstance(subscriptions_obj, dict) else []

        if subs_list:
            lines.append(f"\n📅 *Subscriptions ({len(subs_list)}):*")
            for sub in subs_list:
                sub_id = sub.get("id", "?")
                status = sub.get("status", "unknown")

                # Get pricing info
                items = sub.get("items", {}).get("data", [])
                prices_info = []
                for item in items:
                    price_obj = item.get("price")
                    if isinstance(price_obj, dict):
                        amount = price_obj.get("unit_amount", 0) / 100
                        currency = price_obj.get("currency", "usd").upper()
                        interval = price_obj.get("recurring", {}).get("interval", "unknown")
                        prices_info.append(f"${amount:,.2f} {currency}/{interval}")

                price_str = " + ".join(prices_info) if prices_info else "Price unavailable"
                lines.append(f"   • {sub_id}: {price_str} ({status})")
        else:
            lines.append("\n📅 *Subscriptions:* None")

        return "\n".join(lines)
    except Exception as e:
        print(f"[ROB] Customer lookup error: {e}")
        return f"⚠️ Error looking up customer: {str(e)[:200]}"


def list_invoices(text):
    """List recent invoices with status (paid/unpaid/draft), amount, customer."""
    try:
        print("[ROB] Fetching recent invoices...")

        invoices = _stripe_get("/invoices", params=[
            ("limit", 30),
            ("expand[]", "data.customer"),
        ])

        invoice_list = invoices.get("data", [])

        if not invoice_list:
            return "📄 *Invoices* — No invoices found."

        # Check if user asked specifically for unpaid/draft
        text_lower = text.lower()
        filter_status = None
        if any(kw in text_lower for kw in ["unpaid", "outstanding", "due"]):
            filter_status = "open"
        elif any(kw in text_lower for kw in ["draft"]):
            filter_status = "draft"
        elif any(kw in text_lower for kw in ["paid"]):
            filter_status = "paid"

        if filter_status:
            invoice_list = [inv for inv in invoice_list if inv.get("status") == filter_status]

        lines = [f"📄 *Invoices* — {len(invoice_list)} shown\n"]

        for invoice in invoice_list[:30]:
            invoice_id = invoice.get("id", "?")
            amount = invoice.get("total", 0) / 100
            currency = invoice.get("currency", "usd").upper()
            status = invoice.get("status", "unknown")
            customer_obj = invoice.get("customer")

            customer_email = "Unknown"
            if isinstance(customer_obj, dict):
                customer_email = customer_obj.get("email", "Unknown")

            created = invoice.get("created", 0)
            date_str = datetime.fromtimestamp(created).strftime("%Y-%m-%d")

            # Status emoji
            if status == "paid":
                status_emoji = "✅"
            elif status == "open":
                status_emoji = "⏳"
            elif status == "draft":
                status_emoji = "📝"
            else:
                status_emoji = "❓"

            number = invoice.get("number", "(no number)")
            lines.append(f"{status_emoji} *Invoice {number}* — ${amount:,.2f} {currency}")
            lines.append(f"   Customer: {customer_email} | Status: {status} | {date_str}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[ROB] Invoices fetch error: {e}")
        return f"⚠️ Error fetching invoices: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "get_stripe_balance": get_stripe_balance,
    "list_recent_charges": list_recent_charges,
    "list_active_subscriptions": list_active_subscriptions,
    "get_customer_by_email": get_customer_by_email,
    "list_invoices": list_invoices,
}


def handle_rob_action(text):
    """Check if text matches a ROB action intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_rob_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[ROB] Action intent detected: {intent} (matched: '{match.group(0)}')")
        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result

    return False, None
