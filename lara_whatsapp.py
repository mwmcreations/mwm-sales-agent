"""
LARA WhatsApp Media Module — send text, images, videos, documents via Meta Cloud API.

Extends the base send_whatsapp_meta with typed media helpers and
a media URL builder for the /media/<filename> static route.
"""

import os
import requests as http_requests

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
# LARA_PHONE_NUMBER_ID — Phone number ID for the LARA WhatsApp sender
# (+1 407-537-7207). LARA is multi-tenant on the same WABA as Maya, but
# sends FROM her own Meta number, so this module always uses LARA's PNID.
LARA_PHONE_NUMBER_ID = os.getenv("LARA_PHONE_NUMBER_ID", "")
LARA_MEDIA_BASE_URL = os.getenv("LARA_MEDIA_BASE_URL", "")

WA_API_URL = f"https://graph.facebook.com/v19.0/{LARA_PHONE_NUMBER_ID}/messages"


def _wa_headers():
    return {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _send(payload):
    """Send a WhatsApp payload and return the API response."""
    try:
        resp = http_requests.post(WA_API_URL, json=payload, headers=_wa_headers(), timeout=30)
        resp.raise_for_status()
        print(f"✅ WhatsApp message sent: {payload.get('type', '?')}")
        return resp.json()
    except Exception as e:
        print(f"❌ WhatsApp send failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def send_text_message(to: str, body: str):
    """Send a plain text message."""
    phone = to.replace("whatsapp:", "").lstrip("+")
    return _send({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": body},
    })


def send_image(to: str, image_url: str, caption: str = ""):
    """Send an image with optional caption."""
    phone = to.replace("whatsapp:", "").lstrip("+")
    img_payload = {"link": image_url}
    if caption:
        img_payload["caption"] = caption
    return _send({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "image",
        "image": img_payload,
    })


def send_video(to: str, video_url: str, caption: str = ""):
    """Send a video with optional caption."""
    phone = to.replace("whatsapp:", "").lstrip("+")
    vid_payload = {"link": video_url}
    if caption:
        vid_payload["caption"] = caption
    return _send({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "video",
        "video": vid_payload,
    })


def send_document(to: str, document_url: str, filename: str = "", caption: str = ""):
    """Send a document (PDF, etc.) with optional filename and caption."""
    phone = to.replace("whatsapp:", "").lstrip("+")
    doc_payload = {"link": document_url}
    if filename:
        doc_payload["filename"] = filename
    if caption:
        doc_payload["caption"] = caption
    return _send({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "document",
        "document": doc_payload,
    })


def send_media_message(to: str, media_url: str, caption: str = "", filename: str = ""):
    """Auto-detect media type and send appropriately."""
    ml = media_url.lower()
    if any(ml.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return send_image(to, media_url, caption)
    elif any(ml.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".3gp")):
        return send_video(to, media_url, caption)
    elif any(ml.endswith(ext) for ext in (".mp3", ".ogg", ".wav", ".amr", ".m4a", ".opus")):
        return _send({
            "messaging_product": "whatsapp",
            "to": to.replace("whatsapp:", "").lstrip("+"),
            "type": "audio",
            "audio": {"link": media_url},
        })
    else:
        return send_document(to, media_url, filename=filename or media_url.split("/")[-1], caption=caption)


def media_url(filename: str) -> str:
    """Build a public URL for a file in the /media/ directory."""
    base = LARA_MEDIA_BASE_URL.rstrip("/")
    if not base:
        return ""
    return f"{base}/media/{filename}"
