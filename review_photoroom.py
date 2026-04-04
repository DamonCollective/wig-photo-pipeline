#!/usr/bin/env python3
"""
review_photoroom.py — Interactive review, naming, and organizing of PHOTOROOM images.

For each group of images (grouped by 1-minute timestamp gap):
  1. Downloads the first image from Drive
  2. Opens it in your image viewer
  3. Calls Claude API → suggests folder name + SEO filename slug
  4. You confirm or edit both
  5. Downloads all images in the group
  6. Renames: seo-name-01.png, 02.png ...
  7. Uploads to My Products/[FOLDER NAME]/ on Drive
  8. Saves progress — safe to interrupt and resume

Usage:
  python3 review_photoroom.py

Config (config.json):
  anthropic_api_key  — your Anthropic API key
  photoroom_remote   — rclone remote:path for PHOTOROOM folder (default: Gdrive_M:PHOTOROOM)
  myproducts_folder_id — Drive folder ID for My Products
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import base64
import io
from datetime import datetime
from pathlib import Path

CONFIG_FILE   = Path(__file__).parent / "config.json"
PROGRESS_FILE = Path(__file__).parent / "photoroom_progress.json"

PHOTOROOM_REMOTE    = "Gdrive_M:PHOTOROOM"
MYPRODUCTS_FOLDER_ID = "13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"
GAP_SECONDS         = 60   # images more than 60s apart = different wig

# ── config ─────────────────────────────────────────────────────────────────────

def load_config():
    if not CONFIG_FILE.exists():
        print("config.json not found. Copy config.example.json → config.json.")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)

# ── progress tracking ──────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"done_groups": []}   # list of first-filename of each completed group

def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

# ── timestamp parsing ──────────────────────────────────────────────────────────

def parse_timestamp(filename: str) -> datetime | None:
    """Extract datetime from IMG_YYYYMMDD_HHmmss-Photoroom*.png"""
    m = re.search(r"IMG_(\d{8})_(\d{6})", filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None

# ── grouping ───────────────────────────────────────────────────────────────────

def group_by_gap(files: list[str], gap_seconds: int) -> list[list[str]]:
    """Group filenames by timestamp proximity."""
    timestamped = []
    for f in files:
        ts = parse_timestamp(f)
        if ts:
            timestamped.append((ts, f))

    timestamped.sort(key=lambda x: x[0])

    groups = []
    current = []
    last_ts = None

    for ts, f in timestamped:
        if last_ts is None or (ts - last_ts).total_seconds() > gap_seconds:
            if current:
                groups.append(current)
            current = [f]
        else:
            current.append(f)
        last_ts = ts

    if current:
        groups.append(current)

    return groups

# ── image viewer ───────────────────────────────────────────────────────────────

def open_image_viewer(path: Path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

# ── Claude vision ──────────────────────────────────────────────────────────────

def ai_suggest(image_path: Path, api_key: str) -> tuple[str, str]:
    """
    Ask Claude to look at the wig image and suggest:
      - folder_name: short, uppercase (e.g. "GRAY COUNT 1800")
      - seo_slug: lowercase hyphenated (e.g. "gray-georgian-court-wig-1800")
    Returns (folder_name, seo_slug).
    """
    import anthropic

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a product photo of a theatrical or costume wig sold by a Greek company. "
                            "Look at the wig and give me two things:\n"
                            "1. FOLDER: A short uppercase folder name (2-5 words, e.g. 'GRAY COUNT 1800', 'AFRO PINK WIG', 'ANCIENT GREEK BLONDE')\n"
                            "2. SEO: A lowercase hyphenated SEO filename slug (e.g. 'gray-georgian-court-wig-1800', 'afro-pink-costume-wig')\n\n"
                            "Reply in exactly this format (nothing else):\n"
                            "FOLDER: ...\n"
                            "SEO: ..."
                        ),
                    },
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    folder_name = ""
    seo_slug = ""
    for line in text.splitlines():
        if line.startswith("FOLDER:"):
            folder_name = line.replace("FOLDER:", "").strip()
        elif line.startswith("SEO:"):
            seo_slug = line.replace("SEO:", "").strip().lower().replace(" ", "-")

    return folder_name, seo_slug

# ── rclone helpers ─────────────────────────────────────────────────────────────

def rclone_download_file(remote_path: str, local_path: Path):
    subprocess.run(
        ["rclone", "copyto", remote_path, str(local_path)],
        check=True, capture_output=True
    )

def rclone_upload_dir(local_dir: Path, folder_name: str, folder_id: str):
    subprocess.run(
        [
            "rclone", "copy", str(local_dir),
            f"Gdrive_M:{folder_name}",
            "--drive-root-folder-id", folder_id,
            "-P",
        ],
        check=True,
    )

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()
    api_key = cfg.get("anthropic_api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
    if not api_key:
        print("ERROR: Set 'anthropic_api_key' in config.json.")
        sys.exit(1)

    progress = load_progress()
    done = set(progress["done_groups"])

    # 1. List all files in PHOTOROOM
    print("Fetching file list from PHOTOROOM ...")
    result = subprocess.run(
        ["rclone", "lsf", PHOTOROOM_REMOTE],
        capture_output=True, text=True, check=True
    )
    all_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    print(f"  {len(all_files)} files found.")

    # 2. Group by timestamp
    groups = group_by_gap(all_files, GAP_SECONDS)
    print(f"  {len(groups)} groups (1-minute gap threshold).\n")

    # 3. Filter already done
    pending = [g for g in groups if g[0] not in done]
    print(f"  {len(done)} already done, {len(pending)} remaining.\n")

    if not pending:
        print("All groups processed!")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for idx, group in enumerate(pending, 1):
            first = group[0]
            ts = parse_timestamp(first)
            ts_str = ts.strftime("%H:%M:%S") if ts else "?"
            print(f"─── Group {idx}/{len(pending)}  ({len(group)} images, starts {ts_str}) ───")

            # Download first image for preview
            preview_path = tmp / "preview.png"
            print(f"  Downloading preview: {first}")
            try:
                rclone_download_file(f"{PHOTOROOM_REMOTE}/{first}", preview_path)
            except subprocess.CalledProcessError as e:
                print(f"  FAILED to download: {e}")
                continue

            # Open in image viewer
            open_image_viewer(preview_path)
            time.sleep(1)   # give viewer time to open

            # AI suggestion
            print("  Asking Claude for name suggestions ...", end=" ", flush=True)
            try:
                folder_suggestion, seo_suggestion = ai_suggest(preview_path, api_key)
                print("done")
                print(f"  → Folder : {folder_suggestion}")
                print(f"  → SEO    : {seo_suggestion}")
            except Exception as e:
                print(f"failed ({e})")
                folder_suggestion, seo_suggestion = "", ""

            # User confirms / edits
            print()
            folder_name = input(f"  Folder name [{folder_suggestion}]: ").strip() or folder_suggestion
            seo_slug    = input(f"  SEO slug    [{seo_suggestion}]: ").strip() or seo_suggestion

            if not folder_name or not seo_slug:
                skip = input("  No name given — skip this group? (y/n): ").strip().lower()
                if skip == "y":
                    print("  Skipped.\n")
                    continue

            # Download all images in group
            group_dir = tmp / "group"
            group_dir.mkdir(exist_ok=True)

            print(f"  Downloading {len(group)} image(s) ...")
            for i, fname in enumerate(group, 1):
                out_path = group_dir / f"{seo_slug}-{i:02d}.png"
                try:
                    rclone_download_file(f"{PHOTOROOM_REMOTE}/{fname}", out_path)
                except subprocess.CalledProcessError:
                    print(f"    FAILED: {fname}")

            # Upload to My Products/[folder_name]/
            print(f"  Uploading to My Products/{folder_name}/ ...")
            try:
                rclone_upload_dir(group_dir, folder_name, MYPRODUCTS_FOLDER_ID)
            except subprocess.CalledProcessError as e:
                print(f"  Upload FAILED: {e}")
                shutil.rmtree(group_dir)
                continue

            # Clean up group dir for next iteration
            shutil.rmtree(group_dir)
            group_dir.mkdir()

            # Mark done
            progress["done_groups"].append(first)
            save_progress(progress)

            print(f"  Done. My Products/{folder_name}/\n")

    print("Session complete.")


if __name__ == "__main__":
    main()
