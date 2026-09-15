"""victory_cards.py — title cards as pictures, because the Mini's ffmpeg cannot draw text.

Homebrew's ffmpeg 8 on the Mac Mini was built without freetype ("No such
filter: 'drawtext'"), so the app renders the head card and the sign-off as
transparent 1080x1920 PNGs here (Pillow + the DejaVu Bold font shipped in
victory_assets/), and the worker overlays them with a fade. Same words the
drawtext path would have used; the picture is just made on the other side.

render_card() never raises: any problem returns None and the cut ships
without that card, which is what it did before this file existed.
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "victory_assets", "DejaVuSans-Bold.ttf")
W, H = 1080, 1920
_cache = {}


def render_card(big, small, y_frac=0.40, size_big=70, size_small=42):
    """A transparent 1080x1920 PNG with two centred lines and a soft shadow."""
    key = (big, small, y_frac, size_big, size_small)
    if key in _cache:
        return _cache[key]
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f_big = ImageFont.truetype(FONT, size_big)
        f_small = ImageFont.truetype(FONT, size_small)
        y = int(H * y_frac)
        for text, font, col, dy in ((big or "", f_big, (255, 255, 255, 255), 0),
                                    (small or "", f_small, (232, 232, 232, 255), size_big + 30)):
            if not text:
                continue
            bbox = d.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            d.text((x + 3, y + dy + 3), text, font=font, fill=(0, 0, 0, 150))
            d.text((x, y + dy), text, font=font, fill=col)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _cache[key] = buf.getvalue()
        return _cache[key]
    except Exception as e:
        print("[VI-CARDS] render failed: %r" % (e,))
        return None
