# BuyMe Smart Search — Build Status

## What Was Built

### Layer 1 — Data Ingestion (`scraper/`)
| File | Status | Notes |
|---|---|---|
| `base.py` | Done | `BaseScraper` ABC + `ProductItem` + `ScraperResult` Pydantic models |
| `buyme_store_scraper.py` | Done | Full Playwright scraper for buyme.co.il store list; infinite-scroll, detail page enrichment, raw HTML archive, JSON output |
| `shopify_detector.py` | Done | Probes `/products.json`; paginates with tenacity retry; maps variants → `ProductItem` |
| `per_store_scraper.py` | Done | Generic fallback scraper: sitemap discovery → Playwright page render → JSON-LD + microdata extraction |
| `scheduler.py` | Done | Celery tasks: `scrape_buyme_store_list` (daily), `scrape_store_products` (weekly), `detect_price_changes` (placeholder); beat schedule configured |
| `stores/__init__.py` | Done | Package marker |
| `stores/ksp.py` | Done | `KSPScraper` — KSP.co.il sitemap → product URLs → Playwright scrape → JSON-LD + CSS extraction |
| `stores/ivory.py` | Done | `IvoryScraper` — ivory.co.il sitemap → product URLs → Playwright scrape → CSS extraction |

### Layer 2 — AI Normalization (`normalization/`)
| File | Status | Notes |
|---|---|---|
| `name_normalizer.py` | Done | Claude Haiku via instructor → `NormalizedName` (canonical_name, brand, model, language, confidence) |
| `category_classifier.py` | Done | Claude Haiku + full 9-top-level taxonomy injected into system prompt → `ClassifiedCategory` |
| `spec_extractor.py` | Done | Claude Haiku + Hebrew keyword glossary → `ExtractedSpecs` (brand, model, color, size, storage_gb, etc.) |
| `pipeline.py` | Done | `NormalizationPipeline` wires all three; runs concurrently with `asyncio.gather`; outputs `NormalizedProduct` |
| `deduplication.py` | Done | `EmbeddingClient` (OpenAI text-embedding-3-small), `cosine_similarity`, `DeduplicationEngine` — finds duplicates across stores via embedding cosine similarity (threshold 0.92) |

### Layer 3 — Database (`db/`)
| File | Status | Notes |
|---|---|---|
| `models.py` | Done | Full SQLAlchemy async ORM: `Store`, `Product`, `StoreProduct`, `ScrapeRun`; UUID PKs; `BaseMixin` |
| `vector_index.py` | Done | `EmbeddingService` (OpenAI), `VectorIndex` — enable pgvector extension, upsert embeddings, Python-side cosine similarity search (pre-pgvector fallback), `reindex_all_products` |
| `migrations/` | Placeholder | `.gitkeep` present — run `alembic init db/migrations` to initialize Alembic |

### Layer 4 — Search & Matching
Implemented as text `ilike` search in `api/routes/search.py`. Vector search via `VectorIndex.search_similar()` is ready to wire in.

### Layer 5 — API (`api/`)
| File | Status | Notes |
|---|---|---|
| `schemas.py` | Done | All Pydantic v2 request/response models |
| `dependencies.py` | Done | `Settings` (pydantic-settings), `get_db()`, `get_anthropic_client()` |
| `main.py` | Done | FastAPI app, CORS, `/health`, routers |
| `routes/search.py` | Done | `POST /search` — URL fetch → Claude extraction → ilike DB search → filters → response |
| `routes/stores.py` | Done | `GET /stores` — paginated, filterable by city/category/online |

### Tests (`tests/`)
| File | Status | Notes |
|---|---|---|
| `conftest.py` | Done | `anyio_backend` fixture + mock `anthropic_client` |
| `scraper/test_shopify_detector.py` | Done | Tests `detect_shopify()` returns False on network error |
| `normalization/test_name_normalizer.py` | Done | Tests `NormalizedName` model construction |
| `api/test_health.py` | Done | Tests `GET /health` returns 200 via ASGI transport |

### Infrastructure
| File | Status | Notes |
|---|---|---|
| `main.py` (root) | Done | uvicorn entry point; reads `APP_HOST`, `APP_PORT`, `APP_ENV` |
| `requirements.txt` | Done | All 15 dependencies pinned |
| `.env.example` | Done | All env var keys documented |
| `CLAUDE.md` | Done | Full architecture reference |
| `frontend/` | Stubs | React component stubs only — not yet implemented |

---

## What's Missing / Next Steps

### Immediate (Week 1–2 per timeline)
1. **Initialize Alembic** — `alembic init db/migrations` + write the initial migration for all 4 tables
2. **pgvector setup** — enable extension in Postgres; write Alembic migration to ALTER `products.embedding_vector` from `TEXT` to `vector(1536)`; create IVFFlat index
3. **Run BuyMe store scraper** — execute `python -m scraper.buyme_store_scraper` to seed the `stores` table with real data
4. **`.env` file** — copy `.env.example` → `.env` and fill in `DATABASE_URL` + `ANTHROPIC_API_KEY` + `OPENAI_API_KEY`

### Short Term (Week 3–6)
5. **Per-store scrapers** — validate KSP and Ivory CSS selectors against live sites; add Bug, Hamashbir, etc.
6. **Celery scheduler** — implement `detect_price_changes` task; run `celery worker` + `celery beat`
7. **Frontend** — implement React components in `frontend/src/`
8. **More tests** — expand test coverage for normalization pipeline and API routes

### Medium Term (Week 7–8)
9. **Replace `ilike` search** with pgvector cosine similarity via `VectorIndex.search_similar()` in `api/routes/search.py` (TODO comment already in place)
10. **PostGIS distance filtering** — replace Euclidean approximation in `_build_store_info()` with `ST_Distance`
11. **Similar product search** — RAG + Claude explanation of differences

---

## How to Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set up environment
cp .env.example .env
# edit .env — set DATABASE_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY

# 3. Start PostgreSQL (needs pgvector extension)
# docker run -e POSTGRES_PASSWORD=pass -p 5432:5432 pgvector/pgvector:pg16

# 4. Run migrations (once Alembic is set up)
# alembic init db/migrations
# alembic upgrade head

# 5. Seed stores
python -m scraper.buyme_store_scraper

# 6. Start API
python main.py
# → API available at http://localhost:8000
# → Docs at http://localhost:8000/docs

# 7. (Optional) Start Celery worker + beat
# celery -A scraper.scheduler.celery_app worker --loglevel=info
# celery -A scraper.scheduler.celery_app beat --loglevel=info
```
