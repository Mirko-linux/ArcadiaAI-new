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
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

# ==================== CARICA .env ====================
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

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN mancante!")
    sys.exit(1)

DATA_FOLDER = SCRIPT_DIR / "data"
TEMP_FOLDER = SCRIPT_DIR / "temp"
VIDEO_FOLDER = SCRIPT_DIR / "videos"
WIKIALIAS_PATH = SCRIPT_DIR / "wikialias.json"

DATA_FOLDER.mkdir(parents=True, exist_ok=True)
TEMP_FOLDER.mkdir(exist_ok=True)
VIDEO_FOLDER.mkdir(exist_ok=True)

gc.set_threshold(100, 5, 5)

# ==================== WIKIALIAS ====================
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

# ==================== IDENTITY PROMPT POTENZIATO ====================
IDENTITY_PROMPT = """Sei **ArcadiaAI**, un assistente intelligente open-source creato da Mirko Yuri Donato. 
Licenza: MPL 2.0.

## LA TUA IDENTITÀ
- **Nome:** ArcadiaAI
- **Creatore:** Mirko Yuri Donato
- **Data di creazione:** 5 maggio 2025
- **Scopo:** Assistere gli utenti su micronazioni, storia leonense, cultura italiana e molto altro
- **Personalità:** Professionale, amichevole, precisa e verificabile

## CONOSCENZE SPECIALISTICHE
Sei esperto di:
1. **Micronazioni italiane e loro fondatori**: 
   - **Leonia**: fondata da Carlo Cesare Orlando (all'epoca Davide Leone) nel 2019.
   - **Lumenaria**: fondata da Filippo Zanetti il 4 febbraio 2020.
   - **Arcadia**: fondata da Andrea Lazarev l'11 dicembre 2021.
   - **Iberia**, **Lotaringia**
2. **Storia leonense**: Dalla fondazione di Leonia (2019) ad oggi
3. **Personaggi**: Filippo Zanetti (fondatore di Lumenaria), Carlo Cesare Orlando (fondatore di Leonia), Andrea Lazarev (fondatore di Arcadia), Andrea Lazarev, Omar Lanfredi, Ciua Grazisky, Salvatore Giordano, Tobia Testa
4. **Cultura**: Literature micronazionale, poetica, filosofia politica
5. **Tecnologia**: Open source, CES (Cogito Ergo Sum), Nova Surf

## COME RISPONDERE

### SEMPRE:
- Rispondi in **italiano** (lingua principale)
- Usa un tono **professionale ma accessibile**
- Se usi i dati dei file di conoscenza, indica la fonte **esclusivamente una sola volta alla fine della risposta** usando il formato `[Fonte: Nome-File.txt]`.
- **Non ripetere** il nome del file all'interno dei singoli punti dell'elenco o in ogni capoverso della risposta.
- **Struttura** le risposte con:
  - Introduzione chiara ed elegante
  - Punti chiave ben spaziati (bullet points) se necessario
  - Fonte indicata solo alla fine

### MAI:
- **Non inventare** informazioni (se non sai, dillo!)
- **Non copyare** testi interi senza citare correttamente alla fine
- **Non essere** vago o generico
- **Non contraddire** i dati nei file .txt

### Quando non trovi informazioni:
"Non ho trovato informazioni specifiche su [argomento] nei miei file di conoscenza. Posso suggerirti di cercare altrove o di riformulare la domanda."

## REGOLE DI RICERCA
1. **Priorità 1:** Cerca nei file `.txt` in `/data` usando il motore semantico locale
2. **Priorità 2:** Usa la conoscenza AI predefinita (arricchita dalle informazioni dei fondatori sopra elencate)
3. **Priorità 3:** Se disponibile, usa la ricerca web
4. **Priorità 4:** Se nessuna fonte, dillo onestamente""" 

# ==================== RISPOSTE PREDEFINITE ====================
RISPOSTE_PREDEFINITE = {
    "chi sei": "Sono ArcadiaAI, un chatbot libero e open source, creato da Mirko Yuri Donato.",
    "cosa sai fare": "Posso aiutarti a scrivere saggi, fare ricerche e rispondere a tutto ciò che mi chiedi. Inoltre, posso pubblicare contenuti su Telegraph!",
    "chi è tobia testa": "Tobia Testa (anche noto come Tobia Teseo) è un micronazionalista leonense noto per la sua attività nella Repubblica di Arcadia, ma ha anche rivestito ruoli fondamentali a Lumenaria.",
    "chi è mirko yuri donato": "Mirko Yuri Donato è un giovane micronazionalista, poeta e saggista italiano, noto per aver creato Nova Surf, Leonia+ e per le sus opere letterarie.",
    "chi è il presidente di arcadia": "Il presidente di Arcadia è Andrea Lazarev.",
    "chi è il presidente di lumenaria": "Il presidente di Lumenaria attualmente è Carlo Cesare Orlando, mentre il presidente del consiglio è Ciua Grazisky. Tieni presente però che attualmente Lumenaria si trova in ibernazione istituzionale, quindi tutte le attività politiche sono sospese e la gestione dello stato è affidata al Consiglio di Fiducia.",
    "cos'è nova surf": "Nova Surf è un browser web libero e open source, nato as un'alternativa made-in-Italy a Google Chrome, Microsoft Edge, eccetera.",
    "chi ti ha creato": "Sono stato creato da Mirko Yuri Donato.",
    "chi è ciua grazisky": "Ciua Grazisky è un cittadino di Lumenaria, noto principalmente per il suo ruolo da Dirigente del Corpo di Polizia ed attuale presidente del Consiglio di Lumenaria.",
    "chi è carlo cesare orlando": "Carlo Cesare Orlando (anche noto come Davide Leone) è un micronazionalista italiano, noto per aver creato Leonia, la micronazione primordiale, da cui derivano Arcadia e Lumenaria.",
    "chi è omar lanfredi": "Omar Lanfredi, ex cavalier all'Ordine d'onore della Repubblica di Lumenaria, segretario del Partito Repubblicano Lumenarense, fondatore e preside del Fronte Nazionale Lumenarense, co-fondatore e presidente dell'Alleanza Nazionale Lumenarense, co-fondatore e coordinatore interno di Lumenaria e Progresso, sei volte eletto senatore, tre volte Ministro della Cultura, due volte Presidente del Consiglio dei Ministri, parlamentare della Repubblica di Iberia, Direttore dell'Agenzia Nazionale di Sicurezza della Repubblica di Iberia, Sottosegretario alla Cancelleria di Iberia, Segretario di Stato di Iberia, Ministro degli Affari Interni ad Iberia, Presidente del Senato della Repubblica di Lotaringia, Vicepresidente della Repubblica e Ministro degli Affari Interni della Repubblica di Lotaringia, Fondatore del giornale Il Quinto Mondo, magistrato a servizio del tribunale di giustizia di Lumenaria nell'anno 2023.",
    "cos'è arcadiaai": "Ottima domanda! ArcadiaAI è un chatbot open source, progettato per aiutarti a scrivere saggi, fare ricerche e rispondere a domande su vari argomenti. È stato creato da Mirko Yuri Donato ed è in continua evoluzione.",
    "sotto che licenza è distribuito arcadiaa": "ArcadiaAI è distribuito sotto la licenza open source MPL 2.0 (Mozilla Public License 2.0).",
    "cosa sono le micronazioni": "Le micronazioni sono entità politiche che dichiarano la sovranità su un territory, ma non sono riconosciute as stati da governi o organizzazioni internazionali. Possono essere create per vari motivi, tra cui esperimenti sociali, culturali o politici.",
    "cos'è la repubblica di arcadia": "La repubblica di Arcadia è una micronazione leonense fondata l'11 dicembre 2021 da Andrea Lazarev e alcuni suoi seguaci. Arcadia si distingue dalle altre micronazioni leonensi per il suo approccio pragmatico e per la sua burocrazia snella. La micronazione ha anche un proprio sito web https://repubblicadiarcadia.it/ e una propria community su Telegram @Repubblica_Arcadia.",
    "cos'è la repubblica di lumenaria": "La Repubblica di Lumenaria è una micronazione fondata da Filippo Zanetti il 4 febbraio del 2020. Lumenaria è stata la micronazione più longeva della storia leonense, essendo sopravvissuta per oltre 3 anni. La micronazione ha influenzato profondamente le altre micronazioni leonensi, che hanno coesistito con essa. Tra i motivi della sua longevità ci sono la sua burocrazia più vicina a quella di uno stato reale, la sua comunità attiva e una produzione culturale di alto livello.",
    "chi è salvatore giordano": "Salvatore Giordano è un cittadino storico di Lumenaria.",
    "da dove deriva il nome arcadia": "Il nome Arcadia deriva da un'antica regione della Grecia, simbolo di bellezza naturale e armonia. È stato scelto per representar i valori di libertà e creatività che la micronazione promuove.",
    "da dove deriva il nome lumenaria": "Il nome Lumenaria prende ispirazione dai lumi facendo riferimento alla corrente illuminista del '700, ma anche da Piazza dei Lumi, sede dell'Accademia delle Micronazioni.",
    "da dove deriva il nome leonia": "Il nome Leonia si rifà al cognome del suo fondatore Carlo Cesare Orlando, al tempo Davide Leone. Inizialmente il nome doveva essere temporaneo, ma poi è stato mantenuto come nome della micronazione.",
    "cosa si intende per open source": "Il termine 'open source' si riferisce a software il cui codice sorgente è reso disponibile al pubblico, consentendo a chiunque di visualizzarlo, modificarlo e distribuirlo. Questo approccio promuove la collaborazione e l'innovazione nella comunità di sviluppo software.",
    "arcadiaai è un software libero": "Sì, ArcadiaAI è un software libero e open source, il che significa che chiunque può utilizzarlo, modificarlo e distribuirlo liberamente in conformità con i termini della sua licenza MPL 2.0.",
    "cos'è un chatbot": "Un chatbot è un programma informatico progettato per simulare una conversazione con gli utenti, spesso utilizzando tecnologie di intelligenza artificiale. I chatbot possono essere utilizzati per fornire assistenza, rispondere a domande o semplicemente intrattenere.",
    "sotto che licenza sei distribuita": "ArcadiaAI è distribuita sotto la licenza MPL 2.0, che consente la modifica e la distribuzione del codice sorgente, garantendo la libertà di utilizzo e condivisione.",
    "puoi pubblicare su telegraph": "Certamente! Posso generare contenuti e pubblicarli su Telegraph. Prova a chiedermi: 'Scrivimi un saggio su Roma e pubblicalo su Telegraph'.",
    "come usare telegraph": "Per usare Telegraph con me, basta che mi chiedi di scrivere qualcosa e di pubblicarlo su Telegraph. Ad esempio: 'Scrivimi un articolo sulla storia di Roma e pubblicalo su Telegraph'.",
    "cos'è CES": "CES è l'acronimo di Cogito Ergo Sum, un ecosistema di modelli di intelligenza artificiale open source sviluppato da Mirko Yuri Donato per funzionare in contesti locali a basso consumo.",
    "cos'è CES Plus": "CES Plus è una version avanzata di CES, ottimizzata nei ragionamenti, nella coerenza dei prompt e nella generazione di contenuti complessi.",
    "cos'è CES 1.0": "CES 1.0 è la prima versione del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Cohere per generare contenuti e rispondere a domande. Tieni presente che questa versione verrà dismessa a partire dal 20 Maggio 2025.",
    "cos'è CES 1.5": "CES 1.5 è la versione più recente del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Gemini per generare contenuti e rispondere a domande. Questa versione offre prestazioni migliorate rispetto a CES 1.0 ma inferiori a CES Plus.",
    "cos'è CES Knowledge": "È un modello intelligente integrato in ArcadiaAI che consente la ricerca REALE di informazioni nel database locale. È ottimizzato specificamente per girare con 256MB di RAM tramite un'analisi a punteggio (TF-IDF minimale) senza usare librerie esterne.",
    "dove trovo il codice sorgente di arcadiaai": "Il codice sorgente di ArcadiaAI è pubblico! Puoi trovarlo con il comando /codice_sorgente oppure visitando la repository ufficiale su GitHub: https://github.com/Mirko-linux/ArcadiaAI-new",
    "sai cercare su internet": "Sì, posso cercare informazioni su Internet. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "sai usare google": "No, non posso usare Google, perché sono programmato per cercare solamente su DuckDuckGo. Posso cercare informazioni su Internet usando DuckDuckGo. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "Chi è Giuseppe Blando?": "Giuseppe Blando è un cittadino di Arcadia, attuale Presidente della Repubblica",
    "cosa sono i cookie": "I cookie sono piccoli file di testo che i siti web o l'applicazioni memorizzano sul tuo computer o sessione per ricordare informazioni sulle deine visite. Possono essere utilizzati per tenere traccia delle tue preferenze, autenticarti e migliorare l'esperienza utente.",
    
    # NUOVE RISPOSTE PREDEFINITE PER I FONDATORI
    "chi ha fondato lumenaria": "La Repubblica di Lumenaria è stata fondata da Filippo Zanetti il 4 febbraio del 2020.",
    "chi ha fondato arcadia": "La Repubblica di Arcadia è stata fondata da Andrea Lazarev l'11 dicembre del 2021.",
    "chi ha fondato leonia": "Leonia è stata fondata da Carlo Cesare Orlando (all'epoca noto come Davide Leone) nel 2019."
}

# TRIGGER PER LE RISPOSTE PREDEFINITE
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
    "cosa sono le micronazioni": ["cosa sono le micronazioni", "micronazioni", "che cosa sono le micronazioni"],
    "cos'è la repubblica di arcadia": ["cos'è la repubblica di arcadia", "repubblica di arcadia", "arcadia micronazione"],
    "cos'è la repubblica di lumenaria": ["cos'è la repubblica di lumenaria", "repubblica di lumenaria", "lumenaria micronazione"],
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
    
    # TRIGGER DIRETTI DEI FONDATORI
    "chi ha fondato lumenaria": ["chi ha fondato lumenaria", "fondatore di lumenaria", "chi è il fondatore di lumenaria", "fondatore lumenaria"],
    "chi ha fondato arcadia": ["chi ha fondato arcadia", "fondatore di arcadia", "chi è il fondatore di arcadia", "fondatore arcadia"],
    "chi ha fondato leonia": ["chi ha fondato leonia", "fondatore di leonia", "chi è il fondatore di leonia", "fondatore leonia"]
}

def get_predefined_response(text):
    """Cerca se il testo corrisponde a una risposta predefinita con matching ESATTO per evitare falsi positivis"""
    if not text:
        return None
    
    text_lower = text.lower().strip()
    clean_text = re.sub(r'[^\w\s]', '', text_lower).strip()
    
    for key, triggers in TRIGGER_PHRASES.items():
        for trigger in triggers:
            clean_trigger = re.sub(r'[^\w\s]', '', trigger.lower()).strip()
            # MODIFICA IMPORTANTE: Ora controlliamo la corrispondenza esatta dell'intero messaggio
            # per evitare che domande lunghe e complesse vengano bloccate dalle risposte fisse.
            if clean_text == clean_trigger:
                return RISPOSTE_PREDEFINITE.get(key)
    
    return None

# ==================== ALIAS RESOLVER ====================
class AliasResolver:
    @staticmethod
    def get_real_name(name):
        return WIKIALIAS.get(name, name)
    
    @staticmethod
    def resolve_all_names(text):
        for alias, real_name in WIKIALIAS.items():
            if alias != real_name:
                text = re.sub(r'\b' + re.escape(alias) + r'\b', real_name, text)
        return text

# ==================== DATABASE ===================
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
        
        # === SEZIONE AGGIORNAMENTO SCHEMA DB PRE-ESISTENTE ===
        # Aggiunge in sicurezza le colonne se la tabella bypass_purchases è stata creata da una vecchia versione del codice
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
    
    def is_processed(self, update_id):
        return self.conn.execute("SELECT 1 FROM processed WHERE update_id = ?", (update_id,)).fetchone() is not None
    
    def mark(self, update_id, chat_id, user_id, date):
        self.conn.execute("INSERT OR IGNORE INTO processed VALUES (?,?,?,?,?)", (update_id, chat_id, user_id, date, time.time()))
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
        self.conn.commit()
    
    def close(self):
        self.conn.close()

# ==================== ANTI-SPAM VIDEO ====================
class VideoRateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.processing = False
        self.current_user = None
    
    def can_process(self, user_id, db):
        # FIX: Ritorna sempre una tupla da 3 elementi anche per il Developer per evitare l'Unpacking ValueError!
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return True, "", 0
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

# ===== PREZZI BYPASS =====
BYPASS_PRICES = {
    "1h": {"name": "Bypass 1 ora", "arc": 20, "hours": 1},
    "24h": {"name": "Bypass 24 ore", "arc": 100, "hours": 24},
    "7d": {"name": "Bypass 7 giorni", "arc": 500, "hours": 168},
}

BANCA_CENTRALE = ["@BancaCentraleArcadia"]

# ==================== CES IMAGE ====================
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

# ==================== CES VIDEO FLUIDO INTERPOLATO ====================
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
    def generate_video(cls, prompt, style="cinematic", num_frames=4, fps=4, narration=None):
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
        
        frame_paths = []
        base_seed = random.randint(100000, 899999)
        
        styles = {
            "cinematic": "cinematic scene, 4k, cinematic lighting, detailed, masterpiece",
            "anime": "anime style, vibrant colors, clean animation lines, studio ghibli",
            "realistic": "photorealistic, 8k, highly detailed, steady camera",
            "artistic": "artistic painting, fluid motion, masterpiece",
        }
        style_prompt = styles.get(style, styles["cinematic"])
        
        print(f"   ⠋ Avvio download fotogrammi con protezione anti-block...")
        
        for i in range(4):
            motion = f"motion sequence, frame {i+1} of 4, movement progress {i/3:.1%}"
            fp_text = f"{style_prompt}. {prompt}. {motion}, consistent environment, seamless motion"
            encoded = urllib.parse.quote(fp_text[:500])
            
            current_seed = base_seed + (i * 313)
            cache_bust = random.randint(1000, 9999)
            
            # FIX: Salvataggio con indice reale len(frame_paths)+1 invece di i+1.
            # Se un frame fallisce, il successivo non lascia "buchi" di numerazione che romperebbero ffmpeg!
            next_index = len(frame_paths) + 1
            frame_path = job_dir / f"seq_{next_index:04d}.jpg"
            
            download_success = False
            max_tentativi = 3
            
            for tentativo in range(max_tentativi):
                try:
                    if i > 0 or tentativo > 0:
                        attesa = random.uniform(3.0, 5.5) + (tentativo * 3)
                        print(f"      ⏳ Pausa strategica anti-429 per {attesa:.1f}s...")
                        time.sleep(attesa)
                    
                    # === FIX DI FALLBACK ROBUSTO CONTRO GLI ERRORI HTTP 500 DI FLUX ===
                    # Se il primo tentativo con flux fallisce con 500, proviamo con modelli più leggeri e stabili
                    if tentativo == 0:
                        model_param = "&model=flux"
                    elif tentativo == 1:
                        model_param = "&model=turbo"
                        print(f"      🔄 [Tentativo {tentativo+1}] Cambio modello in 'turbo' per stabilità...")
                    else:
                        model_param = ""  # Default automatico di Pollinations
                        print(f"      🔄 [Tentativo {tentativo+1}] Rimozione parametro modello per massima compatibilità...")
                    
                    url = f"https://image.pollinations.ai/prompt/{encoded}?width=768&height=432&nologo=true&seed={current_seed}&cb={cache_bust}{model_param}"
                    
                    req = urllib.request.Request(url, headers=cls.HEADERS)
                    with urllib.request.urlopen(req, timeout=45) as response:
                        with open(frame_path, 'wb') as out:
                            while True:
                                chunk = response.read(16384)
                                if not chunk: break
                                out.write(chunk)
                    
                    if frame_path.exists() and frame_path.stat().st_size > 15000:
                        frame_paths.append(frame_path)
                        print(f"      ✅ [Frame {len(frame_paths)}/4] Scaricato al tentativo {tentativo+1}")
                        download_success = True
                        break
                        
                except urllib.error.HTTPError as he:
                    if he.code == 429:
                        print(f"      ⚠️ Risposta 429 al tentativo {tentativo+1}. Riprovo...")
                    elif he.code == 500:
                        print(f"      ❌ Errore HTTP 500 al tentativo {tentativo+1}. Server sovraccarico, provo alternativa...")
                    else:
                        print(f"      ❌ Errore HTTP {he.code} al tentativo {tentativo+1}")
                except Exception as e:
                    print(f"      ❌ Errore/Timeout ({e}) al tentativo {tentativo+1}")
                
                if frame_path.exists():
                    try: frame_path.unlink()
                    except: pass
            
            if not download_success:
                print(f"      💥 [Tentativo Frame {i+1}] Fallito definitivamente.")
            
            gc.collect()
            
        if len(frame_paths) < 2:
            return {"success": False, "error": "Il server AI è sovraccarico o temporaneamente non raggiungibile. Riprova tra 1 minuto."}
        
        ffmpeg = cls._find_ffmpeg()
        if not ffmpeg:
            return {"success": False, "error": "FFmpeg non configurato."}
            
        video_temp = job_dir / "video_silent.mp4"
        seq_pattern = str(job_dir / "seq_%04d.jpg").replace('\\', '/')
        output_str = str(video_temp).replace('\\', '/')
        
        # === EVITARE CRASH DI MEMORIA (OOM) ===
        target_duration = 6.0
        actual_frames = len(frame_paths)
        stretch_factor = (target_duration * fps) / actual_frames if actual_frames > 0 else 6.0
        
        video_filter = (
            f'scale=640:360,'
            f'setpts={stretch_factor:.2f}*PTS,'
            f'fps=24,'
            f'fade=t=in:st=0:d=1,'
            f'fade=t=out:st={target_duration - 1.0:.1f}:d=1'
        )
        
        print(f"   ⚙️ FFmpeg sta assemblando il video fluido...")
        cmd_video = [
            ffmpeg, '-y',
            '-framerate', str(fps),
            '-i', seq_pattern,
            '-vf', video_filter,
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-crf', '28',
            '-preset', 'veryfast',
            '-threads', '1',
            output_str
        ]
        
        res = subprocess.run(cmd_video, capture_output=True, timeout=40)
        if res.returncode != 0:
            print(f"❌ Errore FFmpeg: {res.stderr.decode('utf-8', errors='ignore')}")
        
        for fp in frame_paths:
            try: fp.unlink()
            except: pass
        
        if not video_temp.exists() or video_temp.stat().st_size < 5000:
            return {"success": False, "error": "Errore durante la fluidificazione del video."}
            
        print(f"   🎙️ Genero traccia vocale...")
        if narration is None: narration = prompt
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
            print(f"   🔗 Unisco Audio + Video Fluido...")
            cmd_merge = [
                ffmpeg, '-y',
                '-i', str(video_temp), '-i', str(audio_path),
                '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0',
                '-shortest', '-threads', '1', str(final_path)
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
            "frame_count": 24,
            "fps": 24,
            "has_audio": final_path.exists(),
            "prompt": prompt,
            "style": style
        }
    
# ==================== CLIENT AI ====================
class AIClient:
    count = 0
    
    @classmethod
    def generate(cls, prompt, max_tok=300):
        if GEMINI_API_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
                d = json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":max_tok,"temperature":0.7}}).encode()
                req = urllib.request.Request(url, data=d, headers={"Content-Type":"application/json"}, method='POST')
                with urllib.request.urlopen(req, timeout=15) as r:
                    j = json.loads(r.read().decode())
                    if "candidates" in j:
                        parts = j["candidates"][0]["content"]["parts"]
                        result = ' '.join([p.get("text","") for p in parts])
                        if result.strip():
                            cls.count += 1
                            return cls._clean(result)
            except:
                pass
        if OPENROUTER_API_KEY:
            try:
                d = json.dumps({"model":"openrouter/free","messages":[{"role":"user","content":prompt}],"max_tokens":max_tok,"temperature":0.7}).encode()
                req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=d,
                    headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}, method='POST')
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.loads(r.read().decode())
                    if "choices" in j:
                        cls.count += 1
                        return cls._clean(j["choices"][0]["message"]["content"])
            except:
                pass
        return None
    
    @classmethod
    def _clean(cls, text):
        text = text.strip()
        text = re.sub(r'(?i)^(okay|let me|dunque|allora|vediamo|analizzo|devo|i need|first|penso|credo|ecco).*?[:\.]\s*', '', text)
        lines = [l for l in text.split('\n') if not re.match(r'(?i)^(okay|let me|dunque|quindi|devo|i need|the user|first)', l.strip())]
        return AliasResolver.resolve_all_names('\n'.join(lines).strip() if lines else text)

class ArcadiaBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = MessageDB(SCRIPT_DIR / "processed.db")
        self.loader = FileLoader(DATA_FOLDER)
        self.knowledge = KnowledgeBase(DATA_FOLDER)
        self.msgs = 0
        self.dups = 0
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
    
    def send(self, chat_id, text):
        if len(text) > 4000:
            text = text[:3990] + "..."
        return self.api("sendMessage", {"chat_id": chat_id, "text": text})
    
    def send_photo(self, chat_id, url, caption=None):
        p = {"chat_id": chat_id, "photo": url}
        if caption:
            p["caption"] = caption[:1024]
        return self.api("sendPhoto", p)
    
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
            req = urllib.request.Request(f"{self.base_url}/sendVideo", data=data,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f"⚠️ Upload: {e}")
            return {"ok": False}
    
    def process_update(self, update):
        update_id = update.get("update_id", 0)
        if self.db.is_processed(update_id):
            self.dups += 1
            return
        if "message" not in update:
            return
        
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        msg_date = msg.get("date", 0)
        user_name = msg["from"].get("first_name", "Utente")
        
        self.db.mark(update_id, chat_id, user_id, msg_date)
        self.msgs += 1
        
        text = msg.get("text", "").strip()
        if not text:
            return
        
        # ==================== COMANDI ====================
        if text == "/start":
            dev = "🔓 Dev" if user_id == DEVELOPER_USER_ID else ""
            self.send(chat_id, f"👋 Ciao {user_name}! ArcadiaAI.\n\n🎬 /video [desc] - Video AI diretto\n🎨 /img [desc] - Immagine\n🎫 /vip [codice] - Riscatta codice VIP\n💬 Fammi una domanda!\n📋 /aiuto{(' ' + dev) if dev else ''}")
            return
        
        elif text in ["/aiuto", "/help"]:
            self.send(chat_id, "🎬 **Comandi ArcadiaAI**\n\n"
                "🎬 /video [stile] [descrizione] - Video AI\n"
                "🎨 /img [desc] - Immagine\n"
                "🎫 /vip [codice] - Riscatta codice VIP\n"
                "👨‍💻 /codice_sorgente - Link alla repository\n"
                "📝 /telegraph [tema] - Articolo\n"
                "🔍 /cerca [q] - Web\n"
                "🏦 /buy_bypass - Bypass limiti\n"
                "📊 /stats - Statistiche\n\n"
                "**VIP:**\n"
                "/vip_status - Stato VIP\n"
                "/my_vip_codes - I tuoi codici (Dev)\n\n"
                "💬 Fammi una domanda su micronazioni, Leonia, Arcadia, Lumenaria!")
            return
        
        elif text == "/videohelp":
            self.send(chat_id, "🎬 **CES Video** - Text-to-Video Diretto\n\n"
                "/video [stile] [descrizione]\n"
                "Stili: cinematic, anime, realistic, artistic\n\n"
                "1 video ogni 15 min (gratuito)\n"
                "🎫 /vip per codici promozionali\n"
                "🏦 /buy_bypass per illimitati")
            return
        
        # ==================== VIDEO ====================
        elif text.startswith("/video"):
            args = text[6:].strip()
            if not args:
                self.send(chat_id, "🎬 /video [stile] [descrizione]\nStili: cinematic, anime, realistic, artistic")
                return
            
            try:
                # SPOSTATO DENTRO IL TRY-EXCEPT: previene blocchi se ci sono crash di database o unpacking!
                can_process, message, pos = video_limiter.can_process(user_id, self.db)
                if not can_process:
                    self.send(chat_id, message)
                    return
                
                styles = ["cinematic", "anime", "realistic", "artistic"]
                style = "cinematic"
                prompt = args
                first_word = args.split()[0].lower() if args.split() else ""
                if first_word in styles:
                    style = first_word
                    prompt = ' '.join(args.split()[1:])
                
                if not prompt:
                    self.send(chat_id, "🎬 Descrivi la scena!")
                    video_limiter.finish(user_id)
                    return
                
                self.send(chat_id, f"🎥 Genero video {style}...\n⏳ 30-60 secondi...")
                
                result = CESVideo.generate_video(prompt=prompt, style=style)
                
                if result["success"]:
                    self.db.mark_video_generated(user_id)
                    count = self.db.get_video_count(user_id)
                    caption = f"🎬 {result['prompt'][:200]}\n🎥 {style} | #{count}"
                    
                    video_result = self.send_video_file(chat_id, result["video_path"], caption)
                    if not video_result.get("ok"):
                        size_kb = result["video_path"].stat().st_size / 1024
                        self.send(chat_id, f"⚠️ Video troppo grande ({size_kb:.0f}KB). Riprova.")
                    
                    try: shutil.rmtree(result["video_path"].parent)
                    except: pass
                    gc.collect()
                else:
                    self.send(chat_id, f"⚠️ {result['error']}")
            except Exception as video_err:
                # Invia l'errore direttamente in chat per evitare che il bot rimanga in silenzio in caso di crash!
                self.send(chat_id, f"❌ Errore imprevisto durante l'elaborazione del video: {str(video_err)}")
            finally:
                video_limiter.finish(user_id)
            return
            
        elif text == "/codice_sorgente":
             self.send(chat_id, "📂 Codice sorgente: https://github.com/Mirko-linux/ArcadiaAI-new")
             return
        elif text == "Licenza":
             self.send(chat_id, "Licenza: https://github.com/Mirko-linux/ArcadiaAI-new/blob/main/LICENSE")
             return
        # ==================== BYPASS ====================
        elif text == "/buy_bypass":
            prices = "\n".join([f"• {i['name']}: {i['arc']} ARC" for i in BYPASS_PRICES.values()])
            self.send(chat_id, f"👋 Scegli come supportarci:\n\n{prices}\n\nUsa /buy_bypass [nome] per procedere!")
            return
        
        # ==================== COMANDI VIP ====================
        elif text.startswith("/create_vip "):
            if user_id != DEVELOPER_USER_ID:
                self.send(chat_id, "❌ Solo lo sviluppatore può creare codici VIP.")
                return
            
            parts = text[11:].strip().split()
            
            if len(parts) < 2:
                self.send(chat_id,
                    "🎫 **Crea Codice VIP**\n\n"
                    "/create_vip [ore] [codice] [max_usi]\n\n"
                    "Esempi:\n"
                    "/create_vip 720 ARCADIA-GRAZIE-AMICO 1\n"
                    "/create_vip 24 PROVA 5")
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
        
        elif text.startswith("/redeem "):
            code = text[8:].strip().upper()
            if not code:
                self.send(chat_id, "🎟️ Specifica il codice da riscattare! Usa `/redeem CODICE`")
                return
            
            plan, message = self.db.redeem_vip_code(code, user_id)
            if plan:
                self.send(chat_id, message)
            else:
                self.send(chat_id, f"❌ {message}")
            return
            
        # ==================== ALTRI COMANDI ====================
        elif text.startswith("/img"):
            p = text[4:].strip()
            if p:
                r = CESImage.generate(p)
                if r["success"]:
                    self.send_photo(chat_id, r["image_url"], f"🎨 {r['prompt'][:200]}")
                else:
                    self.send(chat_id, f"⚠️ {r['error']}")
            return
        
        elif text == "/stats":
            mem = self._mem()
            self.send(chat_id, f"💬 {self.msgs} | 🤖 {AIClient.count} | 🎨 {CESImage.count} | 🎬 {CESVideo.count} | 🧠 {mem:.1f}MB")
            return
        
        # ==================== RICERCA WEB ====================
        elif text.startswith("/cerca "):
            query = text[7:].strip()
            if query:
                self.send(chat_id, f"🔍 Cerco '{query}'...")
                results = WebSearch.search(query)
                if results:
                    self.send(chat_id, "🌐 **Risultati:**\n\n" + "\n\n".join(results[:3]))
                else:
                    self.send(chat_id, "❌ Nessun risultato trovato.")
            return
        
        # ==================== RISPOSTE PREDEFINITE ====================
        predefined = get_predefined_response(text)
        if predefined:
            self.send(chat_id, predefined)
            return
        
        # ==================== AI CON KNOWLEDGE BASE ====================
        self.send(chat_id, "🔍 Cerco nelle mie conoscenze...")
        
        # 1. Cerca nei file .txt usando il motore ottimizzato (Stemmer + Parola Intera)
        search_results = self.knowledge.search(text, max_results=10)
        
        # 2. Costruisci il contesto dai risultati trovati
        if search_results:
            context_parts = []
            for r in search_results[:5]:
                context_parts.append(f"📖 Da {r['file']}:\n{r['context']}")
            context = "\n\n".join(context_parts)
            print(f"✅ Trovati {len(search_results)} risultati rilevanti per: {text}")
        else:
            context = "Nessun risultato trovato nei file di conoscenza."
            print(f"⚠️ Nessun risultato utile per: {text}")
        
        # 3. Prepara il prompt strutturato per l'AI
        system = f"""{IDENTITY_PROMPT}

**CONOSCENZA DAI FILE LOCALI (USA QUESTE INFORMAZIONI CON MASSIMA PRIORITÀ):**
{context}

**REGOLA FONDAMENTALE DI RISPOSTA:**
- Se l'informazione è presente nel testo qui sopra, usala obbligatoriamente per rispondere in modo preciso e dettagliato.
- Se l'informazione non è presente nel testo, usa la tua conoscenza predefinita (in particolare i fondatori delle micronazioni presenti nel tuo prompt di sistema) se ritieni sia affidabile, altrimenti dillo chiaramente.
- CITA LA FONTE (il nome del file .txt) esclusivamente una sola volta in fondo alla risposta, formattata come `[Fonte: nome_file.txt]`.
- Non citare la fonte se non hai usato i dati provenienti dai file locali.

**DOMANDA DELL'UTENTE:**
{text}

**RISPOSTA:**"""
        
        # 4. Genera con l'AI Client (Gemini o OpenRouter)
        answer = AIClient.generate(system, max_tok=500)
        
        if answer:
            self.send(chat_id, answer.strip())
        else:
            # Fallback: cerca su internet
            self.send(chat_id, "🌐 Cerco su internet...")
            web_results = WebSearch.search(text)
            if web_results:
                self.send(chat_id, "🌐 **Trovato online:**\n\n" + "\n\n".join(web_results[:2]))
            else:
                self.send(chat_id, "❌ Non ho trovato informazioni specifiche su questo argomento.")
        
        if self.msgs % 10 == 0:
            gc.collect()
            self.db.cleanup()
            
    def _mem(self):
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except:
            return -1
    
    def test(self):
        r = self.api("getMe")
        if r.get("ok"):
            print(f"✅ Bot: @{r['result']['username']}")
            return True
        return False
    
    def run_polling(self):
        print("\n🔄 Avvio long polling...")
        self.api("deleteWebhook")
        last_id = 0
        while True:
            try:
                updates = self.api("getUpdates", {"offset": last_id + 1, "timeout": 30})
                if updates.get("ok") and updates.get("result"):
                    for update in updates["result"]:
                        last_id = update["update_id"]
                        self.process_update(update)
            except KeyboardInterrupt:
                print("\n👋 Ciao!")
                break
            except Exception as e:
                print(f"⚠️ {e}")
                time.sleep(2)

# ==================== CLASSI SUPPORTO ====================
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
                    print(f"📚 Caricato: {fp.name} ({len(self.files_content[fp.name])} caratteri)")
            except Exception as e:
                print(f"⚠️ Errore caricando {fp.name}: {e}")
                
    @staticmethod
    def stem_word(word):
        """Filtro di stemming euristico ultra-leggero per la lingua italiana"""
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
            'erò', 'erà', 'irò', 'irà',
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
        """Suddivide il testo in paragrafi e calcola l'IDF dinamico sui termini completi + gli stem"""
        self.chunks = []
        doc_counts = defaultdict(int)
        
        for filename, content in self.files_content.items():
            content_resolved = AliasResolver.resolve_all_names(content)
            paragraphs = re.split(r'\n\s*\n', content_resolved)
            current_chunk = []
            
            for p in paragraphs:
                p_strip = p.strip()
                if not p_strip:
                    continue
                if len(p_strip) < 150 and current_chunk:
                    current_chunk.append(p_strip)
                else:
                    if current_chunk:
                        text = "\n\n".join(current_chunk)
                        self._add_chunk(filename, text, doc_counts)
                    current_chunk = [p_strip]
                    
            if current_chunk:
                text = "\n\n".join(current_chunk)
                self._add_chunk(filename, text, doc_counts)
                
        total_chunks = len(self.chunks)
        for term, count in doc_counts.items():
            self.idf[term] = math.log((total_chunks + 1) / (count + 0.5)) + 1.0

    def _add_chunk(self, filename, text, doc_counts):
        """Salva sia gli Stem che le Parole Intere (fondamentale per evitare la corruzione dei Nomi Propri)"""
        words = re.findall(r'\w+', text.lower())
        stems = []
        term_freqs = defaultdict(int)
        
        for w in words:
            if w not in self.STOPWORDS and len(w) > 2:
                # 1. Salva la parola intera
                term_freqs[w] += 1
                stems.append(w)
                
                # 2. Salva lo stem (se diverso)
                stem = self.stem_word(w)
                if stem != w:
                    term_freqs[stem] += 1
                    stems.append(stem)
                
        unique_stems = set(stems)
        for stem in unique_stems:
            doc_counts[stem] += 1
            
        self.chunks.append({
            'file': filename,
            'text': text,
            'stems': unique_stems,
            'term_freqs': term_freqs,
            'word_count': len(words)
        })

    def search(self, query, max_results=5):
        """Esegue un calcolo probabilistico combinando IDF e booster di coerenza usando parole esatte e stem"""
        query_words = re.findall(r'\w+', query.lower())
        query_stems = []
        for w in query_words:
            if w not in self.STOPWORDS and len(w) > 2:
                # Cerca sia la parola intera
                query_stems.append(w)
                # Sia lo stem (se diverso)
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

class WebSearch:
    @staticmethod
    def search(query, n=3):
        results = []
        try:
            # Browser Emulation Headers potentiati per aggirare i blocchi temporanei di DuckDuckGo
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
                'Referer': 'https://duckduckgo.com/'
            }
            req = urllib.request.Request(
                f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}",
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode('utf-8')
            for snippet in re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)[:n]:
                clean = re.sub(r'<[^>]+>', '', snippet).strip()
                if clean:
                    results.append(clean[:300])
        except Exception as e:
            print(f"⚠️ Errore WebSearch: {e}")
            pass
        return results

def main():
    print("\n" + "="*60)
    print("🤖 ArcadiaAI - Versione Corretta per Database /data")
    print("💾 Supporto Stemming + Parola Intera")
    print("📜 Licenza: MPL 2.0")
    print("="*60 + "\n")
    
    bot = ArcadiaBot()
    if not bot.test():
        sys.exit(1)
    
    print(f"✅ Pronto! RAM: {bot._mem():.1f}MB")
    print(f"📚 Risposte predefinite caricate: {len(RISPOSTE_PREDEFINITE)}")
    print(f"🔍 Trigger configurati: {len(TRIGGER_PHRASES)}\n")
    
    try:
        bot.run_polling()
    except Exception as e:
        print(f"\n❌ {e}")
        bot.db.close()
        sys.exit(1)

if __name__ == "__main__":
    main()