# MapView Editor

A local web utility for editing Acuity nLight MapView floorplan archives (`.mvdb` files).

Load an exported `.mvdb`, edit floorplans, devices, and zones in the browser, then export a modified `.mvdb` for reimport into SensorView.

## Features

- **Load / Export** `.mvdb` archives (7-zip format used by SensorView MapView)
- **Map management** — add, rename, delete floor maps
- **Navigation tree** — the sidebar is SensorView's MapView drop-down in the order it will appear: drag maps to reorder them or move them between building groups, drag group headers to reorder groups, double-click a header to rename a group, or press **Sort** to order every group by level (P1, B, 01 … PH) with names written as `LEVEL nn`
- **Exports SensorView can import** — the archive is written in the exact shape of SensorView's own export (entry attributes, timestamps, compression, member order, integer device coordinates), and export is refused while any map lacks a floorplan image (see [METHOD.md §4](docs/METHOD.md#4-round-tripping-with-sensorview))
- **Device editing** — select, move, add, and remove device markers
- **Zone editing** — draw new zone polygons, reshape vertices, delete zones
- **Image replacement** — swap floorplan PNGs for any map
- **Automatic image optimization on export** — floorplan PNGs are losslessly re-encoded to indexed color where possible, typically ~55-60% smaller with no visual change (see [FLOORPLAN_STANDARD.md](docs/FLOORPLAN_STANDARD.md))
- **Properties panel** — edit device IDs, positions, zone IDs, parent devices, ports
- **Database labels (read-only)** — optionally load a SensorView database backup (`.svdb` or a bare `sensor.mdb`) to show plain-language device and zone names instead of raw hex IDs: next to markers (toggleable), in tooltips, on zones, and in the properties panel. Dots are also color-coded by device model (with an on-map legend). The database is never modified and the exported `.mvdb` is unchanged
- **Device search** — `Ctrl+F` searches IDs and database names across all maps; results jump to and highlight the device. An empty search offers a same-map duplicate-ID check
- **Pan & zoom** — scroll to zoom, drag to pan, `F` to fit
- **Keyboard shortcuts** — `1`–`5` for tools, `Del` to delete, `Ctrl+S` to save, `Ctrl+F` to search

## Requirements

- Python 3.10+
- Flask
- py7zr
- Pillow (for image optimization on export — server still works without it, just skips optimization)
- pyodbc + the [Microsoft Access Database Engine](https://www.microsoft.com/en-us/download/details.aspx?id=54920) (**only** for the optional database-label feature — everything else works without them)

## Install

From PyPI (editor + MCP server, with commands on your PATH):

```bash
py -m pip install mapview-editor
```

Or from a source checkout:

```bash
py -m pip install -r requirements.txt
```

## Usage

```bash
mapview-editor
```

(From a source checkout: `py mapview_editor/server.py` or `py -m mapview_editor`.)

Open http://localhost:5111 and drop a `.mvdb` file onto the page.

### Workflow

1. Export a `.mvdb` from SensorView (Admin > MapView > Export)
2. Load it into MapView Editor
3. Edit maps — consolidate sectors, reposition devices, redraw zones, replace images
4. Click **Export .mvdb** to download the modified archive
5. Import back into SensorView (Admin > MapView > Import)

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1` | Select tool |
| `2` | Move device tool |
| `3` | Add device tool |
| `4` | Draw zone tool |
| `5` | Edit zone tool |
| `F` | Fit map to view |
| `Del` / `Backspace` | Delete selected item |
| `Esc` | Deselect |
| `Ctrl+S` | Save current map |
| `Ctrl+F` | Search devices across all maps |

## MCP integration (let Claude build drawings)

The package includes a [Model Context Protocol](https://modelcontextprotocol.io) server
(`mapview-editor-mcp`, registry name `io.github.scrimillspaugh/mapview-editor`) that
gives an AI assistant editing tools: start the editor, list/read maps, add/move/remove
device markers, draw and delete zones, search devices across maps, rename / reorder /
sort the navigation tree, load files, and export. It drives the running editor server, and the browser UI live-syncs — you watch
the drawing build in real time. If you have unsaved manual edits, the sync warns
instead of overwriting them.

Register with Claude Code:

```bash
claude mcp add mapview -- mapview-editor-mcp
```

(For Claude Desktop, add the same command under `mcpServers` in its config. From a
source checkout, use `py mapview_editor/mcp_server.py` instead.) The editor doesn't
need to be running first — the `start_editor` tool launches it.

All MCP tools speak image coordinates — x right, y down, matching the floorplan PNG —
and the server handles the zone y-flip internally. Placing a marker positions an existing
SensorView device; it never creates devices in SensorView itself.

## .mvdb format

See [METHOD.md](docs/METHOD.md) for the full format and edit-pipeline writeup. In short, a `.mvdb` is a 7-zip archive containing:

- `mapinfo` — JSON index listing all maps (file key, building group, floor name)
- `mapNNNN.json` — per-map JSON with device positions (hex ID + x/y) and zone polygons (WKT POLYGON coordinates)
- `mapNNNN.png` — floorplan background images

## Build a standalone .exe (for PCs without Python)

```
py -m pip install pyinstaller
py -m PyInstaller --clean --onefile --name "MapViewEditor-v$(py -c 'import mapview_editor.server as s; print(s.__version__)')" --add-data "mapview_editor/static;static" --add-data "mapview_editor/templates;templates" exe_entry.py
```

Output: `dist/MapViewEditor-v<version>.exe` — for example `MapViewEditor-v1.0.1.exe`.
Double-clicking it starts the server and opens the browser. The UI assets are
bundled; no extra installs needed for map editing. Only the optional
database-label feature uses the Access Database Engine (a system component that
is never bundled) — without it, loading a database shows a friendly message and
everything else works normally.

The version is read from `__version__` rather than typed, so the filename can never
drift from the build. (The `$(...)` form works in both PowerShell and bash.)

Two rules worth keeping:

- **The version belongs in the filename**, so a download in someone's Downloads
  folder identifies itself without being run. Never ship a bare `MapViewEditor.exe`.
- **Always pass `--clean`.** Otherwise PyInstaller reuses the `build/` cache, stops
  at `checking EXE`, and exits 0 having produced an unchanged binary. Confirm a
  real build by running the exe and reading back the version it reports.

## License

MIT — see the repository root [LICENSE](../LICENSE).

<!-- MCP registry ownership marker -->
mcpName: io.github.scrimillspaugh/mapview-editor
