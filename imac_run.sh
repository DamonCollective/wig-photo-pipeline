#!/usr/bin/env bash
# imac_run.sh — downloads new images from Gdrive_M, runs rembg pipeline, uploads results.
#
# Source:  Gdrive_M:ΔΑΜΩΝ/iphone_photos
# Dest:    My Products folder (Drive ID: 13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr)
#
# Usage:
#   chmod +x imac_run.sh
#   ./imac_run.sh

set -euo pipefail

REMOTE="Gdrive_M"
SOURCE_PATH="ΔΑΜΩΝ/iphone_photos"
DEST_FOLDER_ID="13M2tnha_H5-mV2qKU1RC_3YtCW2xQHwr"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

LOCAL_SOURCE="/tmp/wig_pipeline_source"
LOCAL_DEST="/tmp/wig_pipeline_dest"

# ── cleanup on exit ────────────────────────────────────────────────────────────
cleanup() {
    rm -rf "$LOCAL_SOURCE" "$LOCAL_DEST"
}
trap cleanup EXIT

# ── 1. download new images from Drive ─────────────────────────────────────────
echo "→ Syncing images from Drive..."
mkdir -p "$LOCAL_SOURCE"
rclone copy "${REMOTE}:${SOURCE_PATH}" "$LOCAL_SOURCE" \
    --include "*.jpg"  --include "*.jpeg" --include "*.png" \
    --include "*.heic" --include "*.heif" \
    --include "*.JPG"  --include "*.JPEG" --include "*.PNG" \
    --include "*.HEIC" --include "*.HEIF" \
    -P

COUNT=$(find "$LOCAL_SOURCE" -maxdepth 1 -type f | wc -l)
if [ "$COUNT" -eq 0 ]; then
    echo "No images found in iphone_photos. Nothing to do."
    exit 0
fi
echo "  Downloaded $COUNT image(s)."

# ── 2. write a temp config.json pointing to local folders ─────────────────────
mkdir -p "$LOCAL_DEST"
TEMP_CONFIG=$(mktemp /tmp/wig_config_XXXX.json)
cat > "$TEMP_CONFIG" <<EOF
{
  "source": "$LOCAL_SOURCE",
  "dest":   "$LOCAL_DEST"
}
EOF

# ── 3. run the pipeline ───────────────────────────────────────────────────────
echo ""
CONFIG_FILE="$TEMP_CONFIG" $PYTHON "$SCRIPT_DIR/process_wigs.py"
rm -f "$TEMP_CONFIG"

# ── 4. upload processed PNGs to My Products on Drive ─────────────────────────
TODAY=$(date +%Y-%m-%d)
OUT_SUBDIR="$LOCAL_DEST/$TODAY"

if [ ! -d "$OUT_SUBDIR" ] || [ -z "$(ls -A "$OUT_SUBDIR" 2>/dev/null)" ]; then
    echo "No output to upload."
    exit 0
fi

echo ""
echo "→ Uploading to Google Drive / My Products / $TODAY ..."
rclone copy "$OUT_SUBDIR" "${REMOTE}:$TODAY" \
    --drive-root-folder-id "$DEST_FOLDER_ID" \
    -P

echo ""
echo "Done. Check: https://drive.google.com/drive/folders/${DEST_FOLDER_ID}"
