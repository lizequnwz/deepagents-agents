import { useEffect, useId, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import {
  AlertCircle,
  LoaderCircle,
  Table2,
  Download,
  ChevronLeft,
  ChevronRight,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  RefreshCw,
} from "lucide-react";
import { api, message } from "./api";
import type { ResultPage, Row } from "./types";
import {
  pointSelectionValues,
  traceSelectionValues,
} from "./chartInteractions";
import type { ChartPoint, ChartSelection, ChartSelectionField, SelectionValue } from "./chartInteractions";

interface InteractiveChartElement extends HTMLDivElement {
  on: (event: string, listener: (event: { points?: ChartPoint[] }) => void) => void;
  removeListener: (event: string, listener: (event: { points?: ChartPoint[] }) => void) => void;
}

export function Notice({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`notice ${error ? "danger" : ""}`}
      role={error ? "alert" : "status"}
    >
      <AlertCircle size={16} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
export function Loading({
  label = "Loading saved evidence…",
}: {
  label?: string;
}) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} aria-hidden="true" />
      {label}
    </div>
  );
}
export function Empty({
  title,
  children,
  icon = Table2,
}: {
  title: string;
  children: React.ReactNode;
  icon?: typeof Table2;
}) {
  const Icon = icon;
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={25} aria-hidden="true" />
      </div>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function valueText(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
export function tableValueText(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value) || Number.isInteger(value)) return valueText(value);
  return new Intl.NumberFormat(undefined, {
    maximumSignificantDigits: 12,
    notation: value !== 0 && Math.abs(value) < 0.000001 ? "scientific" : "standard",
  }).format(value);
}
export function DataTable({
  rows,
  columns,
  caption,
}: {
  rows: Row[];
  columns?: string[];
  caption?: string;
}) {
  const [sort, setSort] = useState<{
    column: string;
    direction: "ascending" | "descending";
  } | null>(null);
  const hintId = useId();
  useEffect(() => setSort(null), [rows, columns]);
  const cols = columns?.length ? columns : Object.keys(rows[0] ?? {});
  const preview = rows.slice(0, 10);
  const displayRounding = preview.some((row) => cols.some((column) =>
    typeof row[column] === "number" && tableValueText(row[column]) !== valueText(row[column]),
  ));
  const numericColumns = new Set(
    cols.filter((column) => {
      const values = preview
        .map((row) => row[column])
        .filter((value) => value != null);
      return (
        values.length > 0 &&
        values.every((value) => typeof value === "number")
      );
    }),
  );
  if (sort && cols.includes(sort.column)) {
    preview.sort((a, b) => {
      const first = a[sort.column];
      const second = b[sort.column];
      if (first == null) return second == null ? 0 : 1;
      if (second == null) return -1;
      const comparison =
        typeof first === "number" && typeof second === "number"
          ? first - second
          : valueText(first).localeCompare(valueText(second));
      return sort.direction === "ascending" ? comparison : -comparison;
    });
  }
  return (
    <div className="data-table">
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label={caption || "Saved data preview"}
        aria-describedby={rows.length > 1 ? hintId : undefined}
      >
        <table>
          <caption className={caption ? "" : "sr-only"}>
            {caption || "Saved data preview"}
          </caption>
          <thead>
            <tr>
              {cols.map((column) => (
                <th
                  key={column}
                  scope="col"
                  aria-label={column}
                  aria-sort={sort?.column === column ? sort.direction : "none"}
                  className={numericColumns.has(column) ? "is-numeric" : undefined}
                >
                  {rows.length > 1 ? (
                    <button
                      type="button"
                      className="table-heading-sort"
                      aria-label={`Sort shown rows by ${column}`}
                      onClick={() =>
                        setSort({
                          column,
                          direction:
                            sort?.column === column && sort.direction === "ascending"
                              ? "descending"
                              : "ascending",
                        })
                      }
                    >
                      <span>{column}</span>
                      {sort?.column === column ? (
                        sort.direction === "ascending" ? (
                          <ArrowUp size={13} aria-hidden="true" />
                        ) : (
                          <ArrowDown size={13} aria-hidden="true" />
                        )
                      ) : (
                        <ArrowUpDown size={13} aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    column
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.map((row, i) => (
              <tr key={i}>
                {cols.map((column) => (
                  <td
                    key={column}
                    className={numericColumns.has(column) ? "is-numeric" : undefined}
                  >
                    {tableValueText(row[column]) !== valueText(row[column]) ? (
                      <span className="exact-value" tabIndex={0} title={`Exact stored value: ${valueText(row[column])}`}
                        aria-label={`${tableValueText(row[column])}. Exact stored value: ${valueText(row[column])}`}>
                        {tableValueText(row[column])}
                      </span>
                    ) : valueText(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="muted table-empty">No rows match this view.</p>
        )}
      </div>
      {displayRounding && <p className="table-sort-hint small muted">Display rounding only. Inspect a number for its exact saved value.</p>}
      {rows.length > 1 && (
        <p id={hintId} className="table-sort-hint small muted">
          Column headings sort the shown rows only.
        </p>
      )}
    </div>
  );
}

export function ChartFigure({
  threadId,
  chartId,
  figure,
  title,
  resultId,
  selectionFields = [],
  onInvestigate,
  interactionDisabled = false,
}: {
  threadId: string;
  chartId?: string;
  figure?: { data: unknown[]; layout: Row };
  title?: string;
  resultId?: string;
  selectionFields?: ChartSelectionField[];
  onInvestigate?: (selection: ChartSelection, intent: "explain" | "compare") => void;
  interactionDisabled?: boolean;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [annotations, setAnnotations] = useState<string[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [showData, setShowData] = useState(false);
  const [traces, setTraces] = useState<unknown[]>([]);
  const [selectionColumn, setSelectionColumn] = useState("");
  const [selectedValues, setSelectedValues] = useState<SelectionValue[]>([]);
  const [selectionError, setSelectionError] = useState("");
  const descriptionId = useId();
  const selectionHintId = useId();
  const field = selectionFields.find((field) => field.column === selectionColumn) ?? selectionFields[0];
  const selectionContext = useRef({ field, disabled: interactionDisabled });
  selectionContext.current = { field, disabled: interactionDisabled };
  const options = field ? traceSelectionValues(field, traces) : [];
  const visibleOptions = [...new Map([...options, ...selectedValues].map((value) => [JSON.stringify(value), value])).values()];
  function selectValues(values: SelectionValue[]) {
    setSelectionError(values.length > 100 ? "Select at most 100 values for an investigation." : "");
    setSelectedValues(values.length > 100 ? [] : values);
  }
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let observer: ResizeObserver | undefined;
    let themeObserver: MutationObserver | undefined;
    let plotly: PlotlyAPI | undefined;
    let pointListener: ((event: { points?: ChartPoint[] }) => void) | undefined;
    const element = target.current;
    setError("");
    setLoading(true);
    setAnnotations([]);
    setTraces([]);
    setSelectedValues([]);
    setSelectionError("");
    const data = figure
      ? Promise.resolve(figure)
      : api<{
          data: unknown[];
          layout: Row;
          warnings?: string[];
          notes?: string[];
        }>(`/api/conversations/${threadId}/charts/${chartId}/figure`, {
          signal: controller.signal,
        });
    data
      .then(async (data) => {
        if (cancelled || !element?.isConnected) return;
        if ("warnings" in data || "notes" in data) {
          const annotated = data as {
            warnings?: string[];
            notes?: string[];
          };
          setAnnotations([
            ...new Set([...(annotated.warnings ?? []), ...(annotated.notes ?? [])]),
          ]);
        }
        plotly = Plotly;
        await plotly.react(
          element,
          data.data,
          {
            ...data.layout,
            title: { text: "" },
            autosize: true,
            height: 320,
            margin: { l: 48, r: 22, t: 32, b: 46 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: {
              family: getComputedStyle(element).fontFamily,
              color: getComputedStyle(element).color,
            },
          },
          {
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: ["sendDataToCloud"],
          },
        );
        if (cancelled || !element.isConnected) return;
        setTraces(data.data);
        pointListener = (event) => {
          const { field, disabled } = selectionContext.current;
          if (cancelled || disabled || !field) return;
          selectValues(pointSelectionValues(field, event?.points ?? []));
        };
        const chart = element as InteractiveChartElement;
        chart.on("plotly_click", pointListener);
        chart.on("plotly_selected", pointListener);
        observer = new ResizeObserver(() => {
          if (
            !cancelled &&
            element.isConnected &&
            element.offsetWidth > 0 &&
            element.offsetHeight > 0 &&
            plotly
          )
            void Promise.resolve(plotly.Plots.resize(element)).catch(() => {});
        });
        observer.observe(element);
        themeObserver = new MutationObserver(() => {
          if (!cancelled && element.isConnected && plotly)
            void plotly
              .relayout(element, {
                "font.color": getComputedStyle(element).color,
              })
              .catch(() => {});
        });
        themeObserver.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme"],
        });
        setLoading(false);
      })
      .catch((error) => {
        if (!cancelled) {
          setError(message(error));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
      observer?.disconnect();
      themeObserver?.disconnect();
      if (element && pointListener) {
        const chart = element as InteractiveChartElement;
        chart.removeListener("plotly_click", pointListener);
        chart.removeListener("plotly_selected", pointListener);
      }
      if (element && plotly) plotly.purge(element);
    };
  }, [threadId, chartId, figure, attempt]);
  return (
    <div className="chart-shell">
      <div className="chart-visual" aria-busy={loading}>
        {loading && (
          <div className="chart-skeleton" role="status">
            <div className="skeleton-grid" aria-hidden="true">
              <span /><span /><span />
            </div>
            <span>Preparing chart…</span>
          </div>
        )}
        {error && (
          <div className="chart-error">
            <Notice error>
              <strong>Chart unavailable</strong>
              <p>{error}</p>
            </Notice>
            <button type="button" onClick={() => setAttempt((value) => value + 1)}>
              <RefreshCw size={15} aria-hidden="true" />
              Try chart again
            </button>
          </div>
        )}
        <div
          ref={target}
          className="plotly-chart"
          role="img"
          aria-label={
            title
              ? `${title}. Interactive chart from saved evidence.`
              : "Interactive chart from saved evidence"
          }
          aria-describedby={descriptionId}
          style={{ visibility: loading || error ? "hidden" : "visible" }}
        />
      </div>
      <p id={descriptionId} className="sr-only">
        Use the chart legend to identify its series.{" "}
        {resultId
          ? "Open View chart data for a keyboard-accessible table and complete data download."
          : "Saved data and downloads are available in the Data tab."}
      </p>
      {annotations.map((annotation) => (
        <p className="small warning-text" key={annotation}>{annotation}</p>
      ))}
      {field && resultId && onInvestigate && !loading && !error && (
        <div className="chart-selection">
          <p className="small muted" id={selectionHintId}>
            Select chart marks or use the list. A selection gives context to a new investigation. Applied filters stay the same.
          </p>
          {selectionFields.length > 1 && (
            <label>Selection field
              <select value={field.column} disabled={interactionDisabled}
                onChange={(event) => { setSelectionColumn(event.target.value); selectValues([]); }}>
                {selectionFields.map((field) => <option key={field.column} value={field.column}>{field.label}</option>)}
              </select>
            </label>
          )}
          {visibleOptions.length > 0 && (
            <label>Select {field.label} to investigate
              <select multiple size={Math.min(4, Math.max(2, visibleOptions.length))}
                aria-label={`Select ${field.label} to investigate`}
                aria-describedby={selectionHintId} disabled={interactionDisabled}
                value={selectedValues.map((value) => JSON.stringify(value))}
                onChange={(event) => selectValues(Array.from(event.target.selectedOptions, (option) => JSON.parse(option.value)))}>
                {visibleOptions.map((value) => <option key={JSON.stringify(value)} value={JSON.stringify(value)}>{valueText(value)}</option>)}
              </select>
            </label>
          )}
          <p className="selection-summary small" role="status" aria-live="polite" aria-atomic="true">
            {selectedValues.length ? `Selected ${field.label}: ${selectedValues.map(valueText).join(", ")}` : `No ${field.label} values selected.`}
          </p>
          {selectionError && <Notice error>{selectionError}</Notice>}
          <div className="button-group">
            <button type="button" disabled={interactionDisabled || !selectedValues.length}
              onClick={() => onInvestigate({ result_id: resultId, column: field.column, values: selectedValues }, "explain")}>Explain selection</button>
            <button type="button" disabled={interactionDisabled || !selectedValues.length}
              onClick={() => onInvestigate({ result_id: resultId, column: field.column, values: selectedValues }, "compare")}>Compare selection</button>
            {selectedValues.length > 0 && <button type="button" disabled={interactionDisabled} onClick={() => selectValues([])}>Clear selection</button>}
          </div>
        </div>
      )}
      {resultId && (
        <details
          className="chart-data-access"
          onToggle={(event) => setShowData(event.currentTarget.open)}
        >
          <summary>
            <Table2 size={14} aria-hidden="true" />View chart data
          </summary>
          {showData && <DatasetPreview resultId={resultId} />}
        </details>
      )}
    </div>
  );
}

export function DatasetPreview({ resultId }: { resultId: string }) {
  const [data, setData] = useState<ResultPage | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState({ resultId, offset: 0 });
  const [attempt, setAttempt] = useState(0);
  const offset = page.resultId === resultId ? page.offset : 0;
  useEffect(() => {
    let ignore = false;
    setData(null);
    setError("");
    api<ResultPage>(`/api/results/${resultId}?limit=10&offset=${offset}`)
      .then((r) => {
        if (!ignore) setData(r);
      })
      .catch((e) => {
        if (!ignore) setError(message(e));
      });
    return () => {
      ignore = true;
    };
  }, [resultId, offset, attempt]);
  if (error)
    return (
      <div className="data-error">
        <Notice error>{error}</Notice>
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          <RefreshCw size={15} aria-hidden="true" />Try data again
        </button>
      </div>
    );
  if (!data || data.result_id !== resultId || data.offset !== offset)
    return <Loading />;
  return (
    <div>
      <div className="section-heading">
        <div>
          <h3>{data.short_label}</h3>
          <p className="muted">
            {data.row_count.toLocaleString()} saved rows ·{" "}
            {data.truncated ? "Incomplete extraction" : "Complete extraction"}
          </p>
        </div>
        <a
          className="button secondary small"
          href={`/api/results/${resultId}/download?format=csv`}
        >
          <Download size={14} />
          CSV
        </a>
      </div>
      <DataTable rows={data.rows} columns={data.columns} />
      <div className="pagination">
        <span>
          Rows {data.row_count ? offset + 1 : 0}–
          {Math.min(offset + 10, data.row_count)} of{" "}
          {data.row_count.toLocaleString()}
        </span>
        <div className="button-group">
          <button
            aria-label="Previous data page"
            disabled={offset === 0}
            onClick={() => setPage({ resultId, offset: Math.max(0, offset - 10) })}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            aria-label="Next data page"
            disabled={offset + 10 >= data.row_count}
            onClick={() => setPage({ resultId, offset: offset + 10 })}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      <details>
        <summary>Query and provenance</summary>
        <pre>
          {data.executed_sql || "Reviewed file snapshot. No source query."}
        </pre>
        <a href={`/api/results/${resultId}/download?format=parquet`}>
          Download typed Parquet
        </a>
      </details>
    </div>
  );
}
