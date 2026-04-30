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
| S2 | Stolen `~/.garminconnect/` tokens used to impersonate the user    | **fixable**    | We don't chmod the directory `garth` writes after `client.garth.dump(...)`. We do chmod `~/.mwgc/config.toml`; the same treatment applied here would close the gap. |
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
| I2 | OAuth tokens in `~/.garminconnect/` readable by other users          | **fixable**   | Same fix as S2. |
| I3 | Cloud-sync (OneDrive / Dropbox) roams `~/.mwgc/` to other devices    | **accepted**  | README warns; we can't enforce. |
| I4 | Email or password leaks into error messages or logs                  | **mostly OK** | We never `print()` the password. `AuthError(str(e))` could carry whatever Garmin's error message contains; in practice that's something like "Authentication failed", but worth a defensive audit / scrub of error message paths. |
| I5 | Process argv on a shared box leaks the input GPX path                | **OK**        | `--input` carries a path, no creds. |
| I6 | Memory of a crashed process contains the password                    | **out-of-scope** | OS-level concern; no clean Python-level mitigation. |
| I7 | Test fixtures or commits contain real credentials                    | **OK**        | Synthetic GPX fixture only; no real email or token strings in the git history. |

## D — Denial of service

| #  | Threat                                                                                  | Status      | Notes |
|----|-----------------------------------------------------------------------------------------|-------------|-------|
| D1 | Hostile GPX (huge file / billion laughs) hangs the parser                                | **fixable** | Same as T1. Add a max-file-size guard and/or `defusedxml`. |
| D2 | Network hangs on Garmin upload, GUI Run button stuck disabled                            | **mild**    | We don't set our own HTTP timeouts; we rely on `garth`'s defaults. The GUI's worker is a daemon thread, so closing the window kills it — escape hatch exists. |
| D3 | Hostile GPX with billions of trackpoints exhausts disk via huge FIT                      | **mild**    | No cap on point count; practically self-limiting (the parser would OOM first). A defensive sanity cap (~1M points) would harden this. |
| D4 | Retry loops hammer Garmin and trigger account rate-limit / lockout                       | **OK**      | Exactly one retry-on-`AuthError`, no other loops. |

## E — Elevation of privilege

| #  | Threat                                                                                                                | Status                          | Notes |
|----|-----------------------------------------------------------------------------------------------------------------------|---------------------------------|-------|
| E1 | Code injection via GPX content                                                                                         | **OK**                          | ElementTree doesn't eval; no `pickle`, no `eval`, no `exec` anywhere. |
| E2 | Code injection via `config.toml`                                                                                       | **OK**                          | `tomllib` is data-only. |
| E3 | Code injection via Garmin response                                                                                     | **OK**                          | We `dict.get(...)` and check types; no `eval`. |
| E4 | Path traversal in `--output` writes outside intended dir                                                                | **out-of-scope**                | The user picks the path; whatever they pick they had permission to write to. |
| E5 | **Supply-chain compromise of a transitive dep** (`garth`, `garminconnect`, `curl_cffi`, `fit-tool`, `customtkinter`, …) | **real, partially mitigated**   | We pin lower bounds (`>=`) but no exact versions or lockfile. A malicious update to `garth` (deprecated, still on PyPI) or `curl_cffi` could exfiltrate creds at the next `pip install`. A lockfile would meaningfully reduce this. |
| E6 | Bare `except Exception` in `uploader._get_client` masks a security-relevant failure                                     | **fixable**                     | The broad catch is intentional ("tokens are unusable, fall back to interactive login"), but it could also swallow something important. Tightening to `(FileNotFoundError, GarminConnectAuthenticationError, OSError, json.JSONDecodeError)` would be more defensive. |

## Top findings, ranked

These are the items worth acting on:

1. **🟡 Add a lockfile and pin direct dependencies to exact versions.**
   The largest open attack surface is the dependency tree (`garth`,
   `curl_cffi`, etc.). Reproducible installs cost almost nothing and
   shut down casual supply-chain attacks.
2. **🟡 Harden GPX parsing against XML DoS.** Add `defusedxml` (one
   dep, ~10 lines) and / or a file-size cap (one line). Closes the
   only real "untrusted input" path the tool has.
3. **🟢 chmod the `~/.garminconnect/` token directory after
   `garth.dump()`.** Mirrors what we already do for `config.toml`.
   ~3 lines in `uploader._interactive_login`.
4. **🟢 Tighten the `_get_client` `except` clause.** Catch a specific
   list of token-unusable exceptions rather than bare `Exception`.
5. **🟢 Audit error-message paths for credential leakage.**
   Specifically: does `GarminConnectAuthenticationError`'s `str(e)`
   ever contain the email or token? If so, redact before re-raising.

The rest are either explicit accepted trade-offs (plaintext password,
cloud sync) or assumptions of local trust on the user's own machine.

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

- Analyzed at git `51d1db4` ("Tasks 14-16: CustomTkinter GUI scaffold,
  mwgc-gui entry point, README").
- Date: 2026-04-30.
- Scope: `src/mwgc/**` and `pyproject.toml`. Specs and tests excluded.
