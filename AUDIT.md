# Release audit: ZUPT Web 5.2.8

This document records the release gate executed on 2026-09-01. It covers the
immutable upstream source, the Flask boundary, the container, and the live HTTP
service. A skipped or constrained check is listed explicitly rather than being
represented as a pass.

## Audited inputs

| Input | Audited value |
|---|---|
| ZUPT release | `v5.2.8` |
| Upstream tag commit | `ebb9ab3aa1d42c50030ca02883f6162dc4771fe1` |
| Official source-asset SHA-256 | `378b9506211545b9594cf0d38ac8955d9b1cac34eb6b379ae0ec26b84edb65f7` |
| Bundled manifest | 201 regular files, all hashes valid |
| Build profile | `WITH_SDK=0 WITH_PQBOX=0` |
| Web runtime | Python 3.12, Flask 3.1.3, Gunicorn 26.2.0 |
| Release image | `zupt-web:5.2.8` on Ubuntu 24.04 |

The upstream release asset, exact source inventory, and retrieval procedure are
recorded in [UPSTREAM.md](UPSTREAM.md). The exact-tag upstream CI run completed
15 of 15 jobs successfully. This downstream audit independently rebuilt and
tested the promoted source; the one result taken from that external run is
identified explicitly below.

## Results

### Upstream CLI

The source gate ran in a fresh Ubuntu 24.04 environment.

| Gate | Result |
|---|---|
| Manifest verification and exact 201-file inventory | Pass |
| Source-only scanner (including nested archives/binaries) | Pass: 0 opaque archives |
| Clean source-only build and `make check` | Pass |
| Regression suite | Pass: 22 passed, 0 failed |
| Multithreaded suite | Pass: 14 passed, 0 failed |
| Native post-quantum suite | Pass: 10 passed, 0 failed |
| Deduplication suite | Pass: 14 passed, 0 failed |
| Exact-size codec suite | Pass: 81 passed, 0 failed |
| In-tree SDK library suite | Pass: 15 passed, 0 failed |
| Test-vector suite | Pass: 16 passed, 0 failed |
| Installed-file contract | Pass |
| License audit | Pass |
| ASan/UBSan smoke | Pass |
| Format fuzz smoke | Pass: 1,000 iterations, 0 crashes |
| GCC strict warnings, conversions, and SHA-NI build | Pass |
| Cppcheck warning/performance and error checks | Pass |
| `tests/test_mlkem_fips203.sh` with OpenSSL 3.5 | Upstream exact-tag CI: pass, 3 of 3; local Ubuntu: skipped |

The installed-file test included version/help checks, byte-exact password and
recipient-key round trips, corruption rejection, extraction path confinement,
and an unprivileged execution check.

One Cppcheck *style* subcheck reported an upstream redundant-condition
diagnostic at `src/zupt_format.c:1246` (`knownConditionTrueFalse`): 11 of its 12
style assertions passed. The immutable promoted source was not patched to hide
the finding. Warning/performance and error-severity Cppcheck gates passed, as
did the compiler, sanitizer, fuzz, regression, and live archive matrices.

### Web application and dependencies

| Gate | Result |
|---|---|
| Unit and route suite | Pass: 14 of 14 |
| Python warnings promoted to errors | Pass |
| Python byte compilation | Pass |
| Bandit application scan | Pass: no findings |
| `pip-audit` against the hash-locked requirements | Pass: no known vulnerabilities |
| ShellCheck plus Bash/POSIX syntax checks | Pass |
| Compose model and canonical/legacy environment fallback | Pass |
| Read-only-container route suite | Pass |

The route tests cover CSRF enforcement, password preservation, private-key
handling, archive mode selection, unsafe option combinations, legacy archive
guidance, expiring downloads, CLI readiness, and safe filenames. Passwords are
sent to ZUPT through `--pass-fd 0`, not process arguments.

### Final image and live service

The release image was rebuilt after the final templates, licensing text, and
documentation changes. It then ran with a read-only root filesystem, uid 1001,
all capabilities dropped, `no-new-privileges`, a 256-process limit, and a 2 GiB
work tmpfs.

| Gate | Result |
|---|---|
| Runtime ZUPT version | Pass: 5.2.8 |
| Live HTTP/crypto workflow | Pass: 133 assertions |
| Plain LZHP level-1 round trip | Pass, byte exact |
| Password/store level-5 round trip | Pass, byte exact |
| Hybrid VaptVupt level-9 round trip | Pass, byte exact |
| Full-PQ auto level-5 round trip | Pass, byte exact |
| Inspect, verify, and extract routes | Pass |
| Health/readiness, CSRF, headers, UI, and key generation | Pass |
| Solid + dedup invalid combination | Pass: rejected |
| One-shot job lifecycle | Pass: streamed jobs removed after response close |
| Final-image inventory | Pass: no pip or compiler; required licenses present |

The four credential-mode workflows completed against the production Gunicorn
service. After responses closed, only the two deliberately retained key-pair
jobs remained in the tmpfs; all compression, inspection, verification, and
extraction jobs had been removed.

## Environmental constraints and intentional skips

- The constant-time timing probe was inconclusive on the shared audit host due
  to scheduler contention. It is not reported as a pass or a failure; the
  functional authentication and corruption gates passed.
- Loop-device testing could not run because the audit container had no loop
  device. Path-confinement and installed-file disk-mode checks did run.
- Ubuntu 24.04 supplies OpenSSL 3.0, so its local ML-KEM interoperability probe
  skipped. The same exact ZUPT release separately passed all three probes
  against OpenSSL 3.5.
- External SDK/PQBOX integration checks are intentionally inapplicable to the
  selected source-only profile. Native `--pq`, native `--pq-only`, and the
  rebuildable in-tree SDK library tests ran successfully.
- Docker reported that the audit host kernel does not support swap accounting.
  The configured memory limit still applies, but a distinct swap limit could
  not be demonstrated on that host.

## Reproduction commands

The commands below cover the portable release gates. The timing, loop-device,
and OpenSSL 3.5 qualifications remain as stated above because their results
depend on host capabilities.

```bash
# Verify and build the immutable source-only CLI.
./build-zupt.sh

# Run the extended CLI, license, sanitizer, fuzz, installed-contract, and
# static-analysis gates (the recorded Cppcheck style diagnostic is expected).
cd zupt-5.2.8
make WITH_SDK=0 WITH_PQBOX=0 test-all
make sdk-test
make audit-licenses
make WITH_SDK=0 WITH_PQBOX=0 test-asan-run
make WITH_SDK=0 WITH_PQBOX=0 fuzz-format-run
bash scripts/test-installed-zupt.sh ./zupt
bash tests/test_static_analysis.sh
cd ..

# Run the web unit/route gate in a hash-locked environment.
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
PYTHONWARNINGS=error .venv/bin/python -m unittest discover -s tests -v
python3 -m py_compile app.py tests/test_app.py tests/live_smoke.py
bandit -q -r app.py
pip-audit -r requirements.txt
shellcheck setup.sh build-zupt.sh
bash -n setup.sh
sh -n build-zupt.sh
docker compose config --quiet

# Build and run the production-boundary smoke matrix.
docker build --tag zupt-web:5.2.8 .
docker run --detach --name zupt-web-audit \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --pids-limit 256 \
  --tmpfs /tmp/zupt-work:size=2G,mode=700,uid=1001,gid=1001 \
  --publish 127.0.0.1:8282:8080 zupt-web:5.2.8
ZUPT_WEB_URL=http://127.0.0.1:8282 python3 tests/live_smoke.py
docker rm --force zupt-web-audit
```

The CI definition in `.github/workflows/ci.yml` repeats the portable release
subset on every push and pull request. The host-specific evidence above remains
a recorded release audit rather than a portability claim.
