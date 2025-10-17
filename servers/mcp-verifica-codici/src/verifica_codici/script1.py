import pdfplumber

def estrai_elenco_documenti(percorso_file, codice):
    lista_documenti = []
    with pdfplumber.open(percorso_file) as pdf:
        for page in pdf.pages[1:]:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and len(row) > 13 and row[0] == codice:
                        doc = {
                            'commessa': row[0] if row[0] else '/',
                            'lotto': row[1] if row[1] else '/',
                            'fase': row[2] if row[2] else '/',
                            'capitolo': row[3] if row[3] else '/',
                            'paragrafo': row[4] if row[4] else '/',
                            'WBS': row[5] if row[5] else '/',
                            'parte d-opera': row[6] if row[6] else '/',
                            'tipologia': row[7] if row[7] else '/',
                            'disciplina': row[8] if row[8] else '/',
                            'progressivo': row[9] if row[9] else '/',
                            'revisione': row[10] if row[10] else '/',
                            'titolo': row[11] if row[11] else '/',
                            'formato': row[12] if row[12] else '/',
                            'scala': row[13] if row[13] else '/'
                        }
                        lista_documenti.append(doc)
                        
    return lista_documenti