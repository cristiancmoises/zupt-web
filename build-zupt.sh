#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Build and exercise the bundled ZUPT 5.2.8 source-only release. The script
# works both in the Docker builder (where /build is the source root) and from
# the zupt-web checkout.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
cd "$SCRIPT_DIR"

MANIFEST=$SCRIPT_DIR/zupt-5.2.8.SHA256SUMS

if [ ! -f include/zupt.h ] && [ -d zupt-5.2.8 ]; then
    cd zupt-5.2.8
fi

if [ ! -f include/zupt.h ] || [ ! -x scripts/check-source-only.sh ]; then
    echo "Error: could not locate the ZUPT 5.2.8 source tree" >&2
    exit 1
fi

if [ ! -f "$MANIFEST" ]; then
    echo "Error: missing upstream source manifest: $MANIFEST" >&2
    exit 1
fi

# The manifest was generated from the promoted release tarball after its
# published SHA-256 was verified. Every upstream file used by the build must
# still match byte-for-byte; generated build artifacts do not affect this gate.
sha256sum --check --strict "$MANIFEST"

case "$(sed -n 's/^#define ZUPT_VERSION_STRING "\([^"]*\)".*/\1/p' include/zupt.h)" in
    5.2.8) ;;
    *) echo "Error: bundled source is not ZUPT 5.2.8" >&2; exit 1 ;;
esac

# A previous local build may have generated ignored artifacts. The Makefile is
# already hash-verified above, so its narrowly scoped clean target is safe to
# run before proving the remaining file set is exactly the release manifest.
make clean

expected_files=$(mktemp "${TMPDIR:-/tmp}/zupt-expected.XXXXXXXX")
actual_files=$(mktemp "${TMPDIR:-/tmp}/zupt-actual.XXXXXXXX")
trap 'rm -f -- "$expected_files" "$actual_files"' EXIT HUP INT TERM
sed 's/^[0-9a-f]\{64\}  //' "$MANIFEST" | LC_ALL=C sort > "$expected_files"
find . -type f -print | sed 's#^\./##' | LC_ALL=C sort > "$actual_files"
if ! diff -u "$expected_files" "$actual_files"; then
    echo "Error: bundled ZUPT tree contains missing or unlisted files" >&2
    exit 1
fi

bash scripts/check-source-only.sh --tree .

jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)
case "$jobs" in
    ''|*[!0-9]*) jobs=1 ;;
esac

make -j"$jobs" WITH_SDK=0 WITH_PQBOX=0 V=1
make WITH_SDK=0 WITH_PQBOX=0 check

strip zupt

if readelf -d zupt | grep -Eq '(RPATH|RUNPATH)'; then
    echo "Error: source-only ZUPT binary unexpectedly contains RPATH/RUNPATH" >&2
    exit 1
fi

./zupt version
