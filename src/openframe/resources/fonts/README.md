# Bundled fonts

Two variable-weight `.ttf` files, registered at app startup via
`QFontDatabase.addApplicationFont()` in
[`theme.py`](../../app/shell/theme.py) so every install renders identically
regardless of what happens to already be on that machine - the previous
approach picked a family from the ones already installed system-wide
(`"Noto Sans"`/`"Segoe UI"`/`"Malgun Gothic"` for UI text, `"JetBrains
Mono"`/`"Consolas"` for monospace numeric/code text), which silently
differed across machines whenever the preferred family wasn't present.

| file | family | used for | license |
|------|--------|----------|---------|
| `NotoSansKR[wght].ttf` | Noto Sans KR | general UI text (Korean + Latin) | OFL 1.1 |
| `JetBrainsMono[wght].ttf` | JetBrains Mono | monospace numeric/code text | OFL 1.1 |

Both are pulled as-is from Google's official open-source fonts repository
(`google/fonts`, `ofl/notosanskr` and `ofl/jetbrainsmono`), unmodified.
Full license text for each is in `OFL_NotoSansKR.txt` / `OFL_JetBrainsMono.txt`
in this directory - the SIL Open Font License explicitly permits
redistribution and embedding in software, so there is no redistribution-
rights question here (unlike the ground-motion data - see
`../../infrastructure/ground_motions/data/README.md`).
