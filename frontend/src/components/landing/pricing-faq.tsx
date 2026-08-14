const FAQS = [
  {
    q: "What counts as one analysis credit?",
    a: "Each time you run an analysis on a file, one credit is used. Uploading and storing files is free — credits are only spent when you start an analysis. Pro skills draw from the same monthly balance, at their listed cost.",
  },
  {
    q: "What happens when my credits run out?",
    a: "You can keep uploading files and reading old reports, but you won't be able to start new analyses until your credits reset at the start of the month — or until you upgrade to a larger plan, which applies the new allowance immediately.",
  },
  {
    q: "Can I downgrade or cancel anytime?",
    a: "Yes. Changes apply at the next billing cycle for downgrades, and there are no lock-in contracts. Your reports and files stay yours.",
  },
  {
    q: "Do you keep my data?",
    a: "Your files are stored securely and only used to generate your analyses. Answers in Q&A are drawn only from the stored analysis digest — raw rows never leave your dataset.",
  },
];

export function PricingFaq() {
  return (
    <section className="section-padding border-t border-border">
      <div className="container-page max-w-3xl">
        <p className="text-sm font-medium uppercase tracking-widest text-muted">
          FAQ
        </p>
        <h2 className="mt-3 text-3xl font-medium">Questions, answered.</h2>
        <div className="mt-10 space-y-3">
          {FAQS.map((f) => (
            <div key={f.q} className="card-panel p-5">
              <h3 className="font-medium">{f.q}</h3>
              <p className="mt-1.5 text-sm text-muted">{f.a}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
