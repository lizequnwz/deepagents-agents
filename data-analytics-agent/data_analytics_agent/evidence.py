"""One scoped resolver for publication and report evidence, including lineage."""

from data_analytics_agent.datasets import StoreNotFound
from data_analytics_agent.visualization.schemas import ChartSpec


class EvidenceResolver:
    def __init__(self, *, thread_id, source_id, results, analyses, runs):
        self.thread_id, self.source_id = thread_id, source_id
        self.result_store, self.analysis_store, self.runs = results, analyses, runs
        self.results, self.analyses, self.charts = {}, {}, {}

    def result(self, key):
        if key not in self.results:
            item = self.result_store.get(key, self.thread_id, source_id=self.source_id)
            self.results[key] = item
            for parent in item.parent_result_ids:
                self.result(parent)
        return self.results[key]

    def analysis(self, key):
        if key not in self.analyses:
            item = self.analysis_store.get(
                key, self.thread_id, source_id=self.source_id
            ).analysis
            self.analyses[key] = item
            for result_id in item.input_result_ids:
                self.result(result_id)
            if item.forecast_evaluation:
                self.result(item.forecast_evaluation.predictions_result_id)
                self.result(item.forecast_evaluation.scores_result_id)
            for result_id in item.final_result_ids:
                self.result(result_id)
        return self.analyses[key]

    def chart(self, key):
        if key not in self.charts:
            item = self.runs.storage.get("charts", key, dict)
            if (
                not item
                or item["thread_id"] != self.thread_id
                or item["source_id"] != self.source_id
            ):
                raise StoreNotFound(
                    f"Unknown or out-of-scope chart {key}; use list_conversation_charts."
                )
            chart = ChartSpec.model_validate(item["spec"])
            self.charts[key] = chart
            self.result(chart.result_id)
        return self.charts[key]
