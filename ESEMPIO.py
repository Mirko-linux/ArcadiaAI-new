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

# Tentativo di importazione di CES Image Viewer (deve risiedere nella stessa cartella)
try:
    from ces_image_viewer import CESImageViewer
    HAS_IMAGE_VIEWER = True
except ImportError:
    HAS_IMAGE_VIEWER = False

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

# ==================== IDENTITY PROMPT (CORRETTO - FORZA ITALIANO) ====================
IDENTITY_PROMPT = """Sei **ArcadiaAI**, un assistente intelligente open-source creato da Mirko Yuri Donato. 
Licenza: MPL 2.0.

## REGOLE FONDAMENTALI (DA RISPETTARE SEMPRE)
1. **DEVI rispondere SOLO in italiano.** Mai in inglese o altre lingue.
2. **NON mostrare il tuo ragionamento.** Rispondi direttamente con la risposta finale.
3. **NON usare frasi come "analizzo", "vediamo", "cerco di", "let me", "I need".** Rispondi e basta.

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
3. **Personaggi**: Filippo Zanetti, Carlo Cesare Orlando, Andrea Lazarev, Omar Lanfredi, Ciua Grazisky, Salvatore Giordano, Tobia Testa
4. **Cultura**: Letteratura micronazionale, poetica, filosofia politica
5. **Tecnologia**: Open source, CES (Cogito Ergo Sum), Nova Surf

## COME RISPONDERE

### SEMPRE:
- Rispondi in **italiano** (lingua principale) - **NON IN INGLESE!**
- Usa un tono **professionale ma accessibile**
- Se usi i dati dei file di conoscenza, indica la fonte **esclusivamente una sola volta alla fine della risposta** usando il formato `[Fonte: Nome-File.txt]`.
- **Non ripetere** il nome del file all'interno dei singoli punti dell'elenco o in ogni capoverso della risposta.
- **Struttura** le risposte con:
  - Introduzione chiara ed elegante
  - Punti chiave ben spaziati (bullet points) se necessario
  - Fonte indicata solo alla fine
- **Rispondi direttamente**, senza mostrare il ragionamento o il processo di ricerca.

### MAI:
- **Non inventare** informazioni (se non sai, dillo!)
- **Non copiare** testi interi senza citare correttamente alla fine
- **Non essere** vago o generico
- **Non contraddire** i dati nei file .txt
- **Non rispondere in inglese** - SOLO ITALIANO!
- **Non mostrare il ragionamento** - rispondi direttamente!

### Quando non trovi informazioni:
"Non ho trovato informazioni specifiche su [argomento] nei miei file di conoscenza. Posso suggerirti di chiedere a qualcun altro o riformulare la domanda."

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
    "chi è mirko yuri donato": "Mirko Yuri Donato è un giovane micronazionalista, poeta e saggista italiano, noto per aver creato Nova Surf, Leonia+ e per le sue opere letterarie.",
    "chi è il presidente di arcadia": "Il presidente di Arcadia è Andrea Lazarev.",
    "chi è il presidente di lumenaria": "Il presidente di Lumenaria attualmente è Carlo Cesare Orlando, mentre il presidente del consiglio è Ciua Grazisky. Tieni presente però che attualmente Lumenaria si trova in ibernazione istituzionale, quindi tutte le attività politiche sono sospese e la gestione dello stato è affidata al Consiglio di Fiducia.",
    "cos'è nova surf": "Nova Surf è un browser web libero e open source, nato come un'alternativa made-in-Italy a Google Chrome, Microsoft Edge, eccetera.",
    "chi ti ha creato": "Sono stato creato da Mirko Yuri Donato.",
    "chi è ciua grazisky": "Ciua Grazisky è un cittadino di Lumenaria, noto principalmente per il suo ruolo da Dirigente del Corpo di Polizia ed attuale presidente del Consiglio di Lumenaria.",
    "chi è carlo cesare orlando": "Carlo Cesare Orlando (anche noto come Davide Leone) è un micronazionalista italiano, noto per aver creato Leonia, la micronazione primordiale, da cui derivano Arcadia e Lumenaria.",
    "chi è omar lanfredi": "Omar Lanfredi è un politico micronazionale attivo in Lumenaria, Iberia e Lotaringia. È stato sei volte senatore, tre volte Ministro della Cultura, due volte Presidente del Consiglio dei Ministri a Lumenaria, e ha ricoperto ruoli di primo piano anche in Iberia e Lotaringia.",
    "cos'è arcadiaai": "Ottima domanda! ArcadiaAI è un chatbot open source, progettato per aiutarti a scrivere saggi, fare ricerche e rispondere a domande su vari argomenti. É stato creato da Mirko Yuri Donato ed è in continua evoluzione.",
    "sotto che licenza è distribuito arcadiaa": "ArcadiaAI è distribuito sotto la licenza open source MPL 2.0 (Mozilla Public License 2.0).",
    "cosa sono le micronazioni": "Le micronazioni sono entità politiche che dichiarano la sovranità su un territorio, ma non sono riconosciute come stati da governi o organizzazioni internazionali. Possono essere create per vari motivi, tra cui esperimenti sociali, culturali o politici.",
    "cos'è la repubblica di arcadia": "La Repubblica di Arcadia è una micronazione leonense fondata l'11 dicembre 2021 da Andrea Lazarev e alcuni suoi seguaci. Arcadia si distingue dalle altre micronazioni leonensi per il suo approccio pragmatico e per la sua burocrazia snella. La micronazione ha anche un proprio sito web https://repubblicadiarcadia.it/ e una propria community su Telegram @Repubblica_Arcadia.",
    "cos'è la repubblica di lumenaria": "La Repubblica di Lumenaria è una micronazione fondata da Filippo Zanetti il 4 febbraio del 2020. Lumenaria è stata la micronazione più longeva della storia leonense, essendo sopravvissuta per oltre 3 anni. La micronazione ha influenzato profondamente le altre micronazioni leonensi, che hanno coesistito con essa. Tra i motivi della sua longevità ci sono la sua burocrazia più vicina a quella di uno stato reale, la sua comunità attiva e una produzione culturale di alto livello.",
    "chi è salvatore giordano": "Salvatore Giordano è un cittadino storico di Lumenaria.",
    "da dove deriva il nome arcadia": "Il nome Arcadia deriva da un'antica regione della Grecia, simbolo di bellezza naturale e armonia. È stato scelto per rappresentare i valori di libertà e creatività che la micronazione promuove.",
    "da dove deriva il nome lumenaria": "Il nome Lumenaria prende ispirazione dai lumi facendo riferimento alla corrente illuminista del '700, ma anche da Piazza dei Lumi, sede dell'Accademia delle Micronazioni.",
    "da dove deriva il nome leonia": "Il nome Leonia si rifà al cognome del suo fondatore Carlo Cesare Orlando, al tempo Davide Leone. Inizialmente il nome doveva essere temporaneo, ma poi è stato mantenuto come nome della micronazione.",
    "cosa si intende per open source": "Il termine 'open source' si riferisce a software il cui codice sorgente è reso disponibile al pubblico, consentendo a chiunque di visualizzarlo, modificarlo e distribuirlo. Questo approccio promuove la collaborazione e l'innovazione nella comunità di sviluppo software.",
    "arcadiaai è un software libero": "Sì, ArcadiaAI è un software libero e open source, il che significa che chiunque può utilizzarlo, modificarlo e distribuirlo liberamente in conformità con i termini della sua licenza MPL 2.0.",
    "cos'è un chatbot": "Un chatbot è un programma informatico progettato per simulare una conversazione con gli utenti, spesso utilizzando tecnologie di intelligenza artificiale. I chatbot possono essere utilizzati per fornire assistenza, rispondere a domande o semplicemente intrattenere.",
    "sotto che licenza sei distribuita": "ArcadiaAI è distribuita sotto la licenza MPL 2.0, che consente la modifica e la distribuzione del codice sorgente, garantendo la libertà di utilizzo e condivisione.",
    "puoi pubblicare su telegraph": "Certamente! Posso generare contenuti e pubblicarli su Telegraph. Prova a chiedermi: 'Scrivimi un saggio su Roma e pubblicalo su Telegraph'.",
    "come usare telegraph": "Per usare Telegraph con me, basta che mi chiedi di scrivere qualcosa e di pubblicarlo su Telegraph. Ad esempio: 'Scrivimi un saggio sul Colosseo e pubblicalo su Telegraph'.",
    "cos'è CES": "CES è l'acronimo di Cogito Ergo Sum, un ecosistema di modelli di intelligenza artificiale open source sviluppato da Mirko Yuri Donato per funzionare in contesti locali a basso consumo.",
    "cos'è CES Plus": "CES Plus è una versione avanzata di CES, ottimizzata nei ragionamenti, nella coerenza dei prompt e nella generazione di contenuti complessi.",
    "cos'è CES 1.0": "CES 1.0 è la prima versione del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Cohere per generare contenuti e rispondere a domande. Tieni presente che questa versione verrà dismessa a partire dal 20 Maggio 2025.",
    "cos'è CES 1.5": "CES 1.5 è la versione più recente del modello CES, sviluppato da Mirko Yuri Donato. Utilizza la tecnologia Gemini per generare contenuti e rispondere a domande. Questa versione offre prestazioni migliorate rispetto a CES 1.0 ma inferiori a CES Plus.",
    "cos'è CES Knowledge": "È un modello intelligente integrato in ArcadiaAI che consente la ricerca REALE di informazioni nel database locale. È ottimizzato specificamente per girare con 256MB di RAM tramite un'analisi a punteggio (TF-IDF minimale) senza usare librerie esterne.",
    "dove trovo il codice sorgente di arcadiaai": "Il codice sorgente di ArcadiaAI è pubblico! Puoi trovarlo con il comando /codice_sorgente oppure visitando la repository ufficiale su GitHub: https://github.com/Mirko-linux/ArcadiaAI-new",
    "sai cercare su internet": "Sì, posso cercare informazioni su Internet. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "sai usare google": "No, non posso usare Google, perché sono programmato per cercare solamente su DuckDuckGo. Posso cercare informazioni su Internet usando DuckDuckGo. Se hai bisogno di qualcosa in particolare dimmi /cerca e il termine di ricerca e io lo farò per te.",
    "Chi è Giuseppe Blando?": "Giuseppe Blando è un cittadino di Arcadia, attuale Presidente della Repubblica",
    "cosa sono i cookie": "I cookie sono piccoli file di testo che i siti web o le applicazioni memorizzano sul tuo computer o sessione per ricordare informazioni sulle tue visite. Possono essere utilizzati per tenere traccia delle tue preferenze, autenticarti e migliorare l'esperienza utente.",
    "chi ha fondato lumenaria": "La Repubblica di Lumenaria è stata fondata da Filippo Zanetti il 4 febbraio del 2020.",
    "chi ha fondato arcadia": "La Repubblica di Arcadia è stata fondata da Andrea Lazarev l'11 dicembre del 2021.",
    "chi ha fondato leonia": "Leonia è stata fondata da Carlo Cesare Orlando (all'epoca noto come Davide Leone) nel 2019.",
    "qual è la forma peggiore di micronazionalismo": "La forma peggiore di micronazionalismo è l'idionazione. Si tratta di un'entità fondata da una singola persona che si autoproclama leader di uno Stato immaginario senza alcun seguito reale, interazione sociale autentica o vera produzione culturale, agendo unicamente per egocentrismo.",
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
    "chi è davide sciortino": ["chi è davide sciortino", "chi è davide sortino"]
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

# ==================== ALIAS RESOLVER ====================
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
        self.conn.execute("""CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        
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

BYPASS_PRICES = {
    "1h": {"name": "Bypass 1 ora", "arc": 20, "hours": 1},
    "24h": {"name": "Bypass 24 ore", "arc": 100, "hours": 24},
    "7d": {"name": "Bypass 7 giorni", "arc": 500, "hours": 168},
}

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

# ==================== CES VIDEO ====================
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
            print(f"   🔗 Unisco Audio + Video Fluido con sincronizzazione PTS...")
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

# ==================== CLIENT AI ====================
class AIClient:
    count = 0
    
    @classmethod
    def generate(cls, prompt, max_tok=300):
        # Applica gli alias al prompt (nome reale -> alias)
        prompt_with_aliases = AliasResolver.apply_aliases_to_text(prompt)
        
        if GEMINI_API_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
                d = json.dumps({"contents":[{"parts":[{"text":prompt_with_aliases}]}],"generationConfig":{"maxOutputTokens":max_tok,"temperature":0.7}}).encode()
                req = urllib.request.Request(url, data=d, headers={"Content-Type":"application/json"}, method='POST')
                with urllib.request.urlopen(req, timeout=15) as r:
                    j = json.loads(r.read().decode())
                    if "candidates" in j:
                        parts = j["candidates"][0]["content"]["parts"]
                        result = ' '.join([p.get("text","") for p in parts])
                        if result.strip():
                            cls.count += 1
                            cleaned = cls._clean(result)
                            return cleaned
            except Exception as e:
                print(f"⚠️ Errore Gemini: {e}")
                pass
        
        if OPENROUTER_API_KEY:
            try:
                d = json.dumps({"model":"openrouter/free","messages":[{"role":"user","content":prompt_with_aliases}],"max_tokens":max_tok,"temperature":0.7}).encode()
                req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=d,
                    headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}, method='POST')
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.loads(r.read().decode())
                    if "choices" in j:
                        cls.count += 1
                        cleaned = cls._clean(j["choices"][0]["message"]["content"])
                        return cleaned
            except Exception as e:
                print(f"⚠️ Errore OpenRouter: {e}")
                pass
        
        return None
    
    @classmethod
    def _clean(cls, text):
        """Pulisce la risposta e restituisce i nomi reali"""
        text = text.strip()
        
        # Rimuove righe di metadati
        text = re.sub(r'(?i)^User Safety:\s*\w+\s*\n?', '', text)
        text = re.sub(r'(?i)^Safety:\s*\w+\s*\n?', '', text)
        text = re.sub(r'(?i)^(okay|let me|dunque|allora|vediamo|analizzo|devo|i need|first|penso|credo|echo).*?[:\.]\s*', '', text)
        
        # Rimuove righe indesiderate
        lines = []
        for l in text.split('\n'):
            if not re.match(r'(?i)^(okay|let me|dunque|quindi|devo|i need|the user|first|user safety|safety)', l.strip()):
                lines.append(l)
        text = '\n'.join(lines).strip() if lines else text
        
        # Restituisci i nomi reali
        text = AliasResolver.restore_real_names_to_text(text)
        
        return text

class ArcadiaBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = MessageDB(SCRIPT_DIR / "processed.db")
        self.loader = FileLoader(DATA_FOLDER)
        self.knowledge = KnowledgeBase(DATA_FOLDER)
        self.msgs = 0
        self.dups = 0
        self.username = ""
        self.id = 0
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
            print(f"ℹ️ Info bot caricate all'avvio: @{self.username} (ID: {self.id})")
        else:
            print("⚠️ Impossibile caricare le info del bot durante l'init!")
    
    def test(self):
        r = self.api("getMe")
        if r.get("ok"):
            self.username = r['result'].get('username', '')
            self.id = r['result'].get('id', 0)
            print(f"✅ Bot attivo: @{self.username} (ID: {self.id})")
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
                self.send(chat_id, "❌ Impossibile ottenere il file.")
                return

            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"

            img_temp = TEMP_FOLDER / f"img_{user_id}_{int(time.time())}.jpg"
            
            req = urllib.request.Request(file_url, headers={'User-Agent': 'ArcadiaAI/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(img_temp, 'wb') as f:
                    f.write(resp.read())

            if not img_temp.exists() or img_temp.stat().st_size < 100:
                self.send(chat_id, "❌ Il file immagine non è stato scaricato correttamente.")
                img_temp.unlink(missing_ok=True)
                return

            if HAS_IMAGE_VIEWER:
                try:
                    viewer = CESImageViewer()
                    raw_description = viewer.analizza(str(img_temp))
                except Exception as e:
                    raw_description = f"❌ Errore durante l'analisi dell'immagine: {str(e)}"
            else:
                raw_description = "❌ CES Image Viewer non è disponibile."

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
            self.send(chat_id, f"❌ Errore di rete durante il download dell'immagine: {str(e)}")
        except Exception as e:
            self.send(chat_id, f"❌ Errore durante l'analisi dell'immagine: {str(e)}")
            print(f"❌ Errore in handle_image: {e}")
            import traceback
            traceback.print_exc()

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
        
        if "photo" in msg:
            photo = msg["photo"][-1]
            file_id = photo["file_id"]
            caption = msg.get("caption", "").strip()

            if not caption or any(k in caption.lower() for k in ["analizza", "immagine", "foto", "vedi", "descrivi", "guarda", "che foto", "come sono"]):
                self.handle_image(chat_id, file_id, caption, user_id)
                return
        
        if not text:
            return
        
        is_group = chat_type in ["group", "supergroup"]
        bot_username = self.username.lower() if self.username else ""
        
        is_reply_to_bot = False
        if "reply_to_message" in msg:
            reply_to = msg["reply_to_message"]
            reply_to_from = reply_to.get("from", {})
            reply_to_username = reply_to_from.get("username", "")
            reply_to_id = reply_to_from.get("id", 0)
            
            if (self.id and reply_to_id == self.id) or (bot_username and reply_to_username.lower() == bot_username):
                is_reply_to_bot = True

        registered_commands = [
            "/start", "/aiuto", "/help", "/videohelp", "/video",
            "/codice_sorgente", "/buy_bypass", "/create_vip",
            "/redeem", "/img", "/stats", "/cerca",
            "/vip_status", "/my_vip_codes", "/ai", "/alias_test"
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
        if is_reply_to_bot:
            print("   ↳ 💬 Risposta (reply) diretta al bot.")
        if is_command:
            print(f"   ↳ ✅ Riconosciuto come comando: {first_word}")
        if is_mentioned:
            print(f"   ↳ ✅ Taggato: @{bot_username}")
            
        if is_group:
            if not (is_command or is_mentioned or is_reply_to_bot):
                print("   🚫 Ignorato (Nessun comando, tag o reply esplicita).")
                return

        ai_query = proc_text
        
        if first_word == "/ai":
            ai_query = proc_text[3:].strip()
            if not ai_query:
                self.send(chat_id, "💬 Cosa vuoi chiedermi? Usa `/ai <domanda>`")
                return
        
        if bot_username:
            ai_query = re.sub(r'(?i)@' + re.escape(bot_username), '', ai_query).strip()
        
        ai_query = re.sub(r'\s+', ' ', ai_query).strip()
        
        if first_word == "/start":
            dev = "🔓 Dev" if user_id == DEVELOPER_USER_ID else ""
            self.send(chat_id, f"👋 Ciao {user_name}! ArcadiaAI.\n\n🎬 /video [desc] - Video AI diretto\n🎨 /img [desc] - Immagine\n🎫 /vip [codice] - Riscatta codice VIP\n🖼️ Invia una foto con 'analizza' per descriverla\n💬 Fammi una domanda!\n📋 /aiuto{(' ' + dev) if dev else ''}")
            return
        
        elif first_word in ["/aiuto", "/help"]:
            self.send(chat_id, "🎬 **Comandi ArcadiaAI**\n\n"
                "🎬 /video [stile] [descrizione] - Video AI\n"
                "🎨 /img [desc] - Immagine\n"
                "🖼️ Invia una foto con 'analizza' per descriverla\n"
                "🎫 /vip [codice] - Riscatta codice VIP\n"
                "👨‍💻 /codice_sorgente - Link alla repository\n"
                "📝 /telegraph [tema] - Articolo\n"
                "🔍 /cerca [q] - Web\n"
                "🏦 /buy_bypass - Bypass limiti\n"
                "📊 /stats - Statistiche\n\n"
                "**VIP:**\n"
                "/vip_status - Stato VIP\n"
                "/my_vip_codes - I tuoi codici (Dev)\n\n"
                "💬 Fammi una domanda su micronazioni, Leonia, Arcadia, Lumenaria!\n\n"
                "📌 **Per farmi una domanda in un gruppo:**\n"
                "• Usa `/ai <domanda>`\n"
                "• Oppure taggami con `@{self.username} <domanda>`")
            return
        
        elif first_word == "/videohelp":
            self.send(chat_id, "🎬 **CES Video** - Text-to-Video Diretto\n\n"
                "/video [stile] [descrizione]\n"
                "Stili: cinematic, anime, realistic, artistic\n\n"
                "1 video ogni 15 min (gratuito)\n"
                "🎫 /vip per codici promozionali\n"
                "🏦 /buy_bypass per illimitati")
            return
        
        elif first_word == "/alias_test":
            if not WIKIALIAS:
                self.send(chat_id, "⚠️ **Nessun alias caricato!**\n\n"
                    "Verifica che il file `wikialias.json` esista nella stessa cartella di ESEMPIO.py\n\n"
                    "Il file deve essere in formato JSON valido, ad esempio:\n"
                    "```json\n"
                    "{\n"
                    '  "Mirko Orsato": "Mirko Yuri Donato",\n'
                    '  "Salvatore Shelby": "Salvatore Giordano"\n'
                    "}\n"
                    "```")
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
        
        elif first_word == "/ai":
            if not ai_query:
                return
            
            print(f"   🤖 Query AI: '{ai_query}'")
            self.send(chat_id, "🔍 Cerco nelle mie conoscenze...")
            
            search_results = self.knowledge.search(ai_query, max_results=10)
            
            if search_results:
                context_parts = []
                for r in search_results[:5]:
                    context_parts.append(f"📖 Da {r['file']}:\n{r['context']}")
                context = "\n\n".join(context_parts)
                print(f"✅ Trovati {len(search_results)} risultati rilevanti per: {ai_query}")
            else:
                context = "Nessun risultato trovato nei file di conoscenza."
                print(f"⚠️ Nessun risultato utile per: {ai_query}")
            
            system = f"""{IDENTITY_PROMPT}

**CONOSCENZA DAI FILE LOCALI (USA QUESTE INFORMAZIONI CON MASSIMA PRIORITÀ):**
{context}

**REGOLA FONDAMENTALE DI RISPOSTA:**
- Se l'informazione è presente nel testo qui sopra, usala obbligatoriamente per rispondere in modo preciso e dettagliato.
- Se l'informazione non è presente nel testo, usa la tua conoscenza predefinita se ritieni sia affidabile, altrimenti dillo chiaramente.
- CITA LA FONTE (il nome del file .txt) esclusivamente una sola volta in fondo alla risposta, formattata come `[Fonte: nome_file.txt]`.

**DOMANDA DELL'UTENTE:**
{ai_query}

**RISPOSTA (SOLO IN ITALIANO, DIRETTA, SENZA RAGIONAMENTO):**"""
            
            answer = AIClient.generate(system, max_tok=1200)
            
            if answer:
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
            return
        
        elif first_word == "/video":
            args = proc_text[6:].strip()
            if not args:
                self.send(chat_id, "🎬 /video [stile] [descrizione]\nStili: cinematic, anime, realistic, artistic")
                return
            
            try:
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
                
                self.send(chat_id, f"🎥 Genero video {style}...\n⏳ 30-60 secondi...")
                
                result = CESVideo.generate_video(prompt=prompt, style=style)
                
                if result["success"]:
                    self.db.mark_video_generated(user_id)
                    count = self.db.get_video_count(user_id)
                    caption = f"🎬 {result['generated_narration']}\n🎥 {style} | #{count}"
                    
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
                self.send(chat_id, f"❌ Errore imprevisto durante l'elaborazione del video: {str(video_err)}")
            finally:
                video_limiter.finish(user_id)
            return
        
        elif first_word == "/codice_sorgente":
            self.send(chat_id, "📂 Codice sorgente: https://github.com/Mirko-linux/ArcadiaAI-new")
            return
        
        elif first_word == "/buy_bypass":
            prices = "\n".join([f"• {i['name']}: {i['arc']} ARC" for i in BYPASS_PRICES.values()])
            self.send(chat_id, f"👋 Scegli come supportarci:\n\n{prices}\n\nUsa /buy_bypass [nome] per procedere!")
            return
        
        elif first_word == "/create_vip":
            if user_id != DEVELOPER_USER_ID:
                self.send(chat_id, "❌ Solo lo sviluppatore può creare codici VIP.")
                return
            
            parts = proc_text[11:].strip().split()
            
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
        
        elif first_word == "/redeem":
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
        
        elif first_word == "/img":
            p = proc_text[4:].strip()
            if p:
                r = CESImage.generate(p)
                if r["success"]:
                    self.send_photo(chat_id, r["image_url"], f"🎨 {r['prompt'][:200]}")
                else:
                    self.send(chat_id, f"⚠️ {r['error']}")
            return
        
        elif first_word == "/stats":
            mem = self._mem()
            self.send(chat_id, f"💬 {self.msgs} | 🤖 {AIClient.count} | 🎨 {CESImage.count} | {CESVideo.count} | 🧠 {mem:.1f}MB")
            return
        
        elif first_word == "/cerca":
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
                f"Sei un assistente di ricerca. Basandoti ESCLUSIVAMENTE sui seguenti risultati web, "
                f"fornisci una risposta sintetica e diretta alla domanda dell'utente: '{query}'. "
                f"Non inventare informazioni. Cita le fonti usando [1], [2], ecc.\n\n"
                f"RISULTATI WEB:\n{search_context}\n\n"
                f"RISPOSTA SINTETICA (SOLO IN ITALIANO):"
            )
            
            answer = AIClient.generate(synthesis_prompt, max_tok=400)
            
            if answer:
                final_msg = f"🔍 **Risultati per '{query}':**\n\n{answer.strip()}\n\n📎 Fonti:\n" + "\n".join(urls[:3])
                self.send(chat_id, final_msg)
            else:
                msg = f"🔍 Risultati per '{query}':\n\n"
                for r in raw_results:
                    msg += f"• {r['title']}\n  {r['snippet'][:150]}...\n  🔗 {r['url']}\n\n"
                self.send(chat_id, msg)
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
        
        search_results = self.knowledge.search(ai_query, max_results=10)
        
        if search_results:
            context_parts = []
            for r in search_results[:5]:
                context_parts.append(f"📖 Da {r['file']}:\n{r['context']}")
            context = "\n\n".join(context_parts)
            print(f"✅ Trovati {len(search_results)} risultati rilevanti per: {ai_query}")
        else:
            context = "Nessun risultato trovato nei file di conoscenza."
            print(f"⚠️ Nessun risultato utile per: {ai_query}")
        
        system = f"""{IDENTITY_PROMPT}

**CONOSCENZA DAI FILE LOCALI (USA QUESTE INFORMAZIONI CON MASSIMA PRIORITÀ):**
{context}

**REGOLA FONDAMENTALE DI RISPOSTA:**
- Se l'informazione è presente nel testo qui sopra, usala obbligatoriamente per rispondere in modo preciso e dettagliato.
- Se l'informazione non è presente nel testo, usa la tua conoscenza predefinita se ritieni sia affidabile, altrimenti dillo chiaramente.
- CITA LA FONTE (il nome del file .txt) esclusivamente una sola volta in fondo alla risposta, formattata come `[Fonte: nome_file.txt]`.

**DOMANDA DELL'UTENTE:**
{ai_query}

**RISPOSTA (SOLO IN ITALIANO, DIRETTA, SENZA RAGIONAMENTO):**"""
        
        answer = AIClient.generate(system, max_tok=1200)
        
        if answer:
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
        print("🤖 ArcadiaAI - Versione con Polling Persistente")
        print("💾 I messaggi NON vengono persi quando il bot è spento!")
        print("🔒 Sistema alias attivo: i nomi reali non vengono mai inviati alle API!")
        print("🖼️ Analisi immagini integrata!")
        print("📌 /ai funziona in gruppi e supergruppi!")
        print("🔧 /alias_test per testare il sistema di alias")
        print("🌐 Risponde SEMPRE in ITALIANO")
        print("="*60 + "\n")
        
        self.api("deleteWebhook")
        
        last_id = self.db.get_last_update_id()
        print(f"📌 Ultimo update_id elaborato: {last_id}")
        
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
        words = re.findall(r'\w+', text.lower())
        stems = []
        term_freqs = defaultdict(int)
        
        for w in words:
            if w not in self.STOPWORDS and len(w) > 2:
                term_freqs[w] += 1
                stems.append(w)
                
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

# ==================== WEB SEARCH ====================
class WebSearch:
    @staticmethod
    def search(query, n=4):
        results = []
        try:
            encoded_q = urllib.parse.quote_plus(query)
            req = urllib.request.Request(
                f"https://html.duckduckgo.com/html/?q={encoded_q}",
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode('utf-8', errors='ignore')
                
                blocks = re.findall(r'<div class="result__body">.*?</div>', html, re.DOTALL)
                
                for block in blocks[:n]:
                    title_match = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                    snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                    
                    if title_match and snippet_match:
                        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                        snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                        
                        url_match = re.search(r'href=["\']([^"\']+)', title_match.group(0))
                        url = url_match.group(1) if url_match else ""
                        
                        if len(snippet) > 20:
                            results.append({
                                "title": title,
                                "snippet": snippet,
                                "url": url
                            })
        except Exception as e:
            print(f"⚠️ Errore WebSearch: {e}")
            
        return results
    
def main():
    print("\n" + "="*60)
    print("🤖 ArcadiaAI - Versione con Polling Persistente")
    print("💾 I messaggi NON vengono persi quando il bot è spento!")
    print("🔒 I nomi reali NON vengono mai inviati alle API!")
    print("🖼️ Analisi immagini con CES Image Viewer integrata")
    print("📌 /ai funziona in gruppi e supergruppi!")
    print("🔧 /alias_test per testare il sistema")
    print("🌐 Risponde SEMPRE in ITALIANO")
    print("📜 Licenza: MPL 2.0")
    print("="*60 + "\n")
    
    bot = ArcadiaBot()
    if not bot.test():
        sys.exit(1)
    
    print(f"✅ Pronto! RAM: {bot._mem():.1f}MB")
    print(f"📚 Risposte predefinite caricate: {len(RISPOSTE_PREDEFINITE)}")
    print(f"🔍 Trigger configurati: {len(TRIGGER_PHRASES)}")
    print(f"🖼️ CES Image Viewer disponibile: {HAS_IMAGE_VIEWER}")
    print(f"🔒 Alias caricati: {len(WIKIALIAS)}")
    print("\n")
    
    try:
        bot.run_polling()
    except KeyboardInterrupt:
        print("\n👋 Spegnimento bot eseguito correttamente.")
    except Exception as e:
        print(f"\n❌ Errore critico: {e}")
        bot.db.close()
        sys.exit(1)

if __name__ == "__main__":
    main()