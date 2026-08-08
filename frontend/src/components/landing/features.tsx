const features = [
  {
    title: "Missing data, caught early",
    body: "Columns with more than 20% gaps are flagged before they silently corrupt your analysis.",
  },
  {
    title: "Correlations explained",
    body: "Strong relationships between numeric columns are surfaced with a readable heatmap — not a raw matrix.",
  },
  {
    title: "Outliers that change your answer",
    body: "IQR-based outlier detection shows the points skewing your averages, so you can decide what to do.",
  },
  {
    title: "Distributions at a glance",
    body: "Understand the shape of every numeric column without touching a statistics textbook.",
  },
  {
    title: "Categorical clarity",
    body: "Dominant categories and high-cardinality columns are called out in plain language.",
  },
  {
    title: "Report-grade output",
    body: "Every report is narrated prose plus charts — share it with non-technical stakeholders as-is.",
  },
];

export function Features() {
  return (
    <section className="section-padding border-t border-border">
      <div className="container-page">
        <p className="text-sm font-medium uppercase tracking-widest text-muted">
          Features
        </p>
        <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
          An analyst's checklist, automated.
        </h2>

        <div className="mt-14 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <div key={f.title} className="card-panel p-6">
              <h3 className="text-lg font-medium">{f.title}</h3>
              <p className="mt-2 text-sm text-muted">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
