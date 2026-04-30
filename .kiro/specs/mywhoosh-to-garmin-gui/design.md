# Design Document — GUI

## Overview

The GUI is a thin presentation layer over the existing
`mwgc.core.run` pipeline. The hard work — GPX parsing, FIT
encoding, Garmin Connect upload — does not change. What changes
is how credentials are sourced (config file instead of stdin)
and how progress is rendered (progress bar instead of stdout).

```
+----------------+    +-------------+    +------------------+
| CustomTkinter  |--> |  worker     |--> | mwgc.core.run    |
| App (UI thread)|    |  thread     |    |   (existing)     |
+----------------+    +-------------+    +------------------+
        ^                    |                   |
        |   root.after(0,    |   on_progress     |
        |       updater)     +------ events -----+
        |
   widgets only touched
   on the UI thread
```

## Why CustomTkinter

- Uses stdlib `tkinter` underneath; no Qt or web stack to ship.
- Modern look out of the box (rounded buttons, dark/light theme)
  without writing widget styles by hand.
- Single Python dependency (`customtkinter`), pulls Pillow for
  icons.
- Cost: tkinter's threading model still applies — widgets must
  not be touched from worker threads.

PySide6 was considered for cross-thread signals/slots ergonomics
and a more native look on Windows, but the ~50 MB install hit and
LGPL deployment quirks are not worth it for a personal tool.
Revisit if and when this app needs to ship to other people.

## Module layout

New modules added to the existing `mwgc` package:

```
src/mwgc/
  ... existing ...
  prompter.py    # Prompter protocol + StdinPrompter (current behavior)
                 # + ConfigPrompter (used by GUI)
  config.py      # Config dataclass + load_config / save_config
  gui.py         # App class, MFA dialog, worker thread plumbing
  __main__.py    # already exists for python -m mwgc (CLI entry)
```

A new console-script `mwgc-gui` is added in `pyproject.toml`. The
`customtkinter` dependency is gated behind a `gui` extra so the
CLI install doesn't pay for it:

```toml
[project.optional-dependencies]
gui = ["customtkinter>=5.2"]
```

`mwgc-gui` will register regardless of extras; if `customtkinter`
is missing the entry point fails with a clean `ImportError` and
README points to `pip install mwgc[gui]`.

## Prompter protocol

`uploader.py` currently calls module-level `_prompt_email`,
`_prompt_password`, `_prompt_mfa` functions. We replace this with a
small protocol so the GUI can inject its own implementation.

```python
# prompter.py
from typing import Protocol

class Prompter(Protocol):
    def email(self) -> str: ...
    def password(self) -> str: ...
    def mfa(self) -> str: ...

class StdinPrompter:
    def email(self) -> str: ...           # input(...)
    def password(self) -> str: ...        # getpass.getpass(...)
    def mfa(self) -> str: ...             # input(...)

DEFAULT_PROMPTER: Prompter = StdinPrompter()
```

`uploader.upload`, `uploader._get_client`, and
`uploader._interactive_login` accept an optional
`prompter: Prompter | None = None`. None means "use the default
StdinPrompter". The CLI passes None (no behavior change). The GUI
passes a `ConfigPrompter` with an MFA callback that pops a tk
dialog.

`core.upload` and `core.run` add a matching pass-through parameter
so the GUI can drive everything via `core.run`.

## Config file

Format: TOML, single table.

```toml
# ~/.mwgc/config.toml
[garmin]
email = "you@example.com"
password = "your-password"
```

```python
# config.py
@dataclass(frozen=True)
class Config:
    garmin_email: str
    garmin_password: str

DEFAULT_CONFIG_PATH: Path = Path.home() / ".mwgc" / "config.toml"

def load_config(path: Path | None = None) -> Config:
    """Read the TOML file. Raises ConfigError on missing or malformed."""

def save_config(config: Config, path: Path | None = None) -> None:
    """Write the TOML file with chmod 600 on POSIX."""
```

`ConfigError` lives in `mwgc.errors` next to the existing hierarchy
(it is an `MwgcError`).

Reading uses stdlib `tomllib` (Python 3.11+). Writing uses a
hand-formatted TOML string — no `tomli_w` dep. Values are
double-quoted with `"` escaping; in practice email and password
never contain unescapable characters, but `_quote_toml_string`
handles `\\` and `"` defensively.

Permissions: on POSIX, `os.chmod(path, 0o600)` after write. On
Windows, we rely on the per-user profile ACL (the file lives in
the user's home dir which non-admins cannot read).

## Threading model

Tk's rule: only the thread that created the root window can touch
widgets.

Flow:
1. User clicks "Run" — UI thread reads field values, disables
   controls, spawns `threading.Thread(target=self._run_worker)`.
2. Worker calls `mwgc.core.run(..., on_progress=callback,
   prompter=ConfigPrompter(config, mfa_callback=self._show_mfa))`.
3. `on_progress` and exception handling marshal updates back to
   the UI thread via `self.root.after(0, lambda: ...)`.
4. MFA callback (called from the worker thread) blocks on a
   `queue.Queue`; the UI thread shows the modal, gets the input,
   puts it in the queue, worker wakes and returns the code to
   `python-garminconnect`.

The worker thread is a daemon so closing the window doesn't hang.

## MFA dialog

A small `CTkInputDialog` (or hand-rolled `CTkToplevel`) with one
entry field and OK / Cancel. Submit puts the code in the response
queue. Cancel puts a sentinel that causes the worker to raise
`AuthError("MFA cancelled")`.

The dialog is modal relative to the main window
(`grab_set()` so the user can't interact with the main window
while it's open).

## Error mapping

The GUI catches `MwgcError` (and subclasses) on the worker thread,
posts the message to the UI thread via `root.after`, and:
- Appends `error: <msg>` to the log
- Shows a `tkinter.messagebox.showerror` dialog
- Re-enables controls

For `AuthError` and `UploadError`, the locally written FIT stays
on disk (the existing `core.run` already keeps it).

## Testing strategy

Pytest tests are kept minimal for the GUI module because real
widget tests need a display and become flaky:

- `test_prompter.py`: StdinPrompter happy path + that the
  Prompter protocol's three methods exist (typing is structural).
- `test_config.py`: `load_config` / `save_config` round-trip via
  `tmp_path`, plus malformed and missing-file error paths, plus
  POSIX chmod assertion (skipped on Windows).
- `test_gui.py`: import + construction smoke test only. Asserts
  `gui.App` can be instantiated without entering `mainloop`. Does
  not click buttons.

Real GUI verification happens manually: launch `mwgc-gui`, run a
ride end-to-end. Recorded as a one-line entry in
`tests/manual_qa.md` after task 10 of the CLI spec finishes.

## Integration with the CLI spec

Out-of-scope items in the original CLI spec move accordingly:
- "GUI front-end — `core.run` already accepts `on_progress`, so
  the GUI task is purely UI work later." → handled here.
- "Configurable serial number via env var (`MWGC_SERIAL`)" stays
  out of scope for both v1s.

Breaking-change risk for the CLI is low: the prompter parameter
is optional and defaults to current behavior. All existing
75 tests continue to pass without changes.
