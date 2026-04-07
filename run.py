#!/usr/bin/env python3
"""
run.py — cross-platform runner for wig-photo-pipeline.

Works on:
  - iMac / macOS  (rclone remote: Gdrive_M)
  - Windows Work  (rclone remote: gdrive, Fujitsu Win10)

Usage:
  python3 run.py      # macOS
  python run.py       # Windows
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

DEST_FOLDER_ID = "13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"

PROFILES = {
    "Darwin": {
        "rclone": "rclone",
        "python": "python3",
        "remote": "Gdrive_M",
        "source": "ΔΑΜΩΝ/iphone_photos",
    },
    "Windows": {
        "rclone": r"C:\Users\Damon\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.3-windows-amd64\rclone.exe",
        "python": "python",
        "remote": "gdrive",
        "source": "ΔΑΜΩΝ/iphone_photos",
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


def main():
    system = platform.system()
    if system not in PROFILES:
        print(f"Unsupported OS: {system}")
        sys.exit(1)

    p = PROFILES[system]
    rclone = p["rclone"]
    remote = p["remote"]

    with tempfile.TemporaryDirectory() as tmp:
        local_source = Path(tmp) / "source"
        local_dest   = Path(tmp) / "dest"
        local_source.mkdir()
        local_dest.mkdir()

        # 1. Download images from Drive
        print(f"\n→ Downloading from {remote}:{p['source']} ...")
        run([rclone, "copy", f"{remote}:{p['source']}", str(local_source),
             "--drive-skip-gdocs"] + INCLUDE_FILTERS + ["-P"])

        images = [f for f in local_source.iterdir() if f.is_file()]
        if not images:
            print("No new images found in iphone_photos. Nothing to do.")
            return
        print(f"  Found {len(images)} image(s).")

        # 2. Write temp config pointing to local folders
        config_path = Path(tmp) / "config.json"
        config_path.write_text(json.dumps({
            "source": str(local_source),
            "dest":   str(local_dest),
        }))

        # 3. Run bg-removal pipeline
        print("\n→ Running background removal pipeline...")
        env = os.environ.copy()
        env["CONFIG_FILE"] = str(config_path)
        run([p["python"], str(SCRIPT_DIR / "process_wigs.py")], env=env)

        # 4. Upload results to Drive under today's date folder
        today   = date.today().isoformat()
        out_dir = local_dest / today

        if not out_dir.exists() or not any(out_dir.iterdir()):
            print("No output generated.")
            return

        print(f"\n→ Uploading to Google Drive / My Products / {today} ...")
        run([rclone, "copy", str(out_dir), f"{remote}:{today}",
             "--drive-root-folder-id", DEST_FOLDER_ID, "-P"])

        count = len(list(out_dir.glob("*.png")))
        print(f"\nDone. {count} image(s) uploaded to My Products / {today}")
        print(f"https://drive.google.com/drive/folders/{DEST_FOLDER_ID}")


if __name__ == "__main__":
    main()
