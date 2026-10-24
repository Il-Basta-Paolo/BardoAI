# ADR-0003: Interfaccia Desktop Nativa Windows in PySide6 (Qt6)
> Data: 2026-10-24 | Stato: **Accettato** | Autore: Paolo Basta

## Contesto e Problema
Nelle prime iterazioni del progetto, la GUI era costituita da una Web App locale con server interno FastAPI/Uvicorn e frontend aperto nel browser predefinito di Windows.
Al tavolo da gioco questo approccio si è rivelato problematico per svariati motivi:
1. **Conflitti di porte e firewall**: porte locali (es. 8000) occupate da altri servizi o bloccate da antivirus aziendali/personali.
2. **Consumo di memoria spropositato**: eseguire un server Python + un browser moderno (Chrome/Edge) impegnava fino a 800MB–1.2GB di RAM solo per mostrare una griglia di pulsanti e un VU-meter.
3. **Mancanza di scorciatoie di sistema affidabili**: un'applicazione web nel browser non può catturare hotkey globali né dialogare agilmente con i dispositivi audio del sistema operativo.
4. **Esperienza utente frammentata**: il Master rischiava di chiudere per sbaglio la scheda del browser durante la navigazione di schede D&D Beyond o Roll20.

## Decisione Presa
Rifondare completamente l'applicazione su un'interfaccia desktop nativa per Windows utilizzando **PySide6 (Qt6 for Python)**:
- Finestra nativa Windows con supporto High-DPI (schermi 4K/display moderni) e tema scuro ad alto contrasto.
- Architettura a componenti modulari riutilizzabili (`MoodGridWidget`, `SoundboardWidget`, `TransportBar`, `VoiceMonitorWidget`).
- Comunicazione thread-safe tra i thread audio/STT e la GUI tramite il pattern `EventBridge` basato su segnali e slot Qt (`QtCore.Signal`).

## Conseguenze
### Positive
- **Fluidità e reattività istantanea**: rendering nativo a 60 FPS senza overhead da browser.
- **Consumo RAM ridotto di oltre il 60%**: l'applicazione completa occupa mediamente ~140-180MB di RAM.
- **Portabilità Windows pulita**: compilabile in un unico eseguibile compatto (`BardoAI.exe`) privo di server web o porte di rete aperte.
- **Controllo grafico completo**: layout a griglia responsiva (`QScrollArea`), barre di volume, VU-meter reattivo e slider senza latenze.

### Negative / Trade-off
- Per l'esecuzione dei test unitari è necessario configurare la piattaforma offscreen (`QT_QPA_PLATFORM=offscreen`).

## Alternative Scartate
- **Architettura Web Locale (FastAPI + React/Vue/HTML)**: scartata per eccessivo consumo di RAM, porte di rete bloccate e fragilità al tavolo.
- **Electron**: scartato per la pesantezza nota di Chromium e Node.js.
- **Tkinter**: scartato per look & feel obsoleto su Windows 10/11 e difficoltà nel gestire High-DPI e animazioni fluide.
