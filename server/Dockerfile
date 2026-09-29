# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Browser-based features (Mermaid diagram rendering, LCSC automation) are off by
# default to keep the image small. Opt in with:
#   docker compose build --build-arg INSTALL_PLAYWRIGHT_BROWSERS=1
ARG INSTALL_PLAYWRIGHT_BROWSERS=0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# The app derives the repo root from Path(__file__).parents[4] in
# fde_api/documents/catalog.py, expecting <root>/server/src + <root>/resources.
# Working from /app/server keeps that layout intact.
WORKDIR /app/server

# PyMySQL and redis-py are pure Python, so no compiler or *-dev system packages
# are needed. Dependencies land in their own layer for build caching.
COPY server/requirements.lock /app/server/requirements.lock
RUN pip install -r /app/server/requirements.lock

# Editable install on purpose: a regular install would copy fde_api into
# site-packages and break the parents[4] repo-root lookup, which would make the
# bundled document templates unresolvable.
COPY server/pyproject.toml server/alembic.ini /app/server/
COPY server/migrations/ /app/server/migrations/
COPY server/src/ /app/server/src/
RUN pip install --no-deps -e /app/server

COPY resources/ /app/resources/

RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "1" ]; then \
        playwright install --with-deps chromium; \
    fi

# LibreOffice and ClamAV are intentionally absent: document preview and virus
# scanning degrade gracefully (previews report failure, scanning is marked
# not_required) rather than blocking startup.
RUN useradd --create-home --uid 10001 fde \
    && mkdir -p /app/server/.fde-storage \
    && chown -R fde:fde /app
USER fde

EXPOSE 8010

# Long-running AI calls exceed gunicorn's 30s default, hence the raised timeout.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8010", \
     "--workers", "2", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "fde_api.wsgi:app"]
