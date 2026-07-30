import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Card, CardContent } from "@/components/ui/card"
import { formatScore, getScoreBand, scoreBandLabel } from "@/lib/score"
import type { ReportSummary } from "@/types/audit"

// Exact hex equivalents of the oklch status/severity tokens in index.css
// (recharts needs literal color strings, not CSS custom properties).
const SCORE_BAND_HEX: Record<string, string> = {
  good: "#a9e44a", // --status-good-bar: oklch(85% 0.19 128)
  "needs-work": "#e38f00", // --status-needs-work-bar: oklch(72% 0.16 70)
  poor: "#b63039", // --status-poor-bar: oklch(52% 0.17 22)
  unknown: "#9ca3af",
}

const SEVERITY_HEX: Record<string, string> = {
  critical: "#b63039", // --destructive: oklch(52% 0.17 22)
  high: "#b63039",
  medium: "#eb8a00", // --warning: oklch(72% 0.17 65)
  low: "#726e66", // --muted-foreground
  info: "#a7a39a",
}

const CATEGORY_LABELS: Record<string, string> = {
  accessibility: "Accessibility",
  seo: "SEO",
  performance: "Performance",
  copy: "Copy",
  visual: "Visual",
}

const TOOLTIP_BOX = "rounded-lg border bg-card px-3 py-2 text-xs shadow-sm"

function ScoreTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { label: string; score: number } }> }) {
  if (!active || !payload?.length) return null
  const { label, score } = payload[0].payload
  const band = getScoreBand(score)
  return (
    <div className={TOOLTIP_BOX}>
      <div className="font-semibold">{label}</div>
      <div className="mt-0.5 text-muted-foreground">
        {formatScore(score)}/100 · {scoreBandLabel[band]}
      </div>
      <div className="mt-1 text-[11px] text-link">Click to view →</div>
    </div>
  )
}

function SeverityTooltip({
  active,
  payload,
  total,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number }>
  total: number
}) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className={TOOLTIP_BOX}>
      <div className="font-semibold capitalize">{name}</div>
      <div className="mt-0.5 text-muted-foreground">
        {value} issue{value === 1 ? "" : "s"} · {pct}% of total
      </div>
      <div className="mt-1 text-[11px] text-link">Click to view action list →</div>
    </div>
  )
}

export function ChartsSection({
  summary,
  onSelectCategory,
  onViewActions,
}: {
  summary: ReportSummary
  /** Clicking a category's bar switches the Results left rail to that category. */
  onSelectCategory: (category: string) => void
  /** Clicking a severity slice jumps to the Prioritized Action List. */
  onViewActions: () => void
}) {
  const scoreData = Object.entries(summary.category_scores).map(([category, score]) => ({
    category,
    label: CATEGORY_LABELS[category] ?? category,
    score: score ?? 0,
    fill: SCORE_BAND_HEX[getScoreBand(score)],
  }))

  const issueData = Object.entries(summary.issue_counts)
    .filter(([, count]) => count > 0)
    .map(([severity, count]) => ({ name: severity, value: count }))
  const totalIssues = issueData.reduce((sum, entry) => sum + entry.value, 0)

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card id="chart-scores" className="scroll-mt-24 break-inside-avoid rounded-[22px] p-8 shadow-none">
        <div className="font-display text-xl font-bold">Category Scores</div>
        <p className="mt-1 text-[13px] text-muted-foreground">Click a bar to jump to that category.</p>
        <CardContent className="mt-5 p-0">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={scoreData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  interval={0}
                  tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} />
                <Tooltip content={<ScoreTooltip />} cursor={{ fill: "var(--secondary)" }} />
                <Bar dataKey="score" radius={[6, 6, 0, 0]} cursor="pointer">
                  {scoreData.map((entry) => (
                    <Cell
                      key={entry.category}
                      fill={entry.fill}
                      onClick={() => onSelectCategory(entry.category)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card id="chart-severity" className="scroll-mt-24 break-inside-avoid rounded-[22px] p-8 shadow-none">
        <div className="font-display text-xl font-bold">Issues by Severity</div>
        <p className="mt-1 text-[13px] text-muted-foreground">
          {issueData.length > 0 ? "Click a segment to view the action list." : " "}
        </p>
        <CardContent className="mt-5 p-0">
          <div className="h-64 w-full">
            {issueData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                No issues found — nice and clean.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={issueData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={2}
                    cursor="pointer"
                    onClick={onViewActions}
                  >
                    {issueData.map((entry) => (
                      <Cell key={entry.name} fill={SEVERITY_HEX[entry.name] ?? "#6b7280"} />
                    ))}
                  </Pie>
                  <Tooltip content={<SeverityTooltip total={totalIssues} />} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          {issueData.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[13px] text-muted-foreground">
              {issueData.map((entry) => (
                <li key={entry.name} className="flex items-center gap-1.5">
                  <span
                    className="size-2.5 rounded-full"
                    style={{ background: SEVERITY_HEX[entry.name] ?? "#6b7280" }}
                  />
                  {entry.name} ({entry.value})
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
