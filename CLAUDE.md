# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**aishelf** aggregates AI-domain video content (interviews, technical talks) from multiple platforms. It is composed of three modules with stable file/DB interfaces between them:

| Module | Role | Status |
|---|---|---|
| **M1 Scraper** | Crawl YouTube + Bilibili by author + date range; output transcripts/meta/thumbnails to filesystem | In development |
| **M2 Understanding** | Use LLMs to extract structured topics/summaries from transcripts, save to DB | Planned |
| **M3 Web** | Frontend + API for browsing aggregated content | Planned |

Each module has its own spec in `docs/superpowers/specs/` and plan in `docs/superpowers/plans/`. **Implementation order is M1 → M2 → M3.**

## Commands

- Install with dev deps: `pip install -e ".[dev]"`
- Run M1: `python -m aishelf.scraper run --since YYYY-MM-DD`
- Validate config: `python -m aishelf.scraper validate-config`
- Run tests (network skipped by default): `pytest`
- Run including network smoke tests: `pytest -m ""`
- Run a single test: `pytest tests/unit/test_models.py::test_specific -v`

## Architecture

Source layout uses a `src/` directory; package is `aishelf`. M1 lives in `src/aishelf/scraper/`.

**Key design points for M1** (see spec for the full picture):

- Strategy pattern with `PlatformAdapter` Protocol in `adapters/base.py`; one implementation per platform (`youtube.py`, `bilibili.py`)
- Synchronous execution — one video at a time. Per-video failure does not block the batch.
- Output contract: `data/<platform>/<account_id>/<video_id>/{meta.json, thumb.<ext>, transcript.json}`. Failures go to `data/_failures/<platform>/<account_id>/<video_id>.json`.
- Atomic writes: write into `<final_dir>.tmp`, then `os.rename`. Existence of `meta.json` is the success signal.
- Transcripts: prefer platform CC; if missing, fetch temporary audio and call OpenAI Whisper API. Audio is deleted after transcription.
- Whisper API and yt-dlp are **always mocked in tests**. Live calls only run under the `network` pytest marker.

## Config

`config/authors.yaml` is the user-edited account list (gitignored). `config/authors.example.yaml` is committed as a template. Each entry is a single platform account; the same person on two platforms is two entries.
