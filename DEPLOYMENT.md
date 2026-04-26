# Deployment Guide — Dubai Real Estate Finder

## Quick Start (Local Development)

### Prerequisites
- Docker & Docker Compose
- Node.js 20+
- Python 3.12+
- ANTHROPIC_API_KEY (Claude API)

### 1. Set Environment Variables
```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 2. Start All Services
```bash
docker-compose up -d
```

This starts:
- **PostgreSQL** (port 5433) with PostGIS for geospatial queries
- **Qdrant** (port 6333) for semantic search vectors
- **Redis** (port 6380) for caching
- **Ollama** (port 11434) for local embeddings (nomic-embed-text)
- **Backend** (port 8001) FastAPI server
- **Frontend** (port 3000) Next.js application

### 3. Initialize Embeddings Model
```bash
docker exec realestate_ollama ollama pull nomic-embed-text
```

### 4. Run Database Migrations
```bash
docker exec realestate_backend uv run alembic upgrade head
```

### 5. Seed Initial Data (Optional)
```bash
docker exec realestate_backend uv run python -c "from app.services.seeder import run_seeder; run_seeder()"
```

### 6. Access Application
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8001
- **API Docs**: http://localhost:8001/docs

---

## Architecture

```
┌─────────────┐
│  Frontend   │  (Next.js on port 3000)
│  (port 3000)│
└──────┬──────┘
       │ HTTP
       ↓
┌─────────────────────┐
│  Backend (FastAPI)  │  (port 8001)
│  - Chat agent       │
│  - Property API     │
│  - Ranking engine   │
└──────┬──────────────┘
       │
   ┌───┼───┬───────┬─────────┐
   ↓   ↓   ↓       ↓         ↓
  [DB] [Redis] [Qdrant] [Ollama]
 PG+  Caching  Vectors  Embeddings
PostGIS        (nomic-embed-text)
```

### Core Components

**Backend** (`/backend`)
- FastAPI application with async support
- LangGraph agents for chat and daily digest
- Vector database integration for RAG
- Property scraping and ETL pipeline

**Frontend** (`/frontend`)
- Next.js 14 with React
- Tailwind CSS styling
- Real-time chat with properties
- Map-based property browsing

**Database** (PostgreSQL + PostGIS)
- Property listings with geospatial indexes
- User preferences and shortlists
- Area guides and POI data

**Vector Store** (Qdrant)
- Property embeddings for semantic search
- Area guide embeddings for location context
- Supports property similarity matching

**Embeddings** (Ollama + nomic-embed-text)
- Local embedding model (no external API calls)
- 768-dimensional embeddings
- ~4.5GB model size (runs on CPU or GPU)

---

## Data Flow

### Chat & RAG
```
User Question
    ↓
Intent Router (Claude Haiku)
    ├─→ property_details: fetch from DB
    ├─→ location_context: semantic search on area guides
    ├─→ nearby_comparison: spatial query for nearby listings
    ├─→ search_similar: semantic search on listings
    └─→ general_chat: pass to synthesis
    ↓
Tool Execution (fetch from DB/Qdrant)
    ↓
Synthesis (Claude Haiku)
    ↓
Response to User
```

### Backfill Images
```
Backfill Script (Playwright)
    ↓
Fetch og:image from Property Finder
    ↓
Store in DB (image_url column)
    ↓
Frontend displays via ListingCard component
```

### Daily Digest
```
Scheduled (Daily)
    ↓
Load User Preferences
    ↓
Fetch Recent Listings (24h)
    ↓
Rank by Price/Location/Value
    ↓
Fetch og:image for top listings
    ↓
Compose Email (Claude Haiku)
    ↓
Send Email
```

---

## Configuration

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Claude API access | `sk-ant-...` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@host:5432/db` |
| `QDRANT_URL` | Vector DB endpoint | `http://qdrant:6333` |
| `REDIS_URL` | Cache connection | `redis://redis:6379` |
| `OLLAMA_BASE_URL` | Embeddings API | `http://ollama:11434` |
| `OLLAMA_EMBED_MODEL` | Embedding model | `nomic-embed-text` |
| `NEXT_PUBLIC_API_URL` | Backend URL (frontend) | `http://localhost:8001` |

---

## Common Tasks

### View Logs
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f ollama
```

### Restart Services
```bash
docker-compose restart backend
docker-compose restart frontend
```

### Stop Everything
```bash
docker-compose down
```

### Remove Data (Fresh Start)
```bash
docker-compose down -v
# Then docker-compose up -d again
```

### Backfill Property Images
```bash
docker exec realestate_backend \
  uv run python scripts/backfill_images.py --limit 100
```

### Run Daily Digest
```bash
docker exec realestate_backend \
  uv run python -m app.agents.digest
```

### Access Database
```bash
docker exec -it realestate_db psql -U realestate_user -d realestate_db
```

### Access Qdrant Web UI
```
http://localhost:6333/dashboard
```

---

## Performance Tuning

### Ollama Memory
- Model runs on CPU by default
- GPU acceleration: Set `CUDA_VISIBLE_DEVICES` in docker-compose
- Typical memory: ~4.5GB for nomic-embed-text

### Database Optimization
- PostGIS spatial indexes on `location` column
- Indexes on `area_name`, `available`, `fetched_at`
- Run ANALYZE regularly: `docker exec realestate_db psql -U realestate_user -d realestate_db -c "ANALYZE;"`

### Qdrant Performance
- Collection uses `Cosine` similarity for embeddings
- Default 768-dim vectors from nomic-embed-text
- Snapshots: stored in qdrantdata volume

---

## Troubleshooting

### Backend Won't Start
```bash
# Check logs
docker-compose logs backend

# Verify DB is healthy
docker-compose logs db

# Run migrations manually
docker exec realestate_backend uv run alembic upgrade head
```

### Ollama Out of Memory
```bash
# Check Ollama logs
docker-compose logs ollama

# Reduce parallel requests or restart with less memory
docker-compose restart ollama
```

### Frontend Can't Connect to API
```bash
# Verify backend is running
curl http://localhost:8001/health

# Check NEXT_PUBLIC_API_URL in frontend
# For production: set to your backend domain
```

### Vector Search Not Working
```bash
# Check Qdrant is running
curl http://localhost:6333/health

# Verify collections exist
curl http://localhost:6333/collections

# Re-initialize collections
docker exec realestate_backend uv run python -c \
  "from app.services.vector_store import init_collections; init_collections()"
```

---

## Production Deployment

### Recommendations
1. Use managed PostgreSQL (RDS, Supabase) with PostGIS extension
2. Deploy to Kubernetes or Docker Swarm for scaling
3. Use managed Qdrant (qdrant.io) or self-hosted cluster
4. Redis: managed service (AWS ElastiCache, Azure Cache)
5. Ollama: local or dedicated instance with GPU
6. Frontend: deploy to Vercel, Netlify, or Docker
7. Backend: deploy to ECS, App Engine, or Kubernetes
8. Enable HTTPS and environment-based configuration

### Example: AWS Deployment
```bash
# Build and push images
docker build -t myregistry/real-estate-backend ./backend
docker build -t myregistry/real-estate-frontend ./frontend
docker push myregistry/real-estate-backend
docker push myregistry/real-estate-frontend

# Deploy via ECS, provide RDS endpoint and Ollama service
```

### Example: Vercel + Railway
```bash
# Frontend on Vercel (connect GitHub repo)
# Backend on Railway (Docker image)
# Database on Railway (PostgreSQL + PostGIS)
# Qdrant: Railway or qdrant.io
# Ollama: Railway instance or self-hosted
```

---

## Monitoring

### Health Checks
```bash
# Backend
curl http://localhost:8001/health

# Database
docker-compose exec db pg_isready

# Qdrant
curl http://localhost:6333/health

# Ollama
curl http://localhost:11434/api/tags

# Redis
docker-compose exec redis redis-cli ping
```

### Logs
All services log to `docker-compose logs`. For production, integrate with:
- CloudWatch
- Datadog
- ELK Stack
- Grafana + Prometheus

---

## Support

For issues:
1. Check logs: `docker-compose logs [service]`
2. Verify all services are healthy: `docker-compose ps`
3. Review configuration in `.env` and `docker-compose.yml`
4. Check GitHub issues for known problems
