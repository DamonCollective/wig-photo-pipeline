#!/usr/bin/env bash
# imac_run.sh — mounts damoncollective Drive, runs process_wigs.py, unmounts.
#
# One-time setup (run once, not needed again):
#   rclone config
#   → New remote → name: Gdrive_D → type: drive → sign in as damoncollective@gmail.com
#
# Usage:
#   chmod +x imac_run.sh
#   ./imac_run.sh

set -euo pipefail

REMOTE="Gdrive_D:ΔΑΜΩΝ/iphone_photos"
MOUNT_POINT="$HOME/damon_drive_mount"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

# ── helpers ────────────────────────────────────────────────────────────────────

is_mounted() {
    mountpoint -q "$MOUNT_POINT" 2>/dev/null || \
    mount | grep -q "$MOUNT_POINT"
}

unmount() {
    if is_mounted; then
        echo "Unmounting $MOUNT_POINT ..."
        fusermount -uz "$MOUNT_POINT" 2>/dev/null || umount "$MOUNT_POINT" 2>/dev/null || true
    fi
    rmdir "$MOUNT_POINT" 2>/dev/null || true
}

# Always unmount on exit (even on error or Ctrl-C)
trap unmount EXIT

# ── mount ──────────────────────────────────────────────────────────────────────

mkdir -p "$MOUNT_POINT"

if is_mounted; then
    echo "Already mounted at $MOUNT_POINT — reusing."
else
    echo "Mounting $REMOTE → $MOUNT_POINT ..."
    rclone mount "$REMOTE" "$MOUNT_POINT" \
        --read-only \
        --vfs-cache-mode full \
        --vfs-cache-max-age 1h \
        --daemon \
        --daemon-timeout 60s

    # Wait until the mount is ready (up to 15s)
    for i in $(seq 1 15); do
        if is_mounted; then break; fi
        sleep 1
    done

    if ! is_mounted; then
        echo "ERROR: Mount did not come up in time. Check: rclone listremotes"
        exit 1
    fi
    echo "Mounted OK."
fi

# ── update config.json source path on the fly ─────────────────────────────────

CONFIG="$SCRIPT_DIR/config.json"
if [ ! -f "$CONFIG" ]; then
    echo "ERROR: config.json not found. Copy config.example.json → config.json and set 'dest'."
    exit 1
fi

# Patch the source key to point to the mount (non-destructive — only changes source)
$PYTHON - <<PYEOF
import json, pathlib
cfg_path = pathlib.Path("$CONFIG")
cfg = json.loads(cfg_path.read_text())
cfg["source"] = "$MOUNT_POINT"
cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
PYEOF

# ── run pipeline ───────────────────────────────────────────────────────────────

echo ""
$PYTHON "$SCRIPT_DIR/process_wigs.py"
