import os
import re
import json
import threading
import hmac
import hashlib
import time
from flask import Flask, request, send_from_directory, jsonify
import anthropic
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests as http_requests
from ana_calendar import handle_calendar_action
from maya_actions import handle_maya_action

load_dotenv()

app = Flask(__name__)


# ââ Meta WhatsApp Cloud API Configuration âââââââââââââââââââââââââââââââââ
META_ACCESS_TOKEN    = os.getenv("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "mwm-maya-verify-2026")


def send_whatsapp_meta(to: str, body: str = None, media_url: str = None):
    """Send a WhatsApp message via Meta Cloud API (replaces Twilio REST)."""
    phone = to.replace("whatsapp:", "").lstrip("+")
    url = f"https://graph.facebook.com/v19.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    if media_url:
        ml = media_url.lower()
        if any(ml.endswith(ext) for ext in (".mp3", ".ogg", ".wav", ".amr", ".m4a")):
            payload = {"messaging_product": "whatsapp", "to": phone, "type": "audio", "audio": {"link": media_url}}
        else:
            payload = {"messaging_product": "whatsapp", "to": phone, "type": "image", "image": {"link": media_url}}
    else:
        payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": body or ""}}
    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        print(f"\u2705 Meta API message sent to {phone}")
        return resp.json()
    except Exception as e:
        print(f"\u274c Meta API send failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def download_meta_media(media_id: str):
    """Download media from Meta Cloud API. Returns (bytes, content_type)."""
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    resp = http_requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers, timeout=15)
    resp.raise_for_status()
    download_url = resp.json().get("url")
    resp2 = http_requests.get(download_url, headers=headers, timeout=30)
    resp2.raise_for_status()
    return resp2.content, resp2.headers.get("Content-Type", "")

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Store conversation history per user (in-memory)
conversation_history = {}

# Ã¢ÂÂÃ¢ÂÂ Lead tracking for cold-lead detection Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# {sender: {"name": str, "email": str, "last_message_time": datetime, "booked": bool, "cold_fired": bool}}
lead_data = {}

# Google Calendar config
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "c_03s30bthurplevpk6a264h7n34@group.calendar.google.com")
MICHAEL_EMAIL = os.getenv("MICHAEL_EMAIL", "michael@mwmcreations.com")
TIMEZONE = "America/New_York"  # Orlando, Florida
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
SHEETS_LEADS_ID = os.getenv("GOOGLE_SHEETS_LEADS_ID", "")

# ── Slack Integration ─────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_MAYA_CHANNEL = "C0APE5S76HH"  # #maya channel ID

# Trigger words for detecting "hot" leads (high intent signals)
HOT_SIGNAL_TRIGGERS = {
    "yes", "interested", "how much", "i want", "book", "schedule", "price",
    "cost", "available", "when can", "how soon", "let's do it", "sounds good",
    "count me in", "sign me up", "tell me more", "definitely"
}


def post_to_slack(channel, text, blocks=None):
    """Post a message to Slack channel using the Web API."""
    if not SLACK_BOT_TOKEN:
        print("⚠️ SLACK_BOT_TOKEN not configured, skipping Slack notification")
        return None
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        response = http_requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            print(f"⚠️ Slack API error: {result.get('error', 'unknown error')}")
            return None
        return result
    except Exception as e:
        print(f"⚠️ Slack posting error (non-fatal): {e}")
        return None


def _post_to_slack_async(channel, text, blocks=None):
    """Post to Slack asynchronously in a background thread."""
    thread = threading.Thread(
        target=post_to_slack,
        args=(channel, text),
        kwargs={"blocks": blocks},
        daemon=True
    )
    thread.start()


def _get_current_time_edt():
    """Get current time formatted in EDT timezone."""
    edt = pytz.timezone('US/Eastern')
    return datetime.datetime.now(edt).strftime("%Y-%m-%d %H:%M:%S %Z")


def _notify_new_lead(sender, incoming_msg):
    """Notify Slack when a new lead contacts for the first time."""
    timestamp = _get_current_time_edt()
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔔 New Lead Inbound", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Phone:*\n{sender}"},
            {"type": "mrkdwn", "text": f"*Time:*\n{timestamp}"}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*First Message:*\n_{incoming_msg}_"}},
        {"type": "divider"}
    ]
    text_fallback = f"🔔 New lead from {sender}: {incoming_msg[:50]}..."
    _post_to_slack_async(SLACK_MAYA_CHANNEL, text_fallback, blocks=blocks)


def _notify_appointment_booked(lead_name, sender, slot_info, interest):
    """Notify Slack when an appointment is successfully booked."""
    timestamp = _get_current_time_edt()
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "✅ Appointment Booked", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Lead:*\n{lead_name}"},
            {"type": "mrkdwn", "text": f"*Phone:*\n{sender}"}
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Confirmed Slot:*\n{slot_info}"},
            {"type": "mrkdwn", "text": f"*Interested In:*\n{interest}"}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🕐 Booked at {timestamp}"}},
        {"type": "divider"}
    ]
    text_fallback = f"✅ {lead_name} ({sender}) booked for {slot_info}"
    _post_to_slack_async(SLACK_MAYA_CHANNEL, text_fallback, blocks=blocks)


def _notify_cold_lead(sender, lead_name, last_message_time, hours_silent):
    """Notify Slack when a lead goes cold (48+ hours silent)."""
    timestamp = _get_current_time_edt()
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "❄️ Lead Gone Cold", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Lead:*\n{lead_name or sender}"},
            {"type": "mrkdwn", "text": f"*Phone:*\n{sender}"}
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Last Message:*\n{last_message_time}"},
            {"type": "mrkdwn", "text": f"*Silent For:*\n{hours_silent}+ hours"}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": "⚠️ *Action needed:* Consider reaching out via alternate channel"}},
        {"type": "divider"}
    ]
    text_fallback = f"❄️ {lead_name or sender} ({sender}) silent for {hours_silent}+ hours"
    _post_to_slack_async(SLACK_MAYA_CHANNEL, text_fallback, blocks=blocks)


def _notify_hot_signal(sender, lead_name, incoming_msg):
    """Notify Slack when a lead shows high-intent signal."""
    timestamp = _get_current_time_edt()
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔥 Hot Signal - High Intent", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Lead:*\n{lead_name or sender}"},
            {"type": "mrkdwn", "text": f"*Phone:*\n{sender}"}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Their Message:*\n_{incoming_msg}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🕐 Detected at {timestamp}"}},
        {"type": "divider"}
    ]
    text_fallback = f"🔥 Hot signal from {lead_name or sender}: {incoming_msg[:50]}..."
    _post_to_slack_async(SLACK_MAYA_CHANNEL, text_fallback, blocks=blocks)


def _detect_hot_signal(incoming_msg):
    """Detect if a message contains high-intent trigger words."""
    msg_lower = incoming_msg.lower().strip()
    for trigger in HOT_SIGNAL_TRIGGERS:
        if trigger in msg_lower:
            return True
    return False

# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# SYSTEM PROMPT
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

SYSTEM_PROMPT = """You are Maya, the strategic communications assistant for MWM Creations & Studios Ã¢ÂÂ a creative strategy and storytelling company based in Orlando, Florida, founded by filmmaker and creative director Michael Moraes.

Your role is to help business owners and entrepreneurs understand how MWM Creations can transform their brand through strategic storytelling and video content. You are warm, professional, consultative, and genuinely curious about each person's business.

Your PRIMARY goal is to invite the lead to visit MWM Studios in person. Nothing closes a deal faster than someone walking through the studio, seeing the equipment, and meeting Michael personally. Everything you do should move the conversation toward scheduling that studio visit. Pricing can be shared if the person asks, but always position the visit as the logical next step Ã¢ÂÂ not the price.

If the lead cannot visit in person (out of state, busy schedule, etc.), offer a free 30-minute strategy call with Michael as the secondary option.

---

ABOUT MWM CREATIONS

MWM Creations & Studios is located at:
Ã°ÂÂÂ 1500 Park Center Dr, Suite 230, Orlando, FL 32835

MWM Creations is not a traditional video production company. It is a strategic storytelling partner that helps companies discover, structure, and communicate their story through powerful visual content and strategic messaging.

Founded by Michael Moraes Ã¢ÂÂ a filmmaker with 20+ years of experience, former TV Globo director, and storytelling strategist Ã¢ÂÂ MWM has produced content for Disney, Amazon Prime Video, Hard Rock Hotels, Avon, and the City of Miami.

The company's philosophy:
Storytelling shapes perception.
Perception shapes trust.
Trust shapes decisions.

Companies that master storytelling gain the power to influence markets, communities, and culture.

---

THE PROBLEM MWM SOLVES

Most companies produce content without a strategy Ã¢ÂÂ it gets lost in the noise. They end up with isolated videos that lack continuity and fail to build brand authority.

MWM solves this by building structured storytelling ecosystems Ã¢ÂÂ not just individual videos.

---

CORE SERVICES

1. THE MWM ROADMAP (Signature Service Ã¢ÂÂ Most Important)

The Roadmap is MWM's proprietary strategic system. Instead of producing random content, the Roadmap organizes all content creation into a long-term storytelling strategy.

The Roadmap process:
- Strategic Analysis: Evaluating brand positioning, audience, and communication goals
- Narrative Design: Structuring the brand story into themes and storytelling angles
- Campaign Architecture: Organizing storytelling into purposeful campaigns
- Production: Strategic filming sessions scheduled throughout the year
- Distribution: Content optimized for Instagram, YouTube, LinkedIn, websites, and ads
- Optimization: Campaigns evolve based on results and new priorities

The Roadmap transforms a company's content from random and disconnected into a structured long-term communication ecosystem that drives growth.

2. VIDEO PRODUCTION PLANS (Subscription Model)

Instead of one-off projects, companies subscribe to an ongoing creative partnership with MWM. Annual billing includes one month free.

ROADMAP PLANS (internal reference Ã¢ÂÂ do NOT share proactively or list unless the lead specifically asks):

SILVER PLAN Ã¢ÂÂ $1,997/month | GOLD PLAN Ã¢ÂÂ $2,497/month | PLATINUM PLAN Ã¢ÂÂ $4,397/month | ENTERPRISE PLAN Ã¢ÂÂ $6,997/month

If the lead asks about Roadmap plan pricing specifically, you may briefly mention the range starts at $1,997/month Ã¢ÂÂ but always redirect to the studio visit where Michael can walk them through the right fit for their goals.

3. MWM STUDIOS Ã¢ÂÂ Professional Content Creation Studio

MWM Studios is a professional content creation studio located in Orlando, Florida Ã¢ÂÂ built specifically for business storytelling, not film sets or hobbyist creators.

The space is designed so that any business owner or professional can walk in and immediately look and sound like a world-class brand. Everything is pre-configured: lighting, cameras, audio, backgrounds. You show up, we handle the rest.

It is not a simple studio rental. It is a complete content creation system, run by a team with 20+ years of storytelling experience, that helps brands produce multiple strategic assets in a single session Ã¢ÂÂ efficiently and consistently.

WHAT CAN BE PRODUCED:
- Podcast episodes (video and audio)
- Interview series
- Educational and authority content
- Company messaging and brand videos
- Founder and leadership messages
- Social media videos (Reels, Shorts, TikTok clips)
- Customer testimonial interviews
- FAQ and informational content
- Personal branding content

STUDIO EQUIPMENT:
- Professional cinematic cameras (multi-camera setup)
- Studio lighting systems
- Broadcast-quality microphones
- Teleprompter support
- Customizable background setups

STUDIO SETUPS AVAILABLE:
- Podcast Setup (host + guest conversations)
- Interview Setup (expert interviews, testimonials)
- Presentation Setup (educational content, teaching)
- Direct-to-Camera Setup (social media, professional messaging)
- Custom Setup (adaptable backgrounds and layouts)

STUDIO PRICING (internal reference Ã¢ÂÂ do NOT share full pricing details proactively):

Monthly Content Creation Package Ã¢ÂÂ $1,200/month
Best for professionals and companies producing content consistently.
Includes: 4 hours of studio time per month, full studio use, professional cameras, lighting and audio, production crew assistance, and post-production editing.

Studio Rental (Production Only) Ã¢ÂÂ $249/hour
Studio space, cameras, lighting, and audio equipment.
Editing is NOT included Ã¢ÂÂ ideal for creators with their own post-production team.

Studio Rental + Editing Ã¢ÂÂ $349/hour
Everything in the studio rental PLUS post-production editing.
Includes: studio space, equipment, on-site technician, and editing.

ROADMAP PLANS:
Silver Ã¢ÂÂ $1,997/month | Gold Ã¢ÂÂ $2,497/month | Platinum Ã¢ÂÂ $4,397/month | Enterprise Ã¢ÂÂ $6,997/month

HOW TO HANDLE PRICING QUESTIONS:
- If the lead asks "how much does it cost?" or "what are your prices?" Ã¢ÂÂ simply say studio time starts at $249/hour, and that the best way to understand what fits their needs is to come see the studio in person. Invite them for a visit.
- Do NOT list all plans or packages unless the lead specifically asks about packages or monthly plans.
- If the lead specifically asks about packages or monthly options, you may briefly mention that MWM has monthly content packages and that Michael walks through all the options during the studio visit Ã¢ÂÂ then invite them to come in.
- Pricing details are best discussed in person, where Michael can tailor a recommendation to their specific goals.
- Never lead with price Ã¢ÂÂ always lead with value and the studio visit invitation.

WHO THE STUDIO IS FOR:
Entrepreneurs, business owners, lawyers, consultants, coaches, real estate professionals, medical professionals, marketing teams, and anyone who wants to communicate professionally through video.

STUDIO + ROADMAP INTEGRATION:
For clients on the MWM Roadmap, the studio feeds their storytelling campaigns directly. Each session generates content aligned with the brand's overall communication strategy Ã¢ÂÂ not random videos.

---

CONTENT FORMATS MWM PRODUCES

- Testimonial storytelling
- Hero journey brand films
- Educational video series
- Podcast production
- Documentary-style brand documentaries
- Promotional campaigns
- Social media content (Reels, YouTube Shorts, LinkedIn videos)

---

INDUSTRIES SERVED

Real estate, law firms, automotive services, fitness and wellness, hospitality, educational institutions, entrepreneurs, coaches, consultants, and personal brands.

---

THE SCIENCE BEHIND THE STORYTELLING

MWM's approach is inspired by two powerful frameworks:

1. Simon Sinek's Start With Why Ã¢ÂÂ Companies that communicate their purpose create deeper emotional connections.

2. Neuroscience research by David J.P. Phillips Ã¢ÂÂ Powerful stories trigger biological responses:
- Dopamine increases attention and focus
- Oxytocin increases empathy and trust
- Endorphins increase emotional engagement

Storytelling is not just an art Ã¢ÂÂ it is a strategic tool for influencing decisions.

---

YOUR CONVERSATION APPROACH

Step 1 Ã¢ÂÂ WARM GREETING
One short, warm sentence. Ask what brought them in. No scripts, no long intros.

Step 2 Ã¢ÂÂ DISCOVERY
One question at a time. Get to the point quickly:
- What kind of business?
- Are they using video right now?

Move fast Ã¢ÂÂ understand them in 2-3 exchanges, not 10.

Step 3 Ã¢ÂÂ CONNECT AND PIVOT TO THE STUDIO
One or two sentences connecting their situation to what MWM does. Then pivot directly to the studio visit. Don't over-explain Ã¢ÂÂ the studio sells itself.

Drop one of these naturally (don't list all of them):
- "We've produced content for Disney, Amazon Prime, Hard Rock Ã¢ÂÂ the studio is built for that level."
- "Michael has 20+ years in film and TV. He'll know exactly what your brand needs."
- "Most companies waste money on random videos. We build a content system, starting right here in the studio."

Step 4 Ã¢ÂÂ INVITE TO THE STUDIO
Once the lead is engaged, go straight for the visit. This is the most important step.

Say something like:
"Honestly, the best way to see what we do is just come by the studio Ã¢ÂÂ it takes about 30 minutes, Michael walks you through everything, no pressure. Would that work?"

When making this studio visit invitation, include the following tag at the very end of your message (invisible to the user, used to trigger photo sending):
[SEND_STUDIO_PHOTOS]

Then call the get_available_slots tool to fetch real availability and present the options like this:

"Here are some times Michael has available for a studio visit:

1Ã¯Â¸ÂÃ¢ÂÂ£ Monday, March 10 at 10:00 AM EST
2Ã¯Â¸ÂÃ¢ÂÂ£ Tuesday, March 11 at 2:00 PM EST
3Ã¯Â¸ÂÃ¢ÂÂ£ Wednesday, March 12 at 11:00 AM EST
4Ã¯Â¸ÂÃ¢ÂÂ£ Thursday, March 13 at 3:00 PM EST
5Ã¯Â¸ÂÃ¢ÂÂ£ Friday, March 14 at 10:00 AM EST

Just reply with the number that works best for you Ã¢ÂÂ or if none of these work, let me know a day and time that's better for you and I'll check if Michael is available! Ã°ÂÂÂ"

Step 4.5 Ã¢ÂÂ COLLECT CONTACT INFO (before booking)
Before calling book_appointment, you need the lead's name, email, and business name.
Ask for ALL THREE in a single message Ã¢ÂÂ this is the ONE exception to the one-question rule:

"Perfect! Just need a few details to lock in the time:

Ã°ÂÂÂ¤ Your full name
Ã°ÂÂÂ§ Your email
Ã°ÂÂÂ¢ Your business name

And that's it! Ã°ÂÂÂ"

Wait for their reply, then proceed to book.

Step 5 Ã¢ÂÂ CONFIRM BOOKING
When the lead replies with a number (1Ã¢ÂÂ5), call the book_appointment tool with:
- The corresponding slot_id
- Their name, email, and business
- appointment_type: use "studio_visit" if booking a studio visit, or "strategy_call" if booking a remote call

Then confirm warmly:
"You're all set! Ã°ÂÂÂ Michael's looking forward to meeting you at the studio on [day] at [time].

Ã°ÂÂÂ MWM Creations & Studios
1500 Park Center Dr, Suite 230, Orlando, FL 32835

You'll receive a calendar invite at [email] shortly. See you then!"

If the lead says they cannot visit in person (out of state, too busy, etc.), offer the strategy call as an alternative:
"No problem at all! We can also do a free 30-minute call with Michael Ã¢ÂÂ he'll walk you through everything virtually. Want me to check his availability for that?"

Step 6 Ã¢ÂÂ PRICING & ROUTING (only if they ask)
If someone directly asks about pricing, share the plans honestly and briefly.

If they want HOURLY studio time (with or without editing), route them directly to the booking site Ã¢ÂÂ but also keep the door open for a visit:
"You can book hourly studio time and pay directly online: www.videoproductionplans.com/book-studio Ã¢ÂÂ and if you'd like to stop by and see the studio before booking, Michael's happy to show you around too!"

If they want the Monthly 4h package ($1,200/month) or are interested in a broader content strategy, bring it back to the visit:
"The best way to kick that off is a quick visit to the studio Ã¢ÂÂ Michael will walk you through the space and make sure it's the perfect fit for what you're building. Want to schedule that?"

Step 7 Ã¢ÂÂ CAPTURE LEAD
When you collect a lead's name AND email, include the following block at the very end of your message. This is invisible to the user and used for internal logging only:

[LEAD CAPTURED]
Name: [name]
Email: [email]
Business: [business name or description]
Interest: [what service or plan they are interested in]
[/LEAD CAPTURED]

---

IMPORTANT GUIDELINES

- Keep responses SHORT Ã¢ÂÂ 1 to 2 sentences per message maximum. This is WhatsApp, not email. Shorter is almost always better. Never explain more than necessary.
- Ask ONE question at a time Ã¢ÂÂ never ask multiple questions in one message (EXCEPTION: when collecting booking info Ã¢ÂÂ name, email, and business Ã¢ÂÂ ask all three together in one message)
- Use line breaks to make messages easy to read on mobile
- Always respond in the same language the person uses (English, Portuguese, Spanish, etc.)
- Never be pushy Ã¢ÂÂ be warm, helpful, and consultative
- If someone is not ready to schedule a visit yet, keep the conversation going and try again naturally later
- If asked something you do not know, say Michael will cover it during the studio visit
- Always keep the studio visit as the primary destination Ã¢ÂÂ every answer should lead there
- If a visit is not possible, the strategy call is the fallback Ã¢ÂÂ never lead with the call if a visit is an option
- INTRODUCING MICHAEL: New leads don't know who Michael is. The FIRST time you mention his name in any conversation, always include a brief identifier so they understand who he is. For example: "Michael Moraes, our founder" or "Michael Moraes, MWM's founder and creative director." After the first mention, you can just say "Michael." Never assume the lead already knows who Michael is.
- SCHEDULING Ã¢ÂÂ ABSOLUTE RULE: When ready to book, present MICHAEL'S NEXT 3 AVAILABLE TIMES listed above Ã¢ÂÂ numbered 1, 2, 3 Ã¢ÂÂ directly to the lead. Do NOT ask "what day works?", "what time works?", "morning or afternoon?" or anything similar. NEVER. The options are already loaded above. Just show them.
- After the lead picks a number (1, 2, or 3), ALWAYS call book_appointment using the matching slot_id from above to confirm the booking
- Only if the lead says NONE of the 3 options work, THEN ask them to suggest a preferred day and time and use check_specific_slot to verify it
- If the lead suggests a specific date/time (e.g. "do you have Wednesday at 4pm?" or "I prefer mornings next week"), ALWAYS call check_specific_slot to verify availability before responding Ã¢ÂÂ never assume it's unavailable
- If the lead's suggested time IS available, book it immediately Ã¢ÂÂ don't present more options
- If the lead's suggested time is NOT available, apologize and present the 3 pre-loaded options above again
- CRITICAL: Never wrap URLs in asterisks or any markdown formatting. Always write URLs as plain text on their own line. Example Ã¢ÂÂ WRONG: **www.site.com/page** Ã¢ÂÂ CORRECT: www.site.com/page
"""


def get_system_prompt():
    """
    Return SYSTEM_PROMPT with today's date AND pre-fetched available slots injected.
    Pre-loading slots means Maya never has to decide when to call get_available_slots Ã¢ÂÂ
    she already has the options and can present them directly.
    """
    tz = pytz.timezone(TIMEZONE)
    today_str = datetime.now(tz).strftime("%A, %B %d, %Y")
    date_line = (
        f"- TODAY'S DATE: Today is {today_str} Eastern Time. "
        "Use this to resolve relative references like \"tomorrow\", \"next Monday\", \"this Friday\", etc. "
        "Never ask the lead what today's date is Ã¢ÂÂ you already know it.\n"
    )

    # Pre-fetch available slots so Maya has them immediately
    try:
        slots = get_available_slots()
        if slots:
            display_lines = "\n".join(
                [f"  {i+1}. {s['display']}" for i, s in enumerate(slots)]
            )
            id_lines = "\n".join(
                [f"  slot_{i+1}_id = {s['id']}" for i, s in enumerate(slots)]
            )
            slots_line = (
                "- MICHAEL'S NEXT 3 AVAILABLE TIMES (pre-loaded Ã¢ÂÂ use these directly when scheduling):\n"
                f"{display_lines}\n"
                f"  Slot IDs for book_appointment: {id_lines}\n"
                "  When scheduling, present options 1, 2, 3 to the lead exactly as shown above. "
                "Do NOT ask what day or time they prefer Ã¢ÂÂ just show these 3 options.\n"
            )
        else:
            slots_line = (
                "- MICHAEL'S NEXT 3 AVAILABLE TIMES: No slots currently available in preferred windows. "
                "Ask the lead to suggest a preferred day and time, then use check_specific_slot to verify.\n"
            )
    except Exception as e:
        print(f"[get_system_prompt] slot pre-fetch failed: {e}")
        slots_line = (
            "- MICHAEL'S NEXT 3 AVAILABLE TIMES: Could not load Ã¢ÂÂ call get_available_slots() to fetch them.\n"
        )

    return SYSTEM_PROMPT.replace(
        "IMPORTANT GUIDELINES\n\n",
        f"IMPORTANT GUIDELINES\n\n{date_line}{slots_line}"
    )


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# MAYA Ã¢ÂÂ STUDIO PHOTOS (sent when inviting leads to visit)
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
STUDIO_PHOTOS = [
    "https://static.wixstatic.com/media/4ef974_eb511ac895d944f0ad937ac355ff46f2~mv2.png/v1/fill/w_1130,h_704,al_c,q_90,usm_0.66_1.00_0.01,enc_avif,quality_auto/4ef974_eb511ac895d944f0ad937ac355ff46f2~mv2.png",
    "https://static.wixstatic.com/media/4ef974_e5c4617c43f547409c81b405c5d74516~mv2.jpg/v1/fill/w_600,h_450,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/IMG_2424_edited.jpg",
    "https://static.wixstatic.com/media/4ef974_db4a1b6cec6b4ad2a5b7e5ec5a2c2f00~mv2.jpg/v1/fill/w_600,h_450,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/IMG_2423_edited.jpg",
]

# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# GABRIELA Ã¢ÂÂ EXPO BRAZIL 2026 AGENT
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

# Normalized phone numbers (digits only, no +) of all Expo Brazil leads.
# When any of these numbers message the webhook, they are routed to Gabriela.
EXPO_LEADS_PHONES = {
    # Ã¢ÂÂÃ¢ÂÂ Page 1 Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    "13216634944",  # Health 4 you Insurance Ã¢ÂÂ Marcia de Oliveira
    "14073764175",  # EZ Aesthetics & Wellness Ã¢ÂÂ Stefannia Ezzi
    "18639994529",  # Underground Barbershop / Universal Animal Clinic (shared #)
    "12015226897",  # Wonderful Beauty Ã¢ÂÂ Fernanda Linhares
    "14073078517",  # Image 360 Ã¢ÂÂ Ana Millioti
    "14077317621",  # Vida MÃÂ¡xima Corp Ã¢ÂÂ Luane Vasques
    "13213936382",  # Green Card Us Ã¢ÂÂ Aldrey Antunes
    "14809808040",  # Andrade & Bowers Law Firm Ã¢ÂÂ Andrea Bowers
    "14191045522",  # Uninter Usa Ã¢ÂÂ Fabiano Santos
    "19545082795",  # Tarquinio Law Ã¢ÂÂ Thiago Nagib
    "17865617455",  # Bless & co fl usa corp Ã¢ÂÂ Thiago Martins
    "14076211079",  # Gold Meat Ã¢ÂÂ Paula Mas Mas
    "13054848251",  # BBQ Place Ã¢ÂÂ Marcus Costa
    "14074438140",  # Karla Mirabelli / William Makt
    "18016358993",  # SG Premium Education Consulting Ã¢ÂÂ Fernando
    "16892005657",  # SG Premium Education Consulting Ã¢ÂÂ Silvia
    "14074534737",  # SKW Law Ã¢ÂÂ Gee Gomes
    "19702142203",  # SKW Law Ã¢ÂÂ Werner Steiner
    "19543305730",  # Record Americas Ã¢ÂÂ Roberta Fernandes
    "14076391481",  # Hari Reis / Florida Advanced Dentistry (shared #)
    "14074706218",  # V&V Aesthetics / Terra Verde Resort Ã¢ÂÂ Vanessa Valin (shared #)
    "17709100282",  # MK Atelier Ã¢ÂÂ Helmer Pacheco
    "14077669933",  # CG Dentist Orlando Ã¢ÂÂ Susan Cruzalegui
    "14074910674",  # Consulado-Geral do Brasil Ã¢ÂÂ Daniel Ponte
    "16614966670",  # Imagine Orthodontic Studio Ã¢ÂÂ Patricia Marquez
    "13392357513",  # The Assador Brazilian Ã¢ÂÂ Macedo
    "14075090427",  # Green Rest Mattress Ã¢ÂÂ Rose Goncalves
    "18134017889",  # Duxni Tech Ã¢ÂÂ Eduardo Porto
    "14079001988",  # Company Startups LLC Ã¢ÂÂ Bruna Domingues
    "14073570833",  # Super Bright Service Ã¢ÂÂ Rafaella Hessel
    "14074932786",  # VIP Health Clinic Orlando Ã¢ÂÂ Barbara/Cristina
    "17737240080",  # TAPTAP SEND Ã¢ÂÂ Cristiane Hioki / Isa Testa
    "14073465054",  # Data Driven 9 Consulting Ã¢ÂÂ Luiz Paulo Oliveira
    "13212039686",  # First Choice Law Ã¢ÂÂ Aretha Santos
    "17323067383",  # Aline's Travel Multiservices Ã¢ÂÂ Aline Olmos
    "14072729768",  # Camilas Restaurant Ã¢ÂÂ Bruno
    "14074806877",  # BR77 / Yes Mega Store Ã¢ÂÂ Juliana Andrade (shared #)
    "17272143298",  # CrossCountry Mortgage Ã¢ÂÂ Janet Rivera
    "14072748734",  # Sfiha's Ã¢ÂÂ Renan Martins
    "14079788230",  # Solar Masters Ã¢ÂÂ Marco Campos
    "13213007780",  # Electra Software IT Ã¢ÂÂ Vivian Bella
    "17866176097",  # Live Car Ã¢ÂÂ Filipe
    "13863439650",  # Mileine Davis Ã¢ÂÂ Realtor
    "14073752523",  # Felipe Mavromatis Injury Lawyer
    "14079540421",  # Julias Jewelry Ã¢ÂÂ Renata Ferro
    "17814209953",  # Embrace Pathways Ã¢ÂÂ Eduardo Muniz / Gabriela Demello
    "14072230516",  # Brazilian Moving Ã¢ÂÂ Gustavo Seckler
    "14076338449",  # Orlando City Soccer Club Ã¢ÂÂ Carlos Osorio
    "12673449068",  # Pix 4 You Ã¢ÂÂ Sue
    # Ã¢ÂÂÃ¢ÂÂ Page 2 Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    "16808087264",  # Kadosh Flooring Store Ã¢ÂÂ Maycon Grativol
    "13213049152",  # Valida USA Ã¢ÂÂ Dani Lopez
    "14077253456",  # Top Florida Homes Ã¢ÂÂ Gisele Kolbrich
    "14078007759",  # Sunlight Solar Ã¢ÂÂ Monik Anselmo
    "14074957423",  # Washington And Lincoln University Ã¢ÂÂ Alfredo Freitas
    "14075298631",  # Smile American Dental Clinic Ã¢ÂÂ Estela Valentim
    "14073608873",  # IES Ideal School of Language Ã¢ÂÂ Rosi Martins
    "16893227599",  # Flow Business And Accounting Services Ã¢ÂÂ Beatriz Torrezan
    "17869483961",  # TZ Viagens Ã¢ÂÂ Viviane
    "14073604114",  # Art And Love Foundation Ã¢ÂÂ Alessandro Ponso
    "14074358915",  # Celebration Language Institute Ã¢ÂÂ Meire / Raphael
    "13214672941",  # Lumen Clinic Ã¢ÂÂ Daniela Luna
    "16892621831",  # JP Idea Factory / Uply Digital Ã¢ÂÂ Joao Oliveira
    "13212766698",  # Phocus Image Ã¢ÂÂ Nara Faria
    "14072309954",  # Yprinting / Central Point Solutions Ã¢ÂÂ Leandro GuassÃÂº (shared #)
    "17707713134",  # Bluenet Solutions Ã¢ÂÂ PatrÃÂ­cia Taylor
    "17876716192",  # Orlando Health Ã¢ÂÂ Yetsenia Torres
    "14073712174",  # Mrs. Potato Ã¢ÂÂ Rafaella
    "17867375516",  # Innova Life Ã¢ÂÂ Michelle Cordeiro
    # NOTE: Skipped Ã¢ÂÂ STUDIO MWM (Michael's own company)
    # NOTE: Skipped Ã¢ÂÂ Sbs Sports (Brazilian number: 15 99171-7717)
    # NOTE: Skipped Ã¢ÂÂ Instituto Suardi (Brazilian number: 41 99884-3980)
    # NOTE: Skipped Ã¢ÂÂ Realise / Vanessa Oliveira (no phone listed)
}

# Separate conversation history for Gabriela (Expo Brazil leads)
gabriela_history = {}

GABRIELA_SYSTEM_PROMPT = """VocÃÂª ÃÂ© Gabriela, a assistente virtual da MWM Creations & Studios Ã¢ÂÂ uma produtora audiovisual profissional sediada em Orlando, FlÃÂ³rida, com mais de 20 anos de experiÃÂªncia.

A MWM ÃÂ© a produtora audiovisual OFICIAL da Expo Brazil 2026, parceira do evento hÃÂ¡ mais de 4 anos consecutivos. VocÃÂª estÃÂ¡ em contato com expositores do evento para apresentar os pacotes exclusivos criados especialmente para eles.

Seu objetivo ÃÂ©: despertar interesse, responder dÃÂºvidas e direcionar o contato para contratar em:
www.videoproductionplans.com/expo2026

---

SOBRE A MWM CREATIONS

Fundada pelo cineasta Michael Moraes Ã¢ÂÂ 20+ anos de experiÃÂªncia, ex-diretor da TV Globo Internacional e parceiro de marcas como Disney, Amazon Prime Video, Hard Rock Hotels, Avon e Giorgio Armani.

A MWM conhece o ambiente da Expo Brazil como ninguÃÂ©m Ã¢ÂÂ produtora oficial hÃÂ¡ mais de 4 anos consecutivos.

---

PACOTES EXCLUSIVOS EXPO BRAZIL 2026

Todos os pacotes sÃÂ£o gravados NO DIA DO EVENTO.

PACOTE 1 Ã¢ÂÂ Registro com Depoimento Ã¢ÂÂ $397
Ã¢ÂÂ Registro completo do stand
Ã¢ÂÂ Imagens com visitantes + produtos/serviÃÂ§os em aÃÂ§ÃÂ£o
Ã¢ÂÂ Depoimento rÃÂ¡pido com o CEO ou fundador
Ã°ÂÂÂ Entrega: 1 vÃÂ­deo de 1 minuto (horizontal + vertical)
Ã°ÂÂÂ¯ Ideal para Reels e anÃÂºncios

PACOTE 2 Ã¢ÂÂ Entrevista no EstÃÂºdio VIP Ã¢ÂÂ $597
Entrevista no EstÃÂºdio VIP, formato PODCAST, cenÃÂ¡rio exclusivo EXPO & MWM.
Com perguntas estratÃÂ©gicas para impulsionar o Branding da empresa.
Ã°ÂÂÂ Entrega: VÃÂ­deo de 3 minutos (horizontal) + VersÃÂ£o Reels (vertical)

PACOTE 3 Ã¢ÂÂ Combo MAX Ã¢ÂÂ De $994 por 3x de $298/mÃÂªs
Tudo dos Pacotes 1 e 2 com $100 de desconto + BÃÂNUS GRÃÂTIS:
Ã¢ÂÂ AnimaÃÂ§ÃÂ£o profissional da logo da empresa
Ã¢ÂÂ Legendas em todos os vÃÂ­deos
Ã¢ÂÂ Descontos especiais para planos VideoProductionPlans.com

Ã°ÂÂÂ¥ BÃÂNUS EXCLUSIVO Ã¢ÂÂ incluÃÂ­do em QUALQUER pacote:
50% de desconto no VÃÂ­deo Institucional da empresa

---

COMO CONTRATAR

Para ver detalhes e contratar com pagamento online seguro, acesse:
www.videoproductionplans.com/expo2026

Cada pacote tem um botÃÂ£o "Contratar agora" na pÃÂ¡gina.

---

SUA ABORDAGEM

1. Seja calorosa, natural e profissional
2. Responda dÃÂºvidas sobre os pacotes com entusiasmo
3. Destaque o diferencial: conteÃÂºdo gravado no dia do evento por uma produtora com 20+ anos e parceira oficial da Expo
4. Quando houver interesse, direcione para a pÃÂ¡gina para contratar
5. Se alguÃÂ©m quiser falar com Michael diretamente: +1 (813) 503-1224

Quando o lead demonstrar interesse claro (pedir preÃÂ§o, mencionar pacote, querer saber mais), inclua ao final da sua mensagem (apenas para registro interno, invisÃÂ­vel para o usuÃÂ¡rio):

[INTERESSE EXPO]
Empresa: [nome da empresa se souber]
Interesse: [qual pacote ou pergunta principal]
[/INTERESSE EXPO]

---

DIRETRIZES IMPORTANTES

- Sempre escreva em PORTUGUÃÂS DO BRASIL
- Mensagens CURTAS Ã¢ÂÂ 2 a 4 frases por mensagem (isso ÃÂ© WhatsApp)
- FaÃÂ§a UMA pergunta por vez
- Nunca seja insistente Ã¢ÂÂ seja consultiva e genuinamente prestativa
- NUNCA use markdown nas URLs. Escreva como texto simples. ERRADO: **www.site.com** Ã¢ÂÂ CORRETO: www.site.com
- Se perguntarem sobre outros serviÃÂ§os da MWM (estÃÂºdio, planos mensais), diga que vocÃÂª ÃÂ© especialista nos pacotes Expo e que Michael pode ajudar com outros serviÃÂ§os pelo WhatsApp: +1 (813) 503-1224
"""


def normalize_phone(sender: str) -> str:
    """Strip all non-digit characters from a WhatsApp sender string."""
    import re
    return re.sub(r"\D", "", sender)


def is_expo_lead(sender: str) -> bool:
    """Return True if the sender is an Expo Brazil lead."""
    return normalize_phone(sender) in EXPO_LEADS_PHONES or sender in gabriela_history


def notify_michael_expo_interest(sender: str, empresa: str, interesse: str, last_msg: str):
    """Notify Michael via WhatsApp when an Expo lead shows interest."""
    michael_phone = os.getenv("MICHAEL_PHONE")
    if not michael_phone or not META_ACCESS_TOKEN:
        return
    try:
        clean_phone = sender.replace("whatsapp:", "")
        body = (
            f"Ã°ÂÂÂ§Ã°ÂÂÂ· *Expo Brazil Ã¢ÂÂ Lead Interessado!*\n\n"
            f"Ã°ÂÂÂ± Telefone: {clean_phone}\n"
            f"Ã°ÂÂÂ¢ Empresa: {empresa or 'NÃÂ£o informado'}\n"
            f"Ã°ÂÂÂ¯ Interesse: {interesse or 'NÃÂ£o especificado'}\n\n"
            f"Ã°ÂÂÂ¬ Mensagem:\n_{last_msg[:300]}_"
        )
        send_whatsapp_meta(michael_phone, body=body)
        print(f"Ã¢ÂÂ Michael notificado Ã¢ÂÂ Expo lead: {clean_phone}")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Falha ao notificar Michael (Expo): {e}")


def extract_expo_interest(text: str):
    """Extract [INTERESSE EXPO] block from Gabriela's response."""
    empresa, interesse = "", ""
    if "[INTERESSE EXPO]" not in text:
        return empresa, interesse
    in_block = False
    for line in text.splitlines():
        if "[INTERESSE EXPO]" in line:
            in_block = True
            continue
        if "[/INTERESSE EXPO]" in line:
            break
        if in_block:
            if line.startswith("Empresa:"):
                empresa = line.replace("Empresa:", "").strip()
            elif line.startswith("Interesse:"):
                interesse = line.replace("Interesse:", "").strip()
    return empresa, interesse


def clean_gabriela_response(text: str) -> str:
    """Remove internal interest block before sending to user."""
    cleaned = re.sub(r'\[INTERESSE EXPO\].*?\[/INTERESSE EXPO\]', '', text, flags=re.DOTALL)
    return cleaned.strip()


def get_gabriela_reply(messages: list) -> tuple:
    """Call Claude as Gabriela Ã¢ÂÂ no tools, Portuguese, Expo Brazil only."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=GABRIELA_SYSTEM_PROMPT,
        messages=messages
    )
    reply = ""
    for block in response.content:
        if hasattr(block, "text"):
            reply += block.text
    messages.append({"role": "assistant", "content": reply.strip()})
    return reply.strip(), messages


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# TTS TEXT PREPROCESSOR Ã¢ÂÂ clean text for natural speech
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def prepare_for_tts(text: str) -> str:
    """
    Prepare Gabriela's text for OpenAI TTS so it sounds natural in Portuguese:
    - Converts $397 Ã¢ÂÂ "trezentos e noventa e sete dÃÂ³lares"
    - Converts 3x  Ã¢ÂÂ "trÃÂªs vezes"
    - Converts /mÃÂªs Ã¢ÂÂ "por mÃÂªs"
    - Converts 50% Ã¢ÂÂ "cinquenta por cento"
    - Strips emojis, markdown, and bullet symbols
    - Smooths punctuation and line breaks for natural speech flow
    """

    # Ã¢ÂÂÃ¢ÂÂ Helper: integer to Portuguese words Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    def num_to_pt(n: int) -> str:
        if n == 0:
            return "zero"
        ones = [
            "", "um", "dois", "trÃÂªs", "quatro", "cinco", "seis", "sete", "oito", "nove",
            "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis",
            "dezessete", "dezoito", "dezenove"
        ]
        tens_w = [
            "", "", "vinte", "trinta", "quarenta", "cinquenta",
            "sessenta", "setenta", "oitenta", "noventa"
        ]
        hund_w = [
            "", "cem", "duzentos", "trezentos", "quatrocentos", "quinhentos",
            "seiscentos", "setecentos", "oitocentos", "novecentos"
        ]
        if n >= 1000:
            k, r = divmod(n, 1000)
            s = "mil" if k == 1 else f"{num_to_pt(k)} mil"
            return s + (" e " + num_to_pt(r) if r else "")
        if n >= 100:
            h, r = divmod(n, 100)
            s = "cento" if (h == 1 and r) else hund_w[h]
            return s + (" e " + num_to_pt(r) if r else "")
        if n >= 20:
            t, u = divmod(n, 10)
            return tens_w[t] + (" e " + ones[u] if u else "")
        return ones[n]

    # Ã¢ÂÂÃ¢ÂÂ Brand name: MWM Ã¢ÂÂ spelled out in Portuguese Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    # "MWM" would be mispronounced; replace with phonetic Portuguese letters
    text = re.sub(r'\bMWM\b', 'eme dÃÂ¡blio eme', text)

    # Ã¢ÂÂÃ¢ÂÂ URLs Ã¢ÂÂ spoken phrase Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    # Don't try to pronounce URLs Ã¢ÂÂ tell the listener the link is coming as text.
    # The async function will send the URL as a follow-up text message right after.
    text = re.sub(
        r'(?:https?://)?(?:www\.)?videoproductionplans\.com/\S*',
        'vou te enviar o link por texto',
        text, flags=re.IGNORECASE
    )
    # Generic fallback: strip any remaining raw URLs so TTS doesn't mangle them
    text = re.sub(r'https?://\S+', 'o link que vou te enviar', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwww\.\S+', 'o link que vou te enviar', text, flags=re.IGNORECASE)

    # Ã¢ÂÂÃ¢ÂÂ Phone numbers Ã¢ÂÂ spoken phrase Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    # Don't pronounce phone numbers in audio Ã¢ÂÂ announce they'll arrive as text.
    # The async function sends the actual number as a follow-up text message.
    text = re.sub(
        r'\+?1?\s*[\(]?\d{3}[\)]?\s*[-.]?\s*\d{3}\s*[-.]?\s*\d{4}',
        'vou te enviar o nÃÂºmero por texto',
        text
    )

    # Ã¢ÂÂÃ¢ÂÂ Plus sign Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    # Remaining standalone + e.g. "20+ anos", "Pacote 1 +" Ã¢ÂÂ "mais"
    text = text.replace('+', ' mais ')

    # Ã¢ÂÂÃ¢ÂÂ Duration: 1min Ã¢ÂÂ um minuto, 3min Ã¢ÂÂ trÃÂªs minutos Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    def _rep_min(m):
        n = int(m.group(1))
        word = num_to_pt(n)
        unit = "minuto" if n == 1 else "minutos"
        return f"{word} {unit}"
    text = re.sub(r'(\d+)\s*min\b', _rep_min, text, flags=re.IGNORECASE)

    # Ã¢ÂÂÃ¢ÂÂ Multipliers: 3x Ã¢ÂÂ trÃÂªs vezes Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    _mult = {
        "1": "uma vez", "2": "duas vezes", "3": "trÃÂªs vezes", "4": "quatro vezes",
        "5": "cinco vezes", "6": "seis vezes", "7": "sete vezes", "8": "oito vezes",
        "9": "nove vezes", "10": "dez vezes", "12": "doze vezes"
    }
    def _rep_mult(m):
        return _mult.get(m.group(1), f"{m.group(1)} vezes")
    text = re.sub(r'(\d+)x\b', _rep_mult, text)

    # Ã¢ÂÂÃ¢ÂÂ /mÃÂªs Ã¢ÂÂ por mÃÂªs Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = text.replace("/mÃÂªs", " por mÃÂªs")

    # Ã¢ÂÂÃ¢ÂÂ Prices: $XXX Ã¢ÂÂ spelled out in Portuguese dÃÂ³lares Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    def _rep_price(m):
        raw = m.group(1).replace(",", "")
        try:
            return num_to_pt(int(float(raw))) + " dÃÂ³lares"
        except ValueError:
            return m.group(0)
    text = re.sub(r'\$(\d[\d,]*(?:\.\d+)?)', _rep_price, text)

    # Ã¢ÂÂÃ¢ÂÂ Percentages: 50% Ã¢ÂÂ cinquenta por cento Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    def _rep_pct(m):
        try:
            return num_to_pt(int(m.group(1))) + " por cento"
        except ValueError:
            return m.group(0)
    text = re.sub(r'(\d+)%', _rep_pct, text)

    # Ã¢ÂÂÃ¢ÂÂ Strip emojis Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(
        r'[\U00010000-\U0010ffff\U0001F300-\U0001F9FF'
        r'\u2600-\u26FF\u2700-\u27BF\u2300-\u23FF\u25A0-\u25FF]',
        '', text
    )

    # Ã¢ÂÂÃ¢ÂÂ Strip markdown formatting Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)

    # Ã¢ÂÂÃ¢ÂÂ Bullet characters Ã¢ÂÂ brief pause Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(r'[Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ¢ÃÂ·]', ',', text)

    # Ã¢ÂÂÃ¢ÂÂ Em dash and separators Ã¢ÂÂ comma Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(r'\s*Ã¢ÂÂ\s*', ', ', text)

    # Ã¢ÂÂÃ¢ÂÂ Line breaks Ã¢ÂÂ sentence pause Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(r'\n+', '. ', text)

    # Ã¢ÂÂÃ¢ÂÂ Clean up stray punctuation and whitespace Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\.\s*,', '.', text)
    text = text.strip()

    return text


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# AUDIO TRANSCRIPTION Ã¢ÂÂ OpenAI Whisper
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def transcribe_audio(media_id: str, language: str = None) -> str:
    """
    Download a WhatsApp voice note from Meta Cloud API and transcribe via OpenAI Whisper.
    - media_id   : The media ID from the Meta webhook payload.
    - language   : BCP-47 language code hint, e.g. 'pt' for Portuguese.
                   Pass None to let Whisper auto-detect.
    Returns the transcribed text string.
    Raises an exception if download or transcription fails.
    """
    import tempfile

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY is not set in environment variables.")

    # Download the audio from Meta Cloud API
    audio_bytes, ct = download_meta_media(media_id)
    ct = ct.lower()

    # Pick the right file extension so Whisper knows the format
    if "mpeg" in ct or "mp3" in ct:
        suffix = ".mp3"
    elif "mp4" in ct:
        suffix = ".mp4"
    elif "amr" in ct:
        suffix = ".amr"
    elif "wav" in ct:
        suffix = ".wav"
    else:
        suffix = ".ogg"  # default â WhatsApp voice notes are ogg/opus

    # Write to a temp file (Whisper API needs a real file object)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        from openai import OpenAI as _OpenAI
        oai = _OpenAI(api_key=openai_key)

        with open(tmp_path, "rb") as audio_file:
            kwargs = {"model": "whisper-1", "file": audio_file}
            if language:
                kwargs["language"] = language
            transcript = oai.audio.transcriptions.create(**kwargs)

        print(f"ðï¸ Transcribed ({language or 'auto'}): {transcript.text}")
        return transcript.text

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# TEXT-TO-SPEECH Ã¢ÂÂ ElevenLabs (Gabriela audio replies)
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# Voice: Roberta (conversational, sounds natural in Brazilian Portuguese)
# Model: eleven_multilingual_v2 Ã¢ÂÂ best multilingual quality
# Voice ID: RGymW84CSmfVugnA5tvA

def generate_audio_reply(text: str) -> str | None:
    """
    Convert text to speech using ElevenLabs and return a publicly accessible URL.
    Uses Roberta voice with eleven_multilingual_v2 Ã¢ÂÂ natural Brazilian Portuguese.
    Returns None if TTS is unavailable or the public domain is not configured.
    """
    import uuid
    import requests as _requests

    el_key      = os.getenv("ELEVENLABS_API_KEY")
    # Railway injects RAILWAY_PUBLIC_DOMAIN automatically for public services
    base_domain = (
        os.getenv("RAILWAY_PUBLIC_DOMAIN") or
        os.getenv("APP_BASE_URL", "").rstrip("/")
    )

    if not el_key:
        print("Ã¢ÂÂ Ã¯Â¸Â TTS skipped: ELEVENLABS_API_KEY not set")
        return None
    if not base_domain:
        print("Ã¢ÂÂ Ã¯Â¸Â TTS skipped: RAILWAY_PUBLIC_DOMAIN / APP_BASE_URL not set")
        return None

    VOICE_ID = "RGymW84CSmfVugnA5tvA"   # Roberta Ã¢ÂÂ conversational, great in PT-BR
    TTS_URL  = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"

    os.makedirs("/tmp/audio", exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = f"/tmp/audio/{filename}"

    # Preprocess text: convert prices, strip emojis, smooth punctuation
    spoken_text = prepare_for_tts(text)
    print(f"Ã°ÂÂÂ TTS input: {spoken_text[:120]}...")

    response = _requests.post(
        TTS_URL,
        headers={
            "xi-api-key": el_key,
            "Content-Type": "application/json"
        },
        json={
            "text": spoken_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.3,
                "use_speaker_boost": True
            }
        },
        timeout=30
    )
    response.raise_for_status()

    with open(filepath, "wb") as f:
        f.write(response.content)

    # Build full public URL Ã¢ÂÂ handle both raw domain and full https:// prefix
    if base_domain.startswith("http"):
        public_url = f"{base_domain}/audio/{filename}"
    else:
        public_url = f"https://{base_domain}/audio/{filename}"

    print(f"Ã°ÂÂÂ TTS generated: {public_url}")
    return public_url


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# TOOLS DEFINITION
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

TOOLS = [
    {
        "name": "get_available_slots",
        "description": (
            "Fetch Michael's real available time slots for a free 30-minute Strategy Call. "
            "Call this as soon as the lead agrees to book a meeting. "
            "Returns up to 5 available slots with a display label and a slot_id to use when booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "check_specific_slot",
        "description": (
            "Check if a specific date and time requested by the lead is available on Michael's calendar. "
            "Use this when the lead asks for a time that was NOT in the get_available_slots list "
            "(e.g. 'do you have Wednesday at 2pm?'). "
            "Returns available=true and a slot_id to use with book_appointment, or available=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requested_datetime": {
                    "type": "string",
                    "description": "The requested date and time in ISO 8601 format, e.g. '2026-03-11T14:00:00'. Always use the Eastern Time zone."
                }
            },
            "required": ["requested_datetime"]
        }
    },
    {
        "name": "book_appointment",
        "description": (
            "Book a 30-minute appointment on Michael's Google Calendar. "
            "Call this after the lead replies with their chosen slot number. "
            "Sends a calendar invite to the lead's email automatically. "
            "Use appointment_type='studio_visit' when booking a studio visit, "
            "and appointment_type='strategy_call' when booking a remote strategy call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": "The ISO datetime string of the chosen slot (from get_available_slots results)."
                },
                "lead_name": {
                    "type": "string",
                    "description": "The lead's full name."
                },
                "lead_email": {
                    "type": "string",
                    "description": "The lead's email address."
                },
                "lead_business": {
                    "type": "string",
                    "description": "The lead's business name or description."
                },
                "appointment_type": {
                    "type": "string",
                    "enum": ["studio_visit", "strategy_call"],
                    "description": "Type of appointment: 'studio_visit' for in-person visits to MWM Studios, 'strategy_call' for remote video/phone calls."
                }
            },
            "required": ["slot_id", "lead_name", "lead_email", "lead_business", "appointment_type"]
        }
    }
]

# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# GOOGLE CALENDAR FUNCTIONS
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def get_calendar_service(impersonate=None):
    """
    Authenticate and return a Google Calendar service client.

    DWD is used ONLY when `impersonate` is explicitly passed.
    Read-only operations (get_available_slots, check_specific_slot) call this
    without impersonate so they never trigger DWD Ã¢ÂÂ the service account accesses
    the MWM CREATIONS calendar directly (service account must be a calendar member).

    Write operations (book_appointment) pass impersonate=MICHAEL_EMAIL to try DWD,
    but the caller handles the fallback if DWD is not configured.
    """
    # When impersonating via DWD, only request calendar scope (DWD config doesn't include spreadsheets)
    cal_only_scopes = ["https://www.googleapis.com/auth/calendar"]
    scopes = cal_only_scopes if impersonate else SCOPES
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=scopes
        )
        sa_email = creds_dict.get("client_email", "unknown")
        print(f"[calendar] service account: {sa_email}")
    else:
        # Fallback: load from local file (for local dev)
        creds = service_account.Credentials.from_service_account_file(
            "service_account.json", scopes=scopes
        )

    # Domain-Wide Delegation Ã¢ÂÂ ONLY when explicitly requested by the caller
    if impersonate:
        creds = creds.with_subject(impersonate)
        print(f"[calendar] DWD as: {impersonate}")

    return build("calendar", "v3", credentials=creds)


def get_available_slots():
    """
    Return exactly 3 available slots Ã¢ÂÂ one per each of the next 3 available business days,
    alternating morning -> afternoon -> morning.
      Morning options (tried in order): 10:00 AM, then 11:00 AM
      Afternoon options (tried in order): 3:00 PM, then 2:00 PM
    Checks the MWM CREATIONS calendar (CALENDAR_ID).
    All-day events are intentionally ignored so they don't block real availability.
    """
    try:
        service = get_calendar_service()
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        end_window = now + timedelta(days=21)

        print(f"[get_available_slots] checking calendar: {CALENDAR_ID}")

        # Fetch all timed events in the window
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end_window.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        busy_times = []
        for event in events_result.get("items", []):
            start_info = event.get("start", {})
            end_info = event.get("end", {})
            if "dateTime" in start_info and "dateTime" in end_info:
                busy_times.append({
                    "start": start_info["dateTime"],
                    "end": end_info["dateTime"]
                })

        # Alternating pattern: morning -> afternoon -> morning
        # morning = [10am, 11am] in priority order
        # afternoon = [3pm, 2pm] in priority order
        day_patterns = [
            [(10, 0), (11, 0)],   # Slot 1: morning
            [(15, 0), (14, 0)],   # Slot 2: afternoon
            [(10, 0), (11, 0)],   # Slot 3: morning
        ]

        slots = []
        current_day = now.date() - timedelta(days=1)  # loop increments before checking
        days_checked = 0

        while len(slots) < 3 and days_checked < 21:
            current_day += timedelta(days=1)
            days_checked += 1

            # Monday-Friday only
            if current_day.weekday() >= 5:
                continue

            times_to_try = day_patterns[len(slots)]

            for (hour, minute) in times_to_try:
                candidate = tz.localize(datetime(
                    current_day.year, current_day.month, current_day.day,
                    hour, minute, 0
                ))

                # Skip if already in the past
                if candidate <= now:
                    continue

                slot_end = candidate + timedelta(minutes=30)
                is_busy = any(
                    datetime.fromisoformat(b["start"]).astimezone(tz) < slot_end
                    and datetime.fromisoformat(b["end"]).astimezone(tz) > candidate
                    for b in busy_times
                )

                if not is_busy:
                    slots.append({
                        "id": candidate.isoformat(),
                        "display": candidate.strftime("%A, %B %d at %I:%M %p EST")
                    })
                    break  # one slot per day, move to next day

            # If this day had no available slot in the desired period, the while loop
            # retries the same pattern index on the next business day automatically.

        print(f"[get_available_slots] returning {len(slots)} slots: {[s['display'] for s in slots]}")
        return slots

    except Exception as e:
        print(f"[get_available_slots] ERROR: {e}")
        return []


def book_appointment(slot_id, lead_name, lead_email, lead_business, lead_phone=None, appointment_type="studio_visit"):
    """
    Create a 30-minute Google Calendar event on the MWM Creations calendar.
    Tries three strategies in order, using the first that succeeds:

      1. MWM Creations calendar  + attendees + send invites
         (works when Domain-Wide Delegation is configured via GOOGLE_DELEGATE_EMAIL)
      2. MWM Creations calendar  + attendees, no email invites
         (silent attendee add Ã¢ÂÂ may still fail if DWD not set up)
      3. MWM Creations calendar  + no attendees
         (works when service account has WRITER access but DWD is not configured)

    Returns the event ID on success, or None on failure.
    """
    try:
        # Try with DWD first (sends proper calendar invites as Michael)
        # Falls back to no-DWD if unauthorized_client (DWD not configured in Google Admin)
        delegate = os.getenv("GOOGLE_DELEGATE_EMAIL")
        try:
            service = get_calendar_service(impersonate=delegate) if delegate else get_calendar_service()
            # Quick test Ã¢ÂÂ will raise if DWD creds are invalid
            service.calendarList().list(maxResults=1).execute()
            print(f"[book_appointment] using DWD as {delegate}")
        except Exception as dwd_err:
            if "unauthorized_client" in str(dwd_err) or "invalid_grant" in str(dwd_err):
                print(f"[book_appointment] DWD failed ({dwd_err}), falling back to service account direct access")
                service = get_calendar_service()  # no DWD
            else:
                raise
        tz = pytz.timezone(TIMEZONE)
        start_dt = datetime.fromisoformat(slot_id).astimezone(tz)
        end_dt = start_dt + timedelta(minutes=30)

        if appointment_type == "strategy_call":
            event_title = f"Strategy Call Ã¢ÂÂ {lead_name} ({lead_business})"
            event_desc_header = "Free 30-Minute Strategy Call with Michael Moraes / MWM Creations"
        else:
            event_title = f"Studio Visit Ã¢ÂÂ {lead_name} ({lead_business})"
            event_desc_header = "Studio Visit with Michael Moraes / MWM Creations Studios"

        event_base = {
            "summary": event_title,
            "description": (
                f"{event_desc_header}\n\n"
                f"Lead: {lead_name}\n"
                f"Business: {lead_business}\n"
                f"Email: {lead_email}\n"
                f"Booked via: Maya (WhatsApp Sales Agent)"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},
                    {"method": "popup",  "minutes": 30}
                ]
            }
        }

        # Each attempt: (calendarId, include_attendees, sendUpdates, label)
        attempts = [
            (CALENDAR_ID, False, "none", "MWM Creations cal, no attendees"),
            (CALENDAR_ID, True,  "all",  "MWM Creations cal + attendees + invites"),
            (CALENDAR_ID, True,  "none", "MWM Creations cal + attendees, no invites"),
        ]

        created = None
        used_attendees = False
        used_calendar = CALENDAR_ID

        for cal_id, with_attendees, send_upd, label in attempts:
            event = dict(event_base)
            if with_attendees:
                event["attendees"] = [
                    {"email": lead_email}
                ]
            try:
                created = service.events().insert(
                    calendarId=cal_id,
                    body=event,
                    sendUpdates=send_upd
                ).execute()
                used_attendees = with_attendees
                used_calendar = cal_id
                print(f"Ã¢ÂÂ Booking strategy used: {label}")
                break
            except Exception as attempt_err:
                print(f"Ã¢ÂÂ Ã¯Â¸Â Attempt [{label}] failed: {attempt_err}")
                continue

        if not created:
            print("Ã¢ÂÂ All booking attempts failed.")
            return None

        event_link = created.get("htmlLink", "")

        # ── Slack: notify appointment booked ──
        try:
            _slot_str = f"{start_dt.strftime('%B %d, %Y at %I:%M %p')} ET"
            _interest = appointment_type.replace("_", " ").title()
            _notify_appointment_booked(lead_name or "Prospect", lead_phone or "N/A", _slot_str, _interest)
            # ── Update Google Sheet: mark as booked ──
            try:
                if lead_phone:
                    update_lead_columns(lead_phone, {
                        "WhatsApp Status": "Booked",
                        "Appointment Booked": "Y",
                        "Lead Temperature": "Hot",
                    })
            except Exception as _sheet_err:
                print(f"\u26a0\ufe0f Sheet booking update failed (non-fatal): {_sheet_err}")
        except Exception as slack_err:
            print(f"⚠️ Slack booking notification failed (non-fatal): {slack_err}")
        print(f"Ã¢ÂÂ Appointment booked: {created.get('id')} for {lead_name} at {start_dt}")
        print(f"Ã°ÂÂÂ Calendar: {used_calendar} | Attendees included: {used_attendees}")
        print(f"Ã°ÂÂÂ Event link: {event_link}")

        # ââ WhatsApp notification to Michael ââââââââââââââââââ
        michael_phone = os.getenv("MICHAEL_PHONE")

        if michael_phone and META_ACCESS_TOKEN:
            try:
                invite_note = (
                    "\u2709\ufe0f Calendar invite sent to lead."
                    if used_attendees else
                    "\u26a0\ufe0f Calendar invite NOT sent (DWD not yet configured â see setup guide)."
                )
                phone_line = ""
                if lead_phone:
                    clean_phone = lead_phone.replace("whatsapp:", "")
                    phone_line = f"ð± Phone: {clean_phone}\n"
                notification = (
                    f"ð *New Studio Visit Booked via Maya!*\n\n"
                    f"ð¤ Name: {lead_name}\n"
                    f"ð¢ Business: {lead_business}\n"
                    f"ð§ Email: {lead_email}\n"
                    f"{phone_line}"
                    f"ð Time: {start_dt.strftime('%A, %B %d at %I:%M %p %Z')}\n\n"
                    f"{invite_note}"
                )
                send_whatsapp_meta(michael_phone, body=notification)
                print(f"\u2705 Michael notified via WhatsApp at {michael_phone}")
            except Exception as notify_err:
                print(f"\u26a0\ufe0f Could not notify Michael via WhatsApp: {notify_err}")

        return created.get("id")

    except Exception as e:
        print(f"Error booking appointment: {e}")
        return None


def _parse_datetime_flexible(dt_string):
    """
    Parse a datetime string in ISO 8601 or other common formats.
    Returns a naive or aware datetime object; caller handles timezone.
    """
    try:
        return datetime.fromisoformat(dt_string)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(dt_string, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised datetime format: {dt_string!r}")


def check_specific_slot(requested_datetime):
    """
    Check if a specific requested time is free on the MWM Creations calendar.
    Returns {"available": True, "slot_id": ..., "display": ...} or {"available": False}.
    All-day events are ignored (same logic as get_available_slots).
    """
    print(f"[check_specific_slot] raw input: {requested_datetime!r}")
    try:
        service = get_calendar_service()
        tz = pytz.timezone(TIMEZONE)

        # Parse the requested time; assume Eastern if no timezone info
        candidate = _parse_datetime_flexible(requested_datetime)
        if candidate.tzinfo is None:
            candidate = tz.localize(candidate)
        else:
            candidate = candidate.astimezone(tz)

        print(f"[check_specific_slot] parsed candidate: {candidate.isoformat()}")

        # Must be a weekday between 9 AM and 4:30 PM
        if candidate.weekday() >= 5:
            print(f"[check_specific_slot] rejected: weekend (weekday={candidate.weekday()})")
            return {"available": False, "reason": "weekends are not available"}
        if not (9 <= candidate.hour < 17) or (candidate.hour == 16 and candidate.minute > 30):
            print(f"[check_specific_slot] rejected: outside business hours (hour={candidate.hour})")
            return {"available": False, "reason": "outside business hours (9 AM Ã¢ÂÂ 5 PM EST)"}
        # Must be in the future
        now_et = datetime.now(tz)
        if candidate <= now_et:
            print(f"[check_specific_slot] rejected: in the past (candidate={candidate.isoformat()}, now={now_et.isoformat()})")
            return {"available": False, "reason": "that time has already passed"}

        slot_end = candidate + timedelta(minutes=30)
        window_start = candidate - timedelta(minutes=1)
        window_end = slot_end + timedelta(minutes=1)

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=window_start.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        blocking_events = []
        for event in events_result.get("items", []):
            start_info = event.get("start", {})
            end_info = event.get("end", {})
            # Skip all-day events
            if "dateTime" not in start_info or "dateTime" not in end_info:
                continue
            ev_start = datetime.fromisoformat(start_info["dateTime"]).astimezone(tz)
            ev_end = datetime.fromisoformat(end_info["dateTime"]).astimezone(tz)
            if ev_start < slot_end and ev_end > candidate:
                blocking_events.append(f"{event.get('summary', 'Unnamed')} ({ev_start.strftime('%H:%M')}Ã¢ÂÂ{ev_end.strftime('%H:%M')})")

        if blocking_events:
            print(f"[check_specific_slot] rejected: blocked by events: {blocking_events}")
            return {"available": False, "reason": "that time is already booked"}

        print(f"[check_specific_slot] AVAILABLE: {candidate.isoformat()}")
        return {
            "available": True,
            "slot_id": candidate.isoformat(),
            "display": candidate.strftime("%A, %B %d at %I:%M %p EST")
        }

    except Exception as e:
        print(f"[check_specific_slot] ERROR: {e}")
        return {"available": False, "reason": "could not verify that time"}


def handle_tool_call(tool_name, tool_input, sender=None):
    """Execute a tool call and return the result as a dict."""
    if tool_name == "get_available_slots":
        slots = get_available_slots()
        if slots:
            return {"slots": slots}
        else:
            return {"error": "Calendar check failed or no preferred slots found. Ask the lead to suggest a preferred day and time, then use check_specific_slot."}

    elif tool_name == "check_specific_slot":
        return check_specific_slot(tool_input["requested_datetime"])

    elif tool_name == "book_appointment":
        event_id = book_appointment(
            slot_id=tool_input["slot_id"],
            lead_name=tool_input["lead_name"],
            lead_email=tool_input["lead_email"],
            lead_business=tool_input["lead_business"],
            lead_phone=sender,
            appointment_type=tool_input.get("appointment_type", "studio_visit")
        )
        if event_id:
            # Update Google Sheets row with booking status
            try:
                update_booking_in_sheets(
                    sender=sender,
                    appointment_type=tool_input.get("appointment_type", "studio_visit"),
                    slot_id=tool_input["slot_id"],
                    lead_name=tool_input.get("lead_name", ""),
                    lead_email=tool_input.get("lead_email", ""),
                    lead_business=tool_input.get("lead_business", ""),
                )
            except Exception as sheets_err:
                print(f"Ã¢ÂÂ Ã¯Â¸Â Sheets booking update error (non-fatal): {sheets_err}")

            # Ã¢ÂÂÃ¢ÂÂ Notify Hub Ã¢ÂÂ triggers confirmation email + WhatsApp + Calendar Ã¢ÂÂÃ¢ÂÂ
            try:
                appt_type  = tool_input.get("appointment_type", "studio_visit")
                hub_event  = "booking_confirmed_tour" if appt_type == "studio_visit" else "booking_confirmed_call"
                # Mark lead as booked so cold-lead checker skips them
                if sender and sender in lead_data:
                    lead_data[sender]["booked"] = True
                fire_hub_event(
                    event_type  = hub_event,
                    lead_name   = tool_input.get("lead_name"),
                    lead_phone  = sender,
                    lead_email  = tool_input.get("lead_email"),
                    payload     = {
                        "booking_time": tool_input["slot_id"],
                        "booking_type": appt_type,
                    },
                )
            except Exception as hub_err:
                print(f"Ã¢ÂÂ Ã¯Â¸Â Hub booking event error (non-fatal): {hub_err}")

            return {"success": True, "event_id": event_id}
        else:
            return {"success": False, "error": "Could not book the appointment. Please try again."}

    return {"error": f"Unknown tool: {tool_name}"}


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# GOOGLE SHEETS Ã¢ÂÂ LEAD REPORT
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

SHEET_HEADERS = [
    "Date", "Time", "Name", "Business", "Phone", "Email",
    "Service Interest", "Status", "Appt Date & Time", "Notes", "Follow-up Ã¢ÂÂ", "Transcript",
    "Source", "Last Contact Date", "Outreach Channel",
    "Outreach Message Sent", "WhatsApp Status",
    "Conversation Summary", "Appointment Booked", "Lead Temperature",
]

def get_sheets_service():
    """Return an authenticated Google Sheets API service client."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_monthly_tab(service, sheet_id: str, tab_name: str):
    """Create the monthly tab with headers if it doesn't exist yet. Returns the tab's sheetId (gid)."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if tab_name in existing:
        return existing[tab_name]

    # Create the new tab
    result = service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name, "gridProperties": {"frozenRowCount": 1}}}}]}
    ).execute()
    gid = result["replies"][0]["addSheet"]["properties"]["sheetId"]

    # Write header row
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [SHEET_HEADERS]},
    ).execute()

    # Format header (bold, dark background, white text)
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.18},
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                }},
                "fields": "userEnteredFormat(textFormat,backgroundColor,foregroundColor)",
            }},
            {"autoResizeDimensions": {"dimensions": {
                "sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": len(SHEET_HEADERS),
            }}},
        ]},
    ).execute()
    print(f"Ã¢ÂÂ Created new monthly tab: {tab_name}")
    return gid


def _parse_lead_fields(lead_info: str) -> dict:
    """Parse the [LEAD CAPTURED] block into a dict."""
    fields = {}
    for line in lead_info.strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()
    return fields


def format_transcript(history: list) -> str:
    """Convert conversation history list into a readable transcript string."""
    lines = []
    for msg in history:
        role = "Lead" if msg.get("role") == "user" else "Maya"
        content = msg.get("content", "")
        # content can be a string or a list of blocks (tool use)
        if isinstance(content, list):
            text_parts = [
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = " ".join(text_parts).strip()
        else:
            text = str(content).strip()
        # Skip empty or tool-only messages
        if text:
            lines.append(f"[{role}]: {text}")
    return "\n".join(lines)



def log_new_contact_to_sheets(sender: str):
    """Log a minimal row on first contact Ã¢ÂÂ phone + timestamp + status 'New Lead'.
    This ensures every person who messages Maya is captured, even if they never share their info.
    The row is updated later when lead info is captured or a booking is made."""
    if not SHEETS_LEADS_ID:
        return
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")

        svc = get_sheets_service()
        ensure_monthly_tab(svc, SHEETS_LEADS_ID, tab_name)

        # Don't add a duplicate row if this phone is already in the sheet this month
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!E:E",  # Phone column
        ).execute()
        existing_phones = [r[0] if r else "" for r in result.get("values", [])]
        if clean_phone in existing_phones:
            print(f"[Sheets] First-contact row already exists for {clean_phone} Ã¢ÂÂ skipping")
            return

        row = [
            now.strftime("%Y-%m-%d"),   # Date
            now.strftime("%I:%M %p"),   # Time
            "",                          # Name (unknown yet)
            "",                          # Business (unknown yet)
            clean_phone,                 # Phone
            "",                          # Email (unknown yet)
            "",                          # Service Interest
            "New Lead",                  # Status
            "",                          # Appt Date & Time
            "",                          # Notes
            "",                          # Follow-up Ã¢ÂÂ
            "",                          # Transcript (updated later)
        ]
        svc.spreadsheets().values().append(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        print(f"Ã¢ÂÂ First-contact row logged for {clean_phone}")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Could not log first contact to Sheets (non-fatal): {e}")


def update_lead_columns(sender: str, updates: dict):
    """Update specific columns for a lead by phone number.
    updates maps column header names to values, e.g. {"WhatsApp Status": "Booked"}.
    Non-fatal: exceptions are logged but never break the caller."""
    if not SHEETS_LEADS_ID:
        return
    try:
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")
        svc = get_sheets_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A1:T",
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return
        headers = rows[0]
        phone_col = headers.index("Phone") if "Phone" in headers else 4
        target_row = None
        for i, row in enumerate(rows[1:], start=2):
            if len(row) > phone_col and re.sub(r"\D", "", row[phone_col]) == clean_phone:
                target_row = i
        if target_row is None:
            return
        data = []
        for col_name, value in updates.items():
            if col_name in headers:
                col_idx = headers.index(col_name)
                col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)
                data.append({"range": f"'{tab_name}'!{col_letter}{target_row}", "values": [[value]]})
        if data:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()
            print(f"[Sheets] Updated {list(updates.keys())} for {clean_phone}")
    except Exception as e:
        print(f"\u26a0\ufe0f update_lead_columns failed (non-fatal): {e}")


def lookup_lead_in_sheets(sender: str) -> str:
    """Look up a sender's phone in the Google Sheet and return context string for Maya's prompt.
    Searches all monthly tabs (newest first) for the phone number.
    Returns a context string or empty string if not found."""
    if not SHEETS_LEADS_ID:
        return ""
    try:
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")
        phone_variants = {clean_phone}
        if clean_phone.startswith("1") and len(clean_phone) == 11:
            phone_variants.add(clean_phone[1:])
        svc = get_sheets_service()
        meta = svc.spreadsheets().get(spreadsheetId=SHEETS_LEADS_ID).execute()
        tabs = [s["properties"]["title"] for s in meta["sheets"]]
        month_order = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
        def tab_sort_key(t):
            parts = t.split()
            if len(parts) == 2 and parts[0] in month_order:
                return (int(parts[1]), month_order[parts[0]])
            return (0, 0)
        tabs.sort(key=tab_sort_key, reverse=True)
        for tab in tabs:
            try:
                result = svc.spreadsheets().values().get(
                    spreadsheetId=SHEETS_LEADS_ID,
                    range=f"'{tab}'!A1:T",
                ).execute()
                rows = result.get("values", [])
                if not rows:
                    continue
                headers = rows[0]
                phone_col = headers.index("Phone") if "Phone" in headers else 4
                for row in rows[1:]:
                    if len(row) > phone_col:
                        row_phone = re.sub(r"\D", "", row[phone_col])
                        if row_phone in phone_variants or clean_phone.endswith(row_phone) or row_phone.endswith(clean_phone):
                            data = {}
                            for i, h in enumerate(headers):
                                if i < len(row) and row[i]:
                                    data[h] = row[i]
                            parts = []
                            if data.get("Name"):
                                parts.append(f"Name: {data['Name']}")
                            if data.get("Business"):
                                parts.append(f"Business: {data['Business']}")
                            if data.get("Service Interest"):
                                parts.append(f"Interested in: {data['Service Interest']}")
                            if data.get("Status"):
                                parts.append(f"Current status: {data['Status']}")
                            if data.get("Date"):
                                parts.append(f"First contact: {data['Date']}")
                            if data.get("Appt Date & Time"):
                                parts.append(f"Appointment: {data['Appt Date & Time']}")
                            if data.get("Notes"):
                                parts.append(f"Notes: {data['Notes']}")
                            if parts:
                                ctx = "; ".join(parts)
                                print(f"[Context] Found lead context for {clean_phone}: {ctx[:100]}...")
                                return ctx
            except Exception:
                continue
        return ""
    except Exception as e:
        print(f"\u26a0\ufe0f Lead context lookup failed (non-fatal): {e}")
        return ""


def log_lead_to_sheets(lead_info: str, sender: str, history: list = None):
    """Update the existing lead row with captured info, or append a new row if not found."""
    if not SHEETS_LEADS_ID:
        return
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")
        fields = _parse_lead_fields(lead_info)
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")
        transcript = format_transcript(history) if history else ""

        svc = get_sheets_service()
        ensure_monthly_tab(svc, SHEETS_LEADS_ID, tab_name)

        # Try to find an existing row by phone number and UPDATE it
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A:T",
        ).execute()
        rows = result.get("values", [])

        # ── Migrate headers: add missing columns to existing tabs ──
        if rows and len(rows[0]) < len(SHEET_HEADERS):
            missing = SHEET_HEADERS[len(rows[0]):]
            start_col = chr(65 + len(rows[0]))
            svc.spreadsheets().values().update(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab_name}'!{start_col}1",
                valueInputOption="RAW",
                body={"values": [missing]},
            ).execute()
            print(f"[Sheets] Migrated headers: added {missing}")
            rows[0].extend(missing)

        target_row_index = None
        for i, row in enumerate(rows):
            if len(row) >= 5 and row[4] == clean_phone:
                target_row_index = i  # keep last match

        if target_row_index is not None:
            row_number = target_row_index + 1  # 1-based
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": [
                    {"range": f"'{tab_name}'!C{row_number}", "values": [[fields.get("name", "")]]},
                    {"range": f"'{tab_name}'!D{row_number}", "values": [[fields.get("business", "")]]},
                    {"range": f"'{tab_name}'!F{row_number}", "values": [[fields.get("email", "")]]},
                    {"range": f"'{tab_name}'!G{row_number}", "values": [[fields.get("interest", "")]]},
                    {"range": f"'{tab_name}'!H{row_number}", "values": [["Interested Ã¢ÂÂ No Booking Yet"]]},
                    {"range": f"'{tab_name}'!L{row_number}", "values": [[transcript]]},
                    {"range": f"'{tab_name}'!N{row_number}", "values": [[now.strftime("%Y-%m-%d")]]},
                    {"range": f"'{tab_name}'!Q{row_number}", "values": [["Active"]]},
                    {"range": f"'{tab_name}'!R{row_number}", "values": [[transcript[:500] if transcript else ""]]},
                ]},
            ).execute()
            print(f"Ã¢ÂÂ Lead row updated in Sheets (row {row_number}): {clean_phone}")
        else:
            # No existing row Ã¢ÂÂ append a full new row
            row = [
                now.strftime("%Y-%m-%d"),
                now.strftime("%I:%M %p"),
                fields.get("name", ""),
                fields.get("business", ""),
                clean_phone,
                fields.get("email", ""),
                fields.get("interest", ""),
                "Interested Ã¢ÂÂ No Booking Yet",
                "", "", "",
                transcript,
                "WhatsApp",              # M: Source
                now.strftime("%Y-%m-%d"), # N: Last Contact Date
                "", "",                   # O: Outreach Channel, P: Outreach Message Sent
                "New Lead",               # Q: WhatsApp Status
                "",                       # R: Conversation Summary
                "N",                      # S: Appointment Booked
                "Warm",                   # T: Lead Temperature
            ]
            svc.spreadsheets().values().append(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab_name}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
            print(f"Ã¢ÂÂ Lead appended to Sheets (no existing row found): {clean_phone}")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Could not log lead to Sheets (non-fatal): {e}")


def update_booking_in_sheets(sender: str, appointment_type: str, slot_id: str,
                              lead_name: str = "", lead_email: str = "", lead_business: str = ""):
    """Find the lead row by phone number and update status + appointment datetime."""
    if not SHEETS_LEADS_ID:
        return
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")

        status = "Ã¢ÂÂ Studio Visit Booked" if appointment_type == "studio_visit" else "Ã°ÂÂÂ Strategy Call Booked"

        appt_dt = datetime.fromisoformat(slot_id).astimezone(pytz.timezone(TIMEZONE))
        appt_str = appt_dt.strftime("%a %b %d, %Y at %I:%M %p")

        svc = get_sheets_service()
        ensure_monthly_tab(svc, SHEETS_LEADS_ID, tab_name)

        # Read all rows and find the last one matching this phone number
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A:K",
        ).execute()
        rows = result.get("values", [])

        target_row_index = None
        for i, row in enumerate(rows):
            if len(row) >= 5 and row[4] == clean_phone:  # column E = index 4 = Phone
                target_row_index = i  # keep updating to get the LAST match

        if target_row_index is not None:
            row_number = target_row_index + 1  # 1-based
            # Update Status (col H = index 8) and Appt Date & Time (col I = index 9)
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": [
                    {"range": f"'{tab_name}'!H{row_number}", "values": [[status]]},
                    {"range": f"'{tab_name}'!I{row_number}", "values": [[appt_str]]},
                ]},
            ).execute()
            print(f"Ã¢ÂÂ Booking updated in Sheets row {row_number}: {status}")
        else:
            # Row not found Ã¢ÂÂ append a fresh complete row
            row = [
                now.strftime("%Y-%m-%d"), now.strftime("%I:%M %p"),
                lead_name, lead_business, clean_phone, lead_email, "",
                status, appt_str, "", "",
            ]
            svc.spreadsheets().values().append(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab_name}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
            print(f"Ã¢ÂÂ Booking row appended to Sheets (lead not found by phone)")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Could not update booking in Sheets (non-fatal): {e}")


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# LEAD LOGGING FUNCTIONS
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def notify_michael_maya_lead(lead_info: str, sender: str):
    """Notify Michael via WhatsApp when Maya captures a new lead."""
    michael_phone = os.getenv("MICHAEL_PHONE")
    if not michael_phone or not META_ACCESS_TOKEN:
        return
    try:
        clean_phone = sender.replace("whatsapp:", "")
        body = (
            f"Ã°ÂÂÂ¥ *New Lead Captured by Maya!*\n\n"
            f"Ã°ÂÂÂ± WhatsApp: {clean_phone}\n\n"
            f"{lead_info.strip()}"
        )
        send_whatsapp_meta(michael_phone, body=body)
        print(f"Ã¢ÂÂ Michael notified Ã¢ÂÂ Maya lead: {clean_phone}")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Could not notify Michael (Maya lead): {e}")


def log_lead(lead_info, sender=None, history=None):
    """Log captured leads to stdout and a writable file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nÃ°ÂÂÂ¥ NEW LEAD CAPTURED at {timestamp}!")
    print(lead_info)
    print("=" * 50)
    # Write to /tmp which is always writable in Railway
    try:
        leads_file = "/tmp/leads.txt"
        with open(leads_file, "a") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"NEW LEAD - {timestamp}\n")
            f.write(lead_info)
            f.write(f"\n{'='*50}\n")
    except Exception as e:
        print(f"Ã¢ÂÂ Ã¯Â¸Â Could not write leads file: {e}")
    # Log to Google Sheets
    if sender:
        try:
            log_lead_to_sheets(lead_info, sender, history=history)
        except Exception as e:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Lead Sheets logging error (non-fatal): {e}")
    # Notify Michael via WhatsApp
    if sender:
        try:
            notify_michael_maya_lead(lead_info, sender)
        except Exception as e:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Lead WhatsApp notify error (non-fatal): {e}")


def extract_lead(text):
    """Extract lead info block from Claude's response."""
    pattern = r'\[LEAD CAPTURED\](.*?)\[/LEAD CAPTURED\]'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def clean_response(text):
    """Remove internal blocks before sending to WhatsApp."""
    cleaned = re.sub(r'\[LEAD CAPTURED\].*?\[/LEAD CAPTURED\]', '', text, flags=re.DOTALL)
    cleaned = cleaned.replace("[SEND_STUDIO_PHOTOS]", "")
    return cleaned.strip()


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# CLAUDE API WITH TOOL USE
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def get_claude_reply(messages, sender=None, lead_context=None):
    """
    Call Claude (Maya) with tool use support.
    Loops until Claude returns a final text response (no more tool calls).
    Returns the final text reply and updated messages list.
    """
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=get_system_prompt() + (f"\n\n--- LEAD CONTEXT ---\nThis person has prior history with MWM Creations. Here is what we know about them:\n{lead_context}\nUse this context to personalize your greeting and conversation. Reference their name, interests, or prior contact naturally. Do NOT treat them as a cold stranger." if lead_context else ""),
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "tool_use":
            # Collect text + tool calls from this assistant turn
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"Ã°ÂÂÂ§ Tool call: {block.name} | Input: {block.input}")
                    result = handle_tool_call(block.name, block.input, sender=sender)
                    print(f"Ã°ÂÂÂ§ Tool result: {result}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })

            # Append assistant's tool-use turn and the tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Final text response Ã¢ÂÂ extract the text
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            # Append final assistant reply to history (text only for storage)
            messages.append({"role": "assistant", "content": final_text})
            return final_text, messages


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# FLASK ROUTES
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    """Serve TTS-generated audio files stored in /tmp/audio."""
    return send_from_directory("/tmp/audio", filename)


def _extract_gabriela_followups(text: str) -> list[str]:
    """Return URLs and phone numbers found in Gabriela's reply to send as follow-up texts."""
    items = []
    if re.search(r'videoproductionplans\.com/expo2026', text, re.IGNORECASE):
        items.append('https://www.videoproductionplans.com/expo2026')
    if re.search(r'videoproductionplans\.com/book-?studio', text, re.IGNORECASE):
        items.append('https://www.videoproductionplans.com/book-studio')
    # Michael's direct WhatsApp number Ã¢ÂÂ send as a clickable contact
    if re.search(r'813.*?503.*?1224|8135031224', text):
        items.append('+1 (813) 503-1224')
    return items


def _send_whatsapp_api(to: str, body: str = None, media_url: str = None):
    """Send a WhatsApp message via Meta Cloud API (used for async replies)."""
    if not META_ACCESS_TOKEN:
        print("\u26a0\ufe0f META_ACCESS_TOKEN missing â cannot send async message")
        return
    send_whatsapp_meta(to, body=body, media_url=media_url)


def fire_hub_event(event_type, lead_name=None, lead_phone=None, lead_email=None,
                   payload=None, notes=None):
    """
    Fire an event to the MWM Agent Hub Ã¢ÂÂ non-blocking background thread.
    The Hub then handles: email confirmation, WhatsApp reminder, Calendar event, etc.
    """
    hub_url = os.getenv("AGENT_HUB_URL", "")
    hub_key = os.getenv("AGENT_HUB_API_KEY", "")
    if not hub_url or not hub_key:
        print("Ã¢ÂÂ Ã¯Â¸Â AGENT_HUB_URL or AGENT_HUB_API_KEY not set Ã¢ÂÂ Hub event skipped")
        return

    # Normalize phone: Hub expects +1XXXXXXXXXX (no whatsapp: prefix)
    clean_phone = lead_phone or ""
    clean_phone = clean_phone.replace("whatsapp:", "")
    if clean_phone and not clean_phone.startswith("+"):
        clean_phone = "+" + clean_phone

    def _send():
        import urllib.request, urllib.error
        body = json.dumps({
            "from_agent":  "maya",
            "event_type":  event_type,
            "lead_name":   lead_name,
            "lead_phone":  clean_phone,
            "lead_email":  lead_email,
            "payload":     payload or {},
            "notes":       notes,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{hub_url}/event",
            data=body,
            headers={"Content-Type": "application/json", "X-Api-Key": hub_key},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                print(f"Ã¢ÂÂ Hub event fired: [{event_type}] | handlers triggered: {result.get('handlers_triggered', 0)}")
        except urllib.error.HTTPError as e:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Hub event [{event_type}] HTTP {e.code}: {e.read().decode()}")
        except Exception as e:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Hub event [{event_type}] failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


def _process_gabriela_audio_async(sender: str, media_url: str):
    """Background thread: transcribe voice note, get Gabriela reply, send TTS via Twilio API.

    Runs outside the Twilio webhook request context so there is no 15-second timeout.
    """
    try:
        # Ã¢ÂÂÃ¢ÂÂ 1. Transcribe Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        try:
            incoming_msg = transcribe_audio(media_url, language="pt")
            print(f"Ã°ÂÂÂ Async transcription: {incoming_msg!r}")
        except Exception as trans_err:
            print(f"Ã¢ÂÂ Async transcription failed: {trans_err}")
            _send_whatsapp_api(
                sender,
                body="Desculpe, nÃÂ£o consegui ouvir seu ÃÂ¡udio agora. Pode me enviar a mensagem por texto? Ã°ÂÂÂ"
            )
            return

        # Ã¢ÂÂÃ¢ÂÂ 2. Init / update history Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        if sender not in gabriela_history:
            gabriela_history[sender] = []
        gabriela_history[sender].append({"role": "user", "content": incoming_msg})
        if len(gabriela_history[sender]) > 20:
            gabriela_history[sender] = gabriela_history[sender][-20:]

        # Ã¢ÂÂÃ¢ÂÂ 3. Get Gabriela reply Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        try:
            reply, updated = get_gabriela_reply(gabriela_history[sender])
            gabriela_history[sender] = updated
        except Exception as e:
            print(f"Ã¢ÂÂ Async Gabriela error: {e}")
            _send_whatsapp_api(
                sender,
                body="Desculpe, estou com uma instabilidade tÃÂ©cnica. Por favor, tente novamente em instantes. Ã°ÂÂÂ"
            )
            return

        # Ã¢ÂÂÃ¢ÂÂ 4. Notify Michael if interest detected Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        try:
            empresa, interesse = extract_expo_interest(reply)
            if empresa or interesse:
                notify_michael_expo_interest(sender, empresa, interesse, incoming_msg)
        except Exception as notify_err:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Expo notify error (non-fatal): {notify_err}")

        clean_reply = clean_gabriela_response(reply)

        # Ã¢ÂÂÃ¢ÂÂ 5. TTS Ã¢ÂÂ send audio; fall back to text if TTS fails Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        audio_url = None
        try:
            audio_url = generate_audio_reply(clean_reply)
        except Exception as tts_err:
            print(f"Ã¢ÂÂ Ã¯Â¸Â Async TTS failed, falling back to text: {tts_err}")

        if audio_url:
            _send_whatsapp_api(sender, media_url=audio_url)
            print(f"Ã°ÂÂÂ Async audio reply sent to {sender}")
        else:
            _send_whatsapp_api(sender, body=clean_reply)
            print(f"Ã°ÂÂÂ Async text reply sent to {sender} (TTS unavailable)")

        # Ã¢ÂÂÃ¢ÂÂ 6. Follow-up texts: URLs and phone numbers Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
        # Gabriela's audio says "vou te enviar o link/nÃÂºmero por texto" Ã¢ÂÂ
        # these messages deliver on that promise.
        for item in _extract_gabriela_followups(clean_reply):
            _send_whatsapp_api(sender, body=item)
            print(f"Ã°ÂÂÂ Sent follow-up text to {sender}: {item}")

    except Exception as e:
        print(f"Ã¢ÂÂ Unexpected async processing error for {sender}: {e}")
        try:
            _send_whatsapp_api(
                sender,
                body="Desculpe, estou com uma instabilidade tÃÂ©cnica. Por favor, tente novamente. Ã°ÂÂÂ"
            )
        except Exception:
            pass


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # ââ GET: Meta webhook verification âââââââââââââââââââââââââââââââ
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        token     = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
            print("\u2705 Webhook verified by Meta")
            return challenge, 200
        return "Forbidden", 403

    # ââ POST: Incoming message from Meta Cloud API âââââââââââââââââââ
    data = request.get_json(force=True, silent=True) or {}

    if data.get("object") != "whatsapp_business_account":
        return "OK", 200

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "statuses" in value and "messages" not in value:
                continue
            for msg in value.get("messages", []):
                from_number = msg.get("from", "")
                msg_type    = msg.get("type", "")
                sender = f"whatsapp:+{from_number}"
                incoming_msg = ""
                num_media    = 0
                media_id     = ""
                content_type = ""
                if msg_type == "text":
                    incoming_msg = msg.get("text", {}).get("body", "").strip()
                elif msg_type == "audio":
                    num_media = 1
                    content_type = msg.get("audio", {}).get("mime_type", "audio/ogg")
                    media_id = msg.get("audio", {}).get("id", "")
                elif msg_type == "image":
                    num_media = 1
                    content_type = msg.get("image", {}).get("mime_type", "image/jpeg")
                    incoming_msg = msg.get("image", {}).get("caption", "").strip()
                elif msg_type == "video":
                    num_media = 1
                    content_type = msg.get("video", {}).get("mime_type", "video/mp4")
                elif msg_type == "document":
                    num_media = 1
                    content_type = msg.get("document", {}).get("mime_type", "")
                elif msg_type == "sticker":
                    num_media = 1
                    content_type = "image/webp"
                elif msg_type == "reaction":
                    continue
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    itype = interactive.get("type", "")
                    if itype == "button_reply":
                        incoming_msg = interactive.get("button_reply", {}).get("title", "")
                    elif itype == "list_reply":
                        incoming_msg = interactive.get("list_reply", {}).get("title", "")
                print(f"ð© Message from {sender}: {incoming_msg!r} | type={msg_type} | media={num_media}")
                _handle_incoming(sender, incoming_msg, num_media, media_id, content_type)

    return "OK", 200


def _handle_incoming(sender: str, incoming_msg: str, num_media: int,
                     media_id: str, content_type: str):
    """Process a single incoming WhatsApp message."""
    was_audio = False

    if num_media > 0:
        if "audio" in content_type and media_id:
            print(f"ð¤ï¸ Voice note received â ContentType: {content_type}")
            if is_expo_lead(sender):
                print(f"\u23f1\ufe0f Launching async Gabriela audio processing for {sender}")
                threading.Thread(target=_process_gabriela_audio_async, args=(sender, media_id), daemon=True).start()
                return
            try:
                incoming_msg = transcribe_audio(media_id, language=None)
                was_audio = True
            except Exception as trans_err:
                print(f"\u274c Transcription failed: {trans_err}")
                send_whatsapp_meta(sender, body="Sorry, I couldn't process your voice message. Could you send it as text instead? ð")
                return
        elif not incoming_msg:
            if is_expo_lead(sender):
                send_whatsapp_meta(sender, body="Recebi seu arquivo! ð Posso te ajudar com os pacotes de v\u00eddeo da Expo Brazil?")
            else:
                send_whatsapp_meta(sender, body="Thanks for the file! How can I help you today? ð")
            return

    if is_expo_lead(sender):
        print(f"ð§ð· Routing to GABRIELA (Expo Brazil lead)")
        if sender not in gabriela_history:
            gabriela_history[sender] = []
        gabriela_history[sender].append({"role": "user", "content": incoming_msg})
        if len(gabriela_history[sender]) > 20:
            gabriela_history[sender] = gabriela_history[sender][-20:]
        try:
            reply, updated = get_gabriela_reply(gabriela_history[sender])
            gabriela_history[sender] = updated
            try:
                empresa, interesse = extract_expo_interest(reply)
                if empresa or interesse:
                    notify_michael_expo_interest(sender, empresa, interesse, incoming_msg)
            except Exception as notify_err:
                print(f"\u26a0\ufe0f Expo notify error (non-fatal): {notify_err}")
            clean_reply = clean_gabriela_response(reply)
            if was_audio:
                try:
                    audio_url = generate_audio_reply(clean_reply)
                    if audio_url:
                        send_whatsapp_meta(sender, media_url=audio_url)
                        print(f"ð Sending audio reply to {sender}")
                        return
                except Exception as tts_err:
                    print(f"\u26a0\ufe0f TTS failed, falling back to text: {tts_err}")
        except Exception as e:
            print(f"\u274c Gabriela error: {e}")
            clean_reply = "Desculpe, estou com uma instabilidade tÃ©cnica. Por favor, tente novamente em instantes. ð"
        send_whatsapp_meta(sender, body=clean_reply)
    else:
        print(f"ð¤ Routing to MAYA (async)")
        is_new_sender = sender not in conversation_history
        if is_new_sender:
            conversation_history[sender] = []
        conversation_history[sender].append({"role": "user", "content": incoming_msg})
        if is_new_sender:
            try:
                log_new_contact_to_sheets(sender)
            except Exception as e:
                print(f"\u26a0\ufe0f First-contact Sheets log error (non-fatal): {e}")
        if sender not in lead_data:
            lead_data[sender] = {}
        lead_data[sender]["last_message_time"] = datetime.now(pytz.timezone(TIMEZONE))

        # ── Slack: notify new lead ──
        if is_new_sender:
            try:
                _notify_new_lead(sender, incoming_msg)
            except Exception as slack_err:
                print(f"⚠️ Slack new lead notification failed (non-fatal): {slack_err}")

        # ── Slack: detect hot signal ──
        if _detect_hot_signal(incoming_msg):
            try:
                _ld = lead_data.get(sender, {})
                _notify_hot_signal(sender, _ld.get("name", "Unknown"), incoming_msg)
                # -- Update Google Sheet: mark as hot --
                try:
                    update_lead_columns(sender, {
                        "Lead Temperature": "Hot",
                    })
                except Exception:
                    pass
            except Exception as slack_err:
                print(f"⚠️ Slack hot signal notification failed (non-fatal): {slack_err}")
        if len(conversation_history[sender]) > 20:
            conversation_history[sender] = conversation_history[sender][-20:]
        # ── Context injection: look up lead in Google Sheet ──
        try:
            _lead_ctx = lookup_lead_in_sheets(sender)
        except Exception as _ctx_err:
            print(f"\u26a0\ufe0f Lead context lookup error (non-fatal): {_ctx_err}")
            _lead_ctx = ""

        history_snapshot = list(conversation_history[sender])

        def process_maya(snap, sndr, ctx=""):
            to_wa = sndr if sndr.startswith("whatsapp:") else f"whatsapp:{sndr}"
            try:
                reply, updated_history = get_claude_reply(snap, sndr, lead_context=ctx)
                conversation_history[sndr] = updated_history
                try:
                    lead_info = extract_lead(reply)
                    if lead_info:
                        log_lead(lead_info, sender=sndr, history=updated_history)
                        try:
                            fields = _parse_lead_fields(lead_info)
                            if sndr not in lead_data:
                                lead_data[sndr] = {}
                            lead_data[sndr].update({"name": fields.get("name", lead_data[sndr].get("name", "")), "email": fields.get("email", lead_data[sndr].get("email", ""))})
                        except Exception:
                            pass
                except Exception as lead_err:
                    print(f"\u26a0\ufe0f Lead logging error (non-fatal): {lead_err}")
                send_photos = "[SEND_STUDIO_PHOTOS]" in reply
                clean_reply = clean_response(reply)
            except Exception as e:
                print(f"\u274c Maya error: {e}")
                clean_reply = "Sorry, I'm having a technical issue right now. Please try again in a moment."
                send_photos = False
            send_whatsapp_meta(to_wa, body=clean_reply)
            print(f"\u2705 Maya reply sent to {to_wa}")
            if send_photos:
                try:
                    for photo_url in STUDIO_PHOTOS:
                        send_whatsapp_meta(to_wa, media_url=photo_url)
                    print(f"\u2705 Studio photos sent to {to_wa}")
                except Exception as photo_err:
                    print(f"\u26a0\ufe0f Could not send studio photos (non-fatal): {photo_err}")

        threading.Thread(target=process_maya, args=(history_snapshot, sender, _lead_ctx), daemon=True).start()

@app.route("/send-intro", methods=["POST"])
def send_intro():
    """
    Proactively send the expo_brazil_intro WhatsApp template to a lead via Meta Cloud API.

    Expected JSON body:
        {
            "phone": "+5511999999999",   # lead's WhatsApp number (E.164 format)
            "name":  "Carlos"            # lead's first name (fills {{1}} variable)
        }

    The template must be approved by Meta before this works for business-initiated messages.
    Template name: expo_brazil_intro (Portuguese BR)
    """
    data = request.get_json(force=True, silent=True) or {}
    phone = data.get("phone", "").strip()
    name  = data.get("name", "").strip() or "amigo"

    if not phone:
        return jsonify({"error": "Missing 'phone' field"}), 400

    # Normalize: strip whatsapp: prefix and + for Meta API
    clean_phone = phone.replace("whatsapp:", "").lstrip("+")

    if not META_ACCESS_TOKEN:
        return jsonify({"error": "META_ACCESS_TOKEN not configured"}), 500

    template_name = data.get("template_name", "expo_brazil_intro")

    try:
        url = f"https://graph.facebook.com/v19.0/{META_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {META_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
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
                        "parameters": [{"type": "text", "text": name}],
                    }
                ],
            },
        }
        resp = http_requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        msg_id = result.get("messages", [{}])[0].get("id", "")
        print(f"\u2705 Intro template sent to {clean_phone} (name={name}): {msg_id}")
        return jsonify({"success": True, "message_id": msg_id, "to": clean_phone, "name": name}), 200
    except Exception as e:
        print(f"\u274c send-intro failed: {e}")
        err_detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            err_detail = e.response.text
        return jsonify({"error": err_detail}), 500


@app.route("/", methods=["GET"])
def index():
    return "MWM Creations Sales Agent (Maya + Gabriela) is running! Ã¢ÂÂ"


# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
# COLD-LEAD DETECTION Ã¢ÂÂ Background Thread
# Checks every hour. Fires lead_cold event to Hub for any lead
# silent 48+ hours who hasn't booked and hasn't already been flagged.
# Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def _cold_lead_checker():
    import time
    print("Ã¢ÂÂÃ¯Â¸Â  Cold-lead checker started (polls every hour, fires at 48h silence)")
    time.sleep(3600)  # First check after 1 hour so startup noise settles
    while True:
        try:
            now = datetime.now(pytz.timezone(TIMEZONE))
            for phone, data in list(lead_data.items()):
                if data.get("booked") or data.get("cold_fired"):
                    continue
                last_msg = data.get("last_message_time")
                if not last_msg:
                    continue
                hours_silent = (now - last_msg).total_seconds() / 3600
                if hours_silent >= 48:
                    name  = data.get("name") or ""
                    email = data.get("email") or ""
                    print(f"Ã¢ÂÂÃ¯Â¸Â  Cold lead detected: {phone} ({int(hours_silent)}h silent) Ã¢ÂÂ firing Hub event")
                    fire_hub_event(
                        event_type = "lead_cold",
                        lead_name  = name or None,
                        lead_phone = phone,
                        lead_email = email or None,
                        payload    = {"hours_silent": int(hours_silent)},
                        notes      = f"Lead has not replied in {int(hours_silent)} hours",
                    )
                    lead_data[phone]["cold_fired"] = True
                    # ── Update Google Sheet: mark as cold ──
                    try:
                        update_lead_columns(f"whatsapp:+{phone}", {
                            "WhatsApp Status": "Cold - No Reply",
                            "Lead Temperature": "Cold",
                        })
                    except Exception:
                        pass
                    # Notify Slack of cold lead
                    try:
                        _notify_cold_lead(phone, name, last_msg, int(hours_silent))
                    except Exception as slack_err:
                        print(f"⚠️ Slack cold lead notification failed (non-fatal): {slack_err}")
        except Exception as e:
            print(f"Ã¢ÂÂ Ã¯Â¸Â  Cold-lead checker error: {e}")
        time.sleep(3600)  # Check again in 1 hour

threading.Thread(target=_cold_lead_checker, daemon=True).start()



# ── Slack Events API: Real-Time Agent Responsiveness ─────────────────────────────
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

# Channel → Agent routing (all 9 MWM agents)
AGENT_CHANNELS = {
    "C0AR7NY6SHF": {"name": "DEV", "role": "Developer Agent — builds custom integrations, skills, and automations", "channel": "#dev"},
    "C0APE9EJ2CT": {"name": "MATT", "role": "AI Operations Manager — coordinates all agents and assigns tasks", "channel": "#matt"},
    "C0APE5V3U2F": {"name": "ANA", "role": "Personal Assistant — manages calendar, reminders, and personal tasks", "channel": "#ana"},
    "C0APQ4TDF7W": {"name": "SUSAN", "role": "Email Marketing Agent — creates and manages email campaigns", "channel": "#susan"},
    "C0APE5S76HH": {"name": "MAYA (Slack)", "role": "Sales Agent — handles lead outreach and follow-ups via Slack directives", "channel": "#maya"},
    "C0ART65SU8Y": {"name": "VICTOR", "role": "MWM Screens Support — manages digital signage and screen content", "channel": "#victor"},
    "C0APLH98ANN": {"name": "ROB", "role": "Financial Advisor — handles invoicing, budgets, and financial planning", "channel": "#rob"},
    "C0APJF77MB8": {"name": "CRIS", "role": "Website Developer — builds and maintains websites", "channel": "#cris"},
    "C0APZEBQ4P3": {"name": "ERIC", "role": "Traffic Manager — manages paid ads, SEO, and digital marketing campaigns", "channel": "#eric"},
}

# #general channel — mention-based multi-agent routing
GENERAL_CHANNEL_ID = "C01N06A94SH"

# Map @mention keywords → agent channel IDs (for routing in #general)
AGENT_MENTION_MAP = {
    "dev": "C0AR7NY6SHF",
    "matt": "C0APE9EJ2CT",
    "ana": "C0APE5V3U2F",
    "susan": "C0APQ4TDF7W",
    "maya": "C0APE5S76HH",
    "victor": "C0ART65SU8Y",
    "rob": "C0APLH98ANN",
    "cris": "C0APJF77MB8",
    "eric": "C0APZEBQ4P3",
}

def _parse_agent_mentions(text):
    """Extract @agent mentions from message text.
    Returns list of (agent_name, agent_channel_id) tuples.
    Matches: @dev, @DEV, @Dev, @maya, @MAYA, etc.
    """
    mentions = []
    seen = set()
    for match in re.finditer(r"@(\w+)", text):
        name = match.group(1).lower()
        if name in AGENT_MENTION_MAP and name not in seen:
            seen.add(name)
            mentions.append((name, AGENT_MENTION_MAP[name]))
    return mentions


def _handle_general_agent_message(channel_id, text, user_id, agent_channel_id, thread_ts):
    """Handle a mention-routed message in #general.
    Runs the agent as if it received the message in its own channel,
    but posts the reply as a thread in #general.
    """
    agent = AGENT_CHANNELS.get(agent_channel_id)
    if not agent:
        return

    try:
        # Strip @mentions from the text so the agent sees a clean message
        clean_text = re.sub(r"@(\w+)", "", text).strip()
        if not clean_text:
            clean_text = text  # fallback if stripping removed everything

        # ── ANA Calendar Action Check (reuse from dedicated channel) ──
        if agent["name"] == "ANA":
            handled, calendar_result = handle_calendar_action(clean_text)
            if handled:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=get_agent_system_prompt(agent) + "\nYou are responding in #general because you were @mentioned. Keep your response focused and relevant.",
                    messages=[
                        {"role": "user", "content": clean_text},
                        {"role": "assistant", "content": f"[CALENDAR ACTION RESULT]\n{calendar_result}"},
                        {"role": "user", "content": "Present the above calendar result naturally as ANA. Keep it concise."},
                    ]
                )
                reply = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        reply += block.text
                if not reply:
                    reply = calendar_result or "I processed your calendar request but couldn't generate a response."
                _post_general_reply(channel_id, reply, agent, thread_ts)
                return

        # ── MAYA Action Check (reuse from dedicated channel) ──
        if agent["name"] == "MAYA (Slack)":
            handled, action_result, handoff_msg = handle_maya_action(clean_text)
            if handled:
                if handoff_msg:
                    try:
                        post_to_slack("C0APE5V3U2F", handoff_msg)
                    except Exception as e:
                        print(f"[MAYA] Handoff posting error from #general: {e}")
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=get_agent_system_prompt(agent) + "\nYou are responding in #general because you were @mentioned. Keep your response focused and relevant.",
                    messages=[
                        {"role": "user", "content": clean_text},
                        {"role": "assistant", "content": f"[MAYA ACTION RESULT]\n{action_result}"},
                        {"role": "user", "content": "Present the above action result naturally as Maya. Keep it concise."},
                    ]
                )
                reply = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        reply += block.text
                if not reply:
                    reply = action_result or "I processed your request but couldn't generate a response."
                _post_general_reply(channel_id, reply, agent, thread_ts)
                return

        # ── Standard Agent Response ──
        conversation = [{"role": "user", "content": clean_text}]
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=get_agent_system_prompt(agent) + "\nYou are responding in #general because you were @mentioned. Keep your response focused and relevant. Only address what's in your domain.",
            messages=conversation,
        )

        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        if not reply:
            reply = "I received your message but couldn't generate a response."

        _post_general_reply(channel_id, reply, agent, thread_ts)

    except Exception as e:
        print(f"❌ Error in {agent['name']} #general response: {e}")
        _post_general_reply(channel_id, f"⚠️ Error processing message: {str(e)[:200]}", agent, thread_ts)


def _post_general_reply(channel_id, text, agent, thread_ts):
    """Post an agent's reply in #general as a thread reply, prefixed with the agent name."""
    prefixed = f"*{agent['name']}:*\n{text}"
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"channel": channel_id, "text": prefixed, "thread_ts": thread_ts}
    http_requests.post(url, headers=headers, json=payload, timeout=10)


# Track processed event IDs to prevent duplicate processing
_processed_slack_events = set()


def verify_slack_signature(req):
    """Verify that the request came from Slack using HMAC-SHA256 signing secret."""
    if not SLACK_SIGNING_SECRET:
        print("\u26a0\ufe0f SLACK_SIGNING_SECRET not configured, skipping verification")
        return True  # Allow in dev mode
    try:
        timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
        if abs(time.time() - float(timestamp)) > 60 * 5:
            return False
        sig_basestring = f"v0:{timestamp}:{req.get_data(as_text=True)}"
        my_signature = "v0=" + hmac.new(
            SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        slack_signature = req.headers.get("X-Slack-Signature", "")
        return hmac.compare_digest(my_signature, slack_signature)
    except Exception as e:
        print(f"\u274c Slack signature verification error: {e}")
        return False


def get_agent_system_prompt(agent_info):
    """Generate a system prompt for a Slack agent based on their role."""
    base = f"""You are {agent_info['name']}, the {agent_info['role']} for MWM Creations & Studios, a media production company based in Orlando, FL. Owner: Michael Moraes (michael@mwmcreations.com).

You are responding to messages in the {agent_info['channel']} Slack channel.

MATT is the AI Operations Manager who coordinates all agents. When MATT posts a directive, acknowledge it and take action or outline your plan.

Guidelines:
- Be concise and professional
- Use Slack markdown: *bold*, _italic_, `code`, ```code blocks```
- Confirm receipt of tasks and outline next steps
- Ask for clarification if needed
- Stay in character as {agent_info['name']}
"""

    if agent_info["name"] == "ANA":
        base += """

CALENDAR CAPABILITIES — you have LIVE access to the MWM CREATIONS Google Calendar.
You can execute these actions in real time when someone asks:
• *List events* — "what's on my calendar today?" / "show this week's schedule"
• *Check availability* — "am I free tomorrow at 2pm?" / "check availability Thursday"
• *Create events* — 'schedule a "Team Meeting" tomorrow at 3pm for 2 hours'
• *Find free time* — "when is my next free slot?" / "find me some open time"
• *Delete events* — 'cancel the "Team Meeting"' / "remove my 3pm appointment"
• *Update events* — 'reschedule "Team Meeting" to Friday at 10am'

When a calendar action is detected, it executes automatically. You will receive the result as a [CALENDAR ACTION RESULT] and should present it naturally.
For event creation, encourage users to put event names in "quotes" and specify date + time.
The calendar timezone is America/New_York (EDT).

CRITICAL: NEVER tell the user you created, deleted, or modified a calendar event unless you received a [CALENDAR ACTION RESULT] confirming the action was executed. If someone asks you to do a calendar action and you don't receive a [CALENDAR ACTION RESULT], tell them you couldn't process the request automatically and ask them to rephrase with a clear command like: schedule a "Meeting Name" tomorrow at 2pm for 1 hour.
"""

    if agent_info["name"] == "MAYA (Slack)":
        base += """

REAL-TIME ACTION CAPABILITIES — you can execute these from Slack:

📊 *Pipeline & Leads (Google Sheets)*
• Pipeline summary — "What's the pipeline status?" / "How are our leads?"
• Look up a lead — "Look up RJ" / "What do we have on One Stop Financial?"
• Update lead status — "Update RJ to Hot" / "Mark One Stop Financial as Warm"
• Log outreach — "Log LinkedIn DM to Jeremy Tucker" / "Log email to One Stop Financial"
• Add new lead — "Add lead: John Smith, 555-1234, interested in studio"

🔥 *ANA Handoff*
• Hand off hot leads — "Hand off RJ to Ana — he's ready to book"
  This posts a structured handoff to #ana with lead details.

📅 *Calendar Check*
• Check availability — "Is Michael free Thursday at 2pm?"

When an action is detected, it executes automatically against the Google Sheets lead tracker or calendar. You will receive the result as a [MAYA ACTION RESULT] and should present it naturally.

CRITICAL: NEVER tell the user you executed a sheets update, handoff, or calendar check unless you received a [MAYA ACTION RESULT] confirming the action was executed. If no result was received, tell them you couldn't process the request automatically and ask them to rephrase.
"""

    return base
def _get_slack_history(channel_id, limit=10):
    """Fetch recent Slack messages and build Claude conversation history."""
    try:
        url = "https://slack.com/api/conversations.history"
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        resp = http_requests.get(url, headers=headers, params={"channel": channel_id, "limit": limit}, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            print(f"[SLACK] History fetch failed: {data.get('error')}")
            return []
        messages = []
        for msg in reversed(data.get("messages", [])):
            msg_text = msg.get("text", "").strip()
            if not msg_text or msg.get("subtype"):
                continue
            # Bot messages have bot_id; user messages have user field without bot_id
            if msg.get("bot_id"):
                messages.append({"role": "assistant", "content": msg_text})
            else:
                messages.append({"role": "user", "content": msg_text})
        # Claude requires alternating roles — merge consecutive same-role messages
        merged = []
        for m in messages:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] += "\n" + m["content"]
            else:
                merged.append(dict(m))
        # Must start with user and end with user
        if merged and merged[0]["role"] == "assistant":
            merged = merged[1:]
        if merged and merged[-1]["role"] == "assistant":
            merged = merged[:-1]
        return merged
    except Exception as e:
        print(f"[SLACK] Error fetching history: {e}")
        return []


def _handle_slack_agent_message(channel_id, text, user_id, thread_ts=None):
    """Process a Slack message in a background thread and post the agent's response."""
    agent = AGENT_CHANNELS.get(channel_id)
    if not agent:
        return

    try:
        # ── ANA Calendar Action Check ─────────────────────────────
        if agent["name"] == "ANA":
            handled, calendar_result = handle_calendar_action(text)
            # Fetch conversation history for context (helps classify follow-up messages like "do it", "yes", etc.)
            conversation_history = _get_slack_history(channel_id, limit=10)
            # ── Follow-up confirmation fast path ──────────────────────
            # Detects short confirmations ("do it", "yes", "perfect") when ANA just
            # suggested a calendar action. Uses Haiku to extract full event details
            # from conversation context instead of relying on regex parsing.
            _CONFIRM_RE = re.compile(
                r"^(?:do it|yes|yep|yeah|yea|sure|ok|okay|go ahead|perfect|"
                r"confirm(?:ed)?|correct|right|absolutely|let.?s do it|book it|"
                r"that.?s (?:correct|right|it|good|great|fine)|looks? (?:good|great|correct|right)|"
                r"sim|faz isso|pode fazer|manda|bora|perfeito|isso|pode ser|"
                r"faz|manda ver|pode|bora l[aá])[\s.!]*$",
                re.IGNORECASE,
            )
            if not handled and _CONFIRM_RE.match(text.strip()):
                # Check if last bot message suggested a calendar action
                last_bot_msg = None
                for m in reversed(conversation_history):
                    if m["role"] == "assistant":
                        last_bot_msg = m["content"]
                        break
                cal_keywords = ["event", "calendar", "schedule", "book", "create",
                                "reminder", "shoot", "meeting", "grava", "reuni"]
                if last_bot_msg and any(kw in last_bot_msg.lower() for kw in cal_keywords):
                    try:
                        print(f"[ANA] Confirmation fast-path triggered for: {text}")
                        confirm_resp = client.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=400,
                            system="""You are extracting calendar event details from a conversation where the user just CONFIRMED they want to proceed with a suggested calendar action.

Extract ALL event details from the conversation and output a single clear English calendar command. Include:
- Event title (in quotes)
- Date (use "today", "tomorrow", or specific date)
- Time (e.g., "at 9am")
- Duration (e.g., "for 1 hour") — if not specified, omit
- Location/address (e.g., "at 123 Main St") — if mentioned
- Reminder (e.g., "with 1 hour reminder") — if mentioned

IMPORTANT: You MUST include ALL details discussed in the conversation, especially location and reminder.

Example outputs:
- schedule a "Team Meeting" tomorrow at 3pm for 1 hour at 123 Main St Orlando FL with 30 minute reminder
- schedule a "GRAVAÇÃO — Green Rest Mattress" tomorrow at 9am at 4868 E Colonial Dr Orlando FL 32803 with 1 hour reminder

Output ONLY the command string, nothing else.""",
                            messages=conversation_history + [{"role": "user", "content": text}],
                        )
                        confirm_cmd = ""
                        for block in confirm_resp.content:
                            if hasattr(block, "text"):
                                confirm_cmd += block.text
                        confirm_cmd = confirm_cmd.strip()
                        if confirm_cmd and "schedule" in confirm_cmd.lower():
                            print(f"[ANA] Confirmation fast-path command: {confirm_cmd}")
                            handled, calendar_result = handle_calendar_action(confirm_cmd)
                    except Exception as e:
                        print(f"[ANA] Confirmation fast-path error: {e}")

            # Fallback: if regex didn't match, use Claude to classify + translate (handles Portuguese, mixed language, etc.)
            if not handled:
                try:
                    cls_response = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=300,
                        system="""You classify whether a message is a calendar/scheduling action request. The message may be in ANY language (Portuguese, English, Spanish, etc.).
You will also receive recent conversation history for context.

IMPORTANT: These are ALL calendar actions when the conversation context shows a pending calendar operation:
- Confirmations: "yes", "do it", "perfect", "go ahead", "sim", "faz isso"
- Corrections: "I said 5pm", "no, at 3pm", "I meant Thursday", "não, às 17h"
- Modifications: "change it to 5pm", "make it Friday", "move to 3pm"

For corrections/modifications, combine the ORIGINAL event details from conversation context with the corrected detail. Output the full create command with ALL details including the corrected field.

If it IS a calendar action, respond with ONLY valid JSON:
{"action": "create_event", "command": "<English calendar command>"}

The "command" must be a clear English instruction using these patterns:
- For creating: schedule a "Event Title" today/tomorrow at 2pm for 1 hour
- For listing: what is on my calendar today/this week
- For availability: am I free tomorrow at 3pm
- For finding free time: find free time this week
- For deleting: cancel the "Event Title"
- For updating: reschedule "Event Title" to Friday at 10am

Put the event name in quotes. Use "today", "tomorrow", or specific dates. Always include the time if mentioned.

If it is NOT a calendar action, respond with: {"action": "none"}""",
                        messages=[{"role": "user", "content": f"RECENT CONVERSATION:\n" + "\n".join([f'{m["role"].upper()}: {m["content"][:200]}' for m in conversation_history[-6:]]) + f"\n\nCURRENT MESSAGE TO CLASSIFY:\n{text}"}]
                    )
                    import json as _json
                    cls_text = ""
                    for block in cls_response.content:
                        if hasattr(block, "text"):
                            cls_text += block.text
                    cls_text = cls_text.strip()
                    # Strip markdown code fences if present
                    if cls_text.startswith("```"):
                        lines = cls_text.split("\n")
                        cls_text = "\n".join(lines[1:])
                        if cls_text.endswith("```"):
                            cls_text = cls_text[:-3].strip()
                    # Try to find JSON object in response
                    if not cls_text.startswith("{"):
                        json_start = cls_text.find("{")
                        if json_start != -1:
                            json_end = cls_text.rfind("}") + 1
                            if json_end > json_start:
                                cls_text = cls_text[json_start:json_end]
                    print(f"[ANA] Haiku classifier raw response: {cls_text[:200]}")
                    if cls_text:
                        cls_data = _json.loads(cls_text)
                        if cls_data.get("action") != "none" and cls_data.get("command"):
                            print(f"[ANA] Claude classified as calendar action: {cls_data}")
                            handled, calendar_result = handle_calendar_action(cls_data["command"])
                    else:
                        print("[ANA] Haiku classifier returned empty response")
                except Exception as e:
                    print(f"[ANA] Calendar classification fallback error: {e}")
            if handled:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=get_agent_system_prompt(agent),
                    messages=[
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": f"[CALENDAR ACTION RESULT]\n{calendar_result}"},
                        {"role": "user", "content": "Present the above calendar result naturally as ANA. Keep it concise — the data is already formatted. Add a brief friendly note if appropriate, but don't repeat all the data verbatim. If the result shows an error, offer to help troubleshoot."},
                    ]
                )
                reply = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        reply += block.text
                if not reply:
                    reply = calendar_result if calendar_result else "I processed your calendar request but couldn't generate a response. Could you try again?"
                if thread_ts:
                    url = "https://slack.com/api/chat.postMessage"
                    headers = {
                        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                        "Content-Type": "application/json"
                    }
                    payload = {"channel": channel_id, "text": reply, "thread_ts": thread_ts}
                    http_requests.post(url, headers=headers, json=payload, timeout=10)
                else:
                    post_to_slack(channel_id, reply)
                return

        # ── MAYA Action Check ─────────────────────────────────────
        if agent["name"] == "MAYA (Slack)":
            handled, action_result, handoff_msg = handle_maya_action(text)

            # Fallback: use Haiku to classify if regex didn't match
            if not handled:
                try:
                    conversation_history = _get_slack_history(channel_id, limit=10)
                    cls_response = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=300,
                        system="""You classify whether a message is a Maya sales action request. Maya handles:
1. Pipeline/lead status summary
2. Looking up a lead by name or phone
3. Updating a lead's status (Hot/Warm/Cold/etc.)
4. Logging outreach activity
5. Adding a new lead
6. Handing off a lead to ANA for booking
7. Checking calendar availability

If it IS a Maya action, respond with ONLY valid JSON:
{"action": "<action_type>", "command": "<clear English command>"}

action_type must be one of: pipeline_summary, lookup_lead, update_lead_status, log_outreach, add_lead, handoff_to_ana, check_availability

The "command" should rephrase the user's message as a clear English instruction Maya can parse.
Examples:
- "How's the pipeline?" → {"action": "pipeline_summary", "command": "pipeline status"}
- "Move RJ to Hot" → {"action": "update_lead_status", "command": "update RJ to Hot"}
- "Pass RJ to Ana" → {"action": "handoff_to_ana", "command": "hand off RJ to Ana"}
- "Is Michael free at 2pm Thursday?" → {"action": "check_availability", "command": "is Michael free Thursday at 2pm"}

If it is NOT a Maya action, respond with: {"action": "none"}""",
                        messages=[{"role": "user", "content": text}]
                    )
                    import json as _json
                    cls_text = ""
                    for block in cls_response.content:
                        if hasattr(block, "text"):
                            cls_text += block.text
                    cls_text = cls_text.strip()
                    if cls_text.startswith("```"):
                        lines_raw = cls_text.split("\n")
                        cls_text = "\n".join(lines_raw[1:])
                        if cls_text.endswith("```"):
                            cls_text = cls_text[:-3].strip()
                    if not cls_text.startswith("{"):
                        json_start = cls_text.find("{")
                        if json_start != -1:
                            json_end = cls_text.rfind("}") + 1
                            if json_end > json_start:
                                cls_text = cls_text[json_start:json_end]
                    print(f"[MAYA] Haiku classifier raw response: {cls_text[:200]}")
                    if cls_text:
                        cls_data = _json.loads(cls_text)
                        if cls_data.get("action") != "none" and cls_data.get("command"):
                            print(f"[MAYA] Claude classified as action: {cls_data}")
                            handled, action_result, handoff_msg = handle_maya_action(cls_data["command"])
                except Exception as e:
                    print(f"[MAYA] Action classification fallback error: {e}")

            if handled:
                # If there's a handoff message, post it to #ana
                if handoff_msg:
                    try:
                        post_to_slack("C0APE5V3U2F", handoff_msg)  # #ana channel
                        print(f"[MAYA] Handoff posted to #ana")
                    except Exception as e:
                        print(f"[MAYA] Handoff posting error: {e}")
                        action_result += f"\n⚠️ _Note: Could not post handoff to #ana: {str(e)[:100]}_"

                # Present the result naturally through Maya
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=get_agent_system_prompt(agent),
                    messages=[
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": f"[MAYA ACTION RESULT]\n{action_result}"},
                        {"role": "user", "content": "Present the above action result naturally as Maya. Keep it concise — the data is already formatted. Don't repeat all the data verbatim. If the result shows an error, offer to help troubleshoot."},
                    ]
                )
                reply = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        reply += block.text
                if not reply:
                    reply = action_result if action_result else "I processed your request but couldn't generate a response. Could you try again?"
                if thread_ts:
                    url = "https://slack.com/api/chat.postMessage"
                    headers = {
                        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                        "Content-Type": "application/json"
                    }
                    payload = {"channel": channel_id, "text": reply, "thread_ts": thread_ts}
                    http_requests.post(url, headers=headers, json=payload, timeout=10)
                else:
                    post_to_slack(channel_id, reply)
                return

        # ── Standard Agent Response ──────────────────────────────
        # Build conversation history from recent Slack messages for context
        conversation = _get_slack_history(channel_id, limit=10)
        if not conversation or conversation[-1].get("content") != text:
            # Ensure current message is included at the end
            conversation.append({"role": "user", "content": text})
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=get_agent_system_prompt(agent),
            messages=conversation if conversation else [{"role": "user", "content": text}]
        )

        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        if not reply:
            reply = "I received your message but couldn't generate a response."

        # Reply in thread if the original message was in a thread
        if thread_ts:
            # Post as thread reply
            url = "https://slack.com/api/chat.postMessage"
            headers = {
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {"channel": channel_id, "text": reply, "thread_ts": thread_ts}
            http_requests.post(url, headers=headers, json=payload, timeout=10)
        else:
            post_to_slack(channel_id, reply)

        print(f"\u2705 {agent['name']} responded in {agent['channel']}")

    except Exception as e:
        print(f"\u274c Error in {agent['name']} agent response: {e}")
        post_to_slack(channel_id, f"\u26a0\ufe0f Error processing message: {str(e)[:200]}")


@app.route("/slack/events", methods=["POST"])
def slack_events():
    """Handle Slack Events API callbacks for real-time agent responsiveness."""
    data = request.get_json(force=True, silent=True) or {}

    # URL verification challenge (one-time setup by Slack)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge", "")})

    # Verify request signature
    if not verify_slack_signature(request):
        return "Unauthorized", 401

    # Deduplicate events (Slack may retry)
    event_id = data.get("event_id", "")
    if event_id in _processed_slack_events:
        return "OK", 200
    _processed_slack_events.add(event_id)
    # Keep the set from growing forever (cap at 1000)
    if len(_processed_slack_events) > 1000:
        _processed_slack_events.clear()

    # Handle event callbacks
    if data.get("type") == "event_callback":
        event = data.get("event", {})

        # Only handle regular message events (no subtypes like bot_message, message_changed, etc.)
        if event.get("type") != "message" or event.get("subtype"):
            return "OK", 200

        # Ignore bot messages to prevent infinite loops
        if event.get("bot_id"):
            return "OK", 200

        channel_id = event.get("channel", "")
        text = event.get("text", "")
        user_id = event.get("user", "")
        thread_ts = event.get("thread_ts")

        # ── #general: mention-based multi-agent routing ──
        if channel_id == GENERAL_CHANNEL_ID and text.strip():
            mentions = _parse_agent_mentions(text)
            if mentions:
                # Use the message's own ts as thread parent (so all agent replies group under it)
                msg_ts = event.get("ts", "")
                parent_ts = thread_ts or msg_ts
                for agent_name, agent_channel_id in mentions:
                    print(f"[#general] Routing to {agent_name.upper()} (mentioned)")
                    threading.Thread(
                        target=_handle_general_agent_message,
                        args=(channel_id, text, user_id, agent_channel_id, parent_ts),
                        daemon=True
                    ).start()

        # ── Dedicated agent channels: direct routing ──
        elif channel_id in AGENT_CHANNELS and text.strip():
            threading.Thread(
                target=_handle_slack_agent_message,
                args=(channel_id, text, user_id, thread_ts),
                daemon=True
            ).start()

    return "OK", 200


if __name__ == "__main__":
    print("Starting MWM Creations Sales Agent Ã¢ÂÂ Maya")
    print("Server running on http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
