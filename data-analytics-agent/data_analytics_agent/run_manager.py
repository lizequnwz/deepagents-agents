"""Durable execution lifecycle; tools register evidence directly."""

from __future__ import annotations
import asyncio
import json
import time
from data_analytics_agent.approvals import _extract_approval
from data_analytics_agent.diagnostics import RunDiagnosticsCallback
from data_analytics_agent.presentation import resolve_answer
from data_analytics_agent.reporting.schemas import ReportReference, ReportSpec
from data_analytics_agent.reporting.tools import generate_report
from data_analytics_agent.schemas import (
    CoordinatorResponse,
    ChatTurn,
    RunStatus,
)


class AnalysisBudgetEnded(TimeoutError):
    pass


class RunManager:
    def __init__(
        self,
        *,
        conversations,
        runs,
        results,
        analyses=None,
        reports=None,
        agent=None,
        agent_resolver=None,
        source_resolver=None,
        python_execution_limits=None,
        debug_details=False,
        presentation_budget_seconds=120,
    ):
        self.conversations, self.runs, self.results = conversations, runs, results
        self.analyses, self.reports = analyses, reports
        self.agent, self.agent_resolver, self.source_resolver = (
            agent,
            agent_resolver,
            source_resolver,
        )
        self.python_execution_limits = python_execution_limits
        self.presentation_budget_seconds = presentation_budget_seconds
        self.tasks = {}

    def _graph(self, source_id):
        return self.agent_resolver(source_id) if self.agent_resolver else self.agent

    async def start(self, run_id):
        run = self.runs.get(run_id)
        conversation = self.conversations.get(run.thread_id)
        messages = []
        for turn in conversation.turns:
            messages += [
                {"role": "user", "content": turn.user_message},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer": turn.answer.answer,
                            "results": [
                                r.model_dump(mode="json") for r in turn.answer.results
                            ],
                            "analysis_ids": [
                                a.analysis_id for a in turn.answer.analyses
                            ],
                            "chart_ids": [c.chart_id for c in turn.answer.charts],
                            "report_id": turn.answer.report.report_id
                            if turn.answer.report
                            else None,
                        }
                    ),
                },
            ]
        record = self.conversations.investigation(run.thread_id)
        if record:
            messages.append(
                {
                    "role": "user",
                    "content": "Saved investigation context: " + json.dumps(record),
                }
            )
        messages.append({"role": "user", "content": run.question})
        await self._drive(
            run_id,
            {
                "messages": messages,
                "thread_id": run.thread_id,
                "run_id": run_id,
                "source_id": run.source_id,
                "question": run.question,
            },
        )

    async def resume(self, run_id, command=None):
        self.runs.cancel_event(run_id).clear()
        await self._drive(run_id, command)

    async def stop(self, run_id):
        self.runs.set_status(run_id, RunStatus.STOPPING)
        self.runs.cancel_event(run_id).set()
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
        else:
            self.runs.pause(run_id)
            run = self.runs.get(run_id)
            self.conversations.fail_run(run.thread_id, run_id)

    def _finish(self, run_id, answer):
        run = self.runs.get(run_id)
        reference = self.runs.report_reference(run_id)
        if answer.results and reference is None:
            raise ValueError(
                "Findings are saved, but their required HTML report is missing. Retry report generation."
            )
        if reference:
            answer = answer.model_copy(
                update={"report": ReportReference.model_validate(reference)}
            )
        self.runs.complete(run_id, answer)
        self.conversations.complete_run(
            run.thread_id,
            run_id,
            ChatTurn(
                user_message=run.question,
                answer=answer,
                activities=run.events,
                diagnostics=run.run_diagnostics,
            ),
        )

    async def retry_report(self, run_id):
        run = self.runs.get(run_id)
        spec = self.runs.report_spec(run_id)
        if not run.findings:
            raise ValueError("No saved findings to report.")
        if not spec:
            self.runs.set_phase(run_id, "preparing_report")
            await self._drive(
                run_id,
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "The findings are already published. Load report-design and create their required report now. Do not rerun analysis.",
                        }
                    ]
                },
            )
            return
        self.tasks[run_id] = asyncio.current_task()
        self.runs.cancel_event(run_id).clear()
        self.runs.start_active(run_id)
        self.runs.set_phase(run_id, "preparing_report")

        def render():
            with self.runs.worker(run_id):
                return generate_report(
                    ReportSpec.model_validate(spec),
                    thread_id=run.thread_id,
                    source_id=run.source_id,
                    result_store=self.results,
                    analysis_store=self.analyses,
                    run_store=self.runs,
                    report_store=self.reports,
                    findings=run.findings,
                )

        try:
            async with asyncio.timeout(self.presentation_budget_seconds):
                artifact = await asyncio.to_thread(render)
            self.runs.attach_report(run_id, artifact.reference())
            self._finish(run_id, run.findings)
        except (asyncio.CancelledError, InterruptedError):
            self.runs.cancel_event(run_id).set()
            while self.runs.workers_active(run_id):
                await asyncio.sleep(0.05)
            self.runs.pause(run_id)
            self.conversations.fail_run(run.thread_id, run_id)
        except Exception as exc:
            self.runs.fail(
                run_id,
                str(exc) or "Presentation budget exhausted. Retry the saved report.",
            )
            self.conversations.fail_run(run.thread_id, run_id)
        finally:
            self.tasks.pop(run_id, None)

    async def _consume(self, run_id, agent_input):
        run = self.runs.get(run_id)
        graph = self._graph(run.source_id)
        stream = await graph.astream_events(
            agent_input,
            config={
                "configurable": {"thread_id": run_id},
                "callbacks": [RunDiagnosticsCallback(self.runs, run_id)],
            },
            version="v3",
        )
        async for _event in stream:
            # The callback records tool identities from framework metadata; stream
            # namespaces contain execution IDs, not reliable specialist names.
            pass
        if await stream.interrupted():
            source = (
                self.source_resolver(run.source_id) if self.source_resolver else None
            )
            approval = _extract_approval(
                await stream.interrupts(),
                source=source,
                result_store=self.results,
                thread_id=run.thread_id,
                analysis_limits=self.python_execution_limits,
            )
            self.runs.require_approval(run_id, approval)
            return
        output = await stream.output()
        response = output.get("structured_response") if output else None
        if response is None:
            raise ValueError("Agent finished without a structured response.")
        response = CoordinatorResponse.model_validate(response)
        answer = self.runs.get(run_id).findings or resolve_answer(
            response,
            thread_id=run.thread_id,
            source_id=run.source_id,
            results=self.results,
            analyses=self.analyses,
            runs=self.runs,
        )
        self._finish(run_id, answer)

    async def _consume_with_budget(
        self, run_id, agent_input, *, presentation_only=False
    ):
        task = asyncio.create_task(self._consume(run_id, agent_input))
        presentation_started = time.monotonic() if presentation_only else None
        try:
            while True:
                done, _ = await asyncio.wait([task], timeout=0.1)
                if done:
                    return task.result()
                snapshot = self.runs.get(run_id)
                if snapshot.findings is not None and presentation_started is None:
                    presentation_started = time.monotonic()
                if presentation_started is not None:
                    if (
                        time.monotonic() - presentation_started
                        >= self.presentation_budget_seconds
                    ):
                        raise TimeoutError(
                            "Presentation budget exhausted. Saved findings are available for report retry."
                        )
                elif (
                    snapshot.run_diagnostics.active_ms
                    >= getattr(self.runs, "analysis_budget_seconds", 900) * 1000
                ):
                    raise AnalysisBudgetEnded()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _drive(self, run_id, agent_input):
        run = self.runs.get(run_id)
        self.tasks[run_id] = asyncio.current_task()
        self.runs.start_active(run_id)
        try:
            try:
                await self._consume_with_budget(
                    run_id, agent_input, presentation_only=bool(run.findings)
                )
            except AnalysisBudgetEnded:
                self.runs.cancel_event(run_id).set()
                while self.runs.workers_active(run_id):
                    await asyncio.sleep(0.05)
                self.runs.cancel_event(run_id).clear()
                await self._consume_with_budget(
                    run_id,
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": "The active analysis budget has ended. Stop computation. Inspect committed saved artifacts and execution outputs, publish only supported partial findings with unresolved questions, and create their HTML report now.",
                            }
                        ]
                    },
                    presentation_only=True,
                )
        except (asyncio.CancelledError, InterruptedError):
            self.runs.cancel_event(run_id).set()
            while self.runs.workers_active(run_id):
                await asyncio.sleep(0.05)
            self.runs.pause(run_id)
            self.conversations.fail_run(run.thread_id, run_id)
        except Exception as exc:
            self.runs.fail(run_id, str(exc) or type(exc).__name__)
            self.conversations.fail_run(run.thread_id, run_id)
        finally:
            self.tasks.pop(run_id, None)
