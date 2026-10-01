# Portable analysis example

[Download the example ZIP](portable-analysis-example.zip), extract it, install its recorded requirements in a local Python environment, and run `python analysis.py`. Open `analysis.ipynb` from the extracted folder in Jupyter.

This synthetic example starts with two typed rows containing identifiers, dates and exact decimals. Two independent Python executions double the amounts and reuse both the original and derived snapshots. The final total is independently checked as 24.6800. It includes a diagnostic figure, saved outputs, HTML report, execution code and provenance. A failed attempt and unrelated dataset are excluded from runnable replay.

The ZIP was downloaded through the application's browser control and replayed after extraction into another directory. Notebook replay, fresh-process semantics and saved/reopened notebooks are covered by the release tests. This is a capability demonstration with synthetic data, not a live-model evaluation or a business recommendation.
