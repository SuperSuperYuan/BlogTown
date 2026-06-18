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


def test_representatives_groups_by_label_nearest_first():
    ids = ["a", "b", "c"]
    mat = np.array([[1.0, 0.0], [0.98, 0.2], [0.0, 1.0]], dtype=np.float32)
    labels = np.array([0, 0, 1])
    out = cluster.representatives(labels, mat, ids)
    assert set(out) == {0, 1}
    assert set(out[0]) == {"a", "b"}
    assert out[1] == ["c"]


def test_representatives_caps_to_m():
    ids = [f"i{n}" for n in range(10)]
    mat = np.tile(np.array([1.0, 0.0], dtype=np.float32), (10, 1))
    labels = np.zeros(10, dtype=int)
    out = cluster.representatives(labels, mat, ids, m=3)
    assert len(out[0]) == 3


from aishelf.db import schema, vector


def _seed(con, rid, vec, title=None):
    con.execute(
        "INSERT INTO items (id, type, title, author, platform, source_url, "
        "published_at, collected_at, summary, keywords, embedding, "
        "embedding_model, embedding_dim, content_hash, synced_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, "blog", title or f"标题{rid}", "作者", "p", f"https://x/{rid}",
         "2024-01-01", "2024-01-02", "s", "[]", vector.pack(vec), "m",
         len(vec), "h", "2024-01-02"),
    )


def test_recompute_assigns_clusters_and_colors(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    for rid, vec in [("a", [1.0, 0.0]), ("b", [0.98, 0.1]),
                     ("c", [-1.0, 0.0]), ("d", [-0.98, 0.1])]:
        _seed(con, rid, vec)
    need = cluster.recompute_clusters(con, seed=7)
    assert all(r["cluster"] is not None
               for r in con.execute("SELECT cluster FROM items"))
    rows = list(con.execute("SELECT id, color, signature FROM clusters"))
    assert rows and all(r["color"] in cluster.PALETTE for r in rows)
    assert need
    assert all(isinstance(t, list) for t in need.values())
    con.close()


def test_recompute_no_embeddings_clears(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    con.execute(
        "INSERT INTO items (id, type, title, author, platform, source_url, "
        "published_at, collected_at, summary, keywords, content_hash, synced_at) "
        "VALUES ('x','blog','标题','作者','p','https://x/x','2024-01-01',"
        "'2024-01-02','s','[]','h','2024-01-02')")
    con.execute("UPDATE items SET cluster = 5")
    need = cluster.recompute_clusters(con)
    assert need == {}
    assert con.execute("SELECT cluster FROM items WHERE id='x'").fetchone()["cluster"] is None
    assert con.execute("SELECT count(*) FROM clusters").fetchone()[0] == 0
    con.close()


def test_recompute_carries_name_for_unchanged_membership(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    for rid, vec in [("a", [1.0, 0.0]), ("b", [0.98, 0.1]),
                     ("c", [-1.0, 0.0]), ("d", [-0.98, 0.1])]:
        _seed(con, rid, vec)
    cluster.recompute_clusters(con, seed=7)
    con.execute("UPDATE clusters SET name = '已命名'")
    need = cluster.recompute_clusters(con, seed=7)
    assert need == {}
    assert all(r["name"] == "已命名" for r in con.execute("SELECT name FROM clusters"))
    con.close()
