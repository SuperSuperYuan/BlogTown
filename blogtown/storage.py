import json
from pathlib import Path

from blogtown.models import Post


class PostStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_posts(self) -> list[Post]:
        if not self.path.exists():
            return []

        with self.path.open(encoding="utf-8") as file:
            raw_posts = json.load(file)

        return [Post.from_dict(item) for item in raw_posts]

    def save_post(self, post: Post) -> None:
        posts = [item for item in self.list_posts() if item.slug != post.slug]
        posts.append(post)
        posts.sort(key=lambda item: item.created_at, reverse=True)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([item.to_dict() for item in posts], file, indent=2)
            file.write("\n")
