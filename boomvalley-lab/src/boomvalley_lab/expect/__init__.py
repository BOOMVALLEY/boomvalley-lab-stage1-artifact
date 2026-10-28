"""Per-cell evidence expectations: ONE engine, several families. Phase 1/5/6.

Execution expectations (R39), artifact-provenance rules (R40) and derivation
expectations (R43) share declaration, coverage, lookup, canonicalisation and
verdict mechanics; they differ only in what is expected, what is observed and
which preconditions apply. Phase 0 fixes the family interface so the three
cannot evolve as separate copies again; no family is implemented yet.

Depends on `core`, `declare`, `identity`. Must never import `runtime`.
"""
