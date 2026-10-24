# Guida per Contribuire a Bardo AI

Grazie per l'interesse nel contribuire a **Bardo AI**! Che tu sia un Dungeon Master con idee per nuovi effetti sonori o uno sviluppatore con proposte di miglioramento del codice, ogni contributo coerente con la filosofia del progetto è benvenuto.

---

## 🎲 Come puoi contribuire

1. **Nuovi Effetti Sonori (SFX) per la Soundboard**:
   - Se hai un campione sonoro utile al tavolo (es. una porta che sbatte, un incantesimo d'acqua, un cavallo al galoppo), puoi proporlo aprendo una [Issue con il template dedicato](https://github.com/Il-Basta-Paolo/BardoAI/issues/new/choose).
   - **Regola Fondamentale sulle Licenze Audio**: I campioni audio devono provenire da fonti libere con licenza aperta compatibile (**CC0**, **CC-BY** o **GPL**, come quelle di [The Battle for Wesnoth](https://www.wesnoth.org/) o [Flare RPG](https://flarerpg.org/)). Indica sempre autore e link alla fonte originale.
   - Formato ideale: file audio compresso o WAV stereo a 48kHz, privo di rumore di fondo.

2. **Miglioramento del Vocabolario e delle Parole Chiave**:
   - Suggerire sinonimi, verbi ed espressioni usate comunemente nelle sessioni GdR in italiano per arricchire i profili (Fantasy, Horror, Cyberpunk, Investigativo).
   - Segnalare eventuali falsi positivi lessicali (parole con doppi sensi che attivano effetti non voluti).

3. **Miglioramenti al Codice e Bugfix**:
   - Risoluzione di bug su interfacce audio, miglioramenti all'interfaccia grafica PySide6 o ottimizzazioni del mixer.

---

## 🛠️ Linee Guida di Sviluppo

Se vuoi proporre modifiche al codice tramite Pull Request:

1. **Clona e prepara l'ambiente**:
   Puoi configurare l'ambiente di sviluppo in un clic eseguendo lo script:
   ```cmd
   setup_dev_env.bat
   ```
   Oppure manualmente con:
   ```powershell
   git clone https://github.com/Il-Basta-Paolo/BardoAI.git
   cd BardoAI
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   git config core.hooksPath .githooks
   ```

2. **Esegui sempre i test automatici**:
   Tutti i 93 test unitari devono passare al 100% prima di inviare modifiche:
   ```powershell
   pytest -v
   ```

3. **Portabilità e Pulizia**:
   - Mai inserire percorsi assoluti del proprio computer locale (usare percorsi relativi o costrutti standard come `%LOCALAPPDATA%`).
   - Mantenere il codice tipizzato (type hints) e commentato con chiarezza.
   - Tutte le modifiche rilevanti devono essere accompagnate da un test in `tests/` e documentate in [`CHANGELOG.md`](CHANGELOG.md).

---

## 👤 Autore e Mantenimento
Bardo AI è ideato e mantenuto da **Paolo Basta** ([@Il-Basta-Paolo](https://github.com/Il-Basta-Paolo)).
