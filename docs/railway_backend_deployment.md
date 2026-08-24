# Railway Backend Deployment

This project can run on Railway as a FastAPI backend with a persistent Railway volume mounted at `/data`.

## Railway Service

1. Create a Railway project from the GitHub repository.
2. Add a volume and mount it at `/data`.
3. Configure the service start command through the included `Procfile`:
   `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`
4. Set the required environment variables:
   - `OPENAI_API_KEY`: OpenAI API key for retrieval/generation and Admin publish embeddings.
   - `AI_MENTOR_DATA_DIR`: `/data`
5. Optionally set `FRONTEND_ORIGIN` when a separate frontend is hosted elsewhere, for example on Vercel. Use the exact frontend origin and do not include a trailing path.

## Persistent Runtime Data

When `AI_MENTOR_DATA_DIR=/data`, these runtime paths are stored on the Railway volume:

- `/data/ai_mentor.db`
- `/data/uploads`
- `/data/prepared`
- `/data/admin_chroma`
- `/data/published_configs`
- `/data/human_review_results.json`

When `AI_MENTOR_DATA_DIR` is not set, local development continues to use the existing repository-local runtime paths.

## Health Checks

Railway can use:

- `GET /health`

The existing API health endpoint also remains available:

- `GET /api/health`

Both return a lightweight JSON response and do not run retrieval, embeddings, ChromaDB, or document preparation.

## Frontend Configuration

The bundled static frontend still works with same-origin API calls when served by FastAPI.

For a separately hosted frontend, set `window.AI_MENTOR_API_BASE` before loading `app.js`, for example:

```html
<script>
  window.AI_MENTOR_API_BASE = "https://your-railway-service.up.railway.app";
</script>
```

Also set `FRONTEND_ORIGIN` on Railway to the exact frontend origin so browser CORS requests are allowed.

## Operational Limitations

- Upload size remains limited by the application to 50 MB.
- Document preparation and Admin publish run synchronously in V1 and may take time for larger documents.
- Admin publish requires `OPENAI_API_KEY` because it creates embeddings.
- Do not commit or upload private course source documents to GitHub. Upload them through the Admin workflow into the persistent Railway volume.
