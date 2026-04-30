# Requirements Document

## Introduction

This project converts a single MyWhoosh GPX export into a Garmin-compatible
FIT activity file, stamps it with Garmin Fenix 5 Plus device identifiers,
and uploads it to Garmin Connect.

The first deliverable is a CLI. The architecture must keep conversion and
upload logic decoupled from the CLI layer so a GUI front-end can be added
later without rewriting the core.

Hard scope of v1:
- Single input file per invocation
- Hardcoded Fenix 5 Plus device profile
- GPX with power, cadence, and heart-rate extensions
- Cycling activity (virtual / indoor)

## Requirements

### Requirement 1: GPX → FIT conversion

**User Story:** As a MyWhoosh user, I want my GPX export converted to a
Garmin-compatible FIT file, so that Garmin Connect treats the ride as a
native activity with full metrics.

#### Acceptance Criteria

1. WHEN provided a valid MyWhoosh GPX file THE SYSTEM SHALL produce a
   well-formed `.fit` file that decodes without errors using the official
   Garmin FIT SDK.
2. WHEN parsing the GPX THE SYSTEM SHALL extract, per trackpoint: UTC
   timestamp, latitude, longitude, altitude, heart rate, cadence, and
   power.
3. THE SYSTEM SHALL preserve the activity start timestamp from the first
   GPX trackpoint.
4. IF a trackpoint is missing one of power, cadence, or heart rate THEN
   THE SYSTEM SHALL emit the record without that field rather than fail.
5. THE SYSTEM SHALL set sport to `cycling` and sub-sport to
   `virtual_activity` on the session and lap messages.

### Requirement 2: Fenix 5 Plus device identity

**User Story:** As a Fenix 5 Plus owner, I want the FIT file to identify
as my watch, so that Garmin Connect attributes the activity to the device
and keeps device-specific stats coherent.

#### Acceptance Criteria

1. THE SYSTEM SHALL set `file_id.manufacturer` to `garmin`.
2. THE SYSTEM SHALL set `file_id.product` to `fenix5_plus`
   (FIT `garmin_product` enum value 3111).
3. THE SYSTEM SHALL set `file_id.type` to `activity`.
4. THE SYSTEM SHALL emit a `device_info` message at the start of records
   identifying the creator as Fenix 5 Plus with a configured serial number
   and software version.
5. THE SYSTEM SHALL emit a `file_creator` message with the same software
   version.

### Requirement 3: Session summary metrics

**User Story:** As a Garmin Connect user, I want totals and averages to
appear on the activity, so that the ride looks identical to one recorded
on a real device.

#### Acceptance Criteria

1. THE SYSTEM SHALL compute and write a `session` message containing:
   `start_time`, `total_elapsed_time`, `total_timer_time`,
   `total_distance`, `avg_heart_rate`, `max_heart_rate`, `avg_power`,
   `max_power`, `avg_cadence`, `max_cadence`, `total_calories`.
2. THE SYSTEM SHALL emit at least one `lap` message covering the full
   activity with the same aggregates.
3. THE SYSTEM SHALL emit `event` records of type `timer/start` at the
   first trackpoint and `timer/stop_all` at the last.
4. WHEN computing `total_distance` THE SYSTEM SHALL prefer cumulative
   geodesic distance between trackpoints; IF GPS coordinates are absent
   for a segment THEN THE SYSTEM SHALL fall back to integrating speed
   over time.

### Requirement 4: Garmin Connect upload

**User Story:** As a user, I want the converted file auto-uploaded to
Garmin Connect after conversion, so that I don't open the website
manually.

#### Acceptance Criteria

1. WHEN conversion succeeds AND upload is enabled THE SYSTEM SHALL upload
   the `.fit` file to Garmin Connect.
2. THE SYSTEM SHALL persist Garmin Connect OAuth tokens locally so that
   subsequent runs do not require re-entering credentials.
3. WHERE Garmin Connect requires MFA at login THE SYSTEM SHALL prompt the
   user for the MFA code on stdin.
4. IF the upload fails due to expired or invalid tokens THEN THE SYSTEM
   SHALL prompt for credentials and retry the upload once.
5. IF Garmin Connect rejects the file as a duplicate THEN THE SYSTEM
   SHALL report it as an informational outcome and exit successfully.
6. IF the upload fails for any other reason THEN THE SYSTEM SHALL keep
   the locally written `.fit` file and exit non-zero with the error.

### Requirement 5: CLI interface

**User Story:** As a CLI user, I want a single command to convert and
upload, so that I can chain it from scripts.

#### Acceptance Criteria

1. WHEN invoked with `--input <path>` THE SYSTEM SHALL convert that GPX
   and, by default, upload the resulting FIT.
2. WHERE `--no-upload` is set THE SYSTEM SHALL write the FIT and skip
   upload.
3. WHERE `--output <path>` is set THE SYSTEM SHALL write the FIT to that
   path; otherwise THE SYSTEM SHALL write it next to the input with a
   `.fit` extension.
4. THE SYSTEM SHALL exit with code 0 on success, non-zero on failure.
5. THE SYSTEM SHALL print human-readable progress and a final result line
   to stdout.

### Requirement 6: Decoupled core for future GUI

**User Story:** As a future maintainer, I want core logic separated from
the CLI, so that a GUI front-end can reuse it without subprocess hacks.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose `convert(gpx_path, fit_path, profile)` and
   `upload(fit_path)` as importable functions.
2. THE SYSTEM SHALL NOT write to stdout, stderr, or `sys.exit` from
   modules other than the CLI entrypoint.
3. THE SYSTEM SHALL surface progress via a callback or generator that the
   CLI consumes, so a GUI can bind it to a progress bar later.

### Requirement 7: Error reporting

#### Acceptance Criteria

1. IF the input GPX is malformed THEN THE SYSTEM SHALL report a clear
   parse error and exit non-zero without writing a FIT file.
2. IF the input path does not exist THEN THE SYSTEM SHALL report
   "file not found" and exit non-zero.
3. IF FIT writing fails partway THEN THE SYSTEM SHALL delete the partial
   output before exiting.
4. THE SYSTEM SHALL never include `--no-verify`-style escape hatches that
   bypass FIT validation.
