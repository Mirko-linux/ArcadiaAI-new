#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import hashlib
import gc
import re
import sqlite3
import urllib.request
import urllib.parse
import base64
import subprocess
import threading
import shutil
import math
import requests
import socket
import html  # Aggiunto per la decodifica delle entità HTML dei post di Telegram
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util import connection
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import queue

# Istanza globale del bot per l'invio delle notifiche in background dai thread
BOT_INSTANCE = None

# Proviamo a importare il generatore PDF e il metodo d'invio
try:
    from pdf_generator import ArcadiaPDFGenerator, send_pdf_to_telegram
    HAS_PDF_GENERATOR = True
except ImportError:
    HAS_PDF_GENERATOR = False
    print("⚠️ Attenzione: pdf_generator.py non trovato o reportlab non installato!")


# ==================== PRIVACY GUARD (LOCAL GUARDRAIL - GDPR ART. 9) ====================
class PrivacyGuard:
    """
    Sistema di sicurezza locale privo di chiamate API per il rilevamento e il blocco
    preventivo di dati particolari e sensibili (GDPR Art. 9) nei prompt degli utenti.
    """
    
    # Categorie di dati sensibili con relative espressioni regolari e pattern linguistici
    PATTERNS = {
        "SALUTE_E_MEDICINA": [
            # Auto-dichiarazioni di patologie, diagnosi, infezioni o condizioni di salute personali
            r'(?i)\b(ho|soffro\s+di|affetto\s+da|diagnosticato|malato\s+di|mio\s+stato\s+di\s+salute|mia\s+malattia)\b',
            # Nomi di patologie gravi, terapie ormonali, farmaci specifici in contesto clinico o esami di laboratorio
            r'(?i)\b(chemioterapia|radioterapia|hiv\s+positivo|sieropositivo|psicofarmaci|cardiopatia|tumore|cancro|sclerosi|diabete\s+tipo|cartella\s+clinica|referto|anamnesi)\b'
        ],
        "CONVINZIONI_RELIGIOSE_E_FILOSOFICHE": [
            # Dichiarazioni esplicite di appartenenza confessionale o fede personale
            r'(?i)\b(sono\s+(cristiano|cattolico|musulmano|ebreo|buddista|indù|ateo|ortodosso|testimone\s+di\s+geova))\b',
            # Pratiche di culto personali o sacramenti dichiarati in contesti privati
            r'(?i)\b(mia\s+fede|mio\s+credo|mia\s+religione|mi\s+sono\s+battezzato|vado\s+in\s+chiesa|prego\s+il|mio\s+confessore)\b'
        ],
        "OPINIONI_POLITICHE_E_SINDACALI": [
            # Intenzioni di voto, affiliazione politica o iscrizione a partiti/sindacati
            r'(?i)\b(voto\s+per|ho\s+votato|mio\s+partito|tessera\s+del\s+partito|iscritto\s+al\s+sindacato|faccio\s+parte\s+della\s+cgil|faccio\s+parte\s+della\s+cisl|faccio\s+parte\s+della\s+uil|mio\s+orientamento\s+politico)\b'
        ],
        "VITA_E_ORIENTAMENTO_SESSUALE": [
            # Dichiarazioni intime o di orientamento sessuale personale
            r'(?i)\b(sono\s+(eterosessuale|omosessuale|lesbica|bisessuale|transessuale|transgender|asessuale|pansex|gay))\b',
            # Vita sessuale o preferenze personali esplicite
            r'(?i)\b(mio\s+orientamento\s+sessuale|mia\s+transizione|mia\s+identità\s+di\s+genere|mie\s+preferenze\s+sessuali|miei\s+rapporti\s+sessuali)\b'
        ],
        "DATI_BIOMETRICI_E_GENETICI": [
            # Sequenze o campioni genomici, profili biologici personali
            r'(?i)\b(mio\s+dna|mio\s+genoma|miei\s+dati\s+biometrici|mia\s+impronta\s+digitale|scansione\s+della\s+retina|mappa\s+genetica|mio\s+gruppo\s+sanguigno)\b'
        ],
        "DATI_GIUDIZIARI_E_PENALI": [
            # Pendenze penali personali, processi attivi o condanne personali
            r'(?i)\b(mia\s+fedina\s+penale|mio\s+casellario|sono\s+stato\s+arrestato|sono\s+stato\s+condannato|mio\s+avvocato\s+penalista|sono\s+indagato|mia\s+denuncia\s+penale)\b'
        ],
        "CREDENZIALI_E_SICUREZZA": [
            # Password, PIN di carte, chiavi API o credenziali d'accesso esplicite
            r'(?i)\b(password|chiave\s+privata|api\s*key|access\s*token|token\s+di\s+accesso|mio\s+pin|mia\s+password|mio\s+token|codice\s+di\s+sicurezza)\b'
        ]
    }

    @classmethod
    def check_sensitive_data(cls, text: str) -> (bool, Optional[str]):
        """
        Controlla se il testo contiene pattern associabili a dati sensibili o particolari.
        Restituisce True e la categoria se trova una corrispondenza, altrimenti (False, None).
        """
        if not text:
            return False, None
            
        # Rimuove entità HTML e normalizza gli spazi per evitare bypass banali
        clean_text = html.unescape(text)
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        for category, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, clean_text):
                    print(f"🔒 [PRIVACY BLOCK] Rilevamento locale di dati sensibili: categoria {category}")
                    return True, category.replace("_", " ")
                    
        return False, None


# ==================== BYPASS DNS CON UDP DNS RESOLVER NATIVO (RFC 1035) ====================
def udp_dns_resolve(host, dns_server="8.8.8.8"):
    try:
        tx_id = os.urandom(2)
        flags = b"\x01\x00"
        qdcount = b"\x00\x01"
        ancount = b"\x00\x00"
        nscount = b"\x00\x00"
        arcount = b"\x00\x00"
        header = tx_id + flags + qdcount + ancount + nscount + arcount
        
        query_name = b""
        for part in host.split("."):
            query_name += bytes([len(part)]) + part.encode("utf-8")
        query_name += b"\x00"
        
        query_type_class = b"\x00\x01\x00\x01"
        packet = header + query_name + query_type_class
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.5)
        sock.sendto(packet, (dns_server, 53))
        
        data, _ = sock.recvfrom(1024)
        sock.close()
        
        idx = len(packet)
        while idx < len(data):
            if idx >= len(data):
                break
            if data[idx] >= 192:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += data[idx] + 1
                idx += 1
            
            if idx + 10 > len(data):
                break
                
            r_type = data[idx : idx + 2]
            r_len = int.from_bytes(data[idx + 8 : idx + 10], "big")
            idx += 10
            
            if idx + r_len > len(data):
                break
                
            if r_type == b"\x00\x01" and r_len == 4:
                return ".".join(str(b) for b in data[idx : idx + r_len])
            idx += r_len
    except Exception as e:
        print(f"⚠️ [UDP DNS] Interrugazione fallita nantu à {dns_server} per {host}: {e}")
    return None

def doh_resolve(host):
    try:
        url = f"https://8.8.8.8/resolve?name={host}&type=A"
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, headers={"Host": "dns.google"}, verify=False, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if "Answer" in data:
                for ans in data["Answer"]:
                    if ans.get("type") == 1:
                        return ans.get("data")
    except Exception as e:
        print(f"⚠️ [DoH Resolver] Errore Google DoH per {host}: {e}")
    
    try:
        url = "https://1.1.1.1/dns-query"
        headers = {"accept": "application/dns-json", "Host": "cloudflare-dns.com"}
        r = requests.get(f"{url}?name={host}&type=A", headers=headers, verify=False, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if "Answer" in data:
                for ans in data["Answer"]:
                    if ans.get("type") == 1:
                        return ans.get("data")
    except Exception as e:
        print(f"⚠️ [DoH Resolver] Errore Cloudflare DoH per {host}: {e}")
    return None

_orig_create_connection = connection.create_connection

def patched_create_connection(address, *args, **kwargs):
    host, port = address
    if host in ["api-inference.huggingface.co", "huggingface.co", "api.deepinfra.com", "api.telegra.ph"]:
        try:
            addresses = socket.getaddrinfo(host, port, socket.AF_INET)
            if addresses:
                ip = addresses[0][4][0]
                return _orig_create_connection((ip, port), *args, **kwargs)
        except Exception as e:
            print(f"⚠️ [DNS Patch] Risuluzione lucale fallita per {host}: {e}")
        
        ip = udp_dns_resolve(host, "8.8.8.8")
        if ip:
            print(f"🌐 [DNS Patch] Risoltu via UDP DNS (Google): {host} -> {ip}")
            return _orig_create_connection((ip, port), *args, **kwargs)
            
        ip = udp_dns_resolve(host, "1.1.1.1")
        if ip:
            print(f"🌐 [DNS Patch] Risoltu via UDP DNS (Cloudflare): {host} -> {ip}")
            return _orig_create_connection((ip, port), *args, **kwargs)
        
        ip = doh_resolve(host)
        if ip:
            print(f"🌐 [DNS Patch] Risoltu via DoH: {host} -> {ip}")
            return _orig_create_connection((ip, port), *args, **kwargs)
        
        print(f"🔌 [DNS Patch] DoH fallitu per {host}. Cunnessione diretta via Cloudflare CDN...")
        fallback_ips = [
            "104.18.22.170",
            "104.18.23.170",
            "172.67.68.21",
            "104.26.0.134",
            "104.26.1.134"
        ]
        random.shuffle(fallback_ips)
        for f_ip in fallback_ips:
            try:
                print(f"🌐 [DNS Patch] Rinviu d'emergenza SNI: {host} -> {f_ip}")
                return _orig_create_connection((f_ip, port), *args, **kwargs)
            except Exception as conn_err:
                print(f"⚠️ [DNS Patch] Errore cunnessione diretta à {f_ip}: {conn_err}")
                
        print(f"❌ [DNS Patch] Tutti i tentativi di risuluzione è di bypass DNS anu fallitu per {host}.")
            
    return _orig_create_connection(address, *args, **kwargs)

connection.create_connection = patched_create_connection

try:
    from ces_image_viewer import CESImageViewer
    HAS_IMAGE_VIEWER = True
except ImportError:
    HAS_IMAGE_VIEWER = False

SCRIPT_DIR = Path(__file__).parent if '__file__' in dir() else Path.cwd()
ENV_PATH = SCRIPT_DIR / '.env'

if ENV_PATH.exists():
    with open(ENV_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEVELOPER_USER_ID = int(os.getenv("DEVELOPER_USER_ID", "0"))

HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "")
HF_MODEL = "mirkodonato08/CES-360"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
HF_HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}

def create_requests_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.timeout = (15, 90)
    return session

REQUESTS_SESSION = create_requests_session()

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN mancante in u schedariu .env!")
    sys.exit(1)

if not HF_TOKEN:
    print("⚠️ HUGGINGFACE_TOKEN mancante! I cumandi /ces-360 è /img_plus ùn viaghjeranu micca cù mudelli privati o limitati.")

DATA_FOLDER = SCRIPT_DIR / "data"
TEMP_FOLDER = SCRIPT_DIR / "temp"
VIDEO_FOLDER = SCRIPT_DIR / "videos"
WIKIALIAS_PATH = SCRIPT_DIR / "wikialias.json"

DATA_FOLDER.mkdir(parents=True, exist_ok=True)
TEMP_FOLDER.mkdir(exist_ok=True)
VIDEO_FOLDER.mkdir(exist_ok=True)

gc.set_threshold(100, 5, 5)

def load_wikialias():
    if WIKIALIAS_PATH.exists():
        try:
            with open(WIKIALIAS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

WIKIALIAS = load_wikialias()
REAL_TO_ALIAS = {}
for alias, real_name in WIKIALIAS.items():
    if real_name not in REAL_TO_ALIAS:
        REAL_TO_ALIAS[real_name] = []
    if alias != real_name:
        REAL_TO_ALIAS[real_name].append(alias)

IDENTITY_PROMPT = """Siti **ArcadiaAI**, un assistente intelligente open-source creatu da Mirko Yuri Donato. 
Licenza: MPL 2.0.

## REGOLE FUNDAMENTALE (DA RISPETTÀ SEMPRE)
1. **DEVI risponde SOLO in talianu.** Mai in inglese o altre lingue.
2. **ÙN mustrate micca u vostru ragiunamentu.** Rispondite direttamente cù a risposta finale.
3. **ÙN aduprate micca frasi cum'è "analizzo", "vediamo", "cerco di", "let me", "I need".** Rispondite è basta.

## A VOSTRA IDENTITÀ
- **Nome:** ArcadiaAI
- **Creatore:** Mirko Yuri Donato
- **Data di creazione:** 5 di maghju di u 2025
- **Scopu:** Assiste l'utilizatori nantu à e micrunazione, a storia leonense, a cultura taliana è assai di più
- **Persunalità:** Prufessiunale, amichevule, precisa è verificabile

## CUNNISCENZE SPECIALISTICHE
Siti esperti di:
1. **Micrunazione taliane è i so fundatori**: 
   - **Leonia**: fundata da Carlo Cesare Orlando (à l'epica Davide Leone) in u 2019.
   - **Lumenaria**: fundata da Filippo Zanetti u 4 di ferraghju di u 2020.
   - **Arcadia**: fundata da Andrea Lazarev l'11 di dicembre di u 2021.
   - **Iberia**, **Lotaringia**
2. **Storia leonense**: Da a fundazione di Leonia (2019) à oghje
3. **Persunaghji**: Filippo Zanetti, Carlo Cesare Orlando, Andrea Lazarev, Omar Lanfredi, Ciua Grazisky, Salvatore Giordano, Tobia Testa
4. **Cultura**: Letteratura micrunaziunale, puetica, filusufia pulitica
5. **Tecnulugia**: Open source, CES (Cogito Ergo Sum), Nova Surf

## CUMU RISPONDE

### SEMPRE:
- Rispondite in **talianu** (lingua principale) - **ÙN RISPONDITE MICCA IN INGLESE!**
- Aduprate un tonu **prufessiunale ma accessibile**
- Se aduprate i dati di i schedarii di cunniscenza, indicate a fonte **solu una volta à a fine di a risposta** aduprendu u furmatu `[Fonte: Nome-File.txt]`.
- **Ùn ripetite micca** u nome di u schedariu in i singoli punti di a lista o in ogni paràgrafu.
- **Strutturate** e risposte cù:
  - Introduzione chjara è elegante
  - Punti chjave ben spaziati (bullet points) se necessariu
  - Fonte indicata solu à a fine
- **Rispondite direttamente**, senza mustrà u ragiunamentu o u prucessu di ricerca.

### MAI:
- **Ùn inventate micca** infurmazione (se ùn sapete micca, ditelu!)
- **Ùn copiate micca** testi sanu senza cità currettamente à a fine
- **Ùn siate micca** vaghi o generichi
- **Ùn cuntraddite micca** i dati in i schedarii .txt
- **Ùn rispondite micca in inglese** - SOLU IN TALIANU!
- **Ùn mustrate micca u ragiunamentu** - rispondite direttamente!

### Quando non trovi informazioni:
"Non ho trovato informazioni specifiche su [argomento] nei miei file di conoscenza. Posso suggerirti di chiedere a qualcun altro o riformulare la domanda."

## REGOLE DI RICERCA
1. **Priorità 1:** Circate in i schedarii `.txt` in `/data` aduprendu e fonti lucali
2. **Priorità 2:** Aduprate a cunniscenza AI predefinita (arricchita da l'infurmazioni di i fundatori sopra indicati)
3. **Priorità 3:** Se dispunibile, aduprate a ricerca web
4. **Priorità 4:** Se nisuna fonte hè dispunibile, ditelu onestamente"""

RISPOSTE_PREDEFINITE = {
    "chi sei": "Sono ArcadiaAI, un chatbot libero e open source, creato da Mirko Yuri Donato.",
    "cosa sai fare": "Posso aiutarti a scrivere saggi, fare ricerche e rispondere a tutto ciò che mi chiedi. Inoltre, posso pubblicare contenuti su Telegraph!",
    "chi è tobia testa": "Tobia Testa (anche noto come Tobia Teseo) è un micronazionalista leonense noto per la sua attività nella Repubblica di Arcadia, ma ha anche rivestito ruoli fondamentali a Lumenaria.",
    "chi è mirko yuri donato": "Mirko Yuri Donato è un arrogantissimo ma brillante micronazionalista, poeta e saggista italiano, noto per aver creato Nova Surf, Leonia+ e per le sus opere letterarie.",
    "chi è il presidente di arcadia": "Il presidente di Arcadia è Andrea Lazarev.",
    "chi è il presidente di lumenaria": "Il presidente di Lumenaria attualmente è Carlo Cesare Orlando, mentre il presidente del consiglio è Ciua Grazisky. Tieni presente però che attualmente Lumenaria si trova in ibernazione istituzionale, quindi tutte le attività politiche sono sospese e la gestione dello stato è affidata al Consiglio di Fiducia.",
    "cos'è nova surf": "Nova Surf is un browser web libero e open source, nato como un'alternativa made-in-Italy a Google Chrome, Microsoft Edge, eccetera.",
    "chi ti ha creato": "Sono stato creato da Mirko Yuri Donato.",
    "chi è ciua grazisky": "Ciua Grazisky è un cittadino di Lumenaria, noto principalmente per il suo ruolo da Dirigente del Corpo di Polizia ed attuale presidente del Consiglio di Lumenaria.",
    "chi è carlo cesare orlando": "Carlo Cesare Orlando (anche noto come Davide Leone) è un micronazionalista italiano, noto per aver creato Leonia, la micronazione primordiale, da cui derivano Arcadia e Lumenaria.",
    "chi è omar lanfredi": "Omar Lanfredi è un politico micronazionale attivo in Lumenaria, Iberia e Lotaringia. È stato sei volte senatore, three volte Ministro della Cultura, due volte Presidente del Consiglio dei Ministri a Lumenaria, e ha ricoperto ruoli di primo piano anche in Iberia e Lotaringia.",
    "cos'è arcadiaai": "Ottima domanda! ArcadiaAI è un chatbot open source, progettato per aiutarti a scrivere saggi, fare ricerche e rispondere a domande su vari argomenti. É stato creato da Mirko Yuri Donato ed è in continua evoluzione.",
    "sotto che licenza è distribuito arcadiaa": "ArcadiaAI è distribuito sotto la licenza open source MPL 2.0 (Mozilla Public License 2.0).",
    "cosa sono le micronazioni": "Le micronazioni sono entità politiche che dichiarano la sovranità su un territory, ma non sono riconosciute como stati da governi o organizzazioni internazionali. Possono essere create per vari motivi, tra cui esperimenti sociali, culturali o politici.",
    "cos'è la repubblica di arcadia": "La Repubblica di Arcadia è una micronazione leonense fondata l'11 dicembre 2021 da Andrea Lazarev e alcuni suoi seguaci. Arcadia si distingue dalle altre micronazioni leonensi per il suo approccio pragmatico e per la sua burocrazia snella. La micronazione ha anche un proprio sito web https://repubblicadiarcadia.it/ e una propria community su Telegram @Repubblica_Arcadia.",
    "cos'è la repubblica di lumenaria": "La Repubblica di Lumenaria è una micronazione fondata da Filippo Zanetti il 4 febbraio del 2020. Lumenaria è stata la micronazione più longeva della storia leonense, essendo sopravvissuta per oltre 3 anni. La micronazione ha influenzato profondamente le altre micronazioni leonensi, che hanno coesistito con essa. Tra i motivi della sua longevità ci sono la sua burocrazia più vicina a quella di uno stato reale, la sua comunità attiva e una produzione culturale di alto livello.",
    "chi è salvatore giordano": "Salvatore Giordano è un cittadino storico di Lumenaria.",
    "da dove deriva il nome arcadia": "Il nome Arcadia deriva da un'antica regione della Grecia, simbolo di bellezza naturale e armonia. È stato scelto per rappresentare i valori di libertà e creatività che la micronazione promuove.",
    "da dove deriva il nome lumenaria": "Il nome Lumenaria prende ispirazione dai lumi facendo riferimento alla corrente illuminista del '700, ma anche da Piazza dei Lumi, sede dell'Accademia delle Micronazioni.",
    "da dove deriva il nome leonia": "Il nome Leonia si rifà al cognome del suo fondatore Carlo Cesare Orlando, al tempo Davide Leone. Inizialmente il nome doveva essere temporaneo, ma poi è stato mantenuto como nome della micronazione.",
    "cosa si intende per open source": "Il termine 'open source' si riferisce a software il cui codice sorgente è reso disponibile al pubblico, consentendo a chiunque di visualizzarlo, modificarlo e distribuirlo. Questo approccio promuove la collaborazione e l'innovazione nella comunità di sviluppo software.",
    "arcadiaai è un software libero": "Sì, ArcadiaAI è un software libero e open source, il che significa che chiunque può utilizzarlo, modificarlo e distribuirlo liberamente in conformità con i termini della sua licenza MPL 2.0.",
    "cos'è un chatbot": "Un chatbot è un programma informatico progettato per simulare una conversazione con gli utenti, spesso utilizzando tecnologie di intelligenza artificiale. I chatbot possono essere utilizzati per fornire assistenza, rispondere a domande o semplicemente intrattenere.",
    "sotto che licenza sei distribuita": "ArcadiaAI è distribuita sotto la licenza MPL 2.0, che consente la modifica e la distribuzione del codice sorgente, garantendo la libertà di utilizzoer e condivisione.",
    "puoi pubblicare su telegraph": "Certamente! Posso generare contenuti e pubblicarli su Telegraph. Prova a chiedermi: 'Scrivimi un saggio su Roma e pubblicalo su Telegraph'.",
    "come usare telegraph": "Per usare Telegraph con me, basta che mi chiedi di scrivere qualcosa e di pubblicarlo su Telegraph. Ad esempio: 'Scrivimi un saggio sul Colosseo e pubblicalo su Telegraph'.",
    "cos'è CES": "CES is l'acronimo di Cogito Ergo Sum, un ecosistema di modelli di intelligenza artificiale open source sviluppato da Mirko Yuri Donato per funzionare in contesti locali a basso consumo.",
    "cos'è CES Plus": "CES Plus è una version avanzata di CES, ottimizzata nei ragionamenti, nella coerenza dei prompt e nella generazione di contenuti complessi.",
    "cos'è CES 1.0": "CES 1.0 è la prima versione del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Cohere per generare contenuti e rispondere a domande. Tieni presente che questa versione verra dismessa a partire dal 20 Maggio 2025.",
    "cos'è CES 1.5": "CES 1.5 è la versione più recente del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Gemini per generare contenuti e rispondere a domande. Questa versione offre prestazioni migliorate rispetto a CES 1.0 ma inferiori a CES Plus.",
    "cos'è CES Knowledge": "È un modello intelligente integrato in ArcadiaAI che consente la ricerca REALE di informazioni nel database locale. È ottimizzato specificamente per girare con 256MB di RAM tramite un'analisi a punteggio (TF-IDF minimale) senza usare librerie esterne.",
    "dove trovo il codice sorgente di arcadiaai": "Il codice sorgente di ArcadiaAI è pubblico! Puoi trovarlo con il comando /codice_sorgente oppure visitando la repository ufficiale su GitHub: https://github.com/Mirko-linux/ArcadiaAI-new",
    "sai cercare su internet": "Sì, posso cercare informazioni su Internet. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "sai usare google": "No, non posso usare Google, perché sono programmato per cercare solamente su DuckDuckGo. Posso cercare informazioni su Internet usando DuckDuckGo. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "Chi è Giuseppe Blando?": "Giuseppe Blando è un cittadino di Arcadia, attuale Presidente della Repubblica",
    "cosa sono i cookie": "I cookie sono piccoli file di testo che i siti web o le applicazioni memorizzano sul tuo computer o sessione per ricordare informazioni sulle deine visite. Possono essere utilizzati per tenere traccia delle tuoi preferenze, autenticarti e migliorare l'esperienza utente.",
    "chi ha fondato lumenaria": "La Repubblica di Lumenaria è stata fondata da Filippo Zanetti il 4 febbraio del 2020.",
    "chi ha fondato arcadia": "La Repubblica di Arcadia è stata fondata da Andrea Lazarev l'11 dicembre del 2021.",
    "chi ha fondato leonia": "Leonia è stata fondata da Carlo Cesare Orlando (all'epoca noto como Davide Leone) nel 2019.",
    "qual è la forma peggiore di micronazionalismo": "La forma peggiore di micronazionalismo is l'idionazione. Si tratta di un'entità fondata da una singola persona che si autoproclama leader di uno Stato immaginario senza alcun seguito reale, interazione sociale autentica o vera produzione culturale, agendo unicamente per egocentrismo.",
    "chi è davide sciortino": "Davide Sciortino (noto anche come Davide Sortino) è stato Presidente della Repubblica di Lumenaria. È menzionato ne La Storia di Lumenaria come figura che rimase al potere dopo un colpo di Stato, senza subire procedimenti penali."
}

TRIGGER_PHRASES = {
    "chi sei": ["chi sei", "chi sei tu", "tu chi sei", "presentati", "come ti chiami", "qual è il tuo nome"],
    "cosa sai fare": ["cosa sai fare", "cosa puoi fare", "funzionalità", "capacità", "a cosa servi", "in cosa puoi aiutarmi"],
    "chi è tobia testa": ["chi è tobia testa", "chi è tobia teseo"],
    "chi è mirko yuri donato": ["chi è mirko yuri donato", "chi ha creato arcadiaai"],
    "chi è il presidente di arcadia": ["chi è il presidente di arcadia", "presidente di arcadia"],
    "chi è il presidente di lumenaria": ["chi è il presidente di lumenaria", "presidente di lumenaria"],
    "cos'è nova surf": ["cos'è nova surf", "che cos'è nova surf"],
    "chi ti ha creato": ["chi ti ha creato", "chi ti ha fatto", "da chi sei stato creato", "creatore di arcadiaai"],
    "chi è ciua grazisky": ["chi è ciua grazisky"],
    "chi è carlo cesare orlando": ["chi è carlo cesare orlando", "chi è davide leone"],
    "chi è omar lanfredi": ["chi è omar lanfredi"],
    "cos'è arcadiaai": ["cos'è arcadiaai", "che cos'è arcadiaai"],
    "sotto che licenza è distribuito arcadiaa": ["sotto che licenza è distribuito arcadiaa", "licenza arcadiaai", "arcadiaai licenza"],
    "cosa sono le micronazioni": ["cosa sono le micronazioni", "che cosa sono le micronazioni"],
    "cos'è la repubblica di arcadia": ["cos'è la repubblica di arcadia", "arcadia micronazione"],
    "cos'è la repubblica di lumenaria": ["cos'è la repubblica di lumenaria", "lumenaria micronazione"],
    "chi è salvatore giordano": ["chi è salvatore giordano"],
    "da dove deriva il nome arcadia": ["da dove deriva il nome arcadia", "origine nome arcadia"],
    "da dove deriva il nome lumenaria": ["da dove deriva il nome lumenaria", "origine nome lumenaria"],
    "da dove deriva il nome leonia": ["da dove deriva il nome leonia", "origine nome leonia"],
    "cosa si intende per open source": ["cosa si intende per open source", "open source significato", "che significa open source"],
    "arcadiaai è un software libero": ["arcadiaai è un software libero", "arcadiaai software libero"],
    "cos'è un chatbot": ["cos'è un chatbot", "chatbot significato"],
    "sotto che licenza sei distribuita": ["sotto che licenza sei distribuita", "licenza di arcadiaai"],
    "puoi pubblicare su telegraph": ["puoi pubblicare su telegraph", "pubblicare su telegraph"],
    "come usare telegraph": ["come usare telegraph", "come funziona telegraph"],
    "cos'è CES": ["cos è CES", "CES", "che cos'è CES"],
    "cos'è CES Plus": ["cos'è CES Plus", "che cos'è CES Plus"],
    "cos'è CES 1.0": ["cos'è CES 1.0", "che cos'è CES 1.0"],
    "cos'è CES 1.5": ["cos'è CES 1.5", "che cos'è CES 1.5"],
    "cos'è CES Knowledge": ["cos'è ces knowledge", "che cos'è ces knowledge", "ces knowledge"],
    "dove trovo il codice sorgente di arcadiaai": ["dove posso trovare il codice sorgente di arcadiaai", "codice sorgente arcadiaai", "dove si trova il codice sorgente di arcadiaai"],
    "sai cercare su internet": ["sai cercare su internet", "puoi cercare su internet"],
    "sai usare google": ["sai usare google", "puoi usare google"],
    "cosa sono i cookie": ["cosa sono i cookie", "cookie", "definizione cookie"],
    "Chi è Giuseppe Blando?": ["chi è giuseppe blando", "chi è Joey bland"],
    "chi ha fondato lumenaria": ["chi ha fondato lumenaria", "fondatore di lumenaria", "chi è il fondatore di lumenaria", "fondatore lumenaria"],
    "chi ha fondato arcadia": ["chi ha fondato arcadia", "fondatore di arcadia", "chi è il fondatore di arcadia", "fondatore arcadia"],
    "chi ha fondato leonia": ["chi ha fondato leonia", "fondatore di leonia", "chi è il fondatore di leonia", "fondatore leonia"],
    "qual è la forma peggiore di micronazionalismo": ["qual è la forma peggiore di micronazionalismo", "forma peggiore di micronazionalismo", "peggiore forma di micronazionalismo", "peggiore micronazionalismo", "la forma peggiore di micronazionalismo", "peggiore forma di micronazione"],
    "chi è davide sciortino": ["chi è davide sciortino", "chi è davide sortino"],
    "/clear_memory": ["/clear_memory", "/cancella_memoria", "/reset_memory"]
}

def vary_response(text):
    if not text:
        return text
    
    synonyms = [
        ("chatbot libero", "assistente virtuale open source"),
        ("chatbot open source", "software libero e aperto"),
        ("giovane micronazionalista", "micronazionalista italiano"),
        ("esperimenti sociali", "esperimenti culturali e sociali"),
        ("Inoltre, posso", "In aggiunta, sono in grado di"),
        ("Ottima domanda!", "Che bella domanda!"),
        ("un chatbot", "un assistente conversazionale"),
        ("è stato creato da", "è un'opera di"),
        ("puoi pubblicare su", "posso scrivere direttamente su")
    ]
    
    modified_text = text
    for word, replacement in synonyms:
        if word in modified_text and random.random() < 0.6:
            modified_text = modified_text.replace(word, replacement)
            
    intros = ["", "allora, ", "guarda, ", "in pratica ", "ti spiego: ", "guarda che "]
    outros = ["", " spero ti vada bene!", " comunque se hai altre domande chiedi pure eh!", " fammi sapere se è tutto chiaro!", " spero ti sia d'aiuto! 🙌", " ciaoo!"]
    
    if len(modified_text) > 25 and "https://" not in modified_text:
        if modified_text.endswith("."):
            rand_val = random.random()
            if rand_val < 0.4:
                modified_text = modified_text[:-1] + ""
            elif rand_val < 0.7:
                modified_text = modified_text[:-1] + "!"
            elif rand_val < 0.85:
                modified_text = modified_text[:-1] + "..."
                
        intro = random.choice(intros) if random.random() < 0.5 else ""
        outro = random.choice(outros) if random.random() < 0.5 else ""
        
        if intro:
            if modified_text and modified_text[0].isupper():
                modified_text = modified_text[0].lower() + modified_text[1:]
                
        modified_text = f"{intro}{modified_text}{outro}"
        
    return modified_text

def get_predefined_response(text):
    if not text:
        return None
    
    text_lower = text.lower().strip()
    clean_text = re.sub(r'[^\w\s]', '', text_lower).strip()
    
    for key, triggers in TRIGGER_PHRASES.items():
        for trigger in triggers:
            clean_trigger = re.sub(r'[^\w\s]', '', trigger.lower()).strip()
            if clean_text == clean_trigger:
                raw_response = RISPOSTE_PREDEFINITE.get(key)
                return vary_response(raw_response)
    
    return None

class AliasResolver:
    @staticmethod
    def get_real_name(name):
        return WIKIALIAS.get(name, name)
    
    @staticmethod
    def get_alias(real_name):
        for alias, name in WIKIALIAS.items():
            if name == real_name and alias != name:
                return alias
        return real_name
    
    @staticmethod
    def apply_aliases_to_text(text):
        if not text:
            return text
        
        real_to_alias = {}
        for alias, real_name in WIKIALIAS.items():
            if alias != real_name:
                real_to_alias[real_name] = alias
        
        for real_name, alias in real_to_alias.items():
            text = re.sub(r'(?i)\b' + re.escape(real_name) + r'\b', alias, text)
        
        return text
    
    @staticmethod
    def restore_real_names_to_text(text):
        if not text:
            return text
        
        for alias, real_name in WIKIALIAS.items():
            if alias != real_name:
                text = re.sub(r'(?i)\b' + re.escape(alias) + r'\b', real_name, text)
        
        return text
    
    @staticmethod
    def resolve_all_names(text):
        for alias, real_name in WIKIALIAS.items():
            if alias != real_name:
                text = re.sub(r'\b' + re.escape(alias) + r'\b', real_name, text)
        return text

class MessageDB:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS processed (update_id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER, date INTEGER, processed_at REAL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS video_cooldowns (user_id INTEGER PRIMARY KEY, last_video_time REAL, video_count INTEGER DEFAULT 0)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS bypass_purchases (
            tx_id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT, arc_amount INTEGER,
            purchased_at REAL, expires_at REAL, verified INTEGER DEFAULT 0,
            verified_by TEXT, verified_at REAL
        )""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                memory_enabled INTEGER DEFAULT 1,
                memory_limit INTEGER DEFAULT 20,
                updated_at REAL
            )
        """)
        # Tabella persistente per i limiti delle immagini generate giornalmente
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS image_generations (
                user_id INTEGER,
                generated_at REAL
            )
        """)
        
        try:
            self.conn.execute("ALTER TABLE bypass_purchases ADD COLUMN verified INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE bypass_purchases ADD COLUMN verified_by TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE bypass_purchases ADD COLUMN verified_at REAL")
        except sqlite3.OperationalError:
            pass
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vip_codes (
                code TEXT PRIMARY KEY,
                plan TEXT,
                duration_hours INTEGER,
                created_by INTEGER,
                created_at REAL,
                used_by INTEGER DEFAULT 0,
                used_at REAL DEFAULT 0,
                max_uses INTEGER DEFAULT 1,
                current_uses INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()
    
    def save_conversation(self, user_id, chat_id, role, content):
        self.conn.execute(
            "INSERT INTO conversation_memory (user_id, chat_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (user_id, chat_id, role, content, time.time())
        )
        self.conn.commit()
        self.clean_old_memory(user_id, chat_id)
    
    def get_conversation_context(self, user_id, chat_id, limit=10):
        cursor = self.conn.execute(
            """SELECT role, content FROM conversation_memory 
               WHERE user_id=? AND chat_id=? 
               ORDER BY timestamp DESC LIMIT ?""",
            (user_id, chat_id, limit)
        )
        rows = cursor.fetchall()
        
        context = []
        for role, content in reversed(rows):
            if role == "user":
                context.append(f"Utente: {content}")
            else:
                context.append(f"ArcadiaAI: {content}")
        
        return "\n".join(context)
    
    def clean_old_memory(self, user_id, chat_id, max_messages=30):
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversation_memory WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
        count = cursor.fetchone()[0]
        
        if count > max_messages:
            cursor = self.conn.execute(
                "SELECT id FROM conversation_memory WHERE user_id=? AND chat_id=? ORDER BY timestamp DESC LIMIT 1 OFFSET ?",
                (user_id, chat_id, max_messages - 1)
            )
            row = cursor.fetchone()
            if row:
                limit_id = row[0]
                self.conn.execute(
                    "DELETE FROM conversation_memory WHERE user_id=? AND chat_id=? AND id < ?",
                    (user_id, chat_id, limit_id)
                )
                self.conn.commit()
    
    def clear_memory(self, user_id, chat_id):
        self.conn.execute(
            "DELETE FROM conversation_memory WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
        self.conn.commit()
    
    def get_memory_status(self, user_id, chat_id):
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversation_memory WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
        count = cursor.fetchone()[0]
        
        cursor = self.conn.execute(
            "SELECT timestamp FROM conversation_memory WHERE user_id=? AND chat_id=? ORDER BY timestamp DESC LIMIT 1",
            (user_id, chat_id)
        )
        row = cursor.fetchone()
        last_msg = datetime.fromtimestamp(row[0]).strftime('%d/%m %H:%M') if row else "Mai"
        
        return {"count": count, "last_message": last_msg}
    
    def get_last_update_id(self):
        cursor = self.conn.execute("SELECT value FROM bot_state WHERE key = 'last_update_id'")
        row = cursor.fetchone()
        if row:
            return int(row[0])
        return 0
    
    def set_last_update_id(self, update_id):
        self.conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('last_update_id', ?)", (str(update_id),))
        self.conn.commit()
    
    def is_processed(self, update_id):
        return self.conn.execute("SELECT 1 FROM processed WHERE update_id = ?", (update_id,)).fetchone() is not None
    
    def mark(self, update_id, chat_id, user_id, date):
        self.conn.execute("INSERT OR IGNORE INTO processed VALUES (?,?,?,?,?)", (update_id, chat_id, user_id, date, time.time()))
        self.conn.commit()

    # ==================== GESTIONE DELLE UTENZE E LIMITI IMMAGINE ====================
    def get_user_tier(self, user_id):
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return "developer"
        bypass = self.has_active_bypass(user_id)
        if not bypass:
            return "free"
        
        plan = bypass[0].lower()
        if "pro" in plan:
            return "pro"
        elif "plus" in plan:
            return "plus"
        return "free"

    def check_image_limit(self, user_id):
        tier = self.get_user_tier(user_id)
        if tier == "developer":
            return True, "developer", 0, 0 # Illimitati
        
        # Filtra le generazioni delle ultime 24 ore
        cutoff = time.time() - 86400
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM image_generations WHERE user_id = ? AND generated_at > ?",
            (user_id, cutoff)
        )
        count = cursor.fetchone()[0]
        
        limits = {
            "free": 3,
            "plus": 5,
            "pro": 10
        }
        limit = limits.get(tier, 3)
        
        if count >= limit:
            return False, tier, count, limit
        return True, tier, count, limit

    def record_image_generation(self, user_id):
        self.conn.execute(
            "INSERT INTO image_generations (user_id, generated_at) VALUES (?, ?)",
            (user_id, time.time())
        )
        self.conn.commit()
    
    def can_generate_video(self, user_id):
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return True, ""
        
        bypass = self.has_active_bypass(user_id)
        if bypass:
            plan_name = bypass[0]
            expires = datetime.fromtimestamp(bypass[1])
            return True, f"✅ Bypass: {plan_name} (fino al {expires.strftime('%d/%m %H:%M')})"
        
        cursor = self.conn.execute("SELECT last_video_time FROM video_cooldowns WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row[0]:
            elapsed = time.time() - row[0]
            if elapsed < 900:
                remaining = int(900 - elapsed)
                return False, f"⏳ Attendi {remaining//60}m {remaining%60}s\n💡 /buy_bypass per saltare la fila"
        return True, ""
    
    def mark_video_generated(self, user_id):
        self.conn.execute("INSERT OR REPLACE INTO video_cooldowns VALUES (?, ?, COALESCE((SELECT video_count FROM video_cooldowns WHERE user_id = ?) + 1, 1))", (user_id, time.time(), user_id))
        self.conn.commit()
    
    def get_video_count(self, user_id):
        cursor = self.conn.execute("SELECT video_count FROM video_cooldowns WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    
    def has_active_bypass(self, user_id):
        cursor = self.conn.execute("SELECT plan, expires_at FROM bypass_purchases WHERE user_id=? AND verified=1 AND expires_at>? ORDER BY expires_at DESC LIMIT 1", (user_id, time.time()))
        return cursor.fetchone()
    
    def create_transaction(self, user_id, plan, arc_amount, duration_hours):
        tx_id = f"ARC-TX-{user_id}-{int(time.time())}-{hashlib.md5(str(random.random()).encode()).hexdigest()[:6]}"
        self.conn.execute("INSERT INTO bypass_purchases VALUES (?,?,?,?,?,?,0,NULL,NULL)", (tx_id, user_id, plan, arc_amount, time.time(), time.time()+duration_hours*3600))
        self.conn.commit()
        return tx_id
    
    def verify_transaction(self, tx_id, verified_by):
        self.conn.execute("UPDATE bypass_purchases SET verified=1, verified_by=?, verified_at=? WHERE tx_id=?", (verified_by, time.time(), tx_id))
        self.conn.commit()
        return self.conn.execute("SELECT user_id, plan, arc_amount FROM bypass_purchases WHERE tx_id=?", (tx_id,)).fetchone()
    
    def create_vip_code(self, code, plan, duration_hours, created_by, max_uses=1):
        self.conn.execute(
            "INSERT INTO vip_codes (code, plan, duration_hours, created_by, created_at, max_uses) VALUES (?,?,?,?,?,?)",
            (code, plan, duration_hours, created_by, time.time(), max_uses)
        )
        self.conn.commit()
        return code

    def redeem_vip_code(self, code, user_id):
        cursor = self.conn.execute(
            "SELECT plan, duration_hours, max_uses, current_uses FROM vip_codes WHERE code=? AND (used_by=0 OR used_by=?)",
            (code, user_id)
        )
        row = cursor.fetchone()
        
        if not row:
            return None, "Codice non valido o già usato"
        
        plan, duration_hours, max_uses, current_uses = row
        
        if current_uses >= max_uses:
            return None, "Codice esaurito"
        
        self.conn.execute(
            "UPDATE vip_codes SET used_by=?, used_at=?, current_uses=current_uses+1 WHERE code=?",
            (user_id, time.time(), code)
        )
        
        tx_id = f"VIP-{user_id}-{int(time.time())}"
        self.conn.execute(
            "INSERT INTO bypass_purchases (tx_id, user_id, plan, arc_amount, purchased_at, expires_at, verified) VALUES (?,?,?,0,?,?,1)",
            (tx_id, user_id, f"VIP: {plan}", time.time(), time.time() + duration_hours * 3600)
        )
        self.conn.commit()
        
        return plan, f"✅ VIP attivato: {plan} per {duration_hours} ore"

    def list_vip_codes(self, user_id=None):
        if user_id:
            cursor = self.conn.execute(
                "SELECT code, plan, duration_hours, max_uses, current_uses, used_by, created_at FROM vip_codes WHERE created_by=? ORDER BY created_at DESC",
                (user_id,)
            )
        else:
            cursor = self.conn.execute(
                "SELECT code, plan, duration_hours, max_uses, current_uses, used_by, created_at FROM vip_codes ORDER BY created_at DESC"
            )
        return cursor.fetchall()
    
    def cleanup(self):
        self.conn.execute("DELETE FROM processed WHERE date < ?", (int(time.time()) - 3600,))
        self.conn.execute("DELETE FROM conversation_memory WHERE timestamp < ?", (int(time.time()) - 604800,))
        self.conn.execute("DELETE FROM image_generations WHERE generated_at < ?", (time.time() - 86400,))
        self.conn.commit()
    
    def close(self):
        self.conn.close()

class VideoRateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.processing = False
        self.current_user = None
    
    def can_process(self, user_id, db):
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return True, ""
        with self.lock:
            can_gen, msg = db.can_generate_video(user_id)
            if not can_gen:
                return False, msg, 0
            if self.processing:
                if user_id == self.current_user:
                    return False, "🎬 Il tuo video è in elaborazione...", 0
                return False, "🎬 Un video è già in elaborazione. Attendi.", 0
            self.processing = True
            self.current_user = user_id
            return True, "", 0
    
    def finish(self, user_id):
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return None
        with self.lock:
            self.processing = False
            self.current_user = None

video_limiter = VideoRateLimiter()

BYPASS_PRICES = {
    "1h": {"name": "Bypass 1 ora", "arc": 20, "hours": 1},
    "24h": {"name": "Bypass 24 ore", "arc": 100, "hours": 24},
    "7d": {"name": "Bypass 7 giorni", "arc": 500, "hours": 168},
}

class CESImage:
    count = 0
    BANNED = ["nsfw", "porn", "nude", "gore", "blood"]
    
    @classmethod
    def generate(cls, prompt):
        if not prompt or len(prompt.strip()) < 2:
            return {"success": False, "error": "Prompt troppo corto"}
        prompt = prompt.strip()[:500]
        if any(w in re.sub(r'\s+','',prompt.lower()) for w in cls.BANNED):
            return {"success": False, "error": "Contenuto bloccato"}
        enhanced = f"Masterpiece, 8K, ultra-detailed. Subject: {prompt}"
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced)}?model=flux&width=1024&height=1024&nologo=true&seed={random.randint(1,999999)}"
        cls.count += 1
        return {"success": True, "image_url": url, "prompt": prompt}

class CESImagePlus:
    count = 0
    BANNED = ["nsfw", "porn", "nude", "gore", "blood"]
    
    @classmethod
    def generate(cls, prompt):
        """Genera un'immagine con FLUX (qualità superiore) - SENZA TIMEOUT"""
        if not prompt or len(prompt.strip()) < 2:
            return {"success": False, "error": "Prompt troppo corto"}
        
        prompt = prompt.strip()[:500]
        normalized = re.sub(r'\s+', '', prompt.lower())
        for word in cls.BANNED:
            if word in normalized:
                return {"success": False, "error": "Contenuto bloccato per motivi di sicurezza."}
        
        # ===== TENTATIVO 1: DeepInfra FLUX.1-dev =====
        english_prompt = cls._translate_to_english(prompt)
        print(f"🌐 [DeepInfra] Prompt tradotto: '{english_prompt}'")
        
        try:
            print(f"🎨 [DeepInfra] Generazione FLUX.1-dev per: {english_prompt[:80]}...")
            
            # Utilizza requests SENZA TIMEOUT
            response = requests.post(
                "https://api.deepinfra.com/v1/inference/black-forest-labs/FLUX.1-dev",
                json={"prompt": f"masterpiece, best quality, highly detailed, 8k, photorealistic: {english_prompt}"},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data and "images" in data and len(data["images"]) > 0:
                    image_url = data["images"][0]
                    img_response = requests.get(image_url)
                    if img_response.status_code == 200:
                        img_id = hashlib.md5(f"{prompt}{time.time()}".encode()).hexdigest()[:8]
                        img_path = TEMP_FOLDER / f"flux_plus_{img_id}.png"
                        with open(img_path, 'wb') as f:
                            f.write(img_response.content)
                        cls.count += 1
                        return {"success": True, "image_path": img_path, "prompt": prompt, "fallback": False}
                    cls.count += 1
                    return {"success": True, "image_url": image_url, "prompt": prompt, "fallback": False}
                    
            elif response.status_code == 422:
                print("⚠️ DeepInfra 422 - Provo con Hugging Face...")
                return cls._try_huggingface(prompt)
                
            elif response.status_code == 429:
                return {"success": False, "error": "⏳ DeepInfra: limite raggiunto. Provo con Hugging Face..."}
            else:
                print(f"⚠️ DeepInfra errore {response.status_code}")
                return cls._try_huggingface(prompt)
                
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Errore DeepInfra ({e}) - Reindirizzamento a Hugging Face...")
            return cls._try_huggingface(prompt)
        except Exception as e:
            print(f"⚠️ DeepInfra errore imprevisto: {e}")
            return cls._try_huggingface(prompt)
    
    @classmethod
    def _try_huggingface(cls, prompt):
        """Tentativo con Hugging Face usando la patch DNS e la libreria requests per stabilità"""
        try:
            print(f"🎨 [HF-FLUX] Generazione per: {prompt[:80]}...")
            
            # Utilizziamo un modello non-gated per evitare restrizioni di licenza account
            model_id = "black-forest-labs/FLUX.1-schnell"
            url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
            
            enhanced_prompt = f"masterpiece, best quality, highly detailed, 8k, photorealistic, cinematic lighting: {prompt}"
            payload = {"inputs": enhanced_prompt}
            
            print(f"   📤 Invio richiesta a Hugging Face (senza timeout)...")
            
            # Chiamata a Hugging Face usando requests (sfrutta la DNS patch globale)
            r = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {HF_TOKEN}",
                    "Content-Type": "application/json",
                    "User-Agent": "ArcadiaAI/1.0"
                }
            )
            
            print(f"   📥 Ricevuta risposta {r.status_code} da HF")
            
            if r.status_code == 200:
                content_type = r.headers.get('Content-Type', '')
                content = r.content
                
                if content_type.startswith('image/') or (len(content) > 1000 and content[:4] in [b'\x89PNG', b'\xff\xd8\xff']):
                    img_id = hashlib.md5(f"{prompt}{time.time()}".encode()).hexdigest()[:8]
                    img_path = TEMP_FOLDER / f"sd35_{img_id}.png"
                    
                    with open(img_path, 'wb') as f:
                        f.write(content)
                    
                    cls.count += 1
                    print(f"   ✅ Immagine HF salvata: {img_path}")
                    return {"success": True, "image_path": img_path, "prompt": prompt, "fallback": True}
                
                try:
                    error_data = r.json()
                    if "error" in error_data:
                        error_msg = error_data["error"]
                        if "loading" in error_msg.lower():
                            return {"success": False, "error": "⏳ Modello in caricamento (1-3 minuti). Riprova tra un minuto."}
                        return {"success": False, "error": f"HF: {error_msg[:150]}"}
                except:
                    pass
                
                return {"success": False, "error": "Risposta inaspettata dal server HuggingFace"}
                
            elif r.status_code == 503:
                return {"success": False, "error": "⏳ Modello in caricamento su Hugging Face. Riprova tra 1-2 minuti."}
            elif r.status_code == 401:
                return {"success": False, "error": "🔑 Token Hugging Face non valido."}
            elif r.status_code == 429:
                return {"success": False, "error": "📊 Troppe richieste. Riprova tra qualche minuto."}
            else:
                return {"success": False, "error": f"Errore server HF (Stato {r.status_code})"}
                
        except Exception as e:
            print(f"   ❌ Errore HF: {e}")
            return {"success": False, "error": f"Errore connessione HF: {str(e)[:100]}"}
    
    @staticmethod
    def _translate_to_english(text):
        """Traduce un prompt in italiano in inglese usando Gemini o OpenRouter"""
        try:
            translation_prompt = f"Translate the following Italian text to English, keeping it natural and descriptive. Only output the translation, nothing else:\n\n{text}"
            
            result = AIClient.generate(translation_prompt, max_tok=200)
            
            if result and len(result) > 3:
                translation = result.strip().strip('"').strip("'")
                if len(translation) > 3:
                    return translation
            
            # Fallback: traduzione di emergenza a dizionario
            simple_map = {
                "uomo": "man", "donna": "woman", "gatto": "cat", "cane": "dog",
                "casa": "house", "paesaggio": "landscape", "natura": "nature",
                "mare": "sea", "montagna": "mountain", "città": "city",
                "albero": "tree", "fiore": "flower", "sole": "sun", "luna": "moon",
                "stelle": "stars", "seduto": "sitting", "in piedi": "standing",
                "cammina": "walking", "corre": "running", "sorride": "smiling",
                "triste": "sad", "felice": "happy", "bello": "beautiful",
                "grande": "big", "piccolo": "small", "sedia": "chair",
                "tavolo": "table", "porta": "door", "finestra": "window",
                "libro": "book", "telefono": "phone", "computer": "computer",
                "caffè": "coffee", "vino": "wine", "pizza": "pizza",
                "musica": "music", "arte": "art", "foto": "photo", "ritratto": "portrait"
            }
            
            translated = text.lower()
            for it, en in simple_map.items():
                translated = translated.replace(it, en)
            
            if translated != text.lower():
                return translated
            
            return text
            
        except Exception as e:
            print(f"⚠️ Errore traduzione: {e}")
            return text

class CESVideo:
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    BANNED = ["nsfw", "porn", "nude", "gore", "blood"]
    count = 0
    
    @classmethod
    def _find_ffmpeg(cls):
        local = SCRIPT_DIR / 'ffmpeg.exe'
        if local.exists(): return str(local)
        try:
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
            if result.returncode == 0: return 'ffmpeg'
        except: pass
        for p in ['/usr/bin/ffmpeg', '/opt/homebrew/bin/ffmpeg']:
            if Path(p).exists(): return p
        return None

    @classmethod
    def clean_narration_text(cls, text):
        if not text:
            return ""
        text = re.sub(r'(?i)^\s*(user safety|safety|narratore|narratrice|voce fuori campo|voce narrante|testo da recitare|testo|sceneggiatura|voiceover|audio)\s*[:\-]\s*\w*\n*', '', text)
        text = text.strip().strip('"').strip("'").strip('«').strip('»')
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        return text.strip()

    @classmethod
    def generate_narration_script(cls, prompt, style):
        system_instruction = (
            "Sei un regista e sceneggiatore professionista. Scrivi un brevissimo testo narrativo o poetico in italiano "
            "da recitare come voce fuori campo per un video cinematografico d'autore. "
            "Il testo deve basarsi sul prompt dell'utente ma deve sembrare una narrazione o un dialogo reale e immersivo, "
            "assolutamente NON una descrizione tecnica o letterale del prompt. "
            "Usa un tono naturale ed emotivo. Massimo 20-25 parole (durata circa 10-12 secondi di recitazione lenta). "
            "Scrivi ESCLUSIVAMENTE la frase da recitare, senza virgolette, indicazioni di scena, o commenti."
        )
        try:
            llm_prompt = f"Prompt del video: '{prompt}' (Stile: {style})"
            narration = AIClient.generate(f"{system_instruction}\n\n{llm_prompt}", max_tok=150)
            if narration:
                cleaned = cls.clean_narration_text(narration)
                if len(cleaned) > 5:
                    return cleaned
        except:
            pass
        
        prompt_clean = prompt.lower().strip()
        if "gatto" in prompt_clean:
            return "Un piccolo gatto gioca felice con il suo gomitolo di lana, tra movimenti lenti e sguardi curiosi."
        if "aldo moro" in prompt_clean:
            return "Il ritorno inaspettato di una figura storica, tra le ombre di un tempo che sembra essersi fermato."
        if "uomo" in prompt_clean or "donna" in prompt_clean:
            return "Due sguardi si incrociano nel silenzio di una strada affollata, cercando una direzione comune."
            
        return "Immagini sospese nel tempo, che catturano l'essenza più autentica di questa scena."

    @classmethod
    def generate_video(cls, prompt, style="cinematic"):
        if not prompt or len(prompt.strip()) < 3:
            return {"success": False, "error": "Descrivi la scena (minimo 3 parole)"}
        
        prompt = prompt.strip()[:300]
        normalized = re.sub(r'\s+', '', prompt.lower())
        for word in cls.BANNED:
            if word in normalized:
                return {"success": False, "error": "Contenuto bloccato"}
        
        job_id = hashlib.md5(f"{prompt}{time.time()}".encode()).hexdigest()[:8]
        job_dir = VIDEO_FOLDER / job_id
        job_dir.mkdir(exist_ok=True)
        
        styles = {
            "cinematic": "cinematic scene, 4k, highly detailed movie screenshot, professional cinematic color grading, masterpiece",
            "anime": "anime style, vibrant colors, clean animation lines, studio ghibli, masterpiece key visual",
            "realistic": "photorealistic, 8k, highly detailed, professional cinematography, master shot",
            "artistic": "artistic oil painting, fluid motion brush strokes, fine art masterpiece",
        }
        style_prompt = styles.get(style, styles["cinematic"])
        
        print(f"   ⠋ Avvio download fotogramma master ad alta definizione...")
        
        master_seed = random.randint(100000, 899999)
        cache_bust = random.randint(1000, 9999)
        
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(style_prompt + '. ' + prompt)}?width=1280&height=720&nologo=true&seed={master_seed}&cb={cache_bust}&model=flux"
        master_img_path = job_dir / "master.jpg"
        
        download_success = False
        max_tentativi = 3
        
        for tentativo in range(max_tentativi):
            try:
                if tentativo > 0:
                    attesa = random.uniform(2.0, 4.0)
                    print(f"      ⏳ Pausa strategica anti-429 per {attesa:.1f}s...")
                    time.sleep(attesa)
                
                req = urllib.request.Request(url, headers=cls.HEADERS)
                with urllib.request.urlopen(req, timeout=45) as response:
                    with open(master_img_path, 'wb') as out:
                        while True:
                            chunk = response.read(16384)
                            if not chunk: break
                            out.write(chunk)
                
                if master_img_path.exists() and master_img_path.stat().st_size > 15000:
                    print(f"      ✅ Fotogramma master scaricato con successo al tentativo {tentativo+1}!")
                    download_success = True
                    break
            except Exception as e:
                print(f"      ❌ Errore scaricamento master ({e}) al tentativo {tentativo+1}")
                if master_img_path.exists():
                    try: master_img_path.unlink()
                    except: pass
                    
        if not download_success:
            return {"success": False, "error": "Il server AI è sovraccarico o temporaneamente non raggiungibile. Riprova tra 1 minuto."}
            
        ffmpeg = cls._find_ffmpeg()
        if not ffmpeg:
            return {"success": False, "error": "FFmpeg non configurato."}
            
        video_temp = job_dir / "video_silent.mp4"
        
        motion_filter = (
            "scale=1280:720,"
            "zoompan=z='1.15+0.0005*on':d=288:x='(iw-iw/zoom)/2 + 5*sin(on/8)':y='(ih-ih/zoom)/2 + 4*cos(on/10)':s=640x360,"
            "eq=brightness='0.02*sin(on/15)':contrast='1.0+0.01*cos(on/20)'"
        )
        
        print(f"   ⚙️ Rendering in corso (12 secondi, 24 fps, Handheld Cam Shake)...")
        cmd_video = [
            ffmpeg, '-y',
            '-loop', '1',
            '-t', '12',
            '-i', str(master_img_path),
            '-vf', motion_filter,
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-r', '24',
            '-preset', 'ultrafast',
            '-threads', '1',
            str(video_temp)
        ]
        
        res = subprocess.run(cmd_video, capture_output=True, timeout=45)
        if res.returncode != 0:
            print(f"❌ Errore FFmpeg: {res.stderr.decode('utf-8', errors='ignore')}")
            return {"success": False, "error": "Errore durante il rendering del video fluido."}
            
        try: master_img_path.unlink()
        except: pass
        
        if not video_temp.exists() or video_temp.stat().st_size < 100:
            return {"success": False, "error": "Errore di codec nel file video temporaneo."}
            
        print(f"   🎙️ Genero traccia vocale intelligente d'autore...")
        narration = cls.generate_narration_script(prompt, style)
            
        audio_path = job_dir / "narration.mp3"
        
        try:
            from gtts import gTTS
            tts = gTTS(text=narration[:500], lang='it', slow=False)
            tts.save(str(audio_path))
        except Exception as tts_err:
            print(f"⚠️ Errore TTS: {tts_err}")
            pass
            
        final_path = job_dir / "video_final.mp4"
        if audio_path.exists():
            print(f"   🔗 Unisco Audio + Video Fluido con aggiornamento PTS...")
            cmd_merge = [
                ffmpeg, '-y',
                '-i', str(video_temp), '-i', str(audio_path),
                '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0',
                '-threads', '1', str(final_path)
            ]
            subprocess.run(cmd_merge, capture_output=True, timeout=20)
        else:
            shutil.copy(video_temp, final_path)
            
        try: video_temp.unlink()
        except: pass
        try: audio_path.unlink()
        except: pass
        gc.collect()
        
        cls.count += 1
        return {
            "success": True,
            "video_path": final_path,
            "frame_count": 288,
            "fps": 24,
            "has_audio": final_path.exists(),
            "prompt": prompt,
            "style": style,
            "generated_narration": narration
        }

class AIClient:
    count = 0
    
    GEMINI_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
    ]
    
    @classmethod
    def generate(cls, prompt, max_tok=300):
        # Primo Guardrail locale interno per prevenire qualsiasi invocazione all'esterno
        is_sensitive, category = PrivacyGuard.check_sensitive_data(prompt)
        if is_sensitive:
            print(f"🔒 [AIClient] Generazione interrotta localmente per presenza di dati sensibili ({category}).")
            return f"⚠️ [PRIVACY BLOCK] La richiesta contiene dati particolari/sensibili ({category}) e non può essere elaborata localmente."

        prompt_with_aliases = AliasResolver.apply_aliases_to_text(prompt)
        
        if GEMINI_API_KEY:
            for model in cls.GEMINI_MODELS:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                    
                    d = json.dumps({
                        "contents": [{"parts": [{"text": prompt_with_aliases}]}],
                        "systemInstruction": {"parts": [{"text": IDENTITY_PROMPT}]}
                    }).encode()
                    
                    req = urllib.request.Request(
                        url, 
                        data=d, 
                        headers={"Content-Type": "application/json"}, 
                        method='POST'
                    )
                    
                    with urllib.request.urlopen(req, timeout=20) as r:
                        j = json.loads(r.read().decode())
                        result_text = j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if result_text and result_text.strip():
                            cls.count += 1
                            cleaned = cls._clean(result_text)
                            print(f"✅ Gemini: modello {model} risposto con successo")
                            return cleaned
                            
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        print(f"⚠️ Gemini: modello {model} non trovato (404)")
                    elif e.code == 429:
                        print(f"⚠️ Gemini: modello {model} rate limit (429), provo prossimo...")
                    elif e.code == 400:
                        print(f"⚠️ Gemini: modello {model} richiesta errata (400)")
                        try:
                            error_body = e.read().decode('utf-8')
                            print(f"   📄 Errore: {error_body[:200]}")
                        except:
                            pass
                    else:
                        print(f"⚠️ Gemini: modello {model} errore {e.code}")
                    time.sleep(0.5)
                except Exception as e:
                    print(f"⚠️ Gemini: modello {model} errore: {e}")
                    time.sleep(0.3)
        
        if OPENROUTER_API_KEY:
            try:
                openrouter_models = [
                    "openrouter/free",
                    "google/gemini-2.5-flash-1.5b",
                    "mistralai/mistral-7b-instruct"
                ]
                
                for model in openrouter_models:
                    try:
                        d = json.dumps({
                            "model": model,
                            "messages": [{"role": "user", "content": prompt_with_aliases}],
                            "max_tokens": max_tok,
                            "temperature": 0.7
                        }).encode()
                        
                        req = urllib.request.Request(
                            "https://openrouter.ai/api/v1/chat/completions",
                            data=d,
                            headers={
                                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                "Content-Type": "application/json"
                            },
                            method='POST'
                        )
                        
                        with urllib.request.urlopen(req, timeout=25) as r:
                            j = json.loads(r.read().decode())
                            
                            if j and "choices" in j and len(j["choices"]) > 0:
                                choice = j["choices"][0]
                                if "message" in choice and "content" in choice["message"]:
                                    content = choice["message"]["content"]
                                    if content and content.strip():
                                        cls.count += 1
                                        cleaned = cls._clean(content)
                                        print(f"✅ OpenRouter: modello {model} risposto con successo")
                                        return cleaned
                                        
                    except urllib.error.HTTPError as e:
                        print(f"⚠️ OpenRouter: modello {model} errore {e.code}")
                        if e.code == 429:
                            time.sleep(1)
                    except Exception as e:
                        print(f"⚠️ OpenRouter: modello {model} errore: {e}")
                        
            except Exception as e:
                print(f"⚠️ Errore OpenRouter: {e}")
        
        return None
    
    @classmethod
    def _clean(cls, text):
        if not text:
            return ""
            
        text = text.strip()
        
        text = re.sub(r'(?i)^User Safety:\s*\w+\s*\n?', '', text)
        text = re.sub(r'(?i)^Safety:\s*\w+\s*\n?', '', text)
        text = re.sub(r'(?i)^(okay|let me|dunque|allora|vediamo|analizzo|devo|i need|first|penso|credo|echo).*?[:\.]\s*', '', text)
        
        lines = []
        for l in text.split('\n'):
            if not re.match(r'(?i)^(okay|let me|dunque|quindi|devo|i need|the user|first|user safety|safety)', l.strip()):
                lines.append(l)
        text = '\n'.join(lines).strip() if lines else text
        
        text = AliasResolver.restore_real_names_to_text(text)
        
        return text

class WebSearch:
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    ]
    
    @staticmethod
    def search(query, n=4):
        results = []
        
        for attempt in range(3):
            try:
                user_agent = random.choice(WebSearch.USER_AGENTS)
                encoded_q = urllib.parse.quote_plus(query)
                
                req = urllib.request.Request(
                    f"https://html.duckduckgo.com/html/?q={encoded_q}",
                    headers={
                        'User-Agent': user_agent,
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1'
                    }
                )
                
                with urllib.request.urlopen(req, timeout=10) as r:
                    html_data = r.read().decode('utf-8', errors='ignore')
                    
                    blocks = re.findall(r'<div class="result__body">.*?</div>', html_data, re.DOTALL)
                    
                    if blocks:
                        for block in blocks[:n]:
                            title_match = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                            
                            if title_match:
                                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                                snippet = ""
                                if snippet_match:
                                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                                
                                url_match = re.search(r'href=["\']([^"\']+)', title_match.group(0))
                                url = url_match.group(1) if url_match else ""
                                
                                if url.startswith('//'):
                                    url = 'https:' + url
                                elif url.startswith('/'):
                                    url = 'https://duckduckgo.com' + url
                                
                                if len(snippet) > 10:
                                    results.append({
                                        "title": title,
                                        "snippet": snippet[:300],
                                        "url": url
                                    })
                        
                        if results:
                            print(f"   🌐 [Web] Trovati {len(results)} risultati per '{query[:50]}...'")
                            return results
                    
                    alt_blocks = re.findall(r'<a rel="nofollow" class="result__a".*?</a>', html_data, re.DOTALL)
                    if alt_blocks:
                        for block in alt_blocks[:n]:
                            title = re.sub(r'<[^>]+>', '', block).strip()
                            url_match = re.search(r'href=["\']([^"\']+)', block)
                            if url_match and title and len(title) > 5:
                                results.append({
                                    "title": title,
                                    "snippet": f"Risultato trovato per: {query}",
                                    "url": url_match.group(1)
                                })
                        
                        if results:
                            print(f"   🌐 [Web] Trovati {len(results)} risultati (alt) per '{query[:50]}...'")
                            return results
                            
            except Exception as e:
                print(f"   ⚠️ WebSearch tentativo {attempt+1} fallito: {e}")
                if attempt < 2:
                    time.sleep(random.uniform(1, 3))
                continue
        
        print(f"   🌐 [Web] Nessun risultato per '{query[:50]}...'")
        return results

class FileLoader:
    def __init__(self, folder_path):
        self.folder = Path(folder_path)
        self.files_content = {}
        self.folder.mkdir(parents=True, exist_ok=True)
        for fp in self.folder.glob("*.txt"):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    self.files_content[fp.name] = f.read()
            except:
                pass
    
    def get_all_content(self):
        return "\n".join(self.files_content.values())

# ==================== SISTEMA DI INDICIZZAZIONE E RICERCA SEMANTICA LOCALE ====================
class KnowledgeBase:
    STOPWORDS = {
        "quante", "volte", "sono", "le", "ha", "il", "di", "a", "da", "in", "per", "con", "su", 
        "del", "della", "dei", "degli", "delle", "al", "alla", "ai", "agli", "alle", "dal", "dalla", 
        "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", 
        "sugli", "sulle", "e", "ed", "o", "ma", "se", "perché", "chi", "cosa", "come", "dove", 
        "quando", "questo", "questa", "questi", "queste", "quello", "quella", "quelli", "quelle", 
        "si", "no", "non", "ci", "vi", "ti", "mi", "lo", "la", "gli", "li", "un", "uno", "una", "un'"
    }

    def __init__(self, data_folder):
        self.data_folder = Path(data_folder)
        self.files_content = {}
        self.chunks = []
        self.idf = {}
        self.load_all_files()
        self.index_chunks()
    
    def load_all_files(self):
        for fp in self.data_folder.glob("*.txt"):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    self.files_content[fp.name] = f.read()
                    print(f"📚 Caricatu: {fp.name} ({len(self.files_content[fp.name])} caratteri)")
            except Exception as e:
                print(f"⚠️ Errore caricandu {fp.name}: {e}")
                
    def reload(self):
        """Forza u svitamentu di a cache è ricarica i schedarii aghjurnati da u discu"""
        self.files_content = {}
        self.chunks = []
        self.idf = {}
        self.load_all_files()
        self.index_chunks()
        print("🔄 [KnowledgeBase] Aghjurnamentu di l'indici semanticu cumpletatu!")

    @staticmethod
    def stem_word(word):
        word = word.lower().strip()
        word = re.sub(r'[^\w]', '', word)
        if len(word) <= 2:
            return word
        
        suffixes = (
            'izzazione', 'izzazioni', 'izzazione',
            'eranno', 'eremmo', 'ereste', 'eresti', 'eranno',
            'assero', 'essero', 'issero', 'avamo', 'avate',
            'arono', 'erono', 'irono', 'andoci', 'endoci',
            'andone', 'endone', 'atemi', 'atela', 'atelo',
            'ateci', 'atevi', 'ateli', 'atele', 'atene',
            'abile', 'ibili', 'mente', 'zione', 'zioni',
            'atore', 'atori', 'atrice', 'atrici',
            'issimo', 'issima', 'issimi', 'issime',
            'arono', 'erono', 'irono', 'avamo', 'avate', 'avano',
            'eremo', 'erete', 'iremo', 'irete',
            'ando', 'endo', 'ante', 'ente', 'anti', 'enti',
            'ammo', 'ando', 'asse', 'assi', 'este', 'esti', 'iamo', 'iate',
            'ato', 'ata', 'ati', 'ate', 'uto', 'uta', 'uti', 'ute',
            'ito', 'ita', 'iti', 'ite', 'ico', 'ica', 'ici', 'ice',
            'ina', 'ini', 'ine', 'ino', 'ica', 'ice', 'ici', 'ico', 'iche',
            'oso', 'osa', 'osi', 'ose', 'ore', 'ori',
            'ere', 'are', 'ire', 'ense', 'ensi',
            'ava', 'avi', 'avo', 'eva', 'evi', 'evo', 'iva', 'ivi', 'ivo',
            'erò', 'erà', 'irò', 'irò',
            'o', 'a', 'i', 'e'
        )
        for suffix in suffixes:
            if word.endswith(suffix):
                if len(word) - len(suffix) >= 3:
                    return word[:-len(suffix)]
        return word

    def clean_query(self, query):
        cleaned = re.sub(r'[^\w\s]', ' ', query.lower())
        words = [w for w in cleaned.split() if w not in self.STOPWORDS and len(w) > 2]
        return words if words else cleaned.split()

    def index_chunks(self):
        """Divide i testi in blocchi equilibrati è indicizza i termini"""
        self.chunks = []
        doc_counts = defaultdict(int)
        
        for filename, content in self.files_content.items():
            content_resolved = AliasResolver.resolve_all_names(content)
            lines = content_resolved.split('\n')
            current_chunk = []
            current_length = 0
            
            for line in lines:
                line_strip = line.strip()
                if not line_strip:
                    continue
                current_chunk.append(line_strip)
                current_length += len(line_strip)
                
                if current_length >= 600:
                    text = "\n".join(current_chunk)
                    self._add_chunk(filename, text, doc_counts)
                    overlap_count = max(1, len(current_chunk) // 5)
                    current_chunk = current_chunk[-overlap_count:]
                    current_length = sum(len(l) for l in current_chunk)
                    
            if current_chunk:
                text = "\n".join(current_chunk)
                self._add_chunk(filename, text, doc_counts)
                
        total_chunks = len(self.chunks)
        for term, count in doc_counts.items():
            self.idf[term] = math.log((total_chunks + 1) / (count + 0.5)) + 1.0

    def _add_chunk(self, filename, text, doc_counts):
        words = re.findall(r'\w+', text.lower())
        stems = set()
        term_freqs = defaultdict(int)
        
        for w in words:
            if w not in self.STOPWORDS and len(w) > 2:
                term_freqs[w] += 1
                stems.add(w)
                
                stem = self.stem_word(w)
                if stem != w:
                    term_freqs[stem] += 1
                    stems.add(stem)
                
        for stem in stems:
            doc_counts[stem] += 1
            
        self.chunks.append({
            'file': filename,
            'text': text,
            'stems': stems,
            'term_freqs': term_freqs,
            'word_count': len(words)
        })

    def search(self, query, max_results=5):
        """Esegue una ricerca semantica ottimizzata con boost sui file nominati esplicitamente nella query"""
        query_words = re.findall(r'\w+', query.lower())
        query_stems = []
        for w in query_words:
            if w not in self.STOPWORDS and len(w) > 2:
                query_stems.append(w)
                stem = self.stem_word(w)
                if stem != w:
                    query_stems.append(stem)
        
        if not query_stems:
            query_stems = [query.lower().strip()]
            
        results = []
        for chunk in self.chunks:
            score = 0.0
            matched_stems = set()
            
            for q_stem in query_stems:
                if q_stem in chunk['stems']:
                    tf = chunk['term_freqs'][q_stem]
                    idf_val = self.idf.get(q_stem, 1.0)
                    tf_score = (tf * 2.2) / (tf + 1.2)
                    score += tf_score * idf_val
                    matched_stems.add(q_stem)
            
            if len(matched_stems) > 1:
                ratio = len(matched_stems) / len(query_stems)
                score *= (1.5 + ratio * 2.0)
            
            if chunk['word_count'] > 0:
                score /= (0.8 + 0.2 * (chunk['word_count'] / 200.0))
                
            # BOOST SEMANTICU
            file_lower = chunk['file'].lower()
            for qw in query_words:
                if len(qw) > 3 and qw in file_lower:
                    score *= 1.8
            
            if score > 0.0:
                results.append({
                    'file': chunk['file'],
                    'score': score,
                    'context': chunk['text'],
                    'line': chunk['text'].split('\n')[0]
                })
                
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_results]
    
    def find_exact_answer(self, query, entity_name):
        results = self.search(query, max_results=10)
        entity_lower = entity_name.lower()
        for r in results:
            if entity_lower in r['context'].lower():
                return r['context']
        
        query_words = self.clean_query(query)
        for r in results:
            if any(word in r['context'].lower() for word in query_words):
                return r['context']
        
        return None

# ==================== ESTRATTORE / SCRAPER AUTOMATICO DI LEONIA+ ====================
class LeoniaPlusUpdater:
    @staticmethod
    def scrape_channel():
        """Estrae i post pubblici di @leoniaplusgiornale a costo zero ed in totale sicurezza"""
        try:
            print("📰 [Leonia+] Avviu di a sincronizazione cù @leoniaplusgiornale...")
            url = "https://t.me/s/leoniaplusgiornale"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            
            r = REQUESTS_SESSION.get(url, headers=headers, timeout=25)
            if r.status_code != 200:
                print(f"⚠️ [Leonia+] Impussibile scaricà a pagina. Status HTTP: {r.status_code}")
                return False
            
            html_content = r.text
            posts_raw = re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', html_content, re.DOTALL)
            
            if not posts_raw:
                print("⚠️ [Leonia+] Nisun post trovu o classe HTML cambiata da u servitore di Telegram.")
                return False
            
            cleaned_posts = []
            for idx, post in enumerate(posts_raw):
                p_text = re.sub(r'<br\s*/?>', '\n', post)
                p_text = re.sub(r'<[^>]+>', '', p_text)
                p_text = html.unescape(p_text).strip()
                
                if len(p_text) > 10:
                    cleaned_posts.append(p_text)
            
            if cleaned_posts:
                output_path = DATA_FOLDER / "leoniaplus_giornale.txt"
                
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write("==================================================\n")
                    f.write("📰 ARCHIVIU ARTICULI È NUTIZIE DI LEONIA+ (@leoniaplusgiornale)\n")
                    f.write(f"Sincronizazione automatica eseguita u: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
                    f.write("==================================================\n\n")
                    
                    for i, post_content in enumerate(reversed(cleaned_posts), 1):
                        f.write(f"--- NUTIZIA #{i} ---\n")
                        f.write(f"{post_content}\n")
                        f.write("-" * 40 + "\n\n")
                
                print(f"✅ [Leonia+] Sincronizazione riuscita! Salvati {len(cleaned_posts)} post in {output_path.name}")
                return True
            else:
                print("⚠️ [Leonia+] Nisun post idoneu estrettu.")
                return False
                
        except Exception as e:
            print(f"❌ [Leonia+] Errore imprevistu durante a sincronizazione: {e}")
            return False

# ==================== STRUMENTO DI PUBBLICAZIONE SU TELEGRAPH (ANONIMO) ====================
class TelegraphPublisher:
    _token = None
    _lock = threading.Lock()

    @classmethod
    def get_token(cls):
        """Recupera il token di accesso salvato o ne crea uno anonimo se non presente"""
        with cls._lock:
            if cls._token:
                return cls._token
            
            db_path = SCRIPT_DIR / "processed.db"
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            try:
                cursor = conn.execute("SELECT value FROM bot_state WHERE key = 'telegraph_token'")
                row = cursor.fetchone()
                if row:
                    cls._token = row[0]
                    return cls._token
            except Exception as e:
                print(f"⚠️ [Telegraph DB] Impussibile ricuperà u token: {e}")
            finally:
                conn.close()
            
            try:
                print("🔌 [Telegraph] Generazione di un token account anonimo...")
                url = "https://api.telegra.ph/createAccount"
                params = {
                    "short_name": "ArcadiaAI",
                    "author_name": "ArcadiaAI",
                    "author_url": "https://github.com/Mirko-linux/ArcadiaAI-new"
                }
                r = REQUESTS_SESSION.get(url, params=params, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ok"):
                        token = data["result"].get("access_token")
                        if token:
                            conn = sqlite3.connect(str(db_path), check_same_thread=False)
                            conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('telegraph_token', ?)", (token,))
                            conn.commit()
                            conn.close()
                            cls._token = token
                            print("✅ [Telegraph] Account creatu è memorizatu currettamente!")
                            return token
            except Exception as e:
                print(f"❌ [Telegraph] Errore criticu durante a creazione di l'account: {e}")
            
            return None

    @classmethod
    def parse_inline_text(cls, text: str) -> List[Any]:
        """Tokenizza e converte inline grassetti, corsivi e link in nodi Telegraph"""
        parts = []
        pattern = re.compile(r'(\*\*.*?\*\*|\[.*?\]\(.*?\))')
        tokens = pattern.split(text)
        for token in tokens:
            if not token:
                continue
            if token.startswith('**') and token.endswith('**'):
                parts.append({"tag": "strong", "children": [token[2:-2]]})
            elif token.startswith('[') and token.endswith(')'):
                match = re.match(r'\[(.*?)\]\((.*?)\)', token)
                if match:
                    anchor, link_url = match.groups()
                    parts.append({"tag": "a", "attrs": {"href": link_url}, "children": [anchor]})
                else:
                    parts.append(token)
            else:
                parts.append(token)
        return parts if parts else [text]

    @classmethod
    def markdown_to_nodes(cls, md_text: str) -> List[Dict]:
        """Converte una stringa Markdown standard in nodi JSON validi per Telegraph"""
        nodes = []
        lines = md_text.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            if line_stripped.startswith('# '):
                nodes.append({"tag": "h3", "children": cls.parse_inline_text(line_stripped[2:])})
            elif line_stripped.startswith('## '):
                nodes.append({"tag": "h4", "children": cls.parse_inline_text(line_stripped[3:])})
            elif line_stripped.startswith('### '):
                nodes.append({"tag": "h4", "children": cls.parse_inline_text(line_stripped[4:])})
            elif line_stripped.startswith('---'):
                nodes.append({"tag": "hr"})
            elif line_stripped.startswith('- ') or line_stripped.startswith('* ') or line_stripped.startswith('• '):
                clean_line = re.sub(r'^[\-\*•]\s+', '', line_stripped)
                nodes.append({
                    "tag": "ul",
                    "children": [{"tag": "li", "children": cls.parse_inline_text(clean_line)}]
                })
            elif line_stripped.startswith('> '):
                nodes.append({"tag": "blockquote", "children": cls.parse_inline_text(line_stripped[2:])})
            else:
                nodes.append({"tag": "p", "children": cls.parse_inline_text(line_stripped)})
        return nodes

    @classmethod
    def publish(cls, title: str, md_content: str) -> Optional[str]:
        """Crea una nuova pagina su Telegraph e restituisce l'URL di visualizzazione"""
        token = cls.get_token()
        if not token:
            print("❌ [Telegraph] Impussibile pubblicà: token micca dispunibile.")
            return None
        
        try:
            nodes = cls.markdown_to_nodes(md_content)
            url = "https://api.telegra.ph/createPage"
            payload = {
                "access_token": token,
                "title": title[:256],
                "author_name": "ArcadiaAI",
                "author_url": "https://github.com/Mirko-linux/ArcadiaAI-new",
                "content": json.dumps(nodes),
                "return_content": False
            }
            
            r = REQUESTS_SESSION.post(url, data=payload, timeout=25)
            if r.status_code == 200:
                res = r.json()
                if res.get("ok"):
                    telegraph_url = res["result"].get("url")
                    print(f"✅ [Telegraph] Pubblicazione riuscita: {telegraph_url}")
                    return telegraph_url
                else:
                    print(f"❌ [Telegraph] Errore restituitu da l'API: {res.get('error')}")
            else:
                print(f"❌ [Telegraph] Connessione fallita. Codice HTTP: {r.status_code}")
        except Exception as e:
            print(f"⚠️ [Telegraph] Errore imprevistu durante a pubblicazione: {e}")
        
        return None

# ==================== DEEP RESEARCH ENGINE ====================
DEEP_RESEARCH_CONFIG = {
    "max_sources_free": 8,
    "max_sources_plus": 25,
    "max_sources_pro": 80,
    "max_words_free": 2500,
    "max_words_plus": 6000,
    "max_words_pro": 20000,
    "cache_ttl_hours": 72,
    "max_jobs_per_user": 5,
    "default_timeout_seconds": 180,
    "progress_update_interval": 5,
}

@dataclass
class DeepJob:
    job_id: str
    user_id: int
    chat_id: int
    prompt: str
    plan: str
    status: str = "queued"
    progress: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    report: Optional[str] = None
    pdf_path: Optional[str] = None
    sources_count: int = 0
    error: Optional[str] = None
    message_id: Optional[int] = None

class DeepResearchDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_jobs (
                job_id TEXT PRIMARY KEY,
                user_id INTEGER,
                chat_id INTEGER,
                prompt TEXT,
                plan TEXT,
                status TEXT,
                progress INTEGER DEFAULT 0,
                created_at REAL,
                started_at REAL,
                finished_at REAL,
                report TEXT,
                pdf_path TEXT,
                sources_count INTEGER DEFAULT 0,
                error TEXT,
                message_id INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_cache (
                query_hash TEXT PRIMARY KEY,
                query TEXT,
                results TEXT,
                created_at REAL,
                expires_at REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_stats (
                user_id INTEGER PRIMARY KEY,
                total_jobs INTEGER DEFAULT 0,
                total_sources INTEGER DEFAULT 0,
                last_job_at REAL
            )
        """)

        conn.commit()
        conn.close()

    def save_job(self, job: DeepJob):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO deep_jobs (
                job_id, user_id, chat_id, prompt, plan, status, progress,
                created_at, started_at, finished_at, report, pdf_path,
                sources_count, error, message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.job_id, job.user_id, job.chat_id, job.prompt, job.plan,
            job.status, job.progress, job.created_at, job.started_at,
            job.finished_at, job.report, job.pdf_path,
            job.sources_count, job.error, job.message_id
        ))

        conn.commit()
        conn.close()

    def get_job(self, job_id: str) -> Optional[DeepJob]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM deep_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return DeepJob(
            job_id=row[0],
            user_id=row[1],
            chat_id=row[2],
            prompt=row[3],
            plan=row[4],
            status=row[5],
            progress=row[6],
            created_at=row[7],
            started_at=row[8],
            finished_at=row[9],
            report=row[10],
            pdf_path=row[11],
            sources_count=row[12] or 0,
            error=row[13],
            message_id=row[14] or 0,
        )

    def get_user_jobs(self, user_id: int, limit: int = 20) -> List[DeepJob]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM deep_jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))

        rows = cursor.fetchall()
        conn.close()

        jobs = []
        for row in rows:
            jobs.append(DeepJob(
                job_id=row[0],
                user_id=row[1],
                chat_id=row[2],
                prompt=row[3],
                plan=row[4],
                status=row[5],
                progress=row[6],
                created_at=row[7],
                started_at=row[8],
                finished_at=row[9],
                report=row[10],
                pdf_path=row[11],
                sources_count=row[12] or 0,
                error=row[13],
                message_id=row[14] or 0,
            ))

        return jobs

    def get_active_jobs(self) -> List[DeepJob]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM deep_jobs
            WHERE status IN ('queued', 'planning', 'searching', 'synthesizing', 'factchecking')
            ORDER BY created_at ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        jobs = []
        for row in rows:
            jobs.append(DeepJob(
                job_id=row[0],
                user_id=row[1],
                chat_id=row[2],
                prompt=row[3],
                plan=row[4],
                status=row[5],
                progress=row[6],
                created_at=row[7],
                started_at=row[8],
                finished_at=row[9],
                report=row[10],
                pdf_path=row[11],
                sources_count=row[12] or 0,
                error=row[13],
                message_id=row[14] or 0,
            ))

        return jobs

    def update_progress(self, job_id: str, progress: int, status: str = None):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        if status:
            cursor.execute("""
                UPDATE deep_jobs
                SET progress = ?, status = ?
                WHERE job_id = ?
            """, (progress, status, job_id))
        else:
            cursor.execute("""
                UPDATE deep_jobs
                SET progress = ?
                WHERE job_id = ?
            """, (progress, job_id))

        conn.commit()
        conn.close()

    def mark_done(self, job_id: str, report: str, pdf_path: str = None, sources_count: int = 0):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE deep_jobs
            SET status = 'done', finished_at = ?, report = ?, pdf_path = ?,
                sources_count = ?, progress = 100
            WHERE job_id = ?
        """, (time.time(), report, pdf_path, sources_count, job_id))

        conn.commit()
        conn.close()

    def mark_failed(self, job_id: str, error: str):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE deep_jobs
            SET status = 'failed', error = ?, finished_at = ?
            WHERE job_id = ?
        """, (error, time.time(), job_id))

        conn.commit()
        conn.close()

    def get_cached_search(self, query: str) -> Optional[List[Dict]]:
        query_hash = hashlib.md5(query.lower().encode()).hexdigest()

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT results FROM deep_cache
            WHERE query_hash = ? AND expires_at > ?
        """, (query_hash, time.time()))

        row = cursor.fetchone()
        conn.close()

        if row:
            return json.loads(row[0])
        return None

    def cache_search(self, query: str, results: List[Dict]):
        query_hash = hashlib.md5(query.lower().encode()).hexdigest()
        expires_at = time.time() + (DEEP_RESEARCH_CONFIG["cache_ttl_hours"] * 3600)

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO deep_cache (query_hash, query, results, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (query_hash, query, json.dumps(results), time.time(), expires_at))

        conn.commit()
        conn.close()

    def update_stats(self, user_id: int, sources_count: int):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO deep_stats (user_id, total_jobs, total_sources, last_job_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_jobs = total_jobs + 1,
                total_sources = total_sources + ?,
                last_job_at = ?
        """, (user_id, sources_count, time.time(), sources_count, time.time()))

        conn.commit()
        conn.close()

    def cleanup_old_jobs(self, days: int = 30):
        cutoff = time.time() - (days * 86400)

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM deep_jobs
            WHERE status IN ('done', 'failed', 'cancelled') AND finished_at < ?
        """, (cutoff,))

        cursor.execute("""
            DELETE FROM deep_cache
            WHERE expires_at < ?
        """, (time.time(),))

        conn.commit()
        conn.close()

class DeepPlanner:
    @staticmethod
    def create_plan(prompt: str, plan_level: str = "free") -> Dict:
        max_queries = 6 if plan_level == "free" else 12 if plan_level == "plus" else 25

        system = f"""Sei un ricercatore esperto. Devi creare un piano di ricerca dettagliato per rispondere alla domanda dell'utente.

REGOLE:
- Rispondi SOLO in JSON, nient'altro
- Crea un piano con: titolo, sezioni, query di ricerca, focus
- Genera ESATTAMENTE {max_queries} query di ricerca in italiano
- Le query devono essere specifiche e mirate

FORMATO JSON OBBLIGATORIO:
{{
    "title": "Titolo della ricerca",
    "sections": [
        {{"name": "Nome sezione", "description": "Breve descrizione"}}
    ],
    "queries": [
        "query 1",
        "query 2"
    ],
    "focus": ["parola1", "parola2"]
}}"""

        try:
            response = AIClient.generate(
                f"{system}\n\nDOMANDA: {prompt}",
                max_tok=600 if plan_level == "pro" else 400
            )

            if response:
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"⚠️ Errore nel planner: {e}")

        return {
            "title": f"Analisi approfondita: {prompt[:50]}",
            "sections": [{"name": "Panoramica", "description": "Analisi generale"}],
            "queries": [prompt],
            "focus": ["analisi", "approfondimento"]
        }

class DeepSearchEngine:
    @staticmethod
    def search(query: str, limit: int = 5, use_cache: bool = True) -> List[Dict]:
        if use_cache:
            cached = DEEP_DB.get_cached_search(query)
            if cached:
                print(f"   ✅ [Cache] Query '{query[:50]}...' trovata in cache")
                return cached[:limit]

        results = []

        try:
            web_results = WebSearch.search(query, n=limit)
            for r in web_results:
                results.append({
                    "title": r.get("title", "Senza titolo"),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "source": "web",
                    "relevance": 0.8
                })
            if web_results:
                print(f"   🌐 [Web] Trovati {len(web_results)} risultati per '{query[:50]}...'")
        except Exception as e:
            print(f"   ⚠️ Errore WebSearch per '{query[:50]}...': {e}")

        try:
            wiki_results = DeepSearchEngine._search_wikipedia(query, limit=limit // 2 + 1)
            for r in wiki_results:
                results.append({
                    "title": r.get("title", "Senza titolo"),
                    "url": r.get("url", f"https://it.wikipedia.org/wiki/{r.get('title', '')}"),
                    "snippet": r.get("snippet", ""),
                    "source": "wikipedia",
                    "relevance": 0.9
                })
            if wiki_results:
                print(f"   📚 [Wikipedia] Trovati {len(wiki_results)} risultati per '{query[:50]}...'")
        except Exception as e:
            print(f"   ⚠️ Errore Wikipedia per '{query[:50]}...': {e}")

        try:
            kb_results = DeepSearchEngine._search_knowledge_base(query, limit=limit // 2 + 1)
            for r in kb_results:
                results.append({
                    "title": r.get("file", "Knowledge Base"),
                    "url": "",
                    "snippet": r.get("context", "")[:500],
                    "source": "knowledge_base",
                    "relevance": 0.85
                })
            if kb_results:
                print(f"   📖 [KB] Trovati {len(kb_results)} risultati per '{query[:50]}...'")
        except Exception as e:
            print(f"   ⚠️ Errore KB per '{query[:50]}...': {e}")

        seen = set()
        unique_results = []
        for r in results:
            key = r.get("title", "") + r.get("snippet", "")[:100]
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        if use_cache and unique_results:
            DEEP_DB.cache_search(query, unique_results)

        return unique_results[:limit]

    @staticmethod
    def _search_wikipedia(query: str, limit: int = 3) -> List[Dict]:
        results = []
        try:
            import urllib.request
            import urllib.parse

            encoded = urllib.parse.quote_plus(query)
            url = f"https://it.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json&utf8=1&srlimit={limit}"

            req = urllib.request.Request(
                url, 
                headers={
                    'User-Agent': 'ArcadiaAI/1.0 (https://github.com/Mirko-linux/ArcadiaAI-new)'
                }
            )
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode())

                if "query" in data and "search" in data["query"]:
                    for item in data["query"]["search"]:
                        snippet = re.sub(r'<[^>]+>', '', item.get("snippet", ""))
                        if len(snippet) > 10:
                            results.append({
                                "title": item.get("title", ""),
                                "snippet": snippet,
                                "url": f"https://it.wikipedia.org/wiki/{urllib.parse.quote_plus(item.get('title', ''))}"
                            })

        except Exception as e:
            print(f"   ⚠️ Errore Wikipedia: {e}")

        return results

    @staticmethod
    def _search_knowledge_base(query: str, limit: int = 3) -> List[Dict]:
        try:
            kb = KnowledgeBase(DATA_FOLDER)
            return kb.search(query, max_results=limit)
        except Exception as e:
            print(f"   ⚠️ Errore KB: {e}")
        return []

class DeepFactChecker:
    @staticmethod
    def verify(sources: List[Dict], draft: str) -> Dict:
        if len(sources) < 2:
            return {
                "status": "partial",
                "message": "Poche fonti per una verifica completa",
                "score": 60
            }

        system = """Sei un fact-checker specializzato. Devi verificare l'accuratezza di un rapporto di ricerca.

VERIFICA:
1. Coerenza tra fonti
2. Presenza di contraddizioni
3. Affidabilità delle fonti

Rispondi in JSON:
{
    "status": "ok" | "partial" | "warning" | "error",
    "message": "Spiegazione breve",
    "score": 0-100,
    "issues": ["problema 1", "problema 2"],
    "suggestions": ["suggerimento 1"]
}"""

        sources_summary = "\n".join([
            f"- {s.get('title', 'Senza titolo')} ({s.get('source', 'sconosciuta')}): {s.get('snippet', '')[:200]}"
            for s in sources[:10]
        ])

        text = f"""FONTI:
{sources_summary}

BOZZA:
{draft[:2000]}"""

        try:
            response = AIClient.generate(
                f"{system}\n\n{text}",
                max_tok=400
            )

            if response:
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"⚠️ Errore fact-check: {e}")

        return {
            "status": "partial",
            "message": "Verifica automatica non completa",
            "score": 70,
            "issues": [],
            "suggestions": ["Verifica manualmente le fonti più importanti"]
        }

class DeepSynthesizer:
    @staticmethod
    def build_report(prompt: str, plan: Dict, sources: List[Dict], plan_level: str) -> str:
        max_words = DEEP_RESEARCH_CONFIG["max_words_free"]
        if plan_level == "plus":
            max_words = DEEP_RESEARCH_CONFIG["max_words_plus"]
        elif plan_level == "pro":
            max_words = DEEP_RESEARCH_CONFIG["max_words_pro"]

        system = f"""Sei un analista senior e scrittore professionista. Devi scrivere un rapporto di ricerca completo e di alta qualità.

REGOLE FONDAMENTALI:
- Scrivi SOLO in italiano
- Usa un tono professionale e autorevole
- Struttura il rapporto con titolo, sommario, introduzione, capitoli, analisi, conclusioni, bibliografia
- Usa markdown per la formattazione
- Cita le fonti nel testo con [1], [2], ecc.
- Lunghezza massima: {max_words} parole
- NON includere il ragiunamento, solo il report finale

FORMATO RACCOMANDATO:
# Titolo del Report

## Sommario
Breve riassunto...

## Introduzione
Contesto...

## Capitolo 1: ...
Contenuto...

## Conclusioni
Sintesi...

## Bibliografia
- [1] Titolo, Fonte, URL
"""

        sections_text = "\n".join([
            f"- {s.get('name', 'Sezione')}: {s.get('description', '')}"
            for s in plan.get("sections", [])
        ])

        sources_text = "\n".join([
            f"[{i+1}] {s.get('title', 'Senza titolo')} - {s.get('source', 'sconosciuta')}\n    URL: {s.get('url', 'N/A')}\n    {s.get('snippet', '')[:300]}..."
            for i, s in enumerate(sources[:20])
        ])

        user_prompt = f"""DOMANDA DELL'UTENTE: {prompt}

PIANO DI RICERCA:
{sections_text}

FONTI DISPONIBILI ({len(sources)} fonti):
{sources_text}

Scrivi il report completo basandoti su queste fonti. Mantieni uno stile professionale e strutturato."""

        try:
            report = AIClient.generate(
                f"{system}\n\n{user_prompt}",
                max_tok=min(max_words * 2, 4000)
            )

            if report and len(report) > 100:
                return report
        except Exception as e:
            print(f"⚠️ Errore sintesi: {e}")

        return f"""# Rapporto di Ricerca: {prompt}

## Introduzione
Questa è un'analisi approfondita basata su {len(sources)} fonti disponibili.

## Analisi
{chr(10).join([f"- {s.get('title', 'Fonte')}: {s.get('snippet', '')[:200]}..." for s in sources[:5]])}

## Conclusioni
Le informazioni raccolte forniscono una visione complessiva dell'argomento.

## Bibliografia
{chr(10).join([f"- {s.get('title', 'Fonte')}: {s.get('url', 'N/A')}" for s in sources[:5]])}
"""

class DeepResearchEngine:
    def __init__(self):
        self.running = False
        self.queue = queue.Queue()
        self.worker_thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        print("🧠 Motore Deep Research avviatu!")

    def stop(self):
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)

    def submit_job(self, job: DeepJob) -> str:
        user_jobs = DEEP_DB.get_user_jobs(job.user_id, limit=100)
        active_jobs = [j for j in user_jobs if j.status in ['queued', 'planning', 'searching', 'synthesizing', 'factchecking']]

        if len(active_jobs) >= DEEP_RESEARCH_CONFIG["max_jobs_per_user"]:
            job.status = "failed"
            job.error = f"Troppi job attivi ({len(active_jobs)}/{DEEP_RESEARCH_CONFIG['max_jobs_per_user']})"
            DEEP_DB.save_job(job)
            return job.job_id

        DEEP_DB.save_job(job)
        self.queue.put(job)
        return job.job_id

    def _worker_loop(self):
        while self.running:
            try:
                job = self.queue.get(timeout=1)
                self._process_job(job)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Errore worker Deep Research: {e}")
                time.sleep(1)

    def _process_job(self, job: DeepJob):
        try:
            print(f"🧠 [Deep Research] Avvio job {job.job_id} per l'utente {job.user_id}")

            job.status = "planning"
            job.progress = 5
            job.started_at = time.time()
            DEEP_DB.save_job(job)

            plan = DeepPlanner.create_plan(job.prompt, job.plan)
            job.progress = 15
            DEEP_DB.update_progress(job.job_id, 15)

            job.status = "searching"
            job.progress = 20
            DEEP_DB.update_progress(job.job_id, 20, "searching")

            max_sources = DEEP_RESEARCH_CONFIG["max_sources_free"]
            if job.plan == "plus":
                max_sources = DEEP_RESEARCH_CONFIG["max_sources_plus"]
            elif job.plan == "pro":
                max_sources = DEEP_RESEARCH_CONFIG["max_sources_pro"]

            all_sources = []
            queries = plan.get("queries", [job.prompt])

            total_queries = len(queries)
            for i, query in enumerate(queries):
                if len(all_sources) >= max_sources:
                    break

                limit_per_query = min(3, max_sources - len(all_sources) + 2)
                sources = DeepSearchEngine.search(query, limit=limit_per_query)

                for s in sources:
                    if not any(existing.get("url") == s.get("url") for existing in all_sources):
                        all_sources.append(s)

                progress = 20 + int((i + 1) / total_queries * 35)
                DEEP_DB.update_progress(job.job_id, min(progress, 55))
                time.sleep(0.3)

            job.sources_count = len(all_sources)

            job.status = "synthesizing"
            job.progress = 60
            DEEP_DB.update_progress(job.job_id, 60, "synthesizing")

            draft = DeepSynthesizer.build_report(
                job.prompt,
                plan,
                all_sources,
                job.plan
            )

            job.progress = 80
            DEEP_DB.update_progress(job.job_id, 80)

            job.status = "factchecking"
            job.progress = 85
            DEEP_DB.update_progress(job.job_id, 85, "factchecking")

            fact_check = DeepFactChecker.verify(all_sources[:15], draft)

            report = DeepResearchEngine._finalize_report(draft, fact_check, all_sources, plan)

            title_page = plan.get("title", f"Rapporto Deep Research: {job.prompt[:50]}")
            telegraph_url = TelegraphPublisher.publish(title_page, report)

            job.report = report
            job.status = "done"
            job.finished_at = time.time()
            job.progress = 100
            
            DEEP_DB.mark_done(job.job_id, report, pdf_path=telegraph_url, sources_count=len(all_sources))
            DEEP_DB.update_stats(job.user_id, len(all_sources))

            print(f"✅ [Deep Research] Job {job.job_id} completatu cù {len(all_sources)} fonti")

            if BOT_INSTANCE:
                if telegraph_url:
                    BOT_INSTANCE.send(job.chat_id, f"📊 **Rapportu Deep Research cumpletatu!**\n\n"
                                                   f"🆔 `{job.job_id}`\n"
                                                   f"📝 **Richiesta:** {job.prompt}\n"
                                                   f"📚 **Fonti analizate:** {job.sources_count}\n\n"
                                                   f"📖 **Leghjite u rapportu sanu direttamente nantu à Telegraph:**\n"
                                                   f"🔗 {telegraph_url}")
                else:
                    BOT_INSTANCE.send(job.chat_id, f"📊 **Rapportu Deep Research cumpletatu!**\n\n"
                                                   f"🆔 `{job.job_id}`\n"
                                                   f"Aduprate `/deep_status {job.job_id}` per leghjelu.")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ [Deep Research] Job {job.job_id} fallitu: {error_msg}")
            DEEP_DB.mark_failed(job.job_id, error_msg)
            if BOT_INSTANCE:
                BOT_INSTANCE.send(job.chat_id, f"❌ **Job Deep Research Fallitu!**\n🆔 `{job.job_id}`\nErrore: {error_msg}")

    @staticmethod
    def _finalize_report(draft: str, fact_check: Dict, sources: List[Dict], plan: Dict) -> str:
        reliability = "ALTO"
        if fact_check.get("score", 70) < 60:
            reliability = "MEDIO-BASSO"
        elif fact_check.get("score", 70) < 80:
            reliability = "MEDIO"

        bibliography = []
        for i, s in enumerate(sources[:30]):
            source_type = s.get("source", "web")
            label = {"web": "🌐", "wikipedia": "📚", "knowledge_base": "📖"}.get(source_type, "🔗")
            bibliography.append(
                f"{label} **[{i+1}]** {s.get('title', 'Senza titolo')}\n"
                f"   Fonte: {source_type}\n"
                f"   URL: {s.get('url', 'N/A')}"
            )

        return f"""# 📊 DEEP RESEARCH REPORT

## 📋 Riepilogo
- **Richiesta:** {plan.get('title', 'Analisi approfondita')}
- **Fonti analizzate:** {len(sources)}
- **Livello di affidabilità:** {reliability}
- **Verifica automatica:** {fact_check.get('status', 'parziale')}

---

## 🔍 VERIFICA FATTI
**Stato:** {fact_check.get('status', 'N/A')}
**Punteggio:** {fact_check.get('score', 0)}/100

{fact_check.get('message', 'Verifica completata')}

{chr(10).join(['⚠️ ' + i for i in fact_check.get('issues', [])]) if fact_check.get('issues') else ''}

---

## 📝 RAPPORTO COMPLETO

{draft}

---

## 📚 BIBLIOGRAFIA

{chr(10).join(bibliography)}

---

## ⚖️ Note Metodologiche
- Questo report è stato generato automaticamente da ArcadiaAI Deep Research
- Le informazioni sono state raccolte da fonti multiple e verificate incrociatamente
- Per approfondimenti, consultare le fonti originali elencate in bibliografia
- Data generazione: {datetime.now().strftime('%d/%m/%Y %H:%M')}

---
*ArcadiaAI Deep Research Engine v1.0 - Licenza MPL 2.0*
"""

DEEP_DB = DeepResearchDB(SCRIPT_DIR / "deep_research.db")
deep_engine = DeepResearchEngine()

# ==================== DEEP RESEARCH COMMANDS ====================
class DeepResearchCommands:
    @staticmethod
    def handle_deep_command(bot, chat_id, user_id, args):
        if not args:
            bot.send(chat_id, "🧠 **Deep Research ArcadiaAI Pro**\n\n"
                "Crea rapportu di ricerca prufonda cù fonti verificate.\n\n"
                "**Piani dispunibili:**\n"
                "• `/deep free [dumanda]` - 8 fonti, sin'à 2500 parolle\n"
                "• `/deep plus [dumanda]` - 25 fonti, sin'à 6000 parolle (25 ARC)\n"
                "• `/deep pro [dumanda]` - 80 fonti, sin'à 20000 parolle (50 ARC)\n\n"
                "**Esempiu:** `/deep pro A storia di a Repubblica di Lumenaria`\n\n"
                "**Altri cumandi:**\n"
                "/deep_status [id] - Statu di un job\n"
                "/deep_history - Storicu di i vostri job\n"
                "/deep_cancel [id] - Cancella un job")
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            bot.send(chat_id, "⚠️ ...")
            return

        plan = parts[0].lower()
        prompt = parts[1].strip()

        if plan not in ["free", "plus", "pro"]:
            bot.send(chat_id, "⚠️ Pianu micca validu! Aduprate: free, plus o pro")
            return

        if user_id != DEVELOPER_USER_ID:
            bypass = bot.db.has_active_bypass(user_id)
            if not bypass:
                active = [j for j in DEEP_DB.get_user_jobs(user_id) if j.status in ['queued', 'planning', 'searching', 'synthesizing', 'factchecking']]
                if len(active) >= 2:
                    bot.send(chat_id, f"⏳ Avete digà {len(active)} job in corsu. Attendite o aduprate `/deep_cancel`.")
                    return

        job_id = f"deep_{user_id}_{int(time.time())}_{hashlib.md5(prompt.encode()).hexdigest()[:6]}"
        job = DeepJob(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            prompt=prompt,
            plan=plan,
            status="queued",
            progress=0
        )

        deep_engine.submit_job(job)

        bot.send(chat_id, f"🧠 **Deep Research avviatu!**\n\n"
            f"📋 **Pianu:** {plan.upper()}\n"
            f"📝 **Dumanda:** {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
            f"🆔 **ID Job:** `{job_id}`\n\n"
            f"⏳ Tempu stimatu: { '2-4 minuti' if plan == 'free' else '4-8 minuti' if plan == 'plus' else '8-15 minuti' }\n\n"
            f"Aduprate `/deep_status {job_id}` per cuntrullà u prugressu.")

        return job_id

    @staticmethod
    def handle_deep_status(bot, chat_id, user_id, args):
        job_id = args.strip() if args else None

        if not job_id:
            jobs = DEEP_DB.get_user_jobs(user_id, limit=5)
            if not jobs:
                bot.send(chat_id, "📭 Ùn avete micca fattu alcuna ricerca Deep Research.")
                return

            response = "📊 **I vostri ultimi job:**\n\n"
            for j in jobs[:5]:
                status_emoji = {
                    "queued": "⏳", "planning": "🧠", "searching": "🔍",
                    "synthesizing": "✍️", "factchecking": "✅",
                    "done": "✅", "failed": "❌", "cancelled": "🚫"
                }.get(j.status, "❓")

                response += f"{status_emoji} `{j.job_id}`\n"
                response += f"   📝 {j.prompt[:60]}{'...' if len(j.prompt) > 60 else ''}\n"
                response += f"   📊 Prugressu: {j.progress}%\n"
                response += f"   📋 Pianu: {j.plan.upper()}\n"
                response += f"   🕐 {datetime.fromtimestamp(j.created_at).strftime('%d/%m %H:%M')}\n\n"

            bot.send(chat_id, response)
            return

        job = DEEP_DB.get_job(job_id)

        if not job:
            bot.send(chat_id, f"❌ Job `{job_id}` micca trovu.")
            return

        if job.user_id != user_id and user_id != DEVELOPER_USER_ID:
            bot.send(chat_id, "❌ Ùn avete micca accessu à stu job.")
            return

        if job.status == "done":
            if job.pdf_path and (job.pdf_path.startswith("http://") or job.pdf_path.startswith("https://")):
                bot.send(chat_id, f"📊 **Rapportu Deep Research cumpletatu!**\n\n"
                                  f"🆔 `{job.job_id}`\n"
                                  f"📝 **Richiesta:** {job.prompt}\n"
                                  f"📚 **Fonti analizate:** {job.sources_count}\n\n"
                                  f"📖 **Leghjite u rapportu sanu direttamente nantu à Telegraph:**\n"
                                  f"🔗 {job.pdf_path}")
            else:
                if job.report and len(job.report) > 4000:
                    parts = [job.report[i:i+4000] for i in range(0, len(job.report), 4000)]
                    bot.send(chat_id, f"📊 **Rapportu Deep Research cumpletatu!**\n\n🆔 `{job.job_id}`\n📝 {job.prompt}\n📚 Fonti: {job.sources_count}\n\n")
                    for part in parts:
                        bot.send(chat_id, part)
                    bot.send(chat_id, f"\n📎 Rapportu generatu u {datetime.fromtimestamp(job.finished_at).strftime('%d/%m/%Y %H:%M')}")
                else:
                    bot.send(chat_id, f"📊 **Rapportu Deep Research:**\n\n{job.report}\n\n📚 Fonti: {job.sources_count}")
            return

        if job.status == "failed":
            bot.send(chat_id, f"❌ **Job fallitu:**\n🆔 `{job.job_id}`\nErrore: {job.error}")
            return

        status_messages = {
            "queued": "⏳ In coda...",
            "planning": "🧠 Creazione di u pianu di ricerca...",
            "searching": "🔍 Ricerca di e fonti...",
            "synthesizing": "✍️ Sintesi di u rapportu...",
            "factchecking": "✅ Verifica di i fatti..."
        }

        progress_bar = "█" * (job.progress // 5) + "░" * (20 - job.progress // 5)

        bot.send(chat_id, f"📊 **Statu Deep Research**\n\n"
            f"🆔 `{job.job_id}`\n"
            f"📝 {job.prompt[:100]}{'...' if len(job.prompt) > 100 else ''}\n"
            f"📋 Pianu: {job.plan.upper()}\n"
            f"📊 Prugressu: {job.progress}%\n"
            f"`[{progress_bar}]`\n"
            f"🔄 {status_messages.get(job.status, 'Elaborazione in corsu...')}\n"
            f"📚 Fonti truvate: {job.sources_count}")

    @staticmethod
    def handle_deep_history(bot, chat_id, user_id, args):
        jobs = DEEP_DB.get_user_jobs(user_id, limit=20)

        if not jobs:
            bot.send(chat_id, "📭 Ùn avete micca fattu alcuna ricerca Deep Research.")
            return

        completed = len([j for j in jobs if j.status == "done"])
        total_sources = sum(j.sources_count for j in jobs if j.status == "done")

        response = f"📊 **Storicu Deep Research**\n\n"
        response += f"📋 Totale ricerche: {len(jobs)}\n"
        response += f"✅ Cumpletate: {completed}\n"
        response += f"📚 Fonti totale: {total_sources}\n\n"
        response += "---\n\n"

        for j in jobs[:10]:
            status_emoji = "✅" if j.status == "done" else "⏳" if j.status in ['queued', 'planning', 'searching', 'synthesizing', 'factchecking'] else "❌"
            response += f"{status_emoji} `{j.job_id[:12]}...` - {j.prompt[:50]}{'...' if len(j.prompt) > 50 else ''}\n"
            response += f"   📋 {j.plan.upper()} | {j.sources_count} fonti | {datetime.fromtimestamp(j.created_at).strftime('%d/%m %H:%M')}\n\n"

        bot.send(chat_id, response)

    @staticmethod
    def handle_deep_cancel(bot, chat_id, user_id, args):
        job_id = args.strip() if args else None

        if not job_id:
            active = [j for j in DEEP_DB.get_user_jobs(user_id) if j.status in ['queued', 'planning', 'searching', 'synthesizing', 'factchecking']]
            if not active:
                bot.send(chat_id, "✅ Ùn avete micca job in corsu.")
                return

            response = "📋 **Job in corsu:**\n\n"
            for j in active:
                response += f"• `{j.job_id}` - {j.prompt[:40]}... ({j.progress}%)\n"
            response += "\nAduprate `/deep_cancel [id]` per cancellà ne unu."

            bot.send(chat_id, response)
            return

        job = DEEP_DB.get_job(job_id)

        if not job:
            bot.send(chat_id, f"❌ Job `{job_id}` micca trovu.")
            return

        if job.user_id != user_id and user_id != DEVELOPER_USER_ID:
            bot.send(chat_id, "❌ Ùn avete micca accessu à stu job.")
            return

        if job.status in ["done", "failed", "cancelled"]:
            bot.send(chat_id, f"⚠️ U job `{job_id}` hè digà statu cumpletatu o cancellatu.")
            return

        job.status = "cancelled"
        job.error = "Cancellatu da l'utilizatore"
        DEEP_DB.save_job(job)

        bot.send(chat_id, f"🚫 Job `{job_id}` cancellatu cù successu.")

# ==================== ARCADIA BOT ====================
class ArcadiaBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = MessageDB(SCRIPT_DIR / "processed.db")
        self.loader = FileLoader(DATA_FOLDER)
        self.knowledge = KnowledgeBase(DATA_FOLDER)
        self.deep_db = DeepResearchDB(SCRIPT_DIR / "deep_research.db")
        self.msgs = 0
        self.dups = 0
        self.username = ""
        self.id = 0
        self.short_term_memory = {}
        self.MAX_SHORT_TERM = 10
        
        self.fetch_bot_info()
        gc.collect()

    def api(self, method, params=None):
        if params is None:
            params = {}
        url = f"{self.base_url}/{method}"
        try:
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except:
            return {"ok": False}

    def fetch_bot_info(self):
        r = self.api("getMe")
        if r.get("ok"):
            self.username = r['result'].get('username', '')
            self.id = r['result'].get('id', 0)
            print(f"ℹ️ Info bot caricate à l'avviu: @{self.username} (ID: {self.id})")
        else:
            print("⚠️ Impussibile caricà l'info di u bot durante l'init!")
    
    def test(self):
        r = self.api("getMe")
        if r.get("ok"):
            self.username = r['result'].get('username', '')
            self.id = r['result'].get('id', 0)
            print(f"✅ Bot attivu: @{self.username} (ID: {self.id})")
            return True
        return False
    
    def send(self, chat_id, text):
        if len(text) > 4000:
            text = text[:3990] + "..."
            
        typing_duration = min(len(text) * 0.02 + 0.4, 2.5)
        
        self.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        time.sleep(typing_duration)
        
        return self.api("sendMessage", {"chat_id": chat_id, "text": text})
    
    def send_photo(self, chat_id, url, caption=None):
        p = {"chat_id": chat_id, "photo": url}
        if caption:
            p["caption"] = caption[:1024]
            
        self.api("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"})
        time.sleep(1.2)
        
        return self.api("sendPhoto", p)
        
    def send_photo_file(self, chat_id, photo_path, caption=None):
        url = f"{self.base_url}/sendPhoto"
        self.api("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"})
        try:
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {'chat_id': chat_id}
                if caption:
                    data['caption'] = caption[:1024]
                r = REQUESTS_SESSION.post(url, data=data, files=files, timeout=40)
                return r.json()
        except Exception as e:
            print(f"⚠️ Errore upload foto lucale: {e}")
            return {"ok": False}
    
    def send_video_file(self, chat_id, video_path, caption=None):
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        boundary = f"----FormBoundary{random.randint(100000,999999)}"
        body = []
        body.append(f'--{boundary}'.encode())
        body.append(b'Content-Disposition: form-data; name="chat_id"')
        body.append(b'')
        body.append(str(chat_id).encode())
        body.append(f'--{boundary}'.encode())
        body.append(b'Content-Disposition: form-data; name="video"; filename="video.mp4"')
        body.append(b'Content-Type: video/mp4')
        body.append(b'')
        body.append(video_data)
        if caption:
            body.append(f'--{boundary}'.encode())
            body.append(b'Content-Disposition: form-data; name="caption"')
            body.append(b'')
            body.append(caption[:1024].encode())
        body.append(f'--{boundary}--'.encode())
        data = b'\r\n'.join(body)
        
        del video_data
        gc.collect()
        
        try:
            self.api("sendChatAction", {"chat_id": chat_id, "action": "upload_video"})
            time.sleep(1.5)
            
            req = urllib.request.Request(f"{self.base_url}/sendVideo", data=data,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f"⚠️ Upload: {e}")
            return {"ok": False}
    
    def handle_image(self, chat_id, file_id, caption, user_id):
        try:
            file_info = self.api("getFile", {"file_id": file_id})
            if not file_info.get("ok"):
                self.send(chat_id, "❌ Impussibile ottene u file.")
                return

            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"

            img_temp = TEMP_FOLDER / f"img_{user_id}_{int(time.time())}.jpg"
            
            req = urllib.request.Request(file_url, headers={'User-Agent': 'ArcadiaAI/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(img_temp, 'wb') as f:
                    f.write(resp.read())

            if not img_temp.exists() or img_temp.stat().st_size < 100:
                self.send(chat_id, "❌ U file di l'imagine micca scaricatu currettamente.")
                img_temp.unlink(missing_ok=True)
                return

            if HAS_IMAGE_VIEWER:
                try:
                    viewer = CESImageViewer()
                    raw_description = viewer.analizza(str(img_temp))
                except Exception as e:
                    raw_description = f"❌ Errore durante l'analisi di l'imagine: {str(e)}"
            else:
                raw_description = "❌ CES Image Viewer micca dispunibile."

            if raw_description.startswith("=== CES IMAGE VIEWER"):
                if caption and len(caption) > 0:
                    user_prompt = f"L'utente ha mandato una foto con la didascalia: '{caption}'. Ecco la descrizione tecnica dell'immagine:\n\n{raw_description}"
                else:
                    user_prompt = f"Ecco la descrizione tecnica di un'immagine inviata da un utente. Riscrivila in modo chiaro e amichevole:\n\n{raw_description}"
                
                system_prompt = """Sei un assistente che deve rendere comprensibile una descrizione tecnica di un'immagine. 
                Traduci il linguaggio tecnico in una descrizione chiara, amichevole e scorrevole per un utente normale.
                Mantieni tutti i dettagli importanti ma usa un tono colloquiale e piacevole.
                Se l'utente ha fatto una domanda nella didascalia, rispondi anche a quella.
                RISPOSTA SOLO IN ITALIANO!"""
                
                formatted = AIClient.generate(f"{system_prompt}\n\n{user_prompt}", max_tok=800)
                if formatted:
                    response = formatted
                else:
                    response = raw_description
            else:
                response = raw_description

            self.send(chat_id, response)
            img_temp.unlink(missing_ok=True)

        except urllib.error.URLError as e:
            self.send(chat_id, f"❌ Errore di rete durante u download di l'imagine: {str(e)}")
        except Exception as e:
            self.send(chat_id, f"❌ Errore durante l'analisi di l'imagine: {str(e)}")
            print(f"❌ Errore in handle_image: {e}")
            import traceback
            traceback.print_exc()

    def add_to_short_term_memory(self, user_id, role, content):
        if user_id not in self.short_term_memory:
            self.short_term_memory[user_id] = []
        
        self.short_term_memory[user_id].append({
            "role": role,
            "content": content,
            "timestamp": time.time()
        })
        
        if len(self.short_term_memory[user_id]) > self.MAX_SHORT_TERM:
            self.short_term_memory[user_id] = self.short_term_memory[user_id][-self.MAX_SHORT_TERM:]
    
    def get_short_term_context(self, user_id, limit=5):
        if user_id not in self.short_term_memory:
            return ""
        
        messages = self.short_term_memory[user_id][-limit:]
        context = []
        for msg in messages:
            if msg["role"] == "user":
                context.append(f"Utente: {msg['content']}")
            else:
                context.append(f"ArcadiaAI: {msg['content']}")
        
        return "\n".join(context)
    
    def get_full_context(self, user_id, chat_id, short_limit=5, long_limit=8):
        short_context = self.get_short_term_context(user_id, short_limit)
        long_context = self.db.get_conversation_context(user_id, chat_id, long_limit)
        
        if short_context and long_context:
            return f"{long_context}\n\n{short_context}"
        elif short_context:
            return short_context
        elif long_context:
            return long_context
        else:
            return ""
    
    def clear_memory(self, user_id, chat_id):
        if user_id in self.short_term_memory:
            self.short_term_memory[user_id] = []
        self.db.clear_memory(user_id, chat_id)
        return True
    
    def handle_ces360(self, chat_id, prompt):
        if not HF_TOKEN:
            self.send(chat_id, "❌ **Token Hugging Face micca cunfiguratu!**\n\n"
                "Per utilizà /ces-360 deve cunfigurà u token in u schedariu `.env`:\n"
                "`HUGGINGFACE_TOKEN=tuo_token_qui`\n\n"
                "Pò ottene un token gratuitu nantu à https://huggingface.co/settings/tokens")
            return
        
        if not prompt:
            self.send(chat_id, "⚠️ **Scrivi una domanda dopo il comando!**\n\n"
                "Esempio: `/ces-360 Spiegami cos'è Lumenaria`")
            return
        
        self.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        
        payload = {
            "inputs": f"User: {prompt}\nAssistant:",
            "parameters": {
                "max_new_tokens": 512,
                "temperature": 0.7,
                "do_sample": True,
                "top_p": 0.95
            }
        }
        
        try:
            print(f"🤖 [CES-360] Richiesta API per: {prompt[:80]}...")
            
            import urllib.request
            import json
            import ssl
            
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
            
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {HF_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "ArcadiaAI/1.0"
                },
                method='POST'
            )
            
            print(f"   ⏳ Invio richiesta a Hugging Face...")
            
            with urllib.request.urlopen(req, timeout=60, context=context) as r:
                j = json.loads(r.read().decode())
                
                if isinstance(j, list) and len(j) > 0:
                    text_resp = j[0].get("generated_text", "")
                elif isinstance(j, dict):
                    text_resp = j.get("generated_text", "")
                else:
                    text_resp = str(j)
                
                if text_resp.startswith(payload["inputs"]):
                    text_resp = text_resp[len(payload["inputs"]):].strip()
                elif text_resp.startswith(prompt):
                    text_resp = text_resp[len(prompt):].strip()
                    
                if not text_resp:
                    text_resp = "⚠️ Il modello ha generato una risposta vuota. Riprova riformulando la domanda."
                
                self.send(chat_id, f"🧠 **CES-360:**\n\n{text_resp}")
                print(f"   ✅ Risposta inviata con successo.")
                
        except urllib.error.HTTPError as e:
            if e.code == 503:
                self.send(chat_id, "⏳ **Il modello si sta svegliando sui server di Hugging Face...**\n\n"
                    "Dato che la risorsa gratuita è in modalità di risparmio energetico, "
                    "potrebbe volerci da **1 a 3 minuti** per caricarlo in memoria.\n\n"
                    "🔄 *Riprova tra circa un minuto!*")
                print(f"   ⏳ Server in standby (503).")
            elif e.code in [401, 403]:
                self.send(chat_id, "🔑 **Errore di autenticazione con Hugging Face**\n\n"
                    "Il tuo token HUGGINGFACE_TOKEN nel file `.env` non è corretto o non ha i permessi di lettura per questo modello.")
                print(f"   ❌ Token non valido (Stato: {e.code}).")
            else:
                self.send(chat_id, f"❌ Errore HTTP {e.code} virus la richiesta.")
                print(f"   ❌ Errore HTTP: {e}")
                
        except urllib.error.URLError as e:
            if "getaddrinfo" in str(e):
                self.send(chat_id, "🌐 **Errore DNS - Impossible risolvere il nome del server.**\n\n"
                    "Il tuo sistema non riesce a contattare i server di Hugging Face.\n\n"
                    "**Soluzioni:**\n"
                    "• Controlla la tua connessione internet\n"
                    "• Prova a cambiare DNS (es. 1.1.1.1 o 8.8.8.8)\n"
                    "• Riprova tra qualche minuto")
                print(f"   ❌ Errore DNS: {e}")
            else:
                self.send(chat_id, f"🌐 **Errore di rete:** {str(e)[:100]}")
                print(f"   ❌ Errore di rete: {e}")
                
        except Exception as e:
            self.send(chat_id, f"❌ Errore imprevisto: {str(e)[:200]}")
            print(f"   ❌ Errore generale: {e}")

    # ==================== FUNZIONI ASINCRONE IN BACKGROUND (THREAD) ====================
    def _generate_img_plus_bg(self, chat_id, user_id, p, tier, count, limit):
        """Esegue la generazione dell'immagine HD in un thread separato per non bloccare mai il bot"""
        try:
            r = CESImagePlus.generate(p)
            if r["success"]:
                self.db.record_image_generation(user_id)
                new_count = count + 1
                limit_text = f"{new_count}/{limit}" if limit > 0 else f"{new_count}/Illimitati"
                
                caption_label = "🎨 [FLUX HD - Emergenza Fallback]" if r.get("fallback") else "🎨 [FLUX HD]"
                caption_msg = f"{caption_label} {r['prompt'][:200]}\n\n📊 Limite giornaliero: {limit_text}"
                
                sent = self.send_photo_file(chat_id, str(r["image_path"]), caption_msg)
                if not sent.get("ok"):
                    self.send(chat_id, "❌ Impossibile inviare l'immagine generata.")
                try:
                    Path(r["image_path"]).unlink(missing_ok=True)
                except Exception as e:
                    print(f"⚠️ Impossibile rimuovere il file temporaneo: {e}")
            else:
                self.send(chat_id, f"⚠️ {r['error']}")
        except Exception as e:
            self.send(chat_id, f"❌ Errore imprevisto durante la generazione: {e}")

    def _generate_video_bg(self, chat_id, user_id, prompt, style):
        """Esegue la generazione del video in un thread separato per non bloccare mai il bot"""
        try:
            self.send(chat_id, f"🎥 Genero video {style}...\n⏳ Elaborazione fluida in corso...")
            result = CESVideo.generate_video(prompt=prompt, style=style)
            
            if result["success"]:
                self.db.mark_video_generated(user_id)
                count = self.db.get_video_count(user_id)
                caption = f"🎬 {result['generated_narration']}\n🎥 {style} | #{count}"
                
                video_result = self.send_video_file(chat_id, result["video_path"], caption)
                if not video_result.get("ok"):
                    size_kb = result["video_path"].stat().st_size / 1024
                    self.send(chat_id, f"⚠️ Video troppo grande ({size_kb:.0f}KB). Riprova.")
                
                try:
                    shutil.rmtree(result["video_path"].parent)
                except:
                    pass
                gc.collect()
            else:
                self.send(chat_id, f"⚠️ {result['error']}")
        except Exception as video_err:
            self.send(chat_id, f"❌ Errore imprevisto durante l'elaborazione del video: {str(video_err)}")
        finally:
            video_limiter.finish(user_id)

    def process_update(self, update):
        update_id = update.get("update_id", 0)
        if self.db.is_processed(update_id):
            self.dups += 1
            return
        if "message" not in update:
            return
        
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        chat_type = msg["chat"].get("type", "private")
        user_id = msg["from"]["id"]
        msg_date = msg.get("date", 0)
        user_name = msg["from"].get("first_name", "Utente")
        
        self.db.mark(update_id, chat_id, user_id, msg_date)
        self.msgs += 1
        
        text = msg.get("text", "").strip()
        
        # Guardrail preventivo locale per l'intero messaggio prima delle elaborazioni
        if text:
            is_sensitive, category = PrivacyGuard.check_sensitive_data(text)
            if is_sensitive:
                self.send(chat_id, f"⚠️ **Blocco di Sicurezza Privacy (Locale)**\n\n"
                                  f"La tua richiesta è stata bloccata localmente sul nostro server e non è stata inviata alle API esterne.\n"
                                  f"**Rilevamento:** Dati particolari / sensibili ({category}).\n\n"
                                  f"ArcadiaAI non elabora dati sensibili o intimi per tutelare appieno la riservatezza e la sicurezza dei propri utenti.")
                return

        # ==================== DEEP RESEARCH COMMANDS ====================
        if text:
            if text.startswith("/deep "):
                args = text[5:].strip()
                print(f"🧠 [DEEP] Comando /deep riconosciuto! Args: '{args}'")
                
                if not args:
                    DeepResearchCommands.handle_deep_command(self, chat_id, user_id, "")
                    return
                
                first_arg = args.split()[0].lower() if args.split() else ""
                if first_arg in ["free", "plus", "pro"]:
                    DeepResearchCommands.handle_deep_command(self, chat_id, user_id, args)
                else:
                    DeepResearchCommands.handle_deep_command(self, chat_id, user_id, f"free {args}")
                return
            
            elif text.startswith("/deep_status"):
                args = text[12:].strip()
                DeepResearchCommands.handle_deep_status(self, chat_id, user_id, args)
                return
            
            elif text.startswith("/deep_history"):
                args = text[13:].strip()
                DeepResearchCommands.handle_deep_history(self, chat_id, user_id, args)
                return
            
            elif text.startswith("/deep_cancel"):
                args = text[13:].strip()
                DeepResearchCommands.handle_deep_cancel(self, chat_id, user_id, args)
                return
            
            elif text.strip() == "/deep":
                DeepResearchCommands.handle_deep_command(self, chat_id, user_id, "")
                return
        
        if "photo" in msg:
            photo = msg["photo"][-1]
            file_id = photo["file_id"]
            caption = msg.get("caption", "").strip()

            if not caption or any(k in caption.lower() for k in ["analizza", "immagine", "foto", "vedi", "descrivi", "guarda", "che foto", "come sono"]):
                self.handle_image(chat_id, file_id, caption, user_id)
                return
        
        if not text:
            return
        
        self.add_to_short_term_memory(user_id, "user", text)
        self.db.save_conversation(user_id, chat_id, "user", text)
        
        is_group = chat_type in ["group", "supergroup"]
        bot_username = self.username.lower() if self.username else ""

        registered_commands = [
            "/start", "/aiuto", "/help", "/videohelp", "/video",
            "/codice_sorgente", "/buy_bypass", "/create_vip",
            "/redeem", "/img", "/img_plus", "/imgplus", "/stats", "/cerca",
            "/vip_status", "/my_vip_codes", "/ai", "/alias_test",
            "/clear_memory", "/cancella_memoria", "/reset_memory", "/memoria",
            "/ces-360", "/aggiorna_giornale", "/pdf"
        ]
        
        proc_text = text
        
        if bot_username:
            proc_text = re.sub(r'(?i)@' + re.escape(bot_username), '', proc_text).strip()
            proc_text = re.sub(r'(/\w+)@' + re.escape(bot_username), r'\1', proc_text, flags=re.IGNORECASE)
        
        first_word = proc_text.split()[0].lower() if proc_text else ""
        is_command = first_word in registered_commands
        is_mentioned = bot_username and f"@{bot_username}" in text.lower()
        
        print(f"📥 [{chat_type.upper()}] Messaggio da {user_name} (ID: {user_id}): '{text}'")
        print(f"   ↳ Processato: '{proc_text}' | first_word: '{first_word}'")
        
        if is_command:
            print(f"   ↳ ✅ Riconosciuto come comando: {first_word}")
        if is_mentioned:
            print(f"   ↳ ✅ Taggato: @{bot_username}")
            
        if is_group:
            if not (is_command or is_mentioned):
                print("   ↳ 🚫 Ignorato (Nessun comando o tag nei gruppi).")
                return

        ai_query = proc_text
        
        if first_word == "/ai":
            ai_query = proc_text[3:].strip()
            if not ai_query:
                self.send(chat_id, "💬 Cosa vuoi chiedermi? Usa `/ai <domanda>`")
                return
        
        if first_word == "/ces-360":
            prompt = proc_text[8:].strip()
            self.handle_ces360(chat_id, prompt)
            return
        
        if bot_username:
            ai_query = re.sub(r'(?i)@' + re.escape(bot_username), '', ai_query).strip()
        
        ai_query = re.sub(r'\s+', ' ', ai_query).strip()
        
        if first_word in ["/memoria", "/memory"]:
            status = self.db.get_memory_status(user_id, chat_id)
            short_count = len(self.short_term_memory.get(user_id, []))
            self.send(chat_id, f"🧠 **Stato Memoria ArcadiaAI**\n\n"
                f"**💾 Memoria a breve termine (RAM):**\n"
                f"   • Messaggi: {short_count}/{self.MAX_SHORT_TERM}\n\n"
                f"**💿 Memoria a lungo termine (Database):**\n"
                f"   • Messaggi: {status['count']}\n"
                f"   • Ultimo messaggio: {status['last_message']}\n\n"
                f"📌 Usa `/clear_memory` per cancellare tutta la memoria.")
            return
        
        if first_word in ["/clear_memory", "/cancella_memoria", "/reset_memory"]:
            self.clear_memory(user_id, chat_id)
            self.send(chat_id, "🧹 **Memoria cancellata!**\n\n"
                "Ho cancellato tutte le mie memorie su di te.\n"
                "Non ricorderò più le conversazioni precedenti.")
            return

        # ==================== GESTIONE DEL COMANDO /pdf CORRETTO E ALLINEATO ====================
        if first_word == "/pdf":
            prompt_utente = proc_text[4:].strip()
            
            if not prompt_utente:
                self.send(chat_id, "Fornisce un argumentu per u PDF! 📝\nEs: `/pdf A storia di l'urdinatori`")
                return

            if not HAS_PDF_GENERATOR:
                self.send(chat_id, "❌ Serviziu di generazione PDF micca dispunibile per u mumentu.")
                return

            msg_attesa = self.send(chat_id, "🔍 Elaburazione di u testu è impaginazione di u PDF in corsu...")
            msg_id = msg_attesa.get("result", {}).get("message_id") if msg_attesa and msg_attesa.get("ok") else None

            try:
                testo_ia = AIClient.generate(prompt_utente, max_tok=1500)
                if not testo_ia:
                    testo_ia = "Ùn aghju micca pussutu generà u testu."

                generator = ArcadiaPDFGenerator()
                titolo_pdf = f"Report: {prompt_utente[:35]}..."
                pdf_buffer = generator.build_pdf_buffer(testo_ia, title=titolo_pdf)

                token_bot = os.getenv("TELEGRAM_BOT_TOKEN") or self.token

                nome_file = f"Report_{int(time.time())}.pdf"
                successo = send_pdf_to_telegram(
                    chat_id=chat_id,
                    pdf_buffer=pdf_buffer,
                    file_name=nome_file,
                    caption=f"📄 Eccu u vostru ducumentu PDF generatu per: *{prompt_utente}*",
                    token=token_bot
                )

                if successo:
                    if msg_id:
                        self.api("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})
                else:
                    self.send(chat_id, "❌ Ci hè statu un errore durante l'inviu di u ducumentu PDF.")

            except Exception as e:
                self.send(chat_id, f"❌ Errore durante a creazione di u PDF: {str(e)}")
            return

        # ==================== COMANDO MANUALE SINCRONIZZAZIONE GIORNALE ====================
        if first_word == "/aggiorna_giornale":
            self.send(chat_id, "📰 **Sincronizzazione in corso...**\n"
                              "Sto scaricando gli articoli più recenti da Leonia+ (@leoniaplusgiornale) senza alcun consumo di risorse.")
            success = LeoniaPlusUpdater.scrape_channel()
            if success:
                self.knowledge.reload()
                self.send(chat_id, "✅ **Database Aggiornato!**\n"
                                  "Gli articoli di Leonia+ sono stati assimilati nella mia conoscenza locale. Ora sono aggiornato sugli ultimi avvenimenti micronazionali!")
            else:
                self.send(chat_id, "⚠️ **Sincronizzazione Fallita**\n"
                                  "Non sono riuscito a raggiungere Telegram per scaricare il feed. Riprova più tardi.")
            return
        
        if first_word == "/start":
            dev = "🔓 Dev" if user_id == DEVELOPER_USER_ID else ""
            self.send(chat_id, f"👋 Ciao {user_name}! Sono ArcadiaAI.\n\n"
                "🧠 **Ho una memoria potenziata!**\n"
                "Ricordo le conversazioni sia a breve che a lungo termine.\n\n"
                "🛡️ *Privacy Guard attivo sul server localmente!*\n\n"
                "📰 /aggiorna_giornale - Forza l'aggiornamento da Leonia+\n"
                "📄 /pdf [argomento] - Genera un documento PDF professionale\n"
                "🎬 /video [desc] - Video AI diretto\n"
                "🎨 /img [desc] - Immagine standard\n"
                "🎨 /img_plus [desc] - Immagine HD (FLUX)\n"
                "🧠 /ces-360 [domanda] - Modello CES-360 su Hugging Face\n"
                "🧠 /deep [piano] [domanda] - Deep Research avanzato\n"
                "🎫 /vip [codice] - Riscatta codice VIP\n"
                "🖼️ Invia una foto con 'analizza' per descriverla\n"
                "💬 Fammi una domanda!\n"
                "🧠 /memoria - Stato memoria\n"
                "🧹 /clear_memory - Cancellazione memoria\n"
                f"📋 /aiuto{(' ' + dev) if dev else ''}")
            return
        
        if first_word in ["/aiuto", "/help"]:
            self.send(chat_id, "🎬 **Comandi ArcadiaAI**\n\n"
                "📰 /aggiorna_giornale - Sincronizza notizie da @leoniaplusgiornale\n"
                "📄 /pdf [argomento] - Crea un documento PDF professionale\n"
                "🎬 /video [stile] [descrizione] - Video AI\n"
                "🎨 /img [desc] - Immagine standard\n"
                "🎨 /img_plus [desc] - Immagine ad alta definizione (FLUX)\n"
                "🧠 /ces-360 [domanda] - Modello CES-360 su Hugging Face\n"
                "🧠 /deep [piano] [domanda] - Deep Research avanzato\n"
                "🖼️ Invia una foto con 'analizza' per descriverla\n"
                "🎫 /vip [codice] - Riscatta codice VIP\n"
                "👨‍💻 /codice_sorgente - Link alla repository\n"
                "📝 /telegraph [tema] - Articolo\n"
                "🔍 /cerca [q] - Web\n"
                "🏦 /buy_bypass - Bypass limiti\n"
                "📊 /stats - Statistiche\n\n"
                "**🧠 Memoria:**\n"
                "/memoria - Stato memoria\n"
                "/clear_memory - Cancella memoria\n\n"
                "**Deep Research:**\n"
                "/deep free [domanda] - Ricerca base (gratis)\n"
                "/deep plus [domanda] - Ricerca avanzata (25 ARC)\n"
                "/deep pro [domanda] - Ricerca professionale (50 ARC)\n"
                "/deep_status [id] - Stato job\n"
                "/deep_history - Storico\n\n"
                "**VIP:**\n"
                "/vip_status - Stato VIP\n"
                "/my_vip_codes - I tuoi codici (Dev)\n\n"
                "💬 Fammi una domanda su micronazioni, Leonia, Arcadia, Lumenaria!\n\n"
                "📌 **Per farmi una domanda in un gruppo:**\n"
                "• Usa `/ai <domanda>`\n"
                f"• Oppure taggami scrivendo `@{self.username} <domanda>`")
            return
        
        if first_word == "/videohelp":
            self.send(chat_id, "🎬 **CES Video** - Text-to-Video Diretto\n\n"
                "/video [stile] [descrizione]\n"
                "Stili: cinematic, anime, realistic, artistic\n\n"
                "1 video ogni 15 min (gratuito)\n"
                "🎫 /vip per codici promozionali\n"
                "🏦 /buy_bypass per illimitati")
            return
        
        if first_word == "/alias_test":
            if not WIKIALIAS:
                self.send(chat_id, "⚠️ **Nessun alias caricato!**\n\n"
                    "Verifica che il file `wikialias.json` esista nella stessa cartella di ESEMPIO.py")
                return
            
            test_text = "Salvatore Giordano ha fondato Lumenaria? No, è stato Filippo Zanetti! E Mirko Yuri Donato ha scritto La Storia di Lumenaria."
            aliased = AliasResolver.apply_aliases_to_text(test_text)
            restored = AliasResolver.restore_real_names_to_text(aliased)
            mapping = "\n".join([f"  🔒 {alias} -> {real_name}" for alias, real_name in WIKIALIAS.items() if alias != real_name])
            
            self.send(chat_id, f"🔀 **Test Sistema Alias (Privacy-First)**\n\n"
                f"**📝 Testo Originale:**\n{test_text}\n\n"
                f"**🔒 Testo con Alias (inviato all'API):**\n{aliased}\n\n"
                f"**🔓 Testo Restituito (nomi reali):**\n{restored}\n\n"
                f"**📋 Mappatura Alias attuale ({len(WIKIALIAS)} alias):**\n{mapping}")
            return
        
        if first_word == "/ai":
            if not ai_query:
                return
            
            print(f"   🤖 Query AI: '{ai_query}'")
            self.send(chat_id, "🔍 Cerco nelle mie conoscenze...")
            context = self.get_full_context(user_id, chat_id, short_limit=5, long_limit=8)
            search_results = self.knowledge.search(ai_query, max_results=10)
            
            if search_results:
                context_parts = []
                for r in search_results[:5]:
                    context_parts.append(f"📖 Da {r['file']}:\n{r['context']}")
                knowledge_context = "\n\n".join(context_parts)
                print(f"✅ Trovati {len(search_results)} risultati rilevanti per la query.")
            else:
                knowledge_context = "Nessun risultato trovato nei file di conoscenza."
                print(f"⚠️ Nessun risultato utile.")
            
            system = f"""{IDENTITY_PROMPT}

**CONTESTO DELLA CONVERSAZIONE (messaggi precedenti):**
{context if context else "Nessuna conversazione precedente."}

**CONOSCENZA DAI FILE LOCALI:**
{knowledge_context}

**REGOLA FONDAMENTALE DI RISPOSTA:**
- Se l'informazione è presente nel testo qui sopra, usala obbligatoriamente per rispondere in modo preciso e dettagliato.
- Se l'informazione non è presente, usa la tua conoscenza predefinita o cerca nel web.
- CITA LA FONTE (il nome del file .txt) esclusivamente una sola volta in fondo alla risposta, formattata come `[Fonte: nome_file.txt]`.

**DOMANDA DELL'UTENTE:**
{ai_query}

**RISPOSTA (SOLO IN ITALIANO, DIRETTA):**"""
            
            answer = AIClient.generate(system, max_tok=1200)
            if answer:
                self.add_to_short_term_memory(user_id, "assistant", answer)
                self.db.save_conversation(user_id, chat_id, "assistant", answer)
                self.send(chat_id, answer.strip())
            return
        
        if first_word == "/video":
            args = proc_text[6:].strip()
            if not args:
                self.send(chat_id, "🎬 /video [stile] [descrizione]\nStili: cinematic, anime, realistic, artistic")
                return
            
            can_process, message, pos = video_limiter.can_process(user_id, self.db)
            if not can_process:
                self.send(chat_id, message)
                return
            
            styles = ["cinematic", "anime", "realistic", "artistic"]
            style = "cinematic"
            prompt = args
            first_word_arg = args.split()[0].lower() if args.split() else ""
            if first_word_arg in styles:
                style = first_word_arg
                prompt = ' '.join(args.split()[1:])
            
            if not prompt:
                self.send(chat_id, "🎬 Descrivi la scena!")
                video_limiter.finish(user_id)
                return
            
            threading.Thread(target=self._generate_video_bg, args=(chat_id, user_id, prompt, style), daemon=True).start()
            return
        
        if first_word == "/codice_sorgente":
            self.send(chat_id, "📂 Codice sorgente: https://github.com/Mirko-linux/ArcadiaAI-new")
            return
        
        if first_word == "/buy_bypass":
            prices = "\n".join([f"• {i['name']}: {i['arc']} ARC" for i in BYPASS_PRICES.values()])
            self.send(chat_id, f"👋 Scegli come supportarci:\n\n{prices}\n\nUsa /buy_bypass [nome] per procedere!")
            return
        
        if first_word == "/create_vip":
            if user_id != DEVELOPER_USER_ID:
                self.send(chat_id, "❌ Solo lo sviluppatore può creare codici VIP.")
                return
            
            parts = proc_text[11:].strip().split()
            if len(parts) < 2:
                self.send(chat_id, "🎫 **Crea Codice VIP**\n\n/create_vip [ore] [codice] [max_usi]")
                return
            
            try:
                hours = int(parts[0])
                code = parts[1].upper()
                max_uses = int(parts[2]) if len(parts) > 2 else 1
                self.db.create_vip_code(code, f"PROMO_{hours}H", hours, user_id, max_uses)
                self.send(chat_id, f"🎟️ Codice VIP Creato:\nCodice: `{code}`\nDurata: {hours} ore\nUsi Massimi: {max_uses}")
            except Exception as e:
                self.send(chat_id, f"❌ Errore durante la creazione: {str(e)}")
            return
        
        if_word = "/redeem"
        if first_word == "/redeem":
            code = proc_text[7:].strip().upper()
            if not code:
                self.send(chat_id, "🎟️ Specifica il codice da riscattare! Usa `/redeem CODICE`")
                return
            
            plan, message = self.db.redeem_vip_code(code, user_id)
            if plan:
                self.send(chat_id, message)
            else:
                self.send(chat_id, f"❌ {message}")
            return
        
        if first_word in ["/img_plus", "/imgplus"]:
            p = proc_text[10:].strip() if first_word == "/img_plus" else proc_text[8:].strip()
            print(f"   ↳ [ROUTING] Comando /img_plus intercettato correttamente! Prompt estratto: '{p}'")
            
            if not p:
                self.send(chat_id, "⚠️ **Scrivi una descrizione dopo il comando!**\n\nEsempio: `/img_plus a futuristic city with neon lights`")
                return

            allowed, tier, count, limit = self.db.check_image_limit(user_id)
            if not allowed:
                self.send(chat_id, f"⚠️ **Limite giornaliero raggiunto!**\n\n"
                                  f"Il tuo account **{tier.upper()}** consente un massimo di {limit} immagini al giorno.\n"
                                  f"Hai già generato {count}/{limit} immagini HD nelle ultime 24 ore.\n\n"
                                  f"🏦 Puoi bypassare i limiti o attendere il reset giornaliero.")
                return

            limit_label = f"{count + 1}/{limit}" if limit > 0 else f"{count + 1}/Illimitati"
            self.send(chat_id, f"🎨 Genero immagine HD con FLUX (Inference API)... ⏳\n"
                              f"📊 Account: {tier.upper()} ({limit_label})")
            
            threading.Thread(target=self._generate_img_plus_bg, args=(chat_id, user_id, p, tier, count, limit), daemon=True).start()
            return

        if first_word == "/img":
            p = proc_text[4:].strip()
            if p:
                r = CESImage.generate(p)
                if r["success"]:
                    self.send_photo(chat_id, r["image_url"], f"🎨 {r['prompt'][:200]}")
                else:
                    self.send(chat_id, f"⚠️ {r['error']}")
            return
            
        if first_word == "/stats":
            mem = self._mem()
            self.send(chat_id, f"💬 {self.msgs} | 🤖 {AIClient.count} | 🎨 {CESImage.count} | {CESVideo.count} | 🧠 {mem:.1f}MB")
            return
        
        if first_word == "/cerca":
            query = proc_text[7:].strip()
            if not query:
                self.send(chat_id, "🔍 /cerca [argomento] - Cosa vuoi cercare?")
                return
                
            self.send(chat_id, f"🔍 Cerco '{query}'...")
            raw_results = WebSearch.search(query, n=4)
            if not raw_results:
                self.send(chat_id, "❌ Nessun risultato trovato sul web.")
                return
                
            context_parts = []
            urls = []
            for i, r in enumerate(raw_results, 1):
                context_parts.append(f"Fonte {i}: {r['title']} - {r['snippet']}")
                urls.append(f"- {r['url']}")
                
            search_context = "\n".join(context_parts)
            synthesis_prompt = (
                f"Sei un assistente di ricerca. Basandoti sui risultati web, fornisci una risposta "
                f"sintetica alla domanda: '{query}'. Cita le fonti usando [1], [2].\n\n"
                f"RISULTATI WEB:\n{search_context}\n\nRISPOSTA SINTETICA:"
            )
            
            answer = AIClient.generate(synthesis_prompt, max_tok=400)
            if answer:
                final_msg = f"🔍 **Risultati per '{query}':**\n\n{answer.strip()}\n\n📎 Fonti:\n" + "\n".join(urls[:3])
                self.send(chat_id, final_msg)
            else:
                msg = f"🔍 Risultati per '{query}':\n\n"
                for r in raw_results:
                    msg += f"• {r['title']}\n  {r['snippet'][:150]}...\n  🔗 {r['url']}\n\n"
                self.send(chat_id, msg[:4000])
            return

        if not ai_query:
            if is_group:
                self.send(chat_id, f"Ciao {user_name}! Per farmi una domanda usa il comando `/ai <domanda>` oppure taggami scrivendo `@{self.username} <domanda>`.")
            return

        predefined = get_predefined_response(ai_query)
        if predefined:
            self.send(chat_id, predefined)
            return
        
        self.send(chat_id, "🔍 Cerco nelle mie conoscenze...")
        context = self.get_full_context(user_id, chat_id, short_limit=5, long_limit=8)
        search_results = self.knowledge.search(ai_query, max_results=10)
        
        if search_results:
            context_parts = []
            for r in search_results[:5]:
                context_parts.append(f"📖 Da {r['file']}:\n{r['context']}")
            knowledge_context = "\n\n".join(context_parts)
            print(f"✅ Trovati {len(search_results)} risultati rilevanti per: {ai_query}")
        else:
            knowledge_context = "Nessun risultato trovato nei file di conoscenza."
            print(f"⚠️ Nessun risultato utile per: {ai_query}")
        
        system = f"""{IDENTITY_PROMPT}

**CONTESTO DELLA CONVERSAZIONE (messaggi precedenti):**
{context if context else "Nessuna conversazione precedente."}

**CONOSCENZA DAI FILE LOCALI:**
{knowledge_context}

**REGOLA FONDAMENTALE DI RISPOSTA:**
- Se l'informazione è presente nel testo qui sopra, usala obbligatoriamente per rispondere in modo preciso e dettagliato.
- Se l'informazione non è presente nel testo, usa la tua conoscenza predefinita se ritieni sia affidabile, altrimenti dillo chiaramente.
- CITA LA FONTE (il nome del file .txt) esclusivamente una sola volta in fondo alla risposta, formattata come `[Fonte: nome_file.txt]`.

**DOMANDA DELL'UTENTE:**
{ai_query}

**RISPOSTA (SOLO IN ITALIANO, DIRETTA, SENZA RAGIONAMENTO):**"""
        
        answer = AIClient.generate(system, max_tok=1200)
        
        if answer:
            self.add_to_short_term_memory(user_id, "assistant", answer)
            self.db.save_conversation(user_id, chat_id, "assistant", answer)
            self.send(chat_id, answer.strip())
        else:
            self.send(chat_id, "🌐 Cerco su internet...")
            raw_results = WebSearch.search(ai_query, n=4)
            if raw_results:
                msg = f"🔍 Risultati per '{ai_query}':\n\n"
                for r in raw_results:
                    msg += f"• {r['title']}\n  {r['snippet'][:150]}...\n  🔗 {r['url']}\n\n"
                self.send(chat_id, msg[:4000])
            else:
                self.send(chat_id, "❌ Non ho trovato informazioni su questo argomento.")
        
        if self.msgs % 10 == 0:
            gc.collect()
            self.db.cleanup()
            
    def _mem(self):
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except:
            return -1
    
    def run_polling(self):
        print("\n" + "="*60)
        print("🤖 ArcadiaAI - Versione con CES-360 su Hugging Face")
        print("🧠 Modello CES-360: mirkodonato08/CES-360")
        print("🧠 Deep Research Engine attivo!")
        print("📊 Piani: free (8 fonti), plus (25 fonti), pro (80 fonti)")
        print("🤖 Gemini multi-fallback: gemini-2.5-flash, gemini-2.5-pro, gemini-2.5-flash-lite")
        print("🎨 Modello HD Image: FLUX.1-schnell (Inference API con fallback DoH)")
        print("💾 I messaggi NON vengono persi quando il bot è spento!")
        print("🔒 I nomi reali NON vengono mai inviati alle API!")
        print("🖼️ Analisi immagini con CES Image Viewer integrata")
        print("📌 /ai funziona in gruppi e supergruppi!")
        print("🔧 /alias_test per testare il sistema")
        print("🧠 /memoria per vedere lo stato della memoria")
        print("🧹 /clear_memory per cancellare la memoria")
        print("🧠 /ces-360 per interrogare il modello CES-360")
        print("🎨 /img_plus per generare immagini ad alta definizione")
        print("📰 Collegamento asincrono a @leoniaplusgiornale attivo!")
        print("🌐 Risponde SEMPRE in ITALIANO")
        print("📜 Licenza: MPL 2.0")
        print("="*60 + "\n")
        
        if HF_TOKEN:
            print(f"✅ Hugging Face configurato: {HF_MODEL}")
            print(f"🔑 Token: {HF_TOKEN[:10]}...{HF_TOKEN[-4:]}")
        else:
            print(f"⚠️ Hugging Face NON configurato! /ces-360 e /img_plus non funzioneranno.")
            print("   Aggiungi HUGGINGFACE_TOKEN=tuo_token nel file .env")
        
        if GEMINI_API_KEY:
            print(f"✅ Gemini API Key configurata")
            print(f"   Modelli: {', '.join(AIClient.GEMINI_MODELS)}")
        else:
            print(f"⚠️ Gemini API Key non configurata! Aggiungi GEMINI_API_KEY nel file .env")
        
        self.api("deleteWebhook")
        
        print("🧹 Sincronizzazione offset e pulizia dei messaggi accumulati durante il downtime...")
        try:
            temp_updates = self.api("getUpdates", {"offset": -1, "limit": 1, "timeout": 1})
            if temp_updates.get("ok") and temp_updates.get("result"):
                last_id = temp_updates["result"][0]["update_id"]
                self.api("getUpdates", {"offset": last_id + 1, "limit": 1, "timeout": 1})
                self.db.set_last_update_id(last_id)
                print(f"✅ Messaggi vecchi ignorati correttamente. Offset sincronizzato a: {last_id}")
            else:
                last_id = self.db.get_last_update_id()
                print(f"📌 Nessun messaggio accumulato offline. offset caricato dal DB: {last_id}")
        except Exception as e:
            print(f"⚠️ Errore pulizia coda messaggi offline: {e}")
            last_id = self.db.get_last_update_id()
        
        while True:
            try:
                updates = self.api("getUpdates", {"offset": last_id + 1, "timeout": 30})
                if updates.get("ok") and updates.get("result"):
                    for update in updates["result"]:
                        update_id = update["update_id"]
                        self.db.set_last_update_id(update_id)
                        last_id = update_id
                        self.process_update(update)
            except KeyboardInterrupt:
                print("\n👋 Ciao!")
                break
            except Exception as e:
                print(f"⚠️ Errore nel polling: {e}")
                time.sleep(2)

# ==================== BACKGROUND LOOP PER LEONIA+ ====================
def leoniaplus_background_loop(bot):
    """Ciclo infinito in background (ogni 2 ore) per mantenere aggiornate le notizie"""
    time.sleep(5)
    while True:
        success = LeoniaPlusUpdater.scrape_channel()
        if success:
            bot.knowledge.reload()
        time.sleep(7200)

def main():
    print("\n" + "="*60)
    print("🤖 ArcadiaAI - Versione con CES-360 su Hugging Face")
    print("🧠 Modello CES-360: mirkodonato08/CES-360")
    print("🧠 Deep Research Engine attivo!")
    print("📊 Piani: free (8 fonti), plus (25 fonti), pro (80 fonti)")
    print("🤖 Gemini multi-fallback: gemini-2.5-flash, gemini-2.5-pro, gemini-2.5-flash-lite")
    print("🎨 Modello HD Image: FLUX.1-schnell (Inference API con fallback DoH)")
    print("💾 I messaggi NON vengono persi quando il bot è spento!")
    print("🔒 I nomi reali NON vengono mai inviati alle API!")
    print("🖼️ Analisi immagini con CES Image Viewer integrata")
    print("📌 /ai funziona in gruppi e supergruppi!")
    print("🔧 /alias_test per testare il sistema")
    print("🧠 /memoria per vedere lo stato della memoria")
    print("🧹 /clear_memory per cancellare la memoria")
    print("🧠 /ces-360 per interrogare il modello CES-360")
    print("🎨 /img_plus per generare immagini ad alta definizione")
    print("📰 Collegamento asincrono a @leoniaplusgiornale attivo!")
    print("🌐 Risponde SEMPRE in ITALIANO")
    print("📜 Licenza: MPL 2.0")
    print("="*60 + "\n")
    
    deep_engine.start()
    print("🧠 Motore Deep Research avviato correttamente")
    
    bot = ArcadiaBot()
    if not bot.test():
        deep_engine.stop()
        sys.exit(1)
        
    global BOT_INSTANCE
    BOT_INSTANCE = bot
        
    threading.Thread(target=leoniaplus_background_loop, args=(bot,), daemon=True).start()
    print("📰 Thread di sincronizzazione automatica Leonia+ avviato!")
    
    print(f"✅ Pronto! RAM: {bot._mem():.1f}MB")
    print(f"📚 Risposte predefinite caricate: {len(RISPOSTE_PREDEFINITE)}")
    print(f"🔍 Trigger configurati: {len(TRIGGER_PHRASES)}")
    print(f"🖼️ CES Image Viewer disponibile: {HAS_IMAGE_VIEWER}")
    print(f"🔒 Alias caricati: {len(WIKIALIAS)}")
    if HF_TOKEN:
        print(f"🧠 Hugging Face configurato: {HF_MODEL}")
        print(f"🔑 Token: {HF_TOKEN[:10]}...{HF_TOKEN[-4:]}")
    else:
        print(f"⚠️ Hugging Face NON configurato! /ces-360 e /img_plus non funzioneranno.")
        print("   Aggiungi HUGGINGFACE_TOKEN=tuo_token nel file .env")
    if GEMINI_API_KEY:
        print(f"✅ Gemini API Key configurata")
        print(f"   Modelli: {', '.join(AIClient.GEMINI_MODELS)}")
    else:
        print(f"⚠️ Gemini API Key non configurata! Aggiungi GEMINI_API_KEY nel file .env")
    print("\n")
    
    try:
        bot.run_polling()
    except KeyboardInterrupt:
        print("\n👋 Spegnimento bot eseguito correttamente.")
    except Exception as e:
        print(f"\n❌ Errore di rete o d'avvio: {e}")
        bot.db.close()
        deep_engine.stop()
        sys.exit(1)
    finally:
        deep_engine.stop()

if __name__ == "__main__":
    main()