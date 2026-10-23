FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 1000 brasil
COPY --chown=brasil:brasil . .
USER brasil
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=4).status == 200 else 1)"
# o IP real do cliente é tratado pela própria aplicação (app/seguranca.py, PROXIES_CONFIAVEIS); o uvicorn não confia em X-Forwarded-*
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-proxy-headers", "--limit-concurrency", "200", "--timeout-keep-alive", "10"]
