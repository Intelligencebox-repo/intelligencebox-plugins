# Usa un'immagine Python ufficiale e leggera come base
FROM python:3.12-slim

# Cartella di Lavoro
WORKDIR /app

# Copia e Installazione delle Dipendenze Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia del Codice Sorgente
COPY ./src ./src

# Configurazione dell'Ambiente Python
ENV PYTHONPATH="/app/src"

# Comando di Avvio - usa SSE mode di default per Docker
CMD ["python", "-m", "drafting_assistant.sse_server"]