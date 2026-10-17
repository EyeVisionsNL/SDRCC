#!/usr/bin/env python3
"""Small, bounded, on-demand JPEG with the approved Rensen-Driessen logo burned in.

The original image is never modified or stored. Only a URL already verified by
the vessel-photo provider can reach this renderer. Clients receive the branded
JPEG, so saving the displayed image also preserves the logo.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re

from PIL import Image, ImageChops, ImageOps

LOGO_URL = "https://quem.nl/wp-content/uploads/2021/12/RensenDriessen-Logo-1.jpg"
PHOTO_HOSTS = {"www.rensendriessen.com", "rensendriessen.com"}
MAX_PHOTO_BYTES = 7_000_000
MAX_LOGO_BYTES = 1_200_000
MAX_PIXELS = 14_000_000


def _download(url: str, cap: int, *, logo: bool = False) -> bytes:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment):
        raise ValueError("Unsupported branded-photo URL")
    if logo:
        if url != LOGO_URL:
            raise ValueError("Unexpected logo source")
    elif (parsed.hostname not in PHOTO_HOSTS or
          not re.fullmatch(r"/wp-content/uploads/[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png|webp)",
                           parsed.path, re.I) or ".." in parsed.path):
        raise ValueError("Photo URL outside the approved source")
    request = Request(url, headers={
        "Accept": "image/jpeg,image/png,image/webp",
        "User-Agent": "SDRCC-AIS-ATIS/0.67 (approved credited thumbnail)",
    })
    with urlopen(request, timeout=8.0) as response:
        destination = response.geturl()
        if destination != url:
            raise ValueError("Unexpected image redirect")
        if not str(response.headers.get("Content-Type", "")).lower().startswith("image/"):
            raise ValueError("Not an image")
        raw = response.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("Image exceeds download limit")
    return raw


def _open_limited(raw: bytes) -> Image.Image:
    with Image.open(BytesIO(raw)) as picture:
        if picture.width < 40 or picture.height < 40:
            raise ValueError("Image is too small")
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError("Image exceeds pixel limit")
        return ImageOps.exif_transpose(picture).convert("RGB")


@lru_cache(maxsize=1)
def _logo() -> Image.Image:
    original = _open_limited(_download(LOGO_URL, MAX_LOGO_BYTES, logo=True))
    # The official JPEG has a white canvas. Crop its whitespace, retaining
    # the original green mark (including the three white portholes).
    diff = ImageChops.difference(original, Image.new("RGB", original.size, "white"))
    mask = diff.convert("L").point(lambda value: 255 if value > 28 else 0)
    box = mask.getbbox()
    if box is None:
        raise ValueError("Logo appears blank")
    return original.crop(box)


@lru_cache(maxsize=24)
def render(photo_url: str) -> bytes:
    """Create a display/save-ready branded JPEG (never a bare source image)."""
    photo = _open_limited(_download(photo_url, MAX_PHOTO_BYTES))
    photo.thumbnail((960, 720), Image.Resampling.LANCZOS)
    logo = _logo().copy()

    # A modest lower-right white badge which matches Wim's approved preview.
    width, height = photo.size
    badge_w = max(38, round(width * 0.19))
    padding = max(4, round(badge_w * 0.07))
    logo.thumbnail((badge_w - 2 * padding, round(height * 0.18)), Image.Resampling.LANCZOS)
    badge_h = logo.height + padding * 2
    margin = max(5, round(width * 0.012))
    x = width - badge_w - margin
    y = height - badge_h - margin
    photo.paste("white", (x, y, x + badge_w, y + badge_h))
    photo.paste(logo, (x + (badge_w - logo.width) // 2, y + padding))

    out = BytesIO()
    photo.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()
