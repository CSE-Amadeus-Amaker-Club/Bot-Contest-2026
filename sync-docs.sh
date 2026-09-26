#!/bin/bash
#
# sync-docs.sh
# Synchronize k10-bot-gh-pages repo with source k10-bot repo
# 
# Usage: bash sync-docs.sh [--check] [--push]
#   --check    : Show what would be synced (dry-run)
#   --push     : Auto-commit and push changes to git
#

set -e

SRC="/home/taccart/Documents/PlatformIO/Projects/k10-bot"
DST="/home/taccart/Documents/PlatformIO/Projects/k10-bot-gh-pages"
CHECK_MODE=false
PUSH_MODE=false
SYNC_LOG="$DST/.sync-log.txt"

# Parse arguments
for arg in "$@"; do
  case $arg in
    --check) CHECK_MODE=true ;;
    --push)  PUSH_MODE=true ;;
  esac
done

echo "========================================" | tee -a "$SYNC_LOG"
echo "k10-bot-gh-pages Sync" >> "$SYNC_LOG"
echo "Generated: $(date)" >> "$SYNC_LOG"
echo "========================================" >> "$SYNC_LOG"

if [[ "$CHECK_MODE" == "true" ]]; then
  echo "[DRY-RUN MODE] No changes will be made" | tee -a "$SYNC_LOG"
fi

echo ""

# =====================================================
# 1. Sync Markdown Documentation
# =====================================================
echo "[1/3] Syncing Markdown Documentation..."
md_count=0

for src_md in "$SRC"/data/www/help/*.md; do
  basename=$(basename "$src_md")
  dst_md="$DST/$basename"
  
  if [[ ! -f "$dst_md" ]] || ! diff -q "$src_md" "$dst_md" > /dev/null 2>&1; then
    if [[ "$CHECK_MODE" == "false" ]]; then
      cp "$src_md" "$dst_md"
    fi
    echo "  ✓ $basename" | tee -a "$SYNC_LOG"
    ((md_count++))
  fi
done

if [[ $md_count -eq 0 ]]; then
  echo "  (no changes)" | tee -a "$SYNC_LOG"
fi

# =====================================================
# 2. Sync Python Example Code
# =====================================================
echo ""
echo "[2/3] Syncing Python Example Code..."

if [[ "$CHECK_MODE" == "false" ]]; then
  mkdir -p "$DST/python_example"
  rsync -q --delete \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='venv' \
    --exclude='.venv' \
    "$SRC/example-clients/python/" "$DST/python_example/"
  echo "  ✓ Python example synced" | tee -a "$SYNC_LOG"
else
  echo "  (would sync python_example/)" | tee -a "$SYNC_LOG"
fi

# =====================================================
# 3. Sync Images & Assets
# =====================================================
echo ""
echo "[3/3] Syncing Images & Assets..."

img_count=0

# Copy image files referenced in markdown
for img_file in DFR1216Board.svg wiring.png Bill\ of\ material\ pieces.jpg book_chapters.png contest-guide-ideas.png svgreen64.png svgrey64.png; do
  src_img="$SRC/data/www/help/$img_file"
  
  if [[ -f "$src_img" ]]; then
    dst_img="$DST/$(basename "$img_file")"
    
    if [[ ! -f "$dst_img" ]] || ! diff -q "$src_img" "$dst_img" > /dev/null 2>&1; then
      if [[ "$CHECK_MODE" == "false" ]]; then
        cp "$src_img" "$dst_img"
      fi
      echo "  ✓ $(basename "$img_file")" | tee -a "$SYNC_LOG"
      ((img_count++))
    fi
  fi
done

if [[ $img_count -eq 0 ]]; then
  echo "  (no changes)" | tee -a "$SYNC_LOG"
fi

# =====================================================
# Summary
# =====================================================
echo ""
echo "========================================" >> "$SYNC_LOG"
if [[ "$CHECK_MODE" == "true" ]]; then
  echo "SUMMARY (dry-run)"
else
  echo "SUMMARY"
fi
echo "  Markdown docs updated: $md_count"
echo "  Python example: synced"
echo "  Image assets updated: $img_count"
echo "========================================" >> "$SYNC_LOG"

# =====================================================
# Commit & Push (if requested)
# =====================================================
if [[ "$PUSH_MODE" == "true" ]] && [[ "$CHECK_MODE" == "false" ]]; then
  echo ""
  echo "Committing and pushing changes..."
  
  cd "$DST"
  
  if git diff --quiet --exit-code HEAD; then
    echo "  (no changes to commit)"
  else
    git add -A
    git commit -m "Sync docs and examples from source repo ($(date +%Y-%m-%d))" || true
    git push origin main || git push origin master || echo "  ⚠ Push failed (check git config)"
    echo "  ✓ Changes pushed"
  fi
fi

echo ""
echo "Sync complete!"
