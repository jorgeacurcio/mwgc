# mwgc — MyWhoosh to Garmin Connect

Convert a [MyWhoosh](https://mywhoosh.com/) GPX export into a Garmin FIT
activity file, stamp it with a Garmin Fenix 5 Plus identity, and upload
it to [Garmin Connect](https://connect.garmin.com/).

The CLI does one ride at a time. The architecture keeps conversion and
upload separate from the CLI layer so a GUI can be added later without
rewriting the core (see [`.kiro/specs/mywhoosh-to-garmin/`](.kiro/specs/mywhoosh-to-garmin/)
for the EARS-style spec).

## Requirements

- Python 3.11 or newer
- A Garmin Connect account (only needed for upload)

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
uv pip install -e ".[dev]"
```

With plain pip:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
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

## Out of scope (v1)

- GUI front-end (`core.run` already accepts an `on_progress` callback;
  GUI is purely a UI task on top)
- Batch processing or folder watching
- User-configurable serial number / device profile via env var
- More accurate calorie estimation than the cycling rule of thumb
  (1 kJ work ≈ 1 kcal)
- Normalized power, TSS, IF
