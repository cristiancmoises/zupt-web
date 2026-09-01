# Upstream provenance

The bundled CLI tree is the promoted ZUPT 5.2.8 release archive, not a moving
default-branch snapshot.

| Field | Value |
|---|---|
| Repository | `https://github.com/cristiancmoises/zupt` |
| Release | `v5.2.8` |
| Tag commit | `ebb9ab3aa1d42c50030ca02883f6162dc4771fe1` |
| Source asset | `zupt-5.2.8.tar.gz` |
| SHA-256 | `378b9506211545b9594cf0d38ac8955d9b1cac34eb6b379ae0ec26b84edb65f7` |
| Local path | `zupt-5.2.8/` |
| Retrieved | 2026-09-01 |

The release's exact-tag CI run completed all 15 jobs successfully:
`https://github.com/cristiancmoises/zupt/actions/runs/33456209269`.

`zupt-5.2.8.SHA256SUMS` records all 201 regular files extracted from that
verified asset. `build-zupt.sh` validates every entry before invoking any
upstream build command, so a modified bundled source file fails closed.

Verify a freshly downloaded asset before replacing the bundled tree:

```bash
curl -fLO https://github.com/cristiancmoises/zupt/releases/download/v5.2.8/zupt-5.2.8.tar.gz
printf '%s  %s\n' \
  378b9506211545b9594cf0d38ac8955d9b1cac34eb6b379ae0ec26b84edb65f7 \
  zupt-5.2.8.tar.gz | sha256sum --check --strict
```

The release archive intentionally omits three export-only package recipes
found in the Git tag. That difference is upstream-defined. Do not fill the
missing paths from `master` or otherwise mix tagged and untagged sources.

ZUPT 5.2.8 carries the VaptVupt codec release 2.65.3. “VaptVupt” remains the
proper codec/API compatibility name in files such as `vaptvupt_api.c` and in
the `--vaptvupt` option; it is not the CLI or web-project name.

No `libvuptsdk` or `libpqvaptvupt` artifact is bundled. Both integrations are
disabled to retain upstream's auditable source-only boundary.
