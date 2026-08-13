# Changelog — MapView Editor

All notable changes to the MapView Editor. Versions follow [SemVer](https://semver.org/);
release tags are `mapview-editor-vX.Y.Z`.

## [1.1.0] — 2026-08-13

- **Read-only database labels.** Optionally load a SensorView database backup
  (`.svdb`, or a bare `sensor.mdb`) alongside the `.mvdb` to show plain-language
  device and zone names instead of raw hex IDs. Names appear next to device
  markers (with a toolbar show/hide toggle), in hover tooltips as
  `Label (ID) — Model`, on zone polygons, and as read-only rows in the
  properties panel. A header badge reports match coverage (e.g.
  `42/45 devices matched`).
- **Device-type dot colors.** With a database loaded, dots are colored by
  device family — sensors, WallPods, power packs, power supplies, I/O
  interfaces, backbone — grouped from the model name (a single floor can carry
  20+ distinct models, more than any palette can distinguish). Colorblind-safe
  palette, with an on-map legend of the families present on the current floor;
  the tooltip still shows the exact model.
- **Bigger device dots.** Dot radius now follows the map's own `deviceScale`
  setting (previously a fixed 5px), so markers are findable on large
  floorplans zoomed to fit.
- The database is opened read-only (`ReadOnly=1`) in its own temp directory and
  the connection is closed after reading — the source file is never modified,
  and the exported `.mvdb` is unchanged by this feature.
- New endpoints: `POST /api/labels` (load), `GET /api/labels` (current state,
  used to restore labels after a browser refresh), `DELETE /api/labels` (clear).
- Graceful degradation: the label feature needs `pyodbc` and the Microsoft
  Access Database Engine. If either is missing the server returns a friendly
  message and map editing is unaffected.

## [1.0.1] — 2026-07-28

- `/api/version` no longer returns `repoPath`. Nothing consumed it — the header
  badge dropped it in 1.0.0 — and from a clone it exposed the local filesystem
  path over the API.

## [1.0.0] — 2026-07-27

Initial public release.

- Local web editor for `.mvdb` MapView archives: pan/zoom canvas, move/add/
  remove device markers, draw and reshape zone polygons, properties panel
  (device IDs, zone IDs, parent devices, ports).
- Map management: add, rename, delete floor maps; replace floorplan PNGs.
- Correct zone rendering: WKT polygon y-flip between MapView's y-up storage
  and the y-down canvas/device space.
- Lossless floorplan PNG optimization on export (indexed color when ≤256
  colors, typically ~55–60% smaller; originals kept when not beneficial).
- Export rebuilds the archive from the `mapinfo` index; the original input
  file is never modified.
- Standalone Windows exe (`MapViewEditor.exe`) via PyInstaller; browser opens
  automatically on launch.
- Version reporting: badge in the editor header, `/api/version`, and the startup
  banner. Git branch/commit is appended when running from a clone and omitted in
  the exe, where no repository is present.

[1.1.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.1.0
[1.0.1]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.1
[1.0.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.0
