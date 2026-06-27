#!/usr/bin/env python3
"""
ArcadiaAI Telegram Bot - CES Video Text-to-Video Diretto
OTTIMIZZATO per 256MB RAM - Download singolo file video
Licenza: MPL 2.0
Versione: 2.0 - Con supporto VIP e codici promozionali
"""
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
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
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

# ==================== IDENTITY PROMPT ====================
IDENTITY_PROMPT = """Sei ArcadiaAI, creato da Mirko Yuri Donato. Licenza MPL 2.0. Rispondi in italiano, 3-5 frasi. NON copiare."""

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

# ==================== DATABASE ====================
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
        
        # ===== NUOVO: Tabella codici VIP =====
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
        # Sviluppatore: sempre illimitato
        if user_id == DEVELOPER_USER_ID and DEVELOPER_USER_ID != 0:
            return True, ""
        
        # Controlla bypass attivo
        bypass = self.has_active_bypass(user_id)
        if bypass:
            plan_name = bypass[0]
            expires = datetime.fromtimestamp(bypass[1])
            return True, f"✅ Bypass: {plan_name} (fino al {expires.strftime('%d/%m %H:%M')})"
        
        # Controlla cooldown normale (15 minuti)
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
    
    # ===== NUOVO: Metodi per codici VIP =====
    def create_vip_code(self, code, plan, duration_hours, created_by, max_uses=1):
        """Crea un codice VIP"""
        self.conn.execute(
            "INSERT INTO vip_codes (code, plan, duration_hours, created_by, created_at, max_uses) VALUES (?,?,?,?,?,?)",
            (code, plan, duration_hours, created_by, time.time(), max_uses)
        )
        self.conn.commit()
        return code

    def redeem_vip_code(self, code, user_id):
        """Riscatta un codice VIP"""
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
        
        # Marca come usato
        self.conn.execute(
            "UPDATE vip_codes SET used_by=?, used_at=?, current_uses=current_uses+1 WHERE code=?",
            (user_id, time.time(), code)
        )
        
        # Attiva bypass
        tx_id = f"VIP-{user_id}-{int(time.time())}"
        self.conn.execute(
            "INSERT INTO bypass_purchases (tx_id, user_id, plan, arc_amount, purchased_at, expires_at, verified) VALUES (?,?,?,0,?,?,1)",
            (tx_id, user_id, f"VIP: {plan}", time.time(), time.time() + duration_hours * 3600)
        )
        self.conn.commit()
        
        return plan, f"✅ VIP attivato: {plan} per {duration_hours} ore"

    def list_vip_codes(self, user_id=None):
        """Lista codici VIP creati"""
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

# ===== PREZZI BYPASS AGGIORNATI =====
BYPASS_PRICES = {
    "1h": {"name": "Bypass 1 ora", "arc": 20, "hours": 1},
    "24h": {"name": "Bypass 24 ore", "arc": 100, "hours": 24},
    "7d": {"name": "Bypass 7 giorni", "arc": 500, "hours": 168},
}

# ===== PIANI ABBONAMENTO =====
SUBSCRIPTION_PLANS = {
    "base": {"name": "BASE", "price": 0, "videos_per_day": 3, "research": False},
    "plus": {"name": "Plus", "price": 25, "videos_per_day": 30, "research": True},
    "pro": {"name": "Pro", "price": 50, "videos_per_day": 999, "research": True},
}

BANCA_CENTRALE = ["@BancaCentraleArcadia"]

# ==================== CES IMAGE ====================
class CESImage:
    BANNED = ["nudo","nudità","porn","porno","sessuale","sesso","sex","nsfw","xxx","erotico"]
    count = 0
    
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
    """
    CES Video - Generazione VIDEO FLUIDO su VPS da 256MB RAM
    PRINCIPIO: NO API KEY e ZERO MEMORIA LOCALE
    Logica: Genera 4 frame coerenti su Pollinations con anti-429
    e usa FFmpeg minterpolate (blend) per calcolare i frame mancanti a 24fps.
    """
    BANNED = ["nudo","nudità","porn","porno","sessuale","sesso","sex","nsfw","xxx","erotico"]
    count = 0
    
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
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
            url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=768&height=432&nologo=true&seed={current_seed}&cb={cache_bust}"
            
            frame_path = job_dir / f"seq_{i+1:04d}.png"
            
            download_success = False
            max_tentativi = 3
            
            for tentativo in range(max_tentativi):
                try:
                    if i > 0 or tentativo > 0:
                        attesa = random.uniform(3.0, 5.5) + (tentativo * 3)
                        print(f"      ⏳ Pausa strategica anti-429 per {attesa:.1f}s...")
                        time.sleep(attesa)
                    
                    req = urllib.request.Request(url, headers=cls.HEADERS)
                    with urllib.request.urlopen(req, timeout=45) as response:
                        with open(frame_path, 'wb') as out:
                            while True:
                                chunk = response.read(16384)
                                if not chunk: break
                                out.write(chunk)
                    
                    if frame_path.exists() and frame_path.stat().st_size > 15000:
                        frame_paths.append(frame_path)
                        print(f"      ✅ [Frame {i+1}/4] Scaricato al tentativo {tentativo+1}")
                        download_success = True
                        break
                        
                except urllib.error.HTTPError as he:
                    if he.code == 429:
                        print(f"      ⚠️ Risposta 429 al tentativo {tentativo+1}. Riprovo...")
                    else:
                        print(f"      ❌ Errore HTTP {he.code} al tentativo {tentativo+1}")
                except Exception as e:
                    print(f"      ❌ Errore/Timeout ({e}) al tentativo {tentativo+1}")
                
                if frame_path.exists():
                    try: frame_path.unlink()
                    except: pass
            
            if not download_success:
                print(f"      💥 [Frame {i+1}/4] Fallito definitivamente dopo {max_tentativi} tentativi.")
            
            gc.collect()
            
        if len(frame_paths) < 2:
            return {"success": False, "error": "Il server AI è sovraccarico. Riprova tra 1 minuto."}
        
        ffmpeg = cls._find_ffmpeg()
        if not ffmpeg:
            return {"success": False, "error": "FFmpeg non configurato."}
            
        video_temp = job_dir / "video_silent.mp4"
        seq_pattern = str(job_dir / "seq_%04d.png").replace('\\', '/')
        output_str = str(video_temp).replace('\\', '/')
        
        # Filtro FFmpeg ottimizzato per 256MB RAM
        video_filter = (
            'scale=640:360,'
            'minterpolate=fps=24:mi_mode=blend,'
            'fade=in:0:10,fade=out:st=35:d=10'
        )
        
        print(f"   ⚙️ FFmpeg sta calcolando i frame intermedi per fluidificare...")
        cmd_video = [
            ffmpeg, '-y', '-nobuffer',
            '-framerate', str(fps),
            '-i', seq_pattern,
            '-vf', video_filter,
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-crf', '32',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-threads', '1',
            output_str
        ]
        
        subprocess.run(cmd_video, capture_output=True, timeout=40)
        
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
        except:
            pass
            
        final_path = job_dir / "video_final.mp4"
        if audio_path.exists():
            print(f"   🔗 Unisco Audio + Video Fluido...")
            cmd_merge = [
                ffmpeg, '-y', '-nobuffer',
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

# ==================== BOT ====================
class ArcadiaBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = MessageDB(SCRIPT_DIR / "processed.db")
        self.loader = FileLoader(DATA_FOLDER)
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
            self.send(chat_id, f"👋 Ciao {user_name}! ArcadiaAI.\n\n🎬 /video [desc] - Video AI diretto\n🎨 /img [desc] - Immagine\n🎫 /vip [codice] - Riscatta codice VIP\n📋 /aiuto{(' ' + dev) if dev else ''}")
            return
        
        elif text in ["/aiuto", "/help"]:
            self.send(chat_id, "🎬 **Comandi ArcadiaAI**\n\n"
                "🎬 /video [stile] [desc] - Video AI\n"
                "🎨 /img [desc] - Immagine\n"
                "🎫 /vip [codice] - Riscatta codice VIP\n"
                "📝 /telegraph [tema] - Articolo\n"
                "🔍 /cerca [q] - Web\n"
                "🏦 /buy_bypass - Bypass limiti\n"
                "📊 /stats - Statistiche\n\n"
                "**VIP:**\n"
                "/my_vip_codes - I tuoi codici (Dev)")
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
            
            can_process, message, pos = video_limiter.can_process(user_id, self.db)
            if not can_process:
                self.send(chat_id, message)
                return
            
            try:
                styles = ["cinematic", "anime", "realistic", "artistic"]
                style = "cinematic"
                prompt = args
                first_word = args.split()[0].lower()
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
                    method = result.get("method", "direct")
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
            finally:
                video_limiter.finish(user_id)
            return
        
        # ==================== BYPASS ====================
        elif text == "/buy_bypass":
            prices = "\n".join([f"• {i['name']}: {i['arc']} ARC" for i in BYPASS_PRICES.values()])
            self.send(chat_id, f"🏦 **Bypass Limite Video**\n\n{prices}\n\n/buy [piano] - Genera codice\n/prices - Listino\n/bypass_status - Stato\n\n💳 **Abbonamenti:**\nBASE: 0 ARC/mese\nPlus: 25 ARC/mese\nPro: 50 ARC/mese")
            return
        
        elif text == "/prices":
            prices = "\n".join([f"• {i['name']}: {i['arc']} ARC ({i['hours']}h)" for i in BYPASS_PRICES.values()])
            self.send(chat_id, f"🏦 **Listino:**\n{prices}\n\n💳 **Abbonamenti:**\nBASE: 0 ARC/mese\nPlus: 25 ARC/mese\nPro: 50 ARC/mese")
            return
        
        elif text.startswith("/buy "):
            plan = text[5:].strip()
            if plan not in BYPASS_PRICES:
                self.send(chat_id, "❌ Piano non valido. /prices")
                return
            info = BYPASS_PRICES[plan]
            tx_id = self.db.create_transaction(user_id, info['name'], info['arc'], info['hours'])
            self.send(chat_id, f"🏦 **Ordine creato**\n\n{info['name']}: {info['arc']} ARC\nCodice: `{tx_id}`\n\nInvia ARC a @BancaCentraleArcadia\nCausale: {tx_id}")
            return
        
        elif text == "/bypass_status":
            bypass = self.db.has_active_bypass(user_id)
            if bypass:
                plan, expires = bypass
                exp = datetime.fromtimestamp(expires)
                rem = exp - datetime.now()
                self.send(chat_id, f"✅ **{plan}** attivo\nScade: {exp.strftime('%d/%m %H:%M')}\nRimasto: {rem.days}g {rem.seconds//3600}h")
            else:
                self.send(chat_id, "❌ Nessun bypass.\n💡 /buy_bypass o /vip")
            return
        
        elif text.startswith("/verify_tx "):
            username = msg["from"].get("username", "")
            if f"@{username}" not in BANCA_CENTRALE and username not in BANCA_CENTRALE:
                self.send(chat_id, "❌ Solo Banca Centrale.")
                return
            tx_id = text[11:].strip()
            result = self.db.verify_transaction(tx_id, f"@{username}")
            if result:
                target, plan, amount = result
                self.send(chat_id, f"✅ Verificato: {plan} per utente {target}")
                self.send(target, f"✅ **{plan}** attivato! Bypass video illimitato.")
            else:
                self.send(chat_id, "❌ Transazione non trovata")
            return
        
        # ==================== COMANDI VIP ====================
        elif text.startswith("/create_vip "):
            # Solo sviluppatore può creare codici VIP
            if user_id != DEVELOPER_USER_ID:
                self.send(chat_id, "❌ Solo lo sviluppatore può creare codici VIP.")
                return
            
            # Formato: /create_vip [durata] [codice] [max_usi]
            parts = text[11:].strip().split()
            
            if len(parts) < 2:
                self.send(chat_id,
                    "🎫 **Crea Codice VIP**\n\n"
                    "/create_vip [ore] [codice] [max_usi]\n\n"
                    "Esempi:\n"
                    "/create_vip 720 ARCADIA-GRAZIE-AMICO 1\n"
                    "  (30 giorni, usa il codice una volta)\n"
                    "/create_vip 168 PREMIO-TOP 3\n"
                    "  (7 giorni, usabile da 3 persone)")
                return
            
            try:
                duration = int(parts[0])
            except:
                self.send(chat_id, "❌ Durata non valida. Usa ore (es. 720 per 30 giorni)")
                return
            
            code = parts[1].upper().replace(' ', '-')
            max_uses = int(parts[2]) if len(parts) > 2 else 1
            
            # Calcola nome piano
            if duration >= 720:
                plan = f"VIP {duration//24} giorni"
            elif duration >= 168:
                plan = f"VIP {duration//24} giorni"
            elif duration >= 24:
                plan = f"VIP {duration//24} ore" if duration > 24 else f"VIP {duration} ore"
            else:
                plan = f"VIP {duration} ore"
            
            self.db.create_vip_code(code, plan, duration, user_id, max_uses)
            
            self.send(chat_id,
                f"🎫 **Codice VIP Creato!**\n\n"
                f"Codice: `{code}`\n"
                f"Piano: {plan}\n"
                f"Durata: {duration} ore ({duration//24} giorni)\n"
                f"Usi: {max_uses}\n\n"
                f"📤 Invia questo codice al tuo amico:\n"
                f"`{code}`\n\n"
                f"Lui dovrà usare: /vip {code}")

        elif text.startswith("/vip "):
            # Riscatta codice VIP
            code = text[4:].strip().upper()
            
            if not code:
                self.send(chat_id, "🎫 /vip [codice]\nRiscatta un codice VIP regalato")
                return
            
            plan, message = self.db.redeem_vip_code(code, user_id)
            
            if plan:
                self.send(chat_id,
                    f"🎉 **{message}**\n\n"
                    f"Piano: {plan}\n"
                    f"Bypass video attivo!\n"
                    f"Usa /bypass_status per i dettagli")
            else:
                self.send(chat_id, f"❌ {message}")

        elif text == "/my_vip_codes":
            # Solo sviluppatore vede i codici creati
            if user_id != DEVELOPER_USER_ID:
                self.send(chat_id, "❌ Accesso negato.")
                return
            
            codes = self.db.list_vip_codes(user_id)
            if codes:
                clist = "\n".join([
                    f"• `{c[0]}` - {c[1]} ({c[2]}h) - Usi: {c[4]}/{c[3]} - Utente: {c[5] or 'libero'}"
                    for c in codes
                ])
                self.send(chat_id, f"🎫 **I tuoi codici VIP:**\n{clist}")
            else:
                self.send(chat_id, "📭 Nessun codice VIP creato")

        elif text == "/vip_help":
            self.send(chat_id,
                "🎫 **Comandi VIP**\n\n"
                "/vip [codice] - Riscatta un codice VIP\n"
                "/vip_status - Stato del tuo VIP\n"
                "/my_vip_codes - I tuoi codici (Dev)\n"
                "/create_vip [ore] [codice] [usi] - Crea codice (Dev)\n\n"
                "**Piani VIP:**\n"
                "• 24 ore: Codice usa e getta\n"
                "• 7 giorni: Multi-uso (fino a 3 persone)\n"
                "• 30 giorni: Abbonamento premium")
            return

        elif text == "/vip_status":
            bypass = self.db.has_active_bypass(user_id)
            if bypass:
                plan, expires = bypass
                exp = datetime.fromtimestamp(expires)
                rem = exp - datetime.now()
                self.send(chat_id, f"✅ **{plan}** attivo\nScade: {exp.strftime('%d/%m %H:%M')}\nRimasto: {rem.days}g {rem.seconds//3600}h")
            else:
                self.send(chat_id, "❌ Nessun VIP attivo.\n🎫 /vip [codice] per riscattare un codice")
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
        
        # ==================== AI ====================
        self.send(chat_id, "🤔 Pensando...")
        docs = self.loader.get_all_content()[:2000]
        system = f"{IDENTITY_PROMPT}\n\nCONOSCENZA: Leonia (Carlo Cesare Orlando), Lumenaria (Filippo Zanetti, 2020), Arcadia (Andrea Lazarev, 2021).\nDOCS: {docs}\n\nNON copiare. Rielabora."
        answer = AIClient.generate(f"{system}\n\nDomanda: {text}\n\nRispondi in 3-5 frasi originali.", 400)
        if answer:
            self.send(chat_id, answer.strip())
        else:
            web = WebSearch.search(text)
            self.send(chat_id, "🌐 " + "\n\n".join(web[:2]) if web else "⚠️ Non riesco a rispondere.")
        
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

class WebSearch:
    @staticmethod
    def search(query, n=3):
        results = []
        try:
            req = urllib.request.Request(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}",
                headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode('utf-8')
            for snippet in re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)[:n]:
                clean = re.sub(r'<[^>]+>', '', snippet).strip()
                if clean:
                    results.append(clean[:300])
        except:
            pass
        return results

def main():
    print("\n" + "="*60)
    print("🤖 ArcadiaAI - CES Video Text-to-Video Diretto")
    print("💾 256MB RAM - Download singolo file")
    print("📜 Licenza: MPL 2.0")
    print("="*60 + "\n")
    
    bot = ArcadiaBot()
    if not bot.test():
        sys.exit(1)
    
    print(f"✅ Pronto! RAM: {bot._mem():.1f}MB\n")
    
    try:
        bot.run_polling()
    except Exception as e:
        print(f"\n❌ {e}")
        bot.db.close()
        sys.exit(1)

if __name__ == "__main__":
    main()