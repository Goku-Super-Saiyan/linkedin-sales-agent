import io

from PIL import Image

from agent.images import render_card


def test_card_is_a_square_png_in_brand_colours():
    png = render_card("Agentforce now handles routine service cases at mid-sized companies", "Industry news")
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.size == (1200, 1200)
    assert image.getpixel((5, 5)) == (11, 37, 69)  # #0B2545


def test_card_takes_brand_overrides_and_long_text():
    png = render_card("word " * 60, brand={"background": "#FFFFFF", "name": "Test"})
    assert Image.open(io.BytesIO(png)).getpixel((5, 5)) == (255, 255, 255)
