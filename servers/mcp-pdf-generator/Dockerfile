# Usa un'immagine Python ufficiale e leggera come base
FROM python:3.12-slim

# Imposta la cartella di lavoro all'interno del container
WORKDIR /app

COPY requirements.txt ./

# Installa le dipendenze usando pip. È il metodo più standard e affidabile.
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice sorgente nella cartella di lavoro
COPY ./src ./src

# Dice a Python di cercare i pacchetti anche nella cartella /app/src
ENV PYTHONPATH="/app/src"

# Comando da eseguire quando il container viene avviato
CMD ["python", "-m", "pdf_generator"]