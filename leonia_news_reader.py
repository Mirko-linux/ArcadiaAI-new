"""
leonia_news_reader.py - Modulo per la lettura on-demand delle notizie da Leonia+ Log DB
Integrazione per ArcadiaAI
"""

import os
import re
import time
import json
import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import threading
import requests
import logging

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class NewsArticle:
    """Rappresenta un articolo di notizie estratto dal log"""
    title: str
    link: str
    raw_text: str
    timestamp: float
    message_id: int
    source: Optional[str] = None  # ANSA, TGCom24, RaiNews, Repubblica, Corriere
    category: Optional[str] = None
    relevance_score: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "raw_text": self.raw_text[:200] + "..." if len(self.raw_text) > 200 else self.raw_text,
            "timestamp": self.timestamp,
            "timestamp_str": datetime.fromtimestamp(self.timestamp).strftime('%d/%m/%Y %H:%M'),
            "category": self.category,
            "relevance_score": self.relevance_score
        }

class LeoniaNewsCache:
    """Cache locale per le notizie lette dal canale log"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leonia_news_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER UNIQUE,
                title TEXT,
                link TEXT,
                source TEXT,
                raw_text TEXT,
                timestamp REAL,
                category TEXT,
                relevance_score REAL,
                cached_at REAL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_leonia_news_timestamp 
            ON leonia_news_cache(timestamp DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_leonia_news_category 
            ON leonia_news_cache(category)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_leonia_news_source 
            ON leonia_news_cache(source)
        """)
        
        conn.commit()
        conn.close()
    
    def save_articles(self, articles: List[NewsArticle]):
        """Salva gli articoli nella cache"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        for article in articles:
            cursor.execute("""
                INSERT OR REPLACE INTO leonia_news_cache 
                (message_id, title, link, source, raw_text, timestamp, category, relevance_score, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.message_id,
                article.title,
                article.link,
                article.source,
                article.raw_text,
                article.timestamp,
                article.category,
                article.relevance_score,
                time.time()
            ))
        
        conn.commit()
        conn.close()
    
    def get_recent_articles(self, limit: int = 100) -> List[NewsArticle]:
        """Recupera gli articoli più recenti dalla cache"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT message_id, title, link, source, raw_text, timestamp, category, relevance_score
            FROM leonia_news_cache
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        articles = []
        for row in rows:
            articles.append(NewsArticle(
                title=row[1],
                link=row[2],
                source=row[3],
                raw_text=row[4],
                timestamp=row[5],
                message_id=row[0],
                category=row[6],
                relevance_score=row[7] or 0.0
            ))
        
        return articles
    
    def get_cached_hashes(self) -> set:
        """Recupera gli hash dei messaggi già in cache"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT message_id FROM leonia_news_cache")
        rows = cursor.fetchall()
        conn.close()
        return {row[0] for row in rows}
    
    def clear_old_cache(self, days: int = 3):
        """Pulisce le voci più vecchie di X giorni (le notizie sono fresche)"""
        cutoff = time.time() - (days * 86400)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leonia_news_cache WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"🧹 [NewsCache] Rimosse {deleted} voci più vecchie di {days} giorni")
        return deleted
    
    def get_stats(self) -> Dict:
        """Restituisce statistiche sulla cache"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM leonia_news_cache")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT source) FROM leonia_news_cache")
        sources = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM leonia_news_cache")
        row = cursor.fetchone()
        
        conn.close()
        
        return {
            "total_articles": total,
            "unique_sources": sources,
            "oldest": datetime.fromtimestamp(row[0]).strftime('%d/%m %H:%M') if row[0] else "N/A",
            "newest": datetime.fromtimestamp(row[1]).strftime('%d/%m %H:%M') if row[1] else "N/A"
        }

class LeoniaNewsReader:
    """Lettore di notizie on-demand dal canale log di Leonia+"""
    
    # Pattern per estrarre i dati dal log
    LOG_PATTERN = re.compile(
        r'LOG_DATA\s*\n'
        r'Titolo:\s*(.+?)\s*\n'
        r'Link:\s*(.+?)\s*\n?',
        re.IGNORECASE | re.DOTALL
    )
    
    # Mappatura fonti per emoji
    SOURCE_EMOJIS = {
        "ANSA": "📰",
        "TGCom24": "📺",
        "RaiNews": "📻",
        "Repubblica": "📰",
        "Corriere": "📰",
        "sconosciuta": "📌"
    }
    
    # Mappatura fonti per colore/categoria
    SOURCE_CATEGORIES = {
        "ANSA": "Generale",
        "TGCom24": "Cronaca",
        "RaiNews": "Istituzionale",
        "Repubblica": "Politica",
        "Corriere": "Attualità"
    }
    
    def __init__(self, bot_token: str, channel_id: str, cache_db_path: str = "leonia_news_cache.db"):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.cache = LeoniaNewsCache(cache_db_path)
        self.llm_client = None  # Verrà impostato dal bot principale
        
    def set_llm_client(self, client):
        """Imposta il client LLM per l'analisi delle notizie"""
        self.llm_client = client
    
    def _fetch_channel_history(self, limit: int = 100) -> List[Dict]:
        """
        Recupera gli ultimi messaggi dal canale Telegram usando l'API
        """
        if not self.bot_token or not self.channel_id:
            logger.error("❌ [NewsReader] Bot token o channel ID non configurato")
            return []
        
        try:
            # Verifica che il canale sia accessibile
            url = f"https://api.telegram.org/bot{self.bot_token}/getChat"
            response = requests.get(url, params={"chat_id": self.channel_id}, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ [NewsReader] Canale non accessibile: {response.status_code}")
                return []
            
            # Recupera i messaggi - usiamo getUpdates con offset
            # Nota: il bot deve essere amministratore del canale
            all_messages = []
            offset = 0
            max_attempts = 10
            
            while len(all_messages) < limit and max_attempts > 0:
                response = requests.get(
                    f"https://api.telegram.org/bot{self.bot_token}/getUpdates",
                    params={
                        "offset": offset,
                        "limit": min(100, limit - len(all_messages)),
                        "timeout": 30,
                        "allowed_updates": ["channel_post", "message"]
                    },
                    timeout=35
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ [NewsReader] Errore getUpdates: {response.status_code}")
                    break
                
                data = response.json()
                if not data.get("ok"):
                    logger.error(f"❌ [NewsReader] API error: {data.get('description', 'Unknown error')}")
                    break
                
                updates = data.get("result", [])
                if not updates:
                    break
                
                for update in updates:
                    offset = update["update_id"] + 1
                    
                    # Controlla se è un messaggio del canale
                    message = update.get("channel_post") or update.get("message")
                    if not message:
                        continue
                    
                    # Verifica che il messaggio provenga dal canale corretto
                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    
                    # Confronta con l'ID del canale
                    if str(chat_id) != str(self.channel_id):
                        # Prova a confrontare con il username
                        if chat.get("username", "").lower() != self.channel_id.lower():
                            continue
                    
                    # Estrai il testo
                    text = message.get("text", "")
                    if not text or "LOG_DATA" not in text:
                        continue
                    
                    # Aggiungi il messaggio alla lista
                    all_messages.append({
                        "message_id": message["message_id"],
                        "text": text,
                        "date": message["date"],
                        "chat_id": chat_id
                    })
                
                max_attempts -= 1
                time.sleep(0.5)
            
            logger.info(f"✅ [NewsReader] Recuperati {len(all_messages)} messaggi dal canale log")
            return all_messages
            
        except requests.exceptions.Timeout:
            logger.error("❌ [NewsReader] Timeout durante il recupero dei messaggi")
            return []
        except Exception as e:
            logger.error(f"❌ [NewsReader] Errore imprevisto: {e}")
            return []
    
    def _detect_source(self, link: str) -> str:
        """Rileva la fonte della notizia dall'URL"""
        if not link:
            return "sconosciuta"
        
        link_lower = link.lower()
        if "ansa.it" in link_lower:
            return "ANSA"
        elif "tgcom24.mediaset.it" in link_lower:
            return "TGCom24"
        elif "rainews.it" in link_lower:
            return "RaiNews"
        elif "repubblica.it" in link_lower:
            return "Repubblica"
        elif "corriere.it" in link_lower:
            return "Corriere"
        else:
            return "sconosciuta"
    
    def _parse_log_messages(self, messages: List[Dict]) -> List[NewsArticle]:
        """
        Parser i messaggi del log per estrarre titoli e link
        """
        articles = []
        existing_ids = self.cache.get_cached_hashes()
        
        for msg in messages:
            text = msg.get("text", "")
            message_id = msg.get("message_id")
            
            # Salta se già in cache
            if message_id in existing_ids:
                continue
            
            # Cerca il pattern LOG_DATA
            match = self.LOG_PATTERN.search(text)
            if not match:
                continue
            
            title = match.group(1).strip()
            link = match.group(2).strip()
            
            # Pulisci titolo e link da eventuali caratteri di controllo
            title = re.sub(r'[\r\n]+', ' ', title).strip()
            link = link.strip()
            
            # Verifica che il link sia valido
            if not link.startswith(('http://', 'https://')):
                link = f"https://{link}" if link else ""
            
            # Rileva la fonte
            source = self._detect_source(link)
            
            # Crea l'articolo
            article = NewsArticle(
                title=title,
                link=link,
                source=source,
                raw_text=text,
                timestamp=msg.get("date", time.time()),
                message_id=message_id
            )
            
            articles.append(article)
        
        # Salva gli articoli in cache
        if articles:
            self.cache.save_articles(articles)
            logger.info(f"📰 [NewsReader] Salvati {len(articles)} nuovi articoli in cache")
        
        # Recupera anche gli articoli già in cache per avere più dati
        cached_articles = self.cache.get_recent_articles(100)
        
        # Combina: prima i nuovi, poi quelli in cache (evita duplicati per message_id)
        existing_ids_in_articles = {a.message_id for a in articles}
        all_articles = articles.copy()
        
        for cached in cached_articles:
            if cached.message_id not in existing_ids_in_articles:
                all_articles.append(cached)
        
        # Ordina per timestamp (più recenti prima)
        all_articles.sort(key=lambda x: x.timestamp, reverse=True)
        
        return all_articles
    
    def _analyze_with_llm(self, articles: List[NewsArticle], query: str) -> List[NewsArticle]:
        """
        Usa l'LLM per filtrare e categorizzare le notizie in base alla richiesta
        """
        if not articles:
            return []
        
        if not query or query.strip().lower() in ["ultime notizie", "novità", "aggiornamenti", "notizie", "ultimora"]:
            # Richiesta generica: restituisci tutte le notizie
            for article in articles[:10]:
                article.relevance_score = 1.0
                article.category = self.SOURCE_CATEGORIES.get(article.source, "Generale")
            return articles[:10]
        
        # Prepara il prompt per l'LLM
        system_prompt = """Sei un analista di notizie esperto. Devi analizzare una lista di titoli di notizie provenienti da diverse fonti italiane (ANSA, TGCom24, RaiNews, Repubblica, Corriere).
        Per ogni notizia:
        1. Determinare se è rilevante per la richiesta dell'utente
        2. Assegnare un punteggio di rilevanza da 0 a 1 (0=irrilevante, 1=perfettamente pertinente)
        3. Classificare la notizia in una categoria appropriata
        
        Categorie possibili: Politica, Economia, Cronaca, Sport, Cultura, Tecnologia, Salute, Ambiente, Internazionale, Spettacolo, Attualità
        
        Rispondi SOLO in formato JSON con questa struttura:
        {
            "results": [
                {
                    "title": "Titolo originale",
                    "relevance": 0.9,
                    "category": "Politica"
                }
            ]
        }"""
        
        # Costruisci la lista dei titoli con fonte
        titles_text = "\n".join([f"{i+1}. [{article.source}] {article.title}" for i, article in enumerate(articles[:30])])
        
        user_prompt = f"""Richiesta utente: "{query}"

Titoli da analizzare:
{titles_text}

Analizza i titoli e restituisci il JSON con i punteggi di rilevanza e le categorie."""
        
        try:
            # Usa il client LLM del bot
            if self.llm_client and hasattr(self.llm_client, 'generate'):
                response = self.llm_client.generate(
                    f"{system_prompt}\n\n{user_prompt}",
                    max_tok=800
                )
                
                if response:
                    # Estrai il JSON dalla risposta
                    json_match = re.search(r'\{[\s\S]*\}', response)
                    if json_match:
                        data = json.loads(json_match.group())
                        results = data.get("results", [])
                        
                        # Aggiorna gli articoli con i punteggi
                        scored_articles = []
                        for article in articles[:30]:
                            # Cerca il punteggio per questo titolo
                            for result in results:
                                if result.get("title", "").strip().lower() == article.title.strip().lower():
                                    article.relevance_score = result.get("relevance", 0.5)
                                    article.category = result.get("category", "Generale")
                                    break
                            else:
                                # Se non trovato, usa la categoria predefinita della fonte
                                article.relevance_score = 0.3
                                article.category = self.SOURCE_CATEGORIES.get(article.source, "Generale")
                            
                            if article.relevance_score >= 0.4:  # Soglia di rilevanza
                                scored_articles.append(article)
                        
                        # Ordina per rilevanza
                        scored_articles.sort(key=lambda x: x.relevance_score, reverse=True)
                        
                        logger.info(f"📰 [NewsReader] LLM ha analizzato {len(scored_articles)} notizie rilevanti")
                        return scored_articles[:15]  # Massimo 15 notizie
                        
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ [NewsReader] Errore parsing JSON dall'LLM: {e}")
        except Exception as e:
            logger.warning(f"⚠️ [NewsReader] Errore durante l'analisi LLM: {e}")
        
        # Fallback: filtraggio semplice per parole chiave
        keywords = query.lower().split()
        filtered = []
        for article in articles:
            title_lower = article.title.lower()
            score = 0.0
            
            # Parole chiave nel titolo
            for kw in keywords:
                if kw in title_lower:
                    score += 0.4
                    if len(kw) > 5:  # Parole più lunghe hanno più peso
                        score += 0.2
            
            # Bonus per fonte specifica se menzionata
            source_keywords = {
                "ANSA": ["ansa", "agenzia"],
                "TGCom24": ["tgcom", "mediaset"],
                "RaiNews": ["rai", "rai news"],
                "Repubblica": ["repubblica"],
                "Corriere": ["corriere"]
            }
            
            for src, src_kws in source_keywords.items():
                if any(kw in query.lower() for kw in src_kws):
                    if article.source == src:
                        score += 0.3
            
            # Penalizza le parole negative
            negative_words = ["non", "nessuno", "senza", "contro", "no"]
            for nw in negative_words:
                if nw in title_lower:
                    score -= 0.2
            
            article.relevance_score = max(0, min(1, score))
            article.category = self.SOURCE_CATEGORIES.get(article.source, "Generale")
            
            if article.relevance_score > 0:
                filtered.append(article)
        
        filtered.sort(key=lambda x: x.relevance_score, reverse=True)
        return filtered[:10]
    
    def get_news(self, query: str, limit: int = 100) -> Dict:
        """
        Punto di ingresso principale: recupera e analizza le notizie
        
        Args:
            query: La richiesta dell'utente (es. "ultime novità su politica")
            limit: Numero massimo di messaggi da leggere
            
        Returns:
            Dict con i risultati
        """
        try:
            # 1. Recupera i messaggi dal canale
            messages = self._fetch_channel_history(limit)
            
            if not messages:
                # Prova a usare la cache
                cached = self.cache.get_recent_articles(limit)
                if cached:
                    logger.info("📰 [NewsReader] Usando cache locale (canale non raggiungibile)")
                    articles = cached
                else:
                    return {
                        "success": False,
                        "error": "Impossibile recuperare le notizie. Canale log non raggiungibile o cache vuota.\n\n" +
                                 "Verifica che il bot sia amministratore del canale e che il channel_id sia corretto.",
                        "articles": []
                    }
            else:
                # 2. Parsing dei messaggi
                articles = self._parse_log_messages(messages)
            
            if not articles:
                return {
                    "success": False,
                    "error": "Nessuna notizia trovata nel canale log. Le notizie potrebbero essere scadute.",
                    "articles": []
                }
            
            # 3. Analisi con LLM se richiesta specifica
            if query and query.strip().lower() not in ["ultime notizie", "novità", "aggiornamenti", "notizie", "ultimora"]:
                filtered_articles = self._analyze_with_llm(articles, query)
            else:
                # Richiesta generica: prendi le ultime 10
                filtered_articles = articles[:10]
                for i, article in enumerate(filtered_articles):
                    article.relevance_score = 1.0 - (i * 0.03)
                    article.category = self.SOURCE_CATEGORIES.get(article.source, "Generale")
            
            # 4. Prepara il risultato
            result_articles = filtered_articles[:15]  # Massimo 15 per risposta
            
            # Statistiche fonti
            sources_used = {}
            for a in result_articles:
                sources_used[a.source] = sources_used.get(a.source, 0) + 1
            
            return {
                "success": True,
                "total_found": len(articles),
                "relevant_count": len(result_articles),
                "query": query,
                "articles": result_articles,
                "sources": sources_used,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"❌ [NewsReader] Errore: {e}")
            return {
                "success": False,
                "error": f"Errore durante il recupero delle notizie: {str(e)}",
                "articles": []
            }

    def format_news_response(self, result: Dict, user_tier: str = "free") -> str:
        """
        Formatta i risultati in un messaggio leggibile per l'utente
        """
        if not result.get("success"):
            return f"❌ {result.get('error', 'Errore sconosciuto')}"
        
        articles = result.get("articles", [])
        if not articles:
            return "📰 Nessuna notizia trovata per la tua richiesta."
        
        query = result.get("query", "ultime notizie")
        relevant_count = result.get("relevant_count", 0)
        total_found = result.get("total_found", 0)
        sources = result.get("sources", {})
        
        # Determina se mostrare il riassunto completo o solo i titoli
        show_full_summary = user_tier in ["plus", "pro", "developer"]
        
        # Costruisci il messaggio
        lines = []
        lines.append(f"📰 **Notizie per: '{query}'**")
        lines.append(f"📊 Trovate {relevant_count} notizie rilevanti su {total_found} totali")
        
        # Mostra le fonti
        if sources:
            source_str = ", ".join([f"{self.SOURCE_EMOJIS.get(s, '📌')} {s} ({c})" for s, c in sources.items()])
            lines.append(f"📡 Fonti: {source_str}")
        
        lines.append("")
        lines.append("---")
        
        for i, article in enumerate(articles[:15], 1):
            # Emoji per la fonte
            source_emoji = self.SOURCE_EMOJIS.get(article.source, "📌")
            
            # Barra di rilevanza
            relevance_bar = ""
            if article.relevance_score > 0:
                bars = int(article.relevance_score * 5)
                relevance_bar = "▰" * bars + "▱" * (5 - bars)
            
            # Formatta il titolo
            title = article.title[:120] + "..." if len(article.title) > 120 else article.title
            
            lines.append(f"{source_emoji} **{title}**")
            
            if show_full_summary:
                lines.append(f"   🏷️ **Fonte:** {article.source} | **Categoria:** {article.category}")
                lines.append(f"   🔗 [Leggi l'articolo]({article.link})")
                lines.append(f"   📊 Rilevanza: {relevance_bar} ({int(article.relevance_score * 100)}%)")
            else:
                lines.append(f"   🔗 [Leggi l'articolo]({article.link})")
                lines.append(f"   📊 Rilevanza: {relevance_bar} ({int(article.relevance_score * 100)}%)")
            
            # Mostra il timestamp per gli articoli più vecchi
            if i > 5:
                time_str = datetime.fromtimestamp(article.timestamp).strftime('%H:%M')
                lines.append(f"   🕐 {time_str}")
            
            lines.append("")
        
        # Aggiungi note sul piano
        if not show_full_summary:
            lines.append("---")
            lines.append("💡 Per riassunti dettagliati e categoria esplicita, passa a **PLUS** o **PRO**!")
        
        if relevant_count > 10:
            lines.append(f"\n📌 Mostrate 10 notizie su {relevant_count} rilevanti. Per vederle tutte, usa `/news_all '{query}'`")
        
        # Data di aggiornamento
        timestamp = result.get("timestamp", time.time())
        lines.append(f"\n🕐 Aggiornato: {datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')}")
        
        return "\n".join(lines)

    def get_news_summary(self, result: Dict, max_length: int = 1000) -> str:
        """
        Genera un riassunto vocale delle notizie (per utenti Plus/Pro)
        """
        if not result.get("success"):
            return f"Errore: {result.get('error', 'Nessuna notizia disponibile')}"
        
        articles = result.get("articles", [])
        if not articles:
            return "Nessuna notizia trovata."
        
        # Usa l'LLM per generare un riassunto
        if self.llm_client and hasattr(self.llm_client, 'generate'):
            articles_text = "\n".join([
                f"- [{a.source}] {a.title} (Link: {a.link})" 
                for a in articles[:10]
            ])
            
            system = """Sei un giornalista esperto. Devi creare un riassunto vocale chiaro e scorrevole delle notizie.
            Il riassunto deve essere naturale, come se lo stessi leggendo ad alta voce, con una durata di circa 1-2 minuti.
            Non usare formattazione Markdown, solo testo semplice.
            Organizza le notizie per fonte o per categoria se pertinente."""
            
            user = f"""Crea un riassunto vocale di queste notizie:

{articles_text}

Riassunto (testo semplice, scorrevole, massimo {max_length} caratteri):"""
            
            try:
                summary = self.llm_client.generate(f"{system}\n\n{user}", max_tok=int(max_length/2))
                if summary and len(summary) > 50:
                    return summary.strip()
            except Exception as e:
                logger.warning(f"⚠️ [NewsReader] Errore generazione riassunto: {e}")
        
        # Fallback: elenco semplice
        lines = [f"Ecco le ultime notizie per la tua richiesta."]
        for article in articles[:8]:
            lines.append(f"{article.title} (Fonte: {article.source}).")
        
        return " ".join(lines)
    
    def get_news_stats(self) -> Dict:
        """Restituisce statistiche sul sistema notizie"""
        return self.cache.get_stats()