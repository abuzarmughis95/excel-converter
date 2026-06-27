"""Ledgerline accounting engine.

The canonical double-entry accounting core. Pure, deterministic, and
dependency-free so it runs identically in the FastAPI backend and the Electron
Python sidecar. Correctness here is non-negotiable — exercised by a golden
test-vector suite that is a required CI gate.
"""

__version__ = "0.0.0"
