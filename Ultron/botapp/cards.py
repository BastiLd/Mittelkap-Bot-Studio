from __future__ import annotations

from io import BytesIO
from math import cos, sin, pi
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


def font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def fit(draw: ImageDraw.ImageDraw, value: str, size: int, width: int, bold=False):
    face = font(size, bold)
    value = " ".join(str(value).split())
    while len(value) > 1 and draw.textlength(value, font=face) > width:
        value = value[:-2] + "…"
    return value, face


def rank_card(stats: dict, name: str, color: str, avatar: bytes | None = None) -> bytes:
    # The legacy name/color parameters remain for callers, but the card is one neutral server design.
    width, height = 1200, 460
    image = Image.new("RGB", (width, height), "#090e18")
    draw = ImageDraw.Draw(image)
    mint, purple, light = "#63ead1", "#b69bff", "#e9eff8"
    for y in range(height):
        draw.line((0, y, width, y), fill=(10 + y // 110, 16 + y // 90, 26 + y // 50))
    for x in range(24, width, 24):
        for y in range(24, height, 24):
            draw.point((x, y), fill="#243044")
    draw.rounded_rectangle((16, 16, 1184, 444), radius=24, outline="#324057", width=1)
    draw.line((46, 59, 1154, 59), fill="#28364c", width=1)
    draw.line((46, 59, 242, 59), fill=mint, width=3)
    draw.text((46, 29), "AKTIVITÄT / SERVERPROFIL", font=font(16, True), fill=mint)
    draw.text((947, 29), "COMMUNITY RANK", font=font(15, True), fill="#8d9fb9")
    for offset in (0, 16, 32):
        points = [(600 + offset, 89), (720 + offset, 89), (753 + offset, 122), (843, 122)]
        draw.line(points, fill="#26344d", width=1)
        draw.ellipse((840, 119, 846, 125), fill="#6d6490")
    portrait = Image.new("RGB", (156, 156), "#24344b")
    loaded = False
    if avatar:
        try:
            with Image.open(BytesIO(avatar)) as source:
                if source.width * source.height <= 4_000_000:
                    portrait = ImageOps.fit(source.convert("RGB"), (156, 156))
                    loaded = True
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            pass
    if not loaded:
        initial = (stats["name"][:1] or "?").upper()
        pd = ImageDraw.Draw(portrait)
        face = font(58, True)
        pd.text(((156 - pd.textlength(initial, font=face)) / 2, 40), initial, font=face, fill=mint)
    mask = Image.new("L", (156, 156))
    ImageDraw.Draw(mask).ellipse((0, 0, 155, 155), fill=255)
    for radius, stroke in ((88, "#324258"), (83, mint)):
        draw.arc((136 - radius, 165 - radius, 136 + radius, 165 + radius), 20, 340, fill=stroke, width=2)
    image.paste(portrait, (58, 87), mask)
    label, face = fit(draw, stats["name"], 34, 570, True)
    draw.text((270, 93), label, font=face, fill=light)
    badge = f"PLATZ #{stats['rank']}"
    draw.rounded_rectangle((270, 145, 428, 178), radius=8, fill="#22382f", outline="#36544b")
    draw.text((284, 152), badge, font=font(16, True), fill=mint)
    role, face = fit(draw, stats.get("role", "Mitglied"), 17, 390)
    draw.text((447, 153), role, font=face, fill=purple)
    days = stats.get("membership_days")
    joined = f"Dabei seit {stats.get('joined', 'unbekannt')}" + (f" · {days} Tage" if days is not None else "")
    label, face = fit(draw, joined, 18, 570)
    draw.text((270, 198), label, font=face, fill="#a6b6cc")
    floor = 100 * stats["level"] ** 2
    ceiling = 100 * (stats["level"] + 1) ** 2
    progress = min(1, max(0, (stats["xp"] - floor) / (ceiling - floor)))
    cx, cy, radius = 1030, 158, 76
    draw.ellipse((cx - radius - 11, cy - radius - 11, cx + radius + 11, cy + radius + 11), outline="#2a364c", width=1)
    for n in range(40):
        angle = n * 2 * pi / 40
        draw.line((cx + cos(angle) * 83, cy + sin(angle) * 83, cx + cos(angle) * 87, cy + sin(angle) * 87), fill="#526078", width=1)
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), 0, 360, fill="#2d2d48", width=7)
    if progress:
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), -90, -90 + 360 * progress, fill=purple, width=7)
    draw.text((cx - 26, cy - 36), "LEVEL", font=font(16, True), fill="#9babc1")
    number = str(stats["level"])
    face = font(46, True)
    draw.text((cx - draw.textlength(number, font=face) / 2, cy - 11), number, font=face, fill=light)
    tiles = [(46, "NACHRICHTEN", f"{stats['messages']:,}".replace(",", "."), "Textaktivität", mint),
             (421, "SPRACHCHAT", f"{stats['voice_seconds'] // 60:,} Min.".replace(",", "."), "Zeit im Sprachkanal", purple),
             (796, "SPRACHNACHRICHTEN", str(stats.get("voice_messages", 0)), f"{stats.get('voice_message_seconds', 0)} Sek. Aufnahme", "#eab976")]
    for x, title, value, subtitle, accent in tiles:
        draw.rounded_rectangle((x, 268, x + 358, 358), radius=12, fill="#162030", outline="#2a374b")
        draw.line((x + 18, 285, x + 18, 337), fill=accent, width=3)
        draw.text((x + 32, 280), title, font=font(13, True), fill="#95a6be")
        text, face = fit(draw, value, 27, 230, True)
        draw.text((x + 32, 300), text, font=face, fill=light)
        draw.text((x + 32, 335), subtitle, font=font(12), fill="#8295b0")
    draw.rounded_rectangle((46, 389, 1154, 401), radius=6, fill="#29354a")
    if progress:
        draw.rounded_rectangle((46, 389, 46 + max(12, int(1108 * progress)), 401), radius=6, fill=mint)
    draw.text((46, 416), f"{stats['xp']:,} XP GESAMT".replace(",", "."), font=font(15, True), fill=light)
    next_label = f"NOCH {ceiling - stats['xp']:,} XP BIS LEVEL {stats['level'] + 1}".replace(",", ".")
    face = font(14, True)
    draw.text((1154 - draw.textlength(next_label, font=face), 416), next_label, font=face, fill="#a9b7ce")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()
