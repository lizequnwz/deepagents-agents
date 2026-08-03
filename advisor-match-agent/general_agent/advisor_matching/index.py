"""Compact exact-identity indexes for authoritative advisor records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

from general_agent.advisor_matching import normalization as norm
from general_agent.advisor_matching.schemas import AdvisorRecord


@dataclass(frozen=True, slots=True)
class IndexedAdvisor:
    """Memory-conscious canonical advisor data retained during one match call."""

    crd_number: str
    first_name: str
    last_name: str
    firm_name: str = ""
    email: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    @classmethod
    def from_record(cls, record: AdvisorRecord) -> IndexedAdvisor:
        return cls(**record.model_dump())

@dataclass(frozen=True, slots=True)
class AdvisorIndex:
    """Exact CRD, email, and normalized-name indexes over compact records."""

    records: tuple[IndexedAdvisor, ...]
    by_crd: dict[str, int]
    by_email: dict[str, tuple[int, ...]]
    by_name: dict[tuple[str, str], tuple[int, ...]]

    @classmethod
    def from_records(cls, records: Iterable[AdvisorRecord]) -> AdvisorIndex:
        compact: list[IndexedAdvisor] = []
        by_crd: dict[str, int] = {}
        email_postings: dict[str, list[int]] = defaultdict(list)
        name_postings: dict[tuple[str, str], list[int]] = defaultdict(list)

        for record in records:
            advisor = IndexedAdvisor.from_record(record)
            crd = norm.crd(advisor.crd_number)
            advisor = replace(advisor, crd_number=crd)
            first = norm.first_name(advisor.first_name)
            last = norm.person_name(advisor.last_name)
            if not crd or crd in by_crd:
                raise ValueError(
                    "Master advisor CRD is missing or duplicated: "
                    f"{advisor.crd_number!r}."
                )
            if not first or not last:
                raise ValueError(
                    f"Master advisor {advisor.crd_number} is missing a required "
                    "first or last name."
                )

            position = len(compact)
            compact.append(advisor)
            by_crd[crd] = position
            if email := norm.email(advisor.email):
                email_postings[email].append(position)
            name_postings[(first, last)].append(position)

        if not compact:
            raise ValueError("Advisor reference source is empty.")
        return cls(
            records=tuple(compact),
            by_crd=by_crd,
            by_email={key: tuple(value) for key, value in email_postings.items()},
            by_name={key: tuple(value) for key, value in name_postings.items()},
        )

    def crd_record(self, crd_number: str) -> IndexedAdvisor | None:
        position = self.by_crd.get(norm.crd(crd_number))
        return self.records[position] if position is not None else None

    def email_records(self, email: str) -> tuple[IndexedAdvisor, ...]:
        return self._records(self.by_email.get(norm.email(email), ()))

    def name_records(
        self, first_name: str, last_name: str
    ) -> tuple[IndexedAdvisor, ...]:
        key = (norm.first_name(first_name), norm.person_name(last_name))
        return self._records(self.by_name.get(key, ()))

    def _records(self, positions: tuple[int, ...]) -> tuple[IndexedAdvisor, ...]:
        return tuple(self.records[position] for position in positions)
