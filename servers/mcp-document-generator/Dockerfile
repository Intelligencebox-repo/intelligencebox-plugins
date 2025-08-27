# Usa un'immagine Python ufficiale e leggera come base
FROM python:3.12-slim

# 2. Installazione di Pandoc
# Aggiorna la lista dei pacchetti e installa Pandoc nel sistema operativo del container
RUN apt-get update && apt-get install -y pandoc

# 3. Cartella di Lavoro
WORKDIR /app

# 4. Copia e Installazione delle Dipendenze Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copia del Codice Sorgente
COPY ./src ./src

# 6. Configurazione dell'Ambiente Python
ENV PYTHONPATH="/app/src"


# Esponi la porta 8000 per il server web
EXPOSE 8000


# 7. Comando di Avvio
CMD ["python", "-m", "document_generator"]