# STRIDE threat analysis — mwgc

A point-in-time security review of `mwgc` (CLI + GUI + supporting modules)
using Microsoft's STRIDE framework: **S**poofing, **T**ampering,
**R**epudiation, **I**nformation disclosure, **D**enial of service,
**E**levation of privilege.

This is a static, code-review-level threat model. No penetration testing,
no third-party-library CVE audit. The threat model assumes a
**single-user desktop tool** running under your own user account on
your own machine.

## System and trust boundaries

```
+------------------+   creds + GPX   +-------------+   FIT bytes   +----------------+
|   You (user)     | --------------> |   mwgc      | ------------> | Garmin Connect |
|  (CLI / GUI)     |                 |   (local)   |   over HTTPS  |  (3rd-party)   |
+------------------+                 +------+------+               +----------------+
                                            |
                          +-----------------+-----------------+
                          | local filesystem (your home dir)  |
                          | ~/.mwgc/config.toml   (plaintext) |
                          | ~/.garminconnect/     (OAuth)     |
                          | <ride>.fit            (output)    |
                          +-----------------------------------+
```

Anyone with code-execution-as-you on this machine is implicitly trusted.
The interesting threats are: **untrusted input data** (a GPX file from
elsewhere), the **network path** to Garmin, and **third-party libraries**
that run inside our process.

In each table below, **status** is one of:

- **OK** — mitigated to a level appropriate for the threat model
- **accepted** — known trade-off the user has explicitly opted into
- **fixable** — real concern, low cost to address
- **out-of-scope** — relies on the local-trust assumption

## S — Spoofing

| #  | Threat                                                            | Status         | Notes |
|----|-------------------------------------------------------------------|----------------|-------|
| S1 | MITM impersonates Garmin Connect, captures creds/tokens           | **OK**         | `garth` / `curl_cffi` do TLS verification with the OS root store; we never pass `verify=False`. |
| S2 | Stolen `~/.garminconnect/` tokens used to impersonate the user    | **OK**         | Token persistence now happens via `client.login(tokenstore)` (garminconnect's built-in path); the dead `client.garth.dump()` call was removed. Directory permissions rely on the OS default for `Path.mkdir()`; on a shared host, a chmod-700 hardening would still be a defensive improvement but is out of scope for single-user desktop use. |
| S3 | Hostile process on the box runs `mwgc` claiming to be the user    | **out-of-scope** | Local trust. |

## T — Tampering

| #  | Threat                                                                              | Status                | Notes |
|----|-------------------------------------------------------------------------------------|-----------------------|-------|
| T1 | Malicious GPX with XML billion-laughs / XXE                                          | **fixable**           | `gpxpy` uses stdlib `xml.etree.ElementTree`. Modern CPython disables external-entity loading by default (XXE largely closed), but **entity-expansion DoS is still possible**. Not a code-exec, just memory/CPU pressure. Trivial to harden by parsing through `defusedxml` first or capping the input file size. |
| T2 | GPX with out-of-range fields (HR=10⁹, etc.) corrupts the FIT                          | **OK**                | `fit-tool` validates uint16/uint32 ranges on encode and raises; we catch as `FitBuildError`, delete the partial file, exit code 3. |
| T3 | Local attacker rewrites `~/.mwgc/config.toml` to redirect uploads                    | **out-of-scope**      | Local trust. |
| T4 | Server-side tamper with the upload response (false success or false duplicate)        | **OK**                | TLS protects the response in flight. We trust Garmin Connect on the other side. |

## R — Repudiation

For a single-user personal tool, repudiation barely applies. Worth
noting:

- We don't keep a persistent upload log; the only record is in Garmin
  Connect itself.
- Stack traces and `error: …` go to stderr but aren't persisted to a
  file.

If this ever turned into a multi-user thing, an append-only
`~/.mwgc/uploads.log` would be the obvious add. **Not a real risk
in the current threat model.**

## I — Information disclosure

| #  | Threat                                                              | Status        | Notes |
|----|---------------------------------------------------------------------|---------------|-------|
| I1 | Plaintext password in `~/.mwgc/config.toml`                          | **accepted**  | The user explicitly opted into this. chmod 600 on POSIX, README warns. The keyring upgrade path is in the v1.1 backlog. |
| I2 | OAuth tokens in `~/.garminconnect/` readable by other users          | **OK**        | Same resolution as S2. |
| I3 | Cloud-sync (OneDrive / Dropbox) roams `~/.mwgc/` to other devices    | **accepted**  | README warns; we can't enforce. |
| I4 | Email or password leaks into error messages or logs                  | **mostly OK** | We never `print()` the password. `AuthError(str(e))` could carry whatever Garmin's error message contains; in practice that's something like "Authentication failed", but worth a defensive audit / scrub of error message paths. |
| I5 | Process argv on a shared box leaks the input GPX path                | **OK**        | `--input` carries a path, no creds. |
| I6 | Memory of a crashed process contains the password                    | **out-of-scope** | OS-level concern; no clean Python-level mitigation. |
| I7 | Test fixtures or commits contain real credentials                    | **OK**        | Synthetic GPX fixture only; no real email or token strings in the git history. |

## D — Denial of service

| #  | Threat                                                                                  | Status      | Notes |
|----|-----------------------------------------------------------------------------------------|-------------|-------|
| D1 | Hostile GPX (huge file / billion laughs) hangs the parser                                | **fixable** | Same as T1. Add a max-file-size guard and/or `defusedxml`. |
| D2 | Network hangs on Garmin upload, GUI Run button stuck disabled                            | **OK**      | The uploader now wraps `client.upload_activity` in a `concurrent.futures` future with a hard timeout (default 60 s, override via `MWGC_UPLOAD_TIMEOUT_S`). On timeout it raises `UploadError("upload timed out")` and the GUI re-enables Run. |
| D3 | Hostile GPX with billions of trackpoints exhausts disk via huge FIT                      | **mild**    | No cap on point count; practically self-limiting (the parser would OOM first). A defensive sanity cap (~1M points) would harden this. |
| D4 | Retry loops hammer Garmin and trigger account rate-limit / lockout                       | **OK**      | Exactly one retry-on-`AuthError`, no other loops. |

## E — Elevation of privilege

| #  | Threat                                                                                                                | Status                          | Notes |
|----|-----------------------------------------------------------------------------------------------------------------------|---------------------------------|-------|
| E1 | Code injection via GPX content                                                                                         | **OK**                          | ElementTree doesn't eval; no `pickle`, no `eval`, no `exec` anywhere. |
| E2 | Code injection via `config.toml`                                                                                       | **OK**                          | `tomllib` is data-only. |
| E3 | Code injection via Garmin response                                                                                     | **OK**                          | We `dict.get(...)` and check types; no `eval`. |
| E4 | Path traversal in `--output` writes outside intended dir                                                                | **out-of-scope**                | The user picks the path; whatever they pick they had permission to write to. |
| E5 | **Supply-chain compromise of a transitive dep** (`garth`, `garminconnect`, `curl_cffi`, `fit-tool`, `customtkinter`, …) | **mostly OK**                   | We now ship a hash-pinned `requirements.lock` covering every direct and transitive dep (33 packages). Reproducible installs (`pip install -r requirements.lock`) refuse to install a package whose hash doesn't match. Direct deps in `pyproject.toml` are bounded with both lower and next-major upper bounds. **Residual risk:** the lockfile pins versions, not vendor identity — if PyPI itself were compromised at the time of the next `pip-compile --upgrade`, a malicious version could be locked. We also haven't audited the pinned versions for known CVEs. |
| E6 | Bare `except Exception` in `uploader._get_client` masks a security-relevant failure                                     | **fixable**                     | The broad catch is intentional ("tokens are unusable, fall back to interactive login"), but it could also swallow something important. Tightening to `(FileNotFoundError, GarminConnectAuthenticationError, OSError, json.JSONDecodeError)` would be more defensive. |

## Top findings, ranked

### Open

1. **🟡 Harden GPX parsing against XML DoS.** Add `defusedxml`
   (one dep, ~10 lines) and / or a file-size cap (one line). Closes
   the only real "untrusted input" path the tool has.
2. ~~chmod the `~/.garminconnect/` token directory after `garth.dump()`.~~
   **Done** — `garth.dump()` was already dead code (removed in the
   2026-04-30 QA pass). Token persistence now happens through
   `client.login(tokenstore)`, which is garminconnect's own path. See S2.
3. **🟢 Tighten the `_get_client` `except` clause.** Catch a specific
   list of token-unusable exceptions rather than bare `Exception`.
4. **🟢 Audit error-message paths for credential leakage.**
   Specifically: does `GarminConnectAuthenticationError`'s `str(e)`
   ever contain the email or token? If so, redact before re-raising.

The rest are either explicit accepted trade-offs (plaintext password,
cloud sync) or assumptions of local trust on the user's own machine.

### Done

- ✅ **Lockfile + tight upper bounds (originally finding #1).** A
  hash-pinned `requirements.lock` is committed; direct deps in
  `pyproject.toml` carry next-major upper bounds. See E5 above for
  residual risk and the `## Reproducible install` section of the
  root README for usage.
- ✅ **Token persistence fixed (originally finding #2 / S2, I2).**
  `client.garth.dump()` was dead code (the `.garth` attribute was
  removed in garminconnect ≥ 0.3); the call was being silently
  suppressed, leaving `~/.garminconnect/` permanently empty and
  forcing re-authentication on every run. Fixed by passing `tokenstore`
  to `client.login()`, which is garminconnect's own persistence path.
  Discovered and fixed during the 2026-04-30 real-file QA pass.

## When to redo this analysis

Re-run STRIDE when any of the following lands:

- New external input source (e.g. a folder watcher, a web-based UI, a
  cloud upload destination other than Garmin).
- Network listener / server mode.
- Plugin or scripting hook that loads user code.
- Multi-user or shared-host deployment scenario.
- Any new dependency that handles credentials, network I/O, or XML.
- A switch from `python-garminconnect` to a different upload library
  (the auth flow's threat surface lives there).

## Reference

- **Original analysis:** git `51d1db4`, 2026-04-30. Scope:
  `src/mwgc/**` and `pyproject.toml`. Specs and tests excluded.
- **Mitigations landed since the original analysis** are tracked in
  the **Done** subsection above. Update entries there when you act
  on findings; flip the relevant table row's status at the same
  time.
- Re-run a full analysis when triggers in the next section fire.
