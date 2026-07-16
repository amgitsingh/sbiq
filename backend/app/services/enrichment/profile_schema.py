from __future__ import annotations

from pydantic import BaseModel


class PersonProfile(BaseModel):
    name: str | None = None
    designation: str | None = None
    looking_for: str | None = None
    offerings: str | None = None


class CompanyProfile(BaseModel):
    name: str | None = None
    website: str | None = None
    industry: str | None = None
    products: list[str] = []
    services: list[str] = []
    markets: list[str] = []
    customers: list[str] = []
    technologies: list[str] = []
    employee_count: str | None = None
    headquarters: str | None = None
    funding_stage: str | None = None
    investors: list[str] = []
    recent_news: list[str] = []
    summary: str | None = None


class StructuredProfile(BaseModel):
    person: PersonProfile
    company: CompanyProfile
