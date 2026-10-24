# ADR-0004: Sicurezza Credenziali tramite Windows Credential Manager
> Data: 2026-10-24 | Stato: **Accettato** | Autore: Paolo Basta

## Contesto e Problema
Bardo AI permette l'inserimento di chiavi API opzionali per estendere la regia musicale con modelli linguistici avanzati (es. Gemini API, OpenAI API) o integrazioni Spotify.
Inizialmente, tali valori venivano memorizzati in chiaro all'interno del file locale `config.json`.
Questo presentava rischi di sicurezza inaccettabili:
1. **Rischio di furto / leakage accidentale**: se l'utente o uno sviluppatore condivideva file di log o allegava la cartella del profilo a una issue GitHub, le chiavi API private venivano esposte pubblicamente.
2. **Accesso da malware o script non autorizzati**: qualsiasi processo in esecuzione sul computer poteva leggere file di testo in chiaro nella cartella utente.

## Decisione Presa
Adottare la libreria `keyring` per delegare l'archiviazione e la cifratura di tutti i segreti al gestore di credenziali nativo del sistema operativo:
- Su Windows viene utilizzato direttamente il **Windows Credential Manager** (API DPAPI crittografata con le chiavi di login dell'utente Windows).
- I file JSON salvati su disco (`data/config.json`) contengono esclusivamente puntatori di metadati, mai password, token o API key in chiaro.
- In caso di fallback (es. ambienti headless privi di servizio credenziali), il sistema gestisce l'eccezione senza crashare.

## Conseguenze
### Positive
- **Zero leakage garantito**: anche condividendo l'intera cartella di configurazione o creando zip di backup, le chiavi API rimangono protette e inaccessibili.
- **Integrazione trasparente con Windows**: l'utente non deve digitare password ad ogni avvio; Windows autentica l'accesso in modo sicuro.
- **Conformità alle best practices open-source**: rispetto rigoroso degli standard di sicurezza per software desktop.

### Negative / Trade-off
- Se un profilo viene esportato per essere condiviso con un altro Master, le credenziali private devono essere reinserite manualmente sul PC di destinazione (decisione intenzionale a tutela della privacy).

## Alternative Scartate
- **Salvataggio in chiaro in `config.json`**: scartato per gravi rischi di violazione e divulgazione involontaria.
- **Cifratura simmetrica con password statica nel codice (hardcoded AES key)**: scartata perché non offre reale sicurezza in un'applicazione open source con codice pubblico su GitHub.
