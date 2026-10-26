import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api, message } from "./api";
import { Notice } from "./components";

interface ValuePage {
  revision_id: string;
  values: unknown[];
  next_offset: number | null;
}

export function FilterValueSearch({ threadId, dashboardId, revisionId, filterId, label, disabled, onValues }: {
  threadId: string;
  dashboardId: string;
  revisionId: string;
  filterId: string;
  label: string;
  disabled: boolean;
  onValues: (values: unknown[], append: boolean) => void;
}) {
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  async function search(append = false) {
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    const request = ++sequence.current;
    const term = append ? submitted : draft;
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({
        expected_revision: revisionId,
        search: term,
        offset: String(append ? nextOffset ?? 0 : 0),
        limit: "100",
      });
      const page = await api<ValuePage>(
        `/api/conversations/${threadId}/dashboards/${dashboardId}/filters/${filterId}/values?${query}`,
        { signal: pending.signal },
      );
      if (!mounted.current || request !== sequence.current) return;
      if (page.revision_id !== revisionId) throw new Error("The dashboard changed. Reload its filters before searching again.");
      onValues(page.values, append);
      setCount((previous) => (append ? previous ?? 0 : 0) + page.values.length);
      setNextOffset(page.next_offset);
      setSubmitted(term);
    } catch (error) {
      if (mounted.current && request === sequence.current && !pending.signal.aborted) setError(message(error));
    } finally {
      if (mounted.current && request === sequence.current) setLoading(false);
    }
  }
  return (
    <details className="custom-filter filter-value-search">
      <summary>Search saved values</summary>
      <form aria-label={`Search ${label} values`} onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <label>Value search
          <input type="search" maxLength={500} disabled={disabled || loading} value={draft}
            aria-label={`Search saved ${label}`} onChange={(event) => setDraft(event.target.value)} />
        </label>
        <p className="small muted">Search the complete saved population. Choose found values in the list above.</p>
        <button type="submit" disabled={disabled || loading}><Search size={14} aria-hidden="true" />{loading ? "Searching…" : "Find values"}</button>
        {error && <Notice error>{error}</Notice>}
        {count !== null && !error && (
          <p className="small muted" role="status">{count ? `${count} saved ${count === 1 ? "value" : "values"} found${nextOffset !== null ? ". More values are available." : "."}` : "No matching saved values."}</p>
        )}
        {nextOffset !== null && !error && <button type="button" disabled={disabled || loading} onClick={() => void search(true)}>Load more values</button>}
      </form>
    </details>
  );
}
