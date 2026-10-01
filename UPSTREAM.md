# Upstream provenance

The bundled `zupt-5.2.10/` tree is the complete tracked source of the corrected
ZUPT 5.2.10 release, including source-only package recipes and license
notices. Its signed corrected `v5.2.10` tag resolves to
`24995eb7652a31eedc46386bab14c63cbb31e050`. The source matches all 206 tracked
files of that commit. It imports VaptVupt 2.65.13 matcher-setup changes from
signed codec commit `e30dc9329be7cf9f233b1ac0b1fc9ed31f530391`, retaining ZUPT's
existing GPL notices and wrapper policy. This exact source pin does not by
itself establish the downstream image's cross-OS or deployment readiness.

Web 5.2.12 bundles the corrected desktop ZUPT 5.2.10; these version boundaries
are independent. The desktop source fixes POSIX password-prompt ordering and
signal interruption while retaining archive format 1.6 and codec 2.65.13.
The immutable Web v5.2.10 and v5.2.11 tags remain unchanged. Web v5.2.10 is
blocked by its checkout-EOL manifest mismatch and is not represented as
deployable; its own manifest still rejects its canonical LF batch-file export.
Web v5.2.11's corrected historical export verifies against its own manifest.

`zupt-5.2.10.SHA256SUMS` pins canonical Git-blob digests. `verify-vendor.py`
accepts LF or its exact pure CRLF transformation only for
`gui/packaging/windows/build-windows.bat` and `packaging/portable/zupt-gui.bat`,
as declared by the signed source's `.gitattributes`. Mixed/bare-CR endings,
tampering and every undeclared byte transformation fail. `build-zupt.sh`
retains the exact source-file set and source-only gates. The import uses every
regular Git blob at the pinned commit, including package recipes omitted by
Git archive's export-ignore rules. The historical tests pair each source
snapshot with its own manifest. Validate the current source with:

```sh
python3 verify-vendor.py zupt-5.2.10.SHA256SUMS zupt-5.2.10
```

Public release packages use genuine unencrypted `.zupt` archives, tested by
`zupt test` and accompanied by SHA-256 checksums. No unverified public asset
digest is invented here.

ZUPT 5.2.10 carries the native VaptVupt 2.65.13 codec. The `vaptvupt_api.c`
filename and `--vaptvupt` CLI option retain the codec/API name. Android does
not embed that codec: its STORE/raw-DEFLATE `zupt-android/v1.3` format is
independent of desktop `.zupt/v1.6` and is not interchangeable.

No `libvuptsdk` or `libpqvaptvupt` binary is bundled. Both optional integrations
are disabled to retain the auditable source-only boundary.
