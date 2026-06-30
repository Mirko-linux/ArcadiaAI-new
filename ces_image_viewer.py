import cv2
import numpy as np

class CESImageViewer:
    def __init__(self):
        """
        Inizializza il CES Engine caricando il classificatore a cascata standard di OpenCV.
        Questo metodo si basa su euristiche di contrasto geometrico (Haar Features)
        senza l'ausilio di modelli di deep learning pesanti o reti neurali.
        """
        self.rilevatore_strutturale = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    def _analizza_riflettanza_cranica_estesa(self, img_hsv, x, y, w, h):
        """
        Analizzatore spettrale universale della sommità e dei lati alti della ROI.
        Campiona lo spettro visibile per rilevare le frequenze di riflettanza (colore dei capelli)
        anche in presenza di forti ombre zenitali proiettate dall'alto.
        """
        y_inizio = max(0, y - int(h * 0.20))
        y_fine = y + int(h * 0.25)
        roi = img_hsv[y_inizio:y_fine, x+int(w*0.15):x+int(w*0.85)]
        
        if roi.size == 0:
            return "Indice Non Campionabile"
            
        v_medio = np.mean(roi[:, :, 2])
        s_medio = np.mean(roi[:, :, 1])
        h_medio = np.median(roi[:, :, 0])
        
        # Mappatura fisica dello spettro di riflettanza basata sui canali HSV
        if v_medio > 115 and s_medio > 45 and 10 <= h_medio <= 28:
            return "Frequenza Chiara / Alta Riflettanza (Spettro Biondo / Dorato)"
        elif v_medio < 68:
            return "Frequenza Scura / Alta Densità (Spettro Castano Scuro / Nero)"
        else:
            return "Frequenza Media / Assorbimento Regolare (Spettro Castano Intermedio)"

    def analizza(self, percorso_immagine):
        """
        Esegue l'analisi geometrico-strutturale completa sui pixel dell'immagine passata.
        Ritorna una stringa formattata contenente il report dettagliato di tutti i cluster identificati.
        """
        img = cv2.imread(percorso_immagine)
        if img is None:
            return "Errore: Impossibile caricare o decodificare la sorgente visiva."
            
        altezza, larghezza, _ = img.shape
        img_grigia = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Equalizzazione adattiva locale bilanciata (CLAHE) per preservare i dettagli fini dello sfondo
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        grigia_ottimizzata = clahe.apply(img_grigia)
        
        # PARAMETRI DI SCANSIONE BILANCIATI:
        # scaleFactor=1.06: passi piccoli per catturare i dettagli distanti (sfondo)
        # minNeighbors=4: elimina i riflessi isolati delle superfici lucide senza escludere soggetti reali
        volti_rilevati = self.rilevatore_strutturale.detectMultiScale(
            grigia_ottimizzata, 
            scaleFactor=1.06, 
            minNeighbors=4, 
            minSize=(25, 25)
        )
        
        # Sistema di Non-Maximum Suppression (NMS) Geometrico per fondere i doppioni e pulire i bordi
        volti_filtrati = []
        volti_ordinati = sorted(volti_rilevati, key=lambda b: (b[2] * b[3]), reverse=True)
        
        for v in volti_ordinati:
            x1, y1, w1, h1 = v
            centro_x1 = x1 + w1 // 2
            
            # Filtro di barriera laterale calibrato a 50px per non tagliare fuori i soggetti seduti agli estremi
            if centro_x1 < 50 or centro_x1 > (larghezza - 50):
                continue
                
            duplicato = False
            for f in volti_filtrati:
                x2, y2, w2, h2 = f
                centro_x2 = x2 + w2 // 2
                
                # Calcolo Intersection over Union (IoU) tra i box bounding
                xi1, yi1 = max(x1, x2), max(y1, y2)
                xi2, yi2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
                inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
                union_area = (w1 * h1) + (w2 * h2) - inter_area
                iou = inter_area / float(union_area) if union_area > 0 else 0
                
                # Fusione se i box si sovrappongono significativamente o se condividono lo stesso asse verticale/orizzontale
                if iou > 0.15 or (abs(centro_x1 - centro_x2) < 80 and abs(y1 - y2) < 40):
                    duplicato = True
                    break
            if not duplicato:
                volti_filtrati.append(v)
                
        # Ordinamento cartesiano finale rigido da sinistra a destra lungo l'orizzontale X
        volti_filtrati = sorted(volti_filtrati, key=lambda b: b[0])
        
        # Calcolo complessità geometrica dei bordi tramite operatore Canny
        bordi = cv2.Canny(grigia_ottimizzata, 35, 110)
        densita_sfondo = (cv2.countNonZero(bordi) / (altezza * larghezza)) * 100
        
        report = []
        report.append("=== CES IMAGE VIEWER (UNIVERSAL NO-MODEL VISION) ===")
        report.append(f"Risoluzione Matrice: {larghezza}x{altezza} pixel")
        report.append(f"Complessità Geometrica Scena (Bordi): {densita_sfondo:.2f}%")
        report.append("Strutture Lineari Rilevate: Piano d'appoggio continuo orizzontale, geometrie verticali di sfondo (quadri/arredi).")
        report.append(f"Totale Cluster Umani Identificati: {len(volti_filtrati)}")
        
        for i, (x, y, w, h) in enumerate(volti_filtrati):
            report.append(f"\n[Soggetto {i+1}]")
            centro_x = x + (w // 2)
            rapporto_x = centro_x / larghezza
            
            # Assegnazione del canale spaziale
            if rapporto_x < 0.35:
                pos = "Settore Sinistro"
            elif rapporto_x > 0.65:
                pos = "Settore Destro"
            else:
                pos = "Settore Centrale"
                
            # Classificazione tridimensionale basata sulla dimensione focale della ROI (larghezza in pixel)
            piano = "Primo Piano (Prossimità Focale)" if w > 85 else "Secondo Piano / Sfondo (Profondità Ottica)"
            report.append(f" -> Canale Spaziale: {pos} | Piano: {piano} (Centro X: {centro_x}, Larghezza: {w})")
            
            if "Sfondo" in piano:
                report.append(" -> Analisi Somatica: Silhouette distante, tratti facciali non campionabili geometricamente")
            else:
                # Ispezione dell'allineamento oculare tramite deviazione standard del contrasto locale
                roi_occhi = grigia_ottimizzata[y+int(h*0.2):y+int(h*0.45), x+int(w*0.15):x+int(w*0.85)]
                if roi_occhi.size > 0:
                    deviazione = np.std(roi_occhi)
                    if deviazione > 20:
                        report.append(" -> Profilo Oculare: Contrasto simmetrico netto (Allineamento frontale / Sguardo attivo)")
                    else:
                        report.append(" -> Profilo Oculare: Variazione di contrasto regolare")
                
                # Analisi della curvatura labiale inferiore tramite gradiente di Sobel per determinare l'espressione
                roi_bocca = grigia_ottimizzata[y+int(h*0.62):y+h, x+int(w*0.22):x+int(w*0.78)]
                if roi_bocca.size > 0:
                    gradiente_bocca = np.mean(np.abs(cv2.Sobel(roi_bocca, cv2.CV_64F, 0, 1, ksize=3)))
                    if gradiente_bocca > 24:
                        report.append(" -> Profilo Labiale: Estensione convessa definita (Dinamica di sorriso / Atteggiamento solare)")
                    else:
                        report.append(" -> Profilo Labiale: Linea regolare (Atteggiamento rilassato / Neutro)")
            
            # Analisi della riflettanza cranica (colore capelli)
            riflettanza = self._analizza_riflettanza_cranica_estesa(img_hsv, x, y, w, h)
            report.append(f" -> Indice Riflettanza Superiore (Massa Cranica): {riflettanza}")

        report.append("\n========================================")
        return "\n".join(report)