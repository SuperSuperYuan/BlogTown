"""FastAPI app for the display site: server-rendered video + blog pages."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict, replace

from aishelf.contract.loader import load_items
from aishelf.db import search as db_search
from aishelf.db import sync as db_sync
from aishelf.db.config import default_db_path
from aishelf.site import (
    allowlist,
    ask,
    collect,
    hermes,
    items,
    llm,
    notes,
    schedule_state,
    scheduler,
    schedules,
    views,
)
from aishelf.site.config import get_data_dir

logger = logging.getLogger(__name__)


def _require_collect_token(token: str | None) -> None:
    """Gate the costly Hermes paths (collect + schedule mutations) on the
    passcode allowlist. Raises 403 when the token isn't allowlisted."""
    if not allowlist.is_allowed(token):
        if not allowlist.load_tokens():
            logger.warning(
                "采集白名单为空或缺失：在 config/collect_allowlist.txt（或 "
                "AISHELF_COLLECT_ALLOWLIST 指向的文件）添加口令后才能采集"
            )
        raise HTTPException(status_code=403, detail="采集口令无效，请联系管理员加入白名单")

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

VIDEOS_PER_PAGE = 12
BLOGS_PER_PAGE = 5
SEARCH_PER_PAGE = 20
HOME_PREVIEW = 8
SEARCH_API_PER_PAGE = 20


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def _safe_url(url) -> str:
    """Allow only absolute http(s) URLs from scraped data.

    Blanks javascript:/data: schemes, scheme-relative `//host` URLs, and bare
    scheme-less values — anything that isn't an explicit http/https URL.
    """
    if not url:
        return ""
    candidate = str(url).strip()
    return candidate if urlsplit(candidate).scheme.lower() in ("http", "https") else ""


def _note_for(item) -> str:
    """An item's note, tolerating a record whose id is not path-safe (-> no note)."""
    try:
        return notes.load_note(item.id)
    except ValueError:
        return ""


templates.env.filters["duration"] = _fmt_duration
templates.env.filters["safe_url"] = _safe_url

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Start the timed-collection scheduler only when explicitly enabled, so the
    # test client (which doesn't set the flag) never spawns a background thread.
    stop = None
    if os.environ.get("AISHELF_SCHEDULER_ENABLED"):
        stop = scheduler.start()
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="Atlas", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _items():
    return load_items(get_data_dir())


def _sync_db_async(data_dir) -> None:
    """Refresh the derived DB off the request thread (it's a recoverable view)."""
    def _bg():
        try:
            db_sync.sync(data_dir, default_db_path(data_dir))
        except Exception as exc:  # derived DB; never surface to the caller
            logger.warning("background DB sync failed: %s", exc)
    threading.Thread(target=_bg, name="aishelf-db-sync", daemon=True).start()


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
        {"item": item, "section_url": "/videos", "note": _note_for(item)},
    )


@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "blog_detail.html",
        {"item": item, "section_url": "/blogs", "note": _note_for(item)},
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
def collect_page(request: Request, q: str = ""):
    return templates.TemplateResponse(
        request,
        "collect.html",
        {
            "schedules": schedules.load_schedules(),
            "last_run": schedule_state.load_state(get_data_dir()),
            "prefill": q,
        },
    )


@app.post("/collect/chat")
def collect_chat(req: _ChatRequest, x_collect_token: str | None = Header(default=None)):
    # Gate the expensive collection path: only allowlisted tokens may proceed.
    _require_collect_token(x_collect_token)
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    data_dir = get_data_dir()
    system = {"role": "system", "content": collect.build_collection_instructions(data_dir)}
    payload = [system] + [m.model_dump() for m in req.messages]
    stream = hermes.stream_chat(payload)

    def _with_sync():
        try:
            yield from stream
        finally:
            # Hermes wrote files during the turn; refresh the derived DB.
            _sync_db_async(data_dir)

    return StreamingResponse(_with_sync(), media_type="text/event-stream")


@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request):
    return templates.TemplateResponse(request, "ask.html", {})


@app.post("/ask/chat")
def ask_chat(req: _ChatRequest):
    # Ungated: answering is cheap relative to collection and is core "reading" use.
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    data_dir = get_data_dir()
    messages = [m.model_dump() for m in req.messages]
    question = ask.latest_user_question(messages)
    sources = ask.retrieve(default_db_path(data_dir), question)
    payload = ask.build_messages(messages, sources)

    def _gen():
        # Emit the sources first so the client can render the panel immediately.
        yield hermes.sse({"sources": ask.source_refs(sources)})
        # Low confidence (empty / loose match) takes precedence: guide to collect
        # and suppress jump-cards. Otherwise, surface navigation jump-cards.
        if ask.is_low_confidence(question, sources):
            yield hermes.sse({"collect": {"q": question}})
        else:
            candidates = ask.nav_candidates(sources, ask.nav_types(question))
            if candidates:
                yield hermes.sse({"jump": ask.nav_refs(candidates)})
        yield from llm.stream_completion(payload)

    return StreamingResponse(_gen(), media_type="text/event-stream")


class _ScheduleRequest(BaseModel):
    name: str
    time: str
    prompt: str
    enabled: bool = True


@app.post("/schedules")
def add_schedule(req: _ScheduleRequest, x_collect_token: str | None = Header(default=None)):
    # Creating a schedule recurs collection on the Hermes budget — same gate.
    _require_collect_token(x_collect_token)
    try:
        name = items.safe_id(req.name)
    except ValueError:
        raise HTTPException(status_code=400, detail="名称只能包含字母、数字、点、短横线、下划线")
    try:
        hour, minute = schedules._parse_time(req.time)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="时间格式应为 HH:MM")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="采集需求不能为空")
    new = schedules.Schedule(name=name, hour=hour, minute=minute, prompt=req.prompt, enabled=req.enabled)
    current = schedules.load_schedules()
    merged, replaced = [], False
    for s in current:  # upsert by name, preserving position when editing
        if s.name == name:
            merged.append(new)
            replaced = True
        else:
            merged.append(s)
    if not replaced:
        merged.append(new)
    schedules.save_schedules(merged)
    return {"ok": True}


@app.post("/schedules/{name}/toggle")
def toggle_schedule(name: str, x_collect_token: str | None = Header(default=None)):
    _require_collect_token(x_collect_token)
    current = schedules.load_schedules()
    merged, found = [], False
    for s in current:
        if s.name == name:
            merged.append(replace(s, enabled=not s.enabled))
            found = True
        else:
            merged.append(s)
    if not found:
        raise HTTPException(status_code=404, detail="未找到该定时任务")
    schedules.save_schedules(merged)
    return {"ok": True}


@app.post("/schedules/{name}/delete")
def delete_schedule(name: str, x_collect_token: str | None = Header(default=None)):
    _require_collect_token(x_collect_token)
    current = schedules.load_schedules()
    merged = [s for s in current if s.name != name]
    if len(merged) == len(current):
        raise HTTPException(status_code=404, detail="未找到该定时任务")
    schedules.save_schedules(merged)
    return {"ok": True}


class _NoteRequest(BaseModel):
    text: str = Field(max_length=100_000)


@app.post("/notes/{item_id}")
def save_note_route(item_id: str, req: _NoteRequest):
    try:
        updated_at = notes.save_note(item_id, req.text)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid note id")
    # The note text feeds search; refresh the derived index off-thread.
    _sync_db_async(get_data_dir())
    return {"ok": True, "updated_at": updated_at}


@app.post("/delete/{item_id}")
def delete_item_route(item_id: str):
    try:
        removed = items.delete_item(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid id")
    if not removed:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


@app.get("/api/search")
def api_search(q: str = "", type: str | None = None, page: int = 1):
    """Read-only full-text search over the derived DB (first consumption feature)."""
    if type not in (None, "video", "blog"):
        raise HTTPException(status_code=400, detail="type 只能是 video 或 blog")
    data_dir = get_data_dir()
    offset = max(0, page - 1) * SEARCH_API_PER_PAGE
    hits = db_search.search(
        default_db_path(data_dir), q, type=type, limit=SEARCH_API_PER_PAGE, offset=offset
    )
    return {"q": q, "type": type, "page": page, "results": [asdict(h) for h in hits]}
