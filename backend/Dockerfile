# Backend image for Railway/Fly/any container host. One image, two processes:
#   web:    uvicorn app.main:app   (default CMD)
#   worker: python -m app.worker   (override the start command on a second service)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /srv
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
RUN useradd --system --uid 10001 arena && chown -R arena /srv
USER arena
EXPOSE 8080
# $PORT is assigned by the host; --proxy-headers so client addresses come from X-Forwarded-For; no --reload, no debug.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20 --no-server-header"]
