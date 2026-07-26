FROM python:3.14-slim

WORKDIR /app

# Install deps first so the layer caches across source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# docker-compose overrides this with --reload for development.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
