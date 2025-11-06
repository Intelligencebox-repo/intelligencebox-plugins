# Usa un'immagine Python ufficiale e leggera come base
FROM python:3.12-slim

# Cartella di Lavoro
WORKDIR /app

# Installa dipendenze di sistema per OpenCV e PDF processing
RUN apt-get update && \
    apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copia e Installazione delle Dipendenze Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia del Codice Sorgente
COPY ./src ./src

# Configurazione dell'Ambiente Python
ENV PYTHONPATH="/app/src"

# Comando di Avvio - usa SSE mode per Docker (stdio via docker exec)
CMD ["python", "-m", "verifica_codici.sse_server"]