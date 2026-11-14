#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render transparent caption overlay clips from Resolve subtitle timing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from bidi.algorithm import get_display


DEFAULT_FFMPEG = [
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]


COLOR_FALLBACKS = {
    "gold": (255, 204, 82),
    "rich gold": (255, 190, 36),
    "rose gold": (255, 176, 145),
    "amber": (255, 183, 65),
    "yellow": (255, 235, 80),
    "orange": (255, 115, 43),
    "red": (255, 65, 70),
    "ruby": (235, 36, 84),
    "pink": (255, 94, 176),
    "hot pink": (255, 56, 159),
    "magenta": (255, 55, 235),
    "purple": (160, 86, 255),
    "violet": (132, 92, 255),
    "indigo": (88, 103, 255),
    "blue": (70, 135, 255),
    "royal blue": (52, 91, 255),
    "sky blue": (88, 210, 255),
    "cyan": (70, 235, 255),
    "teal": (59, 217, 205),
    "green": (78, 225, 98),
    "emerald": (58, 212, 124),
    "lime": (188, 255, 75),
    "copper": (230, 126, 70),
    "bronze": (210, 150, 82),
    "silver chrome": (210, 220, 232),
}


def find_ffmpeg() -> str:
    env = os.environ.get("FFMPEG_PATH")
    candidates = [env] if env else []
    candidates.extend(DEFAULT_FFMPEG)
    candidates.append(shutil.which("ffmpeg"))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def first_float(pattern: str, text: str):
    match = re.search(pattern, text, re.S)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def parse_style(template_path: Path) -> dict:
    text = read_text(template_path) if template_path.exists() else ""
    name = template_path.stem.lower()

    # PixMind Glow templates tint a desaturated text pass through ColorGain.
    tint_block = re.search(r"Tint\s*=\s*ColorGain\s*{(?P<body>.*?)\n\s*},", text, re.S)
    block = tint_block.group("body") if tint_block else text
    r = first_float(r"GainRed\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", block)
    g = first_float(r"GainGreen\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", block)
    b = first_float(r"GainBlue\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", block)

    if r is None or g is None or b is None:
        r = first_float(r"Red1\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text)
        g = first_float(r"Green1\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text)
        b = first_float(r"Blue1\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text)

    if r is None or g is None or b is None:
        color = COLOR_FALLBACKS.get(name, (255, 204, 82))
    else:
        color = (
            int(max(0, min(1, r)) * 255),
            int(max(0, min(1, g)) * 255),
            int(max(0, min(1, b)) * 255),
        )

    font_name_match = re.search(r"Font\s*=\s*Input\s*{\s*Value\s*=\s*\"([^\"]+)\"", text)
    font_name = font_name_match.group(1) if font_name_match else ""
    style_match = re.search(r"Style\s*=\s*Input\s*{\s*Value\s*=\s*\"([^\"]+)\"", text)
    font_style = style_match.group(1) if style_match else ""
    size = first_float(r"Size\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text) or 0.185
    glow = first_float(r"Gain\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text) or 2.4
    glow_size = first_float(r"YGlowSize\s*=\s*Input\s*{\s*Value\s*=\s*([0-9.]+)", text) or 10
    return {
        "name": template_path.stem,
        "color": color,
        "font_name": font_name,
        "font_style": font_style,
        "size": size,
        "glow": glow,
        "glow_size": glow_size,
    }


def font_file_candidates(requested: str, style_name: str) -> list[Path]:
    home = Path.home()
    normalized = (requested + " " + style_name).lower().replace(" ", "")
    candidates = []
    if "opensanssemicondensed" in normalized:
        candidates.extend(
            [
                home / "Library/Fonts/OpenSans_SemiCondensed-ExtraBold.ttf",
                home / "Library/Fonts/OpenSans_SemiCondensed-Bold.ttf",
                home / "Library/Fonts/OpenSans_SemiCondensed-SemiBold.ttf",
                home / "Library/Fonts/OpenSans_SemiCondensed-Regular.ttf",
            ]
        )
    if "opensanscondensed" in normalized:
        candidates.extend(
            [
                home / "Library/Fonts/OpenSans_Condensed-ExtraBold.ttf",
                home / "Library/Fonts/OpenSans_Condensed-Bold.ttf",
                home / "Library/Fonts/OpenSans_Condensed-Regular.ttf",
            ]
        )
    if "opensans" in normalized:
        candidates.extend(
            [
                home / "Library/Fonts/OpenSans-ExtraBold.ttf",
                home / "Library/Fonts/OpenSans-Bold.ttf",
                home / "Library/Fonts/OpenSans-Regular.ttf",
            ]
        )
    return candidates


def candidate_fonts(style: dict) -> list[Path]:
    home = Path.home()
    requested = style.get("font_name") or ""
    font_style = style.get("font_style") or ""
    candidates = []
    candidates.extend(font_file_candidates(requested, font_style))
    if requested == "PixMind Glow Hebrew":
        candidates.append(home / "Library/Fonts/PixMindGlowHebrew-Regular.ttf")
    candidates.extend(
        [
            home / "Library/Fonts/Heebo-Black.ttf",
            home / "Library/Fonts/Heebo-ExtraBold.ttf",
            home / "Library/Fonts/Heebo-Bold.ttf",
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ]
    )
    return [p for p in candidates if p.exists()]


def load_font(style: dict, size: int) -> ImageFont.FreeTypeFont:
    for font_path in candidate_fonts(style):
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


def display_text(text: str) -> str:
    text = " ".join(str(text or "").split())
    try:
        return get_display(text)
    except Exception:
        return text


def fit_font(text: str, style: dict, width: int, height: int):
    max_width = int(width * 0.88)
    template_size = float(style.get("size") or 0.185)
    size = int(height * template_size)
    size = max(42, min(size, int(height * 0.20)))
    while size >= 34:
        font = load_font(style, size)
        bbox = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), text, font=font, stroke_width=max(2, size // 18))
        if (bbox[2] - bbox[0]) <= max_width:
            return font, size, bbox
        size -= 4
    font = load_font(style, 34)
    bbox = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), text, font=font, stroke_width=2)
    return font, 34, bbox


def diagonal_mask(width: int, height: int, text_mask: Image.Image) -> Image.Image:
    stripes = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(stripes)
    stripe_w = int(width * 0.065)
    stripe_len = int(max(width, height) * 1.6)
    angle = -33.1125833187743
    centers = [(0.268987341772152, 0.5), (0.5, 0.5), (0.791139240506329, 0.5)]

    # Draw each Fusion-style vertical rectangle into a small image, rotate it,
    # then composite it at the normalized RectangleMask center.
    for cx, cy in centers:
        strip = Image.new("L", (stripe_w * 4, stripe_len), 0)
        sd = ImageDraw.Draw(strip)
        left = (strip.width - stripe_w) // 2
        sd.rectangle((left, 0, left + stripe_w, stripe_len), fill=255)
        strip = strip.filter(ImageFilter.GaussianBlur(max(1, int(width * 0.0025))))
        rotated = strip.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        px = int(cx * width - rotated.width / 2)
        py = int(cy * height - rotated.height / 2)
        layer = Image.new("L", (width, height), 0)
        layer.paste(rotated, (px, py), rotated)
        stripes = ImageChops.lighter(stripes, layer)

    return ImageChops.multiply(stripes, text_mask)


def metallic_text_layer(mask: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    width, height = mask.size
    vertical = Image.new("L", (1, height), 0)
    vd = ImageDraw.Draw(vertical)
    for y in range(height):
        t = y / max(1, height - 1)
        # Similar role to the Fusion desat/bump/tint chain: strong top edge,
        # darker middle, bright lower bevel.
        value = int(112 + 92 * abs(2 * t - 1) + 28 * max(0, 0.55 - t))
        vd.point((0, y), fill=max(55, min(255, value)))
    vertical = vertical.resize((width, height))

    blur = mask.filter(ImageFilter.GaussianBlur(1.2))
    high = ImageChops.subtract(ImageChops.offset(blur, -3, -3), ImageChops.offset(blur, 3, 3), scale=1.0, offset=128)
    low = ImageChops.subtract(ImageChops.offset(blur, 3, 3), ImageChops.offset(blur, -3, -3), scale=1.0, offset=128)
    luma = ImageChops.multiply(vertical, mask)
    luma = ImageChops.add(luma, high.point(lambda v: max(0, v - 128) * 2), scale=1.0, offset=0)
    luma = ImageChops.subtract(luma, low.point(lambda v: max(0, v - 128)), scale=1.0, offset=0)
    luma = luma.point(lambda v: max(0, min(255, int(v))))

    r, g, b = color
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    color_img = Image.merge(
        "RGBA",
        (
            luma.point(lambda v: int(r * v / 255)),
            luma.point(lambda v: int(g * v / 255)),
            luma.point(lambda v: int(b * v / 255)),
            mask,
        ),
    )
    return Image.alpha_composite(layer, color_img)


def render_png(text: str, style: dict, width: int, height: int, out_path: Path):
    shown = display_text(text)
    font, size, bbox = fit_font(shown, style, width, height)
    stroke = max(1, size // 80)
    center_y = 0.50
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2 - bbox[0]
    y = int(height * center_y - text_h / 2 - bbox[1])

    mask = Image.new("L", (width, height), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.text((x, y), shown, font=font, fill=255, stroke_width=stroke, stroke_fill=255)

    color = tuple(style["color"])
    base = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    text_layer = metallic_text_layer(mask, color)
    base = Image.alpha_composite(base, text_layer)

    glow_strength = float(style.get("glow") or 2.559)
    glow_size = float(style.get("glow_size") or 10)
    effect_mask = diagonal_mask(width, height, mask)
    glow_source = effect_mask
    for radius, alpha in [
        (max(2, int(glow_size * 2.0)), 80),
        (max(2, int(glow_size * 1.0)), 125),
        (max(1, int(glow_size * 0.45)), 170),
    ]:
        blurred = glow_source.filter(ImageFilter.GaussianBlur(radius))
        scaled = blurred.point(
            lambda v, a=alpha, gs=glow_strength: min(255, int(v * (a / 255.0) * min(2.4, gs / 1.7)))
        )
        layer = Image.new("RGBA", (width, height), color + (0,))
        layer.putalpha(scaled)
        base = Image.alpha_composite(base, layer)

    out = Image.alpha_composite(base, text_layer)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)


def render_mov(ffmpeg: str, png_path: Path, frames: int, fps: float, out_path: Path):
    duration = max(frames / fps, 0.05)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(png_path),
        "-t",
        f"{duration:.6f}",
        "-an",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "-vendor",
        "apl0",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON file with width, height, fps, and captions")
    parser.add_argument("--template", required=True, help="Resolve .setting template path")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    width = int(data.get("width") or 1080)
    height = int(data.get("height") or 1920)
    fps = float(data.get("fps") or 29.97)
    captions = data.get("captions") or []
    style = parse_style(Path(args.template))
    ffmpeg = find_ffmpeg()

    out_dir = Path(args.out_dir)
    media_dir = out_dir / "media"
    png_dir = out_dir / "png"
    media_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    rendered = []
    for idx, cue in enumerate(captions, start=1):
        text = cue.get("text") or cue.get("name") or ""
        start = int(round(cue["start"]))
        end = int(round(cue["end"]))
        frames = max(1, end - start)
        png = png_dir / f"caption-{idx:04d}.png"
        mov = media_dir / f"caption-{idx:04d}.mov"
        render_png(text, style, width, height, png)
        render_mov(ffmpeg, png, frames, fps, mov)
        rendered.append(
            {
                "text": text,
                "start": start,
                "end": end,
                "frames": frames,
                "media": str(mov),
            }
        )

    manifest = {
        "template": str(Path(args.template)),
        "style": style,
        "width": width,
        "height": height,
        "fps": fps,
        "items": rendered,
    }
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(rendered), "manifest": str(args.manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise
