# ADR-0002: Mixer Audio Unificato Nativo (PyAV + sounddevice)
> Data: 2026-10-24 | Stato: **Accettato** | Autore: Paolo Basta

## Contesto e Problema
Nelle prime versioni sperimentali, la riproduzione audio si basava su LibVLC (Python-VLC) e chiamate esterne di sistema. Questo approccio causava gravi limitazioni al tavolo da gioco:
1. **Dipendenza da DLL esterne**: gli utenti dovevano avere VLC installato o l'installer doveva includere oltre 100MB di librerie C non controllate, con frequenti crash su versioni a 32 vs 64 bit.
2. **Impossibilità di mixaggio avanzato su un unico stream**: VLC gestiva la musica e gli effetti come istanze separate del sistema operativo. Di conseguenza non era possibile applicare *audio ducking* istantaneo (abbassare la musica di sottofondo mentre si sente il ruggito di un drago) né calcolare dissolvenze incrociate (*crossfade*) sincronizzate al millisecondo.
3. **Disconnessioni a caldo**: se il Master collegava le cuffie USB o accendeva le casse dopo l'avvio, VLC falliva silenziosamente o richiedeva il riavvio completo.

## Decisione Presa
Sviluppare un motore audio interno interamente gestito in memoria PCM float32 a 48kHz stereo, basato sulla combinazione di:
- **PyAV (FFmpeg nativo C via Cython)**: decodifica qualsiasi formato audio sorgente (WebM, Opus, MP3, FLAC, AAC, WAV) convertendolo in buffer PCM standard.
- **sounddevice (PortAudio)**: un unico stream di output hardware a bassa latenza su driver WASAPI/DirectSound.
- **Mixer e DSP interno**:
  - Buffer circolare con calcolo di gain matematico in tempo reale.
  - Dissolvenza incrociata non-lineare (*S-Curve crossfade* a coseno/seno) per evitare vuoti di pressione sonora durante il cambio brano.
  - Attenuazione automatica (*audio ducking*) a salita e discesa graduale (ramp up/down) quando viene scatenato un effetto sonoro.
  - Soft-limiter trasparente (`np.tanh`) per prevenire distorsioni digitali (clipping) anche con 5 o 6 effetti simultanei sovrapposti.

## Conseguenze
### Positive
- **Zero dipendenze esterne**: nessun VLC richiesto; il motore audio è interamente autonomo.
- **Ducking perfetto**: la musica cala in modo morbido e naturale al partire del colpo di spada e torna al livello iniziale senza scatti.
- **Riconnessione automatica (`ensure_stream()`)**: gestione trasparente del cambio di scheda audio o cuffie inserite a caldo.
- **Prestazioni eccellenti**: decodifica a blocchi e consumo CPU inferiore all'1.5% su processori moderni.

### Negative / Trade-off
- Richiede la gestione manuale del campionamento e della memoria in numpy, collaudata con test specifici per prevenire memory leak su lunghe sessioni.

## Alternative Scartate
- **LibVLC / python-vlc**: scartato per instabilità su Windows, assenza di audio ducking nativo e pesantezza delle DLL esterne.
- **Pygame Mixer**: scartato per limitazioni sul controllo del sample rate e latenza elevata su formati compressi streaming.
- **GStreamer**: scartato per complessità eccessiva di packaging Windows e conflitti di runtime.
