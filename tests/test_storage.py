import tempfile
import unittest
from pathlib import Path

from blogtown.models import Post
from blogtown.storage import PostStore


class PostStoreTest(unittest.TestCase):
    def test_save_and_list_posts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PostStore(Path(tmpdir) / "posts.json")
            post = Post.create("hello", "Hello", "First post")

            store.save_post(post)

            self.assertEqual(store.list_posts(), [post])


if __name__ == "__main__":
    unittest.main()
