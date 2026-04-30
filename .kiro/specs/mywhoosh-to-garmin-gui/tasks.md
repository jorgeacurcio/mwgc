# Implementation Plan — GUI

Tasks are ordered for incremental delivery. Each is independently
testable and references the requirements it satisfies. Numbering
continues from the CLI spec for clarity (12+).

- [ ] 12. **Prompter protocol + uploader refactor** _(supports R3, R4, R6)_
  - Add `mwgc.prompter` with `Prompter` protocol and `StdinPrompter`
    matching the current behavior.
  - Add `ConfigError` to `mwgc.errors`.
  - Refactor `mwgc.uploader.upload`, `_get_client`,
    `_interactive_login` to accept an optional
    `prompter: Prompter | None = None`; `None` uses `StdinPrompter`.
  - Add the same pass-through to `mwgc.core.upload` and
    `mwgc.core.run`.
  - All 75 existing tests must keep passing without changes.
  - Tests: a small `test_prompter.py` covering StdinPrompter with
    monkeypatched `input` / `getpass`.

- [ ] 13. **Config module** _(R3)_
  - Implement `mwgc.config` with frozen `Config` dataclass
    (`garmin_email`, `garmin_password`), `DEFAULT_CONFIG_PATH`,
    `load_config(path=None) -> Config`,
    `save_config(config, path=None) -> None`.
  - `load_config` raises `ConfigError` on missing or malformed
    file or missing keys.
  - `save_config` writes the parent directory if needed and applies
    `os.chmod(path, 0o600)` on POSIX.
  - Tests: round-trip through `tmp_path`; missing file; malformed
    TOML; missing keys; chmod on POSIX (skip on Windows).

- [ ] 14. **GUI scaffold** _(R1, R2, R5, R6)_
  - Implement `mwgc.gui` with:
    - `App` class building the main window: file entry + Browse,
      output entry + Browse, "Skip upload" checkbox, Run button,
      progress bar, log textbox.
    - `_ProgressBridge` that turns worker-thread `(stage, fraction)`
      callbacks into `root.after(0, ...)` updates.
    - `_run_worker` that calls `mwgc.core.run` with the bridge as
      `on_progress` and a `ConfigPrompter` (loaded lazily) as the
      prompter.
    - Disabled controls during a run; re-enabled on completion.
    - `MwgcError` handling that appends to log and shows
      `messagebox.showerror`.
  - Add `main()` entry point that constructs and `mainloop()`s the
    app.
  - Add `__main__.py` shim only if needed; otherwise rely on the
    `mwgc-gui` console script.
  - Tests: smoke test that `gui.App(...)` constructs without
    entering mainloop (gated on `customtkinter` import; skip if
    not installed).

- [ ] 15. **MFA dialog** _(R4)_
  - Implement an `_MfaDialog` (CTkToplevel modal) with one entry
    and OK / Cancel.
  - In `gui.App`, wire the dialog into a `_request_mfa()` method
    that uses a `queue.Queue` to bridge worker → UI → worker.
  - Pass `_request_mfa` as the `mfa_callback` of `ConfigPrompter`.
  - Cancel raises `AuthError("MFA cancelled")` on the worker
    thread.
  - Tests: skipped — exercised via the manual run in task 17.

- [ ] 16. **pyproject + entry point + README** _(supports R3)_
  - Add `customtkinter>=5.2` under `[project.optional-dependencies]
    gui` (so the CLI install stays slim).
  - Add `mwgc-gui = "mwgc.gui:main"` to `[project.scripts]`.
  - Update root `README.md` with: install with `[gui]` extra, GUI
    usage, config-file format and security warning, GUI
    troubleshooting (missing customtkinter, missing config,
    cancelled MFA).

- [ ] 17. **Manual GUI QA** _(all)_
  - Launch `mwgc-gui` against the same real MyWhoosh GPX used by
    CLI task 10.
  - Verify: file pickers work, progress bar moves, log is
    readable, run with --no-upload writes the FIT, run with
    upload uploads (MFA dialog appears if Garmin asks), errors
    show in a dialog and the FIT is preserved on upload failure.
  - Append a short note to `tests/manual_qa.md` capturing the
    Garmin Connect activity URL for the GUI run.

## Out of scope for GUI v1 (tracked, not built)

- In-app settings dialog to enter / change credentials. v1 expects
  the user to write `~/.mwgc/config.toml` by hand or via their
  editor.
- OS keyring integration for the password. v1 stores plaintext
  with a warning; keyring is a v1.1 candidate.
- Drag-and-drop of GPX files onto the window.
- Multiple concurrent runs / batch mode.
- Persistent log between runs.
- App icon / installer / `.exe` packaging.
