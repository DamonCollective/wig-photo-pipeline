#!/usr/bin/env python3
"""
wig-photo-pipeline — process_wigs.py

Flow:
  1. Read new images from SOURCE (iphone_photos on damoncollective Drive)
  2. Remove background with rembg
  3. Pad to 2000×2000 transparent PNG (Etsy-ready)
  4. Save to DEST/YYYY-MM-DD/ (My Products on costaspapapa Drive)
  5. Log processed filenames so reruns skip already-done files

Config: copy config.example.json → config.json and set paths for this machine.

Install deps:
  pip install rembg pillow pillow-heif
"""

import json
import os
import sys
import io
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", Path(__file__).parent / "config.json"))
LOG_FILE    = Path(__file__).parent / "processed.json"

SUPPORTED = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def load_config():
    if not CONFIG_FILE.exists():
        print("config.json not found. Copy config.example.json → config.json and fill in your paths.")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_log() -> dict:
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}


def save_log(log: dict):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def open_image(path: Path):
    """Open image with HEIC support and EXIF auto-rotation."""
    from PIL import Image, ImageOps
    suffix = path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            print(f"  SKIP {path.name}: HEIC support requires pillow-heif (pip install pillow-heif)")
            return None
    img = Image.open(path)
    return ImageOps.exif_transpose(img)  # corrects rotation from EXIF orientation tag


def remove_bg_square(input_path: Path):
    """Remove background and return a 2000×2000 transparent PNG (PIL Image)."""
    from rembg import remove
    from PIL import Image

    img = open_image(input_path)
    if img is None:
        return None

    # rembg works on bytes
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    result_bytes = remove(buf.getvalue())

    result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    # Pad to square, center the subject
    size = max(result.size)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(result, ((size - result.width) // 2, (size - result.height) // 2))
    return square.resize((2000, 2000), Image.LANCZOS)


def main():
    try:
        from rembg import remove  # noqa — just verify installed
        from PIL import Image     # noqa
    except ImportError:
        print("Missing dependencies. Run:\n  pip install rembg pillow pillow-heif")
        sys.exit(1)

    cfg    = load_config()
    source = Path(cfg["source"])
    dest   = Path(cfg["dest"])

    if not source.exists():
        print(f"Source folder not found: {source}")
        sys.exit(1)
    if not dest.exists():
        print(f"Destination folder not found: {dest}")
        sys.exit(1)

    today   = date.today().isoformat()   # e.g. 2026-04-04
    out_dir = dest / today
    out_dir.mkdir(parents=True, exist_ok=True)

    log = load_log()
    already_done = set(log.get(today, []))

    images = sorted(
        p for p in source.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED
    )

    new_images = [p for p in images if p.name not in already_done]

    if not new_images:
        print("No new images to process.")
        return

    # Starting index: count existing PNGs in output folder
    existing_count = len(list(out_dir.glob("*.png")))
    start_idx = existing_count + 1

    print(f"Processing {len(new_images)} image(s) -> {out_dir}\n")

    processed_this_run = []

    for i, img_path in enumerate(new_images, start=start_idx):
        out_name = f"{today}-{i:02d}.png"
        out_path = out_dir / out_name
        print(f"  [{i:02d}] {img_path.name} → {out_name} ... ", end="", flush=True)
        try:
            result = remove_bg_square(img_path)
            if result is None:
                continue
            result.save(out_path, "PNG")
            processed_this_run.append(img_path.name)
            print("done")
        except Exception as e:
            print(f"FAILED — {e}")

    # Update log
    log.setdefault(today, [])
    log[today].extend(processed_this_run)
    save_log(log)

    print(f"\n{len(processed_this_run)} image(s) saved to {out_dir}")


if __name__ == "__main__":
    main()
