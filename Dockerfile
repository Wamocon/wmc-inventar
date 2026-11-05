# WMC Inventar – Docker-Image (N-01)
# Ohne Internet: docker build --build-arg BASIS=wmc-inventar-basis:1 --build-arg WHEELHOUSE=wheelhouse .
# Mit Internet:  docker build .

ARG BASIS=python:3.12-slim
FROM ${BASIS}

ARG WHEELHOUSE=

# Systempakete (Pango, HarfBuzz für WeasyPrint) – nur nachinstallieren, wenn sie fehlen
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libffi8 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/inventar

COPY requirements.txt requirements-test.txt /srv/inventar/
RUN if [ -n "${WHEELHOUSE}" ]; then \
      pip install --no-index --find-links /srv/inventar/wheelhouse -r requirements.txt; \
    else \
      pip install -r requirements.txt; \
    fi

COPY . /srv/inventar/

# Statische Dateien entstehen beim Bau; der Schlüssel des Entwicklungsmodus gilt nur für diesen Schritt.
RUN INVENTAR_DEBUG=1 python manage.py collectstatic --noinput

RUN useradd --system --uid 1000 inventar && mkdir -p var && chown -R inventar:inventar var
USER inventar

EXPOSE 8000
CMD ["gunicorn", "inventar.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
