# AuditPilot Design System — semantic tokens

Scope: the shared colour and meaning vocabulary used by the dashboard, and
(from Release 2) the PDF. Layout, spacing, and typography conventions live in
the components themselves; this document covers the part that carries meaning.

---

## 1. The palette question

The review proposed a deep-navy / blue-primary palette (`#2563EB`, `#0F766E`,
`#F5F7FA`) and correctly flagged it as placeholder. Adopting it as-is would have
been the wrong move: **AuditPilot already has a brand**, and it isn't navy.

The existing identity, defined in `frontend/src/index.css` and used across the
product:

| Role | Value | Notes |
|---|---|---|
| Canvas | `#faf9f5` | warm cream, not the usual blue-grey SaaS wash |
| Ink | `#16181d` | near-black; also the "spotlight" panel surface |
| Brand accent | `oklch(85% 0.19 128)` | bright lime |
| Display / body | Syne / Instrument Sans | — |

The cream-and-lime combination is distinctive in a category where nearly every
competitor ships blue-on-white. Replacing it with another blue would have cost
the one genuinely differentiated thing the visual identity already had, so the
brand foundation is **kept**, and the semantic system is built to fit it.

What the review got exactly right is the underlying diagnosis: **one hue was
doing too many jobs.** Lime was simultaneously the brand accent, the primary
CTA, "success", "good status", the focus ring, and the quick-fix chip — the same
failure the review identified with orange in the PDF. That is what this system
fixes.

---

## 2. Three separate axes

Each axis owns its hues. A hue from one axis never appears in another, so no
meaning gets diluted.

### Brand (unchanged)

`--primary` (lime) is now reserved for **brand moments and primary actions
only**: the logo mark, the primary button, the focus ring, and the "good" score
bar fill. It is never a text colour and never a status label — its contrast on
cream is 1.4:1, which is fine for a fill with ink on top (11.8:1) and unusable
for text.

### Provenance — *what kind of claim is this?*

The product's real differentiator is that it distinguishes a measurement from an
opinion from a refusal to judge. That distinction now has a visible language
rather than being left to prose.

| Token | Value | Meaning |
|---|---|---|
| `--measured` | `oklch(46% 0.09 205)` teal | detected by a deterministic check |
| `--judgment` | `oklch(48% 0.14 292)` violet | an AI-generated observation |
| `--withheld` | `oklch(50% 0.03 250)` slate | evidence insufficient; no assessment made |

Each has a `-bg` tint for chips and panels. Teal reads as an instrument reading,
violet holds the model's opinion at arm's length, and slate is deliberately
colourless — a refusal to judge should not look like a result.

### Severity — *how bad is this finding?*

| Token | Value |
|---|---|
| `--severity-critical` | `oklch(44% 0.19 25)` |
| `--severity-high` | `oklch(53% 0.18 38)` |
| `--severity-medium` | `oklch(54% 0.13 75)` |
| `--severity-low` | `oklch(50% 0.02 250)` |

Critical and high were previously the same red, flattening the scale exactly
where a reader most needs it separated.

### Score bands — *how healthy is this category?*

Four bands, matching the thresholds the PDF prints under the overall score
(`backend/labels.py::SCORE_BANDS` and `frontend/src/lib/score.ts::getScoreBand`
must agree):

`0–39 Critical · 40–69 Needs attention · 70–89 Good · 90–100 Excellent`

The scale is published beside the score. A number with no stated scale forces
the reader to invent one.

---

## 3. Contrast

Every text token clears WCAG AA (4.5:1) against both surfaces it can appear on —
the cream page and a white card. Verified by computing sRGB from OKLCH and the
WCAG relative-luminance ratio:

| Token | Hex | on cream | on white |
|---|---|---|---|
| measured | `#006670` | 6.38 | 6.72 |
| judgment | `#614aa5` | 6.57 | 6.92 |
| withheld | `#576574` | 5.68 | 5.98 |
| severity-critical | `#a2000f` | 7.85 | 8.27 |
| severity-high | `#bc3500` | 5.44 | 5.74 |
| severity-medium | `#a06700` | 4.79 | 5.05 |
| status-good | `#3b7b00` | 4.93 | 5.20 |
| status-poor | `#ac3037` | 6.19 | 6.53 |

Ink on lime (the primary button) is 11.75:1.

An audit product that fails contrast in its own report would be self-refuting,
so this table is the acceptance criterion for any new token — re-run
`scratchpad/contrast.py` before adding one.

---

## 4. Usage rules

1. **Never colour alone.** Every provenance chip carries a word ("Measured",
   "AI judgment") and an icon; every severity carries a text badge. This is the
   first rule in the UI UX Pro Max accessibility checklist and it is also the
   only way these distinctions survive greyscale printing.
2. **One hue, one job.** Adding a meaning means adding a token, not overloading
   an existing one.
3. **Tinted backgrounds are for panels, not text.** All `-bg` tints keep ink at
   ≥15:1.
4. **Numbers use `tabular-nums`.** Scores and metrics are compared down a
   column; proportional digits make them jitter.
5. **Focus is always visible** (`focus-visible:ring-2 ring-ring`), and motion
   respects `prefers-reduced-motion`.

---

## 5. Provenance in practice

| Surface | Treatment |
|---|---|
| Finding card | provenance chip in a subdued metadata footer, below the recommendation |
| Scorecard | Confidence column: "High — automated checks" vs "Medium — model judgment" |
| Withheld category | slate panel stating the decision, the measurements behind it, and the failed capture as labelled diagnostic evidence |
| Executive summary | "Audit confidence" as one of three lead messages |

The withheld treatment matters most: it's where the product says *we know when
not to make a claim*, which is the thing the review identified as worth making
prominent.
