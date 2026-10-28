"""The eligibility gate: every step yields a core.verdict.Finding. Phase 3+.

Reads evidence; never writes it; never imports `runtime` or adapters. A
declared claim that cannot be checked is VIOLATED.
"""
