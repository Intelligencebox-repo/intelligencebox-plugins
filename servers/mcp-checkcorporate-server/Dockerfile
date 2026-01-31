FROM python:3.12-slim

WORKDIR /app

# Copia e installa dipendenze
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia sorgenti
COPY ./src ./src

ENV PYTHONPATH="/app/src"

EXPOSE 8080

# Avviare in modalità stdio è possibile: override del comando
# Default: avvia il modulo principale
CMD ["python", "-m", "checkcorporate_server"]
