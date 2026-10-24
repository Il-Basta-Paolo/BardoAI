# ADR-0001: Pipeline Vocale Duale Offline (Vosk + Faster-Whisper)
> Data: 2026-10-24 | Stato: **Accettato** | Autore: Paolo Basta

## Contesto e Problema
Durante una sessione GdR dal vivo o su Discord, il Master ha due esigenze vocali contrastanti:
1. **Reattività istantanea per gli effetti sonori (SFX)**: quando il Master pronuncia *"spada"* o *"fulmine"*, il suono deve partire subito (<200ms). Un ritardo di un secondo spezza l'effetto scenico del colpo.
2. **Accuratezza semantica per la musica d'atmosfera**: per capire quando cambiare l'intera colonna sonora (es. passaggio da una tranquilla taverna a un'imboscata nei boschi), serve analizzare la frase per intero, con grammatica e punteggiatura corrette, per evitare cambi repentini o falsi positivi sulle negazioni.

Inviare l'audio in streaming a server cloud (es. OpenAI Whisper API o Google Cloud Speech) presenta problemi insormontabili: latenza di rete variabile, costi a consumo per ore continue di sessione, necessità di connessione internet costante e soprattutto violazione della privacy dei partecipanti al tavolo.

## Decisione Presa
Implementare un'architettura STT **100% locale e duale**:
1. **Vosk (modello compatto italiano ~45MB)**: opera in streaming continuo a 16kHz direttamente sui buffer audio in ingresso. Non aspetta la fine della frase ed emette trascrizioni parziali ogni ~150ms. Se intercetta una parola chiave SFX non negata, scatena immediatamente l'effetto sonoro.
2. **Faster-Whisper (modello locale CTranslate2)**: viene attivato alla fine della frase (rilevata tramite VAD energetico o pause naturali del Master). Genera la trascrizione completa ad altissima fedeltà lessicale e la passa al Director per la regia musicale d'atmosfera.
3. Se l'hardware non dispone di risorse sufficienti per Whisper, il sistema ripiega automaticamente sulle trascrizioni complete di Vosk come fallback trasparente.

## Conseguenze
### Positive
- **Latenza SFX immediata**: ~150-200ms per attivare i suoni di combattimento e magie a voce.
- **Privacy assoluta**: nessun byte audio esce dal computer del Master; zero registrazioni inviate su server remoti.
- **Costi zero**: nessun abbonamento o chiave API obbligatoria per giocare.
- **Resilienza offline**: l'applicazione funziona perfettamente anche in baite di montagna o convention senza connessione internet.

### Negative / Trade-off
- Richiede il download iniziale del modello Vosk (~45MB) al primo avvio (gestito in background senza bloccare la GUI).
- Modelli Whisper più grandi (es. `medium` o `large`) richiedono una GPU dedicata; per questo motivo il profilo di default su CPU è impostato su modelli veloci (`small`/`base`) con fallback Vosk.

## Alternative Scartate
- **API Cloud (OpenAI Whisper / Google Speech-to-Text)**: scartate per latenza imprevedibile (500ms-2s), costi per sessioni di 4 ore e dipendenza da rete.
- **Solo Faster-Whisper**: scartato perché non supporta streaming a bassissima latenza per gli SFX e attendere la fine della frase rendeva i colpi di spada fuori tempo.
- **Solo Vosk**: ottimo per SFX, ma meno accurato di Whisper nella sintassi di frasi lunghe e complesse necessarie per l'analisi d'atmosfera.
