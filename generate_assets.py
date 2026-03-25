from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple


ASSET_FILES: Dict[str, str] = {
    "Tikbalang": "tikbalang.png",
    "Manananggal": "manananggal.png",
    "Kapre": "kapre.png",
    "Bakunawa": "bakunawa.png",
    "Runner": "runner.png",
}


def ensure_assets(asset_dir: str | Path | None = None) -> bool:
    """
    Create simple placeholder sprites (PNG) using Pillow.

    We can't commit binary assets in this environment, so we generate them
    on the first run for the defense prototype.
    """

    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False

    base = Path(__file__).resolve().parent
    asset_dir = Path(asset_dir) if asset_dir is not None else (base / "assets")
    asset_dir.mkdir(parents=True, exist_ok=True)

    size = 128
    padding = 8

    def _blank_rgba() -> Tuple["Image.Image", "ImageDraw.ImageDraw"]:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        return img, draw

    def _save(filename: str, render_fn, *, force: bool = False) -> None:
        """
        Save a placeholder sprite only if missing (unless force=True).
        """
        path = asset_dir / filename
        if path.exists() and not force:
            return
        img, draw = _blank_rgba()
        render_fn(draw)
        img.save(path)

    # Runner (simple warrior silhouette)
    def render_runner(draw: "ImageDraw.ImageDraw") -> None:
        # Body
        draw.rounded_rectangle(
            [size * 0.28, size * 0.28, size * 0.72, size * 0.90],
            radius=12,
            fill=(40, 200, 255, 255),
        )
        # Head
        draw.ellipse([size * 0.42, size * 0.10, size * 0.58, size * 0.30], fill=(40, 200, 255, 255))
        # Eyes (tiny)
        draw.ellipse([size * 0.47, size * 0.18, size * 0.49, size * 0.21], fill=(0, 0, 0, 220))
        draw.ellipse([size * 0.51, size * 0.18, size * 0.53, size * 0.21], fill=(0, 0, 0, 220))

    _save(ASSET_FILES["Runner"], render_runner)

    # Myth obstacle placeholders (simple stylized icons)
    def render_tikbalang(draw: "ImageDraw.ImageDraw") -> None:
        # Stylized Tikbalang: horned horse head + mane.
        # Mane
        draw.polygon(
            [(size * 0.18, size * 0.40), (size * 0.35, size * 0.18), (size * 0.50, size * 0.32), (size * 0.55, size * 0.18), (size * 0.82, size * 0.42), (size * 0.75, size * 0.72), (size * 0.28, size * 0.72)],
            fill=(40, 175, 230, 255),
        )
        # Horns
        draw.polygon([(size * 0.33, size * 0.22), (size * 0.26, size * 0.08), (size * 0.46, size * 0.12)], fill=(100, 240, 255, 255))
        draw.polygon([(size * 0.58, size * 0.20), (size * 0.66, size * 0.06), (size * 0.47, size * 0.12)], fill=(100, 240, 255, 255))
        # Face
        draw.rounded_rectangle([size * 0.30, size * 0.28, size * 0.74, size * 0.90], radius=20, fill=(55, 215, 245, 255))
        # Eyes
        draw.ellipse([size * 0.40, size * 0.52, size * 0.45, size * 0.57], fill=(10, 10, 10, 240))
        draw.ellipse([size * 0.56, size * 0.52, size * 0.61, size * 0.57], fill=(10, 10, 10, 240))
        # Mouth stripe
        draw.rectangle([size * 0.46, size * 0.64, size * 0.54, size * 0.66], fill=(255, 255, 255, 200))

    _save(ASSET_FILES["Tikbalang"], render_tikbalang)

    def render_manananggal(draw: "ImageDraw.ImageDraw") -> None:
        # Stylized Manananggal: upper torso + bat-like wings.
        wing_fill = (235, 140, 60, 170)
        body_fill = (240, 155, 75, 255)
        # Wings (left)
        draw.polygon(
            [(size * 0.48, size * 0.46), (size * 0.24, size * 0.30), (size * 0.08, size * 0.45), (size * 0.22, size * 0.62), (size * 0.44, size * 0.58)],
            fill=wing_fill,
        )
        # Wings (right)
        draw.polygon(
            [(size * 0.52, size * 0.46), (size * 0.76, size * 0.30), (size * 0.92, size * 0.45), (size * 0.78, size * 0.62), (size * 0.56, size * 0.58)],
            fill=wing_fill,
        )
        # Torso
        draw.rounded_rectangle([size * 0.33, size * 0.40, size * 0.67, size * 0.90], radius=18, fill=body_fill)
        # Head
        draw.ellipse([size * 0.43, size * 0.22, size * 0.57, size * 0.36], fill=(235, 145, 70, 255))
        # Hair/neck shadow
        draw.pieslice([size * 0.36, size * 0.18, size * 0.64, size * 0.46], start=180, end=360, fill=(200, 95, 35, 120))
        # Eyes
        draw.ellipse([size * 0.45, size * 0.28, size * 0.49, size * 0.32], fill=(20, 20, 20, 240))
        draw.ellipse([size * 0.51, size * 0.28, size * 0.55, size * 0.32], fill=(20, 20, 20, 240))

    _save(ASSET_FILES["Manananggal"], render_manananggal)

    def render_kapre(draw: "ImageDraw.ImageDraw") -> None:
        # Stylized Kapre: big tree with face.
        canopy = (45, 195, 85, 255)
        trunk = (30, 135, 55, 255)
        # Canopy
        draw.ellipse([size * 0.12, size * 0.12, size * 0.88, size * 0.72], fill=canopy)
        # Trunk
        draw.rounded_rectangle([size * 0.44, size * 0.34, size * 0.56, size * 0.92], radius=14, fill=trunk)
        # Face area
        draw.ellipse([size * 0.38, size * 0.44, size * 0.62, size * 0.62], fill=(20, 80, 35, 200))
        # Eyes
        draw.ellipse([size * 0.42, size * 0.49, size * 0.47, size * 0.55], fill=(0, 0, 0, 240))
        draw.ellipse([size * 0.53, size * 0.49, size * 0.58, size * 0.55], fill=(0, 0, 0, 240))
        # Smile/mouth
        draw.arc([size * 0.45, size * 0.56, size * 0.55, size * 0.68], start=0, end=180, fill=(0, 0, 0, 200), width=3)

    _save(ASSET_FILES["Kapre"], render_kapre)

    def render_bakunawa(draw: "ImageDraw.ImageDraw") -> None:
        # Stylized Bakunawa: coiled serpent with a mouth.
        body = (175, 70, 255, 255)
        highlight = (120, 30, 205, 200)
        # Body coil (rounded shape)
        draw.rounded_rectangle([size * 0.22, size * 0.28, size * 0.80, size * 0.90], radius=34, fill=body)
        # Tail highlight
        draw.polygon(
            [(size * 0.22, size * 0.55), (size * 0.36, size * 0.40), (size * 0.40, size * 0.70)],
            fill=highlight,
        )
        # Mouth area
        draw.ellipse([size * 0.46, size * 0.46, size * 0.58, size * 0.62], fill=(60, 0, 110, 190))
        # Fangs
        draw.polygon(
            [(size * 0.49, size * 0.54), (size * 0.52, size * 0.46), (size * 0.55, size * 0.54)],
            fill=(255, 255, 255, 200),
        )
        # Eyes
        draw.ellipse([size * 0.44, size * 0.45, size * 0.48, size * 0.49], fill=(0, 0, 0, 240))
        draw.ellipse([size * 0.55, size * 0.45, size * 0.59, size * 0.49], fill=(0, 0, 0, 240))

    _save(ASSET_FILES["Bakunawa"], render_bakunawa)

    return True

