# ZUPT Web 5.2.9 candidate audit

This document records evidence gathered for the 5.2.9 candidate on 2026-09-06.
It deliberately separates the published ZUPT upstream release, focused local
checks of this downstream working tree, and checks that still require the final
container or deployment. Results from ZUPT Web 5.2.8 do not transfer to this
candidate.

Current status: source provenance and the focused application/static checks
below pass. The final image, live HTTP workflow, and production deployment are
not release evidence until they are run against the final committed tree.

## Audited inputs

| Input | Audited value |
|---|---|
| ZUPT release | `v5.2.9` |
| Upstream tag commit | `63f27dd0c5afcf155f813a069c29f6384d46790c` |
| Official source asset | `zupt-5.2.9.tar.gz`, 817395 bytes |
| Official source-asset SHA-256 | `24e1e3251c0bbcab049d3a7c3f1451e1b824fbb95ef454ca7c03077c8a470171` |
| Bundled manifest | 203 regular files |
| Build profile | `WITH_SDK=0 WITH_PQBOX=0` |
| Locked web runtime | Python 3.12, Flask 3.1.3, Gunicorn 26.2.0 |
| Candidate base | ZUPT Web `fbfe4c85487080fb0b992f6b3d7d8395e0ed10df` |
| Intended image name | `zupt-web:5.2.9` |

The source inventory and retrieval procedure are recorded in
[UPSTREAM.md](UPSTREAM.md).

## Verified upstream evidence

GitHub Actions run
[`34048047543`](https://github.com/cristiancmoises/zupt/actions/runs/34048047543)
completed successfully at the exact `v5.2.9` tag commit. The GitHub API reported
15 completed jobs and 15 successful conclusions, including GCC and Clang builds,
strict warnings, sanitizers, source reproducibility, analyzers, Linux packages,
and native Windows and macOS package gates.

The published non-draft, non-prerelease
[`v5.2.9` release](https://github.com/cristiancmoises/zupt/releases/tag/v5.2.9)
reports the source asset size and SHA-256 shown above. These are upstream ZUPT
results. They do not by themselves validate this Flask application, its image,
or its deployment.

## Focused local evidence

These checks ran from the current downstream working tree on 2026-09-06 in the
America/Sao_Paulo timezone.

| Gate | Result |
|---|---|
| Published source-asset SHA-256 and size | PASS |
| Manifest names versus archive members | PASS: exact match |
| Manifest hashes versus archive and bundled tree | PASS: 203 of 203 |
| Source-only scanner | PASS: 203 files, 0 archives (`file` 5.46) |
| Stale release-reference scan outside upstream history | PASS: only intentional historical 5.2.8 comparisons remain |
| Hash-locked dependency installation | PASS |
| Unit and route suite with warnings promoted to errors | PASS: 16 of 16 |
| Proxy-TLS secure-cookie regression | PASS |
| Private-workdir ownership, mode, and symlink regression | PASS |
| Invalid `ZUPT_COOKIE_SECURE` startup rejection | PASS |
| Python byte compilation | PASS |
| ShellCheck and Bash/POSIX syntax checks | PASS |
| Compose model validation | PASS |
| Bandit 1.8.6 application scan | PASS: no findings |
| `pip-audit` 2.10.1 with hash enforcement | PASS: no known vulnerabilities |
| Clean Ubuntu 24.04 ZUPT build and `make check` | PASS on an unmodified second run; timing qualification below |
| Final multi-stage Docker build | PASS: Docker 20.10.27 |
| Final-image inventory | PASS: uid 1001; no pip, compiler, or make; required license payload present; no binary RPATH/RUNPATH |
| Hardened read-only container controls | PASS: all capabilities dropped, `no-new-privileges`, 256-PID and 4-GiB limits, mode-0700 tmpfs |
| Live HTTP and cryptographic workflow | PASS: 7 stages, 133 assertions, four credential-mode round trips |
| `git diff --check` | PASS |

The route suite covers CSRF enforcement, byte-accurate passwords, inherited
password input rather than password argv, mutually exclusive credentials,
archive mode selection, legacy archive guidance, expiring downloads, readiness,
safe filenames, and rejection of shared or symlinked work directories. The new
proxy-TLS regression requires the CSRF cookie to be `Secure` when
`ZUPT_COOKIE_SECURE=1`. The HTTPS live smoke test independently rejects a public
HTTPS service that omits that cookie attribute.

The manifest comparison extracted every regular member from the known source
asset and compared its digest with both `zupt-5.2.9.SHA256SUMS` and the bundled
tree. It did not infer provenance merely from a matching directory name.

The first uncached container build stopped in upstream
`test_password_prompt_signal.sh`: the test observed the prompt before it
observed terminal echo being disabled. No source or test was changed; the same
immutable build passed on the next run. Repeating that exact PTY test 100 times
against the resulting binary produced 99 passes and one identical failure.
This is recorded as a timing-sensitive upstream test concern, not hidden as an
all-pass result. The web application does not invoke the interactive prompt;
it supplies passwords through inherited standard input and `--pass-fd 0`.

The live matrix exercised LZHP/plain at level 1, Store/password at level 5,
VaptVupt/hybrid at level 9, and Auto/PQ-only at level 5. Each workflow covered
compression, metadata inspection, verification, extraction, and byte-exact
recovery through the production Gunicorn boundary. The candidate container was
then stopped and removed.

## Not yet run for this candidate

| Gate | Status |
|---|---|
| Local extended ZUPT, SDK, sanitizer, fuzz, and static-analysis suites | NOT RUN; upstream exact-tag coverage is recorded separately |
| Public HTTPS 5.2.9 smoke test | NOT RUN |
| Production deployment and rollback test | NOT RUN |

Do not convert these entries to PASS based on the 5.2.8 audit or on upstream
ZUPT CI. Record the exact final commit, commands, environment, and result when a
gate is executed.

## Security and environment notes

- The default Compose bind remains `127.0.0.1`. Remote publication requires a
  separately managed TLS boundary.
- TLS normally terminates before the Flask container. The application therefore
  does not trust forwarded scheme headers automatically. Set
  `ZUPT_COOKIE_SECURE=1` when browsers reach the service exclusively through
  HTTPS; values other than `0` or `1` fail startup.
- Local HTTP development retains `ZUPT_COOKIE_SECURE=0`, because a browser will
  not return a Secure cookie over plain HTTP.
- The system Python did not contain Flask. The unit suite ran in a temporary
  virtual environment populated with `pip --require-hashes -r requirements.txt`.
- The base shell did not contain `file`; the source scanner ran through
  `guix shell file` with file 5.46.
- The default job path is per-uid. Startup rejects a symlink, foreign owner, or
  group/other permissions; the supported Compose deployment replaces that path
  with a uid-1001, mode-0700 tmpfs.
- No existing local or production service was replaced during the local
  container review. The exact temporary test container was removed afterward.

The selected source-only profile intentionally excludes external SDK/PQBOX
integrations. Native password, `--pq`, and `--pq-only` paths remain in scope.

## Reproduction commands

```bash
# Verify the immutable source and build the source-only CLI.
sha256sum --check --strict zupt-5.2.9.SHA256SUMS
(cd zupt-5.2.9 && bash scripts/check-source-only.sh --tree .)
./build-zupt.sh

# Extended upstream checks applicable to the embedded release archive.
cd zupt-5.2.9
make WITH_SDK=0 WITH_PQBOX=0 test-all
make sdk-test
make audit-licenses
make WITH_SDK=0 WITH_PQBOX=0 test-asan-run
make WITH_SDK=0 WITH_PQBOX=0 fuzz-format-run
bash scripts/test-installed-zupt.sh ./zupt
bash tests/test_static_analysis.sh
cd ..

# Hash-locked web checks.
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
PYTHONWARNINGS=error .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/live_smoke.py
shellcheck setup.sh build-zupt.sh
bash -n setup.sh
sh -n build-zupt.sh
docker compose config --quiet

# Optional dependency-vulnerability and application scans.
bandit -q -r app.py
pip-audit -r requirements.txt

# Pre-deployment container gate over loopback HTTP.
docker build --tag zupt-web:5.2.9 .
docker run --detach --name zupt-web-audit \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --pids-limit 256 \
  --tmpfs /tmp/zupt-work:size=2G,mode=700,uid=1001,gid=1001 \
  --publish 127.0.0.1:8282:8080 zupt-web:5.2.9
python3 tests/live_smoke.py --base-url http://127.0.0.1:8282
docker rm --force zupt-web-audit

# After an HTTPS reverse-proxy deployment with ZUPT_COOKIE_SECURE=1.
python3 tests/live_smoke.py \
  --base-url https://zupt-web.securityops.co \
  --expected-version 5.2.9
```

The CI definition repeats the portable source, application, image, and live
container subset on pushes and pull requests. Hosted CI must still complete on
the final commit; a local working-tree result is not a substitute.
