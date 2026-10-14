# The verification image: Playwright's own Python image (Chromium and its system libraries already in it) plus the pinned
# test dependencies, the e2e suite and the fixtures. It plays two parts in docker/compose.verify.yml: `e2e` runs pytest
# against the app container, and `feedstub` serves the fixtures over HTTP as the stand-in for both feed hosts.
#
# The tag below must equal the `playwright==` pin in e2e/requirements.txt: scripts/verify.py compares them (gate
# playwright-pin), because a browser and a client of different versions is the classic way to lose an afternoon.
#
#     docker build -f e2e/Dockerfile -t tradingjournal/e2e:local .      (from the repository root)
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

# This container exists to run the suite and nothing else, so the pinned lock goes straight into its Python (the image
# marks it "externally managed", which protects a machine's own Python and does not apply to a throwaway test runner).
# The browsers are not part of this install: they live where the image put them (PLAYWRIGHT_BROWSERS_PATH), and the
# pin above is what makes the client match them.
ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1     PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /work/e2e
COPY e2e/requirements.txt ./
RUN pip install -r requirements.txt

COPY e2e/ ./
COPY fixtures/ /work/fixtures/
