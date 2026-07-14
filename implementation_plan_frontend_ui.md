# HireIntel.AI — Ranking UI + Candidate Chat + Deployment Plan

## What We're Building

1. **Candidate Ranking Dashboard** — role dropdown, ranked leaderboard, score breakdown per candidate
2. **Candidate Chat** — select a candidate by number, chat with their resume via RAG
3. **Deployment architecture** — production-ready for tens of thousands of users

---

## Deployment Architecture (Recommended for 10K+ users)

> [!IMPORTANT]
> FastAPI + Docker + React + Cloudflare HTTPS is the right call. Here's how to structure it.

### Recommended Stack

```
Browser
  └─► Cloudflare (HTTPS, CDN, DDoS protection — free tier works)
        ├─► React SPA  (Vercel / Cloudflare Pages — static, free CDN)
        └─► FastAPI backend  (Docker containers on cloud)
                ├─► PostgreSQL  (Supabase / AWS RDS / Neon — managed)
                ├─► Qdrant Cloud  (vector store — managed)
                └─► S3 / R2  (PDF storage — Cloudflare R2 is cheapest)
```

### Cloud Options (pick one)

| Option | Cost at 10K users | Complexity | Recommended for |
|--------|-------------------|------------|-----------------|
| **Railway** | ~$20–50/mo | ⭐ Lowest | MVP, fast launch |
| **AWS ECS Fargate** | ~$60–150/mo | ⭐⭐ Medium | Production, auto-scale |
| **GCP Cloud Run** | ~$30–80/mo | ⭐⭐ Medium | Pay-per-request, great for burst |
| **Kubernetes (GKE/EKS)** | $150+/mo | ⭐⭐⭐ High | Enterprise, full control |

> [!TIP]
> **Start with Railway** for speed. Migrate to GCP Cloud Run or AWS ECS when you hit scale. Cloud Run is ideal for HireIntel because judging/scoring is bursty, not constant.

### What Needs Dockerizing

1. `hireintel-api` — existing FastAPI app (already structured)
2. `hireintel-worker` — background scoring jobs (optional, via Celery + Redis queue)

### HTTPS

HTTPS is **not** an alternative to Docker/React — it's a layer on top. Use **Cloudflare** (free proxy + SSL) in front of everything. Zero config.

---

## UI Plan

### Page 1 — Candidate Ranking Dashboard

**Route:** `/` or `/rankings`

**Layout:**
- Top bar: **HireIntel.AI** logo + role dropdown (all 8 roles)
- Leaderboard table per role:
  - Rank | Candidate ID | Score | Top REQ Scores | Flags
  - Click a row → opens candidate detail panel / chat

**API endpoints needed:**
- `GET /api/rankings/{role}` — reads `data/scores/composed/{role}_ranked.json`
- `GET /api/roles` — lists available roles (already exists via `roles.py`)

### Page 2 — Candidate Chat

**Route:** `/chat/{candidate_id}`

**Layout:**
- Left panel: candidate profile card (name/ID, role, score breakdown per REQ)
- Right panel: chat interface
  - User types question → POST to `/api/chat`
  - Backend does RAG over the candidate's indexed chunks
  - Returns answer + source excerpts

**API endpoints needed:**
- `GET /api/candidate/{candidate_id}` — returns processed JSON (profile, scores)
- `POST /api/chat` — `{candidate_id, question}` → RAG answer + chunks
- `GET /api/candidate/{candidate_id}/pdf` — serves the original PDF (inline view)

---

## Proposed Changes

### Backend — New API Endpoints

#### [MODIFY] [app.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/api/app.py)
- Register two new routers: `rankings` and `chat`

#### [NEW] `src/api/rankings.py`
- `GET /api/rankings/{role}` — read `*_ranked.json`, return top-N candidates with score breakdown

#### [NEW] `src/api/chat.py`
- `POST /api/chat` — accept `candidate_id + question`, call existing RAG retriever, return answer
- `GET /api/candidate/{candidate_id}` — return processed JSON profile
- `GET /api/candidate/{candidate_id}/pdf` — stream original PDF

### Frontend — React App (served by FastAPI or Vercel)

#### [NEW] `frontend/` — React + Vite app
- `src/pages/Rankings.jsx` — role dropdown + leaderboard table
- `src/pages/Chat.jsx` — candidate profile + chat window
- `src/components/ScoreBar.jsx` — per-REQ score visualization
- `src/components/CandidateCard.jsx` — summary card

### Docker

#### [NEW] `Dockerfile`
#### [NEW] `docker-compose.yml`

---

## Open Questions

> [!IMPORTANT]
> Need your input before starting:

1. **Frontend framework**: Build a React app (in `frontend/`) served separately, OR serve rich HTML from FastAPI static files (simpler, no npm build step)?
2. **Chat model**: For candidate chat — use the same OpenRouter model as the scorer, or a different one?
3. **PDF viewer**: Show the PDF inline in the browser, or just show extracted text?
4. **Authentication**: Any login/auth required, or open access for now?
5. **Ranking display**: Show all candidates in the leaderboard, or top-10/20 by default with load more?
