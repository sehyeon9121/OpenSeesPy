# NOT shipped - real PEER records kept for local reference/testing only

65 PEER NGA-West2 acceleration records (`.AT2`, PEER strong-motion format),
covering 13 events (Chi-Chi, Duzce, Friuli, Hector Mine, Imperial Valley,
Kobe, Kocaeli, Landers, Loma Prieta, Manjil, Northridge, San Fernando,
Superstition Hills). Filenames are the original PEER `RSN####_EVENT_STATION-COMPONENT`
names and are globally unique, so they double as `GroundMotionRecord.record_id`.

**This directory is deliberately outside `pyproject.toml`'s `package-data`
globs (which only cover `infrastructure/ground_motions/data/*.AT2`) and
outside `BuiltInGroundMotionCatalog`'s own scan directory** - moved here
2026-08-18 because this project's actual redistribution rights to PEER's
NGA-West2 database were never confirmed (PEER's terms require an account/
membership and don't state a redistribution policy either way; see the
project's own notes on this decision). The shipped Built-in catalog now uses
8 self-authored synthetic records instead - see `../data/README.md`.

These 65 files stay here for local development/testing (a handful of
existing tests deliberately exercise a *real*, non-synthetic record, e.g.
`RSN1116_KOBE_SHI-UP.AT2`) and are **not** cleared for redistribution to
anyone else. Two things are still open and deliberately deferred, not
resolved by this move alone:

1. These files are already committed in this repository's git history on a
   public GitHub remote (as of the commit that first added them) - moving
   them in the working tree does not remove them from history. Purging them
   from history (or making the repository private) is a separate decision,
   intentionally not made yet.
2. If PEER's terms turn out to permit redistribution after checking (see
   `../data/README.md`'s sibling notes), these could move back to being
   shipped again.

Only the acceleration series is kept - PEER's companion `.DT2`/`.VT2`
(integrated displacement/velocity) files were dropped since time-history
analysis only needs the acceleration record and its `DT`. Source: PEER
Ground Motion Database (https://ngawest2.berkeley.edu).
