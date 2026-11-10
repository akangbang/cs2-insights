"""A shareable image of one match: the map, the score, four numbers and the main lesson. No player names."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from cs2_insights.proof import CARD_ACCENT, CARD_BACKGROUND, CARD_MUTED, CARD_SIZE, CARD_TEXT

TILE_FILL = "#161b22"
LEFT = 72


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    """Shorten `text` with an ellipsis until it fits in `width` pixels."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def match_card(map_name: str, result: str, score: str, stats: list[tuple[str, str]], fix: str | None, best: str | None) -> bytes:
    """`stats` are up to four (label, value) pairs; `fix` and `best` are one-line moments."""
    image = Image.new("RGB", CARD_SIZE, CARD_BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default
    width = CARD_SIZE[0] - 2 * LEFT
    draw.rectangle((0, 0, 14, CARD_SIZE[1]), fill=CARD_ACCENT)
    draw.text((LEFT, 44), "Getleanpeek", font=font(34), fill=CARD_MUTED)
    draw.text((LEFT, 96), _fit(draw, f"{map_name} · {result} {score}", font(64), width), font=font(64), fill=CARD_TEXT)

    gap = 24
    tile = (width - gap * 3) / 4
    for i, (label, value) in enumerate(stats[:4]):
        x = LEFT + i * (tile + gap)
        draw.rounded_rectangle((x, 204, x + tile, 364), radius=16, fill=TILE_FILL)
        draw.text((x + 22, 224), _fit(draw, label, font(24), tile - 44), font=font(24), fill=CARD_MUTED)
        draw.text((x + 22, 268), _fit(draw, value, font(60), tile - 44), font=font(60), fill=CARD_TEXT)

    y = 404
    for title, text in (("Fix next", fix or "Nothing costly: a clean match"), ("Best moment", best)):
        if not text:
            continue
        draw.text((LEFT, y), title, font=font(26), fill=CARD_ACCENT)
        draw.text((LEFT, y + 36), _fit(draw, text, font(36), width), font=font(36), fill=CARD_TEXT)
        y += 100
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
