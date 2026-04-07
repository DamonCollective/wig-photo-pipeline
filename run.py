#!/usr/bin/env python3
"""
run.py — cross-platform runner for wig-photo-pipeline.

Works on:
  - iMac / macOS  (rclone remote: Gdrive_M / Gdrive_M_rw)
  - Windows Work  (rclone remote: gdrive / gdrive_rw, Fujitsu Win10)

Usage:
  python run.py             # download + remove bg -> saves to wig_workspace/YYYY-MM-DD/
  python run.py --upload    # upload wig_workspace/YYYY-MM-DD/ to Google Drive
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

# Ensure UTF-8 output on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR     = Path(__file__).parent
DEST_FOLDER_ID = "13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"

PROFILES = {
    "Darwin": {
        "rclone":    "rclone",
        "python":    "python3",
        "remote_ro": "Gdrive_M",
        "remote_rw": "Gdrive_M",       # same remote on iMac (full access)
        "source":    "ΔΑΜΩΝ/iphone_photos",
        "workspace": Path.home() / "wig_workspace",
    },
    "Windows": {
        "rclone":    r"C:\Users\Damon\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.3-windows-amd64\rclone.exe",
        "python":    "python",
        "remote_ro": "gdrive",
        "remote_rw": "gdrive_rw",      # separate read-write remote for uploads
        "source":    "ΔΑΜΩΝ/iphone_photos",
        "workspace": Path.home() / "wig_workspace",
    },
}

INCLUDE_FILTERS = [
    "--include", "*.jpg",  "--include", "*.jpeg", "--include", "*.png",
    "--include", "*.heic", "--include", "*.heif",
    "--include", "*.JPG",  "--include", "*.JPEG", "--include", "*.PNG",
    "--include", "*.HEIC", "--include", "*.HEIF",
]


def run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def cmd_process(p, rclone, today, workspace):
    """Download new images and remove backgrounds -> workspace/YYYY-MM-DD/"""
    source_dir = workspace / "source"
    out_dir    = workspace / today
    source_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download from Drive
    print(f"\n>> Downloading from {p['remote_ro']}:{p['source']} ...")
    run([rclone, "copy", f"{p['remote_ro']}:{p['source']}", str(source_dir),
         "--drive-skip-gdocs"] + INCLUDE_FILTERS + ["-P"])

    images = [f for f in source_dir.iterdir() if f.is_file()]
    if not images:
        print("No images found in iphone_photos. Nothing to do.")
        return

    print(f"  Found {len(images)} image(s).")

    # 2. Write temp config
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        json.dump({"source": str(source_dir), "dest": str(workspace)}, tf)
        config_path = tf.name

    # 3. Run bg-removal pipeline
    print("\n>> Running background removal pipeline...")
    env = os.environ.copy()
    env["CONFIG_FILE"]        = config_path
    env["PYTHONIOENCODING"]   = "utf-8"
    try:
        run([p["python"], str(SCRIPT_DIR / "process_wigs.py")], env=env)
    finally:
        os.unlink(config_path)

    count = len(list(out_dir.glob("*.png")))
    print(f"\nDone. {count} processed image(s) saved to:")
    print(f"  {out_dir}")
    print("\nReview them, then run:  python run.py --upload")


def cmd_upload(p, rclone, today, workspace):
    """Upload workspace/YYYY-MM-DD/ to Google Drive My Products."""
    out_dir = workspace / today

    if not out_dir.exists() or not any(out_dir.glob("*.png")):
        print(f"No processed images found in {out_dir}")
        print("Run without --upload first to process images.")
        sys.exit(1)

    count = len(list(out_dir.glob("*.png")))
    print(f"\n>> Uploading {count} image(s) to Google Drive / My Products / {today} ...")
    run([rclone, "copy", str(out_dir), f"{p['remote_rw']}:{today}",
         "--drive-root-folder-id", DEST_FOLDER_ID, "-P"])

    print(f"\nDone. {count} image(s) uploaded.")
    print(f"https://drive.google.com/drive/folders/{DEST_FOLDER_ID}")


def main():
    upload_mode = "--upload" in sys.argv

    system = platform.system()
    if system not in PROFILES:
        print(f"Unsupported OS: {system}")
        sys.exit(1)

    p         = PROFILES[system]
    rclone    = p["rclone"]
    today     = date.today().isoformat()
    workspace = p["workspace"]
    workspace.mkdir(parents=True, exist_ok=True)

    if upload_mode:
        cmd_upload(p, rclone, today, workspace)
    else:
        cmd_process(p, rclone, today, workspace)


if __name__ == "__main__":
    main()
