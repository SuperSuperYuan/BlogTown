"""Semantic clustering over stored embeddings (主题星系).

Pure helpers (choose_k / kmeans / representatives / color_for) plus one thin DB
writer (recompute_clusters), mirroring the graph.py / collide.py split. numpy
k-means on L2-normalized vectors (cosine clustering); no sklearn. Clusters are a
rebuildable derived view written at sync time.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from aishelf.db import graph

CLUSTER_SEED = 1234

# Fixed palette; cluster colour is PALETTE[id % len] so re-syncs stay stable.
PALETTE = [
    "#ff9a3c", "#4cc2ff", "#38e1c0", "#c08cff",
    "#ff6b9d", "#ffd166", "#7ee787", "#8ab4ff",
]


def choose_k(n: int) -> int:
    """How many galaxies for n embedded items: clamp(round(sqrt(n/3)), 3, 8),
    degrading to a single cluster below 3 items."""
    if n < 3:
        return 1
    return max(3, min(8, round(math.sqrt(n / 3))))


def color_for(cluster_id: int) -> str:
    return PALETTE[cluster_id % len(PALETTE)]
