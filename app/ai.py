import asyncio
import os

import httpx

from .models import AskResponse, ExplanationResponse, ExplainOptions, Investigation, ResearchSource, Scenario
from .ranking import rank_investigations
from .research import load_cached_sources, search_nasa, search_web
from .resource_store import download_sources, load_saved_resource_sources


# This is the small local model used when Ollama is running on the host machine.
DEFAULT_LOCAL_MODEL = "llama3.2:1b"
FIRE_RESEARCH_TERMS = {
    "fire", "flame", "combustion", "microgravity", "micro-gravity", "zero gravity",
    "0g", "spacecraft", "smoke", "aerosol", "flammability", "suppression", "ignition",
}


# Official starting points for deeper investigation, kept separate from search results.
RECOMMENDED_DATA_SOURCES = [
    ResearchSource(
        title="NASA Physical Sciences Informatics",
        url="https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation",
        snippet="Search the PSI investigation catalog and download experiment files.",
        source_type="nasa",
    ),
    ResearchSource(
        title="NASA PSI database tutorial",
        url="https://assets.science.nasa.gov/content/dam/science/bps/bps-general/bps-data_osdr_psi/Complete_PSI_Database_Guide.pdf",
        snippet="Guide to finding investigation metadata, files, and publications in PSI.",
        source_type="nasa",
    ),
    ResearchSource(
        title="NASA Technical Reports Server",
        url="https://ntrs.nasa.gov/search?q=microgravity%20combustion",
        snippet="Search NASA technical reports and publications related to combustion research.",
        source_type="nasa",
    ),
]


def _follow_up_questions(investigation: Investigation) -> list[str]:
    """Offer questions that can be answered from the same record or its source files."""
    return [
        f"Which {', '.join(investigation.measurements[:2])} values were recorded?",
        f"How does this compare with the same material at another gravity level?",
        "Which source file or publication contains the quantitative result?",
    ]


def _human_answer(investigation: Investigation) -> str:
    """Explain the record in plain language before exposing structured metadata."""
    domain_answers = {
        "detection": (
            f"{investigation.name} is about noticing a fire, not starting one. "
            "It studies how smoke and aerosol particles move in microgravity so alarms can detect a fire early, "
            "even though smoke does not rise and spread like it does on Earth."
        ),
        "flammability": (
            f"{investigation.name} studies how easily materials can ignite or keep burning. "
            "That helps engineers choose safer materials and understand how oxygen, airflow, and gravity change fire behavior."
        ),
        "suppression": (
            f"{investigation.name} studies how a burning flame can be put out. "
            "The results can inform spacecraft suppression equipment, but the experiment metadata alone is not a safety certification."
        ),
        "fundamental": (
            f"{investigation.name} measures basic flame behavior that can improve future fire models. "
            "It provides research evidence, not a complete answer for every spacecraft design."
        ),
    }
    return domain_answers[investigation.domain]


def _general_fire_answer() -> str:
    """Give a concise human answer to broad fire-in-space questions."""
    return (
        "A fire can occur in space when an ignition source meets fuel and oxygen, "
        "just as it does on Earth. Microgravity changes what happens next: hot gases do not rise, smoke does not "
        "travel upward normally, and the flame can spread or go out differently. Spacecraft fire safety therefore "
        "focuses on preventing ignition, choosing materials carefully, detecting smoke early, and suppressing flames."
    )


def _is_fire_research_question(question: str) -> bool:
    """Keep automatic downloads limited to the project's fire-research subject area."""
    normalized = question.lower()
    return any(term in normalized for term in FIRE_RESEARCH_TERMS)


def _grounded_explanation(
    investigation: Investigation,
    sources: list[ResearchSource],
    question: str,
    file_context: str = "",
) -> ExplanationResponse:
    """Build a safe response without requiring a model or network connection."""
    # Keep domain implications deterministic so the fallback never invents science.
    domain_implications = {
        "flammability": "Supports material screening and ignition-risk controls for elevated-oxygen habitats.",
        "detection": "Supports smoke-sensor placement and alarm thresholds where aerosol transport differs from Earth.",
        "suppression": "Supports selection of extinguishing gases and timing for crew fire-response procedures.",
        "fundamental": "Provides parameters that can improve fire and flammability models for future missions.",
    }
    return ExplanationResponse(
        investigation_id=investigation.id,
        summary=investigation.description,
        direct_answer=_human_answer(investigation),
        fire_safety_implications=[domain_implications[investigation.domain]],
        evidence=[
            f"Gravity regimes: {', '.join(investigation.gravity)}.",
            f"Conditions: {', '.join(investigation.conditions)}.",
            f"Measurements: {', '.join(investigation.measurements)}.",
        ],
        detailed_analysis=[
            f"The investigation addresses {investigation.domain} in {', '.join(investigation.gravity)}.",
            f"Its most relevant variables are {', '.join(investigation.conditions)} and {', '.join(investigation.measurements)}.",
            f"The requested question is: {question}",
            f"Local file context supplied: {'yes' if file_context else 'no'}.",
        ],
        recommendations=[
            "Compare these conditions with the intended spacecraft atmosphere before applying the result.",
            "Keep the underlying PSI record and publication attached to any engineering decision.",
        ],
        sources=[ResearchSource(title=investigation.name, url=investigation.source_url, snippet=investigation.description, source_type="local"), *sources],
        recommended_data_sources=RECOMMENDED_DATA_SOURCES,
        follow_up_questions=_follow_up_questions(investigation),
        limitations=[
            "This is a grounded metadata interpretation, not a safety certification.",
            "Quantitative conclusions require the underlying PSI files and experiment context.",
        ],
        ai_mode="grounded-heuristic",
    )


async def _ask_local_model(
    investigation: Investigation,
    question: str,
    sources: list[ResearchSource],
    file_context: str,
) -> str | None:
    """Ask an optional host model for wording, returning None when it is unavailable."""
    # Ollama is optional: the application remains useful on machines without a model.
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_LOCAL_MODEL)
    prompt = (
        "You are a cautious NASA fire-safety research assistant. Summarize only the "
        "provided metadata and context in a detailed but concise explanation. Do not invent numbers, conclusions, "
        "or safety certification.\n\n"
        f"Investigation: {investigation.name}\n"
        f"Description: {investigation.description}\n"
        f"Domain: {investigation.domain}\n"
        f"Conditions: {', '.join(investigation.conditions)}\n"
        f"Measurements: {', '.join(investigation.measurements)}\n"
        f"Question: {question}\n"
        f"Local file context: {file_context[:5000]}\n"
        f"Research context: {' | '.join(source.title + ': ' + source.snippet for source in sources)[:5000]}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            generated = response.json().get("response")
            return generated.strip() if isinstance(generated, str) and generated.strip() else None
    except (httpx.HTTPError, ValueError):
        # A local model is an enhancement, never a dependency of core search.
        return None


async def _ask_general_model(question: str, sources: list[ResearchSource]) -> str | None:
    """Let the optional local model answer broad questions without inventing evidence."""
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_LOCAL_MODEL)
    context = " | ".join(source.title + ": " + source.snippet for source in sources)[:6000]
    prompt = (
        "Answer the user's NASA spacecraft fire-safety question in plain language. "
        "Use the supplied context when present, distinguish known facts from uncertainty, "
        "and do not claim that a search found nothing means research does not exist. "
        "Do not invent numbers or safety certification.\n\n"
        f"Question: {question}\n"
        f"Research context: {context or 'No external context was provided.'}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            generated = response.json().get("response")
            return generated.strip() if isinstance(generated, str) and generated.strip() else None
    except (httpx.HTTPError, ValueError):
        return None


async def explain_investigation(
    investigation: Investigation,
    options: ExplainOptions | None = None,
    file_context: str = "",
) -> ExplanationResponse:
    """Return a local-model explanation when available, with a deterministic fallback."""
    # Start with the fully grounded answer so every response has evidence and limitations.
    options = options or ExplainOptions()
    search_query = f"NASA {investigation.name} spacecraft fire safety {options.question}"
    sources: list[ResearchSource] = []
    if options.include_nasa_search:
        sources.extend(await search_nasa(search_query))
    if options.include_web_search:
        sources.extend(await search_web(search_query))
    grounded = _grounded_explanation(investigation, sources, options.question, file_context)
    generated = await _ask_local_model(investigation, options.question, sources, file_context)
    if generated is None:
        return grounded

    # Only replace the summary; safety implications and evidence remain application-owned.
    grounded.summary = generated
    grounded.ai_mode = "local-llm"
    return grounded


async def ask_question(
    question: str,
    investigations: list[Investigation],
    allow_external_search: bool = True,
    scenario: Scenario | None = None,
    include_nasa_search: bool = False,
    include_web_search: bool = False,
) -> AskResponse:
    """Search local PSI evidence first, then use external sources only when needed."""
    scenario_text = _scenario_text(scenario)
    question_for_ai = f"{question}\nCustom scenario: {scenario_text}" if scenario_text else question
    ranked = rank_investigations(investigations, question)
    # Weak incidental matches are not treated as an answer to a broad question.
    local_matches = [item for item in ranked if item.relevance_score >= 1.0][:5]
    if local_matches:
        # Explain the strongest local match while returning all useful local matches.
        explanation = await explain_investigation(
            local_matches[0],
            ExplainOptions(
                question=question_for_ai,
                include_nasa_search=include_nasa_search,
                include_web_search=include_web_search,
            ),
        )
        return AskResponse(
            question=question,
            answer=explanation.direct_answer,
            matched_investigations=local_matches,
            sources=explanation.sources,
            search_path="local",
            ai_mode="local-llm" if explanation.ai_mode == "local-llm" else "grounded-heuristic",
            scenario=scenario,
            recommended_data_sources=explanation.recommended_data_sources,
            follow_up_questions=explanation.follow_up_questions,
            needs_external_search=False,
            saved_resources=[],
        )

    # No local evidence matched, so external search is the explicit fallback path.
    sources: list[ResearchSource] = []
    live_sources: list[ResearchSource] = []
    research_query = question_for_ai
    if _is_fire_research_question(question_for_ai):
        research_query = f"{question_for_ai} spacecraft fire combustion microgravity 0g"
    if allow_external_search:
        if include_nasa_search or not include_web_search:
            live_sources.extend(await search_nasa(research_query))
        if include_web_search or not include_nasa_search:
            live_sources.extend(await search_web(research_query))
    saved_sources = load_saved_resource_sources(question_for_ai) if allow_external_search else []
    sources = live_sources or (load_cached_sources(question_for_ai) if allow_external_search else []) or saved_sources
    saved_resources = []
    if allow_external_search and _is_fire_research_question(question_for_ai):
        saved_resources = await download_sources(RECOMMENDED_DATA_SOURCES + live_sources)
    source_text = "\n".join(f"- {source.title}: {source.snippet}" for source in sources)
    generated_answer = await _ask_general_model(question, sources)
    answer = generated_answer or _general_fire_answer()
    answer += "\n\nNo local investigation matched that exact question."
    if live_sources:
        answer += " Live NASA/web sources were added:\n" + source_text
    elif sources:
        answer += " Live search returned no results, so previously saved research sources were used:\n" + source_text
    elif allow_external_search:
        answer += " Live web access did not return a source in this run. I can still explain the science from the challenge context; use the official links below to verify and continue the research."
    else:
        answer += " External search permission was off, so no outside sources were requested."
    search_path = "local+nasa-web" if live_sources else "local+cached" if sources else "local+external-unavailable" if allow_external_search else "local"
    return AskResponse(
        question=question,
        answer=answer,
        matched_investigations=[],
        sources=sources,
        search_path=search_path,
        ai_mode="local-llm" if generated_answer else "grounded-heuristic",
        scenario=scenario,
        recommended_data_sources=RECOMMENDED_DATA_SOURCES,
        follow_up_questions=[
            "Which NASA investigation is closest to this question?",
            "What variables and units should be extracted from the source files?",
            "Which publication provides quantitative validation?",
        ],
        needs_external_search=not allow_external_search,
        saved_resources=saved_resources,
    )


def _scenario_text(scenario: Scenario | None) -> str:
    """Format only user-provided scenario values for grounded AI context."""
    if scenario is None:
        return ""
    values = [
        f"material={scenario.material}" if scenario.material else "",
        f"oxygen={scenario.oxygen_percent}%" if scenario.oxygen_percent is not None else "",
        f"pressure={scenario.pressure_atm} atm" if scenario.pressure_atm is not None else "",
        f"airflow={scenario.airflow_cm_s} cm/s" if scenario.airflow_cm_s is not None else "",
        f"gravity={scenario.gravity_g} g" if scenario.gravity_g is not None else "",
        f"thickness={scenario.thickness_mm} mm" if scenario.thickness_mm is not None else "",
    ]
    return ", ".join(value for value in values if value)
