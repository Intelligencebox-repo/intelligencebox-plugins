import os
import sys
import socket
import ssl
from typing import List, Dict, Optional
import urllib.parse
import requests


class DbTools:
    """
    Versione definitiva SENZA MOCK.
    Chiama sempre l'API .NET.
    Se manca API_ENDPOINT_URL o credenziali -> errore immediato.
    """

    def __init__(
        self,
        api_endpoint: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        ignore_ssl: bool = False,
    ) -> None:

        # Normalizziamo endpoint
        if api_endpoint:
            api_endpoint = api_endpoint.strip().rstrip("/")
        self.api_endpoint = api_endpoint

        self.client_id = client_id
        self.client_secret = client_secret
        # Se ignore_ssl==True -> disabilitiamo la verifica dei certificati
        self.verify = not bool(ignore_ssl)

        # Validazione iniziale delle variabili ambiente
        if not self.api_endpoint:
            raise RuntimeError("API_ENDPOINT_URL non configurato")

        if not self.client_id:
            raise RuntimeError("CLIENT_ID non configurato")

        if not self.client_secret:
            raise RuntimeError("CLIENT_SECRET non configurato")

    # =========================================================
    #  GET BILANCIO
    # =========================================================
    def get_bilancio(
        self,
        societa: str,
        esercizio: int,
        tipo: str,
        limit: Optional[int] = 100
    ) -> List[Dict]:

        url = f"{self.api_endpoint}/api/bilancio/get-bilancio"

        params = {
            "societa": societa,
            "esercizio": esercizio,
            "tipo": tipo,
            "limit": limit
        }

        headers = {
            "X-Client-ID": self.client_id,
            "X-Client-Secret": self.client_secret
        }

        # Log dettagliata della chiamata HTTP (stampa su stderr)
        try:
            print(f"[DbTools] HTTP verify SSL: {self.verify}", file=sys.stderr, flush=True)
            # Proviamo a recuperare il certificato SSL del server per debug.
            try:
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme and parsed.scheme.lower() == "https":
                    host = parsed.hostname
                    port = parsed.port or 443
                    server_hostname = host

                    # Creiamo un contesto non verificante per poter ottenere il cert
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    with socket.create_connection((host, port), timeout=5) as sock:
                        with ctx.wrap_socket(sock, server_hostname=server_hostname) as ssock:
                            cert = ssock.getpeercert()
                            # Estraiamo campi utili
                            subj = cert.get("subject", [])
                            issuer = cert.get("issuer", [])
                            not_before = cert.get("notBefore")
                            not_after = cert.get("notAfter")
                            san = cert.get("subjectAltName", [])
                            print(f"[DbTools] SSL cert for {host}:{port} subject={subj} issuer={issuer} notBefore={not_before} notAfter={not_after} SAN={san}", file=sys.stderr, flush=True)
                else:
                    print(f"[DbTools] URL scheme is not HTTPS (scheme={parsed.scheme}); no SSL certificate to fetch for {url}", file=sys.stderr, flush=True)
            except Exception as e:
                # In ogni caso vogliamo stampare l'errore ma non bloccare la chiamata
                print(f"[DbTools] Could not fetch SSL cert for {url}: {e}", file=sys.stderr, flush=True)

            masked_headers = {k: (v if k != "X-Client-Secret" else "***") for k, v in headers.items()}
            print(f"[DbTools] GET {url} params={params} headers={masked_headers}", file=sys.stderr, flush=True)

            resp = requests.get(url, params=params, headers=headers, timeout=30, verify=self.verify)

            # Log risultato parziale (status + prima parte del body)
            # Rimuoviamo caratteri non ASCII per evitare errori di codifica
            body_preview = ""
            if resp.text:
                try:
                    body_preview = resp.text[:500].replace("\n", " ").encode('ascii', errors='replace').decode('ascii')
                except Exception:
                    body_preview = f"<body with {len(resp.text)} chars, encoding issue>"
            print(f"[DbTools] Response status={resp.status_code} body_preview={body_preview}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[DbTools] Network error calling {url}: {e}", file=sys.stderr, flush=True)
            return [{"error": "Errore di rete", "details": str(e)}]

        if resp.status_code >= 400:
            return [{
                "error": "Errore API",
                "status": resp.status_code,
                "message": resp.text
            }]

        return resp.json()

    # =========================================================
    #  GET PIANO DEI CONTI
    # =========================================================
    def get_piano_dei_conti(self, societa: str, ricerca: str) -> List[Dict]:

        url = f"{self.api_endpoint}/api/bilancio/get-piano-conti"

        params = {"societa": societa, "ricerca": ricerca}

        headers = {
            "X-Client-ID": self.client_id,
            "X-Client-Secret": self.client_secret
        }

        # Log dettagliata della chiamata HTTP (stampa su stderr)
        try:
            print(f"[DbTools] HTTP verify SSL: {self.verify}", file=sys.stderr, flush=True)
            # Proviamo a recuperare il certificato SSL del server per debug.
            try:
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme and parsed.scheme.lower() == "https":
                    host = parsed.hostname
                    port = parsed.port or 443
                    server_hostname = host

                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    with socket.create_connection((host, port), timeout=5) as sock:
                        with ctx.wrap_socket(sock, server_hostname=server_hostname) as ssock:
                            cert = ssock.getpeercert()
                            subj = cert.get("subject", [])
                            issuer = cert.get("issuer", [])
                            not_before = cert.get("notBefore")
                            not_after = cert.get("notAfter")
                            san = cert.get("subjectAltName", [])
                            print(f"[DbTools] SSL cert for {host}:{port} subject={subj} issuer={issuer} notBefore={not_before} notAfter={not_after} SAN={san}", file=sys.stderr, flush=True)
                else:
                    print(f"[DbTools] URL scheme is not HTTPS (scheme={parsed.scheme}); no SSL certificate to fetch for {url}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[DbTools] Could not fetch SSL cert for {url}: {e}", file=sys.stderr, flush=True)

            masked_headers = {k: (v if k != "X-Client-Secret" else "***") for k, v in headers.items()}
            print(f"[DbTools] GET {url} params={params} headers={masked_headers}", file=sys.stderr, flush=True)

            resp = requests.get(url, params=params, headers=headers, timeout=30, verify=self.verify)

            body_preview = ""
            if resp.text:
                try:
                    body_preview = resp.text[:500].replace("\n", " ").encode('ascii', errors='replace').decode('ascii')
                except Exception:
                    body_preview = f"<body with {len(resp.text)} chars, encoding issue>"
            print(f"[DbTools] Response status={resp.status_code} body_preview={body_preview}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[DbTools] Network error calling {url}: {e}", file=sys.stderr, flush=True)
            return [{"error": "Errore di rete", "details": str(e)}]

        if resp.status_code >= 400:
            return [{
                "error": "Errore API",
                "status": resp.status_code,
                "message": resp.text
            }]

        return resp.json()

    # =========================================================
    #  GET REPORT DISPONIBILI
    # =========================================================
    def get_report_disponibili(self, societa: str, ricerca: str) -> List[Dict]:

        url = f"{self.api_endpoint}/api/bilancio/get-report-disponibili"

        params = {"societa": societa, "ricerca": ricerca}

        headers = {
            "X-Client-ID": self.client_id,
            "X-Client-Secret": self.client_secret
        }

        # Log dettagliata della chiamata HTTP (stampa su stderr)
        try:
            print(f"[DbTools] HTTP verify SSL: {self.verify}", file=sys.stderr, flush=True)
            # Proviamo a recuperare il certificato SSL del server per debug.
            try:
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme and parsed.scheme.lower() == "https":
                    host = parsed.hostname
                    port = parsed.port or 443
                    server_hostname = host

                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    with socket.create_connection((host, port), timeout=5) as sock:
                        with ctx.wrap_socket(sock, server_hostname=server_hostname) as ssock:
                            cert = ssock.getpeercert()
                            subj = cert.get("subject", [])
                            issuer = cert.get("issuer", [])
                            not_before = cert.get("notBefore")
                            not_after = cert.get("notAfter")
                            san = cert.get("subjectAltName", [])
                            print(f"[DbTools] SSL cert for {host}:{port} subject={subj} issuer={issuer} notBefore={not_before} notAfter={not_after} SAN={san}", file=sys.stderr, flush=True)
                else:
                    print(f"[DbTools] URL scheme is not HTTPS (scheme={parsed.scheme}); no SSL certificate to fetch for {url}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[DbTools] Could not fetch SSL cert for {url}: {e}", file=sys.stderr, flush=True)

            masked_headers = {k: (v if k != "X-Client-Secret" else "***") for k, v in headers.items()}
            print(f"[DbTools] GET {url} params={params} headers={masked_headers}", file=sys.stderr, flush=True)

            resp = requests.get(url, params=params, headers=headers, timeout=30, verify=self.verify)

            body_preview = ""
            if resp.text:
                try:
                    body_preview = resp.text[:500].replace("\n", " ").encode('ascii', errors='replace').decode('ascii')
                except Exception:
                    body_preview = f"<body with {len(resp.text)} chars, encoding issue>"
            print(f"[DbTools] Response status={resp.status_code} body_preview={body_preview}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[DbTools] Network error calling {url}: {e}", file=sys.stderr, flush=True)
            return [{"error": "Errore di rete", "details": str(e)}]

        if resp.status_code >= 400:
            return [{
                "error": "Errore API",
                "status": resp.status_code,
                "message": resp.text
            }]

        return resp.json()
