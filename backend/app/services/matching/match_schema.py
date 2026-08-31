"""No "email_draft" field here - the LLM no longer generates a free-form
email at all, deliberately removed in favor of the deterministic,
docs/mail-template.docx-formatted email built by
app/services/matching/participant_email_composer.py at send/preview time.
See app/services/matching/llm_matcher.py's module docstring for why.
"""
from __future__ import annotations

from pydantic import BaseModel


class MatchItem(BaseModel):
    participant_id: int
    rank: int
    # Exactly 3, fixed order: commercial opportunity, complementary
    # expertise, strategic opportunity - see llm_matcher.SYSTEM_PROMPT.
    reasoning: list[str]
    # One sentence: why the sender might be interesting *to* this candidate
    # (the reverse of `reasoning`, which is about the candidate's value to
    # the sender). Feeds docs/mail-template.docx's "Why you could be
    # interesting to [them]" section.
    reciprocal_reason: str
    linkedin_draft: str


class MatchSelection(BaseModel):
    matches: list[MatchItem]


class ReverseDraft(BaseModel):
    reciprocal_reason: str
    linkedin_draft: str
