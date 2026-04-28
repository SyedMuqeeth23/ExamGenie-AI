#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAGRAM_DIR="$ROOT_DIR/docs/diagrams"

if ! command -v npx >/dev/null 2>&1; then
  echo "[compile-diagrams] npx is not installed. Install Node.js to compile Mermaid diagrams."
  exit 0
fi

if [[ ! -d "$DIAGRAM_DIR" ]]; then
  echo "[compile-diagrams] Diagram directory not found: $DIAGRAM_DIR"
  exit 0
fi

shopt -s nullglob
files=("$DIAGRAM_DIR"/*.mmd)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "[compile-diagrams] No .mmd files found in $DIAGRAM_DIR"
  exit 0
fi

for input in "${files[@]}"; do
  base="${input%.mmd}"
  svg_out="$base.svg"
  png_out="$base.png"

  echo "[compile-diagrams] Building $(basename "$input") -> $(basename "$svg_out"), $(basename "$png_out")"
  npx -y @mermaid-js/mermaid-cli -i "$input" -o "$svg_out" -b transparent
  npx -y @mermaid-js/mermaid-cli -i "$input" -o "$png_out" -b transparent

done

echo "[compile-diagrams] Done."
