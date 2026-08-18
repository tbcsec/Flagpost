FROM python:3.14-slim

WORKDIR /app

# WeasyPrint (post-event reports, #134 / ADR-0030) renders PDF via Pango/cairo.
# It's pure-Python but dlopen's these system libraries at runtime; installed as an
# early, stable layer so it caches across source and dependency changes. The
# bundled OFL fonts ship in the source; fonts-dejavu-core is only a glyph fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install deps first so the layer caches across source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Baked in by release-images.yml from the git tag (#111).
#
# The default is deliberately **empty**, not a version string. A Dockerfile has
# no conditional ENV, so this always sets the variable — and pydantic-settings
# gives an env var priority over the Python default. Any literal here would
# therefore shadow config.SOURCE_BUILD_VERSION and every source build would
# report it, which is exactly the bug this replaced. Empty means "not a release
# image"; config.py resolves it to the source-build version.
ARG APP_VERSION=
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8000

# docker-compose overrides this with --reload for development.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
