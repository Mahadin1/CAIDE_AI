"""Declarative chart specifications (thin wrapper around stats_core).

Kept as its own module so the frontend contract ("what is worth plotting")
lives in one obvious place. See eda/stats_core.build_chart_specs for the
implementation; this module exists for import clarity.
"""
from eda.stats_core import build_chart_specs, MAX_CHART_SPECS  # noqa: F401
