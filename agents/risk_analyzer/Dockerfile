FROM python:3.11-slim

WORKDIR /app

# Shared package + agent code
COPY shared/ ./shared/
COPY risk_analyzer/ ./risk_analyzer/
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8088

CMD ["python", "risk_analyzer/main.py"]
