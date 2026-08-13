# Changelog — MapView Editor

All notable changes to the MapView Editor. Versions follow [SemVer](https://semver.org/);
release tags are `mapview-editor-vX.Y.Z`.

## [1.3.0] — 2026-08-13

- **Installable package.** `pip install mapview-editor` now provides
  `mapview-editor` (web editor) and `mapview-editor-mcp` (MCP server) commands.
  Source moved into the `mapview_editor/` package; `py -m mapview_editor` and
  direct `py mapview_editor/server.py` both still work. Published to PyPI via
  GitHub Actions trusted publishing on tag push, and registered in the MCP
  registry as `io.github.scrimillspaugh/mapview-editor` (`server.json`).
- New MCP tool `start_editor` — launches the editor if it isn't running, so an
  assistant can go from nothing to editing without a manual step.

## [1.2.0] — 2026-08-13

- **Device search (`Ctrl+F`).** Search box in the top bar matches device IDs —
  and plain-language names when a database is loaded — across **all** maps.
  Clicking a result switches to that map, centers the view, selects the device,
  and pulses a ring around it. `Enter` jumps to the first result.
- **Duplicate check.** With the search box empty, one click lists every device
  ID that appears more than once on the *same* map (the same device on
  different maps is intentional and not flagged). Each row jumps to the marker.
- **Duplicate warnings while editing.** Adding a device whose ID already exists
  on the current map asks before adding; renaming a device to a duplicate ID
  shows a quiet note. Neither blocks — some sites use repeats deliberately.
- New endpoint: `GET /api/index` (compact all-maps device index for search).
- **Fixed: device markers rendered vertically mirrored.** Device y is stored
  y-up in the `.mvdb` (same as zone WKT), but the editor had read it as y-down
  since 1.0.0 — every dot drew mirrored across the map's horizontal midline.
  Invisible while dots were anonymous; the labels feature exposed it. The
  editor now flips device y on read and write exactly as it always did for
  zones; stored data is untouched and stays SensorView-compatible. Devices
  placed or moved with earlier versions of this editor were saved in the
  wrong frame — the MCP `flip_devices_y` tool repairs a map in one call.
- **MCP integration (`mcp_server.py`).** A Model Context Protocol server that
  lets an AI assistant (Claude) build and edit drawings through the running
  editor: list/read maps, add/move/remove devices, draw/delete zones, search,
  load `.mvdb`/`.svdb` files, and export. Tools speak image coordinates; the
  zone y-flip is handled internally. Requires `pip install mcp`; register with
  `claude mcp add mapview -- py mcp_server.py`.
- **Live sync.** The editor tracks a revision counter (`GET /api/revision`,
  bumped on every mutation) and the browser polls it, so changes made by the
  MCP server or the API appear in the open editor within ~2 seconds. Unsaved
  manual edits are never overwritten — the UI warns instead.

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

[1.3.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.3.0
[1.2.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.2.0
[1.1.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.1.0
[1.0.1]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.1
[1.0.0]: https://github.com/scriMillspaugh/sensorview-toolkit/releases/tag/mapview-editor-v1.0.0
