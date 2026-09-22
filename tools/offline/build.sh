#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PREFIX="$ROOT/.offline"
BIN="$PREFIX/bin"
mkdir -p "$BIN"

if ! command -v cc >/dev/null 2>&1; then
  echo "A C compiler named 'cc' is required." >&2
  exit 2
fi

KISSAT_SRC="$ROOT/third_party/kissat"
if [ ! -x "$BIN/kissat" ]; then
  (
    cd "$KISSAT_SRC"
    ./configure --quiet CC=cc
    make -C build -j2
  )
  cp "$KISSAT_SRC/build/kissat" "$BIN/kissat"
  rm -rf "$KISSAT_SRC/build"
fi

if [ ! -x "$BIN/drat-trim" ]; then
  cc -std=c99 -O2 "$ROOT/third_party/drat-trim/drat-trim.c" -o "$BIN/drat-trim"
fi

"$BIN/kissat" --version
echo "drat-trim: $BIN/drat-trim"
