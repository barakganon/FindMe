# FindMe — Project Configuration & Mandates

## Core Configuration
- **Project Structure**: FastAPI backend (async), React frontend (Vite/TS), PostgreSQL+pgvector.
- **AI Integration**: Gemini 2.5 Flash for chat (intent/response), and embeddings (text-embedding-004) for semantic product search.

## Architectural Mandates
- **Categories**: Use `buyme_categories` (JSONB list) for multi-category support. `buyme_category` is deprecated legacy.
- **Search Strategy**: Hybrid approach combining semantic `pgvector` similarity (`<=>`) and SQL keyword `ILIKE`.
- **User Personalization**: 
  - Logged-in users' preferences and history are injected into the LLM context.
  - Inferred attributes are extracted asynchronously and never block chat responses.
- **Data Quality**: 
  - Deduplication via pgvector embeddings (threshold > 0.99).
  - All store product scrapes must populate `image_url` and `image_url_updated_at`.
- **Deployment**: Standard static SPA (S3/CloudFront) + containerized backend (EC2/ECS).

## Maintenance Rules
- **Migrations:** Keep Alembic head synced with `db/models.py`.
- **Rate Limiting:** Use SlowAPI (200/min).
- **Git:** Work on branches. Commits must be verified against model state.