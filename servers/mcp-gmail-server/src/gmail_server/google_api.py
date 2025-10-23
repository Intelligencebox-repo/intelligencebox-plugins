import os
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Definisce un'eccezione custom per errori di autenticazione
class AuthError(Exception):
    pass

class GoogleAuthManager:
    # Il token verrà salvato in una cartella '/data' che la Box renderà persistente
    TOKEN_PATH = '/data/token.json'

    def __init__(self, scopes: list):
        """
        Inizializza il gestore leggendo le credenziali dalle variabili d'ambiente.
        """
        self.scopes = scopes
        self.client_id = os.getenv("GMAIL_CLIENT_ID")
        self.client_secret = os.getenv("GMAIL_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise ValueError("Le variabili d'ambiente GMAIL_CLIENT_ID e GMAIL_CLIENT_SECRET sono obbligatorie.")

        # Ricostruisce il dizionario di configurazione del client al volo
        self.client_config = {
            "installed": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        
        self.service_cache = {} # Cache per gli oggetti 'service' già creati

    def start_authentication_flow(self) -> str:
        """
        Crea un'istanza del flusso di autenticazione e restituisce l'URL 
        per il consenso dell'utente.
        """
        flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
        #flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url

    def complete_authentication_flow(self, code: str) -> None:
        """
        Usa il codice di autorizzazione fornito dall'utente per ottenere il token 
        e salvarlo su disco in modo persistente.
        """
        flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
        #flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        flow.fetch_token(code=code)
        
        os.makedirs(os.path.dirname(self.TOKEN_PATH), exist_ok=True)
        
        with open(self.TOKEN_PATH, 'w') as token_file:
            token_file.write(flow.credentials.to_json())
        
        self.service_cache = {} # Svuota la cache per forzare la ri-creazione del servizio

    def get_service(self, api_name: str, api_version: str):
        """
        Restituisce un'istanza del servizio Google API valida e autenticata.
        Gestisce il caricamento, la validazione e il refresh del token.
        """
        cache_key = f"{api_name}:{api_version}"
        if cache_key in self.service_cache:
            return self.service_cache[cache_key]

        if not os.path.exists(self.TOKEN_PATH):
            raise AuthError("Token non trovato. L'utente deve completare il flusso di autenticazione.")

        creds = Credentials.from_authorized_user_file(self.TOKEN_PATH, self.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.TOKEN_PATH, 'w') as token_file:
                    token_file.write(creds.to_json())
            else:
                raise AuthError("Credenziali non valide o scadute. L'utente deve rieseguire l'autenticazione.")
        
        try:
            service = build(api_name, api_version, credentials=creds)
            self.service_cache[cache_key] = service # Mette in cache il servizio
            return service
        except Exception as e:
            raise Exception(f'Errore durante la creazione del servizio {api_name}: {e}')