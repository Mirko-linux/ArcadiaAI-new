#!/usr/bin/env python3
import io
import re
import html
import requests
from typing import Optional

# Prova a importare ReportLab. Se non è installato, la guida sotto spiega come fare.
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


class NumberedCanvas(canvas.Canvas):
    """
    Un Canvas personalizzato a due passaggi che calcola automaticamente 
    il numero totale di pagine per stampare un pié di pagina dinamico 
    del tipo "Pagina X di Y" e un'intestazione elegante.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            super().showPage()
        super().save()

    def draw_page_elements(self, page_count):
        self.saveState()
        
        # Colori della palette ArcadiaAI (Blu scuro e Grigio elegante)
        primary_color = colors.HexColor("#1A365D")
        text_muted = colors.HexColor("#718096")
        line_color = colors.HexColor("#E2E8F0")
        
        # Margini e coordinate
        page_width, page_height = letter
        margin = 40
        
        # --- INTESTAZIONE (Dalla pagina 2 in poi per non rovinare la copertina) ---
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(primary_color)
            self.drawString(margin, page_height - 30, "ARCADIA AI - DOCUMENTO GENERATO")
            
            self.setStrokeColor(line_color)
            self.setLineWidth(0.5)
            self.line(margin, page_height - 35, page_width - margin, page_height - 35)
            
        # --- PIÉ DI PAGINA (Su tutte le pagine) ---
        self.setStrokeColor(line_color)
        self.setLineWidth(0.5)
        self.line(margin, 45, page_width - margin, 45)
        
        # Testo del pié di pagina
        self.setFont("Helvetica", 8)
        self.setFillColor(text_muted)
        self.drawString(margin, 30, "Generato automaticamente da ArcadiaAI via Telegram")
        
        # Numero di pagina dinamico (Pagina X di Y)
        page_str = f"Pagina {self._pageNumber} di {page_count}"
        self.drawRightString(page_width - margin, 30, page_str)
        
        self.restoreState()


class ArcadiaPDFGenerator:
    """
    Generatore di PDF professionale con supporto per il parsing del Markdown di base
    generato dai modelli di Intelligenza Artificiale.
    """
    def __init__(self):
        if not HAS_REPORTLAB:
            raise ImportError(
                "La libreria 'reportlab' non è installata. "
                "Esegui: pip install reportlab"
            )
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Configura gli stili tipografici per rendere il PDF moderno ed elegante."""
        # Colori
        c_primary = colors.HexColor("#1A365D")      # Navy Blue
        c_secondary = colors.HexColor("#2B6CB0")    # Slate Blue
        c_text = colors.HexColor("#2D3748")         # Dark Charcoal
        
        # Modifica stili predefiniti per evitare conflitti e migliorarli
        self.styles['Normal'].textColor = c_text
        self.styles['Normal'].fontSize = 10
        self.styles['Normal'].leading = 15
        
        # Nuovo stile per il Titolo Principale del documento
        self.styles.add(ParagraphStyle(
            name='DocTitle',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=c_primary,
            spaceAfter=25
        ))
        
        # Sotto-titolo / Metadati
        self.styles.add(ParagraphStyle(
            name='DocSubtitle',
            parent=self.styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#718096"),
            spaceAfter=30
        ))

        # Intestazioni di livello 1 (# in Markdown)
        self.styles.add(ParagraphStyle(
            name='MarkdownH1',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=c_primary,
            spaceBefore=18,
            spaceAfter=10,
            keepWithNext=True
        ))

        # Intestazioni di livello 2 (## in Markdown)
        self.styles.add(ParagraphStyle(
            name='MarkdownH2',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=16,
            textColor=c_secondary,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True
        ))

        # Stile speciale per i blocchi di codice
        self.styles.add(ParagraphStyle(
            name='CodeBlockStyle',
            parent=self.styles['Normal'],
            fontName='Courier',
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#2D3748"),
            backColor=colors.HexColor("#F7FAFC"),
            borderColor=colors.HexColor("#E2E8F0"),
            borderWidth=0.5,
            borderPadding=8,
            spaceBefore=10,
            spaceAfter=10
        ))

    def _convert_markdown_to_reportlab_tags(self, text: str) -> str:
        """
        Pulisce il testo e converte la sintassi Markdown in tag XML supportati 
        dal motore di rendering Paragraph di ReportLab.
        """
        # 1. Protegge i caratteri XML speciali (fondamentale per evitare crash del parser di ReportLab)
        text = html.escape(text)
        
        # Ripristiniamo temporaneamente gli eventuali caratteri di escape se necessari,
        # ma l'escape di HTML garantisce che '&', '<' e '>' non rompano l'XML di ReportLab.
        # Ora possiamo inserire in sicurezza i nostri tag controllati usando segnaposto temporanei.

        # 2. Grassetti: **testo** o __testo__ -> <b>testo</b>
        text = re.sub(r'\*\*(.*?)\*\*|__(.*?)__', r'<b>\1\2</b>', text)
        
        # 3. Corsivi: *testo* o _testo_ -> <i>testo</i>
        text = re.sub(r'\*(.*?)\*|_(.*?)_', r'<i>\1\2</i>', text)
        
        # 4. Inline Code: `codice` -> <font name="Courier">codice</font>
        text = re.sub(r'`(.*?)`', r'<font name="Courier" color="#C7254E" bgcolor="#F9F2F4">\1</font>', text)
        
        return text

    def build_pdf_buffer(self, ai_text: str, title: str = "Documento ArcadiaAI") -> io.BytesIO:
        """
        Prende il testo markdown generato dall'IA e restituisce un oggetto BytesIO
        contenente il file PDF completo pronto per la trasmissione o il salvataggio.
        """
        buffer = io.BytesIO()
        
        # Setup del documento (Margini impostati a 40 punti, circa 1.4 cm)
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=40,
            rightMargin=40,
            topMargin=50,
            bottomMargin=60
        )
        
        story = []
        
        # --- BLOCCO TITOLO / COPERTINA MINIMALE ---
        story.append(Paragraph(title, self.styles['DocTitle']))
        
        from datetime import datetime
        data_corrente = datetime.now().strftime("%d/%m/%Y alle %H:%M")
        sottotitolo = f"Report di sintesi elaborato dall'intelligenza artificiale il {data_corrente}."
        story.append(Paragraph(sottotitolo, self.styles['DocSubtitle']))
        
        # --- PARSING E DIVISIONE IN PARAGRAFI ---
        # Dividiamo l'output per righe per analizzare la struttura (Intestazioni, Liste, Codice)
        lines = ai_text.split('\n')
        in_code_block = False
        code_block_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            
            # --- Gestione Blocchi di Codice (```) ---
            if line_stripped.startswith("```"):
                if in_code_block:
                    # Fine blocco codice: uniamo le righe conservando gli andata a capo
                    code_text = "\n".join(code_block_lines)
                    # Convertiamo in entità di testo sicuro
                    code_text_escaped = html.escape(code_text)
                    story.append(Paragraph(code_text_escaped, self.styles['CodeBlockStyle']))
                    code_block_lines = []
                    in_code_block = False
                else:
                    # Inizio blocco codice
                    in_code_block = True
                continue
                
            if in_code_block:
                code_block_lines.append(line)
                continue
                
            # --- Gestione Intestazioni (# e ##) ---
            if line_stripped.startswith("# "):
                titolo_h1 = line_stripped[2:]
                parsed_text = self._convert_markdown_to_reportlab_tags(titolo_h1)
                story.append(Paragraph(parsed_text, self.styles['MarkdownH1']))
                continue
                
            if line_stripped.startswith("## "):
                titolo_h2 = line_stripped[3:]
                parsed_text = self._convert_markdown_to_reportlab_tags(titolo_h2)
                story.append(Paragraph(parsed_text, self.styles['MarkdownH2']))
                continue
                
            # --- Gestione Liste (Puntate e Numerate) ---
            # Liste Puntate (- o *)
            match_bullet = re.match(r'^[\s]*[-\*]\s+(.*)', line)
            if match_bullet:
                bullet_content = match_bullet.group(1)
                parsed_text = self._convert_markdown_to_reportlab_tags(bullet_content)
                # Utilizziamo il tag nativo bullet o formattiamo con un pallino UTF-8
                bullet_paragraph = f"&bull; {parsed_text}"
                story.append(Paragraph(bullet_paragraph, self.styles['Normal']))
                story.append(Spacer(1, 4))
                continue
                
            # Liste Numerate (1. o 2.)
            match_numbered = re.match(r'^[\s]*\d+\.\s+(.*)', line)
            if match_numbered:
                num_content = match_numbered.group(1)
                parsed_text = self._convert_markdown_to_reportlab_tags(num_content)
                # Trova il numero originale per mantenerlo coerente
                num_prefix = re.match(r'^[\s]*(\d+\.)', line).group(1)
                numbered_paragraph = f"<b>{num_prefix}</b> {parsed_text}"
                story.append(Paragraph(numbered_paragraph, self.styles['Normal']))
                story.append(Spacer(1, 4))
                continue

            # Interruzione di pagina manuale se specificata
            if line_stripped == "---" or line_stripped == "===PAGEBREAK===":
                story.append(PageBreak())
                continue
                
            # --- Paragrafo Standard ---
            if line_stripped:
                parsed_text = self._convert_markdown_to_reportlab_tags(line_stripped)
                story.append(Paragraph(parsed_text, self.styles['Normal']))
                # Spazio standard tra paragrafi
                story.append(Spacer(1, 8))
            else:
                # Righe vuote creano una piccola spaziatura aggiuntiva
                story.append(Spacer(1, 4))
                
        # Costruisce il PDF utilizzando il nostro NumberedCanvas personalizzato
        doc.build(story, canvasmaker=NumberedCanvas)
        
        # Posiziona il puntatore del buffer all'inizio, pronto per la lettura
        buffer.seek(0)
        return buffer


# ==============================================================================
# FUNZIONE DI TRASMISSIONE INTEGRABILE CON IL TUO BOT TELEGRAM (ESEMPIO.py)
# ==============================================================================

def send_pdf_to_telegram(
    chat_id: int, 
    pdf_buffer: io.BytesIO, 
    file_name: str = "documento.pdf", 
    caption: str = "Ecco il tuo documento in formato PDF!", 
    token: str = ""
) -> bool:
    """
    Invia un file PDF in memoria (BytesIO) direttamente ad una chat Telegram.
    Senza salvare nulla su disco (totalmente serverless).
    """
    if not token:
        print("Errore: Token del Bot Telegram mancante.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    
    # Prepariamo il payload multipart
    files = {
        'document': (file_name, pdf_buffer, 'application/pdf')
    }
    data = {
        'chat_id': chat_id,
        'caption': caption,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, data=data, files=files, timeout=30)
        if response.status_code == 200:
            print(f"✅ PDF '{file_name}' inviato con successo a {chat_id}!")
            return True
        else:
            print(f"❌ Errore Telegram API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Errore durante l'invio del file a Telegram: {e}")
        return False


# ==============================================================================
# ESEMPIO DI UTILIZZO E TEST DI GENERAZIONE IN LOCALE
# ==============================================================================
if __name__ == "__main__":
    if not HAS_REPORTLAB:
        print("Per testare lo script, installa reportlab: pip install reportlab")
        exit(1)
        
    print("Generazione di un PDF di test in corso...")
    
    testo_ia_markdown = """
# Introduzione ad ArcadiaAI
Questo è un documento di esempio generato automaticamente per dimostrare le potenzialità di conversione **Markdown -> PDF** in ambiente *Serverless* e integrabile su Telegram.

## Funzionalità Chiave:
- **Serverless Ready**: Nessuna scrittura su disco rigido. Tutto il processo di compilazione e streaming del file avviene all'interno della RAM via `io.BytesIO`.
- **Parsing Intelligente**: Conversione automatica di grassetti (`**`), corsivi (`*`), liste numerate e puntate.
- **Tipografia di Pregio**: Palette colori studiata per documenti aziendali, relazioni e report tecnici.
- **Numerazione Dinamica**: Pié di pagina con conteggio totale delle pagine calcolato a due passaggi.

## Esempio blocco di codice Python:
```python
def saluta_utente(nome):
    print(f"Ciao {nome}, benvenuto in ArcadiaAI!")
    return True
```

Inoltre, il sistema gestisce in modo sicuro i caratteri speciali come & < > senza far fallire la compilazione del documento PDF.
"""
    
    generator = ArcadiaPDFGenerator()
    # Genera il PDF in memoria
    pdf_data = generator.build_pdf_buffer(testo_ia_markdown, title="Sintesi Ricerca ArcadiaAI")
    
    # Salvataggio di test locale (solo per verificare il file localmente durante lo sviluppo)
    with open("test_generato.pdf", "wb") as f:
        f.write(pdf_data.read())
        
    print("✅ PDF di test salvato localmente come 'test_generato.pdf'!")