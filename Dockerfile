# --- Stage 1: build the Angular dashboard ---
FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: FastAPI runtime serving the API + the built dashboard ---
FROM python:3.11-slim
WORKDIR /app
COPY app/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/backend/ ./
# Angular output (application builder) lands in dist/frontend/browser
COPY --from=web /web/dist/frontend/browser ./static
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
