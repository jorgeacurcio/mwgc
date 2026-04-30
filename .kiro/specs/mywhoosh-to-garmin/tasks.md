# Implementation Plan

Tasks are ordered for incremental delivery. Each is independently
testable and references the requirements it satisfies. Do them top to
bottom; mark a box only when its acceptance criteria pass.

- [x] 1. **Project skeleton and tooling** _(R5, R6)_
  - Create `pyproject.toml` with Python 3.11+, `mwgc` package, console
    entry point `mwgc = mwgc.cli:main`.
  - Add dev deps: `pytest`, `pytest-cov`, `ruff`.
  - Add `src/mwgc/__init__.py`, empty module stubs for the layout in
    design.md.
  - Add `.gitignore` (`.venv`, `__pycache__`, `dist`, `*.fit`, token cache dir).

- [x] 2. **Data models** _(R1, R2)_
  - Implement `mwgc.models` with `TrackPoint`, `DeviceProfile`,
    `ConversionResult` exactly as in design.md.
  - Add `mwgc.errors` with the custom exception hierarchy.

- [x] 3. **Device profile** _(R2)_
  - Implement `mwgc.devices.FENIX_5_PLUS` with manufacturer=`garmin`,
    product=`fenix5_plus`, product_id=3110, stable placeholder serial,
    software_version=19.30.

- [x] 4. **GPX parser** _(R1.1, R1.2, R1.3, R1.4, R3.4, R7.1, R7.2)_
  - Implement `mwgc.gpx_parser.parse_gpx(path) -> tuple[list[TrackPoint], datetime]`.
  - Walk extensions namespace-aware; handle missing HR/cadence/power
    gracefully (None, not error).
  - Compute cumulative distance via haversine; fall back to `speed * dt`
    when GPS missing.
  - Raise `GpxParseError` on malformed XML or zero trackpoints.
  - Tests: at least one real MyWhoosh export saved as
    `tests/fixtures/sample_mywhoosh.gpx`.

- [x] 5. **FIT SDK spike + builder** _(R1.1, R1.5, R2, R3.1, R3.2, R3.3, R7.3)_
  - 30-min spike: encode a 5-record activity with `garmin-fit-sdk` and
    `fit-tool`; pick the one whose API is cleaner. Record the choice in
    a one-line comment at the top of `fit_builder.py`.
  - Implement `build_fit(points, profile, out_path, on_progress=None)`:
    emit message order from design.md table.
  - Compute aggregates in one pass.
  - Sport=cycling, sub_sport=virtual_activity.
  - On exception, delete the partial output file before re-raising.
  - Tests: build → decode → assert file_id, device_info, session totals,
    record count.

- [x] 6. **Core orchestration** _(R6.1, R6.2, R6.3)_
  - Implement `mwgc.core.convert(...)`, `mwgc.core.upload(...)`,
    `mwgc.core.run(...)` per design.md.
  - `on_progress` callback contract: `Callable[[str, float], None]`.
  - No stdout/stderr writes from `core` or below.

- [x] 7. **Uploader (mocked first)** _(R4.1, R4.5, R4.6)_
  - Implement `mwgc.uploader.upload(fit_path) -> UploadOutcome` using
    `python-garminconnect` (`Garmin.upload_activity`).
  - Outcomes: `UPLOADED`, `DUPLICATE`, raise `UploadError` otherwise.
  - Tests: fake `Garmin` client covering happy path, duplicate
    response, and generic failure.

- [x] 8. **Auth flow with token cache and retry** _(R4.2, R4.3, R4.4)_
  - On startup, attempt `Garmin.resume(token_dir)`; on failure, run
    interactive `Garmin(email, password).login()` including the MFA
    prompt, then persist tokens via `client.garth.dump(token_dir)`.
  - On `AuthError` during upload, re-login once and retry.
  - Tests: mock the `Garmin` client to fail-then-succeed; assert one
    retry only.

- [x] 9. **CLI entrypoint** _(R5.1–R5.5, R7.1, R7.2)_
  - `argparse` with `--input`, `--output`, `--no-upload`.
  - Bind `on_progress` to a tidy stdout printer.
  - Exit codes per design.md table.
  - Smoke test: invoke as module against the fixture with `--no-upload`,
    assert `.fit` written and exit code 0.

- [x] 10. **End-to-end manual test** _(all)_
  - Run against a real MyWhoosh GPX with upload enabled.
  - Verify the activity appears on Garmin Connect with: correct device
    (Fenix 5 Plus), sport=cycling, totals match the source file, HR /
    cadence / power graphs present.
  - Capture the resulting Garmin Connect activity URL in a manual
    QA note (`tests/manual_qa.md`).

- [x] 11. **README** _(supporting R5)_
  - Install instructions, CLI usage, where the token cache lives, how to
    log out (delete `~/.garminconnect/`), troubleshooting (MFA, duplicate,
    malformed GPX).

- [x] 18. **`--latest DIR` flag** _(R8)_
  - Add `mwgc.history` module: `DEFAULT_HISTORY_PATH`, `was_uploaded(start_time)`,
    `record_upload(start_time)` backed by `~/.mwgc/history.json`.
  - In `cli.py`, replace the `--input` required arg with a mutually-exclusive
    group: `--input FILE` | `--latest DIR`.
  - `_find_latest_gpx(dir) -> Path`: glob `*.gpx`, sort by `st_mtime`, return
    last; raise `GpxParseError` if none found.
  - Add exit code 6 to the table (skipped — already in history).
  - Tests: `test_history.py` (round-trip, idempotent record, missing file);
    `test_cli.py` additions for `--latest` with and without history hit.

- [x] 19. **README update for `--latest` and history** _(R8, R9)_
  - Document `--latest DIR` usage, the `~/.mwgc/history.json` file, and
    exit code 6.

- [ ] 20. **Temperature forwarding** _(R10)_
  - Add `temperature_c: float | None = None` to `TrackPoint` (frozen
    dataclass default keeps existing callers working).
  - In `gpx_parser._extract_extensions`, parse `atemp` → `temperature_c`.
  - In `fit_builder`, emit `record.temperature` (sint8, °C) when the
    field is set.
  - Tests: `test_gpx_parser` — fixture point with atemp parses correctly;
    point without atemp gives `None`. `test_fit_builder` — temperature
    appears in decoded records when present; absent when not.

- [ ] 21. **HTTP upload timeout** _(R11)_
  - Read `MWGC_UPLOAD_TIMEOUT_S` env var (default 60) in `uploader.py`.
  - Pass the timeout to the garminconnect upload call (investigate whether
    `Garmin` exposes a timeout kwarg; if not, patch at the `garth`/
    `curl_cffi` session level).
  - On timeout, surface as `UploadError("upload timed out")`.
  - Tests: monkeypatch `upload_activity` to raise a timeout exception;
    assert `UploadError` is raised and exit code is 4.

- [ ] 22. **Narrow token-resume exception handling** _(R12)_
  - In `uploader._get_client`, replace `except Exception` with
    `except (FileNotFoundError, GarminConnectAuthenticationError,
    OSError, json.JSONDecodeError)`.
  - Tests: assert that an unexpected exception (e.g. `RuntimeError`)
    during `client.login()` propagates rather than falling back to
    interactive login.

- [ ] 23. **XML DoS hardening** _(R13)_
  - Add `defusedxml>=0.7,<1` to `pyproject.toml` dependencies.
  - In `gpx_parser.parse_gpx`, add a file-size guard (raise
    `GpxParseError` if `path.stat().st_size > 50 * 1024 * 1024`).
  - Wrap the `gpxpy.parse` call using `defusedxml`'s safe parse, or
    configure the underlying expat parser to disable entity expansion.
  - Tests: a GPX file exceeding the size limit raises `GpxParseError`;
    a normal file parses correctly.
  - Update `requirements.lock` after adding the dependency.
  - Update STRIDE doc: flip T1 / D1 status to **OK**.

- [ ] 24. **GitHub Actions CI** _(R14)_
  - Create `.github/workflows/ci.yml`: trigger on push + PR, matrix
    Python 3.11 and 3.13, steps: checkout → setup-python → pip install
    `.[dev]` → ruff check → pytest.
  - Add a workflow status badge to the README `## Development` section.

## Out of scope for v1 (tracked, not built)

- GUI front-end — moved to its own spec under
  [`../mywhoosh-to-garmin-gui/`](../mywhoosh-to-garmin-gui/). Builds
  on `core.run`'s `on_progress` callback and a new `Prompter`
  protocol; no changes to the CLI flow.
- Batch / folder watcher.
- Configurable serial number via env var (`MWGC_SERIAL`).
- Calorie estimate refinement beyond the simple work-kJ method.
- Normalized power, TSS, IF.
