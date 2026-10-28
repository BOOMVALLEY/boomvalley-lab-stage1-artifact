"""BOOMVALLEY-lab — the clean MVP product.

BOOMVALLEY-lab creates and verifies audit-ready evidence for synthetic
experiments; FULLMT independently audits that evidence. This package is the
clean build specified by `docs/BOOMVALLEY/V2_LAB/MVP_REQUIREMENTS_FREEZE.md`
and `CLEAN_IMPLEMENTATION_PLAN.md`.

It is deliberately a separate namespace from `boomvalley`, which is the frozen
research instrument (and, for this product, an executable specification and
regression oracle). Nothing here imports `boomvalley`; a test enforces it.

Phase 0: package skeleton, canonicalisation, identity core, shared declaration
primitives and dependency boundaries. No execution behaviour yet.
"""

from boomvalley_lab.core.versions import PACKAGE_VERSION as __version__

__all__ = ["__version__"]
