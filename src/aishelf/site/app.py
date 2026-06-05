"""FastAPI app for the display site: server-rendered video + blog pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from aishelf.contract.loader import load_items
from aishelf.site import collect, hermes, notes, views
from aishelf.site.config import get_data_dir

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

VIDEOS_PER_PAGE = 24
BLOGS_PER_PAGE = 20
SEARCH_PER_PAGE = 20
HOME_PREVIEW = 8


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def _safe_url(url) -> str:
    """Blank out non-http(s) URLs so scraped data can't inject javascript:/data: links."""
    if not url:
        return ""
    scheme = str(url).split(":", 1)[0].strip().lower() if ":" in str(url) else ""
    if scheme and scheme not in ("http", "https"):
        return ""
    return str(url)


templates.env.filters["duration"] = _fmt_duration
templates.env.filters["safe_url"] = _safe_url

app = FastAPI(title="Atlas")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _items():
    return load_items(get_data_dir())


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    items = _items()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "videos": views.videos(items)[:HOME_PREVIEW],
            "blogs": views.blogs(items)[:HOME_PREVIEW],
        },
    )


@app.get("/videos", response_class=HTMLResponse)
def videos_page(request: Request, page: int = 1, keyword: str = "", q: str = ""):
    items = _items()
    if q:
        result = views.videos(views.search(items, q))
    elif keyword:
        result = views.by_keyword(views.videos(items), keyword)
    else:
        result = views.videos(items)
    return templates.TemplateResponse(
        request,
        "videos.html",
        {"page": views.paginate(result, page, VIDEOS_PER_PAGE), "keyword": keyword, "q": q},
    )


@app.get("/blogs", response_class=HTMLResponse)
def blogs_page(request: Request, page: int = 1, keyword: str = "", q: str = ""):
    items = _items()
    if q:
        result = views.blogs(views.search(items, q))
    elif keyword:
        result = views.by_keyword(views.blogs(items), keyword)
    else:
        result = views.blogs(items)
    return templates.TemplateResponse(
        request,
        "blogs.html",
        {"page": views.paginate(result, page, BLOGS_PER_PAGE), "keyword": keyword, "q": q},
    )


@app.get("/videos/{item_id}", response_class=HTMLResponse)
def video_detail(request: Request, item_id: str):
    item = next((it for it in views.videos(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {"item": item, "section_url": "/videos", "note": notes.load_note(item.id)},
    )


@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "blog_detail.html",
        {"item": item, "section_url": "/blogs", "note": notes.load_note(item.id)},
    )


@app.get("/authors/{key}", response_class=HTMLResponse)
def author_page(request: Request, key: str):
    mine = views.by_author(_items(), key)
    if not mine:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "author.html",
        {"key": key, "videos": views.videos(mine), "blogs": views.blogs(mine)},
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", page: int = 1):
    results = views.search(_items(), q)
    page_obj = views.paginate(results, page, SEARCH_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "q": q,
            "page": page_obj,
            "videos": views.videos(page_obj.items),
            "blogs": views.blogs(page_obj.items),
        },
    )


class _Message(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    messages: list[_Message]


@app.get("/collect", response_class=HTMLResponse)
def collect_page(request: Request):
    return templates.TemplateResponse(request, "collect.html", {})


@app.post("/collect/chat")
def collect_chat(req: _ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    system = {"role": "system", "content": collect.build_collection_instructions(get_data_dir())}
    payload = [system] + [m.model_dump() for m in req.messages]
    return StreamingResponse(hermes.stream_chat(payload), media_type="text/event-stream")


class _NoteRequest(BaseModel):
    text: str = Field(max_length=100_000)


@app.post("/notes/{item_id}")
def save_note_route(item_id: str, req: _NoteRequest):
    try:
        updated_at = notes.save_note(item_id, req.text)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid note id")
    return {"ok": True, "updated_at": updated_at}
