# Changelog — Label Editor

All notable changes to the Label Editor. Versions follow [SemVer](https://semver.org/);
release tags are `label-editor-vX.Y.Z` (`relabeler-vX.Y.Z` before 1.2.0).

## [1.2.0] — 2026-07-28

Renamed from "Relabeler" to "Label Editor" and reorganized. No change to how the
tool reads, edits, or writes files.

### Changed
- **The tool is now `label-editor/`**, matching the `mapview-editor` convention.
  Release tags become `label-editor-vX.Y.Z`; `relabeler-v1.1.0` stays as history.
- **The exe carries its version** — `LabelEditor-v1.2.0.exe` rather than
  `SensorViewRelabeler.exe`, so a download is identifiable on sight.
- Entry point `app.py` → `server.py`, matching the MapView Editor.
- Docs moved under `docs/`. `LABELING.md` came in from the repository root; a
  redirect stub remains at the old path because the shipped v1.1.0 exe links to it.
- The UI, `--help`, and `--version` all say "Label Editor".

### Fixed
- The example CSVs in `examples/` were missing the `Notes` column added in 1.1.0,
  so they no longer matched the template the tool generates.

## [1.1.0] — 2026-07-28

Validation is now split into rules the BMS actually requires and recommendations
you can ignore, and the notes field is editable.

### Fixed
- **Zone names were capped at 20 characters; the column holds 50.** `MAX_LABEL`
  was applied to both tables, so valid zone names were rejected for 30 characters
  they didn't need. Limits are now per-kind, measured from the schema:
  devices `VARCHAR(20)`, zones `VARCHAR(50)`, notes `VARCHAR(200)`.

### Changed
- **The floor-token check no longer blocks a write.** It was a site convention
  (`{BLDG}_{FLR}_{AREA}`) enforced as hard as the real rules, which locked out
  anyone whose labels don't encode a floor in the second field. Now an advisory.
- **Hyphens are accepted.** BACnet permits `-` as a delimiter; Acuity documents
  the underscore for nLight. Hyphens pass validation and raise an advisory.
- Character validation now states the full BACnet restriction set — no spaces,
  symbols, slashes, math operators, or non-ASCII glyphs.
- `core.validate()` returns blockers only (characters, length, duplicates). New
  `core.advisories()` returns non-blocking notes. Web UI renders them in an amber
  block; `/api/validate` gained `advisories` and `docs`; the CLI prints `NOTES`
  and exits 0.

### Added
- **Notes are editable** — `UserComments` on both devices and zones, 200 chars,
  free text. New Notes column in the table, a `Notes` column in the CSV template
  (optional on import), and writes on Apply. Blank means unchanged; an unedited
  note is never rewritten. Length-checked only, since it isn't a BACnet name.
- **[LABELING.md](docs/LABELING.md)** — what the tools enforce versus what they
  recommend, with the schema evidence and the recommended naming format. Linked
  from the web UI header, the CLI help, and the advisory output.

### Notes
Length validation matters more than it looks: Access accepts an over-length write
and silently truncates it — 30 chars in, 20 stored, no error raised. Truncation can
also forge duplicates from labels that differed only past the cutoff.

## [1.0.0] — 2026-07-27

Initial public release.

- Local web tool: load a `.svdb` backup **or a bare `sensor.mdb`**, edit labels
  in the table or round-trip a CSV rename list, validate, download the rebuilt
  `_relabeled` file (same type as the input).
- CLI (`cli.py`): dry-run by default, `--apply` to write; reports crosswalk
  coverage against the backup before writing.
- Validation: BMS naming rules (letter start, underscores only, ≤20 chars),
  duplicate detection, floor-token sanity check.
- Writes both label columns (`UserLabelCurrent`+`UserLabelAuthority`,
  `ZoneName`+`ZoneNameCurrent`) so imports arrive in-sync.
- Safe repackaging from the archive's original member list (excludes the
  Access `.ldb` lock file); the original input file is never modified.
- Standalone Windows exe (`SensorViewRelabeler.exe`) via PyInstaller.

[1.2.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/label-editor-v1.2.0
[1.1.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/relabeler-v1.1.0
