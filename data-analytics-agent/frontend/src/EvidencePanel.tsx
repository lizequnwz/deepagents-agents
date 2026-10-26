import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import { DataTable, Notice } from "./components";
import type { Dashboard, ResultPage } from "./types";

/** Trusted local view over the canonical dashboard, independent of UI protocols. */
export default function EvidencePanel({ dashboard }: { dashboard: Dashboard }) {
  const [inspection, setInspection] = useState<ResultPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const identity = dashboard.revision.revision_id;
  const current = useRef(identity);
  current.current = identity;
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    setInspection(null);
    setError("");
    setLoading(false);
    return () => controller.current?.abort();
  }, [identity]);
  const ids = new Set(dashboard.freshness.map((item) => item.result_id));
  for (const component of dashboard.components) {
    if (component.result_id) ids.add(component.result_id);
    if (component.analysis_result_id) ids.add(component.analysis_result_id);
  }
  async function inspect(resultId: string) {
    if (!ids.has(resultId)) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const started = identity;
    setLoading(true);
    setInspection(null);
    setError("");
    try {
      const result = await api<ResultPage>(`/api/results/${encodeURIComponent(resultId)}?limit=10`, { signal: request.signal });
      if (result.result_id !== resultId) throw new Error("The saved data does not match this evidence.");
      if (!request.signal.aborted && current.current === started) setInspection(result);
    } catch (error) {
      if (!request.signal.aborted && current.current === started) setError(message(error));
    } finally {
      if (!request.signal.aborted && current.current === started) setLoading(false);
    }
  }
  return (
    <section aria-label="Dashboard evidence">
      <details className="dashboard-widget analytical-evidence">
        <summary>Evidence and saved values</summary>
        <p className="small muted">Inspect the saved datasets and values for this dashboard revision.</p>
        <div className="analytical-evidence-grid">
          {dashboard.components.filter((component) => component.type === "metric").map((component) => (
            <div key={component.id} className="analytical-reference">
              <p className="small muted">Saved metric · {component.title}</p>
              <strong className="metric-value">{component.formatted_value ?? "—"}</strong>
              {component.body && <p className="small muted">{component.body}</p>}
            </div>
          ))}
          {[...ids].map((id) => {
            const freshness = dashboard.freshness.find((item) => item.result_id === id);
            return <div className="analytical-reference" key={id}>
              <p className="small" style={{ overflowWrap: "anywhere" }}>Saved dataset <code>{id}</code></p>
              <p className="small muted">{freshness
                ? `Snapshot recorded ${new Date(freshness.queried_at).toLocaleString()}. Source completeness: ${freshness.completeness}.`
                : "Presentation snapshot. See its saved analytical source for completeness."}</p>
              <button type="button" onClick={() => void inspect(id)}>Inspect saved data</button>
            </div>;
          })}
        </div>
      </details>
      {error && <Notice error>{error}</Notice>}
      {loading && <p role="status">Loading saved data…</p>}
      {inspection && <div className="dashboard-widget">
        <div className="widget-heading"><h3>{inspection.short_label || "Saved data"}</h3>
          <button type="button" onClick={() => setInspection(null)}>Close saved data</button></div>
        <DataTable columns={inspection.columns} rows={inspection.rows.slice(0, 10)} />
        <p className="small muted">Preview: at most 10 of {inspection.row_count.toLocaleString()} saved rows.
          {inspection.truncated ? " The extraction is incomplete." : ""}</p>
      </div>}
    </section>
  );
}
