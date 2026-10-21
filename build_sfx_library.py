"""
Costruisce la libreria interna di 20 Effetti Sonori GdR (sfx/*.wav) ad alta chiarezza.
Ogni effetto è composto e masterizzato a 44.1kHz 16-bit PCM (durata 1.5s - 3.0s, peak 0.95, alto RMS)
combinando registrazioni studio Foley da Battle for Wesnoth e Flare RPG (GPL/CC),
con normalizzazione e compressione dinamica per risultare nitido e inconfondibile sopra la musica.
"""

import shutil
import subprocess
import wave
from pathlib import Path
from typing import List, Tuple
import httpx
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
SFX_DIR = BASE_DIR / "sfx"
RAW_CACHE_DIR = SFX_DIR / "_raw_cache"
SFX_DIR.mkdir(parents=True, exist_ok=True)
RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SR = 44100

WESNOTH = "https://raw.githubusercontent.com/wesnoth/wesnoth/master/data/core/sounds"
FLARE = "https://raw.githubusercontent.com/flareteam/flare-game/master/mods/fantasycore/soundfx"

SOURCE_URLS = {
    # Armi
    "sword1": f"{WESNOTH}/sword-1.ogg",
    "dagger": f"{WESNOTH}/dagger-swish.wav",
    "melee2": f"{FLARE}/melee_attack_2.ogg",
    "axe": f"{WESNOTH}/axe.ogg",
    "claws": f"{WESNOTH}/claws.ogg",
    "bite_sm": f"{WESNOTH}/bite-small.ogg",
    "bite": f"{WESNOTH}/bite.ogg",
    "shield": f"{FLARE}/powers/shield.ogg",
    "block": f"{FLARE}/powers/block.ogg",
    "mace": f"{WESNOTH}/mace.ogg",
    "maille": f"{FLARE}/inventory/inventory_maille.ogg",
    "metal": f"{FLARE}/inventory/inventory_metal.ogg",
    "bow": f"{WESNOTH}/bow.ogg",
    "shoot": f"{FLARE}/powers/shoot.ogg",
    "miss1": f"{WESNOTH}/miss-1.ogg",
    "crossbow": f"{WESNOTH}/crossbow.ogg",
    # Creature
    "wyvern_die": f"{FLARE}/enemies/wyvern_die.ogg",
    "drake_die": f"{WESNOTH}/drake-die.ogg",
    "flame_big": f"{WESNOTH}/flame-big.ogg",
    "minotaur": f"{FLARE}/enemies/minotaur_phys.ogg",
    "orc_die": f"{WESNOTH}/orc-die-1.ogg",
    "troll_hit": f"{WESNOTH}/troll-hit-1.ogg",
    "wolf_growl1": f"{WESNOTH}/wolf-growl-1.ogg",
    "wolf_growl2": f"{WESNOTH}/wolf-growl-2.ogg",
    "wolf_die1": f"{WESNOTH}/wolf-die-1.ogg",
    "wolf_die2": f"{WESNOTH}/wolf-die-2.ogg",
    "groan": f"{WESNOTH}/groan.wav",
    "zombie_ment": f"{FLARE}/enemies/zombie_ment.ogg",
    "zombie_die": f"{FLARE}/enemies/zombie_die.ogg",
    "female_die": f"{FLARE}/female_die.ogg",
    "human_die": f"{WESNOTH}/human-die-1.ogg",
    "wail_long": f"{WESNOTH}/wail-long.wav",
    # Magia
    "fireball": f"{FLARE}/powers/fireball.ogg",
    "explosion": f"{WESNOTH}/explosion.ogg",
    "fire": f"{WESNOTH}/fire.wav",
    "shock": f"{FLARE}/powers/shock.ogg",
    "lightning": f"{WESNOTH}/lightning.ogg",
    "heal": f"{WESNOTH}/heal.wav",
    "magic_holy": f"{WESNOTH}/magic-holy-1.ogg",
    "magic_faerie": f"{WESNOTH}/magic-faeriefire.ogg",
    # Ambiente
    "door_open": f"{FLARE}/door_open.ogg",
    "wood_open": f"{FLARE}/wood_open.ogg",
    "stone_open": f"{FLARE}/environment/stone_open.ogg",
    "club": f"{WESNOTH}/club.ogg",
    "quake": f"{FLARE}/powers/quake.ogg",
    "cave_in": f"{WESNOTH}/cave-in.ogg",
    "rumble": f"{WESNOTH}/rumble.ogg",
    "open_chest": f"{WESNOTH}/open-chest.wav",
    "gold": f"{WESNOTH}/gold.ogg",
    "inv_coins": f"{FLARE}/inventory/inventory_coins.ogg",
    "inv_gem": f"{FLARE}/inventory/inventory_gem.ogg",
    "inv_wood": f"{FLARE}/inventory/inventory_wood.ogg",
    "inv_obj": f"{FLARE}/inventory/inventory_object.ogg",
    "potion": f"{WESNOTH}/potion.ogg",
    "inv_potion": f"{FLARE}/inventory/inventory_potion.ogg",
    "dwarf_laugh": f"{WESNOTH}/dwarf-laugh.wav",
    "thunder_flare": f"{FLARE}/powers/thunder.ogg",
    "horn1": f"{WESNOTH}/horn-signals/horn-1.ogg",
    "heartbeat": f"{FLARE}/heartbeat.ogg",
}


def fetch_and_decode(key: str, client: httpx.Client) -> np.ndarray:
    wav_cache = RAW_CACHE_DIR / f"{key}.wav"
    if not wav_cache.exists():
        url = SOURCE_URLS[key]
        ext = url.split(".")[-1].split("?")[0]
        raw_path = RAW_CACHE_DIR / f"{key}_src.{ext}"
        print(f"  [Download] {key} <- {url.split('/')[-1]}")
        resp = client.get(url)
        resp.raise_for_status()
        raw_path.write_bytes(resp.content)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_path), "-ar", str(SR), "-ac", "1", str(wav_cache)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        raw_path.unlink(missing_ok=True)

    with wave.open(str(wav_cache), "rb") as w:
        frames = w.readframes(w.getnframes())
        arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    peak = float(np.max(np.abs(arr))) if len(arr) > 0 else 0.0
    if peak > 1e-4:
        arr = arr / peak * 0.9
    return arr


def pitch_shift(arr: np.ndarray, semitones: float) -> np.ndarray:
    if abs(semitones) < 0.01 or len(arr) == 0:
        return arr
    factor = 2.0 ** (semitones / 12.0)
    new_len = max(1, int(len(arr) / factor))
    indices = np.linspace(0, len(arr) - 1, new_len)
    return np.interp(indices, np.arange(len(arr)), arr).astype(np.float32)


def trim_silence(arr: np.ndarray, threshold: float = 0.015) -> np.ndarray:
    idx = np.where(np.abs(arr) > threshold)[0]
    if len(idx) == 0:
        return arr
    start = max(0, idx[0] - int(0.01 * SR))
    end = min(len(arr), idx[-1] + int(0.05 * SR))
    return arr[start:end]


def synth_church_bell_strike(fundamental_hz: float = 220.0, dur: float = 2.4) -> np.ndarray:
    """
    Risonanza modale autentica di campana di bronzo da cattedrale (parziali di Rayleigh:
    hum 0.5x, prime 1.0x, tierce 1.183x, quint 1.506x, nominal 2.0x, superquint 2.514x, oct 3.0x).
    """
    t = np.linspace(0.0, dur, int(dur * SR), endpoint=False, dtype=np.float32)
    partials = [
        (0.500, 0.45, 0.9),
        (1.000, 1.00, 1.4),
        (1.183, 0.85, 1.9),
        (1.506, 0.55, 2.6),
        (2.000, 0.90, 3.2),
        (2.514, 0.45, 4.5),
        (3.011, 0.35, 5.8),
        (4.166, 0.25, 8.0),
    ]
    sig = np.zeros_like(t)
    for ratio, amp, decay in partials:
        freq = fundamental_hz * ratio
        # Leggero battimento naturale (2 Hz) tipico delle campane fuse in bronzo
        tone = np.sin(2.0 * np.pi * freq * t) + 0.28 * np.sin(2.0 * np.pi * (freq + 1.7) * t)
        sig += amp * tone * np.exp(-decay * t)
    # Transiente metallico del batacchio all'impatto
    clapper = (
        np.sin(2.0 * np.pi * fundamental_hz * 5.4 * t) * np.exp(-38.0 * t) * 0.65
        + np.sin(2.0 * np.pi * fundamental_hz * 7.1 * t) * np.exp(-55.0 * t) * 0.45
    )
    attack = np.minimum(1.0, t / 0.004)
    out = (sig + clapper) * attack
    return (out / (np.max(np.abs(out)) + 1e-6) * 0.9).astype(np.float32)


def synth_glass_clink(base_hz: float = 1480.0, dur: float = 0.65) -> np.ndarray:
    """Risonanza cristallina di due calici/boccali di vetro che brindano."""
    t = np.linspace(0.0, dur, int(dur * SR), endpoint=False, dtype=np.float32)
    modes = [
        (1.000, 1.00, 6.5),
        (2.320, 0.55, 11.0),
        (3.860, 0.30, 17.0),
    ]
    sig = np.zeros_like(t)
    for ratio, amp, decay in modes:
        f = base_hz * ratio
        sig += amp * np.sin(2.0 * np.pi * f * t) * np.exp(-decay * t)
    click = np.sin(2.0 * np.pi * 4200.0 * t) * np.exp(-90.0 * t) * 0.5
    out = (sig + click) * np.minimum(1.0, t / 0.0015)
    return (out / (np.max(np.abs(out)) + 1e-6) * 0.9).astype(np.float32)


def _fft_warm_filter(sig: np.ndarray, cutoff_hz: float = 5200.0, hp_hz: float = 42.0) -> np.ndarray:
    """
    Filtro spettrale ad alta precisione (FFT) che elimina l'asprezza digitale sulle alte frequenze
    (> 5.2 kHz), pulisce la sub-risonanza (< 42 Hz) e aggiunge calore sul medio-basso (160-380 Hz)
    così l'effetto sonoro si fonde in modo organico con la musica orchestrale di sottofondo.
    """
    n = len(sig)
    if n == 0:
        return sig
    spec = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / SR)

    # Roll-off morbido sulle alte frequenze per togliere l'effetto "finto/staccato"
    lp = 1.0 / np.sqrt(1.0 + (freqs / max(500.0, cutoff_hz)) ** 3.2)
    # Pulizia sub-bassi per non scontrarsi con i bassi della musica
    hp = 1.0 / np.sqrt(1.0 + (hp_hz / np.maximum(1.0, freqs)) ** 4.0)
    # Leggero calore cinematografico sui medio-bassi (220 Hz) e ammorbidimento a 3.2 kHz (zona di fastidio uditivo)
    warm_bell = 1.0 + 0.18 * np.exp(-0.5 * ((freqs - 220.0) / 110.0) ** 2)
    harsh_dip = 1.0 - 0.22 * np.exp(-0.5 * ((freqs - 3200.0) / 950.0) ** 2)

    filtered = np.fft.irfft(spec * lp * hp * warm_bell * harsh_dip, n=n)
    return filtered.astype(np.float32)


def _apply_stereo_room_space(mono_sig: np.ndarray, room_wet: float = 0.26) -> np.ndarray:
    """
    Posiziona l'effetto sonoro nello stesso spazio acustico tridimensionale (Stereo Room/Hall)
    della colonna sonora musicale tramite riflessioni primarie decorrelate L/R e coda di riverbero calda.
    Restituisce un array stereo (N_tot, 2) float32.
    """
    ir_len = int(0.42 * SR)
    rng = np.random.default_rng(42)
    t_ir = np.linspace(0.0, 0.42, ir_len, endpoint=False, dtype=np.float32)

    ir_l = np.zeros(ir_len, dtype=np.float32)
    ir_r = np.zeros(ir_len, dtype=np.float32)
    ir_l[0] = 1.0
    ir_r[0] = 1.0

    # Riflessioni primarie naturali (Haas + pareti stanza/sala in legno e pietra)
    early_l = [(0.011, 0.26), (0.019, -0.18), (0.031, 0.15), (0.047, -0.11), (0.067, 0.08)]
    early_r = [(0.014, 0.25), (0.023, -0.17), (0.037, 0.14), (0.053, -0.11), (0.073, 0.08)]
    for delay_s, gain in early_l:
        idx = int(delay_s * SR)
        if idx < ir_len:
            ir_l[idx] += gain * room_wet * 1.4
    for delay_s, gain in early_r:
        idx = int(delay_s * SR)
        if idx < ir_len:
            ir_r[idx] += gain * room_wet * 1.4

    # Coda di riverbero diffusa e calda (smorzata sulle alte frequenze come in una vera stanza)
    tail_env = np.exp(-t_ir / 0.105) * np.minimum(1.0, t_ir / 0.025)
    noise_l = _fft_warm_filter(rng.standard_normal(ir_len).astype(np.float32), cutoff_hz=2300.0, hp_hz=90.0)
    noise_r = _fft_warm_filter(rng.standard_normal(ir_len).astype(np.float32), cutoff_hz=2300.0, hp_hz=90.0)

    ir_l += noise_l * tail_env * (room_wet * 0.065)
    ir_r += noise_r * tail_env * (room_wet * 0.065)

    n_out = len(mono_sig) + ir_len - 1
    n_fft = 1 << (n_out - 1).bit_length()
    sig_spec = np.fft.rfft(mono_sig, n=n_fft)
    left = np.fft.irfft(sig_spec * np.fft.rfft(ir_l, n=n_fft), n=n_fft)[:n_out]
    right = np.fft.irfft(sig_spec * np.fft.rfft(ir_r, n=n_fft), n=n_fft)[:n_out]

    return np.stack([left.astype(np.float32), right.astype(np.float32)], axis=1)


def mix_layers(layers: List[Tuple[float, np.ndarray, float]], max_dur: float = 3.2) -> np.ndarray:
    total_samples = 0
    for start_s, seg, _gain in layers:
        end_idx = int(start_s * SR) + len(seg)
        if end_idx > total_samples:
            total_samples = end_idx

    total_samples = min(total_samples, int(max_dur * SR))
    out = np.zeros(total_samples, dtype=np.float32)

    for start_s, seg, gain in layers:
        st = int(start_s * SR)
        if st >= total_samples:
            continue
        ed = min(total_samples, st + len(seg))
        layer_seg = seg[: ed - st].copy()
        # Micro-fade di 6ms su ogni singolo layer per eliminare click interni
        micro_f = min(int(0.006 * SR), len(layer_seg) // 4)
        if micro_f > 1:
            layer_seg[:micro_f] *= np.linspace(0.0, 1.0, micro_f, dtype=np.float32)
            layer_seg[-micro_f:] *= np.linspace(1.0, 0.0, micro_f, dtype=np.float32)
        out[st:ed] += layer_seg * float(gain)

    # 1. Filtraggio timbrico caldo (rimuove l'effetto metallico/staccato rispetto alla musica)
    out = _fft_warm_filter(out, cutoff_hz=5100.0, hp_hz=42.0)

    # 2. Spazio acustico stereo naturale (riflessioni + coda morbida che si dissolve nella musica)
    stereo = _apply_stereo_room_space(out, room_wet=0.26)

    # 3. Inviluppo di attacco morbido (14ms cosine fade-in) e rilascio naturale (340ms cosine fade-out)
    n_frames = len(stereo)
    attack_len = min(int(0.014 * SR), n_frames // 6)
    if attack_len > 1:
        att_curve = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, attack_len, dtype=np.float32)))
        stereo[:attack_len, 0] *= att_curve
        stereo[:attack_len, 1] *= att_curve

    release_len = min(int(0.34 * SR), n_frames // 3)
    if release_len > 1:
        rel_curve = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, release_len, dtype=np.float32)))
        stereo[-release_len:, 0] *= rel_curve
        stereo[-release_len:, 1] *= rel_curve

    # 4. Mastering dinamico naturale (niente saturazione aggressiva: mantiene la dinamica reale)
    peak = float(np.max(np.abs(stereo))) if n_frames > 0 else 0.0
    if peak > 1e-4:
        stereo = stereo / peak
        # Lievissima compressione soft-knee per amalgama, con picco naturale a 0.74
        stereo = np.tanh(stereo * 1.06)
        stereo = stereo / float(np.max(np.abs(stereo))) * 0.74

    return stereo


def save_wav(name: str, arr: np.ndarray) -> None:
    out_path = SFX_DIR / name
    if arr.ndim == 1:
        arr = np.stack([arr, arr], axis=1)
    pcm = np.clip(arr * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    dur = len(arr) / SR
    rms = float(np.sqrt(np.mean(arr ** 2)))
    peak = float(np.max(np.abs(arr)))
    print(f"  [OK] {name:22s} | stereo | dur={dur:4.2f}s | peak={peak:.2f} | rms={rms:.3f}")


def build_all() -> None:
    s = {}
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for k in SOURCE_URLS:
            s[k] = trim_silence(fetch_and_decode(k, client))

    print("\nMasterizzazione dei 20 effetti sonori GdR ad alta chiarezza...")

    # 1. SPADA: Sfoderamento metallico + primo fendente + scontro di lame e secondo colpo (1.65s)
    save_wav("spada.wav", mix_layers([
        (0.00, pitch_shift(s["dagger"], 2.0), 0.75),
        (0.18, s["sword1"], 1.00),
        (0.55, s["melee2"], 0.85),
        (0.72, pitch_shift(s["sword1"], 2.5), 0.95),
        (0.75, pitch_shift(s["metal"], 4.0), 0.55),
    ], max_dur=1.8))

    # 2. ARTIGLI: Sibilo feroce + doppio squarcio d'artigli e lacerazione (1.45s)
    save_wav("artigli.wav", mix_layers([
        (0.00, s["bite_sm"], 0.75),
        (0.14, s["claws"], 1.00),
        (0.48, pitch_shift(s["claws"], -2.0), 1.00),
        (0.62, s["bite"], 0.85),
    ], max_dur=1.7))

    # 3. SCUDO: Fendente in arrivo + impatto pesante sullo scudo + risonanza metallo/corazza (1.55s)
    save_wav("scudo.wav", mix_layers([
        (0.00, s["miss1"], 0.65),
        (0.12, s["shield"], 1.00),
        (0.14, s["mace"], 0.90),
        (0.16, s["block"], 1.00),
        (0.45, s["metal"], 0.85),
        (0.58, s["maille"], 0.80),
    ], max_dur=1.8))

    # 4. FRECCIA: Tensione e rilascio corda d'arco + sibilo nell'aria + impatto nel bersaglio (1.50s)
    save_wav("freccia.wav", mix_layers([
        (0.00, s["bow"], 1.00),
        (0.22, pitch_shift(s["shoot"], 2.0), 0.85),
        (0.55, s["crossbow"], 1.00),
        (0.62, pitch_shift(s["axe"], 3.0), 0.75),
    ], max_dur=1.7))

    # 5. RUGGITO DRAGO: Ruggito profondo sub-bass + secondo ruggito cavernoso + vampata di fuoco (2.85s)
    save_wav("ruggito_drago.wav", mix_layers([
        (0.00, pitch_shift(s["wyvern_die"], -3.0), 1.00),
        (0.10, pitch_shift(s["drake_die"], -4.5), 0.95),
        (0.85, pitch_shift(s["drake_die"], -7.0), 0.90),
        (1.30, s["flame_big"], 0.85),
    ], max_dur=3.0))

    # 6. MOSTRO RINGHIO: Ringhio gutturale d'orco/minotauro + ruggito aggressivo (1.95s)
    save_wav("mostro_ringhio.wav", mix_layers([
        (0.00, s["minotaur"], 1.00),
        (0.35, pitch_shift(s["troll_hit"], -2.0), 0.95),
        (0.75, pitch_shift(s["orc_die"], -1.5), 0.95),
    ], max_dur=2.2))

    # 7. LUPO: Ringhio iniziale + doppio ululato prolungato del branco nella notte (2.55s)
    save_wav("lupo.wav", mix_layers([
        (0.00, s["wolf_growl1"], 0.85),
        (0.35, pitch_shift(s["wolf_die2"], -3.5), 1.00),
        (0.95, pitch_shift(s["wolf_die1"], -5.0), 0.95),
        (1.35, pitch_shift(s["wolf_growl2"], -2.0), 0.80),
    ], max_dur=2.7))

    # 8. ZOMBIE: Gemito spettrale + lamento gutturale non-morto ad alta presenza (2.35s)
    save_wav("zombie.wav", mix_layers([
        (0.00, s["groan"], 1.00),
        (0.45, s["zombie_ment"], 1.00),
        (1.05, pitch_shift(s["zombie_die"], -1.5), 0.95),
    ], max_dur=2.6))

    # 9. URLO: Grido di terrore nitido + eco spettrale (2.25s)
    save_wav("urlo.wav", mix_layers([
        (0.00, s["female_die"], 1.00),
        (0.25, s["human_die"], 0.90),
        (0.55, s["wail_long"][: int(1.6 * SR)], 0.65),
    ], max_dur=2.4))

    # 10. PALLA DI FUOCO: Innesco fiammata + esplosione + fuoco ardente (2.35s)
    save_wav("palla_di_fuoco.wav", mix_layers([
        (0.00, s["fireball"], 0.95),
        (0.28, s["explosion"], 1.00),
        (0.40, s["flame_big"], 0.95),
        (0.95, s["fire"][: int(1.3 * SR)], 0.75),
    ], max_dur=2.5))

    # 11. FULMINE: Scarica elettrica ad alto voltaggio + schianto di fulmine (2.45s)
    save_wav("fulmine.wav", mix_layers([
        (0.00, s["shock"], 0.95),
        (0.18, s["lightning"][: int(2.2 * SR)], 1.00),
        (0.45, pitch_shift(s["shock"], 3.0), 0.80),
    ], max_dur=2.6))

    # 12. INCANTESIMO: Arpeggio cristallino di guarigione + coro magico (2.20s)
    save_wav("incantesimo.wav", mix_layers([
        (0.00, s["heal"], 1.00),
        (0.15, s["magic_holy"], 0.95),
        (0.55, s["magic_faerie"], 0.85),
    ], max_dur=2.4))

    # 13. PORTA SCRICCHIOLA: Chiavistello + lungo cigolio sinistro di cardini e legno + battuta pesante (2.35s)
    save_wav("porta_scricchiola.wav", mix_layers([
        (0.00, s["door_open"], 0.95),
        (0.22, pitch_shift(s["door_open"], -5.0), 1.00),
        (0.68, pitch_shift(s["wood_open"], -3.5), 1.00),
        (1.25, s["stone_open"][: int(1.0 * SR)], 0.80),
    ], max_dur=2.4))

    # 14. CROLLO: Impatto di sfondamento + frana di rocce e macerie (2.65s)
    save_wav("crollo.wav", mix_layers([
        (0.00, s["club"], 1.00),
        (0.12, s["quake"], 1.00),
        (0.25, s["cave_in"][: int(2.3 * SR)], 1.00),
        (0.50, s["rumble"][: int(2.0 * SR)], 0.85),
    ], max_dur=2.8))

    # 15. MONETE: Apertura forziere + doppia cascata nitida di monete d'oro e gemme (2.15s)
    save_wav("monete.wav", mix_layers([
        (0.00, s["open_chest"], 0.70),
        (0.20, s["inv_coins"], 1.00),
        (0.35, s["gold"], 1.00),
        (0.75, s["inv_gem"], 0.90),
        (0.95, pitch_shift(s["gold"], 1.5), 0.95),
        (1.30, pitch_shift(s["inv_coins"], -1.0), 0.85),
    ], max_dur=2.3))

    # 16. DADI: Shaker dei dadi in mano + rimbalzi fisici progressivi del D20 sul tavolo di legno (1.60s)
    wood_hit = s["inv_wood"][: int(0.14 * SR)]
    obj_hit = s["inv_obj"][: int(0.12 * SR)]
    gem_hit = s["inv_gem"][: int(0.10 * SR)]
    dice_layers = [
        (0.00, pitch_shift(obj_hit, 5.0), 0.60),
        (0.09, pitch_shift(gem_hit, 3.0), 0.65),
        (0.18, pitch_shift(obj_hit, 4.0), 0.65),
        (0.32, pitch_shift(wood_hit, 1.0), 1.00),
        (0.34, pitch_shift(obj_hit, 3.0), 0.95),
        (0.50, pitch_shift(wood_hit, 2.5), 0.88),
        (0.53, pitch_shift(obj_hit, 5.0), 0.82),
        (0.66, pitch_shift(wood_hit, 3.5), 0.75),
        (0.79, pitch_shift(obj_hit, 4.5), 0.68),
        (0.90, pitch_shift(wood_hit, 5.0), 0.58),
        (0.99, pitch_shift(obj_hit, 6.0), 0.50),
        (1.07, pitch_shift(wood_hit, 6.5), 0.42),
        (1.13, pitch_shift(obj_hit, 7.5), 0.35),
        (1.18, pitch_shift(obj_hit, 8.5), 0.28),
    ]
    save_wav("dadi.wav", mix_layers(dice_layers, max_dur=1.6))

    # 17. BRINDISI: Doppio tintinnio di calici/boccali + versamento birra + risata allegra di locanda (2.35s)
    clink1 = synth_glass_clink(1420.0, 0.60)
    clink2 = synth_glass_clink(1680.0, 0.55)
    save_wav("brindisi.wav", mix_layers([
        (0.00, clink1, 0.90),
        (0.03, s["inv_gem"][: int(0.25 * SR)], 0.70),
        (0.24, clink2, 0.85),
        (0.45, s["inv_potion"], 0.95),
        (0.65, s["potion"][: int(1.3 * SR)], 0.90),
        (1.05, s["dwarf_laugh"], 0.75),
    ], max_dur=2.5))

    # 18. TUONO: Schianto elettrico iniziale + potente rombo di tuono profondo (2.85s)
    save_wav("tuono.wav", mix_layers([
        (0.00, s["lightning"][: int(0.6 * SR)], 0.90),
        (0.08, s["thunder_flare"], 1.00),
        (0.25, pitch_shift(s["thunder_flare"], -4.0), 0.95),
        (0.60, s["rumble"][: int(2.1 * SR)], 0.85),
    ], max_dur=2.9))

    # 19. CAMPANA: Doppio rintocco solenne di campana di bronzo da chiesa + risonanza (2.95s)
    bell1 = synth_church_bell_strike(220.0, 2.4)
    bell2 = synth_church_bell_strike(196.0, 2.2)
    save_wav("campana.wav", mix_layers([
        (0.00, bell1, 1.00),
        (0.01, pitch_shift(s["metal"], -4.0)[: int(0.25 * SR)], 0.55),
        (1.25, bell2, 0.95),
        (1.26, pitch_shift(s["metal"], -6.0)[: int(0.25 * SR)], 0.50),
    ], max_dur=3.0))

    # 20. BATTITO: Sequenza ritmica nitida di 3 battiti cardiaci profondi (LUB-DUB x3, 2.50s)
    hb = s["heartbeat"]
    save_wav("battito.wav", mix_layers([
        (0.00, hb, 1.00),
        (0.82, hb, 1.00),
        (1.64, hb, 1.00),
    ], max_dur=2.7))

    shutil.rmtree(RAW_CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    build_all()
    print("\nTutti i 20 effetti sonori sono stati rigenerati e masterizzati con successo!")
