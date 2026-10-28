"""Execution: scheduler, executor, sessions and the run lock. Phase 2+.

Owner decision (frozen R8): ONE ACTIVE SESSION PER RUN. A run may have several
sequential sessions (resume is in MVP), never two simultaneously active
writers. A session that tries to acquire an already active run fails closed.
Distributed or concurrent execution is out of MVP.

Writes evidence through `journal`, `store`, `custody`, `lineage`; decides
nothing about eligibility. `declare`, `identity` and `verify` must never import
this package.
"""
