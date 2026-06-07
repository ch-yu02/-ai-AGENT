import { useState } from "react";

import { searchAcrossClassrooms } from "../services/agentApi";
import { ApiError } from "../services/api";
import type { GlobalSearchHit, GlobalSearchResponse } from "../types/agent";
import { formatClassTime } from "../utils/time";

// 跨课堂搜索面板。
//
// 与 AgentPanel 不同，这个组件不依赖当前选中的 session。它面向已保存历史课堂，
// 用于回答“之前哪节课讲过某个知识点”这类长期记忆问题。
export function GlobalSearchPanel() {
  const [query, setQuery] = useState("");
  const [course, setCourse] = useState("");
  const [response, setResponse] = useState<GlobalSearchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitSearch() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery || isLoading) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = await searchAcrossClassrooms({
        query: trimmedQuery,
        course: course.trim() || null,
        limit: 8,
      });
      setResponse(result);
    } catch (caughtError) {
      setError(formatSearchError(caughtError));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="panel global-search-panel" aria-labelledby="global-search-title">
      <div className="panel-header">
        <div>
          <h2 id="global-search-title">跨课堂搜索</h2>
          <span>搜索已保存历史课程</span>
        </div>
      </div>

      <div className="global-search-body">
        <form
          className="global-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submitSearch();
          }}
        >
          <input
            disabled={isLoading}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：哪节课讲过采样定理"
            value={query}
          />
          <input
            disabled={isLoading}
            onChange={(event) => setCourse(event.target.value)}
            placeholder="课程过滤"
            value={course}
          />
          <button className="primary-button" disabled={!query.trim() || isLoading}>
            {isLoading ? "搜索中" : "搜索"}
          </button>
        </form>

        {error ? <div className="agent-error">{error}</div> : null}
        {response ? <GlobalSearchResult response={response} /> : <SearchEmpty />}
      </div>
    </section>
  );
}

function SearchEmpty() {
  return <div className="global-search-empty">搜索历史课堂中的知识点、作业或概念</div>;
}

function GlobalSearchResult({ response }: { response: GlobalSearchResponse }) {
  return (
    <div className="global-search-results">
      <p className="global-search-answer">{response.answer}</p>
      {response.warnings.length ? (
        <ul className="agent-warnings">
          {response.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {response.hits.length ? (
        <ol className="global-hit-list">
          {response.hits.map((hit) => (
            <GlobalSearchHitItem hit={hit} key={`${hit.session_id}-${hit.source_ref.id}`} />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function GlobalSearchHitItem({ hit }: { hit: GlobalSearchHit }) {
  return (
    <li>
      <div className="global-hit-top">
        <strong>{hit.title}</strong>
        <span>{hit.course || "未命名课程"}</span>
      </div>
      <p>{hit.source_ref.text}</p>
      <div className="global-hit-meta">
        <span>{hit.source_ref.type}</span>
        <span>{hit.source_ref.id}</span>
        {typeof hit.source_ref.ts === "number" ? (
          <span>{formatClassTime(hit.source_ref.ts)}</span>
        ) : null}
        <span>score {hit.score}</span>
      </div>
    </li>
  );
}

function formatSearchError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "跨课堂搜索失败";
}
