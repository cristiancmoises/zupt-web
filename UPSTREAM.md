# Upstream provenance

The bundled `zupt-5.2.10/` directory matches the bytes of all 294 regular files in the
[official ZUPT 5.2.10 source package](https://github.com/cristiancmoises/zupt/releases/tag/v5.2.10).
Its executable modes were restored separately from immutable Git commit
`0165fbd78faf78046d49e004622820ef79061f17`; the archive does not preserve them.
Web 5.2.13 packages CLI 5.2.10; the two versions are independent.

ZUPT extracts regular files with mode 0600, including executable payloads.
After verifying a Web source package's signed checksums, restore only its
required entry points as shown in the [English](README.md#run) or
[Português do Brasil](README.pt-BR.md#execução) instructions. Do not add
execute permission recursively.

| Field | Value |
|---|---|
| Repository | `https://github.com/cristiancmoises/zupt` |
| Release | `v5.2.10` |
| Annotated tag object | `2aeb57cd1552dfcc67083b8f3571c810b3acdb38` |
| Runtime source commit | `0165fbd78faf78046d49e004622820ef79061f17` |
| Source asset | `zupt-5.2.10-source.zupt` |
| SHA-256 | `4173038fb8a7cd810d452268c2e32e7c976fbea0c1865efc4a8dcabfd41bbae9` |
| Source asset size | 1292464 bytes |
| Extracted regular files | 294 files, 3744560 bytes |
| Bundled manifest | `zupt-5.2.10.SHA256SUMS` |
| Manifest SHA-256 | `7c93bde2d3c0b07b0f866c48ef057541af540bf0bc5e7484db9bdb0c8d85aaf7` |
| Codec / archive format | VaptVupt 2.65.13 / ZUPT v1.6 |
| Release-signing fingerprint | `0CFA43B9AA9642EAAF2BE983C4C661C9ECFB46E8` |

The manifest uses paths relative to `zupt-5.2.10/`. `build-zupt.sh` checks
every canonical digest and the complete file set before compiling.
`verify-vendor.py` accepts canonical LF or its exact pure CRLF transformation
only for `gui/packaging/windows/build-windows.bat` and
`packaging/portable/zupt-gui.bat`, as declared by upstream `.gitattributes`.
Mixed/bare-CR endings, undeclared transformations, duplicate/traversing paths,
symlinks, and special files are rejected. To verify a clean source tree without building it:

```sh
./build-zupt.sh --verify-only
```

To check a downloaded source package, use an existing compatible ZUPT CLI and
GnuPG. Confirm the signing fingerprint through a trusted channel; a key shipped
beside a package is not sufficient evidence of its identity.

```sh
release_url=https://github.com/cristiancmoises/zupt/releases/download/v5.2.10
curl -fLO "$release_url/zupt-5.2.10-source.zupt"
curl -fLO "$release_url/SHA256SUMS"
curl -fLO "$release_url/SHA256SUMS.asc"
curl -fLO "$release_url/release-key.asc"
verify_keyring=$(mktemp -d)
chmod 0700 "$verify_keyring"
gpg --homedir "$verify_keyring" --import release-key.asc
test "$(gpg --homedir "$verify_keyring" --with-colons --fingerprint |
  awk -F: '$1 == "fpr" { print $10; exit }')" =   0CFA43B9AA9642EAAF2BE983C4C661C9ECFB46E8
gpg --homedir "$verify_keyring" --verify SHA256SUMS.asc SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
zupt test zupt-5.2.10-source.zupt
mkdir source-review
zupt extract -o source-review zupt-5.2.10-source.zupt
rm -rf -- "$verify_keyring"
```

Compare the extracted payload with the bundled manifest before replacing any
source. Preserve all `LICENSE*`, `NOTICE`, `THIRD-PARTY-NOTICES.md`, and
per-file notices. Do not fill paths from another upstream revision or change
vendored code to make a downstream gate pass.

The production CLI remains C11. The bundled Rust `no_std` varint experiment is
not used by this image. VaptVupt remains the codec/API name in `vaptvupt_api.c`
and the `--vaptvupt` option; it is not the web-project name. External opaque
SDK/PQBOX integrations are disabled with `WITH_SDK=0 WITH_PQBOX=0`.
