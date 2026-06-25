FROM python:3.11-slim

WORKDIR /app

COPY shared/ ./shared/
COPY forensics/ ./forensics/
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8088

CMD ["python", "forensics/main.py"]
