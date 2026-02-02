import os
import json
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from urllib.parse import urlparse, parse_qs

# Definisce un'eccezione custom per errori di autenticazione
class AuthError(Exception):
    pass

class GoogleAuthManager:
    # Il token verrà salvato in una cartella '/data' che la Box renderà persistente
    TOKEN_PATH = '/data/token.json'

    def __init__(self, scopes: list):
        """
        Inizializza il gestore leggendo le credenziali dalle variabili d'ambiente.
        Supporta due modalità:
        1. Modalità token esterno: usa GMAIL_ACCESS_TOKEN, GMAIL_REFRESH_TOKEN iniettati dal sistema
        2. Modalità locale: usa GMAIL_CLIENT_ID/SECRET per flusso OAuth locale
        """
        self.scopes = scopes
        self.client_id = os.getenv("GMAIL_CLIENT_ID")
        self.client_secret = os.getenv("GMAIL_CLIENT_SECRET")

        # Controlla se ci sono token esterni iniettati dal sistema
        self.external_access_token = os.getenv("GMAIL_ACCESS_TOKEN")
        self.external_refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
        self.external_token_expiry = os.getenv("GMAIL_TOKEN_EXPIRY")

        # Determina la modalità di funzionamento
        self._is_external_token_mode = bool(self.external_access_token)

        if self._is_external_token_mode:
            # In modalità esterna, client_id/secret sono comunque necessari per il refresh
            if not self.client_id or not self.client_secret:
                raise ValueError("GMAIL_CLIENT_ID e GMAIL_CLIENT_SECRET sono necessari anche in modalità token esterno per il refresh.")
        else:
            # In modalità locale, client_id/secret sono obbligatori
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
        self._external_creds = None  # Cache per credenziali esterne

    def is_authenticated(self) -> bool:
        """
        Controlla se l'utente è autenticato.
        In modalità token esterno, restituisce True se il token è presente.
        In modalità locale, controlla il file token.json.
        """
        # Modalità token esterno: considera autenticato se c'è un access token
        if self._is_external_token_mode:
            return True

        # Modalità locale: controlla il file token.json
        if not os.path.exists(self.TOKEN_PATH):
            return False  # File token non esiste

        try:
            creds = Credentials.from_authorized_user_file(self.TOKEN_PATH, self.scopes)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    return True  # È scaduto ma può essere rinfrescato, quindi è "autenticato"
                return False  # È invalido e non rinfrescabile
            return True  # È valido
        except Exception:
            return False  # File corrotto, illeggibile, o altri errori
        
    def get_auth_mode(self) -> str:
        """
        Restituisce la modalità di autenticazione corrente.
        'external' = token iniettati dal sistema (GMAIL_ACCESS_TOKEN)
        'local' = flusso OAuth locale con token.json
        """
        return 'external' if self._is_external_token_mode else 'local'

    def start_authentication_flow(self) -> str:
        """
        Crea un'istanza del flusso di autenticazione e restituisce l'URL
        per il consenso dell'utente.
        In modalità token esterno, restituisce un messaggio informativo.
        """
        if self._is_external_token_mode:
            return "ALREADY_AUTHENTICATED_VIA_SYSTEM"

        flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
        flow.redirect_uri = 'http://localhost'
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url

    def complete_authentication_flow(self, code_url: str) -> None:
        """
        Usa il codice di autorizzazione fornito dall'utente per ottenere il token 
        e salvarlo su disco in modo persistente.
        """
        try:
            parsed_url = urlparse(code_url)
            query_params = parse_qs(parsed_url.query)
            code = query_params.get('code', [None])[0]
            if not code:
                raise ValueError("Il parametro 'code' non è stato trovato nell'URL fornito.")
            
            flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
            flow.redirect_uri = 'http://localhost'
            flow.fetch_token(code=code)
            
            os.makedirs(os.path.dirname(self.TOKEN_PATH), exist_ok=True)
            
            with open(self.TOKEN_PATH, 'w') as token_file:
                token_file.write(flow.credentials.to_json())
            
            self.service_cache = {} # Svuota la cache per forzare la ri-creazione del servizio
        
        except ValueError as ve:
            raise AuthError(f"Errore durante l'estrazione del codice di autorizzazione: {ve}")
        except Exception as e:
            raise AuthError(f"Errore durante il completamento del flusso di autenticazione: {e}")

    def _get_external_credentials(self) -> Credentials:
        """
        Crea le credenziali dai token esterni iniettati via ambiente.
        Gestisce anche il refresh automatico se il token è scaduto.
        """
        if self._external_creds and self._external_creds.valid:
            return self._external_creds

        # Calcola l'expiry datetime se fornito
        expiry = None
        if self.external_token_expiry:
            try:
                expiry_ts = int(self.external_token_expiry)
                # Se è in millisecondi, converti in secondi
                if expiry_ts > 1e12:
                    expiry_ts = expiry_ts / 1000
                expiry = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
            except (ValueError, TypeError):
                pass

        creds = Credentials(
            token=self.external_access_token,
            refresh_token=self.external_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=expiry
        )

        # Se le credenziali sono scadute e c'è un refresh token, rinfresca
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Nota: in modalità container, non possiamo persistere il nuovo token
                # Il sistema esterno dovrà gestire il refresh a livello di database
            except Exception as e:
                raise AuthError(f"Errore durante il refresh del token esterno: {e}")

        self._external_creds = creds
        return creds

    def get_service(self, api_name: str, api_version: str):
        """
        Restituisce un'istanza del servizio Google API valida e autenticata.
        Gestisce il caricamento, la validazione e il refresh del token.
        Supporta sia token esterni (iniettati via ambiente) che token locali (file).
        """
        cache_key = f"{api_name}:{api_version}"
        if cache_key in self.service_cache:
            return self.service_cache[cache_key]

        # Modalità token esterno
        if self._is_external_token_mode:
            creds = self._get_external_credentials()
        else:
            # Modalità locale: usa il file token.json
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
        
    def logout(self) -> str:
        """
        Elimina il file token.json per disconnettere l'utente.
        Svuota anche la cache del servizio in memoria.
        """
        if os.path.exists(self.TOKEN_PATH):
            try:
                os.remove(self.TOKEN_PATH)
                self.service_cache = {}
                return "Logout completato. Il token di autenticazione è stato eliminato."
            except Exception as e:
                raise AuthError(f"Errore durante l'eliminazione del token: {e}")
        else:
            return "Nessun utente autenticato. Il token non esisteva già."