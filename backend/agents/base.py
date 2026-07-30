"""
Base agent interface.

Every audit agent (accessibility, performance, SEO, copy) implements this
interface so the orchestrator can run them interchangeably. No implementation
logic lives here — this is the contract only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from models.schemas import AuditCategory, CategoryResult


class BaseAgent(ABC):
    """Abstract base class for all AuditPilot agents.

    Concrete agents are expected to:
      1. Accept prepared page data (e.g. rendered HTML/DOM, Playwright page,
         Lighthouse report, or scraped copy) via `analyze`.
      2. Return a `CategoryResult` with a score, summary, and recommendations.
      3. Use the Gemini client (injected or constructed internally) to turn
         raw findings into actionable, human-readable recommendations.
    """

    category: AuditCategory

    @abstractmethod
    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        """Run this agent's analysis for the given URL.

        Args:
            url: The target URL being audited.
            context: Shared data gathered upfront by the orchestrator
                (e.g. Playwright page content, Lighthouse JSON, screenshots).

        Returns:
            A CategoryResult describing this agent's findings.
        """
        raise NotImplementedError
