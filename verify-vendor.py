#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check exact vendor digests, with two declared Git checkout EOL variants."""

import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import sys


# These are the only Windows batch files in signed ZUPT v5.2.10. Its
# .gitattributes declares text eol=crlf; Git blobs/source exports contain LF.
CRLF_PATHS = frozenset({
    'gui/packaging/windows/build-windows.bat',
    'packaging/portable/zupt-gui.bat',
})


def verify(manifest, source):
    source = source.resolve(strict=True)
    seen = set()
    for line in manifest.read_text(encoding='ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('Malformed source manifest entry')
        expected, name = match.groups()
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or
                str(relative) != name or name in seen):
            raise ValueError(f'Invalid or duplicate source path: {name}')
        seen.add(name)
        path = source.joinpath(*relative.parts)
        # Never hash through a file or ancestor symlink.
        for parent in relative.parents:
            if not stat.S_ISDIR(source.joinpath(*parent.parts).lstat().st_mode):
                raise ValueError(f'Non-directory source parent: {name}')
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f'Not a regular source file: {name}')
        data = path.read_bytes()
        if name in CRLF_PATHS and b'\r' in data:
            canonical = data.replace(b'\r\n', b'\n')
            if b'\r' in canonical or canonical.replace(b'\n', b'\r\n') != data:
                raise ValueError(f'Mixed or invalid source line endings: {name}')
            data = canonical
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'Source checksum mismatch: {name}')
        print(f'{name}: OK')
    if not seen:
        raise ValueError('Empty source manifest')


def main():
    if len(sys.argv) != 3:
        print('Usage: verify-vendor.py MANIFEST SOURCE_DIRECTORY', file=sys.stderr)
        return 2
    try:
        verify(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
