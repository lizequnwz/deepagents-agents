import { useEffect, useRef, useState } from "react";
import EvidencePanel from "./EvidencePanel";
import {
  ArrowDown,
  ArrowUp,
  BookmarkPlus,
  Check,
  Clock3,
  Filter,
  LayoutDashboard,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  PanelsTopLeft,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { ChartEditor } from "./ChartEditor";
import { FilterValueSearch } from "./FilterValueSearch";
import { MetricFormatEditor } from "./MetricFormatEditor";
import { api, post, message } from "./api";
import {
  ChartFigure,
  DataTable,
  Empty,
  Loading,
  Notice,
  valueText,
} from "./components";
import type {
  Answer,
  Dashboard,
  DashboardComponent,
  DashboardFilter,
  ResultPage,
} from "./types";

interface Props {
  threadId: string;
  dashboard: Dashboard | null;
  answer: Answer | null;
  runId: string | null;
  busy: boolean;
  onSaved: (dashboard: Dashboard) => void;
  onRun: (runId: string) => void;
  onReload: () => void;
  onPresentationSaved?: (answer: Answer) => void;
}
const dashboardPath = (thread: string, id: string) =>
  `/api/conversations/${thread}/dashboards/${id}`;

export default function DashboardPanel({
  threadId,
  dashboard,
  answer,
  runId,
  busy,
  onSaved,
  onRun,
  onReload,
  onPresentationSaved,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown[]>>({});
  const [customValues, setCustomValues] = useState<Record<string, string>>({});
  const [searchedOptions, setSearchedOptions] = useState<Record<string, unknown[]>>({});
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [saveDialog, setSaveDialog] = useState(false);
  const [title, setTitle] = useState("");
  const [editing, setEditing] = useState(false);
  const [order, setOrder] = useState<string[]>([]);
  const [spans, setSpans] = useState<Record<string, number>>({});
  const [addingFilter, setAddingFilter] = useState(false);
  const [drill, setDrill] = useState<DashboardComponent | null>(null);
  const [drillQuestion, setDrillQuestion] = useState("");
  const revision = dashboard?.revision;
  const mounted = useRef(true);
  const identity = `${threadId}:${revision?.revision_id ?? answer?.report?.report_id ?? ""}:${runId ?? ""}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const isCurrent = (started: string) =>
    mounted.current && currentIdentity.current === started;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    setValues(
      Object.fromEntries(
        (dashboard?.filters ?? []).map((filter) => [
          filter.id,
          revision?.saved_filter_values[filter.id] ??
            revision?.applied_filters[filter.id] ??
            filter.default_values ??
            [],
        ]),
      ),
    );
    setCustomValues({});
    setSearchedOptions({});
    setTitle(revision?.spec.title ?? answer?.report?.title ?? "");
    setOrder(revision?.spec.components.map((c) => c.id) ?? []);
    setSpans(
      Object.fromEntries(
        revision?.spec.components.map((c) => [c.id, c.span ?? 1]) ?? [],
      ),
    );
    setEditing(false);
    setWorking(false);
    setSaveDialog(false);
    setAddingFilter(false);
    setDrill(null);
    setError("");
  }, [revision?.revision_id, answer?.report?.report_id]);
  async function perform(
    action: "filter" | "refresh" | "drill",
    extra: Record<string, unknown> = {},
  ) {
    if (!revision) return;
    const started = identity;
    setWorking(true);
    setError("");
    try {
      const result = await post<{ run_id: string }>(
        `${dashboardPath(threadId, revision.dashboard_id)}/actions`,
        {
          action,
          expected_revision: revision.revision_id,
          request_id: crypto.randomUUID(),
          ...(action === "filter" ? { filter_values: values } : {}),
          ...extra,
        },
      );
      if (!isCurrent(started)) return;
      setDrill(null);
      onRun(result.run_id);
      onReload();
    } catch (e) {
      if (isCurrent(started)) setError(message(e));
    } finally {
      if (isCurrent(started)) setWorking(false);
    }
  }
  async function save() {
    if (!runId) return;
    const started = identity;
    setWorking(true);
    setError("");
    try {
      const result = await post<Dashboard>(
        `/api/conversations/${threadId}/dashboards`,
        { run_id: runId, title: title.trim() || answer?.report?.title },
      );
      if (!isCurrent(started)) return;
      onSaved(result);
      setSaveDialog(false);
    } catch (e) {
      if (isCurrent(started)) setError(message(e));
    } finally {
      if (isCurrent(started)) setWorking(false);
    }
  }
  async function saveView(filters?: DashboardFilter[]) {
    if (!revision) return;
    const started = identity;
    setWorking(true);
    setError("");
    try {
      const result = await post<Dashboard>(
        `${dashboardPath(threadId, revision.dashboard_id)}/view`,
        {
          expected_revision: revision.revision_id,
          request_id: crypto.randomUUID(),
          title: title.trim(),
          component_order: order,
          component_spans: spans,
          saved_filter_values: values,
          ...(filters ? { filters } : {}),
        },
      );
      if (!isCurrent(started)) return;
      onSaved(result);
      setEditing(false);
      setAddingFilter(false);
    } catch (e) {
      if (isCurrent(started)) setError(message(e));
    } finally {
      if (isCurrent(started)) setWorking(false);
    }
  }
  function move(id: string, direction: number) {
    const next = [...order];
    const index = next.indexOf(id);
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
  }
  function filterOptions(filter: Dashboard["filters"][number]) {
    return [...new Map([...(filter.options ?? []), ...(searchedOptions[filter.id] ?? [])]
      .map((value) => [JSON.stringify(value), value])).values()];
  }
  const pending =
    !!dashboard?.pending_action &&
    ["queued", "running"].includes(dashboard.pending_action.status ?? "");
  const disabled = busy || working || pending;
  const components = dashboard?.components ?? [];
  const dataPanelCount = components.filter(
    (component) => component.type !== "text",
  ).length;
  const changedFilterCount = (dashboard?.filters ?? []).filter((filter) => {
    const draft = values[filter.id] ?? [];
    const applied = revision?.applied_filters[filter.id] ?? [];
    const normalize = (selected: unknown[]) =>
      filter.kind === "category"
        ? JSON.stringify(selected.map((value) => JSON.stringify(value)).sort())
        : JSON.stringify(selected);
    return normalize(draft) !== normalize(applied);
  }).length;
  const ordered = editing
    ? order
        .map((id) => components.find((c) => c.id === id))
        .filter((c): c is DashboardComponent => !!c)
    : components;
  const groups: DashboardComponent[][] = [];
  for (const component of ordered) {
    const previous = groups.at(-1);
    if (!editing && component.type === "metric" && component.span === 1 && previous?.[0].type === "metric" && previous[0].span === 1) previous.push(component);
    else groups.push([component]);
  }
  const description = revision?.spec.description ?? "";
  const deck = description.length > 220 ? description.slice(0, 220).replace(/\s\S*$/, "") + "…" : description;
  async function saveMetricFormat(componentId: string, format: string) {
    if (!revision) return;
    const started = identity;
    setWorking(true);
    setError("");
    try {
      const next = await post<Dashboard>(`${dashboardPath(threadId, revision.dashboard_id)}/presentation`, {
        expected_revision: revision.revision_id, request_id: crypto.randomUUID(),
        metric_formats: { [componentId]: format },
      });
      if (isCurrent(started)) onSaved(next);
    } catch (error) {
      if (isCurrent(started)) setError(message(error));
    } finally {
      if (isCurrent(started)) setWorking(false);
    }
  }
  function renderComponent(component: DashboardComponent) {
    const definition = revision?.spec.components.find((item) => item.id === component.id);
    return (
      <section
        className={`dashboard-widget widget-${component.type} span-${editing ? spans[component.id] : (component.span ?? 1)}`}
        key={component.id}
      >
        <div className="widget-heading">
          <h3>{component.title}</h3>
          {component.type !== "text" && (
            <button
              className="widget-action"
              aria-label={`Investigate ${component.title || component.id}`}
              disabled={disabled}
              onClick={() => {
                setDrill(component);
                setDrillQuestion("");
              }}
            >
              <Search size={15} aria-hidden="true" />
              <span className="widget-action-label">Investigate</span>
            </button>
          )}
        </div>
        {component.type === "metric" ? (
          <>
            <div className="metric-value">
              {component.formatted_value ?? valueText(component.value)}
            </div>
            {definition?.type === "metric" && definition.metric.number_format !== undefined && (
              <MetricFormatEditor key={`${revision?.revision_id}:${component.id}`} title={component.title}
                format={definition.metric.number_format} disabled={disabled}
                onSave={(format) => void saveMetricFormat(component.id, format)} />
            )}
            {component.body && (
              <p className="muted small">{component.body}</p>
            )}
          </>
        ) : component.type === "chart" ? (
          component.chart_id || component.figure ? (
            <ChartFigure
              key={component.chart_id ?? component.result_id ?? component.id}
              threadId={threadId}
              chartId={component.chart_id ?? undefined}
              figure={component.figure ?? undefined}
              title={component.title}
              resultId={component.analysis_result_id ?? component.result_id ?? undefined}
              selectionFields={component.selection_fields}
              interactionDisabled={disabled}
              onInvestigate={(selection, intent) => void perform("drill", {
                component_id: component.id,
                selection,
                question: intent === "explain"
                  ? `Explain the selected ${selection.column} observations within the applied dashboard scope. State supported patterns and limitations.`
                  : `Compare the selected ${selection.column} values with the other values of that field within the applied dashboard scope. State the comparison population and units.`,
              })}
            />
          ) : (
            <Empty title="No data for this selection">
              Adjust the filters to see a chart. The previous chart is
              preserved in its earlier revision.
            </Empty>
          )
        ) : component.type === "table" ? (
          <>
            <DataTable
              columns={component.columns ?? undefined}
              rows={component.rows ?? []}
            />
            <p className="small muted">
              Preview: at most 10 rows
              {component.row_count != null
                ? ` of ${component.row_count.toLocaleString()}`
                : ""}
              .
            </p>
          </>
        ) : (
          <div className="markdown">
            <ReactMarkdown>{component.body ?? ""}</ReactMarkdown>
          </div>
        )}
        {component.warnings?.map((warning, i) => (
          <p className="small warning-text" key={i}>
            {warning}
          </p>
        ))}
        {component.notes?.map((note, i) => (
          <p className="small muted" key={`note-${i}`}>{note}</p>
        ))}
      </section>
    );
  }
  return (
    <div className="dashboard-panel">
      {error && <Notice error>{error}</Notice>}
      {dashboard && revision ? (
        <>
          <div className="canvas-heading dashboard-heading">
            <div>
              <h2>{revision.spec.title}</h2>
              <div className="dashboard-meta" aria-label="Dashboard details">
                <span>
                  <PanelsTopLeft size={14} aria-hidden="true" />
                  {dataPanelCount} data {dataPanelCount === 1 ? "panel" : "panels"}
                </span>
                <span>Version {revision.version}</span>
                <span>
                  <Clock3 size={14} aria-hidden="true" />
                  Saved {new Date(revision.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                </span>
              </div>
              {description && <p className="dashboard-deck">{deck}</p>}
              {description.length > 220 && <details className="dashboard-scope"><summary>Scope and method</summary><p>{description}</p></details>}
            </div>
            <div className="button-group">
              <button disabled={disabled} onClick={() => setEditing(!editing)}>
                <Pencil size={15} aria-hidden="true" />
                Edit view
              </button>
              <button
                disabled={disabled}
                onClick={() => void perform("refresh")}
              >
                <RefreshCw size={15} aria-hidden="true" />
                Refresh data
              </button>
            </div>
          </div>
          {pending && (
            <Notice>
              Updating this dashboard. The last saved view remains visible until
              its new evidence and report are ready.
            </Notice>
          )}
          {dashboard.pending_action?.status === "failed" && (
            <Notice error>
              {dashboard.pending_action.error ||
                "The update failed. The last valid dashboard is preserved. You can retry."}
            </Notice>
          )}
          <div className={`filter-bar ${dashboard.filters.length ? "" : "is-empty"}`}>
            <div className="filter-toolbar-heading">
              <div>
                <h3><Filter size={16} aria-hidden="true" />Filters</h3>
                <p className="small muted">
                  Selections change the dashboard when you apply them.
                </p>
              </div>
              <span
                className={`filter-draft-state ${changedFilterCount ? "is-dirty" : ""}`}
                role="status"
                aria-live="polite"
                aria-atomic="true"
              >
                {changedFilterCount
                  ? `${changedFilterCount} unapplied filter ${changedFilterCount === 1 ? "change" : "changes"}`
                  : dashboard.filters.length ? "Selections are applied" : "No active filters"}
              </span>
            </div>
            <div className="filter-fields">
              {dashboard.filters.length === 0 ? (
                <span className="small muted">All saved observations</span>
              ) : (
                dashboard.filters.map((filter) => (
                  <div className="filter-field" key={filter.id}>
                    {filter.kind === "date_range" ? (
                      <fieldset>
                        <legend>{filter.label}</legend>
                        <div className="date-pair">
                          <input
                            aria-label={`${filter.label} start`}
                            type="date"
                            disabled={disabled}
                            value={String(values[filter.id]?.[0] ?? "")}
                            onChange={(e) =>
                              setValues({
                                ...values,
                                [filter.id]: [
                                  e.target.value,
                                  values[filter.id]?.[1] ?? "",
                                ],
                              })
                            }
                          />
                          <span>to</span>
                          <input
                            aria-label={`${filter.label} end`}
                            type="date"
                            disabled={disabled}
                            value={String(values[filter.id]?.[1] ?? "")}
                            onChange={(e) =>
                              setValues({
                                ...values,
                                [filter.id]: [
                                  values[filter.id]?.[0] ?? "",
                                  e.target.value,
                                ],
                              })
                            }
                          />
                        </div>
                        <button
                          type="button"
                          disabled={disabled || !values[filter.id]?.length}
                          onClick={() =>
                            setValues({ ...values, [filter.id]: [] })
                          }
                        >
                          All dates
                        </button>
                      </fieldset>
                    ) : (
                      <div>
                        <label htmlFor={`filter-${filter.id}`}>{filter.label}</label>
                        <select
                          id={`filter-${filter.id}`}
                          aria-label={filter.label}
                          aria-describedby={`filter-hint-${filter.id}`}
                          disabled={disabled}
                          multiple
                          size={Math.min(5, Math.max(3, (filter.options?.length ?? 0) + 1))}
                          value={values[filter.id]?.length
                            ? values[filter.id].map((value) => JSON.stringify(value))
                            : [""]}
                          onChange={(e) => {
                            const selected = Array.from(e.target.selectedOptions, (option) => option.value);
                            setValues({
                              ...values,
                              [filter.id]: selected.includes("") && (values[filter.id]?.length ?? 0) > 0
                                ? []
                                : selected.filter(Boolean).map((value) => JSON.parse(value)),
                            });
                          }}
                        >
                          <option value="">All values</option>
                          {(values[filter.id] ?? [])
                            .filter((value) => !filterOptions(filter).some((option) => JSON.stringify(option) === JSON.stringify(value)))
                            .map((value) => (
                              <option key={`entered-${JSON.stringify(value)}`} value={JSON.stringify(value)}>
                                {valueText(value)} (entered)
                              </option>
                            ))}
                          {filterOptions(filter).map((option, i) => (
                            <option key={i} value={JSON.stringify(option)}>
                              {valueText(option)}
                            </option>
                          ))}
                        </select>
                        <p id={`filter-hint-${filter.id}`} className="small muted filter-selection-hint">
                          Select one or more values. Use Ctrl or Command to add a value with a mouse.
                        </p>
                        <FilterValueSearch
                          key={`${revision.revision_id}:${filter.id}`}
                          threadId={threadId}
                          dashboardId={revision.dashboard_id}
                          revisionId={revision.revision_id}
                          filterId={filter.id}
                          label={filter.label}
                          disabled={disabled}
                          onValues={(found, append) => setSearchedOptions((previous) => ({
                            ...previous,
                            [filter.id]: append ? [...(previous[filter.id] ?? []), ...found] : found,
                          }))}
                        />
                        <details className="custom-filter">
                          <summary>Other value</summary>
                          <input
                            aria-label={`${filter.label} custom value`}
                            disabled={disabled}
                            placeholder="Enter an exact value"
                            value={customValues[filter.id] ?? ""}
                            onChange={(e) =>
                              setCustomValues({
                                ...customValues,
                                [filter.id]: e.target.value,
                              })
                            }
                          />
                          <button
                            type="button"
                            aria-label={`Add custom ${filter.label}`}
                            disabled={disabled || !customValues[filter.id]?.trim()}
                            onClick={() =>
                              setValues({
                                ...values,
                                [filter.id]: [...new Set([...(values[filter.id] ?? []), customValues[filter.id]])],
                              })
                            }
                          >
                            Add value
                          </button>
                        </details>
                      </div>
                    )}
                    {filter.options_truncated && (
                      <span className="small muted">
                        More values are available. Search saved values or enter an exact value under Other value.
                      </span>
                    )}
                  </div>
                ))
              )}
            </div>
            <div className="button-group filter-actions">
              <button
                aria-label="Add filter"
                disabled={disabled}
                onClick={() => setAddingFilter(true)}
              >
                <Plus size={15} />
                Add filter
              </button>
              {changedFilterCount > 0 && (
                <button
                  disabled={disabled}
                  onClick={() =>
                    setValues(
                      Object.fromEntries(
                        dashboard.filters.map((filter) => [
                          filter.id,
                          revision.applied_filters[filter.id] ?? [],
                        ]),
                      ),
                    )
                  }
                >
                  Use applied values
                </button>
              )}
              {dashboard.filters.length > 0 && (
                <button
                  className="primary"
                  disabled={
                    disabled ||
                    changedFilterCount === 0 ||
                    dashboard.filters.some(
                      (f) =>
                        f.kind === "date_range" &&
                        (values[f.id]?.length ?? 0) > 0 &&
                        values[f.id]?.some((v) => !v),
                    )
                  }
                  onClick={() => void perform("filter")}
                >
                  {working ? "Applying…" : "Apply filters"}
                </button>
              )}
            </div>
          </div>
          {Object.values(revision.applied_filters).some(
            (v) => v.length > 0,
          ) && (
            <div className="applied-state small">
              <Check size={14} aria-hidden="true" />
              Applied:{" "}
              {dashboard.filters
                .filter(
                  (f) => (revision.applied_filters[f.id]?.length ?? 0) > 0,
                )
                .map(
                  (f) =>
                    `${f.label}: ${revision.applied_filters[f.id].map(valueText).join(" – ")}`,
                )
                .join(" · ")}
            </div>
          )}
          {editing && (
            <section className="view-editor">
              <h3>Edit the saved view</h3>
              <label>
                Dashboard title
                <input
                  aria-label="Dashboard title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={200}
                />
              </label>
              <div className="layout-list">
                {order.map((id, i) => {
                  const component = components.find((c) => c.id === id);
                  return (
                    <div key={id}>
                      <span>
                        {component?.title || component?.type}
                      </span>
                      <label className="sr-only" htmlFor={`span-${id}`}>
                        Width for {component?.title || id}
                      </label>
                      <select
                        id={`span-${id}`}
                        value={spans[id] ?? 1}
                        onChange={(e) =>
                          setSpans({ ...spans, [id]: Number(e.target.value) })
                        }
                      >
                        <option value={1}>One column</option>
                        <option value={2}>Two columns</option>
                        <option value={3}>Full width</option>
                      </select>
                      <button
                        aria-label={`Move ${component?.title || id} up`}
                        disabled={i === 0}
                        onClick={() => move(id, -1)}
                      >
                        <ArrowUp size={15} />
                      </button>
                      <button
                        aria-label={`Move ${component?.title || id} down`}
                        disabled={i === order.length - 1}
                        onClick={() => move(id, 1)}
                      >
                        <ArrowDown size={15} />
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="form-actions">
                <button onClick={() => setEditing(false)}>Cancel edits</button>
                <button
                  className="primary"
                  disabled={disabled || !title.trim()}
                  onClick={() => void saveView()}
                >
                  Save view
                </button>
              </div>
            </section>
          )}
          <div className="dashboard-grid">
            {groups.map((group) => !editing && group[0].type === "metric" && group[0].span === 1 ? (
              <div className="metric-strip" key={`metrics-${group[0].id}`}>{group.map(renderComponent)}</div>
            ) : group.map(renderComponent))}
          </div>
          <EvidencePanel dashboard={dashboard} />
          <div className="freshness">
            <span>
              Source completeness:{" "}
              {dashboard.freshness.every((f) => f.completeness === "unknown")
                ? "unknown"
                : "see evidence"}
            </span>
            <span>
              {dashboard.freshness.some((f) => f.snapshot_kind === "upload")
                ? "Files are saved snapshots. Import updated files to use new content."
                : "Refresh preserves the question and records new evidence."}
            </span>
          </div>
        </>
      ) : answer?.report ? (
        <>
          <div className="canvas-heading">
            <div>
              <p className="eyebrow">Saved findings</p>
              <h2>{answer.report.title}</h2>
              <p className="muted">
                Save these findings as a dashboard to arrange panels and declare
                filters.
              </p>
            </div>
            <button
              className="primary"
              disabled={busy || !runId}
              onClick={() => {
                setTitle(answer.report!.title);
                setSaveDialog(true);
              }}
            >
              <BookmarkPlus size={16} />
              Save dashboard
            </button>
          </div>
          {answer.charts.length ? (
            <div className="dashboard-grid">
              {answer.charts.map((chart) => (
                <section
                  className="dashboard-widget span-3"
                  key={chart.chart_id}
                >
                  <h3>{chart.title}</h3>
                  <ChartFigure
                    threadId={threadId}
                    chartId={chart.chart_id}
                    title={chart.title}
                    resultId={chart.result_id}
                  />
                  {runId && onPresentationSaved && (
                    <ChartEditor
                      key={`${answer.report?.report_id}:${chart.chart_id}`}
                      chart={chart}
                      reportId={answer.report!.report_id}
                      runId={runId}
                      disabled={busy}
                      onSaved={(updated) => {
                        if (isCurrent(identity)) onPresentationSaved(updated);
                      }}
                    />
                  )}
                </section>
              ))}
            </div>
          ) : (
            <Empty title="Your findings are ready" icon={LayoutDashboard}>
              Save a dashboard to arrange the report's metrics and tables.
            </Empty>
          )}
        </>
      ) : (
        <Empty
          title="Your dashboard starts with a question"
          icon={LayoutDashboard}
        >
          Ask for the metrics, comparisons or trends you need. Saved charts,
          tables and reports will appear here.
        </Empty>
      )}
      {saveDialog && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="save-title"
          >
            <div className="section-heading">
              <h2 id="save-title">Save dashboard</h2>
              <button
                aria-label="Cancel save dashboard"
                onClick={() => setSaveDialog(false)}
              >
                <X size={20} />
              </button>
            </div>
            <label>
              Dashboard title
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
              />
            </label>
            <p className="muted small">
              The dashboard keeps exact links to the published evidence and
              report.
            </p>
            <button
              className="primary"
              disabled={working || !title.trim()}
              onClick={() => void save()}
            >
              {working ? "Saving…" : "Create dashboard"}
            </button>
          </section>
        </div>
      )}
      {addingFilter && dashboard && (
        <FilterBuilder
          dashboard={dashboard}
          onClose={() => setAddingFilter(false)}
          busy={working}
          onSave={(filter) =>
            void saveView([...dashboard.revision.spec.filters, filter])
          }
        />
      )}
      {drill && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="drill-title"
          >
            <div className="section-heading">
              <h2 id="drill-title">
                Investigate {drill.title || "this component"}
              </h2>
              <button
                aria-label="Close investigation"
                onClick={() => setDrill(null)}
              >
                <X size={20} />
              </button>
            </div>
            <label>
              What would you like to investigate?
              <textarea
                aria-label="Investigation question"
                value={drillQuestion}
                onChange={(e) => setDrillQuestion(e.target.value)}
                placeholder="For example, break this down by month."
              />
            </label>
            <p className="small muted">
              This starts a new analysis using this component and the applied
              filters as context.
            </p>
            <button
              className="primary"
              disabled={working || !drillQuestion.trim()}
              onClick={() =>
                void perform("drill", {
                  component_id: drill.id,
                  question: drillQuestion.trim(),
                })
              }
            >
              Start investigation
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

function FilterBuilder({
  dashboard,
  onClose,
  busy,
  onSave,
}: {
  dashboard: Dashboard;
  onClose: () => void;
  busy: boolean;
  onSave: (filter: DashboardFilter) => void;
}) {
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"category" | "date_range">("category");
  const [description, setDescription] = useState("");
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [columns, setColumns] = useState<Record<string, string[]>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let ignore = false;
    const components = dashboard.components.filter((c) => c.result_id);
    Promise.all(
      components.map(async (c) => {
        const result = await api<ResultPage>(
          `/api/results/${c.analysis_result_id ?? c.result_id}?limit=1`,
        );
        return [c.id, result.columns] as const;
      }),
    )
      .then((items) => {
        if (!ignore) {
          setColumns(Object.fromEntries(items));
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!ignore) {
          setError(message(e));
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [dashboard.revision.revision_id]);
  return (
    <div className="modal-backdrop">
      <section
        className="modal wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="filter-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Explicit business scope</p>
            <h2 id="filter-title">Add a dashboard filter</h2>
          </div>
          <button aria-label="Cancel add filter" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <div className="form-grid">
          <label>
            Filter label
            <input
              aria-label="Filter label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={100}
            />
          </label>
          <label>
            Filter type
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as typeof kind)}
            >
              <option value="category">Category</option>
              <option value="date_range">Date range</option>
            </select>
          </label>
        </div>
        <label>
          Business meaning and scope
          <textarea
            aria-label="Filter meaning"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe the shared business dimension and which panels should change."
          />
        </label>
        <p className="small muted">
          Choose the affected panels and their exact columns. Matching names
          alone do not establish a shared business meaning.
        </p>
        {loading ? (
          <Loading label="Checking available columns…" />
        ) : (
          <div className="binding-list">
            {dashboard.components
              .filter((c) => c.result_id)
              .map((c) => (
                <label key={c.id}>
                  {c.title || c.type}
                  <select
                    aria-label={`Filter column for ${c.title || c.id}`}
                    value={bindings[c.id] ?? ""}
                    onChange={(e) =>
                      setBindings({ ...bindings, [c.id]: e.target.value })
                    }
                  >
                    <option value="">Unaffected</option>
                    {(columns[c.id] ?? []).map((column) => (
                      <option key={column}>{column}</option>
                    ))}
                  </select>
                </label>
              ))}
          </div>
        )}
        {error && <Notice error>{error}</Notice>}
        <div className="form-actions">
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            disabled={
              busy ||
              loading ||
              !label.trim() ||
              !description.trim() ||
              !Object.values(bindings).some(Boolean)
            }
            onClick={() =>
              onSave({
                id: `filter-${crypto.randomUUID()}`,
                label: label.trim(),
                kind,
                description: description.trim(),
                default_values: [],
                bindings: Object.entries(bindings)
                  .filter(([, column]) => column)
                  .map(([component_id, column]) => ({ component_id, column })),
              })
            }
          >
            {busy ? "Saving…" : "Save filter"}
          </button>
        </div>
      </section>
    </div>
  );
}
