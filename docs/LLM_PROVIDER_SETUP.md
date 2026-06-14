# EDU-Mate LLM Provider Setup

EDU-Mate uses one backend-only OpenAI-compatible LLM client for Agent skills and
LLM-backed knowledge extraction. API keys must stay on the backend; never expose
them in the frontend bundle or browser requests.

## Shared Environment Variables

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=replace_me
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=1
```

Knowledge extraction is LLM-only. If the provider is not configured, EDU-Mate
will keep transcript/OCR/classroom saving working, but it will return an
extraction error and skip graph generation.

## DeepSeek

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

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
2. Start a classroom.
3. Send `transcript.segment` and `image.capture` events.
4. Check WebSocket `event.received.data.knowledge_extraction`.
5. Check the following internal `knowledge.extraction` message for `graph_patch`.

## Failure Behavior

- Missing provider config returns `ExtractionError`.
- Provider timeout or HTTP failure returns `ExtractionError`.
- Invalid JSON/schema output returns `ExtractionError`.
- EDU-Mate does not fall back to the legacy rule extractor.
- Invalid extraction output is not written to the graph.
