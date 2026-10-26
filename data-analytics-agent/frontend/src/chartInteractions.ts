export type SelectionValue = string | number | boolean | null;

export interface ChartSelection {
  result_id: string;
  column: string;
  values: SelectionValue[];
}

export interface ChartSelectionField {
  column: string;
  label: string;
  point_key: "x" | "y" | "label" | "name";
}

export interface ChartPoint {
  x?: unknown;
  y?: unknown;
  label?: unknown;
  pointNumber?: number;
  data?: { name?: unknown; x?: unknown; y?: unknown; labels?: unknown };
}

export function isSelectionValue(value: unknown): value is SelectionValue {
  return value === null || typeof value === "string" || typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value));
}

export function pointSelectionValues(field: ChartSelectionField, points: ChartPoint[]): SelectionValue[] {
  const unique = new Map<string, SelectionValue>();
  for (const point of points) {
    const source = point.data?.[field.point_key === "label" ? "labels" : field.point_key];
    const index = point.pointNumber;
    // Event coordinates can be formatted dates or labels. The original trace
    // retains the exact saved scalar; its point index does not infer a format.
    const value = field.point_key === "name"
      ? source
      : Array.isArray(source) && typeof index === "number" && Number.isInteger(index) && index >= 0
        ? source[index]
        : point[field.point_key];
    if (isSelectionValue(value)) unique.set(JSON.stringify(value), value);
  }
  return [...unique.values()];
}

export function traceSelectionValues(field: ChartSelectionField, traces: unknown[]): SelectionValue[] {
  const unique = new Map<string, SelectionValue>();
  for (const trace of traces) {
    if (!trace || typeof trace !== "object") continue;
    const properties = trace as Record<string, unknown>;
    const raw = properties[field.point_key === "label" ? "labels" : field.point_key];
    const values = field.point_key === "name" ? [raw] : Array.isArray(raw) ? raw : [];
    for (const value of values) {
      if (isSelectionValue(value)) unique.set(JSON.stringify(value), value);
    }
  }
  return [...unique.values()];
}
