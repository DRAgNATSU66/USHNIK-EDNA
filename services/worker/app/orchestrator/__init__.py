"""Deterministic orchestrator (Day 9, decision Q7): per sequence, a plan of
candidate routes (planner.py), evidence from the providers in app/evidence/,
one combined answer by fixed rule tables (combiner.py) and a stored decision
trace (engine.py). No LLM in the inference path."""
from app.orchestrator.engine import ORCHESTRATOR_VERSION, Orchestrator, run_orchestrator
from app.orchestrator.planner import Plan, expand_plan, plan_sequence

__all__ = ["ORCHESTRATOR_VERSION", "Orchestrator", "Plan", "expand_plan", "plan_sequence", "run_orchestrator"]
