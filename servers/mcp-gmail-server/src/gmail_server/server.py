import asyncio
import os
from typing import Optional, List, Literal
import json

from pydantic import BaseModel, Field

# Import per MCP
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import Tool, ErrorData, TextContent, INTERNAL_ERROR, INVALID_PARAMS

# Import classe di logica Gmail
from .gmail_tools import GmailTools


# --- DEFINIZIONE DEI PARAMETRI PER I TOOL ---
class AttachmentParams(BaseModel):
    filename: str = Field(description="Nome del file da allegare, inclusa l'estensione.")
    content_base64: str = Field(description="Contenuto dell'allegato codificato in base64.")
    mime_type: Optional[str] = Field(None, description="Tipo MIME dell'allegato (default: application/octet-stream se non specificato).")

class SendEmailParams(BaseModel):
    to: str = Field(description="L'indirizzo email del destinatario.")
    subject: str = Field(description="L'oggetto dell'email.")
    body: str = Field(description="Il corpo del testo dell'email.")
    body_type: Literal['plain', 'html'] = Field('plain', description="Il formato del corpo dell'email, 'plain' o 'html'.")
    attachments: Optional[List[AttachmentParams]] = Field(None, description="Lista di allegati come contenuto base64 con nome file e MIME type opzionale.")
    attachment_paths: Optional[List[str]] = Field(None, description="Una lista di percorsi di file da allegare.")

class SearchEmailsParams(BaseModel):
    query: Optional[str] = Field(None, description="La query di ricerca (es. 'from:boss@example.com').")
    label: Literal['ALL', 'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH'] = Field('INBOX', description="L'etichetta in cui cercare.")
    max_results: Optional[int] = Field(10, description="Il numero massimo di risultati da restituire.")

class EmailIdParams(BaseModel):
    msg_id: str = Field(description="L'ID univoco del messaggio Gmail.")

# Per gestire l'autenticazione
class CompleteAuthParams(BaseModel):
    code_url: str = Field(description="L'URL completo a cui l'utente è stato reindirizzato da Google (anche se la pagina mostra un errore).")


# --- CREAZIONE DEL SERVER MCP ---
def create_gmail_server() -> Server:
    """
    Crea e configura il server MCP per Gmail.
    Questa funzione può essere riutilizzata per diversi tipi di trasporto.
    """
    # --- SETUP per l'auth ---
    gmail_tool = GmailTools()

    # --- CREAZIONE DEL SERVER MCP ---
    server = Server("gmail_server")

    # --- REGISTRAZIONE DEI TOOL (con lo stile @server.list_tools) ---
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [

            # Tool autenticazione
            Tool(name="start-authentication", description="Tool per l'autenticazione. Controlla se l'utente è già autenticato. Se non lo è, restituisce l'URL di Google per il consenso. A questo punto il modello deve inviare questo url al'utente per procedere con l'autenticazione. Se l'utente è già autenticato, restituisce un messaggio di conferma.", inputSchema={"type": "object", "properties": {}}),
            Tool(name="complete-authentication", description="Tool per finalizzare l'autenticazione. Riceve l'URL completo di reindirizzamento fornito dall'utente, estrae il codice di autorizzazione e salva il token per abilitare l'uso degli altri tool.", inputSchema=CompleteAuthParams.model_json_schema()),
            Tool(name="logout", description="Tool per disconnettere l'account Google dell'utente. Cancella il token di accesso salvato. Dopo aver usato questo tool, l'utente dovrà eseguire di nuovo l'autenticazione per usare le altre funzioni.", inputSchema={"type": "object", "properties": {}}),

            # Tool Gmail
            Tool(name="send-email", description="Invia una email tramite Gmail (testo o HTML) con supporto per allegati via percorso file o payload base64. Richiede i parametri 'to', 'subject', e 'body'.", inputSchema=SendEmailParams.model_json_schema()),
            Tool(name="search-emails", description="Cerca email in Gmail. Permette di filtrare per 'query' (es. 'from:mario@rossi.it'), 'label' (es. 'INBOX'), e 'max_results'. Restituisce un elenco di email con i loro dettagli, incluso il 'msg_id' univoco necessario per gli altri tool.", inputSchema=SearchEmailsParams.model_json_schema()),
            Tool(name="get-email-details", description="Tool per ottenere i metadati di una email specifica, dato il suo 'msg_id'. Restituisce mittente, oggetto, data, snippet, ma non il corpo completo del messaggio.", inputSchema=EmailIdParams.model_json_schema()),
            Tool(name="get-email-body", description="Tool per estrarre e leggere il corpo completo (in formato testo) di una email specifica, dato il suo 'msg_id'. Usalo quando l'utente chiede di leggere il contenuto di un messaggio.", inputSchema=EmailIdParams.model_json_schema()),
            Tool(name="delete-email", description="Tool per cancellare un messaggio di posta specifico, dato il suo 'msg_id'.", inputSchema=EmailIdParams.model_json_schema()),
        ]

    # --- GESTIONE DELLA CHIAMATA AI TOOL ---
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            result_message = None

            # Gestione tool autenticazione
            if name == "start-authentication":
                # Controlla l'auth
                is_auth = await asyncio.to_thread(gmail_tool.is_authenticated)
                if is_auth:
                    result_message = "Utente già autenticato e verificato. Il tool è pronto per l'uso. Procedi con la richiesta dell'utente."
                else:
                    auth_url = await asyncio.to_thread(gmail_tool.start_authentication)
                    result_message = f"Utente non verificato. Per autorizzare, visita questo Link e copia l'URL di reindirizzamento: {auth_url}"

            elif name == "complete-authentication":
                args = CompleteAuthParams(**arguments)
                await asyncio.to_thread(gmail_tool.complete_authentication, args.code_url)
                result_message = "Autenticazione completata con successo! Il tool è pronto."

            elif name == "logout":
                result_message = await asyncio.to_thread(gmail_tool.logout)

            # Gestione tool Gmail
            elif name == "send-email":
                args = SendEmailParams(**arguments)
                attachment_payloads = [attachment.model_dump() for attachment in args.attachments] if args.attachments else None
                result_message = await asyncio.to_thread(
                    gmail_tool.send_email,
                    to=args.to,
                    subject=args.subject,
                    body=args.body,
                    body_type=args.body_type,
                    attachments=attachment_payloads,
                    attachment_paths=args.attachment_paths,
                )

            elif name == "search-emails":
                args = SearchEmailsParams(**arguments)
                result_message = await asyncio.to_thread(gmail_tool.search_emails, query=args.query, label=args.label, max_results=args.max_results)

            elif name == "get-email-details":
                args = EmailIdParams(**arguments)
                result_message = await asyncio.to_thread(gmail_tool.get_email_message_details, msg_id=args.msg_id)

            elif name == "get-email-body":
                args = EmailIdParams(**arguments)
                result_message = await asyncio.to_thread(gmail_tool.get_emails_message_body, msg_id=args.msg_id)

            elif name == "delete-email":
                args = EmailIdParams(**arguments)
                result_message = await asyncio.to_thread(gmail_tool.delete_email_message, msg_id=args.msg_id)

            else:
                raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Tool '{name}' non definito."))

            # Converte la risposta (che potrebbe essere un dict o altro) in una stringa per TextContent
            return [TextContent(type="text", text=str(result_message))]

        except Exception as e:
            # Cattura sia gli errori di validazione Pydantic che quelli della logica di business
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Errore durante l'esecuzione del tool '{name}': {e}"))

    return server


# --- FUNZIONE PRINCIPALE DEL SERVER (STDIO MODE) ---
async def serve():
    """
    Funzione principale che configura e avvia il server MCP per Gmail in modalità stdio.
    """
    server = create_gmail_server()

    # --- AVVIO DEL SERVER IN MODALITÀ STDIO ---
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
