# AuditPilot Frontend

A three-page dashboard for AuditPilot: enter a URL, watch live per-agent progress, then get a decision-oriented audit report — an executive summary up front, a primary Visual Review section, per-category detail cards, and a deduplicated, prioritized action list.

## Stack

- React + TypeScript + Vite
- Tailwind CSS v4
- shadcn/ui (Card, Progress, Badge, Button, Input, Alert, Separator — vendored under `src/components/ui`)
- react-router-dom
- recharts (category score bar chart, issue-severity donut chart)

## Pages

- **`/` — URL Input.** Enter a URL, client-side validated, then starts a background report job via `POST /report/jobs`.
- **`/progress` — Audit Progress.** Polls `GET /report/jobs/{id}` every ~1.2s and shows real per-step state (pending/running/completed/failed) for scrape, accessibility, SEO, copy, performance, and visual. Redirects to `/` if landed on directly without a job id. On completion, forwards to `/results` with the finished report; on failure, shows the error with a way back.
- **`/results` — Results Dashboard.** Renders the completed `StructuredAuditReport` as a report built for non-technical readers (founders, marketers, agencies), not an engineering dashboard:
  1. **Executive Summary** — overall score, top 3 issues, estimated fix effort (quick/moderate/involved counts), key strengths.
  2. **Visual Review** — a primary, full-width section: large above-the-fold screenshot (click-to-expand) beside the visual findings.
  3. **Category cards** — Accessibility, SEO, Performance, Copy Review. A category with a failed/unavailable analysis shows a plain-English "Analysis unavailable" panel instead of a raw error.
  4. **Charts** — category-score bar chart and issues-by-severity donut chart.
  5. **Prioritized Action List** — every category's findings deduplicated (the same issue flagged by more than one category becomes one card listing all affected areas), ordered by severity then by how quick the fix is.

  No mock/placeholder data — a hard refresh with no report in state redirects back to `/`. Long URLs never appear directly on a card; they're shortened into a label (e.g. "Hero image (host)") with the raw value behind a "Technical details" disclosure.

## Setup

```bash
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if your backend isn't on :8000
npm run dev
```

Requires the AuditPilot backend running (see `../backend/README.md`) — by default at `http://localhost:8000`, with `POST /report/jobs` and `GET /report/jobs/{id}` reachable and CORS open to the dev server origin.

## Build

```bash
npm run build   # tsc -b && vite build
```

## Structure

```
src/
├── main.tsx                     # entry, wraps <App /> in BrowserRouter
├── App.tsx                       # routes: /, /progress, /results
├── pages/
│   ├── UrlInputPage.tsx           # Page 1 — starts a report job
│   ├── AuditProgressPage.tsx       # Page 2 — polls job status, shows per-agent progress
│   └── AuditResultsPage.tsx        # Page 3 — renders the finished StructuredAuditReport
├── components/
│   ├── ui/                        # shadcn/ui primitives
│   └── audit/
│       ├── ExecutiveSummary.tsx      # score + top 3 issues + effort + strengths, at the top
│       ├── VisualReviewCard.tsx       # primary, full-width Visual Review section + screenshot modal
│       ├── ScreenshotModal.tsx         # click-to-expand overlay for the screenshot
│       ├── CategoryCard.tsx            # generic Accessibility/SEO/Performance card
│       ├── CopyReviewCard.tsx           # Copy category (strengths/weaknesses/recs shape)
│       ├── UnavailablePanel.tsx          # "Analysis unavailable" panel + collapsed technical error
│       ├── IssueItem.tsx                  # one issue card: problem/why it matters/fix/severity/categories/effort
│       ├── RecommendationList.tsx          # per-category issue list built on IssueItem, capped + expandable
│       ├── PrioritizedRecommendations.tsx   # cross-category, deduplicated, prioritized action list
│       ├── ChartsSection.tsx                 # recharts bar + donut, driven by report.summary
│       └── OverallScoreCard.tsx               # (unused since the Executive Summary absorbed this — kept, not deleted)
├── lib/
│   ├── api.ts                     # createReportJob() + getReportJob() fetch wrappers
│   ├── issueText.ts                # why-it-matters/recommended-fix/effort content maps + cross-category dedup
│   ├── rawData.ts                   # shared CopyRawData/VisualRawData type guards
│   ├── score.ts                       # score -> color/label band helpers
│   └── utils.ts                        # shadcn's `cn()` helper
└── types/
    └── audit.ts                    # TS mirror of backend/models/schemas.py
```

## Notes

- `src/types/audit.ts` is hand-written to match the backend's Pydantic models (`ReportJob`, `StructuredAuditReport`, `CategoryResult`, etc.). If those shapes change on the backend, update this file too.
- `src/lib/issueText.ts`'s "why it matters" / "recommended fix" / effort-tier text is a static, curated map keyed by the finite set of check/dimension titles the backend can produce — it's presentation copy, not backend logic. An unrecognized title falls back to generic text rather than breaking.
- `src/components/audit/OverallScoreCard.tsx` is no longer used on the results page (its content was folded into `ExecutiveSummary.tsx`) but is left in place rather than deleted.
- `src/App.css` and `src/assets/*` are unused leftovers from the Vite template and can be deleted.
