FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Avoid heavy GPU wheels; use CPU-only torch if needed in CI
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "src.web_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
