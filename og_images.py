import unicodedata
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

IMAGE_SIZE = (1200, 630)


def _plain_text(value):
    return unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')


def _wrap_text(draw, value, font, max_width, limit=3):
    lines = []
    current = ''
    for word in _plain_text(value).split():
        candidate = f'{current} {word}'.strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = f'{lines[-1].rstrip(".,:;-")}...'
    return lines


def create_og_image(title, technologies=(), author='Al-ameen Olanrewaju'):
    image = Image.new('RGB', IMAGE_SIZE, (16, 30, 26))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 13, IMAGE_SIZE[1]), fill=(213, 115, 72))
    draw.rectangle((817, 0, IMAGE_SIZE[0], IMAGE_SIZE[1]), fill=(24, 49, 40))
    for x in range(850, 1200, 52):
        draw.line((x, 0, x, 630), fill=(31, 60, 48), width=1)
    for y in range(0, 630, 52):
        draw.line((817, y, 1200, y), fill=(31, 60, 48), width=1)

    label_font = ImageFont.load_default(size=20)
    title_font = ImageFont.load_default(size=56)
    tag_font = ImageFont.load_default(size=18)
    footer_font = ImageFont.load_default(size=20)
    draw.rounded_rectangle((72, 66, 132, 126), radius=12, fill=(213, 115, 72))
    draw.text((84, 82), 'AO', font=ImageFont.load_default(size=28), fill=(16, 30, 26))
    draw.text((158, 88), 'AL-AMEEN OLANREWAJU  /  SELECTED WORK', font=label_font, fill=(226, 178, 119))

    title_lines = _wrap_text(draw, title or 'Portfolio project', title_font, 700)
    y = 220
    for line in title_lines:
        draw.text((72, y), line, font=title_font, fill=(244, 243, 228))
        y += 72

    unique_technologies = []
    seen = set()
    for technology in technologies:
        label = _plain_text(technology).strip()
        if label and label.casefold() not in seen:
            unique_technologies.append(label)
            seen.add(label.casefold())

    tag_x = 72
    tag_y = 468
    for technology in unique_technologies[:5]:
        width = int(draw.textlength(technology, font=tag_font)) + 34
        if tag_x + width > 780:
            break
        draw.rounded_rectangle((tag_x, tag_y, tag_x + width, tag_y + 38), radius=8, outline=(94, 138, 113), width=1)
        draw.text((tag_x + 17, tag_y + 10), technology, font=tag_font, fill=(209, 223, 210))
        tag_x += width + 10

    draw.rounded_rectangle((900, 180, 1128, 408), radius=24, outline=(213, 115, 72), width=3)
    draw.line((938, 370, 1088, 220), fill=(226, 178, 119), width=4)
    draw.line((960, 385, 1100, 245), fill=(94, 138, 113), width=2)
    draw.text((72, 560), _plain_text(author), font=footer_font, fill=(181, 198, 184))
    draw.text((942, 552), 'PORTFOLIO / 01', font=label_font, fill=(226, 178, 119))

    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()