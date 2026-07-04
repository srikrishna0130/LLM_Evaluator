# Shadow Model Evaluator

Client sends a prompt and **immediately** gets a **Mock LLM response** (the stand-in "production" model). A **shadow candidate model** — generated via **DigitalOcean Serverless Inference** — then runs **asynchronously in the background**. Both outputs are logged into an **evaluation session** that is retrieved via a **separate endpoint**.

The client never waits on (and never sees) the candidate in the first call — the shadow runs "in the dark" and can never add latency to or break the primary response.

---

## Flow

```
POST /evaluate  { "prompt": "..." }
        │
        ├─ 1. generate Mock LLM response (instant, canned/templated)
        ├─ 2. create session { id, prompt, mock_response, candidate: pending }
        ├─ 3. schedule background shadow task
        └─ 4. return { session_id, response: <mock_response> }   ← client done here

[background]  candidate = DO Serverless Inference(prompt)
              update session.candidate = { text, latency_ms, usage, status }

GET /evaluations/{session_id}
        └─ returns BOTH outputs: mock + candidate (+ status/latency/usage)
```

**Answering the two design questions from earlier:**
- *Does the client get the candidate response?* No — only the mock. The candidate is read later via `GET /evaluations/{id}`.
- *How does the background task survive the client disconnecting?* FastAPI `BackgroundTasks` run **after** the response is flushed, inside the **server's event loop** — they aren't tied to the client socket, so the client can disconnect and the shadow still completes. (In-process only; durability across pod restarts is a "good to have" — see below.)

### Endpoint & auth (DigitalOcean — the candidate only)
- Base URL: `https://inference.do-ai.run/v1`
- Auth: `Authorization: Bearer <MODEL_ACCESS_KEY>` — a `sk-do-...` model access key from the Control Panel under **Inference → Model Access Keys**.
- Model id: any value from `GET /v1/models` (e.g. `openai-gpt-5-mini` or `openai-gpt-5`).

---

## How background tasks are handled (and their limits)

The POC uses **FastAPI's built-in `BackgroundTasks`** — no external queue or worker. The `/evaluate` route builds the mock response, creates the session, registers the shadow call, and returns; Starlette runs the registered task *after* the response is flushed.

```python
@router.post("/evaluate")
async def evaluate(body: EvaluateRequest, request: Request, background_tasks: BackgroundTasks):
    mock = request.app.state.mock_model.generate(body.prompt)          # instant
    session_id = request.app.state.sessions.create(body.prompt, mock)  # status: pending
    background_tasks.add_task(
        run_shadow,
        request.app.state.candidate_model,   # shared pooled client
        request.app.state.sessions,          # shared store
        session_id,
        body.prompt,
    )
    return {"session_id": session_id, "response": mock["text"]}        # returned NOW


async def run_shadow(client, sessions, session_id, prompt):
    try:
        result = await client.generate(prompt)                        # DO serverless call
        await sessions.set_candidate(session_id, result, status="ok")
    except Exception as e:                                            # timeout, 5xx, etc.
        log.exception("shadow failed")
        await sessions.set_candidate(session_id, None, status="failed", error=str(e))
```

**Runtime behavior**
- **Response first, task second:** Starlette flushes the `/evaluate` body, *then* executes the task. The client already has its `session_id` + mock and can disconnect.
- **Runs in the server event loop:** since `run_shadow` is `async def`, it's `await`ed on the loop (a sync task would go to the anyio threadpool). It's decoupled from the client socket, so a client disconnect never cancels it.
- **I/O-bound concurrency is free:** the shadow call `await`s on the network, so many run concurrently without threads.
- **Shared state via `app.state`:** the single pooled `AsyncOpenAI` client and the session store are created once in `lifespan`; the store uses an `asyncio.Lock` because multiple tasks mutate it concurrently.
- **Failures are contained:** the response is already sent, so an exception can't become a 5xx for the caller — we `try/except` and store `candidate_status: failed`.

**Limits (why this is POC-only)**
- **In-process = not durable:** a deploy, crash, or OOM kill loses in-flight shadow calls — no retry, no persistence.
- **Graceful shutdown holds the worker** until pending tasks finish, but a hard restart does not.
- **No backpressure:** a spike spawns unbounded concurrent DO calls (prod needs a bounded queue / semaphore).
- **No cross-process visibility:** with multiple workers/pods, a task runs only on the worker that received the request, and the in-memory store isn't shared.

The production evolution — a durable queue (Redis/RabbitMQ) + a separate worker + DB-backed sessions — is captured under **Good to have** and **Non-goals** below.

---

## Implementation steps (time-boxed, ~2 hrs)

### Step 1 — Config & dependency (~15 min)
Add to `app/core/config.py` (secrets from env only — 12-factor):

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Candidate (shadow) model — serverless inference
    CANDIDATE_BASE_URL: str = "https://inference.do-ai.run/v1"
    CANDIDATE_MODEL: str = "openai-gpt-5-mini"
    MODEL_ACCESS_KEY: str = ""          # secret, from env only
    CANDIDATE_TIMEOUT_S: float = 30.0
    CANDIDATE_MAX_RETRIES: int = 2
```

Mirror them in `.env.example` (no real value committed) and add `openai` to `requirements.txt`.

### Step 2 — Mock model + candidate client (~25 min)
Two small services in `app/services/`.

`mock_model.py` — the instant stand-in "production" model:

```python
class MockModelClient:
    def generate(self, prompt: str) -> dict:
        return {"text": f"[mock] echo: {prompt}", "model": "mock-llm-v0"}
```

`candidate_model.py` — the shadow, behind a mockable async class:

```python
from openai import AsyncOpenAI
from app.core.config import settings

class CandidateModelClient:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.CANDIDATE_BASE_URL,
            api_key=settings.MODEL_ACCESS_KEY,
            timeout=settings.CANDIDATE_TIMEOUT_S,
            max_retries=settings.CANDIDATE_MAX_RETRIES,
        )

    async def generate(self, prompt: str) -> dict:
        resp = await self._client.chat.completions.create(
            model=settings.CANDIDATE_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "text": resp.choices[0].message.content,
            "model": resp.model,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }
```

### Step 3 — Session store (~15 min)
An in-memory, thread-safe store keyed by `session_id` (a `dict` + `asyncio.Lock` is fine for the POC). Records: `prompt`, `mock`, `candidate`, `candidate_status` (`pending|ok|failed`), timestamps. Swappable for Postgres later (see "good to have").

### Step 4 — Endpoints + background shadow (~35 min)
- Instantiate `MockModelClient` and `CandidateModelClient` once in the `lifespan` handler (`app/main.py`), store on `app.state` (reuse the candidate connection pool; close on shutdown).
- `POST /evaluate`:
  1. build the mock response,
  2. create the session (`candidate_status: pending`),
  3. schedule the shadow via `BackgroundTasks`,
  4. return `{ session_id, response: <mock> }` **immediately**.
- Background shadow task: call the candidate, `try/except` + timeout, write `text/latency_ms/usage` and set status `ok`/`failed` on the session. Failures are logged, never surfaced to the caller.
- `GET /evaluations/{session_id}`: return both outputs (404 if unknown; candidate may still be `pending`).

Register both routes in `app/api/router.py`.

### Step 5 — Tests (~20 min)
- Inject a **fake `CandidateModelClient`** (no network). Assert:
  - `POST /evaluate` returns the mock response and a `session_id` fast.
  - after the background task runs, `GET /evaluations/{id}` shows both outputs.
  - candidate failure ⇒ session `candidate_status: failed`, `/evaluate` still succeeded.
- One optional live integration test, skipped unless `MODEL_ACCESS_KEY` is set.

### Step 6 — Docs & polish (~10 min)
README: get a model access key, set `.env`, `curl` both endpoints. Structured log line per shadow run (model id, latency, token usage).

---

## Good to have (if time permits)
- **Durable async:** replace in-process `BackgroundTasks` with a queue (Redis/RabbitMQ) + worker so shadow jobs survive pod restarts.
- **Persistence:** store sessions in Postgres instead of memory (survives restart, queryable history).
- **Scoring/comparison:** compute a diff/score between mock and candidate (latency, token cost, similarity, LLM-as-judge) and expose it on the session.
- **List/filter endpoint:** `GET /evaluations` with pagination for a dashboard.
- **Streaming & batch:** `stream=True` for long candidate outputs; batch inference for offline backfills.
- **Dedicated deployment:** point the same `base_url` config at a dedicated GPU deployment once volume justifies always-on capacity.

## Explicit non-goals for the POC
- No durable queue / no DB — sessions live in memory (lost on restart).
- No auth/rate-limiting on the endpoints.
- The "baseline" is a **mock**, not a real production model — the POC proves the *async shadow serverless path* and the *log-and-retrieve* flow.
