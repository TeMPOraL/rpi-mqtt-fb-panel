# Fonts for the virtual panel

The panel's layout geometry (`BAR_HEIGHT` and everything derived from it) is
computed from the title font's glyph metrics, so **fidelity with the device
requires the exact same font file the device uses**.

## Getting the LCARS font (Swiss 911 Ultra Compressed BT)

The font is "free for personal use" and deliberately **not** distributed with
this repository (see the note in `lcars_constants.py`). Copy it from your
device once:

```sh
scp <user>@<panel-host>:/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf virtual/fonts/
```

Any file matching `virtual/fonts/Swiss-911*.ttf` is picked up automatically by
the virtual runner. It is covered by `.gitignore` and will never be committed.

## Fallback

`DejaVuSans.ttf` is vendored here (Bitstream Vera license, see
`LICENSE-DejaVu.txt`; redistribution permitted) so the virtual panel always
runs. When it is used, the runner prints a loud warning: the UI renders fine,
but bar heights / text wrapping / touch calibration offsets differ from the
device, so **fidelity comparisons are invalid in fallback mode**.

## Resolution order (implemented in `virtual/harness.py`)

1. Explicit `LCARS_FONT_PATH` environment variable (absolute path wins).
2. `virtual/fonts/Swiss-911*.ttf` (first match).
3. Vendored `virtual/fonts/DejaVuSans.ttf` (with warning).
