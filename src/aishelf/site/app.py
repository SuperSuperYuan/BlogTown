"""FastAPI app for the display site: server-rendered video + blog pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import logging
import os
import random
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict, replace

from aishelf.contract.loader import load_items
from aishelf.db import graph as db_graph
from aishelf.db import search as db_search
from aishelf.db import sync as db_sync
from aishelf.db.config import default_db_path
from aishelf.site import (
    allowlist,
    ask,
    collide,
    collect,
    critique,
    hermes,
    items,
    learn,
    llm,
    markdown,
    mirror,
    notes,
    notedraft,
    path,
    posts,
    schedule_state,
    scheduler,
    schedules,
    timeline,
    views,
)
from aishelf.site import digest as digest_mod
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


def _hooks_for(items):
    """Map {id: hook} for the given items, tolerating a missing/locked derived
    DB (the hook is a derived nicety — never break a page render)."""
    try:
        return db_search.hooks_for(
            default_db_path(get_data_dir()), [it.id for it in items]
        )
    except Exception:  # derived view; never fatal
        return {}


def _collide_ref(it) -> dict:
    return {"id": it.id, "type": it.type, "title": it.title, "author": it.author}


def _profile_payload(profile) -> dict:
    """Compact, escapable fact strip for the /mirror page (mirrors _collide_ref)."""
    return {
        "galaxies": [{"name": g.name, "color": g.color, "size": g.size}
                     for g in profile.galaxies],
        "total": profile.total, "videos": profile.videos, "blogs": profile.blogs,
        "span_days": profile.span_days,
        "top_author": profile.top_authors[0][0] if profile.top_authors else "",
    }


def _item_dict(it) -> dict:
    return {"title": it.title, "summary": it.summary, "keywords": it.keywords,
            "author": it.author, "type": it.type}


def _item_detail(it, note: str) -> dict:
    """JSON detail for the /graph node panel: contract fields the graph payload
    omits, plus the user's note rendered to sanitized HTML."""
    return {
        "id": it.id, "type": it.type, "title": it.title, "author": it.author,
        "published_at": it.published_at, "summary": it.summary,
        "keywords": list(it.keywords),
        "note_html": markdown.render_markdown(note),
    }


def _resolve_pair(items, space, *, a_id, b_id, lock_id, rng):
    """Resolve a (item_a, item_b) pair from explicit ids, else a surprising pick
    (with random fallback). Returns None when no pair can be formed."""
    by_id = {it.id: it for it in items}
    if a_id and b_id and a_id != b_id:
        pair = (a_id, b_id)
    else:
        ids, matrix, meta = space
        pair = collide.pick_pair(ids, matrix, meta, lock_id=lock_id, rng=rng)
        if pair is None:
            pair = collide.random_pair(list(by_id), lock_id=lock_id, rng=rng)
    if pair is None:
        return None
    a, b = by_id.get(pair[0]), by_id.get(pair[1])
    if a is None or b is None:
        return None
    return (a, b)


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
    hooks = _hooks_for(items)            # one call; superset map reused below
    vids = views.videos(items)[:HOME_PREVIEW]
    blogs = views.blogs(items)[:HOME_PREVIEW]
    daily = digest_mod.build_digest(items, hooks, today=date.today().isoformat())
    return templates.TemplateResponse(
        request,
        "home.html",
        {"videos": vids, "blogs": blogs, "hooks": hooks, "digest": daily},
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
    page_obj = views.paginate(result, page, VIDEOS_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "videos.html",
        {"page": page_obj, "keyword": keyword, "q": q, "hooks": _hooks_for(page_obj.items)},
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
    page_obj = views.paginate(result, page, BLOGS_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "blogs.html",
        {"page": page_obj, "keyword": keyword, "q": q, "hooks": _hooks_for(page_obj.items)},
    )


@app.get("/videos/{item_id}", response_class=HTMLResponse)
def video_detail(request: Request, item_id: str):
    item = next((it for it in views.videos(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    note = _note_for(item)
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {"item": item, "section_url": "/videos", "note": note,
         "note_html": markdown.render_markdown(note)},
    )


@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    body_html = (
        markdown.render_markdown(item.body or "")
        if getattr(item, "origin", "collected") == "self"
        else None
    )
    note = _note_for(item)
    return templates.TemplateResponse(
        request,
        "blog_detail.html",
        {"item": item, "section_url": "/blogs", "note": note,
         "note_html": markdown.render_markdown(note), "body_html": body_html},
    )


@app.get("/write", response_class=HTMLResponse)
def write_new_page(request: Request):
    return templates.TemplateResponse(request, "write.html", {"item": None})


@app.get("/write/{item_id}", response_class=HTMLResponse)
def write_edit_page(request: Request, item_id: str):
    item = posts.read_post(item_id)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "write.html", {"item": item})


@app.post("/posts")
def create_post_route(request: Request, title: str = Form(""), body: str = Form("")):
    if not title.strip() or not body.strip():
        return templates.TemplateResponse(
            request, "write.html",
            {"item": None, "error": "标题和正文都不能为空", "title": title, "body": body},
            status_code=400,
        )
    item = posts.create_post(title.strip(), body)
    _sync_db_async(get_data_dir())  # make it searchable / graphed off-thread
    return RedirectResponse(f"/blogs/{item.id}", status_code=303)


class _PreviewRequest(BaseModel):
    body: str = Field(default="", max_length=200_000)


@app.post("/posts/preview")
def preview_post(req: _PreviewRequest):
    # Same server-side renderer as the published page → byte-identical preview.
    return {"html": markdown.render_markdown(req.body)}


@app.post("/posts/{item_id}")
def update_post_route(request: Request, item_id: str, title: str = Form(""), body: str = Form("")):
    if not title.strip() or not body.strip():
        existing = posts.read_post(item_id)
        if existing is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request, "write.html",
            {"item": existing, "error": "标题和正文都不能为空", "title": title, "body": body},
            status_code=400,
        )
    try:
        item = posts.update_post(item_id, title.strip(), body)
    except LookupError:
        raise HTTPException(status_code=404)
    _sync_db_async(get_data_dir())
    return RedirectResponse(f"/blogs/{item.id}", status_code=303)


@app.get("/authors/{key}", response_class=HTMLResponse)
def author_page(request: Request, key: str):
    mine = views.by_author(_items(), key)
    if not mine:
        raise HTTPException(status_code=404)
    vids = views.videos(mine)
    blogs = views.blogs(mine)
    return templates.TemplateResponse(
        request,
        "author.html",
        {"key": key, "videos": vids, "blogs": blogs, "hooks": _hooks_for(vids + blogs)},
    )


@app.get("/keyword/{kw}", response_class=HTMLResponse)
def keyword_page(request: Request, kw: str):
    mine = views.by_keyword(_items(), kw)
    if not mine:
        raise HTTPException(status_code=404)
    vids = views.videos(mine)
    blogs = views.blogs(mine)
    return templates.TemplateResponse(
        request,
        "keyword.html",
        {"kw": kw, "videos": vids, "blogs": blogs, "hooks": _hooks_for(vids + blogs)},
    )


@app.get("/keywords", response_class=HTMLResponse)
def keywords_page(request: Request):
    tags = views.keyword_counts(_items())
    max_count = max((c for _, c in tags), default=1)
    return templates.TemplateResponse(
        request, "keywords.html", {"tags": tags, "max_count": max_count}
    )


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    data = timeline.load_timeline(default_db_path(get_data_dir()))
    return templates.TemplateResponse(request, "timeline.html", {"data": data})


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


class _CollideRequest(BaseModel):
    a_id: str | None = None
    b_id: str | None = None
    lock_id: str | None = None


class _PathRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class _LearnRequest(BaseModel):
    cluster_id: int


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


@app.get("/collide", response_class=HTMLResponse)
def collide_page(request: Request):
    return templates.TemplateResponse(request, "collide.html", {})


@app.post("/collide/chat")
def collide_chat(req: _CollideRequest):
    # Ungated: synthesis is cheap (like /ask), not the costly Hermes path.
    data_dir = get_data_dir()
    items = _items()
    space = collide.load_pair_space(default_db_path(data_dir))
    pair = _resolve_pair(items, space, a_id=req.a_id, b_id=req.b_id,
                         lock_id=req.lock_id, rng=random.Random())

    def _gen():
        if pair is None:
            yield hermes.sse({"error": "先去采集一些内容再来碰撞"})
            yield hermes.sse({"done": True})
            return
        a, b = pair
        yield hermes.sse({"pair": {"a": _collide_ref(a), "b": _collide_ref(b)}})
        yield from llm.stream_completion(collide.build_messages(_item_dict(a), _item_dict(b)))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/mirror", response_class=HTMLResponse)
def mirror_page(request: Request):
    return templates.TemplateResponse(request, "mirror.html", {})


@app.post("/mirror/chat")
def mirror_chat():
    # Ungated: synthesis is cheap (like /ask and /collide), not the Hermes path.
    profile = mirror.load_profile(default_db_path(get_data_dir()))

    def _gen():
        if profile is None:
            yield hermes.sse({"error": "先采集一些内容并同步图谱，才能照镜子"})
            yield hermes.sse({"done": True})
            return
        yield hermes.sse({"profile": _profile_payload(profile)})
        yield from llm.stream_completion(mirror.build_messages(profile))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/learn", response_class=HTMLResponse)
def learn_page(request: Request):
    galaxies = learn.load_galaxies(default_db_path(get_data_dir()))
    galaxies_json = [
        {"id": g.id, "items": [{"id": it.id, "title": it.title, "type": it.type}
                               for it in g.items]}
        for g in galaxies
    ]
    return templates.TemplateResponse(
        request, "learn.html", {"galaxies": galaxies, "galaxies_json": galaxies_json}
    )


@app.post("/learn/route")
def learn_route(req: _LearnRequest):
    # Ungated: synthesis is cheap (like /ask, /collide, /mirror), not the Hermes path.
    galaxies = learn.load_galaxies(default_db_path(get_data_dir()))
    galaxy = next((g for g in galaxies if g.id == req.cluster_id), None)

    def _gen():
        if galaxy is None or not galaxy.items:
            yield hermes.sse({"error": "这个星系还没有内容"})
            yield hermes.sse({"done": True})
            return
        yield hermes.sse({"galaxy": {"id": galaxy.id, "name": galaxy.name}})
        item_dicts = [{"id": it.id, "title": it.title, "summary": it.summary, "type": it.type}
                      for it in galaxy.items]
        yield from llm.stream_completion(learn.build_messages(galaxy.name, item_dicts))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request):
    return templates.TemplateResponse(request, "graph.html", {})


@app.get("/api/graph")
def api_graph():
    """Read-only semantic graph (nodes + top-K-capped edges) over the derived DB."""
    return db_graph.load_graph(default_db_path(get_data_dir()))


@app.post("/graph/path")
def graph_path(req: _PathRequest):
    # Ungated: explanation is cheap (like /ask and /collide), not the Hermes path.
    if len(req.ids) < 2:
        raise HTTPException(status_code=400, detail="需要至少两个节点")
    hits = db_search.get_by_ids(default_db_path(get_data_dir()), req.ids)
    ordered = [hits[i] for i in req.ids if i in hits]   # preserve client path order

    def _gen():
        if len(ordered) < 2:
            yield hermes.sse({"error": "这条路径上的内容找不到了"})
            yield hermes.sse({"done": True})
            return
        items_ = [{"title": h.title, "summary": h.summary, "author": h.author, "type": h.type}
                  for h in ordered]
        yield from llm.stream_completion(path.build_messages(items_))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/api/item/{id}")
def api_item(id: str):
    """Read-only per-item detail for the /graph node panel. 404 on unknown or
    path-unsafe id; ungated like the rest of browsing."""
    try:
        items.safe_id(id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == id), None)
    if it is None:
        raise HTTPException(status_code=404)
    return _item_detail(it, _note_for(it))


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
    return {"ok": True, "updated_at": updated_at, "html": markdown.render_markdown(req.text)}


@app.post("/notes/{item_id}/draft")
def note_draft(item_id: str):
    # Ungated: drafting is cheap (like /ask, /collide, /mirror), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    existing = _note_for(it)

    def _gen():
        yield from llm.stream_completion(notedraft.build_messages(_item_dict(it), existing))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.post("/critique/{item_id}")
def critique_route(item_id: str):
    # Ungated: critique is cheap (like /ask, /collide, /notes/{id}/draft), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    note = _note_for(it)

    def _gen():
        yield from llm.stream_completion(critique.build_messages(_item_dict(it), note))

    return StreamingResponse(_gen(), media_type="text/event-stream")


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
