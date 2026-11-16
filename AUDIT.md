# ZUPT Web validation

This document defines the checks for ZUPT Web 5.2.13. It is not an independent
security audit or a claim that an untested deployment is ready. Source identity,
web tests, image tests, and public HTTPS checks have separate scopes.

## Inputs

| Input | Value |
|---|---|
| Web release | 5.2.13 |
| Bundled CLI / codec / format | ZUPT 5.2.10 / VaptVupt 2.65.13 / v1.6 |
| Runtime source commit | `0165fbd78faf78046d49e004622820ef79061f17` |
| Source inventory | 294 regular files; bytes match the source asset; executable modes restored separately from the pinned Git commit |
| Build profile | `WITH_SDK=0 WITH_PQBOX=0` |
| Locked web runtime | Python 3.12, Flask 3.1.3, Gunicorn 26.2.0 |
| Image | `zupt-web:5.2.13`; revision label records the web commit |

[UPSTREAM.md](UPSTREAM.md) records the published source asset, signed checksums,
trusted fingerprint, and relative manifest. The upstream release validates the
core within its recorded scope; its results do not substitute for the web gates.

## Gate matrix

| Boundary | Command or check | Acceptance |
|---|---|---|
| Bundled source | `./build-zupt.sh --verify-only` | All 294 hashes and exact file set; no symlink, special file, or compiled payload |
| Source gate regressions | `python3 -m unittest discover -s tests -p test_build_zupt.py -v` | Exact source accepted without Make; changed, extra, and symlinked files rejected |
| Web routes | `python3 -m unittest discover -s tests -v` | CSRF, passwords over inherited FD, exclusive credentials, cleanup, key expiry, readiness, private work directory |
| Python/shell | `python3 -m py_compile app.py tests/test_app.py tests/test_build_zupt.py tests/live_smoke.py`; `shellcheck setup.sh build-zupt.sh` | No syntax or shell diagnostics |
| Compose | `docker compose config --quiet` | Valid supported model |
| CLI build | `./build-zupt.sh` | Manifest verification, `make check`, stripped binary, no RPATH/RUNPATH |
| Extended CLI | `make WITH_SDK=0 WITH_PQBOX=0 test-all`; `make sdk-test`; `make audit-licenses` | Successful applicable upstream tests and license markers |
| Sanitizer smoke | `make WITH_SDK=0 WITH_PQBOX=0 test-asan-run` | Real instrumented CLI round trips; not a claim that every product path is sanitizer-covered |
| Installed contract | `bash scripts/test-installed-zupt.sh ./zupt` | Staged installed-file CLI checks |
| Final image | Version, uid 1001, revision/core labels, licenses, no pip/compiler/make | All application, template, static, and license files readable by uid 1001 |
| Live container | `python3 tests/live_smoke.py` | HTTP/security headers, CSRF, hybrid/PQ-only key generation, four credential-mode round trips and exact recovered bytes |
| Image export | CI artifact after all preceding jobs and live checks | Docker image archive, verified SHA256SUMS, COMMIT, image metadata |
| Public HTTPS | Live smoke with `--base-url`, `--expected-version 5.2.13`, and `--expected-cli-version 5.2.10` | Real HTTPS and Secure CSRF cookie; separate from loopback CI |

The image job reproduces source-package extraction permissions in a temporary
context containing every tracked file, including export-ignored vendor recipes.
It sets files to 0600 and directories to 0700, restores only the three documented
entry points, then builds and tests that image. The inventory checks public
runtime files as uid 1001 before the live smoke and image export gates.

The manifest verifier retains the two declared LF/CRLF checkout variants and
rejects all other transformations. The existing historical tests read each
immutable Web tag with its own manifest. Gitless source exports report those
two integration checks as skipped; hosted CI fetches history and must execute them.

The live matrix covers these combinations:

| Credential | Codec | Level |
|---|---|---:|
| None | LZHP | 1 |
| Password | Store | 5 |
| Hybrid | VaptVupt | 9 |
| PQ-only | Auto | 5 |

Each covers compression, inspection, verification, extraction, and byte-exact
recovery through Gunicorn.
The container gate retains read-only root, dropped capabilities,
`no-new-privileges`, a 4 GiB memory cap, a 256-PID cap, and private 2 GiB tmpfs.

CI runs the portable matrix on `main`, `5.2.13`, pull requests, and manual
dispatch. The image export step has no unconditional/failure override; it is
reached only after successful image and live checks. Record the exact web
commit and artifact digest when using a result. A successful older revision
must not be relabeled as a new execution.

## Reproduce

```sh
./build-zupt.sh --verify-only
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
PYTHONWARNINGS=error .venv/bin/python -m unittest discover -s tests -v
shellcheck setup.sh build-zupt.sh
bash -n setup.sh
sh -n build-zupt.sh
docker compose config --quiet

# Builds and tests the immutable bundled CLI.
./build-zupt.sh
(cd zupt-5.2.10 &&
  make WITH_SDK=0 WITH_PQBOX=0 test-all &&
  make sdk-test && make audit-licenses &&
  make WITH_SDK=0 WITH_PQBOX=0 test-asan-run &&
  bash scripts/test-installed-zupt.sh ./zupt)

# Build the web image with an explicit source-revision label.
VCS_REF=$(git rev-parse HEAD) docker compose build
docker compose up -d
python3 tests/live_smoke.py --base-url http://127.0.0.1:8181   --expected-version 5.2.10
docker compose down
```

Release-only upstream targets such as `release-check` additionally require the
upstream Git checkout, packaging tools, GUI dependencies, and formal toolchain.
They are not replaced by the embedded-source matrix above. Formal proofs cover
their modeled definitions and assumptions, not the whole Flask service.

For an HTTPS deployment, enable `ZUPT_COOKIE_SECURE=1`, then run the live smoke
against its actual public URL. Do not treat loopback, an exported image, or
upstream formal results as production HTTPS validation.

## Historical evidence and limitations

| Revision / scope | Recorded result | Limit |
|---|---|---|
| Web 5.2.9 CI [34077193840](https://github.com/cristiancmoises/zupt-web/actions/runs/34077193840) | Web, bundled CLI, and image jobs succeeded | Historical; not a 5.2.13 run |
| Web 5.2.9 initial uncached build | Password PTY timing test failed; unchanged retry passed; 99/100 focused repeats passed | Timing-sensitive failure retained; Web uses `--pass-fd 0`, not the interactive prompt |
| Web 5.2.10 historical tag | Rejected by its checkout-EOL manifest mismatch | Immutable failure retained; no retagging |
| Web 5.2.11 / 5.2.12 source gates | Declared LF/CRLF verifier and historical-manifest regressions | Retained in 5.2.13; older results are not a new execution |
| ZUPT 5.2.10 core | [Official release](https://github.com/cristiancmoises/zupt/releases/tag/v5.2.10) with signed source/checksum records | Core evidence only; retain its explicit skips and formal assumptions |
| Web 5.2.13 | Require results from the exact web commit and resulting image | No inherited CI, HTTPS, deployment, or rollback PASS |

External opaque SDK/PQBOX integrations are excluded. No test here establishes
compatibility with their retired archives; follow [MIGRATION.md](MIGRATION.md).
Dependency pins and hashes make installation explicit, but do not guarantee
permanent vulnerability freedom. Review dependency advisories separately.
