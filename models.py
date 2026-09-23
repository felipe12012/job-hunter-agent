from dataclasses import dataclass


@dataclass(frozen=True)
class JobListing:
    id: str
    title: str
    company: str
    url: str
    description: str


@dataclass(frozen=True)
class ScoredListing:
    listing: JobListing
    match_pct: int
    reasoning: str
    draft_message: str
