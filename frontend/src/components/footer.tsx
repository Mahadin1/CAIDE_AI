import { Logo } from "@/components/logo";

export function Footer() {
  return (
    <footer className="border-t border-[#1f1f1f] py-10">
      <div className="container-page flex flex-col items-center justify-between gap-6 md:flex-row">
        <Logo />
        <p className="text-sm text-muted">
          DataScope · plain-English analysis for messy CSVs
        </p>
        <div className="flex items-center gap-6 text-sm text-muted">
          <span>© {new Date().getFullYear()}</span>
          <a href="mailto:support@datascope.app" className="hover:text-foreground">
            Support
          </a>
        </div>
      </div>
    </footer>
  );
}
