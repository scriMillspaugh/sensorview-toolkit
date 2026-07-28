# Method: editing nLight MapView floorplans via an .mvdb export

This documents how the MapView Editor takes apart, edits, and rebuilds a
SensorView **MapView export** (`.mvdb`) — for anyone who wants to understand
the file format or reproduce the process. It is the companion to
[`label-editor/docs/METHOD.md`](../../label-editor/docs/METHOD.md), which covers the `.svdb`
database backup.

## 1. The file format

A MapView **`.mvdb` export is a 7-zip archive** (same container trick as the
`.svdb`) holding three kinds of members:

| Member | What it is |
|---|---|
| `mapinfo` | JSON index of all maps: `{"version": 1, "maps": [{"file": "map0001", "type": 1, "group": "<building group>", "name": "<floor name>"}, ...]}` |
| `mapNNNN.json` | Per-map data: image dimensions, view settings, device markers, zone polygons |
| `mapNNNN.png` | The floorplan background image for that map |

Map file keys are sequential (`map0001`, `map0002`, …). Adding a map means
appending a `mapinfo` entry with the next free number and creating the matching
`.json` (and optionally `.png`).

### Per-map JSON structure

```json
{
  "width": 4000, "height": 3000,
  "zoomLevels": 9, "resolutionMin": 80, "resolutionMax": 800, "deviceScale": 20,
  "devices": [ { "id": "0268FD18", "x": 1234.5, "y": 987.6 } ],
  "zones":   [ { "id": 42, "ParentDeviceID": "0268FD18", "Port": 1,
                 "coords": "POLYGON((100 2900, 400 2900, 400 2600, 100 2600))" } ],
  "subzones": []
}
```

- **Devices** are hex-ID markers with an x/y position. The `id` joins to
  `Devices.DeviceID` in the `.svdb` database — this is the link between the two
  tools: the Label Editor renames a device, MapView shows where it lives.
- **Zones** are polygons in WKT (`POLYGON((x y, x y, ...))`) with an owning
  parent device (typically a bridge) and port.

### ⚠ The coordinate-system trap

Device x/y and the PNG share a **y-down** coordinate space (origin top-left,
standard image coordinates). Zone polygon WKT, however, is stored **y-up**
(origin bottom-left, standard geometry convention). Render both as-is and every
zone appears vertically mirrored against its floorplan.

The fix: flip zone y across the map height (`y' = height − y`) when reading,
and flip back when writing. The flip is its own inverse, so a round-trip is
lossless. If you build your own tooling against `.mvdb` files, this is the
mistake you'll make first.

## 2. The pipeline

```
export.mvdb ──7z extract──► mapinfo + mapNNNN.json/.png ──edit JSON──► repack ──► export_edited.mvdb
      │                                                                              │
      └────────────────────────── original never modified ───────────────────────────┘
```

1. **Extract** to a temp working directory (`py7zr`).
2. **Edit** — everything is plain JSON: move/add/remove device markers, rewrite
   zone polygons, rename/add/delete `mapinfo` entries, swap a map's PNG.
3. **Repackage** a new 7-zip from the members referenced by `mapinfo` (JSON +
   PNG per map, plus `mapinfo` itself). Writing from the index — rather than
   sweeping the temp folder — keeps stray files out of the archive.
4. **Never touch the original.** The edited archive downloads under a new name.

## 3. Floorplan image optimization (free ~55–60% size cut)

Floorplan exports are flat-color line art, but SensorView saves them as 24-bit
RGB PNGs. Nearly all of them use ≤256 unique colors, so re-encoding as 8-bit
indexed PNG is **pixel-for-pixel lossless** and cuts the file to roughly 40% of
its original size — on a real 42-image export, ~40 MB → ~17 MB with zero visual
change.

The editor applies this automatically on export, with guards:
- already-indexed images pass through untouched;
- images with more than 256 colors are left as-is (indexing would band);
- if the "optimized" bytes come out larger, the original bytes are kept.

Details and image guidelines: [`FLOORPLAN_STANDARD.md`](FLOORPLAN_STANDARD.md)
(one map per floor, no stitched multi-sector composites, PNG only).

## 4. Round-tripping with SensorView

1. **Export:** SensorView → Admin → MapView → **Export** → `.mvdb`
2. Edit in MapView Editor (load, edit maps, **Export .mvdb**)
3. **Import:** SensorView → Admin → MapView → **Import** the edited file

Keep the original export until the import is verified. Device markers only
display devices that exist in SensorView's database — placing a marker doesn't
create a device, it just positions one.

## 5. What the editor automates

`server.py` wraps the pipeline (extract, JSON persistence, safe repack, PNG
optimization); `static/editor.js` provides the browser canvas — pan/zoom
(SVG overlay on the floorplan), tools for select/move/add devices, draw and
reshape zone polygons with vertex handles, a properties panel for IDs, parents,
and ports, and the y-flip handling described above. Everything runs on
localhost; map data describes your building layout, so exports shouldn't be
uploaded to third-party services.
