"""Deterministic PNG message cards: layout and fonts are rendered into pixels."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from string import Formatter
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONTS = {"bahnschrift": "Bahnschrift", "segoe": "Segoe UI", "consolas": "Consolas", "arial": "Arial"}
PRESETS = {
    "classic": {"label": "Classic · klare Community-Karte", "background": "#101827", "accent": "#5dd7b7", "radius": 32, "depth": 1, "font": "segoe"},
    "terminal": {"label": "Terminal · technische Konsole", "background": "#07120f", "accent": "#7ce7b3", "radius": 18, "depth": 1, "font": "consolas"},
    "editorial": {"label": "Editorial · hell und großzügig", "background": "#eae9e4", "accent": "#385dbe", "radius": 28, "depth": 1, "font": "bahnschrift"},
    "layered": {"label": "Layered · versetzte Sapphire-Flächen", "background": "#0b1020", "accent": "#829bff", "radius": 36, "depth": 3, "font": "bahnschrift"},
    "blueprint": {"label": "Bauplan · Raster und Koordinaten", "background": "#101f38", "accent": "#65b9ef", "radius": 12, "depth": 2, "font": "consolas"},
    "spotlight": {"label": "Fokus · großes Profil und Lichtbogen", "background": "#17142b", "accent": "#cc97ed", "radius": 44, "depth": 2, "font": "segoe"},
    "ticket": {"label": "Eintrittskarte · geteiltes Layout", "background": "#231b12", "accent": "#edbd78", "radius": 18, "depth": 2, "font": "bahnschrift"},
}
SHADOW_DEFAULTS = {"shadow_x": 8, "shadow_y": 8, "shadow_blur": 8, "shadow_color": "#000000", "shadow_opacity": 35}
KIND_TEXT = {
    "welcome": ("WILLKOMMEN IM UNIVERSUM", "Schön, dass du jetzt Teil unserer Community bist."),
    "farewell": ("EIN KAPITEL GEHT ZU ENDE", "Die Verbindung endet. Die Geschichten bleiben."),
    "birthday": ("HEUTE IST DEIN TAG", "Alles Gute zum Geburtstag von deiner Community."),
}


def validate_style(style):
    if not isinstance(style, dict) or set(style) - {"preset", "design_id", "background", "accent", "radius", "depth", "font", "heading", "subtitle", *SHADOW_DEFAULTS}:
        raise ValueError("Bildstil enthält unbekannte Eigenschaften.")
    if style.get("preset", "layered") not in PRESETS:
        raise ValueError("Bitte ein angebotenes Kartenlayout auswählen.")
    if "design_id" in style and (not isinstance(style["design_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", style["design_id"])):
        raise ValueError("Ungültige Design-Kennung.")
    for key in ("background", "accent", "shadow_color"):
        if key in style and (not isinstance(style[key], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", style[key])):
            raise ValueError("Bildfarben bitte als #RRGGBB angeben.")
    for key, minimum, maximum in (("radius", 0, 80), ("depth", 0, 6), ("shadow_x", -40, 40), ("shadow_y", -40, 40), ("shadow_blur", 0, 50), ("shadow_opacity", 0, 100)):
        if key in style and (type(style[key]) is not int or not minimum <= style[key] <= maximum):
            raise ValueError(f"{key}: ganze Zahl von {minimum} bis {maximum}.")
    if style.get("font", "bahnschrift") not in FONTS:
        raise ValueError("Bitte eine angebotene lokale Schrift auswählen.")
    for key, limit in (("heading", 256), ("subtitle", 500)):
        if key in style:
            if not isinstance(style[key], str) or len(style[key]) > limit:
                raise ValueError(f"{key}: Text bis {limit} Zeichen verwenden.")
            for _, field, spec, conversion in Formatter().parse(style[key]):
                if field is not None and (field not in {"name", "server"} or spec or conversion):
                    raise ValueError("Kartentexte erlauben nur {name} und {server}, ohne Formatoptionen.")


def _rgb(value):
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))


def _mix(a, b, ratio):
    return tuple(round(x * (1 - ratio) + y * ratio) for x, y in zip(a, b))


# These freely licensed fonts are part of the deployment package. Native Windows
# choices remain preferred on Windows installations; minimal Linux images need no apt fonts.
BUNDLED_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
WINDOWS_FONT_DIR = Path("C:/Windows/Fonts")
SYSTEM_FONT_DIR = Path("/usr/share/fonts/truetype")
BUNDLED_FONTS = {"bahnschrift": "Archivo.ttf", "segoe": "Roboto.ttf", "consolas": "RobotoMono.ttf", "arial": "Roboto.ttf"}


def _font_candidates(key):
    filenames = {"bahnschrift": "bahnschrift.ttf", "segoe": "segoeui.ttf", "consolas": "consola.ttf", "arial": "arial.ttf"}
    linux_names = {"bahnschrift": "dejavu/DejaVuSansCondensed.ttf", "segoe": "dejavu/DejaVuSans.ttf", "consolas": "dejavu/DejaVuSansMono.ttf", "arial": "liberation2/LiberationSans-Regular.ttf"}
    return (WINDOWS_FONT_DIR / filenames[key], BUNDLED_FONT_DIR / BUNDLED_FONTS[key],
            SYSTEM_FONT_DIR / linux_names[key], SYSTEM_FONT_DIR / "dejavu/DejaVuSans.ttf")


def _font(key, size):
    for path in _font_candidates(key):
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                # A damaged/unreadable optional system font must not hide the packaged fallback.
                continue
    return ImageFont.load_default(size=size)


def _fit(draw, text, font_key, size, width):
    while size > 20 and draw.textlength(text, font=_font(font_key, size)) > width:
        size -= 2
    font = _font(font_key, size)
    if draw.textlength(text, font=font) > width:
        while text and draw.textlength(text + "…", font=font) > width:
            text = text[:-2]
        text += "…"
    return text, font


def sample_avatar_png():
    """Local illustrated example profile. No remote images or real member identity."""
    image = Image.new("RGB", (256, 256), "#24365a")
    draw = ImageDraw.Draw(image)
    for radius in range(180, 20, -5):
        draw.ellipse((128-radius, 128-radius, 128+radius, 128+radius), fill=_mix((36,54,90), (94,157,166), (180-radius)/220))
    draw.rounded_rectangle((39, 166, 216, 277), radius=74, fill="#ecbb79")
    draw.ellipse((57, 29, 201, 181), fill="#d5e6ed")
    draw.rounded_rectangle((66, 53, 191, 158), radius=48, fill="#202d49")
    draw.rounded_rectangle((83, 72, 176, 145), radius=33, fill="#85c9c7")
    draw.arc((98, 97, 160, 130), 15, 165, fill="#24365a", width=5)
    draw.ellipse((102, 93, 110, 103), fill="#24365a")
    draw.ellipse((149, 93, 157, 103), fill="#24365a")
    draw.rounded_rectangle((48, 78, 64, 127), radius=6, fill="#edbd78")
    draw.rounded_rectangle((193, 78, 209, 127), radius=6, fill="#edbd78")
    draw.line((128, 184, 128, 254), fill="#24365a", width=5)
    draw.rounded_rectangle((154, 191, 187, 217), radius=4, fill="#24365a")
    draw.line((162, 204, 179, 204), fill="#85c9c7", width=4)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _shadows(image, box, radius, options):
    """Composite each requested shadow layer into PNG pixels, behind the card."""
    count = options["depth"]
    if not count or not options["shadow_opacity"]:
        return image
    for layer in reversed(range(1, count + 1)):
        # X/Y specify the outermost displacement; layers fill that distance evenly.
        factor = layer / count
        x = round(options["shadow_x"] * factor)
        y = round(options["shadow_y"] * factor)
        mask = Image.new("L", image.size, 0)
        shifted = (box[0]+x, box[1]+y, box[2]+x, box[3]+y)
        alpha = round(255 * options["shadow_opacity"] / 100 / (count ** .65))
        ImageDraw.Draw(mask).rounded_rectangle(shifted, radius=radius, fill=alpha)
        if options["shadow_blur"]:
            mask = mask.filter(ImageFilter.GaussianBlur(options["shadow_blur"] * factor))
        shadow = Image.new("RGB", image.size, options["shadow_color"])
        image.paste(shadow, (0, 0), mask)
    return image


def render_card(kind, *, name="Mitglied", server="MittelKings Universe", title=None, style=None, avatar_bytes=None, sample_avatar=False):
    if kind not in KIND_TEXT:
        raise ValueError("Bildkarte: willkommen/welcome, farewell oder birthday auswählen.")
    style = style or {}
    validate_style(style)
    preset = style.get("preset", "layered")
    options = {**SHADOW_DEFAULTS, **PRESETS[preset], **style}
    if not all(isinstance(value, str) and len(value) <= 250 for value in (name, server)):
        raise ValueError("Name und Server müssen kurze Texte bis 250 Zeichen sein.")
    if title is not None and (not isinstance(title, str) or len(title) > 256):
        raise ValueError("Kartentitel darf höchstens 256 Zeichen enthalten.")
    name = " ".join(name.split()) or "Mitglied"
    server = " ".join(server.split()) or "Community"
    heading, subtitle = KIND_TEXT[kind]
    context = {"name": name, "server": server}
    heading = " ".join(style.get("heading", heading).format_map(context).split())
    subtitle = " ".join(style.get("subtitle", subtitle).format_map(context).split())
    background, accent = _rgb(options["background"]), _rgb(options["accent"])
    light = sum(background) > 500
    ink, muted = ((24, 32, 48), (76, 88, 108)) if light else ((244, 247, 255), (159, 177, 201))
    width, height = 1200, 420
    image = Image.new("RGB", (width, height), background)
    radius, depth, font_key = options["radius"], options["depth"], options["font"]
    box = (40, 28, 1138, 352) if preset == "layered" else (38, 28, 1154, 382)
    _shadows(image, box, radius, options)
    draw = ImageDraw.Draw(image)
    if preset == "layered":
        for layer in reversed(range(1, depth + 1)):
            offset = layer * 9
            draw.rounded_rectangle((40 + offset, 28 + offset, 1138 + offset, 352 + offset), radius=radius,
                                   fill=_mix(background, accent, .10 + .045 * (depth - layer)))
        draw.rounded_rectangle((40, 28, 1138, 352), radius=radius, fill=_mix(background, accent, .12), outline=_mix(background, accent, .45), width=2)
        draw.rounded_rectangle((49, 37, 1129, 343), radius=max(0, radius - 6), outline=_mix(background, accent, .10), width=2)
        draw.rounded_rectangle((68, 63, 75, 306), radius=3, fill=accent)
    elif preset == "terminal":
        draw.rounded_rectangle((30, 25, 1170, 395), radius=radius, fill=_mix(background, accent, .025), outline=_mix(background, accent, .35), width=2)
        for y in range(70, 385, 8):
            draw.line((42, y, 1158, y), fill=_mix(background, accent, .035))
        for x, color in ((55, (228, 111, 117)), (80, (232, 187, 98)), (105, accent)):
            draw.ellipse((x, 43, x+11, 54), fill=color)
        draw.text((142, 39), "community.console / " + kind, font=_font(font_key, 18), fill=muted)
    elif preset == "editorial":
        draw.rounded_rectangle((28, 24, 1172, 394), radius=radius, fill=_mix(background, (255, 255, 255), .45))
        draw.rounded_rectangle((850, 45, 1150, 372), radius=radius, fill=accent)
        for offset in range(depth):
            draw.arc((840-offset*12, 60-offset*12, 1210+offset*12, 430+offset*12), 110, 285, fill=_mix(accent, (255,255,255), .32), width=3)
    elif preset == "blueprint":
        draw.rounded_rectangle(box, radius=radius, fill=_mix(background, accent, .035), outline=_mix(background, accent, .55), width=2)
        for gx in range(62, 1140, 32):
            draw.line((gx, 43, gx, 366), fill=_mix(background, accent, .09))
        for gy in range(47, 372, 32):
            draw.line((53, gy, 1138, gy), fill=_mix(background, accent, .09))
        draw.line((280, 73, 280, 330), fill=_mix(background, accent, .45), width=2)
        for x,y in ((68,58),(1116,58),(68,350),(1116,350)):
            draw.line((x-9,y,x+9,y), fill=accent, width=2)
            draw.line((x,y-9,x,y+9), fill=accent, width=2)
        draw.text((301, 340), "01 / COMMUNITY-SYSTEM", font=_font("consolas", 16), fill=muted)
    elif preset == "spotlight":
        draw.rounded_rectangle(box, radius=radius, fill=_mix(background, accent, .07), outline=_mix(background, accent, .23), width=2)
        for ring in range(5):
            r = 101 + ring * 15
            draw.arc((223-r, 201-r, 223+r, 201+r), -65, 235, fill=_mix(background, accent, .18 + ring * .035), width=4)
        draw.rounded_rectangle((408, 74, 469, 80), radius=3, fill=accent)
        draw.line((408, 329, 1089, 329), fill=_mix(background, accent, .3), width=1)
    elif preset == "ticket":
        draw.rounded_rectangle(box, radius=radius, fill=_mix(background, accent, .07), outline=_mix(background, accent, .38), width=2)
        draw.rounded_rectangle((54, 44, 330, 366), radius=max(0,radius-8), fill=_mix(background, accent, .16))
        for y in range(49, 369, 16):
            draw.line((354,y,354,y+7), fill=_mix(background, accent, .5), width=2)
        for cy in (29,381):
            draw.ellipse((338,cy-15,370,cy+15), fill=background)
        draw.text((96, 314), "COMMUNITY PASS", font=_font("consolas", 18), fill=accent)
        for x in range(992, 1108, 7):
            draw.line((x, 292, x, 337 - x%3*6), fill=_mix(background, accent, .5), width=2+x%3)
    else:
        draw.rounded_rectangle((28, 24, 1172, 394), radius=radius, fill=_mix(background, accent, .06), outline=_mix(background, accent, .25), width=2)
        for layer in range(depth + 1):
            r = 85 + layer * 32
            draw.arc((1075-r, 205-r, 1075+r, 205+r), 100, 280, fill=_mix(background, accent, .25), width=3)
        draw.rounded_rectangle((60, 350, 1138, 355), radius=2, fill=_mix(background, accent, .2))
    avatar_x, avatar_y, avatar_size = {"editorial": (907,95,184), "spotlight": (129,107,188), "ticket": (110,106,160)}.get(preset, (100,105,160))
    if sample_avatar and not avatar_bytes:
        avatar_bytes = sample_avatar_png()
    if avatar_bytes and len(avatar_bytes) <= 4 * 1024 * 1024:
        try:
            avatar = Image.open(BytesIO(avatar_bytes))
            if avatar.width * avatar.height > 16_000_000:
                raise ValueError("Avatar zu groß")
            avatar = ImageOps.fit(avatar.convert("RGB"), (avatar_size, avatar_size))
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, avatar_size - 1, avatar_size - 1), radius=min(radius + 10, avatar_size // 2), fill=255)
            image.paste(avatar, (avatar_x, avatar_y), mask)
        except (ValueError, OSError):
            avatar_bytes = None
    else:
        avatar_bytes = None
    if not avatar_bytes:
        fill = _mix(accent, background, .45)
        draw.rounded_rectangle((avatar_x, avatar_y, avatar_x+avatar_size, avatar_y+avatar_size), radius=min(radius+10, avatar_size//2), fill=fill)
        initials = "".join(part[0] for part in name.split()[:2]).upper()
        font = _font(font_key, 66)
        draw.text((avatar_x+avatar_size/2, avatar_y+avatar_size/2-4), initials, font=font, fill=ink if preset != "editorial" else (255,255,255), anchor="mm")
    x, max_width = {"editorial": (67,730), "spotlight": (408,680), "ticket": (390,707)}.get(preset, (295,780))
    y = 89 if preset != "terminal" else 97
    heading_text, heading_font = _fit(draw, heading, font_key, 20, max_width)
    draw.text((x, y), heading_text, font=heading_font, fill=accent)
    main = title or name
    main_text, main_font = _fit(draw, main, font_key, 59, max_width)
    draw.text((x, y+39), main_text, font=main_font, fill=ink)
    subtext, subfont = _fit(draw, subtitle, font_key, 23, max_width)
    draw.text((x, y+127), subtext, font=subfont, fill=muted)
    server_text, server_font = _fit(draw, server, font_key, 20, max_width - 30)
    if preset == "terminal":
        server_text = "> " + server_text
    draw.text((x, y+179), server_text, font=server_font, fill=accent)
    if preset == "editorial":
        draw.text((942, 309), "COMMUNITY", font=_font(font_key, 17), fill=(255,255,255))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
