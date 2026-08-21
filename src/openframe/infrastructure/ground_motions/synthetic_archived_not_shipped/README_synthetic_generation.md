# Archived synthetic ground-motion records (not shipped)

**No longer the built-in catalog as of 2026-08-21** - real PEER records are
shipped in `../data/` again (see that folder's README). These 8 synthetic
records are kept here only for reference; they are outside
`pyproject.toml`'s `package-data` globs and outside
`BuiltInGroundMotionCatalog`'s scan directory, so they are not bundled into
any build.

8 synthetic accelerograms (`SYN01.AT2`-`SYN08.AT2`) - not observed earthquake
records. Each is independently generated to statistically match one real PEER
NGA-West2 record's engineering characteristics (response spectrum, PGA, PGV,
Arias intensity, 5-95% effective duration), without copying that record's
own acceleration time series - `max_normalized_cross_correlation` against its
reference in `validation_summary.csv` stays low (0.10-0.41) precisely to
confirm this isn't just a relabeled copy. There is no third-party data
redistribution question for these 8 files: no original sample is reused, only
statistical targets derived from a real record are used as generation goals.

| id | characteristic | calibration reference |
|----|-----------------|------------------------|
| SYN01 | short-duration broadband impulsive | PEER RSN125 (Friuli) |
| SYN02 | strong short-period velocity pulse | PEER RSN1602 (Duzce) |
| SYN03 | medium-period velocity pulse, reverse-fault | PEER RSN767 (Loma Prieta) |
| SYN04 | near-fault long-period large pulse | PEER RSN879 (Landers) |
| SYN05 | short-duration reverse-fault high-intensity | PEER RSN953 (Northridge) |
| SYN06 | soft-soil, very long duration | PEER RSN169 (Imperial Valley) |
| SYN07 | long-duration long-period reverse-fault | PEER RSN1244 (Chi-Chi) |
| SYN08 | long-duration high-energy rock-site | PEER RSN1633 (Manjil) |

`validation_summary.csv` (kept alongside the generation script, not in this
package-data directory) has the full quantitative comparison: target vs
generated PGA/PGV/Arias intensity/duration, spectral log-RMSE, and the
cross-correlation check above, per record.

These briefly replaced the 65 real PEER NGA-West2 records in `../data/`
(2026-08-18 to 2026-08-21) after `../data/`'s redistribution terms were
flagged as unconfirmed. That tradeoff was reconsidered in favor of shipping
the real records again - see `../data/README.md`.

Format, parsing, and everything else about how these are read is unchanged -
still plain PEER-style `.AT2` (see `peer_format.py`): a 4-line header, then
whitespace-separated values wrapped across lines. The header's title line
reads "SYNTHETIC GROUND MOTION - NOT AN OBSERVED EARTHQUAKE RECORD" so this
is unmistakable even from the raw file itself.
