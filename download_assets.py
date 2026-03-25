from __future__ import annotations

import argparse
import io
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


ASSET_FILES = {
    "Tikbalang": "tikbalang.png",
    "Manananggal": "manananggal.png",
    "Kapre": "kapre.png",
    "Bakunawa": "bakunawa.png",
}

# Sources provided by you.
ASSET_SOURCES = {
    "Bakunawa": "https://www.artstation.com/artwork/xYANY1",
    "Kapre": "https://non-aliencreatures.fandom.com/wiki/Kapre",
    "Manananggal": "https://www.hiclipart.com/free-transparent-background-png-clipart-ipean",
    "Tikbalang": "https://www.artstation.com/artwork/8e9eAG",
}


@dataclass(frozen=True)
class DownloadResult:
    kind: str
    source_url: str
    saved_path: Path
    used_image_url: str
    resized_to: int


def _request_bytes(url: str, *, timeout_s: int = 30) -> bytes:
    headers = {
        # Helps bypass some basic anti-bot blocks.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def _extract_og_image(html: str) -> list[str]:
    candidates: list[str] = []
    # og:image
    for m in re.finditer(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        candidates.append(m.group(1))
    # twitter:image
    for m in re.finditer(
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        candidates.append(m.group(1))
    return candidates


def _extract_direct_image_urls(html: str) -> list[str]:
    # Best-effort: grab any jpg/png/webp links in HTML.
    # This is not perfect, but usually works for these sites.
    ext_pat = r"(?:png|jpe?g|webp)"
    pat = rf"https?://[^\s\"']+\.(?:{ext_pat})[^\s\"']*"
    return re.findall(pat, html, flags=re.IGNORECASE)


def _pick_best_image_url(candidates: Iterable[str]) -> Optional[str]:
    cand_list = [c for c in candidates if c and c.startswith(("http://", "https://"))]
    if not cand_list:
        return None

    def score(u: str) -> float:
        # Heuristics: prefer "original"/"large"/"maxres" style.
        s = 0.0
        low = u.lower()
        for token in ("original", "maxres", "max", "large", "hero", "hd"):
            if token in low:
                s += 50.0
        # Prefer longer URLs (often include more info / higher res).
        s += float(min(len(u), 300))
        return s

    return max(cand_list, key=score)


def _resize_square_rgba(img, *, max_dim: int):
    from PIL import Image  # local import to keep startup light

    if img.mode != "RGBA":
        # Convert to RGBA so we can always pad with transparency.
        img = img.convert("RGBA")

    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid image size.")

    scale = min(max_dim / float(w), max_dim / float(h), 1.0)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    if (new_w, new_h) != (w, h):
        img = img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
    x = (max_dim - new_w) // 2
    y = (max_dim - new_h) // 2
    canvas.paste(img, (x, y), img)
    return canvas


def _save_image_to_assets(
    *,
    kind: str,
    source_url: str,
    image_url: str,
    out_path: Path,
    max_dim: int,
    dry_run: bool,
) -> DownloadResult | None:
    if dry_run:
        return DownloadResult(
            kind=kind,
            source_url=source_url,
            used_image_url=image_url,
            saved_path=out_path,
            resized_to=max_dim,
        )

    from PIL import Image

    raw = _request_bytes(image_url)
    with Image.open(io.BytesIO(raw)) as im:
        im2 = _resize_square_rgba(im, max_dim=max_dim)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im2.save(out_path, format="PNG", optimize=True)

    return DownloadResult(
        kind=kind,
        source_url=source_url,
        used_image_url=image_url,
        saved_path=out_path,
        resized_to=max_dim,
    )


def download_assets(*, asset_dir: Path, max_dim: int, force: bool, dry_run: bool) -> list[DownloadResult]:
    try:
        asset_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Cannot create assets dir: {asset_dir}") from e

    results: list[DownloadResult] = []

    for kind, source_url in ASSET_SOURCES.items():
        out_filename = ASSET_FILES[kind]
        out_path = asset_dir / out_filename

        if out_path.exists() and not force:
            print(f"[skip] {kind}: {out_path.name} already exists (use --force to overwrite)")
            continue

        print(f"[fetch] {kind} from {source_url}")
        try:
            html = _request_bytes(source_url).decode("utf-8", errors="ignore")
        except urllib.error.URLError as e:
            print(f"[error] {kind}: cannot fetch source page: {e}")
            continue
        except Exception as e:
            print(f"[error] {kind}: cannot fetch source page: {e}")
            continue

        og_urls = _extract_og_image(html)
        direct_urls = _extract_direct_image_urls(html)
        best = _pick_best_image_url([*og_urls, *direct_urls])
        if not best:
            print(f"[error] {kind}: could not find image URL on page.")
            continue

        print(f"[download] {kind}: {best}")
        try:
            res = _save_image_to_assets(
                kind=kind,
                source_url=source_url,
                image_url=best,
                out_path=out_path,
                max_dim=max_dim,
                dry_run=dry_run,
            )
            if res is not None:
                results.append(res)
        except Exception as e:
            print(f"[error] {kind}: failed saving image: {e}")
            continue

    return results


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Download and resize myth obstacle sprites for the Kivy game.")
    p.add_argument("--asset-dir", default=str(Path(__file__).resolve().parent / "assets"))
    p.add_argument("--max-dim", type=int, default=256, help="Resize sprites to <= this dimension (square + padding).")
    p.add_argument("--force", action="store_true", help="Overwrite existing assets.")
    p.add_argument("--dry-run", action="store_true", help="Do not download/save, just print what would happen.")
    args = p.parse_args(argv)

    asset_dir = Path(args.asset_dir)
    results = download_assets(
        asset_dir=asset_dir,
        max_dim=int(args.max_dim),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
    )

    if args.dry_run:
        print(f"[dry-run] would process {len(results)} asset(s).")
    else:
        print(f"[done] saved {len(results)} asset(s) into {asset_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

