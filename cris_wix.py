"""
Cris Wix Action Handlers — Real-time Slack action capability for Cris (Website Developer).

Handles:
- List Wix sites (all sites in account)
- Query site contacts (leads/form submissions)
- List blog posts (recent posts on a site)
- Query store products (products in a Wix Store)
- Query CMS data items (items in any CMS collection)

Uses WIX_API_KEY and WIX_ACCOUNT_ID from Railway env vars.
Wix REST API — https://dev.wix.com/docs/rest
"""

import os
import re
import json
from datetime import datetime

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
WIX_API_KEY = os.getenv("WIX_API_KEY", "")
WIX_SITE_ID = os.getenv("WIX_SITE_ID", "")  # Default site ID
WIX_ACCOUNT_ID = os.getenv("WIX_ACCOUNT_ID", "")  # Account-level API calls


def _wix_headers(site_id=None):
    """Return auth + site context headers for Wix API."""
    if not WIX_API_KEY:
        raise RuntimeError("WIX_API_KEY not configured")
    headers = {
        "Authorization": WIX_API_KEY,
        "Content-Type": "application/json",
    }
    sid = site_id or WIX_SITE_ID
    if sid:
        headers["wix-site-id"] = sid
    if WIX_ACCOUNT_ID:
        headers["wix-account-id"] = WIX_ACCOUNT_ID
    return headers


def _wix_get(url, params=None, site_id=None):
    """Make a GET request to Wix API."""
    if not WIX_API_KEY:
        raise RuntimeError("WIX_API_KEY not configured")
    resp = http_requests.get(url, headers=_wix_headers(site_id), params=params, timeout=20)
    if resp.status_code != 200:
        error_body = resp.text[:500]
        print(f"[Cris] Wix API error {resp.status_code}: {error_body}")
        resp.raise_for_status()
    return resp.json()


def _wix_post(url, data=None, site_id=None):
    """Make a POST request to Wix API."""
    if not WIX_API_KEY:
        raise RuntimeError("WIX_API_KEY not configured")
    resp = http_requests.post(url, headers=_wix_headers(site_id), json=data, timeout=20)
    if resp.status_code not in (200, 201):
        error_body = resp.text[:500]
        print(f"[Cris] Wix API error {resp.status_code}: {error_body}")
        resp.raise_for_status()
    return resp.json()


# ── Intent Detection ────────────────────────────────────────────────
CRIS_ACTION_INTENTS = {
    "list_sites": [
        r"(?:list|show|get|what)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:wix\s+)?sites?",
        r"(?:what|which)\s+(?:wix\s+)?(?:sites?|websites?)\s+(?:do\s+we|are\s+there|exist)",
        r"(?:our|my|the)\s+(?:wix\s+)?(?:sites?|websites?)",
        r"(?:wix\s+)?(?:sites?|websites?)\s+(?:list|overview|summary)",
    ],
    "query_contacts": [
        r"(?:list|show|get|query|check)\s+(?:me\s+)?(?:the\s+)?(?:site\s+)?(?:contacts?|leads?|subscribers?)",
        r"(?:how\s+many|what|who)\s+(?:contacts?|leads?|subscribers?)\s+(?:do\s+we|are\s+there)",
        r"(?:new|recent|latest)\s+(?:contacts?|leads?|form\s+submissions?)",
        r"(?:contacts?|leads?)\s+(?:list|overview|summary|count)",
        r"(?:form\s+)?submissions?",
    ],
    "list_blog_posts": [
        r"(?:list|show|get|what)\s+(?:me\s+)?(?:the\s+)?(?:blog\s+)?posts?",
        r"(?:recent|latest|new)\s+(?:blog\s+)?posts?",
        r"(?:blog\s+)?(?:posts?|articles?)\s+(?:list|overview|summary)",
        r"(?:what|how\s+many)\s+(?:blog\s+)?(?:posts?|articles?)\s+(?:do\s+we|are\s+there|have\s+been)",
        r"blog\s+(?:content|status|overview)",
    ],
    "query_products": [
        r"(?:list|show|get|what)\s+(?:me\s+)?(?:the\s+)?(?:store\s+)?products?",
        r"(?:what|which)\s+(?:products?|items?)\s+(?:do\s+we|are\s+in)\s+(?:the\s+)?(?:store|shop)",
        r"(?:store|shop|catalog)\s+(?:products?|items?|inventory)",
        r"(?:product|catalog)\s+(?:list|overview|summary)",
    ],
    "query_cms_items": [
        r"(?:list|show|get|query)\s+(?:me\s+)?(?:the\s+)?(?:cms\s+)?(?:collection\s+)?(?:items?|data|content)\s+(?:from|in)\s+(.+)",
        r"(?:what|how\s+many)\s+(?:items?|entries?|records?)\s+(?:are\s+)?(?:in\s+)?(?:the\s+)?(?:cms\s+)?collection\s+(.+)",
        r"(?:cms|collection)\s+(.+?)(?:\s+(?:items?|data|content|entries?))?$",
    ],
}


def detect_cris_intent(text):
    """Detect if text contains a Cris action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "cris" prefix if present
    text_lower = re.sub(r"^(?:cris|hey\s+cris|hi\s+cris)[,:\s]*", "", text_lower).strip()

    for intent, patterns in CRIS_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def list_sites(text):
    """List all Wix sites in the account."""
    try:
        print("[Cris] Fetching Wix sites...")

        data = _wix_post(
            "https://www.wixapis.com/site-list/v2/sites/query",
            data={"query": {"paging": {"limit": 50}}}
        )

        sites = data.get("sites", [])
        if not sites:
            return "🌐 *No Wix sites found* in this account."

        lines = [f"🌐 *Wix Sites* — {len(sites)} found\n"]

        for site in sites:
            name = site.get("displayName", "(unnamed)")
            site_id = site.get("id", "unknown")
            status = site.get("published", False)
            status_emoji = "🟢" if status else "🔴"
            url = site.get("viewUrl", "")

            lines.append(f"  {status_emoji} *{name}*")
            if url:
                lines.append(f"     URL: {url}")
            lines.append(f"     ID: `{site_id}` | Published: {'Yes' if status else 'No'}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Cris] Sites fetch error: {e}")
        return f"⚠️ Error fetching Wix sites: {str(e)[:200]}"


def query_contacts(text):
    """Query contacts/leads from Wix site."""
    try:
        print("[Cris] Fetching site contacts...")

        data = _wix_post(
            "https://www.wixapis.com/contacts/v4/contacts/query",
            data={
                "query": {
                    "paging": {"limit": 25, "offset": 0},
                    "sort": [{"fieldName": "lastActivity.activityDate", "order": "DESC"}],
                },
            }
        )

        contacts = data.get("contacts", [])
        total = data.get("pagingMetadata", {}).get("total", len(contacts))

        if not contacts:
            return "👥 *No contacts found* on this site."

        lines = [f"👥 *Site Contacts* — showing {len(contacts)} of {total}\n"]

        for contact in contacts[:25]:
            name_info = contact.get("info", {}).get("name", {})
            first = name_info.get("first", "")
            last = name_info.get("last", "")
            name = f"{first} {last}".strip() or "(unnamed)"

            emails = contact.get("info", {}).get("emails", [])
            email = emails[0].get("email", "(no email)") if emails else "(no email)"

            phones = contact.get("info", {}).get("phones", [])
            phone = phones[0].get("phone", "") if phones else ""

            labels = [l.get("displayName", "") for l in contact.get("info", {}).get("labelKeys", {}).get("items", [])]

            created = contact.get("createdDate", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            lines.append(f"  • *{name}* — {email}")
            if phone:
                lines.append(f"    📱 {phone}")
            if created:
                lines.append(f"    Added: {created}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Cris] Contacts fetch error: {e}")
        return f"⚠️ Error fetching contacts: {str(e)[:200]}"


def list_blog_posts(text):
    """List recent blog posts from Wix site."""
    try:
        print("[Cris] Fetching blog posts...")

        data = _wix_post(
            "https://www.wixapis.com/blog/v3/posts/query",
            data={
                "query": {
                    "paging": {"limit": 15},
                    "sort": [{"fieldName": "lastPublishedDate", "order": "DESC"}],
                },
                "fieldsets": ["URL", "COUNTERS"],
            }
        )

        posts = data.get("posts", [])

        if not posts:
            return "📝 *No blog posts found* on this site."

        lines = [f"📝 *Blog Posts* — {len(posts)} most recent\n"]

        for post in posts:
            title = post.get("title", "(untitled)")
            status = post.get("status", "unknown")
            url = post.get("url", {}).get("base", "") + post.get("url", {}).get("path", "")

            published = post.get("lastPublishedDate", "")
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    published = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            counters = post.get("metrics", {})
            views = counters.get("views", 0)
            likes = counters.get("likes", 0)
            comments = counters.get("comments", 0)

            status_emoji = {"PUBLISHED": "🟢", "DRAFT": "📝", "SCHEDULED": "⏰"}.get(status, "⚪")

            lines.append(f"  {status_emoji} *{title}*")
            if published:
                lines.append(f"     Published: {published} | 👀 {views} | ❤️ {likes} | 💬 {comments}")
            if url:
                lines.append(f"     {url}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Cris] Blog posts fetch error: {e}")
        return f"⚠️ Error fetching blog posts: {str(e)[:200]}"


def query_products(text):
    """Query store products from Wix site."""
    try:
        print("[Cris] Fetching store products...")

        data = _wix_post(
            "https://www.wixapis.com/stores/v1/products/query",
            data={
                "query": {
                    "paging": {"limit": 25},
                    "sort": '[{"lastUpdated": "desc"}]',
                },
                "includeVariants": False,
            }
        )

        products = data.get("products", [])
        total = data.get("totalResults", len(products))

        if not products:
            return "🛍️ *No products found* in the store."

        lines = [f"🛍️ *Store Products* — showing {len(products)} of {total}\n"]

        for product in products[:25]:
            name = product.get("name", "(unnamed)")
            status = product.get("visible", True)
            status_emoji = "🟢" if status else "🔴"

            price = product.get("price", {})
            formatted_price = price.get("formatted", {}).get("price", "N/A")

            stock = product.get("stock", {})
            in_stock = stock.get("inStock", True)
            quantity = stock.get("quantity")

            product_type = product.get("productType", "physical")

            lines.append(f"  {status_emoji} *{name}* — {formatted_price}")
            stock_str = f"In Stock ({quantity})" if quantity is not None else ("In Stock" if in_stock else "Out of Stock")
            lines.append(f"     Type: {product_type} | {stock_str}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Cris] Products fetch error: {e}")
        return f"⚠️ Error fetching products: {str(e)[:200]}"


def query_cms_items(text):
    """Query items from a CMS collection."""
    try:
        # Extract collection name from text
        text_lower = text.lower().strip()
        text_lower = re.sub(r"^(?:cris|hey\s+cris|hi\s+cris)[,:\s]*", "", text_lower).strip()

        # Try to find collection name from the match
        collection_id = None
        for pattern in CRIS_ACTION_INTENTS["query_cms_items"]:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match and match.groups():
                collection_id = match.group(1).strip().strip('"\'')
                break

        if not collection_id:
            return "📋 Please specify a collection name. Example: 'Show items from Projects collection'"

        print(f"[Cris] Querying CMS collection: {collection_id}")

        data = _wix_post(
            "https://www.wixapis.com/wix-data/v2/items/query",
            data={
                "dataCollectionId": collection_id,
                "query": {
                    "paging": {"limit": 20},
                },
                "returnTotalCount": True,
            }
        )

        items = data.get("dataItems", [])
        total = data.get("pagingMetadata", {}).get("total", len(items))

        if not items:
            return f"📋 *No items found* in collection '{collection_id}'."

        lines = [f"📋 *CMS Collection: {collection_id}* — showing {len(items)} of {total}\n"]

        for item in items[:20]:
            item_data = item.get("data", {})
            item_id = item.get("id", "unknown")

            # Show first few meaningful fields
            display_fields = []
            for key, value in item_data.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, (str, int, float, bool)) and value:
                    display_fields.append(f"{key}: {str(value)[:60]}")
                if len(display_fields) >= 4:
                    break

            lines.append(f"  • ID: `{item_id[:12]}...`")
            for field in display_fields:
                lines.append(f"    {field}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Cris] CMS query error: {e}")
        return f"⚠️ Error querying CMS collection: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────

ACTION_MAP = {
    "list_sites": list_sites,
    "query_contacts": query_contacts,
    "list_blog_posts": list_blog_posts,
    "query_products": query_products,
    "query_cms_items": query_cms_items,
}


def handle_cris_action(text):
    """Main entry point: detect intent and execute action.
    Returns (handled: bool, response: str).
    """
    intent, match = detect_cris_intent(text)
    if intent and intent in ACTION_MAP:
        print(f"[Cris] Action intent detected: {intent} (matched: '{match.group(0)}')")
        result = ACTION_MAP[intent](text)
        return True, result
    return False, ""
