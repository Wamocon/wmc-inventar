# WMC Inventar – Docker-Image (N-01)
# Der Bau braucht Internet (Basis-Image, Systempakete, Python-Pakete).

ARG BASIS=python:3.12-slim
FROM ${BASIS}

# Systempakete (Pango, HarfBuzz für WeasyPrint)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libffi8 \
        fonts-dejavu-core \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/inventar

COPY requirements.txt requirements-test.txt /srv/inventar/
RUN pip install -r requirements.txt

COPY . /srv/inventar/

# Statische Dateien entstehen beim Bau; der Schlüssel des Entwicklungsmodus gilt nur für diesen Schritt.
RUN INVENTAR_DEBUG=1 python manage.py collectstatic --noinput

RUN useradd --system --uid 1000 --create-home inventar && mkdir -p var && chown -R inventar:inventar var
USER inventar

EXPOSE 8000
CMD ["gunicorn", "inventar.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
