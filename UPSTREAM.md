# Upstream provenance

The bundled CLI tree is the promoted ZUPT 5.2.9 release archive, not a moving
default-branch snapshot.

| Field | Value |
|---|---|
| Repository | `https://github.com/cristiancmoises/zupt` |
| Release | `v5.2.9` |
| Tag commit | `63f27dd0c5afcf155f813a069c29f6384d46790c` |
| Source asset | `zupt-5.2.9.tar.gz` |
| SHA-256 | `24e1e3251c0bbcab049d3a7c3f1451e1b824fbb95ef454ca7c03077c8a470171` |
| Size | 817395 bytes |
| Local path | `zupt-5.2.9/` |
| Retrieved | 2026-09-06 |

The release's exact-tag CI run completed all 15 jobs successfully:
`https://github.com/cristiancmoises/zupt/actions/runs/34048047543`.

`zupt-5.2.9.SHA256SUMS` records all 203 regular files extracted from that
verified asset. `build-zupt.sh` validates every entry before invoking any
upstream build command, so a modified bundled source file fails closed.

Verify a freshly downloaded asset before replacing the bundled tree:

```bash
curl -fLO https://github.com/cristiancmoises/zupt/releases/download/v5.2.9/zupt-5.2.9.tar.gz
printf '%s  %s\n' \
  24e1e3251c0bbcab049d3a7c3f1451e1b824fbb95ef454ca7c03077c8a470171 \
  zupt-5.2.9.tar.gz | sha256sum --check --strict
```

The release archive intentionally omits three export-only package recipes
found in the Git tag. That difference is upstream-defined. Do not fill the
missing paths from `master` or otherwise mix tagged and untagged sources.

ZUPT 5.2.9 carries the VaptVupt codec release 2.65.11. “VaptVupt” remains the
proper codec/API compatibility name in files such as `vaptvupt_api.c` and in
the `--vaptvupt` option; it is not the CLI or web-project name.

No `libvuptsdk` or `libpqvaptvupt` artifact is bundled. Both integrations are
disabled to retain upstream's auditable source-only boundary.
