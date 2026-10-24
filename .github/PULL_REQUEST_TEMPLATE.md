### 📌 Descrizione della Modifica
<!-- Spiega chiaramente cosa introduce o corregge questa Pull Request. Se risolve un'issue aperta, collegala qui (es. "Risolve #123"). -->

---

### 🏷️ Tipologia di Modifica
<!-- Seleziona una o più opzioni applicabili inserendo una 'x' tra le parentesi -->
- [ ] 🐛 **Bugfix** (correzione di un problema o crash senza modifiche alle API)
- [ ] ✨ **Nuova Funzionalità** (aggiunta di una caratteristica o estensione)
- [ ] 🎵 **Soundboard / Audio** (aggiunta o modifica di profili musicali, atmosfere o campioni SFX)
- [ ] 🖥️ **Interfaccia Grafica (UI)** (miglioramenti a finestre, layout o componenti PySide6)
- [ ] ⚡ **Ottimizzazione / Refactoring** (miglioramento prestazioni, pulizia codice, zero cambi funzionali)
- [ ] 📖 **Documentazione** (aggiornamenti a README, guide, commenti o licenze)
- [ ] ⚙️ **CI/CD & Tooling** (modifiche a workflow GitHub Actions, hook o script di build)

---

### 🎵 Verifica Licenze Audio e Risorse Sonore
<!-- Compila questa sezione SE E SOLO SE la PR introduce o modifica file sonori (.wav, .mp3, .ogg) in sfx/ o configurazioni audio -->
Se questa Pull Request include file audio, conferma quanto segue:
- [ ] **Origine verificata**: I suoni provengono da fonti aperte documentate (es. OpenGameArt, freesound.org con licenza libera, Battle for Wesnoth, Flare RPG).
- [ ] **Licenza compatibile**: La licenza è esplicitamente **CC0**, **CC-BY**, **GPLv2** o **Pubblico Dominio** (nessuna licenza non commerciale "NC", "ND" o campionamento da videogiochi/film protetti da copyright).
- [ ] **Attribuzione documentata**: Ho aggiunto il titolo del file, l'autore originale e il link alla fonte nel file [`CREDITS.md`](CREDITS.md).

*Fonti e licenze dei file audio inclusi (URL esatto):*
> 

---

### 🛠️ Checklist Tecnica del Contributore
Prima di inviare la Pull Request, verifica di aver completato tutti i seguenti controlli:
- [ ] Il codice segue lo stile del progetto ed è stato validato con `ruff check .` (zero errori o warning).
- [ ] L'intera suite di test automatici passa al 100% eseguendo `python -m pytest`.
- [ ] Ho aggiunto test unitari in `tests/` per coprire le nuove funzionalità o prevenire regressioni sul bugfix.
- [ ] Non sono presenti percorsi assoluti locali (es. cartelle specifiche dell'utente) né credenziali/token inseriti nel codice.
- [ ] Se applicabile, ho aggiornato [`README.md`](README.md) o [`CHANGELOG.md`](CHANGELOG.md).

---

### 🖼️ Screenshot o Video (per modifiche grafiche)
<!-- Se la modifica tocca l'interfaccia utente (PySide6 / Qt), allega qui uno screenshot o una breve registrazione prima/dopo -->
