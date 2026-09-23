FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
CMD ["python3", "services/runner.py"]

