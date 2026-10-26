"""
Test per audio_engine.py:
- Inizializzazione motore sounddevice a mixer unico
- Decodifica PyAV di file audio in PCM float32 stereo 48kHz
- Regolazione volumi con curva psicoacustica
- Calcolo ducking sample-accurate
- Polyphonic SFX mixing

Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

__author__ = "Paolo Basta"

import math
from pathlib import Path
import numpy as np

from audio_engine import AudioEngine, SAMPLE_RATE, CHANNELS, perceptual_gain
from sfx_manager import load_audio_file_to_pcm


def test_audio_engine_initialization():
    engine = AudioEngine()
    assert engine.active_deck_id in ("A", "B")
    assert engine.music_volume == 75
    assert engine.sfx_volume == 80
    assert engine.paused is False
    engine.shutdown()


def test_audio_engine_volume_and_gain():
    engine = AudioEngine()
    engine.set_music_volume(50)
    assert engine.music_volume == 50
    # Verifica che il guadagno target segua la curva percettiva
    assert math.isclose(engine._music_gain_target, perceptual_gain(50), rel_tol=1e-3)

    # Volume a zero deve dare guadagno zero
    engine.set_music_volume(0)
    assert engine._music_gain_target == 0.0

    engine.shutdown()


def test_pyav_pcm_decoding():
    # Verifica che un WAV reale venga decodificato a 48000Hz stereo float32
    wav_path = Path("sfx/spada.wav")
    assert wav_path.is_file()

    pcm = load_audio_file_to_pcm(wav_path, target_sample_rate=SAMPLE_RATE)
    assert pcm is not None
    assert pcm.dtype == np.float32
    assert pcm.ndim == 2
    assert pcm.shape[1] == CHANNELS
    # I valori devono essere compresi in [-1.0, 1.0]
    assert np.max(np.abs(pcm)) <= 1.0


def test_audio_engine_sfx_and_ducking():
    engine = AudioEngine()

    # Crea un frame sintetico float32
    fake_sfx = np.zeros((4800, 2), dtype=np.float32)
    fake_sfx[:, 0] = 0.5
    fake_sfx[:, 1] = 0.5

    # Playback SFX
    dur = engine.play_sfx(fake_sfx, trim=1.0)
    assert math.isclose(dur, 0.1, rel_tol=1e-3)
    assert len(engine._sfx_voices) >= 1

    # Ducking
    clock_before = engine._frame_clock
    engine.duck(duration_sec=1.5)
    assert engine._duck_until_frame > clock_before

    engine.shutdown()
