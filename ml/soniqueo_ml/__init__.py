"""SONIQUEO offline data pipelines, recommendation models and evaluation (ADR-008).

The pipelines reuse the backend's data layer (ORM models, settings, catalogue rules), never its
API or request handling (ADR-012). Make the backend package importable when running from a checkout.
"""

import os
import sys
from pathlib import Path

# The API caps every statement (DB_STATEMENT_TIMEOUT_MS); batch pipelines legitimately run long
# bulk statements, so they run without that cap unless one is set explicitly.
os.environ.setdefault("DB_STATEMENT_TIMEOUT_MS", "0")

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND_DIR.is_dir() and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

__version__ = "0.1.0"
