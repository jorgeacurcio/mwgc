# Manual QA log

## CLI — task 10 (2026-04-30)

**GPX source:** real MyWhoosh export, ride "Mompox City"
(`F7Km5OLATQyZwSQc99BPVpwGEOWNKz272AQeu0Zv.gpx`)

**Command:**
```
python -m mwgc --input <gpx-path>
```

**Conversion output:** 1934 points, 1935 s, 13 458 m  
**FIT size:** 41 KB  
**Garmin Connect activity:** https://connect.garmin.com/app/activity/22718269601

**Verified on Garmin Connect:**
- Activity visible, sport = cycling (virtual)
- HR graph ✅
- Cadence graph ✅
- Power graph ✅  *(required a bug-fix: MyWhoosh exports power as float strings
  e.g. `<power>180.0</power>`; parser was doing `int(text)` which raised
  `ValueError` and silently dropped all power readings. Fixed to
  `int(float(text))` — see commit for details.)*

**Token caching:** first run prompted for credentials; subsequent runs reuse
cached tokens in `~/.garminconnect/` automatically.  
*(A second bug was found and fixed: `_interactive_login` was calling
`client.garth.dump()` which no longer exists in garminconnect ≥ 0.3.
Fix: pass the token dir to `client.login(tokenstore)` directly so
garminconnect handles persistence itself.)*

---

## GUI — task 17 (2026-04-30)

**Command:** `.venv\Scripts\mwgc-gui.exe`

**Verified:**
- Window opens cleanly (no config-file error) ✅
- Browse picker selects GPX; FIT path auto-fills ✅
- Skip upload run: progress bar moves through convert stages, log ends with "Upload skipped" ✅
- Upload run: uses cached tokens from `~/.garminconnect/`, no credential dialogs shown,
  log ends with "Already on Garmin Connect (duplicate)" (expected — ride already uploaded
  via CLI task 10) ✅
- Run button disabled during run, re-enabled on completion ✅

**Design change made during QA:** the original GUI required a plaintext
`~/.mwgc/config.toml` for credentials. Changed to dialog-based prompting
(`_DialogPrompter`) that pops a modal for email / password / MFA only when
the token cache is absent or expired — matching the CLI behaviour.
The `config.py` module is retained (used by `save_config` in other contexts)
but the GUI no longer reads it.
