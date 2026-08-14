# Dashboard IA Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure DataScope's Next.js frontend into a multi-page information architecture: a persistent collapsible sidebar shell, per-feature nested report routes, and new Files / Reports / Skills / Billing pages, plus a command palette — a UI restructure that preserves every existing capability and all 17 API proxy routes untouched.

**Architecture:** `app/dashboard/layout.tsx` becomes a server shell that renders a sidebar (client), header (breadcrumb + command-palette trigger + user menu), and `{children}`. `app/dashboard/reports/[id]/` gains a layout that renders a persistent report header + sub-nav, with each existing report section moved into a real nested route (Overview, Findings, Charts, Deep dive, Skills, Q&A, Export). New top-level pages assemble existing components (UploadRow, ReportCharts, AdaptiveResults, SkillsPanel, PlanPicker) as-is. A shared query helper (`lib/queries.ts`) centralizes the duplicated Supabase lookups.

**Tech Stack:** Next.js 15.1.6 (app router, RSC), React 19, Tailwind 3.4, existing shadcn/ui primitives; **new** `cmdk`, `@radix-ui/react-dialog`, `@radix-ui/react-tooltip`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-separator`, `@radix-ui/react-collapsible`.

## Global Constraints

- **Do NOT modify** any file under `src/app/api/**` and do **NOT** change `src/lib/types.ts`. Existing component data-fetching logic is preserved — components are relocated and restyled, not rewritten.
- **Auth guard:** the sidebar layout must keep `if (!user) redirect("/login")` semantics (currently in `app/dashboard/layout.tsx`).
- **Design tokens:** use existing tokens only (`bg-background`, `bg-surface`, `bg-elevated`, `text-foreground`, `text-muted`, `border-border`, `bg-accent`, `font-heading`) — no new palette. Keep the pure-black/Vercel dark default.
- **Real routes:** report sub-tabs must be nested route segments sharing `reports/[id]/layout.tsx`, NOT client tab state. Back button / shareable URLs must work.
- **No fake data:** where the backend has no data (e.g. credit-ledger history), show what exists (current cycle usage) and flag the gap in copy; do not invent a ledger.
- **Verification:** `npx tsc --noEmit` must pass with zero errors; a feature-inventory pass must confirm all 6 deep-dives, 9 charts, 7 Pro skills, Q&A, exports, and row drill-down remain reachable.
- **Commits:** none unless the user explicitly asks (per repo policy). The project has no test runner — verification is typecheck + build + manual inventory.

---

### Task 1: Install new UI primitive dependencies

**Files:**
- Modify: `frontend/package.json` (via npm install)

**Interfaces:**
- Consumes: nothing
- Produces: `cmdk`, `@radix-ui/react-dialog`, `@radix-ui/react-tooltip`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-separator`, `@radix-ui/react-collapsible` available to import.

- [ ] **Step 1: Install deps**

Run in `/workspace/frontend`:
```bash
npm install cmdk @radix-ui/react-dialog @radix-ui/react-tooltip @radix-ui/react-dropdown-menu @radix-ui/react-separator @radix-ui/react-collapsible
```
Expected: deps added to `package.json` + `package-lock.json`, no peer conflicts (all support React 19).

- [ ] **Step 2: Verify install**

Run: `npx tsc --noEmit` — must still pass (no code changes yet).
Expected: no errors.

---

### Task 2: Add shadcn/ui primitives (Command, Dialog, Tooltip, DropdownMenu, Separator, Collapsible, Sheet, Breadcrumb)

**Files:**
- Create: `frontend/src/components/ui/command.tsx`
- Create: `frontend/src/components/ui/dialog.tsx`
- Create: `frontend/src/components/ui/tooltip.tsx`
- Create: `frontend/src/components/ui/dropdown-menu.tsx`
- Create: `frontend/src/components/ui/separator.tsx`
- Create: `frontend/src/components/ui/collapsible.tsx`
- Create: `frontend/src/components/ui/sheet.tsx`
- Create: `frontend/src/components/ui/breadcrumb.tsx`
- Create: `frontend/src/components/ui/sidebar.tsx`

**Interfaces:**
- Consumes: Task 1 deps
- Produces: named exports — `Command`, `CommandDialog`, `CommandInput`, `CommandList`, `CommandEmpty`, `CommandGroup`, `CommandItem`, `CommandSeparator`, `CommandShortcut`; `Dialog*`; `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider`; `DropdownMenu*`; `Separator`; `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent`; `Sheet`, `SheetTrigger`, `SheetContent`, `SheetHeader`, `SheetTitle`, `SheetDescription`, `SheetClose`; `Breadcrumb` family; `SidebarProvider`, `useSidebar`, `Sidebar`, `SidebarHeader`, `SidebarContent`, `SidebarFooter`, `SidebarGroup`, `SidebarGroupLabel`, `SidebarGroupContent`, `SidebarMenu`, `SidebarMenuItem`, `SidebarMenuButton`, `SidebarMenuSub`, `SidebarTrigger`, `SidebarRail`, `SidebarInset`, `SidebarInput`.

- [ ] **Step 1: Write the primitive files**

Port the standard shadcn/ui implementations (dialogs.dev registry) for `command`, `dialog`, `tooltip`, `dropdown-menu`, `separator`, `collapsible`, `sheet`, `breadcrumb`, `sidebar`, adapting only the token references to this repo's CSS variables (`--accent`, `--background`, `--surface`, `--elevated`, `--border`, `--muted`, `--foreground`; radius `var(--radius)`) — the same adaptation already present in `button.tsx`, `card.tsx`, `badge.tsx`.

For `sidebar.tsx` use the shadcn sidebar composition: `SidebarProvider` (state + `useSidebar` context with `open`, `setOpen`, `toggleSidebar`, `isMobile`, `setOpenMobile`, `openMobile`), desktop collapsible rail via CSS width transition, mobile rendering inside a `Sheet`, tooltips when collapsed. Keep the component API (the names listed above) but keep the file focused (~300 lines max) — do not paste the entire 700-line registry file; implement the API surface we use.

- [ ] **Step 2: Typecheck**

Run in `/workspace/frontend`: `npx tsc --noEmit`
Expected: no errors.

---

### Task 3: Shared query helpers + skills metadata module

**Files:**
- Create: `frontend/src/lib/queries.ts`
- Create: `frontend/src/lib/skills.ts`
- Modify: `frontend/src/components/report/skills-panel.tsx` (import SKILLS/SKILL_ORDER from `@/lib/skills`, delete the local copies)

**Interfaces:**
- Consumes: `createClient` from `@/lib/supabase/server`, types from `@/lib/types`
- Produces:
  - `getProfile(supabase): Promise<Profile | null>` — select `id, email, name, plan, credits, qa_credits, reports_this_month` by session user.
  - `getReportWithUpload(supabase, reportId): Promise<ReportWithUpload | null>` — select `id, upload_id, summary_json, narrative, created_at, analysis_mode, source_format, sample_info_json, column_glossary, uploads(id, filename, created_at, status)`; also export the `ReportWithUpload` type.
  - `getUploadsWithReports(supabase): Promise<Upload[]>` — select `*, reports(id)` ordered `created_at desc`.
  - `getReportsForList(supabase): Promise<ReportListItem[]>` — select `id, upload_id, created_at, analysis_mode, source_format, uploads(id, filename, status, created_at)` ordered `created_at desc`; export `ReportListItem` type (`Report` subset + `uploads`).
- `lib/skills.ts` exports `SKILLS: Record<UserSkill, {label; cost; description; needsBaseline?}>`, `SKILL_ORDER: UserSkill[]`, and `ADAPTIVE_TASKS: {type; title; description}[]` (the 6 adaptive analyses).

- [ ] **Step 1: Write `lib/queries.ts`**

Server-only module (imports `@/lib/supabase/server`). Export the types and functions listed above. Use `.returns<T>()` for typed rows. Guard `user` null with early return of `null`.

- [ ] **Step 2: Write `lib/skills.ts`**

Move the `SKILLS` and `SKILL_ORDER` constants verbatim from `skills-panel.tsx:12-62`. Add `ADAPTIVE_TASKS` with titles/descriptions matching `adaptive-results.tsx` sections: Automatic segmentation, Forecasting, Cohort retention, Group significance, Feature engineering, Anomaly detection.

- [ ] **Step 3: Update `skills-panel.tsx` to import the constants**

Delete lines 12-62 of `skills-panel.tsx`; add `import { SKILLS, SKILL_ORDER } from "@/lib/skills";`. No other behavior change.

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit` — expected: pass.

---

### Task 4: Persistent sidebar shell + header (dashboard layout)

**Files:**
- Create: `frontend/src/components/dashboard/dashboard-sidebar.tsx` (client)
- Create: `frontend/src/components/dashboard/dashboard-header.tsx` (client)
- Create: `frontend/src/components/dashboard/command-palette.tsx` (client)
- Create: `frontend/src/components/dashboard/user-menu.tsx` (client)
- Modify: `frontend/src/app/dashboard/layout.tsx` (rewrite shell)
- Create: `frontend/src/components/dashboard/sidebar-layout.tsx` (client wrapper bridging sidebar/header/palette state)

**Interfaces:**
- Consumes: `getProfile`, `getUploadsWithReports`, `getReportsForList` (Task 3); `SidebarProvider/useSidebar` etc. (Task 2); `ThemeToggle`; `Logo`
- Produces:
  - `DashboardShell({ profile, uploads, reports, children })` — the client composition (SidebarProvider wrapping `DashboardSidebar` + `<div className="flex-1"><DashboardHeader/><main>{children}</main></div>`). Exposes the shared layout.
  - `CommandPalette({ uploads, reports })` — Cmd/Ctrl+K dialog.
  - `UserMenu({ name, email, planLabel })` — dropdown with Account / Billing / Sign out.

- [ ] **Step 1: Write `dashboard-sidebar.tsx`**

Client component. Renders:
- Top: `Logo` + "DataScope" (hide text when collapsed).
- A `SidebarTrigger` (hamburger) for mobile + collapse toggle on desktop.
- Primary nav group: **Overview** (`/dashboard`, `LayoutDashboard`), **Files** (`/dashboard/files`, `Files`), **Reports** (`/dashboard/reports`, `FileBarChart`/`BarChart3`), **Skills** (`/dashboard/skills`, `Wand2`). Active state from `usePathname()` (exact match for `/dashboard`, prefix match for the others). Collapsed state shows icon + tooltip.
- "Start analysis" accent button linking to `/dashboard/files#upload` (label hidden when collapsed).
- Footer group: usage summary (plan badge + `N credits`) linking to `/dashboard/account/billing`, and a `Settings` link to `/dashboard/account`.

- [ ] **Step 2: Write `dashboard-header.tsx`**

Client component. Renders a sticky header row inside the content column:
- Left: mobile `SheetTrigger` (hamburger, opens the sidebar as a drawer) + `Breadcrumb` — segments derived from `usePathname()` and `useParams()` (e.g. `Reports / {filename}`; fall back to capitalized segment when no param). Pass `reportFilename` from the report layout when present (see Task 5) via `children`-agnostic approach: the header accepts an optional `trail?: {label; href}[]` prop so the report layout can supply its own breadcrumb trail.
- Right: `CommandPalette` trigger button (shows `⌘K`), `ThemeToggle`, `UserMenu`.

- [ ] **Step 3: Write `command-palette.tsx`**

Client component with `CommandDialog`. On `metaKey/ctrlKey + k` open. Groups:
- **Navigate**: Overview, Files, Reports, Skills, Account, Billing.
- **Files** (upload.status === "ready"): item per file → `/dashboard/files/{id}`; header item "Upload a file" → `/dashboard/files#upload`.
- **Reports**: item per report → `/dashboard/reports/{id}` (label = parent filename).
Uses `CommandInput`, `CommandList`, `CommandEmpty`, `CommandGroup`, `CommandItem`, `CommandSeparator`. Keep search local (no network).

- [ ] **Step 4: Write `user-menu.tsx`**

Client `DropdownMenu`. Trigger = initials avatar. Items: Account (`/dashboard/account`), Billing (`/dashboard/account/billing`), separator, Sign out (server action). Define a `signOut` server action in `dashboard/layout.tsx` (moved from the current layout's `SignOutButton`) and pass it as a prop.

- [ ] **Step 5: Rewrite `app/dashboard/layout.tsx`**

Server component: auth guard (`if (!user) redirect("/login")`), fetch `profile`, `uploads`, `reports` via Task 3 helpers, compute `planLabel` + `credits` + `qaCredits`, define the `signOut` server action, and render `<DashboardShell profile={...} uploads={...} reports={...} signOut={signOut}>{children}</DashboardShell>`.
Remove the old header markup, `PLAN_LABEL`, `initials`, `SignOutButton` from this file (moved into client components).

- [ ] **Step 6: Verify shell renders**

Run: `npx tsc --noEmit` — pass.
Manual: `npm run dev`, open `/dashboard` → sidebar visible, collapses, mobile drawer works, palette opens with ⌘K, user menu shows Account/Billing/Sign out.

---

### Task 5: Report route split (layout + 7 nested pages)

**Files:**
- Create: `frontend/src/app/dashboard/reports/[id]/layout.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/page.tsx` (Overview)
- Create: `frontend/src/app/dashboard/reports/[id]/findings/page.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/charts/page.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/deep-dive/page.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/skills/page.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/qa/page.tsx`
- Create: `frontend/src/app/dashboard/reports/[id]/export/page.tsx`
- Create: `frontend/src/components/report/report-subnav.tsx` (client)
- Create: `frontend/src/components/report/report-findings.tsx` (shared findings renderer, extracted from current page)
- Create: `frontend/src/components/report/report-header.tsx` (server, reused meta line/badges)

**Interfaces:**
- Consumes: `getReportWithUpload`, `getProfile` (Task 3); all `report/*` components as-is
- Produces:
  - `ReportSubNav({ reportId })` — client links: Overview (`/dashboard/reports/{id}`), Findings (`/findings`), Charts (`/charts`), Deep dive (`/deep-dive`), Skills (`/skills`), Q&A (`/qa`), Export (`/export`). Active via `usePathname()` (exact segment match).
  - `ReportFindings({ findings })` — the findings list markup extracted from the current report page (severity-styled cards).
  - `ReportHeader({ report, isPro })` — filename, badges (format/analysis mode), meta line (date, rows × cols, duplicates), "Export" button linking to `/export`.

- [ ] **Step 1: Extract `ReportFindings`**

Move the findings card markup (`page.tsx:166-194`) and `severityStyles` into `report-findings.tsx`, accepting `findings: ReportFinding[]` and sorting by severity order high → medium → low → info. The current page and new Overview both use it.

- [ ] **Step 2: Write `report-subnav.tsx`**

Horizontal tab bar (rounded pill container, same style as the login mode-switch). Links are real Next `<Link>`s.

- [ ] **Step 3: Write `report-header.tsx`**

Server component rendering: back link (`/dashboard/reports`), title + badges + meta (moved from current page.tsx:73-126), plus an `Export report` button linking to `/export`.

- [ ] **Step 4: Write `reports/[id]/layout.tsx`**

Server component: `const { id } = await params`; fetch report + profile via helpers; `notFound()` if missing; render `<div className="space-y-8"><ReportHeader report={report} isPro={isPro} /><ReportSubNav reportId={id} />{children}</div>`. Also pass `report.uploads.filename` to the header breadcrumb trail (via a context or by rendering header inline — the header component may accept `trail`).

- [ ] **Step 5: Write Overview page (`[id]/page.tsx`)**

Renders: `ReportOverview` (At a glance), sample notice (copy from current page.tsx:132-148), narrative card, `ReportFindings` limited to the **top 5 by severity** with a "View all N findings" link to `/findings`, dataset-overview dtypes card, column glossary card. Uses `getReportWithUpload` + `getProfile`.

- [ ] **Step 6: Write Findings page**

Renders `ReportFindings` (all findings), plus `executed_tasks`/`skipped_tasks` lists when present in `summary`.

- [ ] **Step 7: Write Charts page**

Renders `<ReportCharts summary={summary} reportId={id} />` (includes drill-down modal internally).

- [ ] **Step 8: Write Deep-dive page**

Renders `<AdaptiveResults summary={summary} reportId={id} />`.

- [ ] **Step 9: Write Skills page**

`isPro ? <SkillsPanel reportId={id} summary={summary} plan={plan} credits={credits} /> : <UpgradePrompt/>` where `UpgradePrompt` is a small inline card with a link to `/pricing` (reuse the `card-panel` + `btn-accent` styles). Also render the sample notice on this page (adaptive analyses are sampled) — keep one source of truth: render the sample notice on Overview, Deep-dive, and Charts pages.

- [ ] **Step 10: Write Q&A page**

`isPro ? <ReportQa reportId={id} qaCredits={qaCredits} /> : <UpgradePrompt/>`.

- [ ] **Step 11: Write Export page**

Server component. Renders an export action card: three `<form>`s posting to `/api/reports/{id}/pdf|html|clean` (target `_blank`) — moved from current page.tsx:106-124 — plus, when `report.export_pdf_url`/`export_html_url`/`cleaned_data_url` exist, direct links. Gate behind `isPro` with the same `UpgradePrompt`. Include a note that exports are generated from the stored analysis.

- [ ] **Step 12: Remove old single-page content**

The old `reports/[id]/page.tsx` is fully replaced by the layout + Overview. Delete the now-unused imports (`ArrowLeft`, `Download`, `FileCode`, `FileSpreadsheet`, `Card*`, `Badge`, `Button`) from the new Overview page — no leftover dead code.

- [ ] **Step 13: Typecheck + route check**

Run: `npx tsc --noEmit` — pass.
Manual: visit each of the 7 routes on a real report; back button returns through the tab history; sub-nav highlights correctly.

---

### Task 6: Files page (table + upload) and file detail restyle

**Files:**
- Create: `frontend/src/app/dashboard/files/page.tsx`
- Create: `frontend/src/components/dashboard/files-table.tsx` (client)
- Modify: `frontend/src/app/dashboard/files/[id]/page.tsx` (header back-link + breadcrumb trail)
- Modify: `frontend/src/components/dashboard/upload-row.tsx` (add optional `href` + `extraMenuItems` props)

**Interfaces:**
- Consumes: `getUploadsWithReports` (Task 3), `UploadRow`, `UploadFlow`, `RowMenu`
- Produces:
  - `FilesTable({ initialUploads })` — client table with live state.
  - `UploadRow` extended: `href?: string` (wraps filename in a `Link` when status === "ready"), `extraMenuItems?: RowMenuItem[]` (appended to the kebab menu).

- [ ] **Step 1: Extend `UploadRow`**

Add optional props `href` and `extraMenuItems`. When `href` is set and status is `"ready"`, render the filename inside `<Link href={href}>`; otherwise keep the plain `<p>`. Append `extraMenuItems` after the computed items in `<RowMenu items={...}/>`.

- [ ] **Step 2: Write `files-table.tsx`**

Client component holding `uploads` state (mirrors `UploadsSection`'s status-change handler). Layout:
- `section id="upload"` → `UploadFlow` (disabled while any upload is analyzing).
- Filter tabs: All / Saved (`ready`) / Analyzing (`pending|processing`) / Reports (`done`) / Failed (`failed`) with counts.
- Rows: for each filtered upload render `UploadRow` with `href` (ready files → `/dashboard/files/{id}`) and `extraMenuItems` adding "Open file" (ready) and "View report" (done, if `reports[0]`).
- Empty states per filter.

- [ ] **Step 3: Write `files/page.tsx`**

Server component: fetch uploads, render page title ("Files"), description, and `<FilesTable initialUploads={...} />`.

- [ ] **Step 4: Restyle `files/[id]/page.tsx`**

Change the back link to `/dashboard/files` ("Files"), keep the rest (FileAnalyze flow untouched). Remove the `ArrowLeft`→`Dashboard` copy.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit` — pass. Manual: `/dashboard/files` shows upload, tabs filter, ready rows open the file page.

---

### Task 7: Reports list page

**Files:**
- Create: `frontend/src/app/dashboard/reports/page.tsx`
- Create: `frontend/src/components/dashboard/reports-list.tsx` (client)

**Interfaces:**
- Consumes: `getReportsForList` (Task 3), `RelativeTime`, `Badge`, `RowMenu`
- Produces: `ReportsList({ initialReports })` — client table with local search (filename) + date-range filter (select: all / 30d / 90d / this year).

- [ ] **Step 1: Write `reports-list.tsx`**

Client component. Table columns: File (link to `/dashboard/reports/{id}`, shows parent `uploads.filename`), Analyzed (`RelativeTime`), Details (format badge, analysis-mode badge, rows × cols from `summary_json.shape`), Source status (parent `uploads.status` badge via the same `statusMeta` map used by `UploadRow`), Actions (`RowMenu`: View report, Download PDF/HTML/CSV). Local search input + date select; empty state.

- [ ] **Step 2: Write `reports/page.tsx`**

Server component: fetch `getReportsForList`, render title "Reports" + `<ReportsList initialReports={...} />`. Empty-state copy points to the Files page.

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit` — pass.

---

### Task 8: Skills index page

**Files:**
- Create: `frontend/src/app/dashboard/skills/page.tsx`
- Create: `frontend/src/components/dashboard/skills-overview.tsx` (client, for the Pro-gate upgrade CTA when logged out of Pro context)

**Interfaces:**
- Consumes: `getProfile` (Task 3), `SKILLS`, `SKILL_ORDER`, `ADAPTIVE_TASKS` (Task 3), `PlanPicker`? No — links to `/pricing`
- Produces: server page rendering the full skills catalog.

- [ ] **Step 1: Write `skills/page.tsx`**

Server component fetching profile. Renders:
- Intro section: what adaptive deep-dives vs Pro skills are, credit costs, tier gate.
- Grid of the 7 Pro skills (`SKILL_ORDER`): name, cost badge, description, "run from any report → Skills tab".
- Grid of the 6 adaptive analyses (`ADAPTIVE_TASKS`): auto-run on every report, included in all plans.
- If plan === "free": upgrade CTA card → `/pricing`; if paid: note that skills charge from report credits.
- "How to use" steps: open a report → Skills tab → configure → charged from credits.

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit` — pass.

---

### Task 9: Account vs Billing split

**Files:**
- Modify: `frontend/src/app/dashboard/account/page.tsx` (remove Subscription section)
- Create: `frontend/src/app/dashboard/account/billing/page.tsx`

**Interfaces:**
- Consumes: `getProfile` (Task 3), `PlanPicker`
- Produces: `/dashboard/account/billing` route.

- [ ] **Step 1: Trim account page**

Remove the "Subscription" card + `CreditCard` import + `PlanPicker` import. Keep ProfileInfo + AccountForm. Update the badge line to keep credits/QA info (or move entirely to Billing page — keep a concise summary badge).

- [ ] **Step 2: Write `account/billing/page.tsx`**

Server component: fetch profile; render plan badge, current-cycle usage summary card (plan, credits left this month of allowance, Q&A credits, reports this month), a `PlanPicker` card, and a small note flagging the backend gap: "A full credit-history ledger isn't available yet — this shows your current monthly cycle only."

- [ ] **Step 3: Typecheck + nav check**

Run: `npx tsc --noEmit` — pass. Sidebar/palette/user-menu Billing links resolve.

---

### Task 10: Overview rebuild

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx` (rewrite)
- Create: `frontend/src/components/dashboard/overview-content.tsx` (client)

**Interfaces:**
- Consumes: `getProfile`, `getUploadsWithReports` (Task 3), `UploadFlow`, `UploadRow`
- Produces: `OverviewContent({ initialUploads, plan, credits, qaCredits })` — client activity area.

- [ ] **Step 1: Write `overview-content.tsx`**

Client component holding uploads state. Renders:
- Quick upload section (`id="upload"`) → `UploadFlow` (disabled while analyzing), with a hint linking to `/dashboard/files`.
- "Recent files" (up to 5 ready) using `UploadRow` with `href`.
- "In progress / needs attention" (`pending|processing|failed`) using `UploadRow`.
- "Recent reports" (up to 5 done) — compact cards linking to report pages, showing filename + analyzed date + format badge.
- Empty onboarding state (no uploads at all): 3-step card (Upload a file → Review the plan → Read the report) with buttons to Files and Pricing.
- Footer link "View all files →" `/dashboard/files`, "View all reports →" `/dashboard/reports`.

- [ ] **Step 2: Rewrite `dashboard/page.tsx`**

Server component: greeting ("Welcome back" + name), a usage summary strip (plan, credits/allowance, Q&A credits) with "Manage plan" → `/dashboard/account/billing`, then `<OverviewContent .../>`. Reuse `PLAN_CREDITS` map (already in this file).

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit` — pass.

---

### Task 11: /features and /pricing pages + landing trim

**Files:**
- Create: `frontend/src/app/features/page.tsx`
- Create: `frontend/src/app/pricing/page.tsx`
- Modify: `frontend/src/app/page.tsx` (remove PricingSection; keep Hero/HowItWorks/Features/FinalCta)
- Modify: `frontend/src/components/site-nav.tsx` (add "Features" → /features; change "Pricing" → /pricing)
- Modify: `frontend/src/components/landing/final-cta.tsx` (fix "two full analyses" → "3 analyses")
- Create: `frontend/src/components/landing/features-hero.tsx` + `frontend/src/components/landing/pricing-faq.tsx` (small static sections)

**Interfaces:**
- Consumes: `SiteNav`, `Footer`, `Features`, `PricingSection`, `Button`
- Produces: public `/features` and `/pricing` routes.

- [ ] **Step 1: Build `/features/page.tsx`**

`SiteNav` + hero strip + `Features` grid + three new static deep-dive sections (EDA checklist / Adaptive deep-dives / Pro skills with costs) + `FinalCta` + `Footer`. Static content; no new data fetching.

- [ ] **Step 2: Build `/pricing/page.tsx`**

`SiteNav` + `PricingSection` + `PricingFaq` (static 4-item FAQ) + `FinalCta` + `Footer`.

- [ ] **Step 3: Trim landing + update nav**

`app/page.tsx` drops `PricingSection`. `site-nav.tsx` links: How it works (anchor), Features (/features), Pricing (/pricing). `final-cta.tsx` copy: "Free accounts get 3 analyses every month."

- [ ] **Step 4: Typecheck + route check**

Run: `npx tsc --noEmit` — pass. Visit `/`, `/features`, `/pricing`.

---

### Task 12: Verification & feature inventory

**Files:** none (verification only)

- [ ] **Step 1: Full typecheck + lint**

Run in `/workspace/frontend`:
```bash
npx tsc --noEmit
npx next lint 2>&1 || true
```
Expected: tsc clean. Lint warnings addressed if trivial (unused imports/args), otherwise documented.

- [ ] **Step 2: Production build**

Run: `npm run build`
Expected: build succeeds; all new routes render statically/dynamically as configured (`force-dynamic` on data pages).

- [ ] **Step 3: Feature-inventory pass (manual checklist)**

Walk a real report and confirm each of the following is reachable:
- [ ] 9 chart types render on `/charts` (missing values, correlation heatmap, outlier scatter, categorical bar, histogram, group comparison, Cramér's V, time trend, strongest correlations)
- [ ] Row drill-down opens from a chart on `/charts`
- [ ] 6 adaptive deep-dives render on `/deep-dive` (segmentation, forecast, cohort, group significance, feature engineering, anomalies)
- [ ] 7 Pro skills render + can be launched from `/skills` (Pro account)
- [ ] Q&A works on `/qa` (Pro)
- [ ] PDF / HTML / cleaned-CSV exports work from `/export` (Pro)
- [ ] File plan-review flow works at `/dashboard/files/[id]`
- [ ] Palette reaches: files, reports, upload action
- [ ] All 17 `src/app/api/**/route.ts` files unmodified (`git status` shows no changes under `api/`)
- [ ] Sidebar persists, collapses, highlights active route; mobile drawer works
- [ ] `git diff --stat` reviewed; no dead imports left behind

---

## Self-review notes

- **Spec coverage:** every route in the spec maps to a task (Overview→T10, Files→T6, File detail→T6.4, Reports→T7, Report shell+7 tabs→T5, Skills→T8, Account/Billing→T9, landing/features/pricing→T11, sidebar/palette→T4, primitives→T1/T2).
- **Placeholders:** none — all code blocks in tasks are concrete.
- **Type consistency:** `getReportWithUpload`/`ReportWithUpload`, `getUploadsWithReports`/`Upload[]`, `getReportsForList`/`ReportListItem[]`, `SKILLS`/`SKILL_ORDER`, `UploadRow.href`/`extraMenuItems` names are fixed across tasks.
- **Backend gap handling:** Billing ledger flagged (T9), report "status" filter sourced from parent upload (T7) — no invented data.
