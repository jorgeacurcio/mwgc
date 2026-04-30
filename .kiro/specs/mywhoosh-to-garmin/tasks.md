# Implementation Plan

Tasks are ordered for incremental delivery. Each is independently
testable and references the requirements it satisfies. Do them top to
bottom; mark a box only when its acceptance criteria pass.

- [ ] 1. **Project skeleton and tooling** _(R5, R6)_
  - Create `pyproject.toml` with Python 3.11+, `mwgc` package, console
    entry point `mwgc = mwgc.cli:main`.
  - Add dev deps: `pytest`, `pytest-cov`, `ruff`.
  - Add `src/mwgc/__init__.py`, empty module stubs for the layout in
    design.md.
  - Add `.gitignore` (`.venv`, `__pycache__`, `dist`, `*.fit`, token cache dir).

- [ ] 2. **Data models** _(R1, R2)_
  - Implement `mwgc.models` with `TrackPoint`, `DeviceProfile`,
    `ConversionResult` exactly as in design.md.
  - Add `mwgc.errors` with the custom exception hierarchy.

- [ ] 3. **Device profile** _(R2)_
  - Implement `mwgc.devices.FENIX_5_PLUS` with manufacturer=`garmin`,
    product=`fenix5_plus`, product_id=3111, stable placeholder serial,
    software_version=16.0.

- [ ] 4. **GPX parser** _(R1.1, R1.2, R1.3, R1.4, R3.4, R7.1, R7.2)_
  - Implement `mwgc.gpx_parser.parse_gpx(path) -> tuple[list[TrackPoint], datetime]`.
  - Walk extensions namespace-aware; handle missing HR/cadence/power
    gracefully (None, not error).
  - Compute cumulative distance via haversine; fall back to `speed * dt`
    when GPS missing.
  - Raise `GpxParseError` on malformed XML or zero trackpoints.
  - Tests: at least one real MyWhoosh export saved as
    `tests/fixtures/sample_mywhoosh.gpx`.

- [ ] 5. **FIT SDK spike + builder** _(R1.1, R1.5, R2, R3.1, R3.2, R3.3, R7.3)_
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

- [ ] 6. **Core orchestration** _(R6.1, R6.2, R6.3)_
  - Implement `mwgc.core.convert(...)`, `mwgc.core.upload(...)`,
    `mwgc.core.run(...)` per design.md.
  - `on_progress` callback contract: `Callable[[str, float], None]`.
  - No stdout/stderr writes from `core` or below.

- [ ] 7. **Uploader (mocked first)** _(R4.1, R4.5, R4.6)_
  - Implement `mwgc.uploader.upload(fit_path) -> UploadOutcome` using
    `python-garminconnect` (`Garmin.upload_activity`).
  - Outcomes: `UPLOADED`, `DUPLICATE`, raise `UploadError` otherwise.
  - Tests: fake `Garmin` client covering happy path, duplicate
    response, and generic failure.

- [ ] 8. **Auth flow with token cache and retry** _(R4.2, R4.3, R4.4)_
  - On startup, attempt `Garmin.resume(token_dir)`; on failure, run
    interactive `Garmin(email, password).login()` including the MFA
    prompt, then persist tokens via `client.garth.dump(token_dir)`.
  - On `AuthError` during upload, re-login once and retry.
  - Tests: mock the `Garmin` client to fail-then-succeed; assert one
    retry only.

- [ ] 9. **CLI entrypoint** _(R5.1–R5.5, R7.1, R7.2)_
  - `argparse` with `--input`, `--output`, `--no-upload`.
  - Bind `on_progress` to a tidy stdout printer.
  - Exit codes per design.md table.
  - Smoke test: invoke as module against the fixture with `--no-upload`,
    assert `.fit` written and exit code 0.

- [ ] 10. **End-to-end manual test** _(all)_
  - Run against a real MyWhoosh GPX with upload enabled.
  - Verify the activity appears on Garmin Connect with: correct device
    (Fenix 5 Plus), sport=cycling, totals match the source file, HR /
    cadence / power graphs present.
  - Capture the resulting Garmin Connect activity URL in a manual
    QA note (`tests/manual_qa.md`).

- [ ] 11. **README** _(supporting R5)_
  - Install instructions, CLI usage, where the token cache lives, how to
    log out (delete `~/.garminconnect/`), troubleshooting (MFA, duplicate,
    malformed GPX).

## Out of scope for v1 (tracked, not built)

- GUI front-end — `core.run` already accepts `on_progress`, so the GUI
  task is purely UI work later.
- Batch / folder watcher.
- Configurable serial number via env var (`MWGC_SERIAL`).
- Calorie estimate refinement beyond the simple work-kJ method.
- Normalized power, TSS, IF.
