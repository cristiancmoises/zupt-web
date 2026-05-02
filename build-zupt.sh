#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Builder stage script. Runs inside the Docker builder image, in /build,
# after `COPY zupt-2.2.3/ .` has placed the source.
#
# Steps:
#   1. Defensively recreate libzuptsdk.so / .so.2 symlinks if missing.
#      (Some git clones, .dockerignore filters, or non-symlink-aware
#      file transfers strip these. The Makefile needs them to link
#      against -lzuptsdk.)
#   2. Clean + build with all available cores.
#   3. Strip debug symbols.
#   4. Retarget the binary's RUNPATH from the build-tree-relative
#      $ORIGIN/vendor/zuptsdk to the canonical /usr/lib/zupt that the
#      runtime image will use.
#   5. Print the resulting RUNPATH for the build log.

set -eu

# Resolve the source root: the directory where this script lives.
# This works whether invoked from /build inside the Docker builder
# image or from any other test harness.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cd vendor/zuptsdk

# Recreate the SONAME and ld-name symlinks if missing or dangling.
# Idempotent — does nothing if they're already valid.
for link in libzuptsdk.so libzuptsdk.so.2; do
    if [ ! -L "$link" ] || [ ! -e "$link" ]; then
        ln -sf libzuptsdk.so.2.0.0 "$link"
    fi
done

ls -la libzuptsdk.so*

cd "$SCRIPT_DIR"
make clean
make -j"$(nproc)"
strip zupt
patchelf --set-rpath /usr/lib/zupt zupt
readelf -d zupt | grep -E 'RUNPATH|RPATH'
