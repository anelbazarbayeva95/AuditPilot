import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Strips the query string/hash and "www." for a compact, readable display of
 * a URL that may otherwise carry a long tracking query string (UTM params,
 * Google Ads click IDs, etc). Presentation-only — the real, full URL is still
 * what's sent to the backend and used everywhere the exact value matters.
 */
export function formatDisplayUrl(url: string): string {
  try {
    const parsed = new URL(url)
    const path = parsed.pathname === "/" ? "" : parsed.pathname
    return `${parsed.hostname.replace(/^www\./, "")}${path}`
  } catch {
    return url
  }
}
