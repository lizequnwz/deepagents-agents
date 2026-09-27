"""One cached lexical index for discovery and paginated browsing.

Names/synonyms keep exact-match priority; TF-IDF ranks partial matches using
catalog-wide term rarity. Parent descriptions never become column evidence.
"""

from sklearn.feature_extraction.text import TfidfVectorizer

from data_analytics_agent.semantic import (
    SEARCH_STOP_WORDS,
    SemanticMatch,
    _normalize_search_text,
)


class SemanticSearchIndex:
    def __init__(self, catalog):
        self.entities = []
        for dataset in catalog.datasets.values():
            self.entities.append(("dataset", None, dataset))
            self.entities.extend(
                ("field", dataset.name, f) for f in dataset.fields.values()
            )
        self.entities.extend(("metric", None, m) for m in catalog.metrics.values())
        self.names = [_normalize_search_text(e.name) for _, _, e in self.entities]
        self.synonyms = [
            tuple(_normalize_search_text(s) for s in e.synonyms)
            for _, _, e in self.entities
        ]
        documents = [
            " ".join(
                [name] * 3
                + list(synonyms) * 2
                + [_normalize_search_text(e.description)]
            )
            for (_, _, e), name, synonyms in zip(
                self.entities, self.names, self.synonyms
            )
        ]
        self.vectorizer = TfidfVectorizer(
            token_pattern=r"(?u)\b\w+\b",
            stop_words=sorted(SEARCH_STOP_WORDS),
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        # A catalog containing only stop words still supports exact lookup.
        self.matrix = None
        if any(set(doc.split()) - SEARCH_STOP_WORDS for doc in documents):
            self.matrix = self.vectorizer.fit_transform(documents)

    def search(self, query, *, entity_kinds=None, dataset_name=None, time_only=False):
        query = _normalize_search_text(query)
        kinds = set(entity_kinds or ("dataset", "field", "metric"))
        similarities = {}
        if self.matrix is not None:
            scores = (self.matrix @ self.vectorizer.transform([query]).T).tocoo()
            similarities = dict(zip(scores.row, scores.data))
        matches = []
        for i, (kind, parent, entity) in enumerate(self.entities):
            if kind not in kinds or (
                dataset_name and (parent or entity.name) != dataset_name
            ):
                continue
            if time_only and (kind != "field" or not entity.is_time):
                continue
            score, reason = similarities.get(i, 0.0), "lexical_relevance"
            if query == self.names[i] or (
                parent and query == _normalize_search_text(f"{parent}.{entity.name}")
            ):
                score, reason = 500.0, "exact_name"
            elif query in self.synonyms[i]:
                score, reason = 400.0, "exact_synonym"
            elif score:
                # Full business phrases in a longer question outrank incidental words.
                phrases = (self.names[i], *self.synonyms[i])
                if any(p and f" {p} " in f" {query} " for p in phrases):
                    score += 2.0
                if parent and set(_normalize_search_text(parent).split()) & set(
                    query.split()
                ):
                    score += 0.25
            if score:
                matches.append(
                    SemanticMatch(
                        kind,
                        entity.name,
                        parent,
                        entity.description,
                        entity.name,
                        reason,
                        float(score),
                    )
                )
        return tuple(
            sorted(
                matches,
                key=lambda m: (-m.score, m.kind, m.parent_dataset or "", m.name),
            )
        )
