# Politica di Sicurezza e Privacy — Bardo AI

La sicurezza del sistema e la tutela assoluta della privacy dei giocatori al tavolo sono principi fondamentali dell'architettura di **Bardo AI**.

---

## 🎙️ 1. Privacy Vocale: Riconoscimento 100% Locale e Offline

Bardo AI è progettato per essere utilizzato durante sessioni di gioco di ruolo private, dal vivo o su piattaforme come Discord:

* **Zero Trasmissione Audio su Cloud**: Tutto il flusso vocale catturato dal microfono viene elaborato **esclusivamente in locale** sulla CPU del computer tramite i motori open source **Vosk** e **Faster-Whisper**.
* **Nessun Salvataggio di Registrazioni Vocali**: I frammenti audio PCM vengono analizzati in memoria volatile (RAM) per estrarre la trascrizione testuale e vengono immediatamente sovrascritti. Nessun file audio della tua voce viene salvato su disco o inviato a server esterni.
* **Nessuna Telemetria o Tracciamento Nascosto**: L'applicazione non contiene tracker pubblicitari, moduli di profilazione né telemetria utente.

---

## 🔐 2. Gestione Cifrata delle Credenziali

Se decidi di utilizzare integrazioni opzionali (come chiavi API Gemini, OpenAI o credenziali Spotify):

* **Windows Credential Manager**: Tutte le chiavi segrete vengono salvate nella cassaforte protetta del sistema operativo Windows tramite la libreria `keyring`.
* **Zero Credenziali nei File di Testo**: Nessuna chiave API o token di sessione viene mai scritto in chiaro nei file di configurazione `config.json` o nei file di log.
* **Salvataggi Atomici**: Le scritture delle impostazioni avvengono tramite file temporanei e sostituzioni atomiche (`tempfile` + `replace`), proteggendo la configurazione da corruzioni in caso di interruzione improvvisa.

---

## 🛡️ 3. Eseguibili Windows e Integrità

* Gli eseguibili ufficiali distribuiti tramite le [Releases di GitHub](https://github.com/Il-Basta-Paolo/BardoAI/releases) sono compilati da codice sorgente verificato con metadati Windows ufficiali (Autore: **Paolo Basta**).
* Prima di ogni rilascio viene eseguito uno **smoke-test automatico** per confermare la totale assenza di crash e l'integrità dei binari.

---

## 📬 4. Segnalazione di Vulnerabilità di Sicurezza

Se riscontri una potenziale vulnerabilità o un problema relativo alla sicurezza dei dati:

1. Non aprire una segnalazione pubblica nella sezione Issues.
2. Contatta direttamente l'autore **Paolo Basta** aprendo una discussione privata su GitHub o tramite l'indirizzo privato noreply associato al repository (`147190444+Il-Basta-Paolo@users.noreply.github.com`).
3. Riceverai un riscontro rapido e le eventuali correzioni verranno rilasciate con la massima priorità.
