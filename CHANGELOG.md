# Changes

Versions are the installer's (`LuXcale-<version>-setup.exe`).
Every saved result's `settings.json` records the `app_version` that made it.

## 1.0.3 — 2026-11-02

- Measured values can no longer be negative: the background under each band is now the lowest line
  that stays under the lane's brightness profile (its lower convex hull), instead of a straight line
  between the band area's two ends. When an end touches another band the old line could sit above
  the signal. Numbers change a little (most bands under 1%; very faint bands come out slightly
  higher, so ratios against a very faint control group can drop). Results saved by earlier versions
  still re-run to the numbers they had
- The screen opens a blot with its whole raw range (0–65,535), as a picture viewer shows it;
  "Auto" still stretches the contrast. Figure strips keep their own automatic contrast
- Size marks (kDa) without a button: Ctrl+click a ladder band to add a mark and type its kDa;
  drag a mark to move it, right-click to delete it, double-click to change its kDa
- The language button is at the top right

## 1.0.2 — 2026-11-02

- Level a tilted blot before measuring (angle, auto level, two points); saturated pixels stay flagged
- Auto-detect fits the lanes' positions and widths to the bands
- Each band area of a blot can have its own lane boxes; dragging moves only that area's boxes
- The graph says where its bar names are changed (the "Lane name" column); double-click the graph to go there
- "Close all" starts a new project (blots, experiments, lane table and results cleared; files untouched)
- Split rows out of order in a saved settings file are refused instead of measured
- Clearer screen: plain words, steps ①–⑥ in working order, number boxes never squeezed;
  a band area takes a band count instead of split-row numbers

## 1.0.1 — 2026-10-30

- First lab release: Windows installer without administrator rights, Korean by default
