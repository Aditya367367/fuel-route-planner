import threading
from dataclasses import dataclass

import numpy as np

from stations.models import Station

_lock = threading.Lock()
_index = None


@dataclass
class StationIndex:
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray
    rows: list  # same order as the arrays, for building responses


def get_store():
    """Load stations into memory on first use. Restart the server after re-running load_stations."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _load()
    return _index


def reset_store():
    global _index
    _index = None


def _load():
    rows = list(
        Station.objects.exclude(latitude=None).exclude(longitude=None).values(
            "name", "address", "city", "state", "price", "latitude", "longitude"
        )
    )
    return StationIndex(
        lat=np.array([r["latitude"] for r in rows], dtype=float),
        lon=np.array([r["longitude"] for r in rows], dtype=float),
        price=np.array([r["price"] for r in rows], dtype=float),
        rows=rows,
    )
