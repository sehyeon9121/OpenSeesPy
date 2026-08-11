# Built-in ground-motion records

65 PEER NGA-West2 acceleration records (`.AT2`, PEER strong-motion format),
covering 13 events (Chi-Chi, Duzce, Friuli, Hector Mine, Imperial Valley,
Kobe, Kocaeli, Landers, Loma Prieta, Manjil, Northridge, San Fernando,
Superstition Hills). Filenames are the original PEER `RSN####_EVENT_STATION-COMPONENT`
names and are globally unique, so they double as `GroundMotionRecord.record_id`.

Only the acceleration series is kept - PEER's companion `.DT2`/`.VT2`
(integrated displacement/velocity) files were dropped since time-history
analysis only needs the acceleration record and its `DT`.

Event, station, component, units, NPTS and DT are not stored separately -
`infrastructure/ground_motions/peer_format.py` parses them straight out of
each file's own 4-line PEER header, so this directory is the only source of
truth. Source: PEER Ground Motion Database (https://ngawest2.berkeley.edu).
