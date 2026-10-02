FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY . .
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
CMD ["uvicorn", "qco_watch.api:app", "--host", "0.0.0.0", "--port", "8000"]
