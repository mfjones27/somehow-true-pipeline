"""Original Pillow motion graphics. Diagrams are conceptual, never measured data."""

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .errors import FactoryError
from .models import Manifest

WIDTH, HEIGHT, FPS = 1080, 1920, 30
NAVY = "#091321"
SURFACE = "#102237"
GRID = "#1D3447"
MUTED = "#A8B8CA"
WHITE = "#F3F7F8"
LIME = "#D1F56A"
BELGIAN = "#FFBC76"
DUTCH_FIELD = "#253622"
BELGIAN_FIELD = "#493722"
SCHEMATIC_STYLES = frozenset(("nested-enclaves", "border-house"))


@lru_cache(maxsize=100)
def font(path: str, size: int):
    return ImageFont.truetype(path, size=size)


def fit_text(text: str, path: str, max_width: int, max_height: int,
             largest: int, smallest: int, max_lines: int):
    """Never shrink to unreadable type or cut words; reject text that cannot fit."""
    for size in range(largest, smallest - 1, -2):
        face = font(path, size)
        lines = []
        current = ""
        for word in text.split():
            if face.getlength(word) > max_width:
                break
            candidate = f"{current} {word}".strip()
            if current and face.getlength(candidate) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        else:
            lines.append(current)
            spacing = math.ceil(size * 1.22)
            ink_boxes = [face.getbbox(line, anchor="lt") for line in lines]
            ink_fits = all(
                right - left <= max_width and bottom - top <= spacing
                for left, top, right, bottom in ink_boxes
            )
            if ink_fits and len(lines) <= max_lines and len(lines) * spacing <= max_height:
                return face, lines, spacing
    raise FactoryError("Display text cannot fit safe area; shorten titles/caption segments")


def draw_lines(draw, layout, x, y, fill=WHITE):
    face, lines, spacing = layout
    for index, line in enumerate(lines):
        # Left-top anchor makes coordinates correspond to the actual ink boundary.
        draw.text((x, y + index * spacing), line, font=face, fill=fill, anchor="lt")


class FramePainter:
    def __init__(self, manifest: Manifest, settings: Settings):
        self.manifest = manifest
        self.settings = settings
        self.title_layouts = [
            fit_text(scene.text, settings.font_bold, 780, 310, 94, 64, 3)
            for scene in manifest.scenes
        ]
        self.caption_layouts = [
            fit_text(caption.text, settings.font_bold, 736, 210, 58, 44, 3)
            for caption in manifest.captions
        ]
        self.base = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
        draw = ImageDraw.Draw(self.base)
        # Low-contrast framing stays away from text and is not data.
        draw.line((100, 290, 900, 290), fill=GRID, width=2)
        draw.line((100, 1205, 900, 1205), fill=GRID, width=2)
        label = ("TECHNICAL TEST / SYNTHETIC AUDIO" if manifest.duration < 25
                 else "THINGS THAT SOUND FAKE")
        draw.text((110, 210), label, font=font(settings.font_bold, 28),
                  fill=LIME, anchor="lt")
        self.scene_bases = []
        for i, scene in enumerate(manifest.scenes):
            image = self.base.copy()
            scene_draw = ImageDraw.Draw(image)
            disclaimer = ("SCHEMATIC NOT A MAP" if scene.visual_style in SCHEMATIC_STYLES
                          else "ABSTRACT VISUAL / NOT TO SCALE")
            scene_draw.text((110, 1180), disclaimer,
                            font=font(settings.font_regular, 21), fill=MUTED, anchor="lt")
            scene_draw.text((110, 260), f"{i + 1:02d} / {len(manifest.scenes):02d}",
                            font=font(settings.font_regular, 22), fill=MUTED, anchor="lt")
            draw_lines(scene_draw, self.title_layouts[i], 110, 340)
            self.scene_bases.append(image)

    def frame(self, t: float) -> Image.Image:
        index = next((i for i, s in enumerate(self.manifest.scenes) if t < s.end),
                     len(self.manifest.scenes) - 1)
        scene = self.manifest.scenes[index]
        image = self.scene_bases[index].copy()
        draw = ImageDraw.Draw(image)
        elapsed = t - scene.start
        reveal = min(1.0, elapsed / 0.65)
        reveal = 1 - (1 - reveal) ** 3
        self.diagram(draw, scene.visual_style, elapsed, reveal)
        caption_index = next(
            (i for i, c in enumerate(self.manifest.captions) if c.start <= t < c.end), None)
        if caption_index is not None:
            draw.rounded_rectangle((100, 1250, 900, 1518), radius=22, fill=SURFACE)
            draw.rounded_rectangle((100, 1276, 106, 1492), radius=3, fill=LIME)
            layout = self.caption_layouts[caption_index]
            text_height = len(layout[1]) * layout[2]
            draw_lines(draw, layout, 128, 1250 + (268 - text_height) // 2)
        # A whole-video progress bar with explicit scene boundaries.
        draw.rounded_rectangle((100, 1538, 900, 1546), radius=4, fill=GRID)
        progress_x = 100 + 800 * min(1, (t + 1 / FPS) / self.manifest.duration)
        draw.rounded_rectangle((100, 1538, max(104, progress_x), 1546), radius=4, fill=LIME)
        for s in self.manifest.scenes[1:]:
            x = 100 + 800 * s.start / self.manifest.duration
            draw.line((x, 1536, x, 1548), fill=NAVY, width=4)
        return image

    def diagram(self, draw, style, elapsed, reveal):
        cx, cy = 500, 915
        if style == "nested-enclaves":
            self.nested_enclaves(draw, elapsed, reveal)
        elif style == "border-house":
            self.border_house(draw, reveal)
        elif style == "orbit":
            for radius in (135, 220):
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                             outline=GRID, width=3)
                angle = elapsed * (0.65 if radius == 135 else -0.38) + radius
                x, y = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
                dot = 12 * reveal
                draw.ellipse((x-dot, y-dot, x+dot, y+dot), fill=LIME)
            r = 34 * reveal
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=WHITE)
        elif style == "wave":
            draw.line((150, cy, 850, cy), fill=GRID, width=2)
            for row, color, amp in ((0, LIME, 100), (1, MUTED, 58)):
                points = [
                    (150 + x, cy + amp * reveal * math.sin(x / 70 - elapsed * 1.6 + row))
                    for x in range(0, max(6, int(700 * reveal)), 3)
                ]
                draw.line(points, fill=color, width=6 if row == 0 else 3, joint="curve")
        elif style == "network":
            points = [
                (cx + 215 * math.cos(i * math.tau / 6 - math.pi / 2),
                 cy + 215 * math.sin(i * math.tau / 6 - math.pi / 2))
                for i in range(6)
            ]
            for i, (x, y) in enumerate(points):
                draw.line((cx, cy, cx + (x-cx)*reveal, cy + (y-cy)*reveal),
                          fill=GRID, width=4)
                next_x, next_y = points[(i + 1) % 6]
                draw.line((x, y, next_x, next_y), fill=GRID, width=2)
                r = (13 + 3 * math.sin(elapsed * 2 - i)) * reveal
                draw.ellipse((x-r, y-r, x+r, y+r), fill=WHITE)
                phase = (elapsed * 0.3 + i / 6) % 1
                px, py = cx + (x-cx)*phase, cy + (y-cy)*phase
                draw.ellipse((px-5, py-5, px+5, py+5), fill=LIME)
            draw.ellipse((cx-23, cy-23, cx+23, cy+23), fill=LIME)
        else:  # pulse; visual metaphor, not a biological or measured signal
            for offset in (0, 0.33, 0.66):
                phase = (elapsed * 0.22 + offset) % 1
                radius = (45 + 180 * phase) * reveal
                color = tuple(round(a * (1-phase) + b * phase)
                              for a, b in zip((209, 245, 106), (29, 52, 71)))
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                             outline=color, width=5)
            draw.ellipse((cx-20, cy-20, cx+20, cy+20), fill=WHITE)

    def nested_enclaves(self, draw, elapsed, reveal):
        """Three deliberately rectangular nesting levels, not geographic polygons."""
        bold = font(self.settings.font_bold, 38)
        draw.rounded_rectangle((150, 700, 850, 1150), radius=24,
                               fill=DUTCH_FIELD, outline=LIME, width=4)
        draw.text((180, 730), "Dutch", font=bold, fill=LIME, anchor="lt")
        # Staged outline reveal draws attention inward without moving any boundary.
        outer_reveal = min(1, max(0, (elapsed - 0.1) / 0.5))
        inner_reveal = min(1, max(0, (elapsed - 0.3) / 0.5))
        draw.rounded_rectangle((295, 810, 805, 1110), radius=20,
                               fill=BELGIAN_FIELD, outline=BELGIAN, width=4)
        draw.text((325, 840), "Belgian", font=bold, fill=BELGIAN, anchor="lt")
        draw.line((325, 892, 325 + 435 * outer_reveal, 892), fill=BELGIAN, width=3)
        draw.rounded_rectangle((435, 935, 765, 1075), radius=16,
                               fill=DUTCH_FIELD, outline=LIME, width=4)
        draw.text((465, 965), "Dutch", font=bold, fill=LIME, anchor="lt")
        draw.line((465, 1030, 465 + 265 * inner_reveal, 1030), fill=LIME, width=3)

    def border_house(self, draw, reveal):
        """An invented house and border relationship, not a particular real building."""
        bold = font(self.settings.font_bold, 32)
        draw.rectangle((150, 750, 500, 1145), fill=DUTCH_FIELD)
        draw.rectangle((501, 750, 850, 1145), fill=BELGIAN_FIELD)
        draw.text((160, 705), "Netherlands", font=bold, fill=LIME, anchor="lt")
        draw.text((620, 705), "Belgium", font=bold, fill=BELGIAN, anchor="lt")
        # One simple pitched-roof house spans both colored fields.
        draw.polygon(((285, 900), (500, 770), (715, 900)), fill=SURFACE)
        draw.line(((285, 900), (500, 770), (715, 900)),
                  fill=WHITE, width=6, joint="curve")
        draw.rectangle((320, 900, 680, 1120), fill=SURFACE, outline=WHITE, width=5)
        for left in (365, 570):
            draw.rectangle((left, 950, left + 65, 1015), outline=WHITE, width=4)
            draw.line((left + 32, 950, left + 32, 1015), fill=WHITE, width=3)
        draw.rectangle((462, 1030, 538, 1120), outline=WHITE, width=4)
        # Reveal fixed border dashes top-to-bottom; never animate a moving border.
        endpoint = 750 + round(395 * reveal)
        for y in range(750, endpoint, 34):
            draw.line((500, y, 500, min(y + 20, endpoint)), fill=WHITE, width=7)
