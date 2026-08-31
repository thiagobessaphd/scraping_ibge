FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/pwuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=pwuser:pwuser scraping_ibge_municipios.py .

# A imagem oficial fornece o usuário sem privilégios "pwuser" e os
# navegadores instalados em /ms-playwright. O diretório é criado aqui para
# também funcionar quando não houver um volume montado pelo Compose.
RUN mkdir -p /app/resultados_ibge \
    && chown -R pwuser:pwuser /app

USER pwuser

CMD ["python", "scraping_ibge_municipios.py"]
