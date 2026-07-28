# SensorView Toolkit

Local, browser-based utilities for working with **Acuity nLight SensorView**
export files. Everything runs on your own machine — no cloud, no accounts, and
your exports never leave the PC.

> **Unofficial community toolkit.** Not an Acuity Brands product and not
> affiliated with or endorsed by Acuity. SensorView, nLight, and MapView are
> trademarks of their respective owners. Always keep your original export
> files and review results before importing.

## The tools

| Tool | Works on | What it does |
|---|---|---|
| [**Label Editor**](label-editor/) | `.svdb` (database backup) or bare `sensor.mdb` | Batch-rename device and zone labels from a rename list (in-browser editor or CSV), edit per-device notes, validate against BACnet and SensorView limits, rebuild the backup for re-import. Includes a CLI. |
| [**MapView Editor**](mapview-editor/) | `.mvdb` (MapView export) | Edit floorplans in the browser: move/add/remove device markers, draw and reshape zone polygons, rename/add/delete maps, swap floorplan images, auto-optimize PNGs on export. |

Both follow the same pattern:

```
export from SensorView ──► edit locally ──► rebuilt file ──► import into SensorView
        (original file is never modified)
```

**Each tool's README has its own install, usage, and build instructions.** Start
there — [Label Editor](label-editor/README.md) ·
[MapView Editor](mapview-editor/README.md).

## Download (no Python needed)

Standalone Windows builds are on the
[**Releases page**](https://github.com/scriMillspaugh/sensorview-toolkit/releases).
Download the `.exe`, double-click, and the tool opens in your browser.

Each tool is versioned and released separately — tags `label-editor-vX.Y.Z` and
`mapview-editor-vX.Y.Z`, with the version in the filename
(`LabelEditor-v1.2.0.exe`). See each tool's changelog for what changed:
[Label Editor](label-editor/CHANGELOG.md) ·
[MapView Editor](mapview-editor/CHANGELOG.md).

You will also see one older `relabeler-v1.1.0` release — that is the Label Editor
under its previous name, kept for history. Use the latest release.

The exes are unsigned, so Windows SmartScreen may warn on first run — choose
**More info → Run anyway**. Everything still runs 100% locally.

> The Label Editor additionally needs the free
> [Microsoft Access Database Engine](https://www.microsoft.com/en-us/download/details.aspx?id=54920)
> (64-bit), installed once per PC. The MapView Editor needs nothing extra.

## Why local-only matters

A SensorView `.svdb` backup contains a `Users` table with **hashed passwords**,
and both file types describe your building layout and device network. These
files should never be uploaded to third-party services. Both tools bind to
localhost and do all processing on your machine.

## Reference

- [Labeling practices](label-editor/docs/LABELING.md) — what the Label Editor
  enforces (BACnet character rules, SensorView column limits, uniqueness) versus
  what it only recommends, plus a naming format that holds up in a BMS.
- [`.svdb` format and pipeline](label-editor/docs/METHOD.md)
- [`.mvdb` format and pipeline](mapview-editor/docs/METHOD.md)
- [Floorplan image guidelines](mapview-editor/docs/FLOORPLAN_STANDARD.md)

## Support

These tools are free and always will be. If they saved you an afternoon:

- **[Give to Seattle Children's](https://give.seattlechildrens.org/give/284150)** —
  to direct it at the team behind these tools, choose **Other Area of Support**
  and enter **Research Building & Engineering**. The giving form cannot be
  pre-filled from a link, so that step has to be done by hand.
- **[Buy me a coffee](https://venmo.com/u/spawahh)** — Venmo, if you would
  rather say thanks directly.

Neither is expected, and neither buys support or priority on issues.

## License

MIT — see [LICENSE](LICENSE).
