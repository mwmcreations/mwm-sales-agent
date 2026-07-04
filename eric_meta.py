"""
Eric Meta Ads Action Handlers — Real-time Slack action capability for Eric (Traffic Manager).

Handles:
- Get active campaigns (list running/active campaigns)
- Get campaign stats (performance metrics for a specific campaign)
- Pause campaign (pause an active campaign)
- Get ad account balance (check spending and balance)
- List ad sets (list ad sets, optionally for a campaign)

Uses META_ADS_TOKEN and META_AD_ACCOUNT_ID from Railway env vars.
Meta Marketing API v21.0 — https://developers.facebook.com/docs/marketing-apis
"""

import os
import re
import json
from datetime import datetime, timedelta

import requests as http_requests

# ── Config ──────────────────────────────────────────────────────────
META_ADS_TOKEN = os.getenv("META_ADS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")  # e.g. act_691911781413399
META_GRAPH_URL = "https://graph.facebook.com/v21.0"


def _meta_get(endpoint, params=None):
    """Make a GET request to Meta Graph API."""
    if not META_ADS_TOKEN:
        raise RuntimeError("META_ADS_TOKEN not configured")
    if params is None:
        params = {}
    params["access_token"] = META_ADS_TOKEN
    url = f"{META_GRAPH_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        error_body = resp.text[:500]
        print(f"[Eric] Meta API error {resp.status_code}: {error_body}")
        resp.raise_for_status()
    return resp.json()


def _meta_post(endpoint, data=None, params=None):
    """Make a POST request to Meta Graph API."""
    if not META_ADS_TOKEN:
        raise RuntimeError("META_ADS_TOKEN not configured")
    if data is None:
        data = {}
    if params is None:
        params = {}
    params["access_token"] = META_ADS_TOKEN
    url = f"{META_GRAPH_URL}/{endpoint.lstrip('/')}"
    resp = http_requests.post(url, params=params, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _account_id():
    """Return the ad account ID, ensuring it has the act_ prefix."""
    acct = META_AD_ACCOUNT_ID
    if not acct:
        raise RuntimeError("META_AD_ACCOUNT_ID not configured")
    if not acct.startswith("act_"):
        acct = f"act_{acct}"
    return acct


# ── Intent Detection ────────────────────────────────────────────────
ERIC_ACTION_INTENTS = {
    "get_active_campaigns": [
        r"(?:what|list|show|get|check|pull)\s+(?:active|running|current|live)\s+(?:campaigns?|ads?)",
        r"(?:what|which|list|show)\s+(?:campaigns?|ads?)\s+(?:are|is)\s+(?:active|running|live|on)",
        r"(?:active|running|live|current)\s+(?:campaigns?|ads?)",
        r"(?:list|show|get|what)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:campaigns?|ads?)(?:\s+(?:status|overview|summary|including|paused|inactive|archived))?",
        r"(?:are|is)\s+(?:there\s+)?(?:any\s+)?(?:campaigns?|ads?)\s+(?:running|active|live)",
        r"(?:what|which)\s+(?:ads?|campaigns?)\s+(?:do\s+we|are\s+we)\s+(?:have|running)",
    ],
    "get_campaign_stats": [
        r"(?:stats?|metrics?|performance|results?|numbers?|data)\s+(?:for|on|of)\s+(?:the\s+)?(?:campaign|ad)\s*[:\-]?\s*(.+)",
        r"(?:how|what)(?:'s|s| is| are| did)\s+(?:the\s+)?(.+?)\s+(?:campaign|ad)\s+(?:doing|performing|going)",
        r"(?:how|what)(?:'s|s| is| did)\s+(?:the\s+)?(?:campaign|ad)\s+(.+?)(?:\s+(?:doing|performing|going))?",
        r"(?:get|show|pull|check)\s+(?:stats?|metrics?|performance|results?)\s+(?:for|on)\s+(.+)",
        r"(?:campaign|ad)\s+(?:stats?|metrics?|performance|results?)\s+(?:for|on)\s+(.+)",
        r"(?:what|how)(?:'s|s| is| are)\s+(?:the\s+)?(?:open|click|conversion|spend|reach|impression|ctr|cpm|cpc)\s+(?:rate|count)?\s*(?:for|on)\s+(.+)",
    ],
    "pause_campaign": [
        r"(?:pause|stop|disable|turn\s+off|deactivate|halt)\s+(?:the\s+)?(?:campaign|ad)\s*[:\-]?\s*(.+)",
        r"(?:pause|stop|disable|turn\s+off|deactivate|halt)\s+(.+?)(?:\s+(?:campaign|ad))?$",
    ],
    "get_ad_account_balance": [
        r"(?:what|check|show|get)\s+(?:the\s+)?(?:ad\s+)?(?:account\s+)?(?:balance|spend|spending|budget|billing)",
        r"(?:how\s+much)\s+(?:have\s+we|did\s+we|are\s+we)\s+(?:spent?|spending)",
        r"(?:ad\s+)?account\s+(?:balance|spend|spending|budget|overview|status)",
        r"(?:total|daily|monthly)\s+(?:ad\s+)?spend",
        r"(?:billing|payment|budget)\s+(?:status|overview|summary)",
    ],
    "list_ad_sets": [
        r"(?:list|show|get|what)\s+(?:ad\s*sets?|ad\s+groups?)",
        r"(?:what|which)\s+(?:ad\s*sets?|ad\s+groups?)\s+(?:do\s+we|are|is)\s+(?:have|running|active)",
        r"(?:ad\s*sets?|ad\s+groups?)\s+(?:for|in|under)\s+(.+)",
        r"(?:ad\s*sets?|ad\s+groups?)\s+(?:list|overview|summary|status)",
    ],
}


def detect_eric_intent(text):
    """Detect if text contains an Eric action intent.
    Returns (intent, match) or (None, None).
    """
    text_lower = text.lower().strip()
    # Strip "eric" prefix if present
    text_lower = re.sub(r"^(?:eric|hey\s+eric|hi\s+eric)[,:\s]*", "", text_lower).strip()

    for intent, patterns in ERIC_ACTION_INTENTS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return intent, match
    return None, None


# ── Action Handlers ─────────────────────────────────────────────────

def get_active_campaigns(text):
    """List active/running campaigns from Meta Ads."""
    try:
        print("[Eric] Fetching active campaigns from Meta Marketing API...")
        acct = _account_id()

        # Fetch all campaigns (no filtering to avoid 400 errors with token scope)
        data = _meta_get(f"{acct}/campaigns", params={
            "fields": "name,status,objective,daily_budget,lifetime_budget,start_time,stop_time,created_time",
            "limit": 50,
        })

        all_campaigns = data.get("data", [])
        if not all_campaigns:
            return "📊 *No campaigns found* in this ad account."

        # Split by status
        active = [c for c in all_campaigns if c.get("status") == "ACTIVE"]
        paused = [c for c in all_campaigns if c.get("status") in ("PAUSED", "CAMPAIGN_PAUSED")]
        other = [c for c in all_campaigns if c.get("status") not in ("ACTIVE", "PAUSED", "CAMPAIGN_PAUSED")]
        campaigns = active + paused  # Show active and paused first

        if not campaigns:
            lines = [f"📊 *No active/paused campaigns right now.* Found {len(all_campaigns)} total:\n"]
            for c in all_campaigns[:15]:
                status_emoji = {"ACTIVE": "🟢", "PAUSED": "⏸️", "ARCHIVED": "📦"}.get(c.get("status", ""), "⚪")
                lines.append(f"  {status_emoji} *{c.get('name', '(unnamed)')}* — {c.get('status', 'unknown')}")
            return "\n".join(lines)

        active = [c for c in campaigns if c.get("status") == "ACTIVE"]
        paused = [c for c in campaigns if c.get("status") in ("PAUSED", "CAMPAIGN_PAUSED")]

        lines = [f"📊 *Campaigns Overview* — {len(campaigns)} found\n"]

        if active:
            lines.append(f"🟢 *Active:* {len(active)}")
            for c in active:
                name = c.get("name", "(unnamed)")
                obj = c.get("objective", "N/A")
                budget = c.get("daily_budget")
                budget_str = f" — ${int(budget)/100:.2f}/day" if budget else ""
                lines.append(f"  • *{name}* ({obj}){budget_str}")
                lines.append(f"    ID: {c.get('id', '?')}")

        if paused:
            lines.append(f"\n⏸️ *Paused:* {len(paused)}")
            for c in paused:
                name = c.get("name", "(unnamed)")
                obj = c.get("objective", "N/A")
                lines.append(f"  • *{name}* ({obj})")
                lines.append(f"    ID: {c.get('id', '?')}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Eric] Get active campaigns error: {e}")
        return f"⚠️ Error fetching campaigns: {str(e)[:200]}"


def get_campaign_stats(text):
    """Get performance stats for a campaign (by name or ID)."""
    try:
        print("[Eric] Fetching campaign stats from Meta Marketing API...")
        acct = _account_id()

        # Extract campaign name/ID from text
        text_clean = re.sub(
            r"^(?:eric[,:\s]*)?(?:get|show|pull|check|what|how)(?:'s|s| is| are| did)?\s*(?:the\s+)?(?:stats?|metrics?|performance|results?|numbers?|data)?\s*(?:for|on|of)?\s*(?:the\s+)?(?:campaign|ad)?\s*[:\-]?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()
        # Also strip trailing "campaign", "ad", "doing", "performing"
        text_clean = re.sub(r"\s+(?:campaign|ad|doing|performing|going)$", "", text_clean, flags=re.IGNORECASE).strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which campaign? Try: *Get stats for [campaign name]* or list campaigns first."

        # First get all campaigns to find by name
        data = _meta_get(f"{acct}/campaigns", params={
            "fields": "name,status,objective",
            "limit": 50,
        })
        campaigns = data.get("data", [])

        # Find matching campaign
        target = None
        search_lower = text_clean.lower()

        # Try exact ID match first
        for c in campaigns:
            if c.get("id") == text_clean:
                target = c
                break

        # Then fuzzy name match
        if not target:
            for c in campaigns:
                if search_lower in c.get("name", "").lower():
                    target = c
                    break

        # Broader word match
        if not target:
            search_words = [w for w in search_lower.split() if len(w) > 2]
            best_score = 0
            for c in campaigns:
                name_lower = c.get("name", "").lower()
                if search_words:
                    matches = sum(1 for w in search_words if w in name_lower)
                    score = matches / len(search_words)
                    if score > best_score and score >= 0.4:
                        best_score = score
                        target = c

        if not target:
            avail = ", ".join(c.get("name", "?") for c in campaigns[:10]) if campaigns else "none found"
            return f"🔍 Campaign *{text_clean}* not found.\n\n*Available campaigns:* {avail}"

        campaign_id = target["id"]
        campaign_name = target.get("name", "(unnamed)")

        # Get insights for this campaign (last 30 days)
        today = datetime.now().strftime("%Y-%m-%d")
        thirty_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            insights = _meta_get(f"{campaign_id}/insights", params={
                "fields": "impressions,reach,clicks,spend,cpc,cpm,ctr,actions,cost_per_action_type,frequency",
                "time_range": json.dumps({"since": thirty_ago, "until": today}),
            })
            stats = insights.get("data", [{}])[0] if insights.get("data") else {}
        except Exception:
            stats = {}

        if not stats:
            return (
                f"📊 *{campaign_name}*\n"
                f"• *Status:* {target.get('status', 'unknown')}\n"
                f"• *Objective:* {target.get('objective', 'N/A')}\n"
                f"• _No performance data available for the last 30 days._"
            )

        # Format stats
        impressions = int(stats.get("impressions", 0))
        reach = int(stats.get("reach", 0))
        clicks = int(stats.get("clicks", 0))
        spend = float(stats.get("spend", 0))
        cpc = float(stats.get("cpc", 0))
        cpm = float(stats.get("cpm", 0))
        ctr = float(stats.get("ctr", 0))
        frequency = float(stats.get("frequency", 0))

        # Extract conversions from actions
        conversions = 0
        actions = stats.get("actions", [])
        for action in actions:
            if action.get("action_type") in ("lead", "offsite_conversion", "onsite_conversion", "purchase"):
                conversions += int(action.get("value", 0))

        lines = [
            f"📊 *{campaign_name}* — Last 30 Days\n",
            f"• *Status:* {target.get('status', 'unknown')}",
            f"• *Objective:* {target.get('objective', 'N/A')}",
            f"",
            f"📈 *Performance:*",
            f"  • *Impressions:* {impressions:,}",
            f"  • *Reach:* {reach:,}",
            f"  • *Clicks:* {clicks:,}",
            f"  • *CTR:* {ctr:.2f}%",
            f"  • *Frequency:* {frequency:.1f}",
            f"",
            f"💰 *Spend:*",
            f"  • *Total Spend:* ${spend:,.2f}",
            f"  • *CPC:* ${cpc:.2f}",
            f"  • *CPM:* ${cpm:.2f}",
        ]

        if conversions > 0:
            cost_per = spend / conversions if conversions else 0
            lines.append(f"\n🎯 *Conversions:* {conversions:,} (${cost_per:.2f} each)")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Eric] Get campaign stats error: {e}")
        return f"⚠️ Error fetching campaign stats: {str(e)[:200]}"


def pause_campaign(text):
    """Pause an active Meta campaign."""
    try:
        print("[Eric] Pausing campaign via Meta Marketing API...")
        acct = _account_id()

        # Extract campaign name/ID
        text_clean = re.sub(
            r"^(?:eric[,:\s]*)?(?:pause|stop|disable|turn\s+off|deactivate|halt)\s+(?:the\s+)?(?:campaign|ad)?\s*[:\-]?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()
        text_clean = re.sub(r"\s+(?:campaign|ad)$", "", text_clean, flags=re.IGNORECASE).strip()

        if not text_clean or len(text_clean) < 2:
            return "🤔 Which campaign? Try: *Pause [campaign name]*"

        # Find the campaign
        data = _meta_get(f"{acct}/campaigns", params={
            "fields": "name,status",
            "limit": 50,
        })
        campaigns = data.get("data", [])

        target = None
        search_lower = text_clean.lower()

        for c in campaigns:
            if c.get("id") == text_clean:
                target = c
                break

        if not target:
            for c in campaigns:
                if search_lower in c.get("name", "").lower():
                    target = c
                    break

        if not target:
            avail = ", ".join(c.get("name", "?") for c in campaigns[:10]) if campaigns else "none"
            return f"🔍 Campaign *{text_clean}* not found.\n\n*Available:* {avail}"

        if target.get("status") == "PAUSED":
            return f"⏸️ Campaign *{target.get('name')}* is already paused."

        # Pause the campaign
        campaign_id = target["id"]
        _meta_post(campaign_id, data={"status": "PAUSED"})

        return (
            f"⏸️ *Campaign paused!*\n"
            f"• *Campaign:* {target.get('name', '(unnamed)')}\n"
            f"• *ID:* {campaign_id}\n"
            f"• *Previous Status:* {target.get('status', 'unknown')}\n"
            f"• Campaign is now paused and no longer serving ads."
        )
    except Exception as e:
        print(f"[Eric] Pause campaign error: {e}")
        return f"⚠️ Error pausing campaign: {str(e)[:200]}"


def get_ad_account_balance(text):
    """Get ad account balance and spending info."""
    try:
        print("[Eric] Fetching ad account balance from Meta Marketing API...")
        acct = _account_id()

        # Get account info
        account_data = _meta_get(acct, params={
            "fields": "name,account_status,currency,amount_spent,balance,spend_cap,funding_source_details"
        })

        name = account_data.get("name", "(unnamed)")
        status_map = {1: "Active", 2: "Disabled", 3: "Unsettled", 7: "Pending Review", 8: "Pending Closure", 9: "In Grace Period", 100: "Pending", 101: "Temporarily Unavailable"}
        status = status_map.get(account_data.get("account_status"), f"Unknown ({account_data.get('account_status')})")
        currency = account_data.get("currency", "USD")
        amount_spent = int(account_data.get("amount_spent", 0)) / 100  # Amount in cents
        balance = int(account_data.get("balance", 0)) / 100
        spend_cap = account_data.get("spend_cap")
        spend_cap_str = f"${int(spend_cap)/100:,.2f}" if spend_cap and spend_cap != "0" else "No cap"

        # Get recent spend (last 7 days)
        today = datetime.now().strftime("%Y-%m-%d")
        seven_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        try:
            insights = _meta_get(f"{acct}/insights", params={
                "fields": "spend,impressions,clicks",
                "time_range": json.dumps({"since": seven_ago, "until": today}),
            })
            recent = insights.get("data", [{}])[0] if insights.get("data") else {}
            recent_spend = float(recent.get("spend", 0))
            recent_impressions = int(recent.get("impressions", 0))
            recent_clicks = int(recent.get("clicks", 0))
        except Exception:
            recent_spend = 0
            recent_impressions = 0
            recent_clicks = 0

        lines = [
            f"💰 *Ad Account: {name}*\n",
            f"• *Status:* {status}",
            f"• *Currency:* {currency}",
            f"• *Total Spent (lifetime):* ${amount_spent:,.2f}",
            f"• *Balance:* ${balance:,.2f}",
            f"• *Spend Cap:* {spend_cap_str}",
        ]

        if recent_spend > 0:
            lines.append(f"\n📈 *Last 7 Days:*")
            lines.append(f"  • *Spend:* ${recent_spend:,.2f}")
            lines.append(f"  • *Impressions:* {recent_impressions:,}")
            lines.append(f"  • *Clicks:* {recent_clicks:,}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Eric] Get ad account balance error: {e}")
        return f"⚠️ Error fetching account balance: {str(e)[:200]}"


def list_ad_sets(text):
    """List ad sets, optionally filtered by campaign."""
    try:
        print("[Eric] Fetching ad sets from Meta Marketing API...")
        acct = _account_id()

        # Check if a campaign name is specified
        text_clean = re.sub(
            r"^(?:eric[,:\s]*)?(?:list|show|get|what)\s+(?:ad\s*sets?|ad\s+groups?)\s*(?:for|in|under)?\s*",
            "", text.strip(), flags=re.IGNORECASE
        ).strip().rstrip("?").strip()

        campaign_filter = None
        if text_clean and len(text_clean) > 2:
            # Try to find a campaign by name
            camp_data = _meta_get(f"{acct}/campaigns", params={
                "fields": "name,status",
                "limit": 50,
            })
            campaigns = camp_data.get("data", [])
            search_lower = text_clean.lower()
            for c in campaigns:
                if search_lower in c.get("name", "").lower():
                    campaign_filter = c
                    break

        if campaign_filter:
            # Get ad sets for specific campaign
            data = _meta_get(f"{campaign_filter['id']}/adsets", params={
                "fields": "name,status,daily_budget,lifetime_budget,targeting,optimization_goal,bid_strategy,start_time",
                "limit": 50,
            })
            ad_sets = data.get("data", [])
            header = f"📋 *Ad Sets for {campaign_filter.get('name', '?')}* — {len(ad_sets)} found\n"
        else:
            # Get all ad sets for account (no filtering to avoid token scope issues)
            data = _meta_get(f"{acct}/adsets", params={
                "fields": "name,status,campaign_id,daily_budget,lifetime_budget,optimization_goal,bid_strategy",
                "limit": 50,
            })
            ad_sets = data.get("data", [])
            header = f"📋 *Ad Sets* — {len(ad_sets)} found\n"

        if not ad_sets:
            return f"📋 *No ad sets found.* {'Try listing campaigns first.' if not campaign_filter else ''}"

        lines = [header]
        for ad_set in ad_sets:
            status_emoji = {"ACTIVE": "🟢", "PAUSED": "⏸️"}.get(ad_set.get("status", ""), "⚪")
            name = ad_set.get("name", "(unnamed)")
            budget = ad_set.get("daily_budget")
            budget_str = f" — ${int(budget)/100:.2f}/day" if budget else ""
            opt = ad_set.get("optimization_goal", "")
            opt_str = f" ({opt})" if opt else ""

            lines.append(f"  {status_emoji} *{name}*{budget_str}{opt_str}")
            lines.append(f"    ID: {ad_set.get('id', '?')}")

        return "\n".join(lines)
    except Exception as e:
        print(f"[Eric] List ad sets error: {e}")
        return f"⚠️ Error fetching ad sets: {str(e)[:200]}"


# ── Main Handler ────────────────────────────────────────────────────
_INTENT_HANDLERS = {
    "get_active_campaigns": get_active_campaigns,
    "get_campaign_stats": get_campaign_stats,
    "pause_campaign": pause_campaign,
    "get_ad_account_balance": get_ad_account_balance,
    "list_ad_sets": list_ad_sets,
}


def handle_eric_action(text):
    """Check if text matches an Eric action intent and execute it.
    Returns (handled: bool, response: str or None).
    """
    intent, match = detect_eric_intent(text)
    if intent and intent in _INTENT_HANDLERS:
        print(f"[Eric] Action intent detected: {intent} (matched: '{match.group(0)}')")
        handler = _INTENT_HANDLERS[intent]
        result = handler(text)
        return True, result

    return False, None


# ── S3b.2: Cold-lead retargeting audience (Sales Machine automation) ──
def add_to_custom_audience(phone, audience_id=None):
    """Add a phone number to the Meta cold-lead retargeting Custom Audience.

    Returns True on success, False on API failure, None when not configured
    (no META_COLD_AUDIENCE_ID env var) — callers treat None as a silent no-op.
    Phone is SHA256-hashed per Meta's user-data spec (normalized to digits
    with country code, no plus).
    """
    import hashlib
    import re as _re
    audience_id = audience_id or os.getenv("META_COLD_AUDIENCE_ID", "")
    if not audience_id:
        return None
    digits = _re.sub(r"\D", "", str(phone))
    if not digits:
        return False
    hashed = hashlib.sha256(digits.encode("utf-8")).hexdigest()
    try:
        result = _meta_post(
            f"{audience_id}/users",
            {
                "payload": {
                    "schema": ["PHONE_SHA256"],
                    "data": [[hashed]],
                }
            },
        )
        ok = bool(result) and not result.get("error")
        if not ok:
            print(f"[Eric] Custom audience add failed: {result}")
        return ok
    except Exception as e:
        print(f"[Eric] Custom audience add error: {e}")
        return False
