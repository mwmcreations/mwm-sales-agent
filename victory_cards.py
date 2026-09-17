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
        safe = W - 120

        def width(t, f):
            b = d.textbbox((0, 0), t, font=f)
            return b[2] - b[0]

        def wrap(text, f):
            """Two balanced lines when one will not fit; three when two will
            not either (an end card with an event, a date and a place)."""
            words = text.split()
            best, best_gap = None, 10 ** 9
            for i in range(1, len(words)):
                a, b = " ".join(words[:i]), " ".join(words[i:])
                gap = abs(width(a, f) - width(b, f))
                if words[i - 1] in ("\u00b7", "-", "\u2014", "|"):      # break at a separator, and drop it
                    a, gap = " ".join(words[:i - 1]), gap - 400
                if width(a, f) <= safe and width(b, f) <= safe and gap < best_gap:
                    best, best_gap = [a, b], gap
            if best:
                return best
            for i in range(1, len(words) - 1):
                for j in range(i + 1, len(words)):
                    parts = [" ".join(words[:i]), " ".join(words[i:j]), " ".join(words[j:])]
                    if all(width(x, f) <= safe for x in parts):
                        gap = max(width(x, f) for x in parts) - min(width(x, f) for x in parts)
                        if gap < best_gap:
                            best, best_gap = parts, gap
            return best or [text]

        # lay the lines out first, so a soft dark band can sit behind them:
        # white words over a white gi and a bright hall were hard to read
        # (16 Sep self-test #8, "Learn to stand up" over the crowd)
        layout, dy, widest = [], 0, 0
        for text, font, col in ((big or "", f_big, (255, 255, 255, 255)),
                                (small or "", f_small, (232, 232, 232, 255))):
            if not text:
                continue
            # a long sentence shrinks a little, then wraps to two lines
            size = font.size
            while width(text, font) > safe * 1.6 and size > max(40, font.size - 24):
                size -= 4
                font = ImageFont.truetype(FONT, size)
            lines = [text] if width(text, font) <= safe else wrap(text, font)
            for line in lines:
                tw = width(line, font)
                layout.append((line, font, col, (W - tw) // 2, y + dy, size))
                widest = max(widest, tw)
                dy += int(size * 1.25)
            dy += 12
        if layout:
            pad_x, pad_y = 44, 28
            top = layout[0][4] - pad_y
            bottom = layout[-1][4] + int(layout[-1][5] * 1.2) + pad_y
            left = max(24, (W - widest) // 2 - pad_x)
            band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(band).rounded_rectangle((left, top, W - left, bottom), radius=28,
                                                   fill=(0, 0, 0, 118))
            img.alpha_composite(band)
            d = ImageDraw.Draw(img)
        for line, font, col, x, yy, size in layout:
            d.text((x + 3, yy + 3), line, font=font, fill=(0, 0, 0, 150))
            d.text((x, yy), line, font=font, fill=col)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _cache[key] = buf.getvalue()
        return _cache[key]
    except Exception as e:
        print("[VI-CARDS] render failed: %r" % (e,))
        return None
