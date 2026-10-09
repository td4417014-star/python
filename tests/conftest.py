import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def synth_root(tmp_path_factory):
    """Small synthetic BTCUSD store: 2023-12-20 .. 2024-01-06 (ticks + bars + spec)."""
    from ubt.data.synthetic import build_store
    root = tmp_path_factory.mktemp("data")
    build_store(str(root), "BTCUSD", "2023-12-20", "2024-01-06", seed=11, mean_dt=6.0)
    return str(root)
