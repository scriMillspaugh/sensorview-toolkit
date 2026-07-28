# Floorplan Image Standard

Guidelines for floorplan images used in `.mvdb` MapView archives, based on analysis of a real export (42 images, 40.1 MB).

## One map = one floor

Each floor gets its own map entry. Don't stitch multiple sectors into a single combined image (some legacy exports do this — e.g. `LEVEL 07- SECTOR 1-3`) — it inflates file size for no benefit once every floor has its own page, and makes device/zone coordinates harder to reason about.

## Format: PNG, 8-bit indexed color

Floorplan exports are flat-color line art — walls, room fills, a background tint. They are **not photographs** and don't need photographic color depth.

- Save as **PNG** (required by MapView; no other format is supported by SensorView import)
- Use **8-bit indexed/palette color** (PNG color type 3), not 24-bit RGB truecolor

**Why this matters:** every image sampled from a real export already used ≤256 unique colors, but was saved as 24-bit RGB (3 bytes/pixel) instead of indexed (1 byte/pixel). Re-encoding as indexed is **pixel-for-pixel lossless** — no visual difference — and cut file size to **~42% of the original** across every sample tested (38–47% range). For the full 40 MB set, that's roughly **40 MB → 17 MB** with zero quality tradeoff.

If your source drawing has more than 256 colors (gradients, photo textures, anti-aliased renders), indexing would introduce visible banding — check with an image tool before converting, or leave it as RGB.

## Compression

Use PNG `optimize=True` with max compression level (`compress_level=9` in Pillow, or equivalent). This is free — same pixels, smaller file, no visual change. Marginal on top of the indexed-color win above, but costs nothing.

## Dimensions

No hard ceiling, but as a sanity check: a single floor plan rarely needs to exceed ~5000 px on its long edge for on-screen editing and zoom. If a floor image is dramatically larger than its neighbors, check whether it accidentally includes a stitched multi-sector composite (see "One map = one floor" above).

## How MapView Editor applies this

`server.py`'s `/api/export` endpoint automatically re-encodes every floorplan PNG to indexed color (when it's losslessly possible) at export time. You don't need to pre-process images — load, edit, and export; the optimization happens on the way out. The export toast reports the before/after size so you can see the savings.

If an image already exceeds 256 colors or optimization would produce a larger file, the original bytes are kept untouched.
