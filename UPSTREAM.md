# Upstream provenance

The bundled `zupt-5.2.10/` tree is the complete tracked source of the coordinated
ZUPT 5.2.10 release candidate, including source-only package recipes and license
notices. Its immutable signed `v5.2.10` tag resolves to
`3b3b8f494b4bdd3b74aab60388eef1694ef316f8`. The source matches all 206 tracked
files of that commit. It imports VaptVupt 2.65.13 matcher-setup changes from
signed codec commit `e30dc9329be7cf9f233b1ac0b1fc9ed31f530391`, retaining ZUPT's
existing GPL notices and wrapper policy. Public availability and cross-OS
promotion must be checked independently of this local signed source pin.

Web 5.2.11 still bundles desktop ZUPT 5.2.10; these version boundaries are
independent. The immutable Web v5.2.10 tag is blocked by its checkout-EOL
manifest mismatch and is not moved or represented as deployable.

`zupt-5.2.10.SHA256SUMS` pins canonical Git-blob digests. `verify-vendor.py`
accepts LF or its exact pure CRLF transformation only for
`gui/packaging/windows/build-windows.bat` and `packaging/portable/zupt-gui.bat`,
as declared by the signed source's `.gitattributes`. Mixed/bare-CR endings,
tampering and every undeclared byte transformation fail. `build-zupt.sh`
retains the exact source-file set and source-only gates. Validate with:

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
