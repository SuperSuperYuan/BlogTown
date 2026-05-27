from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from blogtown.models import Post
from blogtown.storage import PostStore

ROOT = Path(__file__).resolve().parent.parent
STORE = PostStore(ROOT / "data" / "posts.json")


def render_page(posts: list[Post]) -> bytes:
    articles = "\n".join(
        f"""
        <article>
          <h2>{escape(post.title)}</h2>
          <time>{escape(post.created_at)}</time>
          <p>{escape(post.body)}</p>
        </article>
        """
        for post in posts
    )

    if not articles:
        articles = "<p class=\"empty\">No posts yet. Publish the first one below.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BlogTown</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #1f2933; background: #f7f5ef; }}
    header {{ background: #264653; color: white; padding: 32px max(24px, 8vw); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 28px 24px 48px; }}
    h1 {{ margin: 0; font-size: 36px; letter-spacing: 0; }}
    form {{ display: grid; gap: 12px; margin: 0 0 28px; padding: 20px; background: white; border: 1px solid #d9d4c8; border-radius: 8px; }}
    label {{ display: grid; gap: 6px; font-weight: 700; }}
    input, textarea {{ font: inherit; padding: 10px 12px; border: 1px solid #b8b2a6; border-radius: 6px; }}
    textarea {{ min-height: 120px; resize: vertical; }}
    button {{ width: fit-content; border: 0; border-radius: 6px; padding: 10px 16px; background: #2a9d8f; color: white; font-weight: 700; cursor: pointer; }}
    article {{ padding: 20px 0; border-top: 1px solid #d9d4c8; }}
    article h2 {{ margin: 0 0 6px; }}
    time, .empty {{ color: #667085; }}
  </style>
</head>
<body>
  <header>
    <h1>BlogTown</h1>
    <p>A tiny local blog starter powered by the Python standard library.</p>
  </header>
  <main>
    <form method="post" action="/posts">
      <label>Slug <input name="slug" placeholder="hello-world" required></label>
      <label>Title <input name="title" placeholder="Hello BlogTown" required></label>
      <label>Body <textarea name="body" required></textarea></label>
      <button type="submit">Publish</button>
    </form>
    {articles}
  </main>
</body>
</html>""".encode()


class BlogTownHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path != "/":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render_page(STORE.list_posts()))

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/posts":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode()
        form = parse_qs(payload)

        post = Post.create(
            slug=form.get("slug", [""])[0].strip(),
            title=form.get("title", [""])[0].strip(),
            body=form.get("body", [""])[0].strip(),
        )
        STORE.save_post(post)

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), BlogTownHandler)
    print("BlogTown is running at http://127.0.0.1:8000")
    server.serve_forever()
