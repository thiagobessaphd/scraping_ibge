FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 1001 appuser

COPY --chown=appuser:appuser scraping_ibge_municipios.py .

RUN mkdir -p /app/resultados_ibge \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "scraping_ibge_municipios.py"]
