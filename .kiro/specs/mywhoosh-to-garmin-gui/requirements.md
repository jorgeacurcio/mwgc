# Requirements Document — GUI

## Introduction

A desktop GUI for `mwgc` that runs the same convert + upload pipeline
as the CLI. Built with **CustomTkinter** for a modern look without a
heavy Qt dependency. The GUI reads Garmin Connect credentials from a
TOML config file, so it doesn't have to prompt for them every run.
MFA codes are still requested interactively when Garmin requires one,
because they're per-login.

The GUI is a strict consumer of the existing core: no convert or
upload logic lives in the GUI module. See the CLI spec under
[`../mywhoosh-to-garmin/`](../mywhoosh-to-garmin/) for that core.

Hard scope of GUI v1:
- Single window, one ride per click
- Credentials read from `~/.mwgc/config.toml` (no in-app settings UI)
- MFA prompted via a modal dialog when Garmin asks for it
- Reuses `mwgc.core.run` end-to-end; no parallel pipeline

## Requirements

### Requirement 1: Single-window workflow

**User Story:** As a MyWhoosh user, I want a desktop window that
converts and uploads my ride without opening a terminal, so the
workflow fits the rest of my desktop usage.

#### Acceptance Criteria

1. THE SYSTEM SHALL display a main window containing: a GPX file
   path entry with a "Browse…" button, an output FIT path entry
   with a "Browse…" button, a "Skip upload" checkbox, a "Run"
   button, a progress bar, and a multi-line log area.
2. WHEN the user clicks "Run" THE SYSTEM SHALL invoke
   `mwgc.core.run(...)` on a worker thread with the entered
   values.
3. WHILE a run is in progress THE SYSTEM SHALL disable the Run
   button and the input fields, so a second run cannot start
   until the first finishes.
4. WHEN the run completes THE SYSTEM SHALL re-enable the controls
   and append a final summary line to the log.
5. WHERE the output FIT path entry is empty THE SYSTEM SHALL
   default it to the input GPX path with `.fit` extension, the
   same as the CLI.

### Requirement 2: Progress reporting

**User Story:** As a user, I want a visible progress bar and a
running log so that I know the app isn't frozen while the upload
takes its time.

#### Acceptance Criteria

1. THE SYSTEM SHALL update the progress bar's value to match the
   `fraction` argument from each `on_progress` event (range 0..1).
2. THE SYSTEM SHALL append each progress event to the log area in
   the form `[NN%] stage`, deduplicating identical (stage, integer
   percent) pairs to keep the log readable.
3. THE SYSTEM SHALL marshal every progress event from the worker
   thread to the UI thread before touching widgets (tkinter does
   not allow cross-thread widget access).

### Requirement 3: Credential config file

**User Story:** As a regular user, I don't want to retype my Garmin
email and password every run, so I'll keep them in a config file.

#### Acceptance Criteria

1. THE SYSTEM SHALL read Garmin Connect credentials from a TOML
   file at `~/.mwgc/config.toml` containing a `[garmin]` table
   with `email` and `password` keys.
2. IF the config file is missing AND upload is requested THEN
   THE SYSTEM SHALL display an error dialog with the expected
   path and key names, and abort the run before any upload
   attempt.
3. IF the config file is malformed (TOML parse error or missing
   keys) AND upload is requested THEN THE SYSTEM SHALL display
   an error dialog naming the parse error and abort.
4. WHERE the "Skip upload" checkbox is set THE SYSTEM SHALL NOT
   read the config file and SHALL allow the run regardless of
   whether the file exists.
5. THE SYSTEM SHALL store the config file with restrictive
   permissions where the OS supports it (chmod 600 on POSIX);
   on Windows the file relies on the user-profile ACL.
6. THE SYSTEM SHALL document in the README that the password is
   stored in plaintext and the file should not be committed or
   roamed to shared cloud storage.

### Requirement 4: MFA dialog

**User Story:** As a user with MFA enabled, I want to be prompted
for the code only when Garmin requires one, not every run.

#### Acceptance Criteria

1. WHEN Garmin Connect requests an MFA code during login THE
   SYSTEM SHALL display a modal dialog with a single text entry
   and an OK button.
2. THE SYSTEM SHALL block the worker thread until the user
   submits the code, then return the code to `python-garminconnect`.
3. IF the user cancels or closes the dialog without submitting
   THEN THE SYSTEM SHALL raise an authentication error and abort
   the upload, preserving the locally written FIT file.

### Requirement 5: Errors

#### Acceptance Criteria

1. IF the run raises an `MwgcError` (or subclass) THEN THE SYSTEM
   SHALL display the error message in an error dialog and append
   it to the log area.
2. THE SYSTEM SHALL preserve the locally written FIT file on
   upload failure so the user can retry, matching CLI R4.6.

### Requirement 6: Reuse the existing core

**User Story:** As a future maintainer, I want the GUI to reuse
the same conversion and upload code as the CLI, so that fixes and
features land in one place.

#### Acceptance Criteria

1. THE SYSTEM SHALL invoke `mwgc.core.run` with the same arguments
   the CLI uses; no parallel conversion or upload code lives in
   the GUI module.
2. THE SYSTEM SHALL NOT introduce stdout/stderr writes from
   `mwgc.core` or `mwgc.uploader` (R6.2 from the CLI spec stays
   in force).
