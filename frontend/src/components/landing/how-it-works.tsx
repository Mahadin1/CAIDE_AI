const steps = [
  {
    n: "01",
    title: "Upload your data",
    body: "Drop in a CSV, Excel, JSON or Parquet file — any size. The agent profiles every column and proposes an analysis plan.",
  },
  {
    n: "02",
    title: "Review the plan, or just go",
    body: "Check the planned analyses, tweak column types, exclude noise or add questions. Start it and watch the progress.",
  },
  {
    n: "03",
    title: "Read the plain-English story",
    body: "A narrated report explains what matters — what's dirty, what's correlated, what's hiding in the tails.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="section-padding border-t border-border">
      <div className="container-page">
        <p className="text-sm font-medium uppercase tracking-widest text-muted">
          How it works
        </p>
        <h2 className="mt-3 max-w-2xl text-3xl font-medium md:text-4xl">
          Three steps from spreadsheet to understanding.
        </h2>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {steps.map((step) => (
            <div key={step.n} className="card-panel p-6">
              <span className="font-heading text-sm font-medium text-muted">
                {step.n}
              </span>
              <h3 className="mt-3 text-lg font-medium">{step.title}</h3>
              <p className="mt-2 text-sm text-muted">{step.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
