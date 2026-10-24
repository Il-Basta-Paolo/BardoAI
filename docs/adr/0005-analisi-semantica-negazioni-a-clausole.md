# ADR-0005: Parsing Semantico delle Negazioni e Frasi a Clausole
> Data: 2026-10-24 | Stato: **Accettato** | Autore: Paolo Basta

## Contesto e Problema
Nel linguaggio parlato al tavolo di gioco, il Master utilizza costantemente frasi complesse, descrizioni suggestive e negazioni per creare atmosfera o rassicurare i giocatori:
- *"I goblin estraggono le spade e vi caricano!"* (deve partire il combattimento e il clangore delle armi).
- *"Tranquilli, non estraete le spade, non c'è nessun pericolo nella stanza"* (NON deve partire il combattimento né il clangore).
- *"Non vedete mostri, la caverna è silenziosa"* (NON deve attivarsi la musica dei mostri).

I software tradizionali o i bot vocali basati su semplice ricerca di sottostringhe (*keyword matching*) falliscono clamorosamente in questo contesto: rilevando *"spade"* o *"mostri"*, fanno partire la musica di battaglia nel momento sbagliato, distruggendo l'immersione della scena.
Inoltre, nella lingua italiana esistono frequenti omografi contestuali che ingannano i parser ingenui:
- *"Vi danno il benvenuto"* (verbo dare, non "danno" inteso come ferita o scontro).
- *"Vi sedete intorno al fuoco"* (bivacco accogliente / riposo, non incendio o incantesimo palla di fuoco).
- *"Questa pozione costa dieci monete"* (costo monetario, non "costa" marittima).

## Decisione Presa
Implementare un motore di parsing semantico strutturato su due livelli:
1. **Divisione per clausole linguistiche**:
   - Il testo viene segmentato in preposizioni e proposizioni logiche attraverso punteggiatura e congiunzioni (*ma, tuttavia, però, mentre, invece*).
   - Ogni clausola viene analizzata per la presenza di particelle negative e avverbi (*non, nessun, niente, senza, manco, nulla*).
   - I termini all'interno di una clausola negativa vengono neutralizzati e separati dalle affermazioni.
2. **Regole di disambiguazione contestuale italiana**:
   - Analisi delle parole adiacenti (n-grammi) per disambiguare forme verbali vs sostantivi di scontro (*"danno"* preceduto da *"vi / ti / gli"* viene classificato come saluto/benvenuto).
   - Match su confini di parola esatti (regex `\b`) per prevenire falsi positivi su radici lessicali sovrapposte (es. *"costa"* vs *"costante"*, *"arco"* vs *"barco"*).

## Conseguenze
### Positive
- **Zero falsi allarmi**: le scene rassicuranti o descrittive non vengono mai interrotte da musica di battaglia non richiesta.
- **Precisione naturale al tavolo**: il Master può parlare liberamente in italiano senza doversi autocensurare o utilizzare comandi vocali rigidi e innaturali.
- **Copertura testata al 100%**: oltre 25 casi tipici di negazioni e omografi sono costantemente verificati nella suite di regressione automatizzata `tests/test_corpus.py`.

### Negative / Trade-off
- L'analisi a clausole richiede regole sintattiche dedicate per la lingua italiana; l'estensione ad altre lingue richiede vocabolari di negazione e congiunzioni specifici.

## Alternative Scartate
- **Keyword matching semplice (sottostringhe)**: scartato per la valanga di falsi positivi sulle negazioni al tavolo.
- **Chiamata LLM remota per ogni singola frase**: scartata per lentezza (1-3 secondi di attesa rendono il cambio scena goffo e fuori tempo) e per i costi/privacy già discussi in ADR-0001.
