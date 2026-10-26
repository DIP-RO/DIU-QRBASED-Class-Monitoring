FROM node:24-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY backend backend
COPY migrations migrations
COPY alembic.ini ./
COPY --from=ui /src/frontend/dist frontend/dist
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/diu_monitor.db
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]

