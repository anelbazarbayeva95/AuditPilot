# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AuditPilot: an agentic website-auditing platform. Given a single URL, it scrapes the page with Playwright, runs five analysis agents (Accessibility, SEO, Performance, Copy, Visual) in parallel, and renders a decision-oriented report in a React dashboard. Two independent apps, no shared tooling: `backend/` (FastAPI + Python) and `frontend/` (React + Vite + TypeScript).

## Commands

### Backend (`backend/`)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt + pytest/pytest-asyncio
playwright install chromium
uvicorn main:app --reload             # http://localhost:8000
```

Tests: `pytest -v` (or `pytest -q`). Run one file: `pytest tests/test_accessibility_agent.py`. Run one test: `pytest tests/test_accessibility_agent.py::TestEmptyButtons::test_empty_button_flagged`. `pytest.ini` sets `asyncio_mode = auto`, so `async def test_...` needs no `@pytest.mark.asyncio` decorator. The whole suite runs with fakes/stubs for Gemini (`FakeGeminiClient` pattern, see `tests/test_copy_agent.py`) and HTTP (`httpx.MockTransport`, see `tests/test_suggestions.py`) — no real network calls or API keys required.

Requires `GEMINI_API_KEY` in `backend/.env` (copy from `.env.example`) only for agents that actually call Gemini at runtime (Copy, Visual, the suggestion-enrichment pass) — `GeminiClient` doesn't validate the key until the first real call, so importing/unit-testing any agent works without one. As of 2026, AI Studio issues `AQ.`-prefixed "Auth keys" rather than the older `AIza...` format; both work with this project's `google-genai`-based client.

The Performance agent additionally shells out to `npx lighthouse` at runtime, so it needs Node.js/`npx` on `PATH` — this is separate from the Python venv and isn't installed by `pip install`. PDF export (`/report/pdf`) uses ReportLab, which is in `requirements.txt`.

### Frontend (`frontend/`)

```bash
npm install
cp .env.example .env   # VITE_API_BASE_URL, default http://localhost:8000
npm run dev            # http://localhost:5173
npm run build           # tsc -b && vite build
npm run lint            # oxlint
```

No frontend test runner is configured. There's no `--emptyOutDir` in normal use, so if you need a scratch build to inspect output without touching the tracked `dist/`, pass `--outDir` to `vite build` explicitly.

## Architecture

### Backend request flow

The frontend only uses one path: `POST /report/jobs` (returns a job id immediately) then polls `GET /report/jobs/{id}` for `{status, progress, result, error}`. `main.py` also exposes older synchronous endpoints (`/audit`, `/audit/full`, `/report`, `/report/pdf`) kept for direct API use/testing, but they are not what the UI drives.

`jobs.py`'s `JobManager` is the real orchestration entrypoint:

1. `scraper.py` renders the page once with Playwright and extracts `ScrapedPageData` (title, meta, headings, images, buttons, links, inputs, open graph tags) — every element-level field (`selector`, `section`, `width`/`height`) is computed from the live DOM via a small injected JS helper (`_ELEMENT_HELPERS_SCRIPT`), never guessed.
2. Accessibility, SEO, Copy, Performance, and Visual all run concurrently against that shared scrape (`asyncio.gather`). `screenshot.py` captures full-page + viewport PNGs for the Visual agent.
3. Each agent is wrapped in `run_agent_safely()` (`orchestrator.py`) — one agent failing (Gemini down, Lighthouse unavailable, scrape partially incomplete) produces `CategoryResult(score=None, summary="Analysis failed: ...")` instead of failing the whole job. `jobs.py`'s per-step `progress` dict reflects this so the frontend's progress page shows real state, not a simulated loader.
4. After Accessibility/SEO complete, `agents/suggestions.py`'s `enrich_with_ai_suggestions()` runs as a best-effort post-process: it asks Gemini for a suggested `<title>` (only when there's a real signal to base it on — h1s/meta description/og:title, never invented from just a domain) and, for a bounded number of missing-alt-text images, fetches the real image bytes and asks Gemini's vision model to describe them. Every failure mode here (no key, network, bad content-type, empty response) just leaves `Recommendation.ai_suggestion` unset — this pass never fails the job.
5. `report.py`'s `combine_report()` merges everything into one `StructuredAuditReport` (pure function, unit-testable without running any agent) — overall score, per-category scores, a flat cross-category `recommendations` list, and base64-encoded screenshots.

`browser_defaults.py` centralizes the Playwright context fingerprint (desktop Chrome UA, `en-US` locale, 1280×900 viewport) shared by `scraper.py` and `screenshot.py` — Playwright's default headless identity gets outright blocked (HTTP 403) by some real sites, so both modules present the same realistic browser identity rather than the default headless one.

`lighthouse_runner.py` shells out to `npx lighthouse`. Lighthouse's own chrome-launcher only auto-detects a *separately installed* system Chrome or an explicit `CHROME_PATH` — it has no awareness of Playwright's bundled Chromium even though that's usually the only Chromium binary present on a fresh checkout. When `CHROME_PATH` isn't already set, `run_lighthouse()` resolves Playwright's `chromium.executable_path` and passes it through `env`, so the Performance agent works out of the box without a separate Chrome install.

`report.py`'s `combine_report()` output also feeds `pdf_report.py`, which builds the same content as a downloadable ReportLab PDF (`POST /report/pdf`) — Executive Summary, one section per category including Visual with an embedded screenshot, and a severity-sorted recommendations list.

### The "no fabrication" data model

`Recommendation` (`models/schemas.py`) is the unit everything downstream renders: `title`, `description`, `severity`, `category`, plus real evidence fields — `context` (distinguishing value: an image src, a CSS selector, a form field name), `selector` (computed CSS selector, only set when the check is element-level), `section` (nearest landmark ancestor: Header/Navigation/Footer/Main content), and `ai_suggestion` (Gemini-generated, only ever a suggestion, never asserted as fact). Every one of these is `None` rather than guessed when the real value isn't known — e.g. page-level checks like "Missing Title" have no `selector`, because there's only one `<title>` tag to point to. When extending an agent, follow this pattern rather than inventing a plausible-looking value.

`agents/scoring.py` has the shared 0-100 scoring logic (with a per-check deduction cap so e.g. 20 missing-alt-text images can't alone zero out the whole Accessibility score) used by the rule-based agents.

### Frontend structure

Three routes via react-router: `/` (`UrlInputPage`, starts a job) → `/progress` (`AuditProgressPage`, polls the job) → `/results` (`AuditResultsPage`). A direct load of `/progress` or `/results` with no job/report in router state redirects back to `/` — there is no mock/placeholder data path.

`AuditResultsPage` is a 3-column "Docs Layout," not a single scrolling page: `ResultsSidebar` (left) switches which `SectionId` is mounted — only the active section exists in the DOM at a time — and `ResultsSubNav` (right) shows jump links scoped to whatever the active section actually rendered. Section order is Executive Summary → Action list → Visual → Accessibility → SEO → Performance → Copy → Charts; the Action list sits right after the summary deliberately, as the primary decision-making section rather than the last thing reached.

Two different card families render findings, chosen per category by whether repeated element-level findings are possible:
- **Accessibility and SEO** use `GroupedFindingsSection` + `FindingCard` + `FindingDrawer` — findings are grouped by title (`groupFindingsByTitle`, `lib/issueText.ts`) so e.g. 8 empty buttons render as one card with an occurrence count instead of 8 identical ones. Clicking a card opens `FindingDrawer`, a hand-rolled right-side panel (no Radix Dialog/Sheet in this repo — manual focus trap + Escape handling, see the pattern in `FindingDrawer.tsx`) with the full evidence/fix/reference.
- **Performance** stays on the plain `CategoryCard` + `RecommendationList` + `IssueItem`, since its findings are each a distinct metric (LCP/CLS/INP) and don't repeat per element.
- The cross-category **Action list** (`PrioritizedRecommendations` + `IssueItem`) merges the same underlying issue when more than one agent flags it (`dedupeRecommendations`, matches by embedded resource URL first, then by title) and orders by severity then by how quick the fix is (`effortFor`).

All finding cards are evidence-first: the real detected element/value renders in a prominent "Detected" block (quoted for real content like headings/labels/filenames, monospace for selectors/raw metrics — `looksLikeCode()`) before the explanatory why-it-matters/recommended-fix text, which is secondary. `resolveAffectedElement()`/`occurrenceElement()` (`lib/issueText.ts`) are what compute that evidence value — prefer the backend's structured `context`/`selector` fields, only falling back to parsing the description text for the few paths that don't carry one yet.

`lib/issueText.ts` is the single source of truth for presentation-only text: why-it-matters/recommended-fix/effort-tier copy, WCAG references, and fix explanations are all static maps keyed by the finite set of check/dimension titles the backend can produce (see the `*Check`/`*Dimension` enums in `models/schemas.py`) — an unrecognized title falls back to generic text rather than breaking. `types/audit.ts` is a hand-written mirror of `models/schemas.py`; there's no codegen, so backend schema changes must be reflected there manually.

Severity has a shared visual language across every card (`lib/score.ts`): `severityStripeClass`/`isElevatedSeverity` give critical/high findings a colored left accent + tinted background that medium/low findings don't get, so hierarchy reads at a glance rather than every card looking identical.
