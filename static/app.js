/**
 * Bardo AI — Logica Frontend:
 * - Riconoscimento vocale continuo in Italiano (Web Speech API)
 * - Analisi ibrida (Parole chiave + AI)
 * - Doppio Player YouTube Music con Crossfade fluido + Fallback stream yt-dlp
 * - Gestione Profili GdR multipli, Atmosfere e Playlist YouTube Music
 */

const state = {
  config: null,
  ytmAuth: { authenticated: false },
  activeProfileId: "fantasy_dnd",
  currentMoodId: null,
  isMoodLocked: false,
  isListening: false,
  recognition: null,
  lastInterimAnalyzed: "",
  cooldownUntil: 0,
  cooldownInterval: null,

  // Coda e riproduzione
  queue: [],
  currentIndex: -1,
  isPlaying: false,
  masterVolume: 75,
  crossfadeSeconds: 3.5,

  // Doppio player YouTube IFrame per Crossfade
  ytReady: false,
  players: { A: null, B: null },
  activeSlot: "A", // "A", "B", oppure "AUDIO" (fallback)
  fadeInterval: null,
  progressInterval: null,
  speechLogCount: 0,
};

// --- INIZIALIZZAZIONE ---

document.addEventListener("DOMContentLoaded", async () => {
  bindUIEvents();
  await fetchConfig();
  initSpeechRecognition();
  startProgressLoop();
});

async function fetchConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    state.config = data.config;
    state.ytmAuth = data.ytmusic_auth || { authenticated: false };
    state.activeProfileId = state.config.active_profile_id || "fantasy_dnd";
    state.masterVolume = state.config.audio?.master_volume ?? 75;
    state.crossfadeSeconds = state.config.audio?.crossfade_seconds ?? 3.5;

    syncUIFromConfig();
  } catch (err) {
    showToast("Errore nel caricamento della configurazione: " + err.message);
  }
}

function getActiveProfile() {
  if (!state.config || !state.config.profiles) return null;
  return (
    state.config.profiles[state.activeProfileId] ||
    Object.values(state.config.profiles)[0]
  );
}

function syncUIFromConfig() {
  if (!state.config) return;

  // Popola selettore profili
  const profileSelect = document.getElementById("profileSelect");
  profileSelect.innerHTML = "";
  Object.values(state.config.profiles).forEach((prof) => {
    const opt = document.createElement("option");
    opt.value = prof.id;
    opt.textContent = `${prof.icon || "🎲"} ${prof.name}`;
    if (prof.id === state.activeProfileId) opt.selected = true;
    profileSelect.appendChild(opt);
  });

  // Slider volume e crossfade
  document.getElementById("volumeSlider").value = state.masterVolume;
  document.getElementById("volumeValueLabel").textContent = `${state.masterVolume}%`;
  document.getElementById("crossfadeSlider").value = state.crossfadeSeconds;
  document.getElementById("crossfadeValueLabel").textContent = `${state.crossfadeSeconds}s`;

  // Badge modalità analisi
  const mode = state.config.analyzer?.mode || "hybrid";
  const modeLabels = {
    hybrid: "Modalità: Ibrida (Parole + AI)",
    keywords: "Modalità: Parole Chiave (IT)",
    ai_always: "Modalità: Sempre AI",
  };
  document.getElementById("analyzerModeBadge").textContent =
    modeLabels[mode] || "Modalità: Ibrida";

  // Stato Account YT Music
  const authBadge = document.getElementById("ytmAuthStatusBadge");
  if (state.ytmAuth?.authenticated) {
    authBadge.textContent = "✅ Account YouTube Music Collegato";
    authBadge.style.color = "#34d399";
  } else {
    authBadge.textContent = "Modalità Diretta Attiva (Senza Login)";
    authBadge.style.color = "#94a3b8";
  }

  renderMoodsGrid();
  populateAssignMoodSelect();
  renderSavedPlaylists();
}

// --- RENDERING SOUNDBOARD ATMOSFERE ---

function renderMoodsGrid() {
  const profile = getActiveProfile();
  if (!profile) return;

  document.getElementById("profileTitle").textContent = `${profile.icon || "🐉"} Atmosfere — ${profile.name}`;
  document.getElementById("profileDesc").textContent =
    profile.description || "Clicca un'atmosfera o parla al microfono per attivare la musica.";

  const grid = document.getElementById("moodsGrid");
  grid.innerHTML = "";

  const moods = profile.moods || {};
  Object.values(moods).forEach((mood) => {
    const card = document.createElement("div");
    card.className = `mood-card ${state.currentMoodId === mood.id ? "active" : ""}`;
    card.style.setProperty("--mood-color", mood.color || "#10b981");

    const sampleKw = [
      ...(mood.phrases || []).slice(0, 2),
      ...(mood.keywords || []).slice(0, 3),
    ].slice(0, 4);

    const hasCustomPl = Boolean(mood.custom_playlist && mood.custom_playlist.trim());
    const pinnedCount = (mood.pinned_tracks || []).length;

    card.innerHTML = `
      <div>
        <div class="mood-card-top">
          <div class="mood-title-group">
            <span class="mood-icon">${mood.icon || "🎵"}</span>
            <span class="mood-name">${escapeHtml(mood.name)}</span>
          </div>
          <button class="btn-edit-mood" title="Modifica parole chiave, query o playlist" data-edit-mood="${mood.id}">⚙️</button>
        </div>
        <p class="mood-desc">${escapeHtml(mood.description || "")}</p>
      </div>
      <div class="mood-tags">
        ${hasCustomPl ? `<span class="mood-tag playlist-tag">🎵 Playlist Personale</span>` : ""}
        ${pinnedCount > 0 ? `<span class="mood-tag playlist-tag">📌 ${pinnedCount} fissati</span>` : ""}
        ${sampleKw.map((k) => `<span class="mood-tag">"${escapeHtml(k)}"</span>`).join("")}
      </div>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.closest("[data-edit-mood]")) {
        e.stopPropagation();
        openEditMoodModal(mood.id);
        return;
      }
      triggerMoodManually(mood.id);
    });

    grid.appendChild(card);
  });
}

// --- RICONOSCIMENTO VOCALE CONTINUO IN ITALIANO ---

function initSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    document.getElementById("micStatusLabel").textContent =
      "⚠️ Il browser non supporta Web Speech API (usa Chrome o Edge per il microfono, oppure la barra di testo sotto).";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "it-IT";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    document.getElementById("micPulseDot").classList.add("active");
    document.getElementById("micStatusLabel").textContent =
      "In ascolto in italiano... Parla liberamente durante la sessione!";
  };

  recognition.onresult = (event) => {
    let interimTranscript = "";
    let finalTranscript = "";

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript + " ";
      } else {
        interimTranscript += transcript;
      }
    }

    const liveBox = document.getElementById("liveInterimText");
    if (finalTranscript.trim()) {
      liveBox.textContent = `« ${finalTranscript.trim()} »`;
      state.lastInterimAnalyzed = "";
      analyzeSpokenText(finalTranscript.trim(), false);
    } else if (interimTranscript.trim()) {
      liveBox.textContent = `« ${interimTranscript.trim()}... »`;
      // Se la frase parziale contiene già parole forti (almeno 3 parole nuove), analizzala in anticipo per reattività immediata
      const words = interimTranscript.trim().split(/\s+/);
      if (
        words.length >= 3 &&
        interimTranscript.trim() !== state.lastInterimAnalyzed &&
        interimTranscript.length - state.lastInterimAnalyzed.length > 12
      ) {
        state.lastInterimAnalyzed = interimTranscript.trim();
        analyzeSpokenText(interimTranscript.trim(), true);
      }
    }
  };

  recognition.onerror = (event) => {
    if (event.error === "no-speech" || event.error === "aborted") {
      return;
    }
    console.warn("[SpeechRecognition] Errore:", event.error);
    if (event.error === "not-allowed") {
      state.isListening = false;
      updateMicButtonUI();
      showToast("Permesso microfono negato dal browser. Consenti l'accesso al microfono nella barra dell'indirizzo.");
    }
  };

  recognition.onend = () => {
    // Riavvio automatico continuo finché l'utente mantiene attivo l'ascolto
    if (state.isListening) {
      try {
        recognition.start();
      } catch (e) {
        setTimeout(() => {
          if (state.isListening) {
            try { recognition.start(); } catch (_) {}
          }
        }, 400);
      }
    } else {
      document.getElementById("micPulseDot").classList.remove("active");
      document.getElementById("micStatusLabel").textContent =
        "Microfono in pausa — clicca 'Avvia Ascolto Vocale' per riprendere";
    }
  };

  state.recognition = recognition;
}

function toggleMicrophone() {
  if (!state.recognition) {
    showToast("Usa Google Chrome o Microsoft Edge per il riconoscimento vocale in tempo reale.");
    return;
  }

  state.isListening = !state.isListening;
  updateMicButtonUI();

  if (state.isListening) {
    try {
      state.recognition.start();
      showToast("🎙️ Ascolto vocale in italiano attivato!");
    } catch (e) {
      console.warn(e);
    }
  } else {
    try {
      state.recognition.stop();
    } catch (e) {
      console.warn(e);
    }
  }
}

function updateMicButtonUI() {
  const btn = document.getElementById("btnToggleMic");
  const txt = document.getElementById("micBtnText");
  if (state.isListening) {
    btn.classList.add("listening");
    txt.textContent = "Ascolto Attivo (Clicca per Pausa)";
  } else {
    btn.classList.remove("listening");
    txt.textContent = "Avvia Ascolto Vocale (IT)";
  }
}

// --- ANALISI DEL TESTO PARLATO E ATTIVAZIONE MUSICA ---

async function analyzeSpokenText(text, isInterim = false) {
  if (!text || text.trim().length < 2) return;

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        profile_id: state.activeProfileId,
        current_mood_id: state.currentMoodId,
      }),
    });
    const data = await res.json();

    // 1. Azioni vocali sul player (pausa, riprendi, prossima traccia)
    if (data.voice_action) {
      if (!isInterim) {
        handleVoiceAction(data.voice_action, text, data.reason);
      }
      return;
    }

    const detectedMoodId = data.mood_id;
    const isCommand = data.matched_by === "command" || data.force_change;

    if (!isInterim) {
      addSpeechLogEntry(text, data);
    }

    if (!detectedMoodId) return;

    // Se l'atmosfera è bloccata manualmente e non è un comando esplicito "Bardo metti..."
    if (state.isMoodLocked && !isCommand) {
      return;
    }

    // Se siamo già in quell'atmosfera e non è un comando forzato, non interrompere la musica
    if (detectedMoodId === state.currentMoodId && !isCommand) {
      return;
    }

    // Controlla Cooldown per evitare cambi continui (a meno che non sia il primo avvio o un comando esplicito)
    const now = Date.now();
    if (!isCommand && state.currentMoodId && now < state.cooldownUntil) {
      return;
    }

    // Attiva la nuova atmosfera!
    startCooldown();
    if (data.playback) {
      applyMoodPlayback(detectedMoodId, data.playback, data.matched_terms, data.matched_by);
    } else {
      await triggerMoodManually(detectedMoodId);
    }
  } catch (err) {
    console.error("Errore analisi:", err);
  }
}

function handleVoiceAction(action, text, reason) {
  addSpeechLogEntry(text, { matched_by: "command", matched_terms: [reason || action] });
  if (action === "pause") {
    pausePlayback();
    showToast("⏸️ Musica messa in pausa dal comando vocale");
  } else if (action === "resume") {
    resumePlayback();
    showToast("▶️ Riproduzione ripresa");
  } else if (action === "next") {
    playNextTrack();
    showToast("⏭️ Prossima traccia");
  }
}

function startCooldown() {
  const sec = Number(state.config?.analyzer?.cooldown_seconds ?? 18);
  if (sec <= 0) return;

  state.cooldownUntil = Date.now() + sec * 1000;
  const badge = document.getElementById("cooldownBadge");
  const timerEl = document.getElementById("cooldownTimer");
  badge.classList.remove("hidden");

  if (state.cooldownInterval) clearInterval(state.cooldownInterval);
  state.cooldownInterval = setInterval(() => {
    const rem = Math.ceil((state.cooldownUntil - Date.now()) / 1000);
    if (rem <= 0) {
      badge.classList.add("hidden");
      clearInterval(state.cooldownInterval);
    } else {
      timerEl.textContent = `${rem}s`;
    }
  }, 500);
}

function addSpeechLogEntry(text, result) {
  const log = document.getElementById("speechLog");
  state.speechLogCount += 1;
  document.getElementById("logCount").textContent = state.speechLogCount;

  const profile = getActiveProfile();
  const mood = profile?.moods?.[result.mood_id];
  const entry = document.createElement("div");
  entry.className = `log-entry ${mood ? "matched" : ""}`;

  const terms = (result.matched_terms || []).join(", ");
  const rightBadge = mood
    ? `<span class="log-badge">${mood.icon} ${escapeHtml(mood.name)} (${escapeHtml(terms || result.matched_by)})</span>`
    : result.voice_action
    ? `<span class="log-badge">🎛️ ${escapeHtml(terms)}</span>`
    : `<span class="log-badge">Nessun cambio</span>`;

  entry.innerHTML = `
    <span>"${escapeHtml(text)}"</span>
    ${rightBadge}
  `;
  log.prepend(entry);
}

// --- ATTIVAZIONE ATMOSFERA E CARICAMENTO BRANI YOUTUBE MUSIC ---

async function triggerMoodManually(moodId) {
  const profile = getActiveProfile();
  const mood = profile?.moods?.[moodId];
  if (!mood) return;

  showToast(`${mood.icon} Caricamento atmosfera: ${mood.name}...`);
  try {
    const res = await fetch(`/api/mood-tracks/${state.activeProfileId}/${moodId}`);
    const playback = await res.json();
    applyMoodPlayback(moodId, playback, ["Selezione manuale"], "manual");
  } catch (err) {
    showToast("Errore caricamento brani: " + err.message);
  }
}

function applyMoodPlayback(moodId, playback, matchedTerms = [], matchedBy = "") {
  state.currentMoodId = moodId;
  const mood = playback.mood;
  const tracks = playback.tracks || [];

  // Aggiorna colore ambientale ed evidenzia card
  const color = mood.color || "#10b981";
  document.documentElement.style.setProperty("--accent", color);
  document.documentElement.style.setProperty("--accent-glow", hexToRgba(color, 0.28));
  renderMoodsGrid();

  // Aggiorna badge player
  const badge = document.getElementById("activeMoodBadge");
  badge.textContent = `${mood.icon} ${mood.name}`;
  badge.style.borderColor = color;
  badge.style.color = "#fff";
  badge.style.background = hexToRgba(color, 0.25);

  document.getElementById("playbackSourceBadge").textContent =
    playback.source || "YouTube Music";

  if (matchedBy && matchedBy !== "manual") {
    const reasonStr = matchedTerms?.length ? ` (${matchedTerms.join(", ")})` : "";
    showToast(`${mood.icon} Scena rilevata: ${mood.name}${reasonStr}`);
  }

  if (tracks.length > 0) {
    state.queue = tracks;
    state.currentIndex = 0;
    renderQueue();
    playTrackWithCrossfade(state.queue[0]);
  } else {
    showToast("Nessun brano trovato per questa atmosfera.");
  }
}

// --- DOPPIO PLAYER YOUTUBE MUSIC CON CROSSFADE + FALLBACK AUDIO ---

window.onYouTubeIframeAPIReady = function () {
  state.players.A = new YT.Player("yt-player-a", {
    height: "200",
    width: "200",
    playerVars: { autoplay: 0, controls: 0, disablekb: 1, rel: 0 },
    events: {
      onReady: () => { state.ytReady = true; },
      onStateChange: (e) => onYTPlayerStateChange("A", e),
      onError: (e) => onYTPlayerError("A", e),
    },
  });

  state.players.B = new YT.Player("yt-player-b", {
    height: "200",
    width: "200",
    playerVars: { autoplay: 0, controls: 0, disablekb: 1, rel: 0 },
    events: {
      onReady: () => { state.ytReady = true; },
      onStateChange: (e) => onYTPlayerStateChange("B", e),
      onError: (e) => onYTPlayerError("B", e),
    },
  });
};

function onYTPlayerStateChange(slot, event) {
  if (slot !== state.activeSlot) return;
  if (event.data === YT.PlayerState.ENDED) {
    playNextTrack();
  } else if (event.data === YT.PlayerState.PLAYING) {
    state.isPlaying = true;
    document.getElementById("btnPlayPause").textContent = "⏸️";
  } else if (event.data === YT.PlayerState.PAUSED) {
    state.isPlaying = false;
    document.getElementById("btnPlayPause").textContent = "▶️";
  }
}

async function onYTPlayerError(slot, event) {
  if (slot !== state.activeSlot) return;
  const currentTrack = state.queue[state.currentIndex];
  if (!currentTrack) return;

  console.warn(`[YT Player ${slot}] Restrizione embed (${event.data}) per ${currentTrack.title}, attivo stream diretto yt-dlp...`);
  try {
    const res = await fetch(`/api/ytmusic/stream/${currentTrack.videoId}`);
    if (!res.ok) throw new Error("Stream fallback non disponibile");
    const streamData = await res.json();
    if (streamData.stream_url) {
      playViaFallbackAudio(streamData.stream_url);
      return;
    }
  } catch (e) {
    console.warn("Fallback audio non riuscito, passo al brano successivo:", e);
  }
  playNextTrack();
}

function playViaFallbackAudio(streamUrl) {
  const audioEl = document.getElementById("fallbackAudioPlayer");
  try {
    if (state.players.A?.pauseVideo) state.players.A.pauseVideo();
    if (state.players.B?.pauseVideo) state.players.B.pauseVideo();
  } catch (_) {}

  state.activeSlot = "AUDIO";
  audioEl.src = streamUrl;
  audioEl.volume = state.masterVolume / 100;
  audioEl.play().then(() => {
    state.isPlaying = true;
    document.getElementById("btnPlayPause").textContent = "⏸️";
  }).catch(() => {
    playNextTrack();
  });

  audioEl.onended = () => playNextTrack();
}

function playTrackWithCrossfade(track) {
  if (!track || !track.videoId) return;

  // Aggiorna UI brano corrente
  document.getElementById("currentTrackThumb").src =
    track.thumbnail || `https://i.ytimg.com/vi/${track.videoId}/hqdefault.jpg`;
  document.getElementById("currentTrackTitle").textContent = track.title || "Brano";
  document.getElementById("currentTrackArtist").textContent = track.artist || "YouTube Music";
  document.getElementById("currentTrackYTMUrl").href =
    track.ytmusic_url || `https://music.youtube.com/watch?v=${track.videoId}`;
  renderQueue();

  // Ferma eventuale player audio fallback
  const audioEl = document.getElementById("fallbackAudioPlayer");
  if (!audioEl.paused) {
    audioEl.pause();
  }

  if (!state.ytReady || !state.players.A || !state.players.B) {
    // Se l'API IFrame sta ancora inizializzando, usa subito lo stream diretto o riprova tra 400ms
    setTimeout(() => playTrackWithCrossfade(track), 400);
    return;
  }

  const prevSlot = state.activeSlot === "B" ? "B" : "A";
  const nextSlot = prevSlot === "A" ? "B" : "A";
  const outgoingPlayer = state.players[prevSlot];
  const incomingPlayer = state.players[nextSlot];

  state.activeSlot = nextSlot;
  state.isPlaying = true;
  document.getElementById("btnPlayPause").textContent = "⏸️";

  const fadeSec = Number(state.crossfadeSeconds);
  const targetVol = Number(state.masterVolume);

  if (state.fadeInterval) {
    clearInterval(state.fadeInterval);
    state.fadeInterval = null;
  }

  // Avvia nuovo brano nel player entrante
  try {
    incomingPlayer.setVolume(fadeSec > 0 ? 0 : targetVol);
    incomingPlayer.loadVideoById(track.videoId);
    incomingPlayer.playVideo();
  } catch (e) {
    console.error("Errore avvio player entrante:", e);
  }

  if (fadeSec <= 0) {
    try { outgoingPlayer.pauseVideo(); } catch (_) {}
    document.getElementById("crossfadeIndicator").classList.add("hidden");
    return;
  }

  // Esegui Crossfade graduale
  const indicator = document.getElementById("crossfadeIndicator");
  indicator.classList.remove("hidden");

  const steps = 25;
  const stepMs = (fadeSec * 1000) / steps;
  let currentStep = 0;

  state.fadeInterval = setInterval(() => {
    currentStep += 1;
    const ratio = Math.min(1, currentStep / steps);
    const inVol = Math.round(targetVol * ratio);
    const outVol = Math.round(targetVol * (1 - ratio));

    try {
      incomingPlayer.setVolume(inVol);
      outgoingPlayer.setVolume(outVol);
    } catch (_) {}

    if (currentStep >= steps) {
      clearInterval(state.fadeInterval);
      state.fadeInterval = null;
      try {
        outgoingPlayer.pauseVideo();
      } catch (_) {}
      indicator.classList.add("hidden");
    }
  }, stepMs);
}

function togglePlayPause() {
  if (state.queue.length === 0) {
    const profile = getActiveProfile();
    if (profile?.default_mood) {
      triggerMoodManually(profile.default_mood);
    }
    return;
  }
  if (state.isPlaying) {
    pausePlayback();
  } else {
    resumePlayback();
  }
}

function pausePlayback() {
  state.isPlaying = false;
  document.getElementById("btnPlayPause").textContent = "▶️";
  const audioEl = document.getElementById("fallbackAudioPlayer");
  if (state.activeSlot === "AUDIO") {
    audioEl.pause();
  } else {
    try { state.players[state.activeSlot]?.pauseVideo(); } catch (_) {}
  }
}

function resumePlayback() {
  state.isPlaying = true;
  document.getElementById("btnPlayPause").textContent = "⏸️";
  const audioEl = document.getElementById("fallbackAudioPlayer");
  if (state.activeSlot === "AUDIO") {
    audioEl.play();
  } else {
    try { state.players[state.activeSlot]?.playVideo(); } catch (_) {}
  }
}

function playNextTrack() {
  if (state.queue.length === 0) return;
  state.currentIndex = (state.currentIndex + 1) % state.queue.length;
  playTrackWithCrossfade(state.queue[state.currentIndex]);
}

function playPrevTrack() {
  if (state.queue.length === 0) return;
  state.currentIndex =
    (state.currentIndex - 1 + state.queue.length) % state.queue.length;
  playTrackWithCrossfade(state.queue[state.currentIndex]);
}

function renderQueue() {
  const list = document.getElementById("queueList");
  document.getElementById("queueCount").textContent = state.queue.length;
  list.innerHTML = "";

  if (state.queue.length === 0) {
    list.innerHTML = `<div class="empty-queue">Nessun brano in coda.</div>`;
    return;
  }

  state.queue.forEach((track, idx) => {
    const item = document.createElement("div");
    item.className = `queue-item ${idx === state.currentIndex ? "playing" : ""}`;
    item.innerHTML = `
      <img src="${escapeHtml(track.thumbnail || `https://i.ytimg.com/vi/${track.videoId}/hqdefault.jpg`)}" alt="" />
      <div class="queue-item-info">
        <div class="queue-item-title">${idx === state.currentIndex ? "🔊 " : ""}${escapeHtml(track.title)}</div>
        <div class="queue-item-artist">${escapeHtml(track.artist || "YouTube Music")} ${track.duration ? `• ${escapeHtml(track.duration)}` : ""}</div>
      </div>
    `;
    item.addEventListener("click", () => {
      state.currentIndex = idx;
      playTrackWithCrossfade(track);
    });
    list.appendChild(item);
  });
}

function startProgressLoop() {
  if (state.progressInterval) clearInterval(state.progressInterval);
  state.progressInterval = setInterval(() => {
    if (!state.isPlaying) return;

    let cur = 0;
    let dur = 0;
    if (state.activeSlot === "AUDIO") {
      const audioEl = document.getElementById("fallbackAudioPlayer");
      cur = audioEl.currentTime || 0;
      dur = audioEl.duration || 0;
    } else {
      const p = state.players[state.activeSlot];
      if (p && typeof p.getCurrentTime === "function") {
        cur = p.getCurrentTime() || 0;
        dur = p.getDuration() || 0;
      }
    }

    if (dur > 0) {
      document.getElementById("currentTimeLabel").textContent = formatSeconds(cur);
      document.getElementById("durationLabel").textContent = formatSeconds(dur);
      document.getElementById("seekSlider").value = Math.min(100, Math.round((cur / dur) * 100));
    }
  }, 1000);
}

// --- EVENTI INTERFACCIA E MODALI ---

function bindUIEvents() {
  // Microfono e Lock
  document.getElementById("btnToggleMic").addEventListener("click", toggleMicrophone);

  document.getElementById("btnLockMood").addEventListener("click", () => {
    state.isMoodLocked = !state.isMoodLocked;
    const btn = document.getElementById("btnLockMood");
    if (state.isMoodLocked) {
      btn.textContent = "🔒 Atmosfera Bloccata";
      btn.style.borderColor = "#f59e0b";
      btn.style.color = "#fbbf24";
      showToast("🔒 Atmosfera bloccata: la voce non cambierà scena finché non sblocchi.");
    } else {
      btn.textContent = "🔓 Cambio Auto Attivo";
      btn.style.borderColor = "";
      btn.style.color = "";
      showToast("🔓 Cambio atmosfera vocale riattivato.");
    }
  });

  // Simulazione frase scritta
  document.getElementById("simulateForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("simulateInput");
    const text = input.value.trim();
    if (!text) return;
    document.getElementById("liveInterimText").textContent = `« ${text} »`;
    analyzeSpokenText(text, false);
    input.value = "";
  });

  // Chip di prova rapida
  document.querySelectorAll(".chip[data-phrase]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const phrase = chip.getAttribute("data-phrase");
      document.getElementById("liveInterimText").textContent = `« ${phrase} »`;
      // Ignora il cooldown sui click dei chip dimostrativi
      state.cooldownUntil = 0;
      analyzeSpokenText(phrase, false);
    });
  });

  // Cambio profilo ambientazione
  document.getElementById("profileSelect").addEventListener("change", async (e) => {
    state.activeProfileId = e.target.value;
    state.currentMoodId = null;
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_profile_id: state.activeProfileId }),
    });
    syncUIFromConfig();
    showToast("Profilo ambientazione aggiornato!");
  });

  // Controlli Player
  document.getElementById("btnPlayPause").addEventListener("click", togglePlayPause);
  document.getElementById("btnNextTrack").addEventListener("click", playNextTrack);
  document.getElementById("btnPrevTrack").addEventListener("click", playPrevTrack);
  document.getElementById("btnShuffleQueue").addEventListener("click", () => {
    if (state.queue.length <= 1) return;
    state.queue.sort(() => Math.random() - 0.5);
    state.currentIndex = 0;
    renderQueue();
    playTrackWithCrossfade(state.queue[0]);
    showToast("🔀 Coda mescolata!");
  });

  // Seek barra progresso
  document.getElementById("seekSlider").addEventListener("input", (e) => {
    const pct = Number(e.target.value) / 100;
    if (state.activeSlot === "AUDIO") {
      const audioEl = document.getElementById("fallbackAudioPlayer");
      if (audioEl.duration) audioEl.currentTime = audioEl.duration * pct;
    } else {
      const p = state.players[state.activeSlot];
      if (p && typeof p.getDuration === "function") {
        const dur = p.getDuration();
        if (dur > 0) p.seekTo(dur * pct, true);
      }
    }
  });

  // Volume e Crossfade
  document.getElementById("volumeSlider").addEventListener("input", (e) => {
    state.masterVolume = Number(e.target.value);
    document.getElementById("volumeValueLabel").textContent = `${state.masterVolume}%`;
    if (state.activeSlot === "AUDIO") {
      document.getElementById("fallbackAudioPlayer").volume = state.masterVolume / 100;
    } else {
      try { state.players[state.activeSlot]?.setVolume(state.masterVolume); } catch (_) {}
    }
  });

  document.getElementById("volumeSlider").addEventListener("change", () => {
    fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio: { master_volume: state.masterVolume } }),
    });
  });

  document.getElementById("crossfadeSlider").addEventListener("input", (e) => {
    state.crossfadeSeconds = Number(e.target.value);
    document.getElementById("crossfadeValueLabel").textContent = `${state.crossfadeSeconds}s`;
  });

  document.getElementById("crossfadeSlider").addEventListener("change", () => {
    fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio: { crossfade_seconds: state.crossfadeSeconds } }),
    });
  });

  // Fissa brano corrente nell'atmosfera attiva
  document.getElementById("btnPinCurrentTrack").addEventListener("click", async () => {
    const track = state.queue[state.currentIndex];
    if (!track || !state.currentMoodId) {
      showToast("Seleziona prima un'atmosfera e avvia un brano.");
      return;
    }
    const res = await fetch("/api/mood/pin-track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_id: state.activeProfileId,
        mood_id: state.currentMoodId,
        track: track,
      }),
    });
    const data = await res.json();
    if (data.config) {
      state.config = data.config;
      renderMoodsGrid();
      showToast(`📌 "${track.title}" fissato nell'atmosfera corrente!`);
    }
  });

  // Ricerca istantanea su YouTube Music
  document.getElementById("instantSearchForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = document.getElementById("instantSearchInput").value.trim();
    if (!q) return;
    showToast(`🔍 Ricerca su YouTube Music: "${q}"...`);
    try {
      const res = await fetch(`/api/ytmusic/search?q=${encodeURIComponent(q)}&type=tracks`);
      const data = await res.json();
      if (data.tracks && data.tracks.length > 0) {
        state.queue = data.tracks;
        state.currentIndex = 0;
        document.getElementById("playbackSourceBadge").textContent = `Ricerca: ${q}`;
        renderQueue();
        playTrackWithCrossfade(state.queue[0]);
      } else {
        showToast("Nessun risultato trovato.");
      }
    } catch (err) {
      showToast("Errore ricerca: " + err.message);
    }
  });

  // Apertura/chiusura modali
  document.getElementById("btnOpenYTMModal").addEventListener("click", () => {
    populateAssignMoodSelect();
    renderSavedPlaylists();
    document.getElementById("modalYTM").classList.remove("hidden");
  });

  document.getElementById("btnOpenAISettings").addEventListener("click", () => {
    openAISettingsModal();
  });

  document.getElementById("btnAddMood").addEventListener("click", () => {
    openEditMoodModal(null);
  });

  document.getElementById("btnNewProfile").addEventListener("click", () => {
    document.getElementById("modalNewProfile").classList.remove("hidden");
  });

  document.getElementById("btnDeleteProfile").addEventListener("click", async () => {
    const prof = getActiveProfile();
    if (!prof) return;
    if (!confirm(`Vuoi davvero eliminare il profilo "${prof.name}"?`)) return;
    const res = await fetch(`/api/profile/${prof.id}`, { method: "DELETE" });
    if (res.ok) {
      const data = await res.json();
      state.config = data.config;
      state.activeProfileId = state.config.active_profile_id;
      syncUIFromConfig();
      showToast("Profilo eliminato.");
    } else {
      const err = await res.json();
      showToast(err.detail || "Impossibile eliminare il profilo.");
    }
  });

  document.querySelectorAll(".btn-close[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-close");
      document.getElementById(id).classList.add("hidden");
    });
  });

  // --- Eventi Modale YouTube Music ---
  document.getElementById("formAddPlaylistUrl").addEventListener("submit", async (e) => {
    e.preventDefault();
    const urlInput = document.getElementById("inputPlaylistUrl").value.trim();
    const assignMood = document.getElementById("selectAssignMood").value;
    if (!urlInput) return;

    showToast("⏳ Caricamento playlist da YouTube Music...");
    try {
      const res = await fetch("/api/ytmusic/save-playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_input: urlInput,
          assign_to_profile_id: assignMood ? state.activeProfileId : null,
          assign_to_mood_id: assignMood || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Errore caricamento playlist");

      state.config = data.config;
      syncUIFromConfig();
      document.getElementById("inputPlaylistUrl").value = "";
      showToast(`✅ Playlist "${data.playlist.title}" (${data.playlist.trackCount} brani) importata!`);

      // Avvia subito in coda se richiesto
      if (data.playlist.tracks?.length) {
        state.queue = data.playlist.tracks;
        state.currentIndex = 0;
        document.getElementById("playbackSourceBadge").textContent = data.playlist.title;
        renderQueue();
        playTrackWithCrossfade(state.queue[0]);
      }
    } catch (err) {
      showToast("Errore: " + err.message);
    }
  });

  document.getElementById("btnSearchYTMPlaylists").addEventListener("click", async () => {
    const q = document.getElementById("inputSearchYTMPlaylists").value.trim();
    if (!q) return;
    showToast(`🔍 Cerco playlist "${q}" su YouTube Music...`);
    const res = await fetch(`/api/ytmusic/search?q=${encodeURIComponent(q)}&type=playlists`);
    const data = await res.json();
    renderPlaylistsList(data.playlists || []);
  });

  document.getElementById("btnLoadAccountPlaylists").addEventListener("click", async () => {
    const res = await fetch("/api/ytmusic/user-playlists");
    const data = await res.json();
    if (!data.authenticated) {
      showToast("Collega prima il tuo account nella sezione 3 qui sotto, oppure incolla il link della playlist nella sezione 1!");
      return;
    }
    renderPlaylistsList(data.playlists || []);
  });

  document.getElementById("btnConnectYTMAccount").addEventListener("click", async () => {
    const raw = document.getElementById("inputYTMHeaders").value.trim();
    if (!raw) {
      showToast("Incolla prima i Request Headers copiati da music.youtube.com");
      return;
    }
    try {
      const res = await fetch("/api/ytmusic/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ headers_raw: raw }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Errore autenticazione");
      state.ytmAuth.authenticated = true;
      syncUIFromConfig();
      renderPlaylistsList(data.playlists || []);
      showToast(`🎉 Account YouTube Music collegato! Trovate ${data.playlists_count} playlist.`);
    } catch (err) {
      showToast(err.message);
    }
  });

  document.getElementById("btnDisconnectYTMAccount").addEventListener("click", async () => {
    await fetch("/api/ytmusic/disconnect", { method: "POST" });
    state.ytmAuth.authenticated = false;
    syncUIFromConfig();
    showToast("Account YouTube Music scollegato.");
  });

  // --- Eventi Modale Impostazioni AI ---
  document.getElementById("settingAIProvider").addEventListener("change", (e) => {
    updateAIProviderBoxes(e.target.value);
  });

  document.getElementById("formAISettings").addEventListener("submit", async (e) => {
    e.preventDefault();
    const analyzerCfg = {
      mode: document.getElementById("settingAnalyzerMode").value,
      cooldown_seconds: Number(document.getElementById("settingCooldown").value),
      confidence_threshold: Number(document.getElementById("settingThreshold").value),
      ai_provider: document.getElementById("settingAIProvider").value,
      gemini_api_key: document.getElementById("settingGeminiKey").value.trim(),
      gemini_model: document.getElementById("settingGeminiModel").value.trim(),
      ollama_url: document.getElementById("settingOllamaUrl").value.trim(),
      ollama_model: document.getElementById("settingOllamaModel").value.trim(),
      openai_api_key: document.getElementById("settingOpenAIKey").value.trim(),
      openai_base_url: document.getElementById("settingOpenAIBaseUrl").value.trim(),
      openai_model: document.getElementById("settingOpenAIModel").value.trim(),
    };
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analyzer: analyzerCfg }),
    });
    const data = await res.json();
    state.config = data.config;
    syncUIFromConfig();
    document.getElementById("modalAISettings").classList.add("hidden");
    showToast("💾 Impostazioni di analisi salvate!");
  });

  document.getElementById("btnResetDefaults").addEventListener("click", async () => {
    if (!confirm("Ripristinare tutti i profili e le atmosfere ai valori predefiniti?")) return;
    const res = await fetch("/api/profiles/reset", { method: "POST" });
    const data = await res.json();
    state.config = data.config;
    syncUIFromConfig();
    document.getElementById("modalAISettings").classList.add("hidden");
    showToast("Profili predefiniti ripristinati.");
  });

  // --- Eventi Modale Modifica Atmosfera ---
  document.getElementById("formEditMood").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveMoodFromModal();
  });

  document.getElementById("btnDeleteMood").addEventListener("click", async () => {
    const moodId = document.getElementById("editMoodId").value;
    const profile = getActiveProfile();
    if (!profile || !moodId || !profile.moods[moodId]) return;
    if (!confirm(`Eliminare l'atmosfera "${profile.moods[moodId].name}"?`)) return;

    delete profile.moods[moodId];
    const res = await fetch("/api/profile/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile }),
    });
    const data = await res.json();
    state.config = data.config;
    syncUIFromConfig();
    document.getElementById("modalEditMood").classList.add("hidden");
    showToast("Atmosfera eliminata.");
  });

  // --- Eventi Modale Nuovo Profilo ---
  document.getElementById("formNewProfile").addEventListener("submit", async (e) => {
    e.preventDefault();
    const icon = document.getElementById("newProfileIcon").value.trim() || "🎲";
    const name = document.getElementById("newProfileName").value.trim();
    const desc = document.getElementById("newProfileDesc").value.trim();
    const tpl = document.getElementById("newProfileTemplate").value;
    if (!name) return;

    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_" + Date.now().toString().slice(-4);
    let moods = {};
    let defaultMood = "";

    if (tpl !== "empty" && state.config.profiles[tpl]) {
      moods = JSON.parse(JSON.stringify(state.config.profiles[tpl].moods));
      defaultMood = state.config.profiles[tpl].default_mood;
    }

    const newProfile = {
      id,
      name,
      icon,
      description: desc,
      default_mood: defaultMood,
      moods,
    };

    const res = await fetch("/api/profile/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: newProfile }),
    });
    const data = await res.json();
    state.config = data.config;
    state.activeProfileId = id;
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_profile_id: id }),
    });
    syncUIFromConfig();
    document.getElementById("modalNewProfile").classList.add("hidden");
    showToast(`✨ Profilo "${name}" creato!`);
  });
}

// --- FUNZIONI DI SUPPORTO MODALI ---

function populateAssignMoodSelect() {
  const sel = document.getElementById("selectAssignMood");
  sel.innerHTML = `<option value="">-- Solo salva in libreria (o scegli atmosfera) --</option>`;
  const profile = getActiveProfile();
  if (!profile) return;
  Object.values(profile.moods || {}).forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `Associa a: ${m.icon} ${m.name}`;
    sel.appendChild(opt);
  });
}

function renderSavedPlaylists() {
  const saved = state.config?.audio?.saved_playlists || [];
  renderPlaylistsList(saved);
}

function renderPlaylistsList(playlists) {
  const container = document.getElementById("playlistsContainer");
  container.innerHTML = "";
  if (!playlists.length) {
    container.innerHTML = `<p class="help-text">Nessuna playlist caricata. Cerca una playlist qui sopra o incolla un link YouTube Music!</p>`;
    return;
  }

  playlists.forEach((pl) => {
    const card = document.createElement("div");
    card.className = "playlist-card";
    card.innerHTML = `
      <img src="${escapeHtml(pl.thumbnail || "https://i.ytimg.com/vi/jfKfPfyJRdk/hqdefault.jpg")}" alt="" />
      <div class="playlist-card-info">
        <div class="playlist-card-title">${escapeHtml(pl.title)}</div>
        <button class="btn btn-secondary btn-sm" style="margin-top:4px;">▶️ Riproduci / Usa</button>
      </div>
    `;
    card.querySelector("button").addEventListener("click", async () => {
      document.getElementById("inputPlaylistUrl").value = pl.playlistId;
      showToast(`⏳ Carico brani della playlist "${pl.title}"...`);
      const res = await fetch(`/api/ytmusic/playlist?id_or_url=${encodeURIComponent(pl.playlistId)}`);
      const data = await res.json();
      if (data.tracks?.length) {
        state.queue = data.tracks;
        state.currentIndex = 0;
        document.getElementById("playbackSourceBadge").textContent = data.title;
        renderQueue();
        playTrackWithCrossfade(state.queue[0]);
        document.getElementById("modalYTM").classList.add("hidden");
      }
    });
    container.appendChild(card);
  });
}

function openAISettingsModal() {
  const cfg = state.config?.analyzer || {};
  document.getElementById("settingAnalyzerMode").value = cfg.mode || "hybrid";
  document.getElementById("settingCooldown").value = cfg.cooldown_seconds ?? 18;
  document.getElementById("settingThreshold").value = cfg.confidence_threshold ?? 2.0;
  document.getElementById("settingAIProvider").value = cfg.ai_provider || "gemini";
  document.getElementById("settingGeminiKey").value = cfg.gemini_api_key || "";
  document.getElementById("settingGeminiModel").value = cfg.gemini_model || "gemini-2.0-flash";
  document.getElementById("settingOllamaUrl").value = cfg.ollama_url || "http://localhost:11434";
  document.getElementById("settingOllamaModel").value = cfg.ollama_model || "llama3.2";
  document.getElementById("settingOpenAIKey").value = cfg.openai_api_key || "";
  document.getElementById("settingOpenAIBaseUrl").value = cfg.openai_base_url || "https://api.openai.com/v1";
  document.getElementById("settingOpenAIModel").value = cfg.openai_model || "gpt-4o-mini";

  updateAIProviderBoxes(cfg.ai_provider || "gemini");
  document.getElementById("modalAISettings").classList.remove("hidden");
}

function updateAIProviderBoxes(provider) {
  document.getElementById("aiConfigGemini").classList.toggle("hidden", provider !== "gemini");
  document.getElementById("aiConfigOllama").classList.toggle("hidden", provider !== "ollama");
  document.getElementById("aiConfigOpenAI").classList.toggle("hidden", provider !== "openai");
}

function openEditMoodModal(moodId) {
  const profile = getActiveProfile();
  if (!profile) return;

  const isEdit = Boolean(moodId && profile.moods?.[moodId]);
  const mood = isEdit
    ? profile.moods[moodId]
    : {
        id: "",
        name: "",
        icon: "🎵",
        color: "#10b981",
        description: "",
        phrases: [],
        keywords: [],
        queries: [],
        custom_playlist: "",
      };

  document.getElementById("modalMoodTitle").textContent = isEdit
    ? `⚙️ Modifica Atmosfera: ${mood.name}`
    : "➕ Crea Nuova Atmosfera";
  document.getElementById("editMoodId").value = mood.id || "";
  document.getElementById("editMoodIcon").value = mood.icon || "🎵";
  document.getElementById("editMoodName").value = mood.name || "";
  document.getElementById("editMoodColor").value = mood.color || "#10b981";
  document.getElementById("editMoodDesc").value = mood.description || "";
  document.getElementById("editMoodPhrases").value = (mood.phrases || []).join("\n");
  document.getElementById("editMoodKeywords").value = (mood.keywords || []).join(", ");
  document.getElementById("editMoodQueries").value = (mood.queries || []).join("\n");
  document.getElementById("editMoodPlaylist").value = mood.custom_playlist || "";

  document.getElementById("btnDeleteMood").classList.toggle("hidden", !isEdit);
  document.getElementById("modalEditMood").classList.remove("hidden");
}

async function saveMoodFromModal() {
  const profile = getActiveProfile();
  if (!profile) return;

  let moodId = document.getElementById("editMoodId").value.trim();
  const name = document.getElementById("editMoodName").value.trim();
  if (!name) return;

  if (!moodId) {
    moodId = name.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  }

  const existing = profile.moods?.[moodId] || {};
  const phrases = document
    .getElementById("editMoodPhrases")
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const keywords = document
    .getElementById("editMoodKeywords")
    .value.split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const queries = document
    .getElementById("editMoodQueries")
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  profile.moods[moodId] = {
    id: moodId,
    name,
    icon: document.getElementById("editMoodIcon").value.trim() || "🎵",
    color: document.getElementById("editMoodColor").value || "#10b981",
    description: document.getElementById("editMoodDesc").value.trim(),
    phrases,
    keywords,
    queries: queries.length ? queries : [`${name} rpg music instrumental`],
    custom_playlist: document.getElementById("editMoodPlaylist").value.trim(),
    pinned_tracks: existing.pinned_tracks || [],
  };

  const res = await fetch("/api/profile/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile }),
  });
  const data = await res.json();
  state.config = data.config;
  syncUIFromConfig();
  document.getElementById("modalEditMood").classList.add("hidden");
  showToast(`💾 Atmosfera "${name}" salvata!`);
}

// --- UTILITIES ---

function showToast(msg) {
  const container = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 3800);
}

function formatSeconds(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? "0" : ""}${r}`;
}

function hexToRgba(hex, alpha) {
  const clean = hex.replace("#", "");
  if (clean.length !== 6) return `rgba(16, 185, 129, ${alpha})`;
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
