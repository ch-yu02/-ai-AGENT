# EDU-Mate / Lecture-Link Development Guide

This is the single source of truth for the current project state, development
rules, capability boundaries, and near-term roadmap. Keep `Tasks.md` and
`docs/AGENT_DEVELOPMENT_PLAN.md` aligned with this file instead of duplicating
conflicting plans.

## Current State

EDU-Mate is now a full-stack local classroom Agent system. It is no longer only
a backend MVP or only a realtime dashboard.

Completed core capabilities:

- Realtime classroom lifecycle: start session, receive events, update context,
  push WebSocket updates, end session, and save local artifacts.
- Frontend realtime dashboard: start/end classroom, WebSocket status,
  transcript panel, timeline panel, visual/OCR panel, knowledge graph panel,
  history panel, Agent panel, global search panel, and post-class artifacts.
- Local history: ended sessions are saved under `data/sessions/{session_id}/`;
  frontend can list, open, deep-link to, and delete saved sessions.
- Post-class artifacts: summary and todos are generated on session end;
  quiz is generated on demand.
- Classroom Agent: `POST /agent/chat` supports `qa`, `summary`, `todos`, and
  `quiz` modes with strict/grounded QA.
- Cross-classroom search: `POST /agent/search` searches saved sessions with
  optional course/date filters.
- Optional LLM integration: cloud/local OpenAI-compatible provider support via
  environment variables.
- Optional RAG: lexical search by default, optional LlamaIndex backends for
  single-session and global indexes.
- Internal knowledge extraction: offline rule-based extraction runs on session
  end and turns transcript/OCR context into internal `knowledge.extraction`
  events for graph growth.
- Mock sender: sends ASR, visual, and mock internal knowledge extraction events
  to a session created manually from the frontend.

## Capability Boundaries

External integrations should normally send only:

```text
transcript.segment
image.capture
```

Knowledge extraction is an EDU-Mate responsibility:

- `knowledge.extraction` is an internal pipeline event.
- It may be produced by the internal LLM knowledge extractor.
- It may be sent by `mock_sender.py` for demo/debug.
- External ASR/OCR/hardware integrations should not be required to send it.

Current extraction state:

- Automatic extraction uses the LLM-backed extractor at session end and during
  recording in small batches.
- If the LLM provider is missing or fails, failures are surfaced as extraction
  errors and graph generation is skipped. EDU-Mate does not automatically fall
  back to rule-based graph extraction.

Current image serving state:

- Raw image bytes can be uploaded with `PUT /sessions/{session_id}/images/{image_id}`.
- Images are served from `GET /sessions/{session_id}/images/{image_id}`.
- Served files are constrained to `data/sessions/{session_id}/images/`.

## Commands

Preferred helper:

```bash
scripts/dev.sh help
```

Start backend and frontend together:

```bash
scripts/dev.sh dev
```

Run all tests:

```bash
scripts/dev.sh test
```

Compile-check backend:

```bash
scripts/dev.sh compile
```

Build/check frontend:

```bash
scripts/dev.sh build
```

Run mock sender against a frontend-created session:

```bash
scripts/dev.sh mock --session-id REPLACE_WITH_SESSION_ID --no-end
```

Manually smoke-test configured LLM provider:

```bash
scripts/dev.sh llm-smoke
```

Rebuild global search index snapshots:

```bash
scripts/dev.sh rebuild-global-index
scripts/dev.sh rebuild-global-index --llamaindex
```

LAN testing:

```bash
BACKEND_HOST=0.0.0.0 FRONTEND_HOST=0.0.0.0 scripts/dev.sh dev
```

Underlying commands:

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
.venv/bin/python -m unittest discover -s backend/tests
cd frontend && npm run dev
cd frontend && npm test
cd frontend && npm run build
```

Note: `fastapi.testclient.TestClient` has been unstable in this environment, so
tests prefer manager-level, service-level, and storage-level coverage.

## Backend Structure

```text
backend/app/main.py
backend/app/api/
backend/app/core/
backend/app/models/
backend/app/storage/
backend/app/agent/
backend/app/skills/
backend/app/rag/
backend/app/llm/
backend/scripts/
backend/tests/
```

Layer rules:

- `api/`: thin HTTP/WebSocket routes only. Convert domain exceptions to HTTP.
- `core/`: runtime managers for sessions, context, graph, and WebSockets.
- `models/`: shared Pydantic contracts for events, context, graph, sessions.
- `storage/`: local persistence and history deletion/reading.
- `agent/`: prompt routing, classroom Agent orchestration, global search.
- `skills/`: QA, summarizer, todo detective, quiz master.
- `rag/`: document conversion, lexical/LlamaIndex query services, global index.
- `llm/`: provider settings and cloud/local model client.

Core manager notes:

- `SessionManager` owns lifecycle and keeps recording/ended sessions in memory.
- `ContextManager` converts realtime events into transcript, visuals,
  knowledge extractions, timeline, and compressed context.
- `KnowledgeGraphManager` consumes internal `knowledge.extraction`, deduplicates
  nodes by normalized entity name, creates placeholder nodes for missing
  relation endpoints, and emits `GraphPatch`.
- `WebSocketManager` tracks subscribers by `session_id` and removes failed
  sockets during broadcast.

## Frontend Structure

```text
frontend/src/App.tsx
frontend/src/components/
frontend/src/services/
frontend/src/stores/
frontend/src/types/
frontend/src/utils/
frontend/src/styles.css
```

Frontend rules:

- Keep HTTP calls in `frontend/src/services/`.
- Keep WebSocket parsing in `services/websocket.ts`.
- Keep realtime merge logic in `frontend/src/stores/classroomStore.ts`.
- Components should render state and trigger service actions, not own protocol
  parsing.
- TypeScript contracts should mirror `docs/API_SCHEMA.md`.

Important components:

- `ClassroomControls`
- `StatusStrip`
- `RealtimeTranscriptPanel`
- `TimelinePanel`
- `VisualOcrPanel`
- `KnowledgeGraphPanel`
- `HistoryPanel`
- `AgentPanel`
- `GlobalSearchPanel`
- `PostClassArtifactsPanel`

## Runtime Data

Ended sessions are stored under:

```text
data/sessions/{session_id}/metadata.json
data/sessions/{session_id}/transcript.md
data/sessions/{session_id}/timeline.json
data/sessions/{session_id}/knowledge_graph.json
data/sessions/{session_id}/summary.md
data/sessions/{session_id}/todos.json
data/sessions/{session_id}/quiz.json
data/sessions/{session_id}/agent_messages.json
data/sessions/{session_id}/agent_artifacts.json
data/sessions/{session_id}/llama_index/
```

Global search/index artifacts:

```text
data/indexes/global/documents.json
data/indexes/global/manifest.json
data/indexes/global/llama_index/
```

`data/sessions/*` is ignored by git except `.gitkeep`. Do not destructively
clean this directory unless explicitly requested.

## Input Contract

The integration contract lives in:

```text
docs/INPUT_DATA_CONTRACT.md
```

External modules:

- ASR sends `transcript.segment`.
- OCR/VLM/camera sends `image.capture`.
- Hardware should coordinate IP, image path, microphone/camera ownership, and
  offline caching.

Internal EDU-Mate module:

- The internal knowledge extractor reads `ClassroomContext.transcript` and
  `ClassroomContext.visuals`.
- It generates internal `knowledge.extraction` via the LLM-backed extractor at
  session end and in recording-time batches.
- `KnowledgeGraphManager` applies the generated extraction to the graph.

## API Summary

System and sessions:

```text
GET    /
GET    /health
POST   /sessions/start
GET    /sessions/{session_id}
GET    /sessions
GET    /sessions/{session_id}/history
DELETE /sessions/{session_id}/history
POST   /sessions/{session_id}/end
```

Realtime:

```text
POST /events
WS   /ws/{session_id}
```

Agent:

```text
POST /agent/chat
POST /agent/search
```

## WebSocket Rules

- Do not rely on receiving `session.started`; the frontend usually connects
  after session creation.
- Treat browser `onopen` and backend `ws.connected` as idempotent connected
  signals.
- `event.received.data.context_update.timeline_item` is the canonical
  incremental timeline item.
- `event.received.data.graph_patch` is optional and normally appears only when
  internal `knowledge.extraction` updates the graph.
- ASR/OCR events may include `event.received.data.knowledge_extraction` when
  they trigger batched internal extraction; the actual graph update is then
  broadcast as a separate `knowledge.extraction` event.
- Apply graph patch operations in order.
- Keep transcript, timeline, visuals, graph, and Agent artifacts visible after
  session end.

## Agent And RAG

Single-classroom Agent:

- `POST /agent/chat`
- modes: `auto`, `qa`, `summary`, `todos`, `quiz`
- QA answer modes: `strict`, `grounded`
- strict mode should answer only from classroom data.
- grounded mode may use model background knowledge, but must return warnings.

Cross-classroom search:

- `POST /agent/search`
- Searches saved sessions only.
- Supports filters such as course and date range.
- Can open frontend history detail and focus source refs.

LLM:

- Provider config comes from environment variables.
- API keys must stay backend-only.
- `.env` and `.env.*` are ignored by git.
- Tests must not depend on network, real API keys, or heavy local models.

RAG:

- Lexical fallback should remain available.
- Optional LlamaIndex backends should fail gracefully and return warnings.
- Saved indexes should be treated as cache artifacts, not source of truth.

## Testing

Backend uses standard-library `unittest`.

Current backend test areas include:

- session manager
- context manager
- knowledge graph manager
- websocket manager
- local storage and storage integration
- Agent intent router and classroom Agent
- skills
- RAG documents/query services/LlamaIndex fallback
- LLM client
- global search
- post-class artifact generation

Frontend uses Vitest, currently focused on store/reducer behavior.

Testing rules:

- Prefer temporary directories for storage tests.
- Do not depend on persistent files in `data/sessions/`.
- Do not call real LLM providers in automated tests.
- Use fake clients/services for provider-specific behavior.
- Keep route tests light because `TestClient` is unreliable here.

## Manual Smoke Flow

1. Start backend/frontend:

```bash
scripts/dev.sh dev
```

2. Open:

```text
http://127.0.0.1:5173
```

3. Click Start Classroom.
4. Copy `session_id`.
5. Send mock events:

```bash
scripts/dev.sh mock --session-id REPLACE_WITH_SESSION_ID --no-end
```

6. Verify:

- WebSocket status connected.
- Transcript grows.
- Timeline grows.
- Visual/OCR panel updates.
- Mock internal knowledge extraction updates graph.
- Agent panel can answer/summarize/extract todos/generate quiz.
- Ending session saves history and artifacts.

## Active Roadmap

Highest priority:

1. Document real provider setup for LLM-backed knowledge extraction.
2. Tune extraction quality fixtures and prompts.
3. Keep extraction lightweight in the realtime `POST /events` path.

Next:

1. Document real LlamaIndex/embedding provider setup.
2. Add frontend tests for URL deep-link and focused source behavior.
3. Add Ollama/vLLM local model setup examples.
4. Improve visual image upload if frontend must display real images.

Later:

1. Recording-time batch incremental indexing.
2. Export full classroom Markdown package.
3. Export graph Mermaid, todos ICS, and quiz/Anki formats.
4. API key/config UI.
5. Deployment docs and startup service for Ubuntu/DK device.

## Documentation Map

- `AGENTS.md`: this source of truth.
- `Tasks.md`: active checklist derived from this guide.
- `docs/API_SCHEMA.md`: HTTP/WebSocket/Agent API schema.
- `docs/INPUT_DATA_CONTRACT.md`: ASR/OCR/hardware input contract.
- `docs/AGENT_DEVELOPMENT_PLAN.md`: Agent/RAG focused roadmap derived from this guide.
- `docs/LLM_PROVIDER_SETUP.md`: DeepSeek/OpenAI/local provider setup.
