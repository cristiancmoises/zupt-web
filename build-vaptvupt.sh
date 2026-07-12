#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Builder stage script. Runs inside the Docker builder image, in /build,
# after `COPY vaptvupt-5.2.1/ .` has placed the source.
#
# Steps:
#   1. Defensively recreate libvuptsdk.so / .so.2 symlinks if missing.
#      (Some git clones, .dockerignore filters, or non-symlink-aware
#      file transfers strip these. The Makefile needs them to link
#      against -lvuptsdk.)
#   2. Clean + build with all available cores, WITH_SDK=1 so --pq-sdk
#      and the Argon2id password KDF are available (links the vendored
#      libvuptsdk plus -lcrypto -largon2).
#   3. Strip debug symbols.
#   4. Retarget the binary's RUNPATH from the build-tree-relative
#      vendor/vuptsdk paths to the canonical /usr/lib/vaptvupt that the
#      runtime image will use.
#   5. Print the resulting RUNPATH for the build log.

set -eu

# Resolve the source root: the directory where this script lives.
# This works whether invoked from /build inside the Docker builder
# image or from any other test harness.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Inside the Docker builder the source tree IS the script dir (/build).
# From a repo checkout the source tree is the vaptvupt-5.2.1/ subdir —
# hop into it so the script works in both places.
if [ ! -d vendor/vuptsdk ] && [ -d vaptvupt-5.2.1/vendor/vuptsdk ]; then
    cd vaptvupt-5.2.1
    SCRIPT_DIR="$PWD"
fi

cd vendor/vuptsdk

# Recreate the SONAME and ld-name symlinks if missing or dangling.
# Idempotent — does nothing if they're already valid.
for link in libvuptsdk.so libvuptsdk.so.2; do
    if [ ! -L "$link" ] || [ ! -e "$link" ]; then
        ln -sf libvuptsdk.so.2.0.0 "$link"
    fi
done

ls -la libvuptsdk.so*

cd "$SCRIPT_DIR"
make clean
make WITH_SDK=1 -j"$(nproc)"
strip vaptvupt
patchelf --set-rpath /usr/lib/vaptvupt vaptvupt
readelf -d vaptvupt | grep -E 'RUNPATH|RPATH'
