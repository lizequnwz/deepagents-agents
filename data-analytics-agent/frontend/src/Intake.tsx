import { useEffect, useState } from "react";
import { FileUp, FileText, X, Check, Download, LoaderCircle } from "lucide-react";
import { api, post, query, message } from "./api";
import { DataTable, Loading, Notice } from "./components";
import type { DocumentRef, Row, Upload } from "./types";

const TYPES: Record<string, string> = {
  original: "Keep stored type",
  text: "Text / identifier",
  integer: "Whole number",
  number: "Number (approximate)",
  boolean: "True / false",
  date_iso: "Date: YYYY-MM-DD",
  date_dmy: "Date: DD/MM/YYYY",
  date_mdy: "Date: MM/DD/YYYY",
};
interface Sheet {
  name: string;
  range: string;
  preview: (string | null)[][];
}

export function Attachment({
  threadId,
  disabled = false,
  onComplete,
  onError,
}: {
  threadId?: string;
  disabled?: boolean;
  onComplete: (threadId: string) => void;
  onError: (error: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [workbook, setWorkbook] = useState<{
    file: File;
    sheets: Sheet[];
  } | null>(null);
  const [sheet, setSheet] = useState("");
  const [range, setRange] = useState("");
  const [cached, setCached] = useState(false);
  async function stage(
    file: File,
    selection?: {
      sheet: string;
      cell_range: string;
      use_cached_formulas: boolean;
    },
  ) {
    setBusy(true);
    try {
      const document = /\.(pdf|txt|md)$/i.test(file.name);
      const result = await api<{ thread_id: string }>(
        `/api/${document ? "documents" : "uploads"}?${query({ filename: file.name, thread_id: threadId, ...selection })}`,
        {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/octet-stream" },
        },
      );
      setWorkbook(null);
      onComplete(result.thread_id);
    } catch (e) {
      onError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function choose(file?: File) {
    if (!file) return;
    onError("");
    setBusy(true);
    try {
      if (/\.xlsx$/i.test(file.name)) {
        const result = await api<{ sheets: Sheet[] }>("/api/uploads/workbook", {
          method: "POST",
          body: file,
        });
        if (!result.sheets.length)
          throw new Error("The workbook has no worksheets.");
        setWorkbook({ file, sheets: result.sheets });
        setSheet(result.sheets[0].name);
        setRange(result.sheets[0].range);
        setCached(false);
      } else {
        await stage(file);
      }
    } catch (e) {
      onError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <label
        className={`button secondary attachment-button ${disabled || busy ? "disabled" : ""}`}
        title={busy ? "Importing file" : "Attach file"}
        aria-busy={busy}
      >
        {busy ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <FileUp size={16} aria-hidden="true" />}
        {busy ? "Importing…" : "Attach file"}
        <input
          aria-label="Attach file"
          type="file"
          accept=".csv,.parquet,.xlsx,.pdf,.txt,.md"
          disabled={disabled || busy}
          onChange={(e) => {
            void choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
      {workbook && (
        <div className="modal-backdrop">
          <section
            className="modal wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="workbook-title"
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">Excel table selection</p>
                <h2 id="workbook-title">{workbook.file.name}</h2>
              </div>
              <button
                aria-label="Cancel workbook import"
                disabled={busy}
                onClick={() => setWorkbook(null)}
              >
                <X size={20} />
              </button>
            </div>
            <p>
              Select one table. Include its header and all required data rows.
            </p>
            <div className="form-grid">
              <label>
                Worksheet
                <select
                  value={sheet}
                  onChange={(e) => {
                    setSheet(e.target.value);
                    setRange(
                      workbook.sheets.find((s) => s.name === e.target.value)
                        ?.range ?? "",
                    );
                  }}
                >
                  {workbook.sheets.map((s) => (
                    <option key={s.name}>{s.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Table range
                <input
                  value={range}
                  onChange={(e) => setRange(e.target.value)}
                  placeholder="A1:D100"
                />
              </label>
            </div>
            <DataTable
              rows={(
                workbook.sheets.find((s) => s.name === sheet)?.preview ?? []
              ).map((row) =>
                Object.fromEntries(
                  row.map((v, i) => [String.fromCharCode(65 + i), v]),
                ),
              )}
            />
            <label className="checkbox">
              <input
                type="checkbox"
                checked={cached}
                onChange={(e) => setCached(e.target.checked)}
              />
              Use stored formula values. The app does not recalculate Excel
              formulas.
            </label>
            <div className="form-actions">
              <button onClick={() => setWorkbook(null)} disabled={busy}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={busy || !range}
                onClick={() =>
                  void stage(workbook.file, {
                    sheet,
                    cell_range: range,
                    use_cached_formulas: cached,
                  })
                }
              >
                {busy ? "Importing…" : "Import selected table"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

export function SchemaReview({
  upload,
  onConfirmed,
}: {
  upload: Upload;
  onConfirmed: () => void;
}) {
  const [types, setTypes] = useState<Record<string, string>>({});
  const [grain, setGrain] = useState("");
  const [keys, setKeys] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setTypes(
      Object.fromEntries(upload.columns.map((c) => [c.name, c.suggested_type])),
    );
    setGrain(upload.review?.grain ?? "");
    setKeys(upload.review?.key_columns ?? []);
    setError("");
  }, [upload.upload_id]);
  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await post(
        `/api/conversations/${upload.thread_id}/uploads/${upload.upload_id}/confirm`,
        { types, grain, key_columns: keys },
      );
      onConfirmed();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="schema-review">
      <p className="eyebrow">Review required</p>
      <h2>Confirm the data to analyze</h2>
      <p>
        <strong>{upload.filename}</strong> · {upload.row_count.toLocaleString()}{" "}
        rows · {upload.columns.length} columns
      </p>
      <p className="muted">
        Review types before analysis. Types do not establish business meaning,
        units or source completeness.
      </p>
      {upload.warnings.map((note, i) => (
        <Notice key={i}>{note}</Notice>
      ))}
      <DataTable rows={upload.sample_rows} />
      <p className="small muted">
        Preview contains at most 10 rows. Type and key checks use all imported
        rows.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Column</th>
              <th>Use as</th>
              <th>Missing</th>
              <th>Review note</th>
            </tr>
          </thead>
          <tbody>
            {upload.columns.map((c) => (
              <tr key={c.name}>
                <th scope="row">{c.name}</th>
                <td>
                  <select
                    aria-label={`Type for ${c.name}`}
                    value={types[c.name] ?? c.suggested_type}
                    onChange={(e) =>
                      setTypes({ ...types, [c.name]: e.target.value })
                    }
                  >
                    {Object.entries(TYPES).map(([v, label]) => (
                      <option value={v} key={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{c.null_count}</td>
                <td>{c.warning || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label>
        What does one row represent?{" "}
        <span className="muted small">Optional</span>
        <input
          maxLength={500}
          placeholder="For example, one order line"
          value={grain}
          onChange={(e) => setGrain(e.target.value)}
        />
      </label>
      <fieldset>
        <legend>
          Columns that uniquely identify a row{" "}
          <span className="small muted">Optional</span>
        </legend>
        <div className="checkbox-list">
          {upload.columns.map((c) => (
            <label key={c.name} className="checkbox">
              <input
                type="checkbox"
                checked={keys.includes(c.name)}
                onChange={(e) =>
                  setKeys(
                    e.target.checked
                      ? [...keys, c.name]
                      : keys.filter((k) => k !== c.name),
                  )
                }
              />
              {c.name}
            </label>
          ))}
        </div>
      </fieldset>
      {error && <Notice error>{error}</Notice>}
      <div className="form-actions">
        <button
          className="primary"
          disabled={busy || Object.keys(types).length !== upload.columns.length}
          onClick={() => void confirm()}
        >
          <Check size={16} />
          {busy ? "Checking all rows…" : "Confirm data and continue"}
        </button>
      </div>
    </section>
  );
}

export function DocumentViewer({
  threadId,
  document,
  onImport,
}: {
  threadId: string;
  document: DocumentRef;
  onImport: () => void;
}) {
  const [page, setPage] = useState(1);
  const [content, setContent] = useState<{
    text: string;
    tables: { table_index: number; row_count: number; preview: unknown[][] }[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let ignore = false;
    setContent(null);
    setError("");
    api<typeof content>(
      `/api/conversations/${threadId}/documents/${document.document_id}?page=${page}`,
    )
      .then((r) => {
        if (!ignore) setContent(r);
      })
      .catch((e) => {
        if (!ignore) setError(message(e));
      });
    return () => {
      ignore = true;
    };
  }, [threadId, document.document_id, page]);
  async function importTable(index: number) {
    setBusy(true);
    setError("");
    try {
      await post(
        `/api/conversations/${threadId}/documents/${document.document_id}/tables?table_index=${index}&header_row=0`,
      );
      onImport();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="document-view">
      <div className="section-heading">
        <h3>
          <FileText size={17} />
          {document.filename}
        </h3>
        <a
          className="button secondary small"
          href={`/api/conversations/${threadId}/documents/${document.document_id}/download`}
        >
          <Download size={14} />
          Original
        </a>
      </div>
      {error && <Notice error>{error}</Notice>}
      <label>
        Page
        <select value={page} onChange={(e) => setPage(Number(e.target.value))}>
          {Array.from({ length: document.page_count }, (_, i) => (
            <option key={i} value={i + 1}>
              {i + 1} of {document.page_count}
            </option>
          ))}
        </select>
      </label>
      {!content ? (
        <Loading />
      ) : (
        <>
          <pre className="document-text">
            {content.text || "This page has no extractable text."}
          </pre>
          {content.tables.map((t) => (
            <div className="document-table" key={t.table_index}>
              <h4>
                Extracted table {t.table_index + 1} · {t.row_count} rows
              </h4>
              <DataTable
                rows={
                  t.preview.map((row) =>
                    Object.fromEntries(
                      row.map((value, i) => [`Column ${i + 1}`, value]),
                    ),
                  ) as Row[]
                }
              />
              <p className="small muted">
                Import and review this table before calculation. The first row
                will be its header.
              </p>
              <button
                disabled={busy}
                onClick={() => void importTable(t.table_index)}
              >
                Import table for review
              </button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
