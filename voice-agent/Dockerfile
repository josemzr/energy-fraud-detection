FROM python:3.12-slim-bookworm

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
COPY app ./app/
COPY static ./static/

ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "hypercorn server:app --bind 0.0.0.0:${PORT:-8000}"]
