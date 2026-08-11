# AuditPilot backend — FastAPI + Playwright (Chromium) + Lighthouse (Node/npx).
#
# Needs Python (the app itself, Playwright's own browser automation) *and* Node
# (PerformanceAgent shells out to `npx --yes lighthouse`, see lighthouse_runner.py)
# in the same image — there's no way to split this across a slimmer single-runtime
# base without losing the Performance category.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Node, for the `npx lighthouse` call below and at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

# Installed globally so lighthouse_runner.py's `npx --yes lighthouse` resolves
# it locally instead of fetching the package over the network on every cold
# start (npx only skips the fetch when the package is already resolvable).
RUN npm install -g lighthouse

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os, urllib.request; p = os.environ.get('PORT', '8000'); urllib.request.urlopen('http://localhost:' + p + '/health', timeout=3)" || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
