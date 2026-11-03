# Changes

Versions are the installer's (`LuXcale-<version>-setup.exe`).
Every saved result's `settings.json` records the `app_version` that made it.

## 1.0.4 — 2026-11-03

### Quantification
- **Tilt per band area:** each band area (row of boxes) can lean on its own, on top of the blot's
  tilt, for a strip that lies crooked; it is measured on the raw image turned once by both angles
  - "Area tilt" box and "Level" in ③, or drag the round handle at the right end of the picked
    area: the row turns about its own middle
- **Auto-detect:** finds the lanes when band widths differ from lane to lane, and no longer loses
  a very strong (saturated) lane

### Screen
- **Drag and drop:** drop TIF files or a folder anywhere on the window to open them; the empty
  blot list shows a "+" with "drop blot TIFs here, or click to open"
- **Wheel:** number boxes and pickers change with the mouse wheel only after you click them;
  otherwise the wheel scrolls the panel
- **Band area names** sit above the boxes, clear of the rotate handle

## 1.0.3 — 2026-11-02

### Quantification
- **Background correction changed:** the background under each band is the lower convex hull of the
  lane's brightness profile, replacing the straight line between the band area's two ends
  - Measured values are never negative
  - Smaller error when a band area's edge touches a neighbouring band (synthetic check: 41% → 11%)
  - The background method is recorded in each result; results saved by earlier versions re-run with
    their original method and give the same numbers

### Screen
- **Default brightness:** the whole raw range (0–65,535); "Auto" stretches the contrast,
  "Original" brings back the whole range
- **Brightness histogram:** the blot's values with two handles, dragged to set the screen range;
  the number boxes follow
- **Figure contrast separated:** ⑥ figure strips use their own automatic contrast, independent of the
  screen; "Same as screen" applies the current screen brightness
- **Language button** moved to the top right

### Updates
- **New-version notice:** at start the installed program asks GitHub for the latest release; when
  there is a newer one a "New version … – download" button appears at the top. It downloads the
  installer, checks its size and SHA-256, and starts it (your settings and results stay). Nothing
  about you or your blots is sent; without internet nothing is shown

### Size marks (kDa)
- **Editing changed:** the "Click to mark" button is removed; marks are edited on the blot
  - Ctrl+click: add a mark and type its kDa
  - Drag: move / right-click: delete / double-click: change its kDa

## 1.0.2 — 2026-11-02

### Quantification
- **Blot tilt:** a tilted blot is levelled before measuring (angle, auto level, two points);
  saturated pixels stay flagged
- **Auto-detect:** fits the lanes' positions and widths to the bands
- **Lane boxes per band area:** each band area of a blot can have its own lane boxes
- **Settings check:** split rows out of order in a saved settings file are refused instead of measured

### Screen
- **Layout:** steps ①–⑥ in working order, plain words, number boxes never squeezed;
  a band area takes a band count instead of split-row numbers
- **Close all:** starts a new project (blots, experiments, lane table and results cleared; files untouched)
- **Bar names:** the graph points to the "Lane name" column; double-click the graph to go there

## 1.0.1 — 2026-10-30

- First lab release: Windows installer without administrator rights, Korean by default
