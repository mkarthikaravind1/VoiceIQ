"""
Prosody — how something was said, not what was said.

Extracts loudness and pitch from an utterance and turns them into an "arousal"
score relative to the caller's own baseline, so a naturally loud or
high-pitched voice is not mistaken for an angry one. The score is then blended
with the text sentiment: the same words count as more negative when they are
shouted.

This is a transparent heuristic, not a trained emotion model.
"""
import numpy as np

SAMPLE_RATE = 16000
FRAME = 640          # 40 ms
HOP = 320            # 20 ms
F0_MIN, F0_MAX = 75, 400   # human speech pitch range, Hz


def extract_prosody(audio: np.ndarray, transcript: str = "") -> dict:
    """audio: float32 mono at 16 kHz in [-1, 1] (speech only, silence removed)."""
    duration = len(audio) / SAMPLE_RATE
    if len(audio) < FRAME * 2:
        return {"energy_db": None, "pitch_hz": None, "pitch_range_st": None,
                "rate_wps": None, "duration_s": round(duration, 2)}

    n_frames = 1 + (len(audio) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = audio[idx] * np.hanning(FRAME)

    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    voiced_gate = rms > max(0.01, 0.3 * float(np.median(rms)))
    energy_db = float(20 * np.log10(np.mean(rms[voiced_gate]) + 1e-12)) if voiced_gate.any() else None

    # Pitch per frame by autocorrelation (computed with an FFT)
    lag_min, lag_max = SAMPLE_RATE // F0_MAX, SAMPLE_RATE // F0_MIN
    spectrum = np.fft.rfft(frames, n=2 * FRAME, axis=1)
    autocorr = np.fft.irfft(np.abs(spectrum) ** 2, axis=1)[:, :FRAME]
    autocorr /= autocorr[:, :1] + 1e-12
    window = autocorr[:, lag_min:lag_max]
    best = np.argmax(window, axis=1)
    strength = window[np.arange(n_frames), best]
    voiced = voiced_gate & (strength > 0.45)        # periodic enough to be a vowel
    f0 = SAMPLE_RATE / (best[voiced] + lag_min)

    pitch_hz = float(np.median(f0)) if len(f0) >= 5 else None
    pitch_range_st = None
    if len(f0) >= 5:
        lo, hi = np.percentile(f0, [10, 90])
        pitch_range_st = float(12 * np.log2(hi / lo))   # spread in semitones

    words = len(transcript.split())
    return {
        "energy_db": None if energy_db is None else round(energy_db, 1),
        "pitch_hz": None if pitch_hz is None else round(pitch_hz, 1),
        "pitch_range_st": None if pitch_range_st is None else round(pitch_range_st, 1),
        "rate_wps": round(words / duration, 2) if duration > 0.3 and words else None,
        "duration_s": round(duration, 2),
    }


def arousal_from_prosody(prosody: dict, ctx) -> float:
    """
    Arousal in [-1, 1] relative to this caller's baseline (0 on their first
    utterance). +6 dB louder or +3 semitones higher than usual each count as
    "clearly raised". Updates the baseline on ctx.
    """
    energy, pitch = prosody.get("energy_db"), prosody.get("pitch_hz")
    if energy is None:
        return 0.0

    if ctx.baseline_energy_db is None:
        ctx.baseline_energy_db = energy
        ctx.baseline_pitch_hz = pitch
        return 0.0

    d_energy = (energy - ctx.baseline_energy_db) / 6.0
    d_pitch = 0.0
    if pitch and ctx.baseline_pitch_hz:
        d_pitch = 12 * np.log2(pitch / ctx.baseline_pitch_hz) / 3.0
    arousal = float(np.clip(0.6 * d_energy + 0.4 * d_pitch, -1.0, 1.0))

    # Slow-moving baseline, so one outburst doesn't become the new normal
    ctx.baseline_energy_db = 0.8 * ctx.baseline_energy_db + 0.2 * energy
    if pitch:
        ctx.baseline_pitch_hz = pitch if not ctx.baseline_pitch_hz else 0.8 * ctx.baseline_pitch_hz + 0.2 * pitch
    return round(arousal, 2)


def fuse_sentiment(text_sentiment: float, arousal: float) -> float:
    """
    Blend what was said with how it was said.
      - negative words + raised voice  → more negative (up to 1.5x)
      - neutral words  + raised voice  → slightly negative
      - positive words                 → unchanged (excited is fine)
    A calm or quieter-than-usual voice never changes the text score.
    """
    if arousal <= 0.3:
        return round(text_sentiment, 2)
    if text_sentiment < 0:
        fused = text_sentiment * (1 + 0.5 * arousal)
    elif text_sentiment <= 0.2:
        fused = text_sentiment - 0.25 * arousal
    else:
        fused = text_sentiment
    return round(max(-1.0, min(1.0, fused)), 2)
