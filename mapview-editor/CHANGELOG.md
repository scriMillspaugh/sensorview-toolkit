# Changelog — MapView Editor

All notable changes to the MapView Editor. Versions follow [SemVer](https://semver.org/);
release tags are `mapview-editor-vX.Y.Z`.

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

[1.0.1]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.1
[1.0.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.0
