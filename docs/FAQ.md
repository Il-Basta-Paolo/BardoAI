# Domande Frequenti (FAQ)

Questa guida raccoglie le risposte ai dubbi più comuni sull'utilizzo di **Bardo AI** durante le sessioni reali di gioco di ruolo, sia al tavolo dal vivo sia online su Discord.

---

## 🎲 1. Al Tavolo da Gioco & Microfoni

### I dadi che rotolano, le risate o i bicchieri possono attivare per sbaglio musica o suoni?
**No.** Il sistema utilizza una doppia protezione:
1. **Filtro VAD (Voice Activity Detection) adattivo**: il modulo microfonico campiona costantemente l'energia spettrale dell'ambiente ed elabora solo i frammenti audio che presentano le caratteristiche armoniche della voce umana, scartando i transienti impulsivi e i rumori d'urto (dadi che cadono, penne sul tavolo, applausi).
2. **Isteresi e validazione semantica**: anche se un rumore dovesse superare la soglia del microfono, il modello STT offline cerca parole di senso compiuto in lingua italiana. Un colpo secco non produrrà mai frasi come *"I goblin caricano!"* né parole chiave SFX isolate. Inoltre, il regista musicale richiede un intervallo minimo di isteresi temporale tra un cambio d'atmosfera e l'altro per evitare oscillazioni repentine.

### Che tipo di microfono è consigliabile utilizzare?
Bardo AI funziona con qualsiasi microfono riconosciuto da Windows (USB, jack 3.5mm, cuffie con microfono o persino il microfono integrato del portatile).  
Per un'esperienza ottimale al tavolo con molti giocatori, si consiglia un microfono a diagramma polare **cardioide** posizionato vicino al Master e puntato verso la sua voce: questo massimizza la chiarezza della narrazione riducendo i brusii laterali degli altri giocatori.

### Cosa succede se interpreto un PNG con voce roca, urlata o sussurrata?
I modelli acustici (Vosk per gli effetti immediati e Faster-Whisper per la narrazione estesa) sono addestrati su una vastissima varietà di timbri e intonazioni naturali del parlato.  
Se stai recitando una scena molto teatrale con sussurri estremi quasi impercettibili, la tua voce potrebbe scendere sotto la soglia di cattura del microfono; in questi rari casi puoi sempre fare affidamento sulla **Soundboard a click** integrata a schermo per far partire qualsiasi atmosfera o suono manualmente con un solo tocco.

---

## 🎧 2. Sessioni Online & Discord

### Come posso trasmettere la musica e gli effetti sonori su Discord ai miei giocatori?
Per condividere l'audio di Bardo AI all'interno di un canale vocale Discord insieme alla tua voce, il metodo più semplice e diffuso consiste nell'utilizzare un cavo virtuale gratuito:

1. **Installa un cavo virtuale**: scarica il driver gratuito [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (o software similari).
2. **Imposta l'uscita in Bardo AI**: nelle Impostazioni audio di Windows o di Bardo AI, seleziona `CABLE Input (VB-Audio Virtual Cable)` come dispositivo di riproduzione audio principale.
3. **Instrada l'audio su Discord**:
   - Se usi un secondo account "Bot": apri Discord sul secondo account (o via browser), seleziona `CABLE Output` come microfono e unisciti al canale vocale.
   - Se vuoi usare il tuo account principale per trasmettere sia il tuo microfono sia Bardo AI: utilizza l'applicazione gratuita [Voicemeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm). Imposta il tuo microfono fisico su *Hardware Input 1*, il canale virtuale di Bardo AI su *Hardware Input 2*, e invia entrambi sul bus virtuale `B1` da selezionare come microfono su Discord.

### I miei giocatori rischiano di sentire l'eco della loro voce?
**No.** Bardo AI cattura esclusivamente l'ingresso del microfono selezionato e genera il flusso audio in uscita (musica + effetti). Non intercetta né reindirizza il flusso audio proveniente da Discord o dalle altre applicazioni del computer.

---

## 🔒 3. Connessione & Privacy Offline

### Posso usare Bardo AI completamente offline (es. in una baita senza Internet)?
**Sì.** Bardo AI è stato progettato con un'architettura **100% offline**:
- La pipeline vocale (Vosk e Faster-Whisper) viene eseguita per intero sulla CPU/GPU del tuo computer.
- L'intera soundboard con i 20 campioni audio di default (spade, frecce, ruggiti, fulmini, ecc.) e tutti i suoni personalizzati sono residenti in locale sul tuo disco fisso.
- La connessione Internet serve unicamente per lo streaming di nuove tracce musicali. Se hai già ascoltato brani in precedenza (che restano memorizzati nella cache locale) o se aggiungi le tue tracce audio nelle cartelle dei profili, l'intera applicazione è completamente autonoma anche in mezzo ai boschi o in assenza di rete.

### Le mie registrazioni vocali vengono inviate a server esterni?
**Mai.** A differenza di molti assistenti vocali cloud, Bardo AI non invia alcun pacchetto audio o testo trascritto all'esterno. La tua voce rimane confinata nella memoria RAM del tuo computer e viene cancellata subito dopo l'elaborazione del frame.

---

## 🛠️ 4. Personalizzazione & Campagne

### Posso aggiungere i miei file audio personali (.mp3, .wav, .ogg)?
**Certamente.** Puoi espandere la soundboard in qualsiasi momento:
- Clicca sulla scheda **Suoni Personalizzati** nell'interfaccia e premi il pulsante per aprire la cartella locale.
- Copia all'interno i tuoi file sonori (.wav, .mp3, .ogg o .flac).
- Il nome del file (senza estensione) diventerà automaticamente la parola chiave per attivarlo a voce e la dicitura sul pulsante a schermo.

### Posso creare profili per altri giochi di ruolo (es. Call of Cthulhu, Cyberpunk, ecc.)?
**Sì.** Bardo AI include già 4 profili preconfigurati (*Fantasy/D&D*, *Horror/Cthulhu*, *Sci-Fi/Cyberpunk*, *Giallo/Investigativo*). Puoi selezionarli dal menu a tendina in alto o personalizzarne le parole chiave e le playlist modificando il file di configurazione `config.json` nella cartella dati dell'applicazione.
