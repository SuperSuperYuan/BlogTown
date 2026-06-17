from aishelf.db import cluster


def test_choose_k_small_corpus_is_single_cluster():
    assert cluster.choose_k(0) == 1
    assert cluster.choose_k(2) == 1


def test_choose_k_floor_and_ceiling():
    assert cluster.choose_k(3) == 3          # round(sqrt(1)) = 1 -> floored to 3
    assert cluster.choose_k(100) == 6        # round(sqrt(33.3)) = 6
    assert cluster.choose_k(1000) == 8       # round(sqrt(333)) = 18 -> capped at 8


def test_color_for_cycles_palette():
    assert cluster.color_for(0) == cluster.PALETTE[0]
    assert cluster.color_for(len(cluster.PALETTE)) == cluster.PALETTE[0]
    assert len({cluster.color_for(i) for i in range(len(cluster.PALETTE))}) == len(cluster.PALETTE)


import numpy as np


def test_kmeans_single_cluster_labels_all_zero():
    mat = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    labels = cluster.kmeans(mat, 1, seed=1)
    assert list(labels) == [0, 0, 0]


def test_kmeans_separates_two_groups():
    mat = np.array([[1.0, 0.0], [0.99, 0.1], [-1.0, 0.0], [-0.99, 0.1]], dtype=np.float32)
    labels = cluster.kmeans(mat, 2, seed=7)
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]


def test_kmeans_is_deterministic():
    mat = np.array([[1.0, 0.0], [0.2, 0.9], [-1.0, 0.1], [0.1, -1.0]], dtype=np.float32)
    a = cluster.kmeans(mat, 2, seed=42)
    b = cluster.kmeans(mat, 2, seed=42)
    assert list(a) == list(b)


def test_kmeans_clamps_k_to_n():
    mat = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    labels = cluster.kmeans(mat, 5, seed=1)
    assert len(labels) == 2 and set(int(x) for x in labels) <= {0, 1}
