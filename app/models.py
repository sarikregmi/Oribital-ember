from typing import Literal

from pydantic import BaseModel, Field


class Investigation(BaseModel):
    id: str
    name: str
    description: str
    domain: Literal["flammability", "detection", "suppression", "fundamental"]
    gravity: list[str]
    fuels: list[str]
    conditions: list[str]
    measurements: list[str]
    hardware: list[str]
    source_url: str
    keywords: list[str] = Field(default_factory=list)


class InvestigationResult(Investigation):
    relevance_score: float
    matched_signals: list[str]


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[InvestigationResult]


class ResearchSource(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: Literal["local", "nasa", "web"]
    provider: str | None = None


class ExplainOptions(BaseModel):
    question: str = "Explain this investigation for spacecraft fire safety."
    include_nasa_search: bool = False
    include_web_search: bool = False


class Scenario(BaseModel):
    material: str | None = None
    oxygen_percent: float | None = Field(default=None, ge=0, le=100)
    pressure_atm: float | None = Field(default=None, ge=0, le=10)
    airflow_cm_s: float | None = Field(default=None, ge=0, le=1000)
    gravity_g: float | None = Field(default=None, ge=0, le=10)
    thickness_mm: float | None = Field(default=None, ge=0, le=100)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    allow_external_search: bool = True
    include_nasa_search: bool = False
    include_web_search: bool = False
    scenario: Scenario | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    matched_investigations: list[InvestigationResult]
    sources: list[ResearchSource]
    recommended_data_sources: list[ResearchSource]
    follow_up_questions: list[str]
    needs_external_search: bool
    saved_resources: list[str]
    search_path: Literal["local", "local+nasa-web", "local+cached", "local+external-unavailable"]
    ai_mode: Literal["grounded-heuristic", "local-llm"]
    scenario: Scenario | None = None


class StartupResourcesResponse(BaseModel):
    status: str
    query: str
    sources_found: int
    saved_resources: list[str]


class ExplanationResponse(BaseModel):
    investigation_id: str
    summary: str
    direct_answer: str
    fire_safety_implications: list[str]
    evidence: list[str]
    detailed_analysis: list[str]
    recommendations: list[str]
    sources: list[ResearchSource]
    recommended_data_sources: list[ResearchSource]
    follow_up_questions: list[str]
    limitations: list[str]
    ai_mode: Literal["grounded-heuristic", "local-llm", "llm-rag"]


class DownloadedResource(BaseModel):
    id: str
    title: str
    url: str
    snippet: str
    source_type: Literal["local", "nasa", "web"]
    filename: str
    size_bytes: int
    analysis_supported: bool
    provider: str | None = None


class DatasetAnalysis(BaseModel):
    resource_id: str
    title: str
    source_url: str
    file_name: str
    file_size_bytes: int
    analysis: dict
