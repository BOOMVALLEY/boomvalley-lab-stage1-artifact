"""Identities: one type per meaning, one digest service underneath.

    kinds        the identity taxonomy (frozen: MVP_REQUIREMENTS_FREEZE §6)
    registered   externally frozen identities the product verifies against,
                 never recomputes (e.g. a pre-registered study's schedule)

Depends on `core` (and later `declare`). Must never import `runtime` or
provider adapters.
"""
