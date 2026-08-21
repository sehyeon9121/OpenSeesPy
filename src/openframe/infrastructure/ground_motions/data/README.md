# Built-in ground-motion records

65 real PEER NGA-West2 acceleration records (`.AT2`, PEER strong-motion
format), covering 13 events (Chi-Chi, Duzce, Friuli, Hector Mine, Imperial
Valley, Kobe, Kocaeli, Landers, Loma Prieta, Manjil, Northridge, San
Fernando, Superstition Hills). Filenames are the original PEER
`RSN####_EVENT_STATION-COMPONENT` names and are globally unique, so they
double as `GroundMotionRecord.record_id`.

This is what actually ships in a built package (`pyproject.toml`'s
`package-data` globs `data/*.AT2`).

Only the acceleration series is kept - PEER's companion `.DT2`/`.VT2`
(integrated displacement/velocity) files were dropped since time-history
analysis only needs the acceleration record and its `DT`. Source: PEER
Ground Motion Database (https://ngawest2.berkeley.edu).

**Redistribution note:** PEER's terms of use require an account/membership
and don't state an explicit redistribution policy either way, so shipping
these real records (in a public repo/installer) carries some residual
copyright risk that was consciously accepted here. This directory
previously held 8 statistically-calibrated synthetic records instead (moved
to `../synthetic_archived_not_shipped/` when that decision was reverted, see
that folder's README for why they were tried and dropped).
