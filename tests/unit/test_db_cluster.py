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
