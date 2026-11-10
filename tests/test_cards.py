from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from cs2_insights.cards import _fit, _plain, match_card
from cs2_insights.proof import CARD_SIZE

STATS = [("Avoidable deaths", "9 of 23"), ("Coverage", "F"), ("Buy calls right", "4 of 7"), ("Deaths traded", "0 of 23")]


def test_card_is_a_share_sized_png():
    image = Image.open(BytesIO(match_card("Dust2", "Loss", "12–16", STATS, "Round 2: should have forced", "Round 14: right call to force")))
    assert image.format == "PNG" and image.size == CARD_SIZE


def test_card_works_without_moments_or_with_long_text():
    assert match_card("Ancient", "Win", "13–3", STATS[:2], None, None)
    assert match_card("A map with a very long name indeed", "Draw", "15–15", STATS, "x" * 300, "y" * 300)


def test_long_text_is_shortened_to_fit():
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = ImageFont.load_default(30)
    short = _fit(draw, "word " * 100, font, 400)
    assert short.endswith("...") and draw.textlength(short, font=font) <= 400
    assert _fit(draw, "fits", font, 400) == "fits"


def test_characters_the_font_lacks_are_swapped_for_plain_ones():
    assert _plain("12–16 · Dust2 → done…") == "12-16 · Dust2 -> done..."
