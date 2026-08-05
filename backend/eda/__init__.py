"""DataScope adaptive EDA package.

This package implements the deterministic "brain" of DataScope:

  * loader        — multi-format file loading + encoding detection
  * streaming     — online/streaming statistics (Welford, top-k sketches)
  * sampling      — automatic full-vs-sample analysis mode decisions
  * fingerprint   — compact, LLM-safe data profile
  * classification— column kind detection
  * stats_core    — backbone statistics (deterministic)
  * tests         — enhanced statistical tests (normality, ANOVA, ...)
  * text          — free-text column analysis
  * dates         — temporal feature extraction + seasonality
  * charts        — declarative chart specs with drill-down metadata
  * planner       — LLM-driven analysis planning (with deterministic fallback)
  * findings      — rule-based findings with method/evidence/interpretation/action
  * narrator      — LLM narrative from plan + findings (with deterministic fallback)

Design rule (see docs/ARCHITECTURE.md): pandas/scipy/statsmodels compute,
rule code decides, and the LLM only plans and narrates. No number in any
report is ever produced by the LLM.
"""
