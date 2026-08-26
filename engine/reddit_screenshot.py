"""Rendu d'un post Reddit façon « screenshot » (mode sombre) avec Pillow.

Reproduit le look d'une capture d'écran du post Reddit (comme RedditVideoMakerBot
via Playwright), mais SANS toucher à Reddit : on dessine la carte du post
localement à partir du texte fourni. RGBA → coins arrondis transparents pour
que le fond gameplay apparaisse autour/derrière la carte.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# Couleurs Reddit dark mode
BG = (26, 26, 27, 255)            # #1a1a1b  (fond de carte)
TEXT = (215, 218, 220, 255)       # #d7dadc  (texte principal)
TEXT_SEC = (129, 131, 132, 255)   # #818384  (texte secondaire)
SEP = (52, 53, 54, 255)           # #343536  (séparateurs)
UPVOTE = (255, 69, 0, 255)        # #ff4500  (orange)
DOWNVOTE = (113, 147, 255, 255)   # #7193ff  (bleu)

_WEIGHTS = {"regular": "Roboto-Regular.ttf", "bold": "Roboto-Bold.ttf", "medium": "Roboto-Medium.ttf"}


def _font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / _WEIGHTS[weight]), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Retour à la ligne selon la largeur réelle en pixels."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _avatar_color(seed: str) -> tuple[int, int, int]:
    palette = [(255, 69, 0), (0, 121, 211), (113, 147, 255), (72, 187, 120),
               (255, 160, 0), (148, 101, 255), (237, 69, 92), (0, 200, 200)]
    return palette[sum(seed.encode()) % len(palette)]


def _draw_arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, up: bool, color) -> None:
    """Triangle pointe en haut (up=True) ou en bas."""
    half = size // 2
    if up:
        pts = [(cx, cy - half), (cx - half, cy + half), (cx + half, cy + half)]
    else:
        pts = [(cx, cy + half), (cx - half, cy - half), (cx + half, cy - half)]
    draw.polygon(pts, fill=color)


def render_reddit_post(
    title: str,
    body: str,
    subreddit: str = "AmItheAsshole",
    username: str = "throwaway_account",
    upvotes: int = 12800,
    comments: int = 342,
    age: str = "5h ago",
    width: int = 1000,
    title_size: int = 46,
    body_size: int = 34,
) -> Image.Image:
    """Dessine la carte du post Reddit (RGBA, coins arrondis) et la renvoie."""
    pad_x = 44
    pad_top = 36
    inner_w = width - 2 * pad_x

    draw_tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    font_title = _font(title_size, "bold")
    font_body = _font(body_size, "regular")
    font_meta = _font(24, "medium")
    font_meta_sec = _font(22, "regular")
    font_stats = _font(26, "medium")

    title_lines = _wrap(draw_tmp, title, font_title, inner_w)
    body_lines = _wrap(draw_tmp, body, font_body, inner_w)

    line_h_title = title_size + 12
    line_h_body = body_size + 10

    # hauteur de la carte
    header_h = 88          # avatar + r/subreddit + u/username
    title_h = len(title_lines) * line_h_title
    body_h = len(body_lines) * line_h_body
    footer_h = 64
    total_h = pad_top + header_h + title_h + 26 + body_h + 20 + footer_h + pad_top

    img = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # carte (coins arrondis)
    radius = 18
    draw.rounded_rectangle((0, 0, width - 1, total_h - 1), radius=radius, fill=BG)

    y = pad_top

    # --- header : avatar + r/subreddit + u/username ---
    avatar_r = 20
    av_color = _avatar_color(subreddit)
    draw.ellipse((pad_x, y, pad_x + 2 * avatar_r, y + 2 * avatar_r), fill=av_color)
    draw.text((pad_x + avatar_r, y + avatar_r - 4), subreddit[0].upper(),
              font=_font(26, "bold"), fill=(255, 255, 255, 255), anchor="mm")
    draw.text((pad_x + 2 * avatar_r + 16, y - 2), f"r/{subreddit}",
              font=font_meta, fill=TEXT)
    draw.text((pad_x + 2 * avatar_r + 16, y + 30), f"u/{username} • {age}",
              font=font_meta_sec, fill=TEXT_SEC)
    y += header_h + 8

    # séparateur
    draw.line((pad_x, y, width - pad_x, y), fill=SEP, width=2)
    y += 22

    # --- titre ---
    for line in title_lines:
        draw.text((pad_x, y), line, font=font_title, fill=TEXT)
        y += line_h_title
    y += 8

    # --- corps ---
    for line in body_lines:
        draw.text((pad_x, y), line, font=font_body, fill=TEXT)
        y += line_h_body
    y += 16

    # séparateur
    draw.line((pad_x, y, width - pad_x, y), fill=SEP, width=2)
    y += 16

    # --- footer : votes + stats ---
    _draw_arrow(draw, pad_x + 10, y + 14, 22, up=True, color=UPVOTE)
    up_txt = _fmt(upvotes)
    draw.text((pad_x + 28, y), up_txt, font=font_stats, fill=TEXT)
    up_w = int(draw.textlength(up_txt, font=font_stats))
    _draw_arrow(draw, pad_x + 28 + up_w + 30, y + 14, 22, up=False, color=DOWNVOTE)
    draw.text((pad_x + 28 + up_w + 48, y),
              f"{_fmt(comments)} comments", font=font_meta_sec, fill=TEXT_SEC)

    return img


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)
