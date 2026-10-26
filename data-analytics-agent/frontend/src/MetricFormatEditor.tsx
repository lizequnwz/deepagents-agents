import { useState } from "react";

const formats = [
  { value: ",.2f", label: "2 decimal places" },
  { value: ",.0f", label: "Whole numbers" },
  { value: ",.4f", label: "4 decimal places" },
];

export function MetricFormatEditor({ title, format, disabled, onSave }: {
  title: string;
  format: string;
  disabled: boolean;
  onSave: (format: string) => void;
}) {
  const [value, setValue] = useState(format);
  return (
    <details className="metric-format">
      <summary>Number format</summary>
      <div className="metric-format-controls">
        <label>
          <span className="sr-only">Number format for {title}</span>
          <select aria-label={`Number format for ${title}`} disabled={disabled} value={value}
            onChange={(event) => setValue(event.target.value)}>
            {!formats.some((item) => item.value === format) && <option value={format}>Current format ({format})</option>}
            {formats.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
          </select>
        </label>
        <button type="button" disabled={disabled || value === format} onClick={() => onSave(value)}>Save format</button>
      </div>
      <p className="small muted">Display format only. The saved value stays the same.</p>
    </details>
  );
}
