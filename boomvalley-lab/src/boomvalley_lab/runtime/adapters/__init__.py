"""Provider and transform adapters — plugins. Phase 2+.

Adapters emit facts (what answered, what was produced); they never decide
scientific eligibility. Provider libraries may be imported only here. Nothing
in `declare`, `identity`, `verify`, `expect` or `core` may import this package.
"""
