import { useId, useState } from "react";
import { Pencil } from "lucide-react";
import { post, message } from "./api";
import { Notice } from "./components";
import type { Answer, Chart } from "./types";

interface EditableChart extends Chart {
  x_label?: string | null;
  y_label?: string | null;
  secondary_y_label?: string | null;
  secondary_y?: string | null;
  palette?: string;
}

const chartTypes = ["bar", "line", "area", "scatter", "pie", "histogram", "box", "heatmap", "map", "waterfall", "funnel"];
const palettes = ["default", "blues", "viridis", "plasma", "teal", "sunset", "red_blue"];

export function ChartEditor({ chart, reportId, runId, disabled, onSaved }: {
  chart: EditableChart;
  reportId: string;
  runId: string;
  disabled: boolean;
  onSaved: (answer: Answer) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(chart.title);
  const [xLabel, setXLabel] = useState(chart.x_label ?? "");
  const [yLabel, setYLabel] = useState(chart.y_label ?? "");
  const [secondaryLabel, setSecondaryLabel] = useState(chart.secondary_y_label ?? "");
  const [chartType, setChartType] = useState(chart.chart_type);
  const [palette, setPalette] = useState(chart.palette ?? "default");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const panelId = useId();
  const changes = {
    ...(title.trim() !== chart.title ? { title: title.trim() } : {}),
    ...(xLabel !== (chart.x_label ?? "") ? { x_label: xLabel || null } : {}),
    ...(yLabel !== (chart.y_label ?? "") ? { y_label: yLabel || null } : {}),
    ...(secondaryLabel !== (chart.secondary_y_label ?? "") ? { secondary_y_label: secondaryLabel || null } : {}),
    ...(chartType !== chart.chart_type ? { chart_type: chartType } : {}),
    ...(palette !== (chart.palette ?? "default") ? { palette } : {}),
  };
  async function save() {
    setBusy(true);
    setError("");
    try {
      const answer = await post<Answer>(`/api/runs/${runId}/presentation`, {
        report_id: reportId,
        chart_id: chart.chart_id,
        ...changes,
      });
      onSaved(answer);
      setEditing(false);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  function open() {
    setTitle(chart.title);
    setXLabel(chart.x_label ?? "");
    setYLabel(chart.y_label ?? "");
    setSecondaryLabel(chart.secondary_y_label ?? "");
    setChartType(chart.chart_type);
    setPalette(chart.palette ?? "default");
    setError("");
    setEditing(true);
  }
  return (
    <div className="chart-editor">
      <button type="button" disabled={disabled || busy} aria-expanded={editing} aria-controls={panelId}
        onClick={() => editing ? setEditing(false) : open()}>
        <Pencil size={14} aria-hidden="true" />Edit chart
      </button>
      {editing && (
        <form id={panelId} className="chart-editor-form" aria-label={`Edit ${chart.title}`}
          onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <p className="small muted">Save display changes to this chart and its report. The saved data stays the same.</p>
          <fieldset disabled={disabled || busy}>
            <legend className="sr-only">Chart display</legend>
            <label>Chart title<input value={title} maxLength={160} required onChange={(event) => setTitle(event.target.value)} /></label>
            <div className="chart-editor-fields">
              <label>Chart type<select aria-label="Chart type" value={chartType} onChange={(event) => setChartType(event.target.value)}>
                {chartTypes.map((type) => <option key={type} value={type}>{type[0].toUpperCase() + type.slice(1)}</option>)}
              </select></label>
              <label>Color palette<select aria-label="Color palette" value={palette} onChange={(event) => setPalette(event.target.value)}>
                {palettes.map((value) => <option key={value} value={value}>{value === "red_blue" ? "Red and blue" : value[0].toUpperCase() + value.slice(1)}</option>)}
              </select></label>
              <label>X-axis label<input value={xLabel} maxLength={80} onChange={(event) => setXLabel(event.target.value)} placeholder="Use saved field label" /></label>
              <label>Y-axis label<input value={yLabel} maxLength={80} onChange={(event) => setYLabel(event.target.value)} placeholder="Use saved field label" /></label>
              {chart.secondary_y && <label>Second Y-axis label<input value={secondaryLabel} maxLength={80} onChange={(event) => setSecondaryLabel(event.target.value)} /></label>}
            </div>
          </fieldset>
          <p className="small muted">A chart type must be valid for its saved data. Incompatible changes leave the current chart in place.</p>
          {error && <Notice error>{error}</Notice>}
          <div className="button-group">
            <button type="button" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
            <button className="primary" disabled={disabled || busy || !title.trim() || Object.keys(changes).length === 0}>
              {busy ? "Saving chart…" : "Save chart"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
