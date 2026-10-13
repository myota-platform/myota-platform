FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/myota-platform/myota-platform"

WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends -y postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
CMD ["python3", "services/runner.py"]
