# Bundled certificate fonts

All fonts shipped here are licensed under the **SIL Open Font License 1.1**
(redistribution permitted). Each family's full licence + copyright is in the
matching `OFL-*.txt` file in this directory.

| Family (id) | Files | Licence |
|---|---|---|
| Liberation Serif / Sans / Mono (`serif`, `sans`, `mono`) | `Liberation*.ttf` | `OFL-Liberation.txt` |
| Noto Serif Display (`display`) | `NotoSerifDisplay-*.ttf` | `OFL-NotoSerifDisplay.txt` |
| Lato (`lato`) | `Lato-*.ttf` | `OFL-Lato.txt` |
| Fira Code (`code`) | `FiraCode-*.ttf` | `OFL-FiraCode.txt` |
| Rajdhani (`rajdhani`) | `Rajdhani-*.ttf` | `OFL-Rajdhani.txt` |
| Orbitron (`orbitron`) | `Orbitron-Regular.ttf`, `Orbitron-Bold.ttf` | `OFL-Orbitron.txt` |

**Orbitron** upstream ships a variable font (`Orbitron[wght].ttf`); the static
`Regular` (wght 400) and `Bold` (wght 700) instances bundled here were generated
with `fonttools varLib.instancer` (a build-time step only — `fonttools` is not a
runtime dependency).

The renderer loads these files directly (`ImageFont.truetype`) and the editor
loads the *same bytes* over `@font-face`, so the preview matches the download
(ADR-0027 parity).
