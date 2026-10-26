import { EventSchema } from "@ag-ui/core/schemas";
import { z } from "zod";
import type { Activity } from "./types";

const status = z.enum(["queued", "running", "approval_required", "clarification_required", "completed", "failed", "paused", "stopping"]);
const snapshot = z.object({
  schema_version: z.literal("1.0"), thread_id: z.string(), source_id: z.string(), run_id: z.string(),
  status, phase: z.string(), next_event_id: z.number().int().nonnegative(),
  report_ready: z.boolean(), findings_ready: z.boolean(), answer_ready: z.boolean(),
  clarification: z.object({ interrupt_id: z.string() }).nullable(),
  review: z.object({ interrupt_id: z.string(), review_types: z.array(z.string()), action_count: z.number() }).nullable(),
}).strict();
export type PublicRunState = z.infer<typeof snapshot>;
const activity = z.object({
  id: z.number().int().positive(), kind: z.string(), label: z.string(), phase: z.string(),
  agent: z.string().nullable(), tool_name: z.string().nullable(),
  duration_ms: z.number().nullable(), created_at: z.string(),
}).strict();

/** Attach to saved execution. EventSource reconnects; it never starts a run. */
export function observeRun(threadId: string, runId: string, handlers: {
  state: (value: PublicRunState) => void;
  activity: (value: Activity) => void;
  connection: (value: "connected" | "reconnecting") => void;
  error: (error: Error) => void;
  closed: () => void;
}) {
  const source = new EventSource(`/api/conversations/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/events`);
  source.onopen = () => handlers.connection("connected");
  source.onerror = () => handlers.connection("reconnecting");
  source.onmessage = (message) => {
    try {
      const event = EventSchema.parse(JSON.parse(message.data));
      if (event.type === "RUN_STARTED") {
        if (event.runId !== runId || event.threadId !== threadId || event.protocolVersion !== "1.0")
          throw new Error("The run stream has an incompatible identity or protocol.");
      } else if (event.type === "STATE_SNAPSHOT") {
        const state = snapshot.parse(event.snapshot);
        if (state.run_id !== runId || state.thread_id !== threadId)
          throw new Error("The run state belongs to another conversation.");
        handlers.state(state);
      } else if (event.type === "CUSTOM" && event.name === "analytics.activity") {
        const value = activity.parse(event.value);
        handlers.activity({ id: value.id, kind: value.kind, label: value.label, phase: value.phase,
          ...(value.agent ? { agent: value.agent } : {}),
          ...(value.tool_name ? { tool: { name: value.tool_name } } : {}),
        });
      } else if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
        if (event.type === "RUN_FINISHED" && (event.runId !== runId || event.threadId !== threadId))
          throw new Error("The completion event belongs to another run.");
        source.close();
        handlers.closed();
      } else {
        throw new Error("The run stream contains an unsupported event.");
      }
    } catch (error) {
      source.close();
      handlers.error(error instanceof Error ? error : new Error("The run stream is invalid."));
    }
  };
  return () => source.close();
}

