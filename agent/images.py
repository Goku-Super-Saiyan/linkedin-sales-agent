"""Branded picture cards: the post's key line in large type on the company's colours.

The card is drawn again from the sheet's "Picture" text each time it's needed, so no image files
have to be stored anywhere. Fonts are Inter (SIL Open Font License, see assets/fonts).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
SIZE = 1200
MARGIN = 96

DEFAULT_BRAND = {
    "name": "360 Degree Cloud",
    "background": "#0B2545",
    "accent": "#1B9AF5",
    "text": "#FFFFFF",
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def render_card(text: str, label: str = "", brand: dict | None = None) -> bytes:
    """A 1200x1200 PNG with `text` as the headline and `label` (for example the pillar) above it."""
    brand = {**DEFAULT_BRAND, **(brand or {})}
    image = Image.new("RGB", (SIZE, SIZE), brand["background"])
    draw = ImageDraw.Draw(image)
    width = SIZE - 2 * MARGIN

    # Top: accent bar and the label.
    draw.rectangle([MARGIN, MARGIN, MARGIN + 120, MARGIN + 12], fill=brand["accent"])
    if label:
        draw.text((MARGIN, MARGIN + 44), label.upper(), font=_font("Bold", 34), fill=brand["accent"])

    # Middle: the headline, as large as fits in the space between the label and the footer.
    top, bottom = MARGIN + 140, SIZE - MARGIN - 120
    for size in range(96, 39, -4):
        font = _font("Bold", size)
        lines = _wrap(draw, text.strip(), font, width)
        line_height = int(size * 1.22)
        if len(lines) * line_height <= bottom - top and all(draw.textlength(l, font=font) <= width for l in lines):
            break
    y = top + (bottom - top - len(lines) * line_height) // 2
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=brand["text"])
        y += line_height

    # Bottom: a thin rule and the company name.
    draw.line([MARGIN, SIZE - MARGIN - 70, SIZE - MARGIN, SIZE - MARGIN - 70], fill=brand["accent"], width=3)
    draw.text((MARGIN, SIZE - MARGIN - 44), brand["name"], font=_font("Regular", 34), fill=brand["text"])

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
