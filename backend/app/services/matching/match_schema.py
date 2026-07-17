from __future__ import annotations

from pydantic import BaseModel


class MatchItem(BaseModel):
    participant_id: int
    rank: int
    reasoning: list[str]
    email_draft: str
    linkedin_draft: str


class MatchSelection(BaseModel):
    matches: list[MatchItem]
