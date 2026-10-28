"""The authoritative `bvl` lifecycle (T1-010).

`lifecycle.dispatch` is the one entry of every `bvl` command.  A `bvl-study-1`
study and the K0 run directory it opens go through the gated lifecycle
(``lifecycle.gated``): validate -> check (P09-ERF coverage + GNDCRW comparison
set + P08 strict gate-2) -> run under the CLEARED authorization only -> status
/ resume -> package (manifest-4) -> verify -> analyse (the pre-bound analysis of
a verified package).  Scientific execution has no other way into the engine.
"""
