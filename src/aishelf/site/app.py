"""FastAPI app for the display site: server-rendered video + blog pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aishelf.contract.loader import load_items
from aishelf.site import views
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


templates.env.filters["duration"] = _fmt_duration

app = FastAPI(title="aishelf")
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
        request, "video_detail.html", {"item": item, "section_url": "/videos"}
    )


@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "blog_detail.html", {"item": item, "section_url": "/blogs"}
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
