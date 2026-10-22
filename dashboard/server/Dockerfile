FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Seoul
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt
COPY server/*.py /app/server/
COPY common/*.py /app/common/
COPY dashboard/ /app/dashboard/
WORKDIR /app/server
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/status', timeout=3)"
EXPOSE 8790
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8790"]
