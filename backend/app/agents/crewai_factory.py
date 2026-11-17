"""Backwards-compatible alias – the CrewAI crew now lives in ``app.agents.crewai_specialist``."""
from app.agents.crewai_specialist import build_crew, run_crew_analysis  # noqa: F401
