# EDU-Mate / Lecture-Link Development Guide

This file records the current full-stack conventions so future agents and
developers can continue the project without rediscovering the structure.

## Current Scope

The backend MVP implements this classroom data flow:

1. Start a classroom session.
2. Receive realtime events.
3. Update classroom context and knowledge graph in memory.
4. Push updates to WebSocket subscribers.
5. End the classroom and save local files.

The frontend MVP is also implemented. It provides a realtime classroom
dashboard that can:

1. Start and end a classroom session through the backend API.
2. Connect to `/ws/{session_id}` and consume `WebSocketMessage` updates.
3. Show realtime transcript segments.
4. Show unified timeline items.
5. Show image/OCR/VLM updates.
6. Apply `graph_patch.operations` to a knowledge graph view.

The project is now past the "minimum realtime demo" stage. The active
development area should shift toward history reading, post-class skills,
LLM integration, and end-to-end demo hardening.

## Commands

Run the backend:

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Run backend tests:

```bash
.venv/bin/python -m unittest discover -s backend/tests
```

Compile-check backend files:

```bash
.venv/bin/python -m py_compile backend/app/main.py backend/app/api/*.py backend/app/core/*.py backend/app/models/*.py backend/app/storage/*.py backend/tests/*.py
```

Install/update backend dependencies:

```bash
.venv/bin/pip install -r backend/requirements.txt
```

Run the frontend:

```bash
cd frontend
npm run dev
```

Build/check the frontend:

```bash
cd frontend
npm run build
```

Run frontend tests:

```bash
cd frontend
npm test
```

Run the mock sender against a running backend:

```bash
.venv/bin/python backend/scripts/mock_sender.py
```

Run the mock sender against a session created by the frontend UI:

```bash
.venv/bin/python backend/scripts/mock_sender.py --session-id REPLACE_WITH_SESSION_ID --no-end
```

Run the mock sender without ending the session:

```bash
.venv/bin/python backend/scripts/mock_sender.py --no-end
```

Note: `fastapi.testclient.TestClient` has been unstable in this environment, so
tests prefer manager-level and service-level coverage instead of route-level
TestClient tests.

## Backend Layers

Keep the existing separation:

- `backend/app/main.py`: FastAPI app creation, CORS, health routes, router registration.
- `backend/app/api/`: thin HTTP/WebSocket route handlers.
- `backend/app/core/`: business/runtime managers.
- `backend/app/models/`: shared Pydantic data contracts.
- `backend/app/storage/`: local persistence.
- `backend/tests/`: standard-library `unittest` tests.

API modules should translate manager exceptions to HTTP status codes. Core
managers should not import FastAPI or raise `HTTPException`.

## Core Managers

`SessionManager`

- Owns classroom lifecycle: create, get, end, require recording.
- Keeps both recording and ended sessions in memory.
- Ending a session is idempotent.
- Raises `SessionNotFoundError` or `SessionConflictError`.

`ContextManager`

- Converts `RealtimeEvent` into `ClassroomContext`.
- Handles:
  - `transcript.segment` -> transcript + timeline
  - `image.capture` -> visuals + timeline
  - `knowledge.extraction` -> knowledge_extractions + timeline
- Provides `get_compressed_context()` for future post-class skills.

`KnowledgeGraphManager`

- Consumes `knowledge.extraction`.
- Maintains one `KnowledgeTree` per session.
- Produces `GraphPatch` for frontend incremental updates.
- Deduplicates nodes by normalized entity name.
- Adds placeholder nodes when relations reference missing entities.

`WebSocketManager`

- Tracks WebSocket connections by `session_id`.
- Broadcasts `WebSocketMessage` to all subscribers for a session.
- Removes failed sockets during broadcast.
- Tests use fake WebSocket objects; do not require a real network server.

## Storage

`LocalStorage.save_session()` writes MVP artifacts to:

```text
data/sessions/{session_id}/metadata.json
data/sessions/{session_id}/transcript.md
data/sessions/{session_id}/timeline.json
data/sessions/{session_id}/knowledge_graph.json
```

`data/sessions/*` is ignored by git except `.gitkeep`.

The session end route should:

1. Load context and graph.
2. Mark the session ended.
3. Save files with `LocalStorage`.
4. Broadcast `session.ended` with storage paths.

Do not write event data directly from API routes. Keep persistence in
`backend/app/storage/`.

## Event Contract

Realtime input uses `RealtimeEvent`:

```json
{
  "session_id": "lec_xxx",
  "event_type": "transcript.segment",
  "payload": {}
}
```

Supported event types:

- `transcript.segment`
- `image.capture`
- `knowledge.extraction`

The event payload remains flexible for MVP integration. Parse payloads into
stronger models inside managers, not in route functions.

## API Routes

Current routes:

```text
GET  /
GET  /health
POST /sessions/start
GET  /sessions/{session_id}
POST /sessions/{session_id}/end
POST /events
WS   /ws/{session_id}
```

`POST /events` pipeline:

1. `session_manager.require_recording()`
2. `context_manager.handle_event()`
3. derive `event_count` from context counters
4. `knowledge_graph_manager.handle_event()`
5. `websocket_manager.broadcast()`
6. return `EventAcceptedResponse`

## Frontend Layers

The frontend lives in `frontend/` and uses React, Vite, TypeScript, and Vitest.

Keep the existing separation:

- `frontend/src/App.tsx`: page orchestration, HTTP actions, WebSocket lifecycle.
- `frontend/src/components/`: presentation components for controls and panels.
- `frontend/src/services/`: API and WebSocket clients. Components should not
  call `fetch` directly.
- `frontend/src/stores/`: reducer/store logic for merging realtime messages
  into dashboard state.
- `frontend/src/types/`: TypeScript mirrors of backend contracts from
  `docs/API_SCHEMA.md`.
- `frontend/src/utils/`: formatting helpers such as classroom-relative time.
- `frontend/src/styles.css`: global MVP layout and panel styling.

Frontend service defaults:

- `VITE_API_BASE_URL` overrides `http://127.0.0.1:8000`.
- `VITE_WS_BASE_URL` overrides `ws://127.0.0.1:8000/ws`.

`App.tsx` should remain focused on:

1. starting/ending sessions,
2. opening/closing the active WebSocket,
3. dispatching messages to `classroomReducer`,
4. rendering the dashboard panels.

Do not move WebSocket message merge logic into UI panels. Keep
`event.received`, `session.ended`, and `graph_patch` handling in
`frontend/src/stores/classroomStore.ts`.

## Frontend MVP Behavior

Implemented panels:

- `ClassroomControls`: start/end session buttons.
- `StatusStrip`: session status, WebSocket status, event count.
- `RealtimeTranscriptPanel`: transcript updates from `transcript.segment`.
- `TimelinePanel`: `context_update.timeline_item` display.
- `VisualOcrPanel`: `image.capture` OCR/caption display.
- `KnowledgeGraphPanel`: deterministic node and relation view from graph patches.

Frontend WebSocket rules:

- Do not rely on receiving `session.started`; the frontend usually connects
  after session creation.
- Treat browser `onopen` and backend `ws.connected` as idempotent connected
  signals.
- Treat `event.received.data.context_update.timeline_item` as the canonical
  incremental timeline item.
- Treat `event.received.data.graph_patch` as optional. It is normally present
  only for `knowledge.extraction`.
- Apply graph patch operations in order.
- Treat `session.ended` as a final realtime state update, but keep transcript,
  timeline, visuals, and graph visible after ending the classroom.

## Testing Conventions

Use `unittest`, not pytest, unless the project explicitly adopts pytest later.

Existing tests:

- `test_session_manager.py`
- `test_context_manager.py`
- `test_knowledge_graph_manager.py`
- `test_websocket_manager.py`
- `test_local_storage.py`
- `test_storage_integration.py`

When adding a module, add a focused test file under `backend/tests/`.

Prefer temporary directories for storage tests:

```python
tempfile.TemporaryDirectory()
LocalStorage(Path(temp_dir) / "sessions")
```

Do not write tests that depend on persistent files in `data/sessions/`.

Frontend tests use Vitest.

Existing frontend tests:

- `frontend/src/stores/classroomStore.test.ts`

Prefer reducer/service-level tests for realtime message handling. UI tests can
be added later when the project adopts a browser test setup. Do not make tests
depend on a live backend server unless explicitly writing an integration smoke
test.

## Manual Smoke Test

Start backend:

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Start a session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/start \
  -H "Content-Type: application/json" \
  -d '{"title":"通信原理第8讲","course":"通信原理"}'
```

Send a transcript event:

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"REPLACE_WITH_SESSION_ID",
    "event_type":"transcript.segment",
    "payload":{
      "segment_id":"seg_001",
      "start_ts":1.0,
      "end_ts":3.5,
      "text":"傅里叶变换可以把时域信号转换到频域。"
    }
  }'
```

Send a knowledge event:

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"REPLACE_WITH_SESSION_ID",
    "event_type":"knowledge.extraction",
    "payload":{
      "extraction_id":"ext_001",
      "timestamp_range":[1.0,3.5],
      "source_segment_ids":["seg_001"],
      "entities":[
        {"entity_id":"node_fourier","name":"傅里叶变换"},
        {"entity_id":"node_freq","name":"频域"}
      ],
      "relations":[
        {"source":"傅里叶变换","target":"频域","relation":"maps_to"}
      ]
    }
  }'
```

End the session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/REPLACE_WITH_SESSION_ID/end
```

Check saved files:

```bash
ls data/sessions/REPLACE_WITH_SESSION_ID
```

## Full-Stack Manual Smoke Test

Start backend:

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Start frontend:

```bash
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Click "Start Classroom" in the UI, then run mock sender in another terminal.
Copy the UI-generated `session_id`, then send mock events into that exact
frontend session:

```bash
.venv/bin/python backend/scripts/mock_sender.py --session-id REPLACE_WITH_SESSION_ID --no-end
```

Use `--no-end` during frontend debugging so the page stays in the recording
state after mock events arrive. Omit `--no-end` when you want to exercise the
full end-and-save path.

Expected frontend behavior:

1. WebSocket status reaches connected.
2. Transcript panel grows for `transcript.segment`.
3. Timeline panel grows for all event types.
4. Visual/OCR panel updates for `image.capture`.
5. Knowledge graph panel updates for `knowledge.extraction`.
6. Ending a classroom leaves the captured data visible.

## WebSocket Manual Test

Do not test from a page with strict CSP such as `connect-src https:`. Use
`about:blank` or a local HTML file.

Browser console:

```js
const sid = "REPLACE_WITH_SESSION_ID";
const ws = new WebSocket(`ws://127.0.0.1:8000/ws/${sid}`);
ws.onopen = () => console.log("connected");
ws.onmessage = (event) => console.log("WS:", JSON.parse(event.data));
ws.onerror = (event) => console.log("error", event);
ws.onclose = (event) => console.log("closed", event.code, event.reason);
```

Sessions are in memory. If the backend restarts, old session IDs no longer
exist even if saved files remain on disk.

## Style Notes

- Keep comments useful and explain responsibilities, data flow, and extension points.
- Avoid moving business logic into route modules.
- Keep route response models in `backend/app/models/`.
- Keep frontend HTTP and WebSocket logic in `frontend/src/services/`.
- Keep frontend realtime merge logic in `frontend/src/stores/`.
- Keep backward-compatible shims only when they prevent existing imports from breaking
  (`api/schemas.py`, `api/realtime.py` currently do this).
- Use UTF-8 for Chinese content in JSON and Markdown.
- Avoid destructive cleanup of `data/sessions/` unless explicitly requested.

## Near-Term Extension Points

Likely next modules:

- History API: list/read saved sessions from `LocalStorage`.
- Post-class skills: summarizer, todos, quiz.
- Cloud LLM client: DeepSeek first, with retries and structured output checks.
- Frontend history view: list saved sessions and replay transcript/timeline/graph.
- Frontend post-class view: summary, todos, quiz.
- Mock sender extensions: add alternate scenarios, longer replay files, or
  JSON fixture loading for demo rehearsals.
- Storage hardening: periodic snapshots while recording.
