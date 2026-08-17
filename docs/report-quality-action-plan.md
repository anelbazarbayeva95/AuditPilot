# Report Quality — Feedback Analysis & Action Plan

Source: external review of the generated PDF audit for `nike.com` (5 pages, generated 2026-08-17 04:09 UTC).

The review's verdict — *"reads as an automated internal diagnostic rather than an authoritative client
deliverable"* — is accurate, and its ranking is right: **credibility before decoration.** This document
records what was verified in the code and the PDF binary, separates the feedback into what to act on
as stated vs. what needs adjusting, and lays out the work in three shippable releases.

> **Status:** Release 1 (§6) is implemented. Release 2 is blocked on the renderer decision in §4 —
> ReportLab cannot produce a tagged PDF, so the tagging and typography work should follow that call
> rather than be spent twice. Release 3 is not started.

---

## 1. Verified findings

Everything below was checked against the repo and against the PDF file, not assumed.

| Claim in the review | Verified? | Evidence in code / file |
|---|---|---|
| Performance score shown with no LCP/CLS/INP value | **Confirmed — and it is a rendering gap, not a measurement gap** | `PerformanceAgent.analyze()` puts full `PerformanceMetrics` into `CategoryResult.raw_data` (`agents/performance.py:36`), but `pdf_report.py` never reads `raw_data` for Performance — only for Copy/Visual (`_insight_section_flowables`). The numbers were collected and then dropped on the floor. |
| No test environment / device profile / run count disclosed | Confirmed, **and there is an internal inconsistency behind it** | `lighthouse_runner.py:123` runs `npx lighthouse` with no `--preset`/`--form-factor`, so it uses Lighthouse's CLI default: **mobile emulation with simulated 4G throttling and 1 run** — while `scraper.py`/`screenshot.py` use a **desktop 1280×900** context (`browser_defaults.py`). The 25/100 is a mobile-throttled number presented alongside a desktop screenshot, undisclosed. |
| "SEO 100/100" not credible as a complete conclusion | Confirmed | `agents/seo.py` implements exactly 6 checks: title, meta description, missing h1, multiple h1, Open Graph tags, image alt. No canonical, robots, status code, structured data, indexability, internal links, mobile rendering. The summary string still reads "No SEO issues detected." |
| No WCAG version / criteria / engine / rule IDs | Confirmed — mapping exists but in the wrong layer | `AccessibilityFinding` (`models/schemas.py:161`) has no WCAG field. The mapping exists only as frontend presentation text: `WCAG_REFERENCE_BY_TITLE` in `frontend/src/lib/issueText.ts:326`. The PDF cannot see it. |
| Visual analysis contradicts the screenshot | **Confirmed by pixel analysis of the embedded image** | The embedded viewport PNG (1280×900, PDF object 7) is **71.3% a single flat colour `#f5f5f5`**, **64.3% of its rows are >99% one colour**, and real page content only begins around **y≈740** — the bottom ~18%. The hero genuinely never rendered. The Visual agent then described a "large, centrally placed headline" it could not have seen. This is a capture failure the pipeline did not detect. |
| Findings duplicated in several places | Confirmed | `_build_pdf_bytes` (`pdf_report.py:152-159`) re-renders **every** recommendation in a trailing "Recommendations" section after already rendering them per category. The 7 empty buttons are *not* duplicate data (each is a distinct DOM element with its own selector), but each one is printed twice. |
| Machine labels leak into prose | Confirmed | `_finding_to_recommendation` does `check.value.replace("_", " ").title()` → "Cta Quality", "Slow Lcp". `_insight_section_flowables` prints the raw enum value in italics: `<i>value_proposition_clarity</i>`. |
| "7 issue(s)", "5 strength(s)" | Confirmed | `_summarize()` in `agents/accessibility.py:191` and equivalents. |
| PDF metadata anonymous | Confirmed | The file's document info dictionary reads `Title (anonymous)`, `Author (anonymous)`, `Subject (unspecified)`, `Keywords ()`. `SimpleDocTemplate` is constructed with no `title`/`author`/`subject`/`keywords` (`pdf_report.py:96`). |
| No page numbers / headers / footers, uncontrolled pagination | Confirmed | `doc.build(story)` with no `onFirstPage`/`onLaterPages` callback and no `KeepTogether`/`CondPageBreak` anywhere. |
| Equal-weight average | Confirmed | `report.py:155` — `_average()` over the 5 category scores, silently skipping `None` categories without saying so. |
| Concatenated `KYLIAN MBAPPÉMERCURIAL SUPERFLY` | Confirmed, root cause found | `scraper.py:158-163` extracts headings with `e.textContent.trim()`. `textContent` concatenates every descendant text node with **no separator** and ignores rendering, so two visually separate lines become one token. `innerText` (used elsewhere in the same file for buttons/links) does not have this problem. |
| Confidence levels absent from the report | Partly — they exist and are discarded | `ConfidenceLevel` is already on `CopyInsight`/`VisualInsight` and is already requested in both prompts. The PDF never renders it. |

**Net:** a large share of the review's "missing evidence" complaints are *data we already collect and
then throw away at the render step*. That makes Release 1 cheaper than the feedback's length suggests.

---

## 2. Where the feedback needs adjusting

Acting on these as literally stated would make the product worse or violate the repo's own
no-fabrication rule (`CLAUDE.md` → "The 'no fabrication' data model").

1. **"The seven empty-button findings may include duplicates."** They are seven distinct elements with
   distinct computed selectors. The *presentation* duplicates them (per-category list + master list), and
   the frontend already groups them (`groupFindingsByTitle`). Fix: group and de-duplicate **in the
   renderer**, and dedupe defensively on `(check, selector)` — do not drop real occurrences.
2. **"Recommended owner."** AuditPilot has no organisation model and no way to know who owns a
   component. Inventing an owner is exactly the fabrication the codebase forbids. Ship the field as
   optional, populated only from caller-supplied config, rendered as "—" (Unassigned) otherwise.
3. **"Cap accessibility at 60 for unresolved critical failures."** Adopt the *shape*, not that number —
   a cap must be derived from a documented rule and printed next to the score, otherwise it is one more
   undocumented magic number of the kind the review is objecting to.
4. **"Make the PDF tagged."** ReportLab's flowable pipeline has no practical route to a fully tagged,
   PDF/UA-conformant document. Metadata, language, bookmarks, and outline are reachable today; real
   tagging is not, without changing renderer. See the decision in §4.
5. **"Avoid awarding 100."** The rule should be *"never award 100 without printing the tested scope"* —
   a genuinely clean page across a disclosed set of checks should still be allowed to score 100 with the
   coverage stated beside it. Suppressing true results is its own credibility problem.

---

## 3. Proposed data-model changes

All new fields are `Optional` and default to `None` — same discipline as the existing schema: absent
means "not determined", never a plausible-looking guess. `frontend/src/types/audit.ts` is a hand-written
mirror and must be updated in the same change (no codegen).

```python
# models/schemas.py

class RunContext(BaseModel):
    """How this audit was produced — printed in the report's Methodology section."""
    started_at: datetime
    finished_at: datetime
    requested_url: str
    final_url: str                     # after redirects
    http_status: Optional[int]
    viewport: str                      # "1280x900"
    user_agent: str
    scraper_wait_until: str            # "load" | "networkidle"
    lighthouse_version: Optional[str]
    lighthouse_form_factor: Optional[str]     # "mobile" | "desktop"
    lighthouse_throttling: Optional[str]      # e.g. "simulated 4G / 4x CPU"
    lighthouse_runs: Optional[int]
    gemini_model: Optional[str]
    wcag_target: str = "WCAG 2.2 AA"
    report_version: str                # "1.0"

class CategoryCoverage(BaseModel):
    """What was and wasn't tested — this is what makes a score interpretable."""
    checks_run: list[str]
    checks_not_covered: list[str]
    method: Literal["automated", "ai_assisted", "not_run"]

class Evidence(BaseModel):
    dom_excerpt: Optional[str]         # truncated outerHTML, captured live
    accessible_name_computation: Optional[str]
    measured_value: Optional[str]      # "4820 ms", "0.31"
    threshold: Optional[str]           # "good ≤ 2500 ms"
    screenshot_crop_base64: Optional[str]

# Recommendation gains:
    wcag_criterion: Optional[str]      # "WCAG 4.1.2 — Name, Role, Value"
    rule_id: Optional[str]             # own check id, or axe rule id later
    detection: Optional[Literal["automated", "ai_generated", "manual"]]
    confidence: Optional[ConfidenceLevel]
    impact: Optional[Literal["high", "medium", "low"]]
    effort: Optional[Literal["quick", "moderate", "involved"]]
    occurrences: Optional[int]         # after grouping
    validation: Optional[str]          # how to verify the fix
    owner: Optional[str]               # caller-supplied only; never inferred
    timing: Optional[Literal["immediate", "next_sprint", "backlog"]]

# CategoryResult gains:
    coverage: Optional[CategoryCoverage]
    score_status: Literal["scored", "insufficient_evidence", "not_run"] = "scored"
    score_explanation: Optional[str]   # "100 − (3 × 10 high) = 70, capped per check at 30"

# StructuredAuditReport gains:
    run_context: RunContext
    screenshot_quality: Optional[ScreenshotQuality]
```

`effortFor()` and `WCAG_REFERENCE_BY_TITLE` currently live in `frontend/src/lib/issueText.ts`. They move
to the backend so the PDF and the UI cannot disagree; the frontend keeps only genuinely
presentation-only copy (why-it-matters prose).

---

## 4. Decision required: PDF renderer

The review asks for controlled pagination, running headers/footers, page numbers, real typography,
annotated figures, **and** a tagged/accessible PDF. ReportLab reaches maybe 60% of that.

| | Stay on ReportLab | Move to HTML + WeasyPrint |
|---|---|---|
| Metadata, bookmarks, language | Yes | Yes |
| Page numbers, running headers | Yes (`onPage` canvas callbacks) | Yes (`@page`, CSS counters) |
| Editorial pagination | Manual `KeepTogether`/`CondPageBreak` | `break-inside: avoid` — far cheaper |
| Tagged / PDF-UA | **No practical route** | Yes (`pdf_variant='pdf/ua-1'`) |
| Shares design vocabulary with the React UI | No — parallel implementation | Yes — same tokens/CSS |
| New system deps | None | Pango/Cairo in `backend/Dockerfile` |

**Recommendation:** ship Release 1 credibility fixes on ReportLab (they are data-plumbing, not layout),
then migrate the renderer in Release 2 rather than investing in ReportLab layout work that gets thrown
away. A report *about* accessibility that is itself an untagged PDF is the single most quotable weakness
in the review, and only the migration closes it.

---

## 5. Workstreams

### W1 — Screenshot integrity *(highest credibility risk)*
`screenshot.py`, `report.py`, `agents/visual.py`, `pdf_report.py`

1. Improve capture: `wait_until="networkidle"`, await `document.fonts.ready`, scroll to bottom and back
   to trigger lazy-loaded hero media, then settle before capturing. Retry once on a degraded result.
2. Add blank/degraded detection on the viewport PNG — dominant-colour share and share of uniform rows.
   Thresholds anchored to the measured failure (71% dominant colour, 64% uniform rows): flag when
   dominant colour ≥ 60% **or** content-bearing rows < 40%.
3. Return `ScreenshotQuality {ok | degraded, dominant_colour_pct, uniform_row_pct, reason}`.
4. On `degraded`: **do not run the Visual agent's evaluative pass.** Visual gets
   `score_status="insufficient_evidence"`, `score=None`, and a plain summary saying the render was
   incomplete and why. It is then excluded from the overall score with that exclusion printed.
5. The PDF prints the degraded screenshot **with a disclosure box**, never as evidence of a good render.

*Acceptance:* replaying today's Nike capture yields `degraded`, no visual score, and a disclosure block —
no claim about a headline that isn't in the image.

### W2 — Performance evidence
`lighthouse_runner.py`, `agents/performance.py`, `pdf_report.py`

1. Set the form factor explicitly instead of inheriting Lighthouse's mobile CLI default, and record it.
   Either match the desktop scrape (`--preset=desktop`) or keep mobile deliberately — but disclose it.
   Today's mixed desktop-screenshot/mobile-score report is internally inconsistent.
2. Capture `lighthouseVersion`, `configSettings` (throttling, form factor, screen emulation), `fetchTime`,
   `finalDisplayedUrl`, and run count into `RunContext`.
3. Render the metrics table in the report: LCP / CLS / INP / TBT / FCP, each with measured value,
   threshold, and pass-fail — the data is already in `raw_data`.
4. Replace `"Audit render-blocking resources, bundle size, and server response time"` with real
   diagnostics parsed from the Lighthouse audits already returned: `render-blocking-resources`,
   `unused-javascript`, `uses-responsive-images`, `server-response-time` — each carries `details.items`
   with the resource URL, transfer size, and estimated saving in ms. That answers *which* resource,
   *how big*, and *expected effect* directly from measured data.
5. Median-of-3 runs behind a flag (default 1, disclosed) — single-run variance is a real objection.

### W3 — Accessibility rigour
`agents/accessibility.py`, `scraper.py`, `models/schemas.py`

1. Move WCAG mapping into the backend (`wcag_criterion` per check), sourced from the existing frontend map.
2. Capture `dom_excerpt` (truncated `outerHTML`) in the scraper's existing injected JS helper — cheap,
   real, and it is exactly the "short DOM excerpt" the review asks for.
3. Emit the accessible-name computation for empty buttons: *"no text content, no `aria-label`, no
   `aria-labelledby`, no `title` → accessible name is empty"*. This is deterministic from data already scraped.
4. Group findings by `check` with an occurrence list and defensive dedupe on `(check, selector)`;
   print `occurrences` rather than N near-identical bullets.
5. Publish `CategoryCoverage`: 5 checks run, and name what is **not** covered (colour contrast, focus
   order, keyboard traps, ARIA validity, reading order, motion).
6. Set `detection="automated"` on every rule-based finding so automated fact is separable from AI judgment.
7. *Later:* inject `axe-core` in the existing Playwright session for real rule IDs and breadth. Highest
   coverage gain in the whole plan, but it is a new dependency and a new failure mode — Release 3.

### W4 — SEO credibility
`agents/seo.py`

1. Publish coverage and change the summary from "No SEO issues detected" to
   *"No issues found across the 6 checks performed; 8 areas not tested (listed in Methodology)."*
2. Add checks that are free from data already in hand or one cheap request: canonical link, `meta robots`,
   `robots.txt` fetch, HTTP status and redirect chain, `viewport` meta, structured-data (JSON-LD) presence,
   title/meta-description length bounds, heading-order sanity, internal-link count.
3. Only then is a 100 defensible — and it prints with its scope beside it.

### W5 — Scoring model
`report.py`, `agents/scoring.py`

1. Weighted overall score, weights declared in code and printed in Methodology. Starting proposal:
   Accessibility 25 / Performance 25 / SEO 20 / Copy 15 / Visual 15.
2. `score_status="insufficient_evidence"` propagates: a category in that state is excluded from the
   overall score and the exclusion is stated in the report, not silently averaged away (today
   `_average()` drops `None` categories without a word).
3. `score_explanation` per category — the arithmetic in one line: *"100 − (7 empty buttons × 10, capped at
   30) − ... = 70"*. This alone answers "how do seven issues become 70".
4. Blocking-failure cap, documented and printed wherever it applies.
5. Never print 100 without the coverage line adjacent.

### W6 — Report architecture, editorial, and PDF craft
`pdf_report.py` (Release 1 fixes; Release 2 renderer migration)

Restructure to the order the review proposes, which is sound:
**Cover → Executive summary → Scorecard → Priority action plan → Category findings → Methodology → Appendix.**

- **Cover:** client/host, audited URL, long-form date (`17 August 2026 at 04:09 UTC`), report version,
  environment, status.
- **Scorecard table:** replace the cramped Summary column with `Area | Score | Critical findings |
  Confidence | Priority`, as suggested.
- **Priority action plan** replaces the duplicated master list: top 5–10, ranked by impact × effort ×
  confidence, each with occurrences, owner (or "—"), timing, and validation method. Category sections
  then hold detail, and nothing is printed twice.
- **Methodology section** rendered from `RunContext` + per-category `CategoryCoverage`.
- **Appendix** takes the raw selectors, full automated output, and technical traces out of the body.
- **Findings as cards/compact tables:** Finding · Evidence · Impact · Recommendation · Priority.
- **Metadata:** pass `title`/`author`/`subject`/`keywords` to the doc template; set document language;
  add outline bookmarks per section.
- **Pagination:** `onFirstPage`/`onLaterPages` callbacks for running header + `Page N of M`;
  `KeepTogether` around figures and cards; `CondPageBreak` before sections.
- **Screenshots:** captioned with URL, viewport, capture time, and page state; sized to be legible;
  numbered annotation markers tied to findings (Release 3).
- **Editorial normalisation:** one central label map (`"cta_quality" → "CTA Quality"`,
  `"slow_lcp" → "Slow LCP"`) shared by PDF and UI; a real pluralisation helper (no more "issue(s)");
  machine names confined to the appendix.
- **Provenance labelling:** every Copy/Visual insight rendered with its already-collected
  `ConfidenceLevel` and an "AI-generated observation" marker, so "Excellent contrast" is visibly a
  judgment and not a measurement.

### W7 — Text hygiene at the source
`scraper.py`

1. Switch heading extraction from `textContent` to `innerText` plus whitespace collapse — this is the
   direct cause of `KYLIAN MBAPPÉMERCURIAL SUPERFLY`, and it feeds the Copy agent's prompt, so the
   damage is not cosmetic.
2. Normalise quoting/casing when page content is quoted back in prose ("JA 4 'NIGHTMARE'" vs "Ja 4").
3. Apply the same collapse to button and link text before prompt assembly.

### W8 — Frontend parity
`frontend/src/types/audit.ts`, `lib/issueText.ts`, `components/audit/*`

Mirror the schema changes by hand; surface Methodology and Coverage; show the degraded-screenshot
disclosure; render impact/effort/confidence/validation; drop the local WCAG and effort maps in favour of
backend-supplied values.

---

## 6. Release plan

**Release 1 — Credibility (do first; mostly plumbing data we already have)**
W1 screenshot integrity · W2.1–W2.4 performance evidence · W3.1–W3.6 accessibility evidence & dedupe ·
W4.1 SEO coverage disclosure · W5 scoring transparency · W6 metadata, pagination, page numbers, dedupe
of the master list, label map, pluralisation · W7 text hygiene.

*Exit criterion:* every score in the PDF is traceable to a printed measurement, a printed check list, or
an explicit "insufficient evidence" — and no claim contradicts an included image.

**Release 2 — Deliverable quality**
Renderer migration (§4) · cover page · report architecture reorder · Methodology and Appendix sections ·
priority action plan with impact/effort/confidence/owner/timing · tagged, accessible PDF output ·
captioned, legible screenshots · W8 frontend parity.

**Release 3 — Depth**
axe-core integration · expanded SEO checks (W4.2) · median-of-3 Lighthouse runs · annotated screenshot
crops per finding · context-aware recommendations (brand/page-purpose sensitivity instead of a generic
conversion checklist) · trend comparison against a previous audit.

---

## 7. Test plan

The suite runs fully on fakes (`FakeGeminiClient`, `httpx.MockTransport`) — keep it that way.

- `test_screenshot_quality.py` — blank/degraded detection against a synthetic flat-colour PNG and a
  content-bearing one; assert the measured Nike-style profile classifies as `degraded`.
- `test_report.py` — a degraded visual result is excluded from the weighted overall score and reported as
  such; weighted arithmetic; `score_explanation` strings.
- `test_accessibility_agent.py` — WCAG criterion present per check; dedupe on `(check, selector)`;
  occurrence counts; accessible-name computation text.
- `test_performance_agent.py` — metrics and run config survive into the rendered report; opportunity
  parsing produces named resources with sizes and savings.
- `test_pdf_report.py` — metadata populated (title/author/subject/keywords), page numbers present, no
  recommendation rendered twice, no raw enum values (`cta_quality`, `slow_lcp`) anywhere in the text
  layer, degraded-screenshot disclosure rendered.
- `test_scraper.py` — `innerText` extraction collapses whitespace and does not concatenate sibling lines.

---

## 8. Scope limits worth stating in the report itself

The review's deepest point is that an audit must disclose its own limits. These belong in the generated
Methodology section, not just in this document: one URL, one viewport, one run, no authenticated states,
no manual verification pass, automated checks only, WCAG target level stated, and an explicit list of
what each category did not test.
