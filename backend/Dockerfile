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
# $PORT is assigned by the host; no --reload, no debug. --no-proxy-headers: uvicorn must NOT rewrite the client address from a header any
# client can send; the app decides what to trust (TRUSTED_PROXY_HOPS, see docs/DEPLOYMENT.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-proxy-headers --timeout-graceful-shutdown 20 --no-server-header"]
