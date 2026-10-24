# Changelog — Bardo AI

Tutte le modifiche rilevanti a questo progetto sono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.0.0/)
e questo progetto aderisce al [Semantic Versioning](https://semver.org/lang/it/).

---

## [2.6.2] — 2026-10-24

### 🌟 Aggiunto
- **VU-Meter Dinamico con Noise Gate Regolabile**: indicatore RMS in tempo reale del microfono nell'header con cursore di soglia trascinabile via mouse. L'interfaccia segnala visivamente il superamento della soglia (indicatore verde) o il filtraggio del rumore di fondo (indicatore grigio).
- **Selettore Dispositivo Audio d'Uscita**: menu a tendina nella barra di trasporto per instradare a caldo il flusso sonoro su cuffie, altoparlanti o mixer virtuali (Voicemeeter, VB-Cable per Discord) senza dover riavviare l'applicazione.
- **Modalità Auto-Float (Picture-in-Picture)**: contrazione automatica della finestra in una mini-barra flottante Always-on-Top non appena il Master passa ad un'altra applicazione (manuali PDF, appunti, VTT).
- **Barra di Ricerca Rapida Soundboard**: casella di ricerca reattiva nella scheda effetti con filtro istantaneo per nome e parole chiave, switch automatico alla categoria "Tutti" e reset immediato con tasto `Esc`.
- **Scorciatoie da Tastiera Globali & Dialog F1**: comandi rapidi per microfono (`Spazio`/`Ctrl+M`), volume master (frecce `Su`/`Giù`), salto traccia (`Ctrl+N`) e finestra interattiva di aiuto richiamabile con `F1`.
- **Esportazione e Importazione Profili di Campagna (`.bardo.json`)**: supporto per salvare, esportare e importare pacchetti di configurazione personalizzati con risoluzione automatica delle collisioni di ID.

### 🔄 Modificato
- **Persistenza Impostazioni Utente**: salvataggio automatico della soglia del Noise Gate (`gate_threshold`) e del dispositivo di output (`output_device`) nel file di configurazione locale.
- **Isolamento Thread Modelli Vocali**: introdotta protezione per la chiusura controllata dei thread in background Vosk e Faster-Whisper, prevenendo crash da teardown delle librerie C native.

### 🧪 Test & Affidabilità
- **Estensione Suite Automatizzata**: aggiunti 43 nuovi test unitari e di integrazione (93 test complessivi, 100% pass rate) a copertura di VU-meter, selettore audio, import/export profili, scorciatoie da tastiera e modalità floating.

---

## [2.6.1] — 2026-10-24

### 🐛 Risolto
- **Disallineamento Profilo / Griglia Atmosfere all'Avvio**: risolta l'anomalia per cui all'avvio dell'applicazione il menu a tendina superiore mostrava "Fantasy & D&D" mentre la griglia delle atmosfere sottostante mostrava quelle di Cyberpunk (o dell'ultimo profilo memorizzato). Ora l'indice del menu a tendina viene sincronizzato immediatamente all'avvio con il profilo salvato in configurazione (`active_profile_id`).
- **Sincronizzazione Bidirezionale Sicura**: implementato allineamento atomico con blocco preventivo dei segnali (`blockSignals(True/False)`) in `_apply_profile`, prevenendo loop ricorsivi di cambio profilo o mancata emissione di eventi Qt.

### 🌟 Aggiunto
- **Suite di Test UI Offscreen**: aggiunti nuovi test unitari in `tests/test_ui_profile_sync.py` per collaudare l'avvio, il cambio profilo manuale da combobox e l'allineamento programmatico su macchina vergine offscreen.

---

## [2.6.0] — 2026-10-24

### 🌟 Aggiunto
- **Interfaccia Desktop PySide6 (Qt6)**: nuova interfaccia desktop nativa per Windows con supporto High-DPI per display moderni, navigazione fluida e tema scuro ad alto contrasto.
- **Mixer Audio Unificato (PyAV + sounddevice)**: decodifica interna nativa a 48kHz stereo float32. Supporto sample-accurate per dissolvenze S-Curve (*crossfade*) e attenuazione automatica (*audio ducking*) della musica durante la riproduzione degli effetti sonori.
- **Analisi Semantica delle Negazioni**: parsing per clausole linguistiche per ignorare trigger di pericolo o SFX in presenza di negazioni (*"non ci sono mostri"*, *"senza estrarre le armi"*).
- **Disambiguazione Lessicale Italiana**: regole contestuali per prevenire falsi positivi su omografi comuni (*"vi danno il benvenuto"*, *"intorno al fuoco"*, *"costa dieci monete"*, *"lo farò"*, *"è reale"*).
- **Pipeline Vocale Offline Duale**: integrazione combinata di Vosk (streaming a bassissima latenza ~150ms per l'attivazione immediata degli effetti) e Faster-Whisper (trascrizione di frase completa per la regia d'atmosfera) senza invio di audio su server remoti.
- **4 Profili di Campagna Preconfigurati**: cataloghi musicali e atmosfere dedicate per *Fantasy & D&D*, *Horror & Cthulhu*, *Sci-Fi & Cyberpunk*, *Giallo & Investigativo*.
- **Soundboard a Categorie**: griglia responsiva con i 20 effetti inclusi e supporto a campioni audio personalizzati in `%LOCALAPPDATA%\BardoAI\data\custom_sfx`.
- **Sicurezza Cifrata delle Credenziali**: archiviazione protetta delle API key opzionali tramite Windows Credential Manager (`keyring`).
- **Suite di Test Completa**: 50 test automatizzati con `pytest` su motore audio, parsing semantico, persistenza e stabilità cross-PC.
- **Eseguibili e Installer Ufficiale**: compilazione con risorse di versione Windows che attestano Paolo Basta come autore ufficiale (`BardoAI.exe` standalone e `BardoAI_Setup.exe` installer).

### 🔄 Modificato
- Riscritto completamente il modulo di gestione audio, eliminando la duplicazione degli stream e i disallineamenti di volume.
- Migrata la persistenza da file JSON grezzi non protetti a modelli Pydantic v2 con salvataggi atomici e recupero automatico da file temporanei.
- Risoluzione dei brani musicali basata su corrispondenze a parole intere (regex `\b`) per garantire brani rigorosamente strumentali ed evitare falsi scarti.

### 🐛 Risolto
- Risolto crash `TypeError: unhashable type: 'dict'` in `analyzer.py` su profili passati come dizionario.
- Risolto `NameError: sys` in `main_window.py` durante la risoluzione dinamica dell'icona dell'applicazione.
- Risolto blocco dell'audio quando i dispositivi di riproduzione (cuffie/casse) vengono connessi a caldo dopo l'avvio dell'applicazione (`ensure_stream()`).
- Risolti errori di permessi (`PermissionError`) quando l'applicazione viene installata in cartelle di sistema protette come `C:\Program Files`.
- Risolto problema di visualizzazione limitata a soli 10 suoni nella griglia della soundboard.

### 🗑️ Rimosso
- Rimossa la vecchia architettura basata su web server locale (FastAPI/Uvicorn) e browser web.
- Rimossa la dipendenza da LibVLC e dalle relative librerie DLL esterne.
- Rimosse le chiavi e i cookie di sessione salvati in chiaro nei file di configurazione.
