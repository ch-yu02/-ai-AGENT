# EDU-Mate LLM Provider Setup

EDU-Mate uses one backend-only OpenAI-compatible LLM client for Agent skills,
internal LLM-backed knowledge extraction, and the structured-notes knowledge
tree agent. API keys must stay on the backend; never expose them in the
frontend bundle or browser requests.

This cloud/local OpenAI-compatible provider is separate from the local OpenVINO
Qwen used by `scripts/dev.sh whisperlive-md`. Local Qwen maintains
`structured_notes.md`; the backend provider turns those notes into graph updates
and, on final snapshots, can infer the classroom title and course.

## Shared Environment Variables

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=replace_me
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=1
```

Local development commands in `scripts/dev.sh` load `.env` automatically for
backend, dev, audio/WhisperLive integration, LLM smoke, global-index rebuild,
and build commands. Put local secrets in `.env`; keep `.env` ignored by Git and
commit only `.env.example`.

Knowledge extraction is LLM-only. If the provider is not configured, EDU-Mate
will keep transcript/OCR/classroom saving working, but it will return an
extraction error and skip graph generation.

The same provider is used by:

- `/agent/chat` LLM-backed skills and grounded QA.
- Internal realtime/end-of-session knowledge extraction.
- `/agent/knowledge-tree/update-from-notes`, which turns Qwen structured notes
  into knowledge-tree updates and final session metadata.

## Vector RAG / LlamaIndex

The default RAG backend is still lexical search because it has no external
model dependency. To enable vector retrieval for classroom Agent QA and
cross-classroom search, install the optional dependencies:

```bash
scripts/dev.sh install-rag
```

On the current device, this command installs CPU-only torch before installing
the rest of the RAG stack. Set `RAG_INSTALL_CPU_TORCH=0` only if you have a
separately managed torch build and want pip to reuse it.

Then configure `.env`:

```bash
RAG_QUERY_BACKEND=llamaindex
GLOBAL_SEARCH_BACKEND=llamaindex
RAG_EMBEDDING_BACKEND=huggingface
RAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
RAG_EMBEDDING_DEVICE=cpu
RAG_LLAMAINDEX_LLM=disabled
```

The first HuggingFace embedding run may download the embedding model and can be
noticeably slower. Keep `RAG_EMBEDDING_DEVICE=cpu` on the current device unless
you have separately validated GPU/NPU embedding support.

`RAG_LLAMAINDEX_LLM=disabled` is intentional. EDU-Mate uses LlamaIndex as the
vector retriever, then builds source-grounded answers through its own Agent
logic so source constraints remain consistent.

Useful checks:

```bash
scripts/dev.sh rag-smoke --require-llamaindex
scripts/dev.sh rebuild-global-index --llamaindex
```

The global index writes an auditable snapshot to
`data/indexes/global/documents.json`, a manifest to
`data/indexes/global/manifest.json`, and the persisted vector index to
`data/indexes/global/llama_index/`. Search lazily rebuilds the vector index when
the manifest fingerprint changes; the CLI command above forces a rebuild before
demos.

If optional dependencies, embedding model download, or index loading fails,
EDU-Mate returns a warning and falls back to lexical search instead of failing
the API request.

## DeepSeek

DeepSeek V4 uses the new model names `deepseek-v4-flash` and
`deepseek-v4-pro`. Keep the OpenAI-compatible base URL at
`https://api.deepseek.com`; the backend client appends `/chat/completions`.

Recommended default for realtime classroom extraction:

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
```

Use the higher quality V4 Pro model when latency/cost is less important:

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-v4-pro
LLM_BASE_URL=https://api.deepseek.com
```

Legacy model names such as `deepseek-chat` and `deepseek-reasoner` are not used
by the current project examples. Prefer the V4 names above for new local
configuration unless your provider account documents a different mapping.

## OpenAI

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
```

## Local OpenAI-Compatible Provider

For Ollama, vLLM, llama.cpp server, or another local OpenAI-compatible endpoint:

```bash
LLM_PROVIDER=local
LLM_API_KEY=
LLM_MODEL=llama3.1
LLM_BASE_URL=http://127.0.0.1:11434/v1
```

`local` is allowed to run without `LLM_API_KEY`; cloud providers require a key.

## Smoke Test

```bash
scripts/dev.sh llm-smoke
```

Then run a classroom flow:

1. Start backend/frontend with `scripts/dev.sh dev`.
2. Start or attach to a classroom.
3. Send `transcript.segment` and `image.capture` events, or run
   `scripts/dev.sh whisperlive-md --enable-cloud-graph`.
4. For `/events` extraction, check WebSocket `event.received.data.knowledge_extraction`.
5. For notes-driven extraction, check the response from
   `/agent/knowledge-tree/update-from-notes`.
6. Check the following internal `knowledge.extraction` message for `graph_patch`.
7. On final notes snapshots, check `session.updated` if the cloud model returned
   `session_title` or `course`.

## Failure Behavior

- Missing provider config returns `ExtractionError`.
- Provider timeout or HTTP failure returns `ExtractionError`.
- Invalid JSON/schema output returns `ExtractionError`.
- EDU-Mate does not fall back to the legacy rule extractor.
- Invalid extraction output is not written to the graph.
- Notes-agent failures return `status="failed"` and warnings; subtitles and
  structured Markdown saving continue.
