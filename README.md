# aishelf

AI video content aggregator. Three modules:

- **M1 Scraper** — pulls videos from YouTube and Bilibili by author + date range, saves metadata/thumbnails/transcripts to disk.
- **M2 Understanding** — uses LLMs to extract structured topics from transcripts (planned).
- **M3 Web** — browse aggregated content by person/topic (planned).

## Quick start (M1)

```bash
pip install -e ".[dev]"
cp config/authors.example.yaml config/authors.yaml
# edit config/authors.yaml to your accounts
export OPENAI_API_KEY=...    # required only if any videos lack platform CC
python -m aishelf.scraper validate-config
python -m aishelf.scraper run --since 2026-01-01
```

Output lands in `data/<platform>/<account>/<video_id>/`.

## Tests

```bash
pytest                # default — skips network tests
pytest -m ""          # include live smoke tests
```

## Docs

- M1 design spec: `docs/superpowers/specs/2026-05-28-m1-scraper-design.md`
- M1 implementation plan: `docs/superpowers/plans/2026-05-28-m1-scraper.md`
