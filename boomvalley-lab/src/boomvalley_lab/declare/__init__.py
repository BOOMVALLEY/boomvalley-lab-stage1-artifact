"""The experiment declaration — the domain model, usable with no runtime.

Phase 0 holds only the primitives every later section is built from:

    selector     one selector language (factor -> level constraints)
    projection   one projection: cell coordinates -> a unit key
    collection   one named-collection rule (views, mechanisms)
    sections     one table of what an absent declaration section means

Depends on `core` only. Must never import `runtime` or provider adapters.
"""
