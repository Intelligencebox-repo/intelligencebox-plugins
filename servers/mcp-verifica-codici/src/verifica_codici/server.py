import asyncio
import os
import json
from typing import List

# Import necessari da Pydantic per definire i parametri
from pydantic import BaseModel, Field

# Import necessari dal framework MCP
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import delle nostre funzioni logiche dai moduli separati
from .script1 import estrai_elenco_documenti
from .script2 import recupera_percorso_file
from .script3 import genera_immagine_pulita
from .script4 import estrai_codice_immagine
from .script5 import verifica_codici

# Import per la validazione con cartelle
from .code_extractor_folders import FolderCodeExtractor
from .master_list_parser import MasterListParser


# --- Definizione dei Parametri di Input con Pydantic ---
class VerificaCodiciParams(BaseModel):
    index_pdf_path: str = Field(..., description="Il percorso del file PDF che contiene l'elenco dei documenti da verificare.")
    codice_commessa: str = Field(..., description="Il codice della commessa da utilizzare per filtrare i documenti nell'elenco.")
    collection_id: str = Field(..., description="Collection ID dove cercare i documenti da verificare tramite RAG.")

class ValidateFoldersParams(BaseModel):
    documents_folder: str = Field(..., description="Percorso alla cartella contenente i PDF dei documenti da validare (es. '/dataai/collection_name').")
    master_list_pdf: str = Field(..., description="Percorso al file PDF contenente l'elenco master dei documenti attesi (es. '/dataai/collection_name/elenco-documenti.pdf').")


# --- HANDLER PER VALIDATE_FOLDERS ---
async def handle_validate_folders(arguments: dict) -> list[TextContent]:
    """Handler per il tool validate_folders"""
    try:
        # Valida i parametri
        params = ValidateFoldersParams(**arguments)

        # Inizializza gli estrattori
        code_extractor = FolderCodeExtractor()
        list_parser = MasterListParser()

        # Estrai i codici dai documenti nella cartella
        print(f"[INFO] Scansione documenti in: {params.documents_folder}")
        extracted_codes = await asyncio.to_thread(
            code_extractor.extract_from_folder,
            params.documents_folder,
            recursive=False
        )

        # Estrai l'elenco dei codici attesi dalla master list
        print(f"[INFO] Parsing master list da: {params.master_list_pdf}")
        expected_codes = await asyncio.to_thread(
            list_parser.parse_master_list,
            params.master_list_pdf
        )

        # Prepara i set per il confronto (filtra i None)
        extracted_set = set(code for code in extracted_codes.values() if code is not None)
        expected_set = set(expected_codes)

        # Calcola le differenze
        matching = extracted_set & expected_set
        missing_from_documents = expected_set - extracted_set
        unexpected_in_documents = extracted_set - expected_set
        extraction_failures = [filename for filename, code in extracted_codes.items() if code is None]

        # Costruisci il risultato
        result = {
            "summary": {
                "total_pdfs_scanned": len(extracted_codes),
                "codes_extracted_successfully": len([c for c in extracted_codes.values() if c]),
                "extraction_failures": len(extraction_failures),
                "expected_codes_count": len(expected_codes),
                "matching_count": len(matching),
                "missing_count": len(missing_from_documents),
                "unexpected_count": len(unexpected_in_documents)
            },
            "matching": {
                "description": "Codici trovati nei documenti che corrispondono alla master list",
                "codes": sorted(list(matching)),
                "count": len(matching)
            },
            "missing_from_documents": {
                "description": "Codici presenti nella master list ma non trovati nei documenti",
                "codes": sorted(list(missing_from_documents)),
                "count": len(missing_from_documents)
            },
            "unexpected_in_documents": {
                "description": "Codici trovati nei documenti ma non presenti nella master list",
                "codes": sorted(list(unexpected_in_documents)),
                "count": len(unexpected_in_documents)
            },
            "extraction_failures": {
                "description": "File per i quali l'estrazione del codice è fallita",
                "files": extraction_failures,
                "count": len(extraction_failures)
            },
            "details": {
                "description": "Dettaglio di tutti i file scansionati",
                "files": {
                    filename: code if code else "ESTRAZIONE_FALLITA"
                    for filename, code in extracted_codes.items()
                }
            }
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    except FileNotFoundError as e:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=str(e)))
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante la validazione: {str(e)}"))


# --- CREAZIONE DEL SERVER MCP ---
def create_verifica_codici_server() -> Server:
    """
    Crea e configura il server MCP per la verifica dei codici.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """
    server = Server("verifica-codici")

    # --- REGISTRAZIONE DEL TOOL ---
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="start_verification",
                description="Avvia il processo di verifica dei documenti a partire da un file di elenco.",
                inputSchema=VerificaCodiciParams.model_json_schema(),
            ),
            Tool(
                name="validate_folders",
                description="Valida i codici documentali da una cartella di PDF contro un elenco master. Estrae i codici tramite OCR e confronta con la master list.",
                inputSchema=ValidateFoldersParams.model_json_schema(),
            )
        ]

    # --- GESTIONE DELLA CHIAMATA AL TOOL ---
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "validate_folders":
            return await handle_validate_folders(arguments)
        elif name != "start_verification":
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito."))

        try:
            # Validazione dei parametri di input tramite Pydantic
            params = VerificaCodiciParams(**arguments)

            # --- ESECUZIONE DELLA LOGICA DI ORCHESTRAZIONE ---

            # STEP 1 - script1: Estrazione dell'elenco documenti
            elenco_da_controllare = await asyncio.to_thread(estrai_elenco_documenti, params.index_pdf_path, params.codice_commessa)
            if not elenco_da_controllare:
                return [TextContent(type="text", text="Verifica completata: nessun documento trovato nell'elenco fornito.")]
            
            risultati_negativi = []
            risultati_positivi = []
            # Inizio ciclo di elaborazione
            for doc in elenco_da_controllare:
                titolo_documento = doc.get('titolo', 'Titolo Sconosciuto')
                
                try:
                    # STEP 2 - script2: Recupero del file specifico tramite RAG
                    percorso_file = await recupera_percorso_file(titolo_documento, params.collection_id)
                    
                    # STEP 3 - script3: Generazione dell'immagine pulita
                    immagine_pulita = await asyncio.to_thread(genera_immagine_pulita, percorso_file)
                    if immagine_pulita is None:
                        raise ValueError("Generazione dell'immagine pulita fallita.")

                    # STEP 4 - script4: Estrazione del codice tramite Tesseract
                    codice_estratto = await asyncio.to_thread(estrai_codice_immagine, immagine_pulita)

                    # STEP 5 - script5: Verifica dei codici
                    risultato_verifica = verifica_codici(doc, codice_estratto)

                    if risultato_verifica['status'] == 'FAILED':
                        risultati_negativi.append(risultato_verifica)
                    elif risultato_verifica['status'] == 'SUCCESS':
                        risultati_positivi.append(risultato_verifica)
                
                except Exception as e:
                    risultati_negativi.append({
                        'titolo_documento': titolo_documento,
                        'status': 'FAILED',
                        'error_details': f"Errore durante l'elaborazione: {str(e)}"
                    })
                    continue
            
            # --- Creazione del Report Finale ---
            if not risultati_negativi:
                report_lines = [f"Successo! I codici di tutti i {len(elenco_da_controllare)} documenti analizzati coincidono."]
                for ris in risultati_positivi:
                    line = (
                        f"- Titolo: {ris['titolo_documento']}\n"
                        f"  Codice Atteso:   {ris.get('codice_atteso', 'N/A')}\n"
                        f"  Codice Estratto: {ris.get('codice_estratto', 'N/A')}"
                    )
                    report_lines.append(line)
                report_finale = "\n".join(report_lines)
            else:
                report_lines = [f"Sono stati trovati {len(risultati_negativi)} documenti con errori:"]
                for res in risultati_negativi:
                    line = (
                        f"- Titolo: {res['titolo_documento']}\n"
                        f"  Codice Atteso:   {res.get('codice_atteso', 'N/A')}\n"
                        f"  Codice Estratto: {res.get('codice_estratto', 'N/A')}\n"
                        f"  Dettagli Errore: {res.get('error_details', 'N/A')}"
                    )
                    report_lines.append(line)
                if risultati_positivi:
                    report_lines.append(f"\n--- DOCUMENTI CORRETTI ({len(risultati_positivi)}) ---")
                    for ris in risultati_positivi:
                        line = (
                            f"- Titolo: {ris['titolo_documento']}\n"
                            f"  Codice Atteso:   {ris.get('codice_atteso', 'N/A')}\n"
                            f"  Codice Estratto: {ris.get('codice_estratto', 'N/A')}"
                        )
                        report_lines.append(line)

                report_finale = "\n".join(report_lines)

            return [TextContent(type="text", text=report_finale)]

        except Exception as e:
            # Cattura errori di validazione Pydantic o altri errori imprevisti
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante l'esecuzione del tool: {e}"))

    return server


# --- FUNZIONE PRINCIPALE DEL SERVER (STDIO MODE) ---
async def serve():
    """
    Funzione principale che configura e avvia il server MCP per la verifica dei codici in modalità stdio.
    """
    server = create_verifica_codici_server()

    # --- AVVIO DEL SERVER IN MODALITÀ STDIO ---
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)