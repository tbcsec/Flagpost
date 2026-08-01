FROM python:3.14-slim

WORKDIR /app

# Install deps first so the layer caches across source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Baked in by release-images.yml from the git tag (#111). Stays "dev" for a
# source build, which is reported as-is — someone running from source is a real
# deployment, just distinguishable from a released one.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8000

# docker-compose overrides this with --reload for development.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
