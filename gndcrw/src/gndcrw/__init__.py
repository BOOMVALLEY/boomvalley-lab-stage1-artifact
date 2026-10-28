"""GNDCRW - checks the experiment before takeoff.

A pre-execution integrity gate: given a declaration, a target catalog, two
assembled experiment surfaces and their pair context, decide RUN / BLOCK /
UNVERIFIABLE under GNDCRW-STRICT-0.1. It never runs the experiment.
"""

__version__ = "0.2.0"
