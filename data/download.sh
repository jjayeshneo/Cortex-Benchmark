#!/usr/bin/env bash
# Fetch and verify the Cortex-Bench database.
#
# Every gold answer in this benchmark was produced by executing its reference SQL against ONE
# frozen database. An answer from a different snapshot is not a different answer -- it is a
# meaningless one. The hash check below is therefore not boilerplate: if it fails, stop.
set -euo pipefail

SNAPSHOT="wm_synthetic_v1.3_2026_09_01"
SHA256="7caa6785340cd23b4c2691df0cf8c0350718da13bba598338d10e4e8576ee8ed"
SIZE_BYTES=1152135168

# The database ships as a GitHub release asset. At 1.07 GB it is comfortably inside GitHub's
# 2 GiB per-file limit -- the generated file is 2.23 GB, but a bulk-load rebuild compacts it by
# 52% with byte-identical contents (verified: 373 columns, 22 tables, zero row differences in
# either direction, and gold-SQL mode reproduces 190/190 gold answers against it).
DEFAULT_URL="https://github.com/jjayeshneo/Cortex-Benchmark/releases/download/data-v1.3/wealth_management_v1.3.duckdb"
URL="${CORTEX_BENCH_DB_URL:-$DEFAULT_URL}"

DEST="${1:-data/wealth_management.duckdb}"
mkdir -p "$(dirname "$DEST")"

verify() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$SHA256  $f" | sha256sum -c - >/dev/null
  else
    local got
    got=$(shasum -a 256 "$f" | awk '{print $1}')
    [ "$got" = "$SHA256" ] || { echo "sha256 mismatch: got $got"; return 1; }
  fi
}

if [ -f "$DEST" ]; then
  echo "found $DEST -- verifying"
  if verify "$DEST"; then
    echo "OK: $DEST matches snapshot $SNAPSHOT"
    exit 0
  fi
  echo "ERROR: $DEST exists but does not match snapshot $SNAPSHOT."
  echo "Move it aside and re-run; do NOT score against it."
  exit 1
fi


echo "downloading $SNAPSHOT (~1.1 GB)..."
if command -v curl >/dev/null 2>&1; then
  curl -fL --retry 3 --retry-delay 2 -o "$DEST.part" "$URL"
else
  wget -O "$DEST.part" "$URL"
fi
mv "$DEST.part" "$DEST"

echo "verifying..."
verify "$DEST" || { echo "sha256 mismatch -- download is corrupt, not usable"; exit 1; }
echo "OK: $DEST  snapshot $SNAPSHOT"
