import sys
import os

_ROOT = os.path.dirname(__file__)

# Make top-level packages (core, irides_core, irides_cli, api, worker, mcp) importable from tests
for subpath in ("", "core", "cli", "api", "worker", "mcp"):
    candidate = os.path.join(_ROOT, subpath) if subpath else _ROOT
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
