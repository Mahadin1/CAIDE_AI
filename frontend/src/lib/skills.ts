import type { UserSkill } from "@/lib/types";

/** The 7 user-initiated Pro skills and their credit costs. Mirrors
 *  gating.py's skill registry — costs shown here are for preview only,
 *  the backend always enforces them. */
export const SKILLS: Record<
  UserSkill,
  { label: string; cost: number; description: string; needsBaseline?: boolean }
> = {
  predictive_baseline: {
    label: "Predictive baseline",
    cost: 10,
    description: "Honest baseline model for a target you choose — holdout metrics + permutation importance.",
  },
  psm: {
    label: "Treatment comparison (PSM)",
    cost: 15,
    description: "Propensity-score matched association between a treatment and an outcome. Association only, with a mandatory caveat.",
  },
  key_driver: {
    label: "Key drivers",
    cost: 8,
    description: "Rank the columns most strongly associated with an outcome, validated on a holdout set.",
  },
  what_if: {
    label: "What-if simulator",
    cost: 3,
    description: "Predict an outcome for hypothetical values. Requires a completed predictive baseline first.",
    needsBaseline: true,
  },
  segment_comparison: {
    label: "Segment comparison",
    cost: 5,
    description: "Formally compare two segments you define, with significance + effect size.",
  },
  decompose: {
    label: "Metric change decomposition",
    cost: 8,
    description: "Split a metric's change between two periods into mix shift vs within-segment contribution.",
  },
  join_quality: {
    label: "Join quality check",
    cost: 5,
    description: "Attach a second file and check match rate, duplicate keys and orphaned rows before merging.",
  },
};

export const SKILL_ORDER: UserSkill[] = [
  "predictive_baseline",
  "psm",
  "key_driver",
  "what_if",
  "segment_comparison",
  "decompose",
  "join_quality",
];

/** The 6 adaptive multi-skill analyses that run automatically on every
 *  report (tier-gated server-side via gating.py). Rendered on the
 *  report "Deep dive" tab. */
export const ADAPTIVE_TASKS: { type: string; title: string; description: string }[] = [
  {
    type: "segmentation",
    title: "Automatic segmentation",
    description: "Groups rows by their numeric profile and shows how distinct the segments really are.",
  },
  {
    type: "forecast",
    title: "Forecasting",
    description: "Projects a metric forward from a date column when a trend is detectable.",
  },
  {
    type: "cohort",
    title: "Cohort retention",
    description: "Tracks how a cohort of identifiers is retained period over period.",
  },
  {
    type: "group_significance",
    title: "Group significance",
    description: "Compares two groups on a numeric outcome with p-values and effect sizes.",
  },
  {
    type: "feature_engineering",
    title: "Feature engineering",
    description: "Suggests log transforms and encodings for skewed or high-cardinality columns.",
  },
  {
    type: "anomalies",
    title: "Anomaly detection",
    description: "Flags unusual rows across the numeric columns you care about.",
  },
];
