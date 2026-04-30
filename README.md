# mwgc — MyWhoosh to Garmin Connect

Convert a [MyWhoosh](https://mywhoosh.com/) GPX export into a Garmin FIT
activity file, stamp it with a Garmin Fenix 5 Plus identity, and upload
it to [Garmin Connect](https://connect.garmin.com/).

Ships as a **CLI** (`mwgc`) and a desktop **GUI** (`mwgc-gui`). Both
share the same conversion + upload pipeline. See
[`.kiro/specs/mywhoosh-to-garmin/`](.kiro/specs/mywhoosh-to-garmin/) for
the CLI spec and
[`.kiro/specs/mywhoosh-to-garmin-gui/`](.kiro/specs/mywhoosh-to-garmin-gui/)
for the GUI spec.

## Requirements

- Python 3.11 or newer
- A Garmin Connect account (only needed for upload)

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
uv pip install -e ".[dev]"          # CLI + dev tools (also pulls the GUI dep)
# uv pip install -e ".[gui]"        # CLI + GUI, no test/lint tools
# uv pip install -e .                 # CLI only
```

With plain pip:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"           # or .[gui], or just .
```

The GUI requires `customtkinter`; it's pulled in by both the `gui` and
`dev` extras. If you install the bare package, `mwgc-gui` will fail
with a clean `ImportError` until you `pip install mwgc[gui]`.

### Reproducible install (locked)

A hash-pinned lockfile lives at [`requirements.lock`](requirements.lock).
It captures the exact version of every direct and transitive dependency
plus their SHA-256 hashes, so `pip` will refuse to install anything that
doesn't match. Use it when you want the same dependency tree the
project was tested against (and to limit casual supply-chain risk):

```bash
pip install -r requirements.lock
pip install -e . --no-deps
```

To regenerate after changing `pyproject.toml`:

```bash
pip install pip-tools                 # one-time
pip-compile pyproject.toml \
    --extra dev --extra gui \
    --output-file requirements.lock \
    --generate-hashes
```

To bump a single dep:

```bash
pip-compile --upgrade-package gpxpy ...   # same flags as above
```

## Usage

Convert and upload in one step:

```bash
mwgc --input ride.gpx
```

Convert only, no upload:

```bash
mwgc --input ride.gpx --no-upload
```

Custom output path:

```bash
mwgc --input ride.gpx --output ./out/ride.fit
```

The default output path is the input file with the extension changed
to `.fit`. The activity is tagged as cycling, sub-sport
`virtual_activity`.

Sample output:

```
[  0%] convert/aggregating
[ 10%] convert/framing
[ 35%] convert/records
[ 70%] convert/done
[ 80%] upload/uploading
[100%] upload/uploaded
ride.fit written (3214 points, 3214.0s, 32114.5 m). Uploaded to Garmin Connect.
```

`python -m mwgc ...` works too if you'd rather not rely on the
console-script entry point.

### GUI

```bash
mwgc-gui
```

A single window with a GPX file picker, an output FIT path, a
"Skip upload" checkbox, a "Run" button, a progress bar, and a log
area. The GUI reuses the same conversion and upload pipeline as the
CLI; the only difference is where credentials come from.

The GUI reads Garmin credentials from a TOML config file at
`~/.mwgc/config.toml`:

```toml
[garmin]
email = "you@example.com"
password = "your-password"
```

If the file is missing and you click Run with upload enabled, the GUI
shows an error dialog explaining what to put where and aborts. With
"Skip upload" ticked, the config file is not required.

If your Garmin account has MFA enabled, a small modal dialog appears
during login asking for the code. Cancelling it cancels the run.

> The password is stored in plaintext. Don't commit `~/.mwgc/` to a
> repo and don't sync it via cloud-drive software. On macOS / Linux
> the file is `chmod 600` automatically; on Windows it relies on the
> per-user profile ACL. OS keyring integration is in the v1.1
> backlog.

### Exit codes

| Code | Meaning                                               |
|-----:|-------------------------------------------------------|
|    0 | Success (a duplicate upload is treated as success too)|
|    1 | Generic / unexpected error                            |
|    2 | Bad input — file missing or malformed GPX             |
|    3 | FIT build failed                                      |
|    4 | Upload failed (non-auth)                              |
|    5 | Garmin Connect authentication failed after retry      |

## Token cache and logout

On first upload, mwgc prompts for your Garmin Connect email, password,
and (if your account has it enabled) an MFA code. On success, OAuth
tokens are written to:

```
~/.garminconnect/
```

Subsequent runs reuse those tokens, so you won't be prompted again
until they expire. To log out, delete the directory:

```bash
rm -rf ~/.garminconnect       # macOS / Linux
Remove-Item -Recurse ~/.garminconnect   # Windows PowerShell
```

The next upload after deletion will prompt for credentials again.

## Troubleshooting

**Asks for credentials every run.** Token write failed or the cache is
on a path that gets wiped. Check `~/.garminconnect/` exists after a
successful run. If it doesn't, your home directory is probably
read-only or roamed away under your back.

**MFA code rejected.** Codes are valid for ~30 seconds and only once.
If you mistyped, the run will fail with exit code 5; rerun and enter
the next code Garmin shows you.

**`Already on Garmin Connect (duplicate).`** Garmin recognises this
exact ride was already uploaded. The local FIT is kept, exit code is
0. If you need to re-upload deliberately, delete the previous activity
on Garmin Connect first.

**`error: GPX parse failed: ...`** The input isn't a valid GPX file or
contains zero trackpoints. Open it in a text editor — MyWhoosh exports
should start with `<gpx version="1.1" ...>` and contain `<trkpt>`
entries with timestamps.

**`error: input file not found: <path>`** Path typo or wrong working
directory. Pass an absolute path to be sure.

**Activity shows up but readings are empty.** Your GPX export
genuinely has no power, cadence, or HR data. mwgc only forwards what
it finds in the GPX `<extensions>` block — it doesn't fabricate
metrics.

**Activity attributed to the wrong watch.** The device profile is
hardcoded to Fenix 5 Plus (`garmin_product` enum value 3110). If you
own a different model and want it tagged as such, edit
[`src/mwgc/devices.py`](src/mwgc/devices.py).

**`mwgc-gui` fails with `ModuleNotFoundError: No module named 'customtkinter'`.**
You installed without the GUI extra. Run `pip install -e ".[gui]"`
(or `".[dev]"`).

**GUI's Run button stays disabled.** The previous run is still in
progress. If something hung, close and reopen the window — the worker
thread is a daemon, so closing the window kills it.

**GUI says "config file not found".** Create
`~/.mwgc/config.toml` with the format shown in the GUI section
above. Or click "Skip upload" if you only want to convert.

**GUI's MFA dialog never appears.** It only fires when Garmin asks
for one. If your account has MFA enabled and you don't see a dialog,
either Garmin reused a recent session or the worker died before
reaching login — check the log area for an error line.

## Development

Run the test suite:

```bash
.venv/Scripts/python -m pytest      # Windows
# .venv/bin/python -m pytest        # macOS / Linux
```

Lint:

```bash
.venv/Scripts/ruff check src tests
```

The Kiro-style spec under [`.kiro/specs/mywhoosh-to-garmin/`](.kiro/specs/mywhoosh-to-garmin/)
is the source of truth for behavior. If you're changing how mwgc works,
update the spec first and the code second.

A point-in-time STRIDE threat analysis lives at
[`docs/stride-analysis.md`](docs/stride-analysis.md). Re-run it when
adding a new external input source, a network listener, a plugin
mechanism, or a credential-handling dependency.

## Out of scope (v1)

- GUI Settings dialog for entering / editing credentials in-app
  (today: edit `~/.mwgc/config.toml` by hand)
- OS keyring storage for the password (today: plaintext config file)
- Drag-and-drop GPX onto the GUI window
- Batch processing or folder watching
- User-configurable serial number / device profile via env var
- More accurate calorie estimation than the cycling rule of thumb
  (1 kJ work ≈ 1 kcal)
- Normalized power, TSS, IF
