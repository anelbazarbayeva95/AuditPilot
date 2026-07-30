import { scrollToSection } from "@/components/audit/ResultsSidebar"

export interface SubNavItem {
  id: string
  label: string
}

/**
 * Right rail for the Results "Docs Layout" — jump links to the sub-blocks
 * (or individual issues) within whichever section is currently active.
 * Built from real report data by the parent page, not a hardcoded list, so
 * it always matches what's actually rendered (e.g. one entry per real issue).
 */
export function ResultsSubNav({ title, items }: { title: string; items: SubNavItem[] }) {
  if (items.length === 0) return null

  return (
    <aside className="hidden border-l px-6 py-8 lg:sticky lg:top-0 lg:block lg:h-svh lg:self-start lg:overflow-y-auto print:hidden">
      <div className="mb-2.5 text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        {title}
      </div>
      <nav className="flex flex-col gap-2">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => scrollToSection(item.id)}
            className="line-clamp-2 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {item.label}
          </button>
        ))}
      </nav>
    </aside>
  )
}
