"""pytest configuration.

Loads scripts/03_aggregate.py under the name `aggregate` so tests can just
`import aggregate`. The file starts with a digit, which Python won't accept
as a normal module name, so we go through importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

_agg_spec = importlib.util.spec_from_file_location("aggregate", SCRIPTS / "03_aggregate.py")
_aggregate = importlib.util.module_from_spec(_agg_spec)
sys.modules["aggregate"] = _aggregate
_agg_spec.loader.exec_module(_aggregate)

_rev_spec = importlib.util.spec_from_file_location("revenue", SCRIPTS / "04_revenue_at_risk.py")
_revenue = importlib.util.module_from_spec(_rev_spec)
sys.modules["revenue"] = _revenue
_rev_spec.loader.exec_module(_revenue)
