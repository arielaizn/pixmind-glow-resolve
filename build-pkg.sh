#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
VERSION="1.5.0"
ID="com.pixmind.resolve-hebrew-auto-captions"
OUT="dist/PixMindGlowCaptions-$VERSION.pkg"
mkdir -p dist build
find payload -name .DS_Store -delete
pkgbuild --root payload --identifier "$ID" --version "$VERSION" \
  --scripts scripts --ownership recommended --install-location / build/component.pkg
productbuild --package build/component.pkg --identifier "$ID" --version "$VERSION" "$OUT"
rm -rf build
echo "Built $OUT"
