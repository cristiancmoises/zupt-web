# Migrating from VaptVupt Web 5.2.1 to ZUPT Web 5.2.8

The product and canonical command are again named ZUPT/`zupt`. Archive format
v1.6 and the `.zupt` extension remain unchanged, but one old optional crypto
integration needs deliberate recovery before upgrade.

## Compatibility matrix

| Archive created by 5.2.1 | ZUPT Web 5.2.8 |
|---|---|
| Unencrypted | Supported |
| Native hybrid `--pq` | Supported |
| Native full-PQ `--pq-only` | Supported |
| Argon2id password mode | Recover with 5.2.1, then migrate |
| SDK v2 `--pq-sdk` | Recover with 5.2.1, then migrate |

The unsupported paths depended on a frozen library whose production API is
not completely rebuildable from published source and whose ML-KEM behavior is
not the current FIPS 203 implementation. It is intentionally absent from the
new image.

## Safe migration procedure

1. Back up every archive and key before testing. Never use the only copy.
2. Keep the `v5.2.1` Git tag or its already-built image available only as a
   temporary, local compatibility reader.
3. Use that reader to extract each Argon2id or SDK-v2 archive into isolated
   storage.
4. Compare the restored files to known hashes or the original dataset where
   possible.
5. Create a fresh archive with ZUPT Web 5.2.8. Native hybrid `--pq` is the
   recommended recipient-key mode; `--pq-only` is available when a classical
   X25519 layer is not desired.
6. Verify the new archive and perform a test restore before retiring the old
   recovery environment.

To build the old reader without altering the current checkout:

```bash
git worktree add ../zupt-web-5.2.1 v5.2.1
docker build -t zupt-web-compat:5.2.1 ../zupt-web-5.2.1
```

Run the compatibility container only on a trusted host and avoid exposing it
to a network. The old tag contains the dependency that this release removed.

If the 5.2.1 Compose service is still running, download any ephemeral keys you
still need before stopping it: its work directory is a tmpfs and disappears
with the container. You can test 5.2.8 alongside it first with
`PORT_HOST=8282 ./setup.sh`. Once migration is verified, stop the old project
explicitly from its own checkout with `docker compose down`; the new setup
script does not remove another Compose project for you.

## Other upstream hardening changes

- Pre-AIT historical archives now fail closed by default. The CLI-only
  `--allow-legacy-no-ait` option is a recovery override for a known, trusted
  archive, not a normal operating mode.
- Key parsing is stricter; malformed or noncanonical key files previously
  tolerated may now be rejected.
- Writers in 5.2.2 and later add authenticated, flag-gated dedup/disk records
  that older readers are not claimed to understand.
- `ZUPT_*` environment variables are canonical. `VAPTVUPT_*` values remain
  accepted as fallbacks so existing deployment configuration is not lost.
