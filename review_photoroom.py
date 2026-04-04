#!/usr/bin/env python3
"""
review_photoroom.py — Interactive review, naming, and organizing of PHOTOROOM images.

Main thread: shows preview → gets your input → moves to next group immediately.
Background worker: downloads all images, saves locally, uploads to Drive.

Keys:
  <name>  → folder name, then SEO slug
  s       → send to SKIPPED folder
  x       → ignore completely (mark done, no upload)
  p       → same folder as previous group

Usage:
  python3 review_photoroom.py
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

PROGRESS_FILE        = Path(__file__).parent / "photoroom_progress.json"
PHOTOROOM_REMOTE     = "Gdrive_M:PHOTOROOM"
MYPRODUCTS_FOLDER_ID = "13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"
WORKSPACE            = Path.home() / "wig_workspace"
GAP_SECONDS          = 60

# ── thread-safe print ──────────────────────────────────────────────────────────

_print_lock = threading.Lock()

def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

# ── progress ───────────────────────────────────────────────────────────────────

_progress_lock = threading.Lock()

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"done_groups": []}

def save_progress(progress: dict):
    with _progress_lock:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, indent=2)

# ── timestamp / grouping ───────────────────────────────────────────────────────

def parse_timestamp(filename: str) -> datetime | None:
    m = re.search(r"IMG_(\d{8})_(\d{6})", filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None

def group_by_gap(files: list[str], gap_seconds: int) -> list[list[str]]:
    timestamped = [(parse_timestamp(f), f) for f in files if parse_timestamp(f)]
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

# ── rclone ─────────────────────────────────────────────────────────────────────

def rclone_download(remote_path: str, local_path: Path):
    subprocess.run(
        ["rclone", "copyto", remote_path, str(local_path)],
        check=True, capture_output=True
    )

def rclone_upload(local_dir: Path, folder_name: str):
    subprocess.run(
        ["rclone", "copy", str(local_dir),
         f"Gdrive_M:{folder_name}",
         "--drive-root-folder-id", MYPRODUCTS_FOLDER_ID],
        check=True, capture_output=True
    )

# ── background worker ──────────────────────────────────────────────────────────

def worker(work_queue: queue.Queue, progress: dict):
    """Runs in background: download → save local → upload → mark done."""
    while True:
        item = work_queue.get()
        if item is None:
            work_queue.task_done()
            break

        group, folder_name, seo_slug, start_i, first = item

        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir)

            # Download all images
            tprint(f"\n  [↑ {folder_name}] Downloading {len(group)} image(s) ...")
            ok = 0
            for i, fname in enumerate(group, start_i):
                out = group_dir / f"{seo_slug}-{i:02d}.png"
                try:
                    rclone_download(f"{PHOTOROOM_REMOTE}/{fname}", out)
                    ok += 1
                except subprocess.CalledProcessError:
                    tprint(f"  [↑ {folder_name}] FAILED: {fname}")

            # Save local copy
            if folder_name != "SKIPPED":
                local_dest = WORKSPACE / folder_name
                local_dest.mkdir(parents=True, exist_ok=True)
                for f in group_dir.iterdir():
                    shutil.copy2(f, local_dest / f.name)

            # Upload to Drive
            try:
                rclone_upload(group_dir, folder_name)
                tprint(f"  [↑ {folder_name}] Done — {ok} file(s) uploaded.")
            except subprocess.CalledProcessError as e:
                tprint(f"  [↑ {folder_name}] Upload FAILED: {e}")
                work_queue.task_done()
                continue

        progress["done_groups"].append(first)
        save_progress(progress)
        work_queue.task_done()

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

    # Start background worker
    work_queue = queue.Queue()
    t = threading.Thread(target=worker, args=(work_queue, progress), daemon=True)
    t.start()

    prev_folder = None
    prev_seo    = None
    prev_count  = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for idx, group in enumerate(pending, 1):
            first    = group[0]
            ts_first = parse_timestamp(first)
            ts_str   = ts_first.strftime("%H:%M:%S") if ts_first else "?"

            gap_str = ""
            if idx > 1 and ts_first:
                prev_last_ts = parse_timestamp(pending[idx - 2][-1])
                if prev_last_ts:
                    gap = int((ts_first - prev_last_ts).total_seconds())
                    gap_str = f"  ← {gap}s after previous"

            print(f"\n─── Group {idx}/{len(pending)}  ({len(group)} image(s), starts {ts_str}){gap_str} ───")

            # Download preview (just first image)
            preview_path = tmp / f"preview_{idx}.png"
            try:
                rclone_download(f"{PHOTOROOM_REMOTE}/{first}", preview_path)
            except subprocess.CalledProcessError:
                print("  FAILED to download preview — skipping.")
                continue

            open_image_viewer(preview_path)
            time.sleep(1)

            # Get user input
            if prev_folder:
                prompt = f"  Name / 's' skip / 'x' ignore / 'p' = {prev_folder}: "
            else:
                prompt = "  Folder name / 's' skip / 'x' ignore: "

            folder_name = input(prompt).strip()

            if folder_name.lower() == "x":
                progress["done_groups"].append(first)
                save_progress(progress)
                print("  Ignored.")
                continue

            elif folder_name.lower() == "s":
                folder_name = "SKIPPED"
                seo_slug    = "skipped"

            elif folder_name.lower() == "p" and prev_folder:
                folder_name = prev_folder
                seo_slug    = prev_seo

            else:
                seo_slug = input("  SEO slug: ").strip().lower().replace(" ", "-")

            if not folder_name or not seo_slug:
                print("  Empty — skipping.")
                continue

            # Starting index
            if folder_name == prev_folder and folder_name != "SKIPPED":
                start_i = prev_count + 1
            else:
                start_i = 1

            # Update prev tracking
            if folder_name != "SKIPPED":
                if folder_name == prev_folder:
                    prev_count += len(group)
                else:
                    prev_folder = folder_name
                    prev_seo    = seo_slug
                    prev_count  = len(group)

            # Queue the work — background thread handles the rest
            work_queue.put((group, folder_name, seo_slug, start_i, first))
            print(f"  Queued → My Products/{folder_name}/  (processing in background)")

    # Wait for all background jobs to finish
    work_queue.put(None)
    print("\nWaiting for background uploads to finish ...")
    work_queue.join()
    t.join()
    print("All done.")


if __name__ == "__main__":
    main()
