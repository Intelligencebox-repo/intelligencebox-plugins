# test_local.py
import os
from src.pdf_generator.server import create_pdf_file

input_filename = "lutaro_story.md"

print(f"Caricamento del testo dal file: {input_filename}...")

try:
    with open(input_filename, "r", encoding="utf-8") as f:
        # Legge tutto il contenuto del file
        markdown_text = f.read()
except FileNotFoundError:
    print(f"ERRORE: File '{input_filename}' non trovato. Crealo prima di eseguire il test.")
    exit()

# Trova la prima riga che è un titolo per usarla come nome del file
pdf_title = "documento_senza_titolo"
for line in markdown_text.split('\n'):
    stripped_line = line.strip()
    if stripped_line.startswith('# '):
        # Prende il testo dopo '# ', lo pulisce e lo usa come nome file
        pdf_title = stripped_line[2:].strip().replace(' ', '_').lower()
        break
    elif stripped_line.startswith('## '):
        pdf_title = stripped_line[3:].strip().replace(' ', '_').lower()
        break
### Aggiungere un caso in cui non ci sono titoli

print("Avvio del test di generazione PDF...")

# Chiama la funzione con i dati letti dal file
risultato = create_pdf_file(
    filename=f"{pdf_title}.pdf",
    text_content=markdown_text
)

# Stampa il messaggio di successo restituito dalla funzione
print(risultato)
print("Test completato. Controlla la cartella 'output'.")