from io import BytesIO

from PIL import Image

from og_images import create_og_image


def test_open_graph_image_has_expected_dimensions_and_png_format():
    image_data = create_og_image('Portfolio & Project', ['Python', 'Flask', 'Python'])

    with Image.open(BytesIO(image_data)) as image:
        assert image.format == 'PNG'
        assert image.size == (1200, 630)