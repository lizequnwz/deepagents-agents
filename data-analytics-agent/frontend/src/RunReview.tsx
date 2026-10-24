import { useEffect, useState } from "react";
import { CheckCheck, MessageCircleQuestion, Play, Square } from "lucide-react";
import { post, message } from "./api";
import { DataTable, Notice } from "./components";
import type { Run } from "./types";

export function RunReview({
  run,
  onUpdate,
}: {
  run: Run;
  onUpdate: () => void;
}) {
  const [decisions, setDecisions] = useState<string[]>([]);
  const [code, setCode] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<string[]>([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setDecisions(run.approval?.actions.map(() => "") ?? []);
    setCode(run.approval?.actions.map((a) => a.query) ?? []);
    setFeedback(run.approval?.actions.map(() => "") ?? []);
    setReply("");
    setError("");
  }, [run.approval?.interrupt_id, run.clarification?.interrupt_id]);
  async function act(path: string, body: unknown = {}) {
    setBusy(true);
    setError("");
    try {
      await post(`/api/runs/${run.run_id}/${path}`, body);
      onUpdate();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const stopButton = (
    <button
      className="stop-button"
      disabled={busy}
      onClick={() => void act("stop")}
    >
      <Square size={12} />
      Stop
    </button>
  );
  if (run.status === "approval_required" && run.approval)
    return (
      <section className="review-panel">
        <div className="review-heading">
          <CheckCheck size={21} />
          <div>
            <h3>Review the proposed calculation</h3>
            <p className="muted small">
              Choose a decision for every proposal. Edited code is executed
              exactly as reviewed.
            </p>
          </div>
        </div>
        {run.approval.actions.map((action, i) => (
          <div className="review-action" key={i}>
            <h4>
              {action.review_type === "python"
                ? "Python analysis"
                : "SQL query"}
            </h4>
            <p className="small">{action.description}</p>
            <p className="small muted">
              {action.source_id && <>Source: {action.source_id} · </>}
              {action.dialect && action.review_type === "sql" && (
                <>{action.dialect} · </>
              )}
              {action.timeout_seconds && (
                <>Time limit: {action.timeout_seconds}s · </>
              )}
              {action.max_result_rows && (
                <>
                  Result limit: {action.max_result_rows.toLocaleString()} rows
                </>
              )}
            </p>
            {action.input_datasets &&
              Object.keys(action.input_datasets).length > 0 && (
                <details className="review-inputs">
                  <summary>
                    Bound input datasets ·{" "}
                    {Object.keys(action.input_datasets).length}
                  </summary>
                  {Object.entries(action.input_datasets).map(
                    ([name, input]) => (
                      <section key={name}>
                        <h4>{name}</h4>
                        <p className="small">
                          {input.row_count.toLocaleString()} saved rows ·{" "}
                          {input.truncated
                            ? "Incomplete extraction"
                            : "Complete extraction"}
                        </p>
                        <p className="small muted">
                          {input.originating_question}
                        </p>
                        <p className="small">
                          Columns: {input.columns.join(", ")}
                        </p>
                        <DataTable
                          rows={input.sample_rows ?? []}
                          columns={input.columns}
                        />
                        <p className="small muted">
                          Preview contains at most 10 rows. Input binding:{" "}
                          {input.result_id}
                        </p>
                      </section>
                    ),
                  )}
                </details>
              )}
            <label>
              Proposed code
              <textarea
                className="code-editor"
                aria-label={`Proposed ${action.review_type} ${i + 1}`}
                value={code[i] ?? action.query}
                readOnly={decisions[i] !== "edit"}
                onChange={(e) =>
                  setCode(code.map((v, j) => (j === i ? e.target.value : v)))
                }
              />
            </label>
            <label>
              Decision
              <select
                aria-label={`Decision ${i + 1}`}
                value={decisions[i] ?? ""}
                onChange={(e) =>
                  setDecisions(
                    decisions.map((v, j) => (j === i ? e.target.value : v)),
                  )
                }
              >
                <option value="">Choose a decision</option>
                {action.allowed_decisions.map((d) => (
                  <option value={d} key={d}>
                    {d === "approve"
                      ? "Approve"
                      : d === "edit"
                        ? "Edit and approve"
                        : "Reject"}
                  </option>
                ))}
              </select>
            </label>
            {decisions[i] === "reject" && (
              <label>
                Feedback
                <textarea
                  value={feedback[i] ?? ""}
                  onChange={(e) =>
                    setFeedback(
                      feedback.map((v, j) => (j === i ? e.target.value : v)),
                    )
                  }
                />
              </label>
            )}
          </div>
        ))}
        {error && <Notice error>{error}</Notice>}
        <button
          className="primary"
          disabled={
            busy ||
            decisions.length !== run.approval.actions.length ||
            decisions.some((d) => !d)
          }
          onClick={() =>
            void act("decisions", {
              interrupt_id: run.approval!.interrupt_id,
              decisions: decisions.map((action, i) => ({
                action,
                ...(action === "edit"
                  ? {
                      [run.approval!.actions[i].review_type === "python"
                        ? "edited_python"
                        : "edited_sql"]: code[i],
                    }
                  : {}),
                ...(action === "reject" ? { feedback: feedback[i] } : {}),
              })),
            })
          }
        >
          {busy ? "Continuing…" : "Submit review"}
        </button>
        {stopButton}
      </section>
    );
  if (run.status === "clarification_required" && run.clarification)
    return (
      <section className="review-panel">
        <div className="review-heading">
          <MessageCircleQuestion size={21} />
          <h3>One detail to clarify</h3>
        </div>
        <p>{run.clarification.question}</p>
        <div className="choice-list">
          {run.clarification.choices.map((choice) => (
            <button
              key={choice}
              className={reply === choice ? "selected" : ""}
              onClick={() => setReply(choice)}
            >
              {choice}
            </button>
          ))}
        </div>
        <label>
          Your answer
          <textarea
            aria-label="Clarification answer"
            value={reply}
            onChange={(e) => setReply(e.target.value)}
          />
        </label>
        {error && <Notice error>{error}</Notice>}
        <button
          className="primary"
          disabled={busy || !reply.trim()}
          onClick={() =>
            void act("clarification", {
              message: reply.trim(),
              interrupt_id: run.clarification!.interrupt_id,
            })
          }
        >
          {busy ? "Continuing…" : "Continue analysis"}
        </button>
        {stopButton}
      </section>
    );
  return (
    <>
      {error && <Notice error>{error}</Notice>}
      {(run.status === "paused" || run.status === "failed") && (
        <div className="recovery">
          <Notice error={run.status === "failed"}>
            {run.error || "This work is paused. Saved evidence is preserved."}
          </Notice>
          <button
            disabled={busy}
            onClick={() => void act(run.findings ? "retry-report" : "resume")}
          >
            <Play size={15} />
            {run.findings ? "Retry report" : "Resume analysis"}
          </button>
        </div>
      )}
      {[
        "queued",
        "running",
        "approval_required",
        "clarification_required",
      ].includes(run.status) && (
        stopButton
      )}
    </>
  );
}
