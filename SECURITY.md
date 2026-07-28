# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/scriMillspaugh/sensorview-toolkit/security/advisories/new)
rather than opening a public issue.

Expect an acknowledgement within a couple of weeks. This is a small,
independently maintained utility, not a commercial product with an on-call
rotation — please set expectations accordingly.

## Never attach a real export to an issue

**A SensorView `.svdb` backup contains a `Users` table with hashed passwords.**
Both `.svdb` and `.mvdb` files also describe your building layout, device
network, and controller topology.

Do not attach real export files to issues, pull requests, or discussions, and
do not paste real device IDs, labels, IP addresses, or building identifiers.
If reproducing a bug needs a sample, describe the structure or build a small
file with invented data.

## What these tools do and do not do

Both tools bind to `127.0.0.1` and process everything on the local machine.
Neither transmits your files anywhere, contacts a remote service, or performs
any network I/O beyond serving the local browser UI. There is no telemetry, no
analytics, and no auto-update.

Your input file is never modified. Every operation extracts to a temporary
directory, edits there, and writes a new output file.

## Supported versions

Only the latest release of each tool receives fixes:

| Tool | Supported |
|---|---|
| Label Editor | latest release only |
| MapView Editor | latest release only |

## Executables are unsigned

The published `.exe` files are built with PyInstaller and are **not** code
signed, so Windows SmartScreen will warn on first run. That warning is expected.

Because they are unsigned, verify what you are running: download only from the
[Releases page](https://github.com/scriMillspaugh/sensorview-toolkit/releases)
of this repository, and check that the filename carries the version you expect
(`LabelEditor-vX.Y.Z.exe`). If you would rather not run an unsigned binary, run
from source instead — see each tool's README.
