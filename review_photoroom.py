#!/usr/bin/env python3
"""
review_photoroom.py — Interactive review, naming, and organizing of PHOTOROOM images.

For each group of images (grouped by 1-minute timestamp gap):
  1. Downloads the first image from Drive and opens it in your image viewer
  2. You type a folder name and SEO slug
  3. Downloads all images in the group
  4. Renames: seo-name-01.png, 02.png ...
  5. Uploads to My Products/[FOLDER NAME]/ on Drive
  6. Saves progress — safe to interrupt and resume

Usage:
  python3 review_photoroom.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PROGRESS_FILE        = Path(__file__).parent / "photoroom_progress.json"
PHOTOROOM_REMOTE     = "Gdrive_M:PHOTOROOM"
MYPRODUCTS_FOLDER_ID = "13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"
GAP_SECONDS          = 60   # images more than 60s apart = different wig

# ── progress tracking ──────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"done_groups": []}

def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

# ── timestamp parsing ──────────────────────────────────────────────────────────

def parse_timestamp(filename: str) -> datetime | None:
    m = re.search(r"IMG_(\d{8})_(\d{6})", filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None

# ── grouping ───────────────────────────────────────────────────────────────────

def group_by_gap(files: list[str], gap_seconds: int) -> list[list[str]]:
    timestamped = []
    for f in files:
        ts = parse_timestamp(f)
        if ts:
            timestamped.append((ts, f))

    timestamped.sort(key=lambda x: x[0])

    groups, current, last_ts = [], [], None
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

# ── rclone helpers ─────────────────────────────────────────────────────────────

def rclone_download(remote_path: str, local_path: Path):
    subprocess.run(
        ["rclone", "copyto", remote_path, str(local_path)],
        check=True, capture_output=True
    )

def rclone_upload(local_dir: Path, folder_name: str):
    subprocess.run(
        [
            "rclone", "copy", str(local_dir),
            f"Gdrive_M:{folder_name}",
            "--drive-root-folder-id", MYPRODUCTS_FOLDER_ID,
            "-P",
        ],
        check=True,
    )

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    progress = load_progress()
    done = set(progress["done_groups"])

    print("Fetching file list from PHOTOROOM ...")
    result = subprocess.run(
        ["rclone", "lsf", PHOTOROOM_REMOTE],
        capture_output=True, text=True, check=True
    )
    all_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    print(f"  {len(all_files)} files found.")

    groups = group_by_gap(all_files, GAP_SECONDS)
    print(f"  {len(groups)} groups (1-minute gap threshold).")

    pending = [g for g in groups if g[0] not in done]
    print(f"  {len(done)} done, {len(pending)} remaining.\n")

    if not pending:
        print("All groups processed!")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for idx, group in enumerate(pending, 1):
            first = group[0]
            ts = parse_timestamp(first)
            ts_str = ts.strftime("%H:%M:%S") if ts else "?"
            print(f"─── Group {idx}/{len(pending)}  ({len(group)} image(s), starts {ts_str}) ───")

            # Download and show first image
            preview_path = tmp / "preview.png"
            try:
                rclone_download(f"{PHOTOROOM_REMOTE}/{first}", preview_path)
            except subprocess.CalledProcessError:
                print("  FAILED to download preview — skipping.")
                continue

            open_image_viewer(preview_path)
            time.sleep(1)

            # User types names
            print()
            folder_name = input("  Folder name (e.g. GRAY COUNT 1800): ").strip()
            seo_slug    = input("  SEO slug    (e.g. gray-georgian-court-wig-1800): ").strip().lower().replace(" ", "-")

            if not folder_name or not seo_slug:
                ans = input("  Empty name — skip this group? (y/n): ").strip().lower()
                if ans == "y":
                    print("  Skipped.\n")
                    continue

            # Download all images in group
            group_dir = tmp / "group"
            group_dir.mkdir(exist_ok=True)

            print(f"  Downloading {len(group)} image(s) ...")
            for i, fname in enumerate(group, 1):
                out = group_dir / f"{seo_slug}-{i:02d}.png"
                try:
                    rclone_download(f"{PHOTOROOM_REMOTE}/{fname}", out)
                    print(f"    {fname} → {out.name}")
                except subprocess.CalledProcessError:
                    print(f"    FAILED: {fname}")

            # Upload
            print(f"  Uploading to My Products/{folder_name}/ ...")
            try:
                rclone_upload(group_dir, folder_name)
            except subprocess.CalledProcessError as e:
                print(f"  Upload FAILED: {e}")
                shutil.rmtree(group_dir)
                continue

            shutil.rmtree(group_dir)
            group_dir.mkdir()

            progress["done_groups"].append(first)
            save_progress(progress)
            print(f"  Saved. My Products/{folder_name}/\n")

    print("Session complete.")


if __name__ == "__main__":
    main()
