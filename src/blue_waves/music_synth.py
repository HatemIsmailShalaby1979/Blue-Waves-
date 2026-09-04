"""Procedural music synthesis engine for Blue Waves offline fallback.

.. deprecated:: 0.3.0
    This is the **last-resort fallback only**. For competitive quality use
    Suno API (suno_api provider) or aimlapi (aimlapi_music provider).
    This synthesizer produces functional but non-competitive output —
    it is kept for offline/zero-cost mode and contract testing only.

Produces full, structured musical arrangements (intro / verse / chorus / bridge /
outro) that react to the prompt, genre, mood and lyrics. Built on numpy/scipy:
oscillator synthesis with ADSR envelopes, vibrato, per-voice filters, a drum
kit, stereo mixing, delay and reverb.

This is a *real* composition engine (multiple layered voices + song structure),
not a single beeping oscillator.
"""

from __future__ import annotations

import hashlib
import math
import wave
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Delivery spec: streaming/YouTube targets expect stereo 48 kHz, and the
# media quality gate enforces it. The whole synth is sample-rate
# parameterized, so this constant propagates to every voice and effect.
SR = 48000


# ── Note helpers ────────────────────────────────────────────────────────────

NOTE_FREQS: dict[str, float] = {}

_note_pc = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
            "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def _freq(note: str) -> float:
    """Frequency in Hz for a note like 'A4' or 'C#3'."""
    if note in NOTE_FREQS:
        return NOTE_FREQS[note]
    name = note[:-1]
    octave = int(note[-1])
    pc = _note_pc[name]
    midi = (octave + 1) * 12 + pc
    f = 440.0 * (2 ** ((midi - 69) / 12.0))
    NOTE_FREQS[note] = f
    return f


def _midi_freq(midi: int) -> float:
    return 440.0 * (2 ** ((midi - 69) / 12.0))


def _midi(note: str) -> int:
    name = note[:-1]
    octave = int(note[-1])
    return (octave + 1) * 12 + _note_pc[name]


# ── Deterministic RNG seeded from prompt ────────────────────────────────────

class SeededRng:
    def __init__(self, seed: str) -> None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self._state = int.from_bytes(digest[:8], "big") or 1

    def _next(self) -> int:
        self._state = (self._state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return self._state

    def rand(self) -> float:
        return (self._next() >> 11) / (1 << 53)

    def randrange(self, lo: int, hi: int) -> int:
        if hi <= lo:
            return lo
        return lo + int(self.rand() * (hi - lo))

    def choice(self, seq: list[Any]) -> Any:
        return seq[self.randrange(0, len(seq))]


# ── Tempo / timing ──────────────────────────────────────────────────────────

def beat_seconds(tempo: int) -> float:
    return 60.0 / tempo


def bars_to_seconds(bars: float, tempo: int) -> float:
    return bars * 4 * beat_seconds(tempo)


# ── Sound synthesis primitives ──────────────────────────────────────────────

def adsr_envelope(n: int, attack: float, decay: float, sustain: float,
                  release: float, sr: int = SR) -> np.ndarray:
    """Exponential-ish ADSR envelope over n samples. Values in seconds."""
    n_a = int(attack * sr)
    n_d = int(decay * sr)
    n_r = int(release * sr)
    n_s = max(0, n - n_a - n_d - n_r)
    env = np.zeros(n)
    t = np.arange(n_a) / max(1, n_a)
    env[:n_a] = t * t  # quick attack curve
    d = np.arange(n_d) / max(1, n_d)
    env[n_a:n_a + n_d] = 1 - (1 - sustain) * (d * d)
    if n_r > 0:
        r = np.arange(n_r) / max(1, n_r)
        start = n_a + n_d + n_s
        end = start + n_r
        if end > n:
            end = n
        env[start:end] = sustain * (1 - r[:end - start])
    else:
        env[n_a + n_d:] = sustain
    return np.clip(env, 0, 1)


# One cycle of a waveform, band-limited so that no harmonic sits at or above
# Nyquist. Naive `sign(sin())` / modulo ramps are *not* band-limited: every
# harmonic past Nyquist folds back down as an inharmonic partial, which is
# heard as harsh treble noise. Measured on this engine, a naive square was
# ~63% inharmonic energy and ~57% of its output above 6 kHz — that aliasing
# was the single biggest reason generated music sounded like noise.
_TABLE_CACHE: dict[tuple[str, int, int], np.ndarray] = {}
_TABLE_SIZE = 4096
_MAX_HARMONICS = 96


def _bandlimited_table(wave: str, freq: float, sr: int = SR) -> np.ndarray:
    """Single cycle of `wave` containing only harmonics below Nyquist.

    Cached per (wave, rounded Hz, sample rate). Pitch always comes from the
    phase accumulator at render time, so rounding the cache key only affects
    how many harmonics the table holds — never the tuning.
    """
    key = (wave, int(round(freq)), sr)
    cached = _TABLE_CACHE.get(key)
    if cached is not None:
        return cached

    nyq = sr * 0.5
    f = max(freq, 1.0)
    max_h = min(_MAX_HARMONICS, max(1, int(nyq / f)))
    ph = np.arange(_TABLE_SIZE) / _TABLE_SIZE * 2 * np.pi
    tbl = np.zeros(_TABLE_SIZE)

    if wave == "square":
        # sum over odd k of 4/(pi*k) * sin(k*ph)
        for k in range(1, max_h + 1, 2):
            tbl += (4.0 / (np.pi * k)) * _harm_taper(nyq, k * f) * np.sin(k * ph)
    elif wave == "saw":
        # -(2/pi) * sum 1/k * sin(k*ph)
        for k in range(1, max_h + 1):
            tbl += -(2.0 / (np.pi * k)) * _harm_taper(nyq, k * f) * np.sin(k * ph)
    elif wave == "triangle":
        # (8/pi^2) * sum over odd k of (-1)^((k-1)/2) / k^2 * sin(k*ph)
        for k in range(1, max_h + 1, 2):
            sign = -1.0 if ((k - 1) // 2) % 2 else 1.0
            tbl += (8.0 / (np.pi ** 2 * k * k)) * sign * _harm_taper(nyq, k * f) * np.sin(k * ph)
    else:
        tbl = np.sin(ph)

    peak = float(np.abs(tbl).max())
    if peak > 0:
        tbl = tbl / peak
    if len(_TABLE_CACHE) > 512:
        _TABLE_CACHE.clear()
    _TABLE_CACHE[key] = tbl
    return tbl


def _harm_taper(nyq: float, harm_freq: float) -> float:
    """Fade out the top ~20% of the band instead of truncating, which would
    otherwise ring (Gibbs) right at the bandlimit."""
    edge = nyq * 0.98
    if harm_freq <= nyq * 0.78:
        return 1.0
    return float(np.clip((edge - harm_freq) / (edge - nyq * 0.78), 0.0, 1.0))


def _table_lookup(tbl: np.ndarray, cycles: np.ndarray) -> np.ndarray:
    """Read `tbl` at fractional cycle positions with linear interpolation."""
    size = len(tbl)
    x = cycles * size
    base = np.floor(x)
    i0 = base.astype(np.int64) % size
    i1 = (i0 + 1) % size
    frac = (x - base).astype(tbl.dtype)
    return tbl[i0] + (tbl[i1] - tbl[i0]) * frac


def osc(freq: float, n: int, sr: int = SR, phase: float = 0.0,
        wave: str = "sine", fm_ratio: float = 0.0, fm_index: float = 0.0) -> np.ndarray:
    t = np.arange(n) / sr
    # Track phase in *cycles* so the same accumulator drives both the sine
    # path and the band-limited wavetable path.
    cycles = freq * (phase + t)
    if fm_ratio and fm_index:
        cycles = cycles + fm_index * np.sin(2 * np.pi * freq * fm_ratio * t)
    if wave in ("square", "saw", "triangle"):
        return _table_lookup(_bandlimited_table(wave, freq, sr), cycles)
    return np.sin(2 * np.pi * cycles)


def note_buffer(freq: float, dur: float, wave: str = "sine",
                amp: float = 0.3, attack: float = 0.01, decay: float = 0.1,
                sustain: float = 0.8, release: float = 0.15,
                vibrato: float = 0.0, vibrato_rate: float = 5.0,
                cutoff: float | None = None, fm_ratio: float = 0.0,
                fm_index: float = 0.0, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(1)
    body = osc(freq, n, sr, wave=wave, fm_ratio=fm_ratio, fm_index=fm_index)
    if vibrato and vibrato_rate:
        tb = (np.arange(n) / sr)
        # Modulate the phase accumulator rather than substituting a plain sine,
        # otherwise every vibrato voice silently loses its timbre.
        cycles = freq * tb + vibrato * np.sin(2 * np.pi * vibrato_rate * tb)
        if wave in ("square", "saw", "triangle"):
            body = _table_lookup(_bandlimited_table(wave, freq, sr), cycles)
        else:
            body = np.sin(2 * np.pi * cycles)
    env = adsr_envelope(n, attack, decay, sustain, release, sr)
    out = body * env * amp
    if cutoff:
        b, a = _butter(cutoff, sr)
        if b is not None:
            out = _filter(b, a, out)
    return out


def _butter(cutoff: float, sr: int, order: int = 2):
    from scipy.signal import butter
    nyq = sr / 2.0
    if cutoff <= 0 or cutoff >= nyq:
        return None, None
    return butter(order, cutoff / nyq)


def _filter(b, a, x: np.ndarray) -> np.ndarray:
    from scipy.signal import lfilter
    return lfilter(b, a, x)


def _lowpass(x: np.ndarray, cutoff: float, sr: int = SR, order: int = 2) -> np.ndarray:
    from scipy.signal import butter, lfilter
    nyq = sr / 2.0
    if cutoff <= 0 or cutoff >= nyq:
        return x
    b, a = butter(order, cutoff / nyq, btype="low")
    return lfilter(b, a, x)


def _highpass(x: np.ndarray, cutoff: float, sr: int = SR, order: int = 2) -> np.ndarray:
    from scipy.signal import butter, lfilter
    nyq = sr / 2.0
    if cutoff <= 0 or cutoff >= nyq:
        return x
    b, a = butter(order, cutoff / nyq, btype="high")
    return lfilter(b, a, x)


def _bandpass(x: np.ndarray, lo: float, hi: float, sr: int = SR,
              order: int = 2) -> np.ndarray:
    """Band-limit a signal to [lo, hi]. Used to keep percussion noise from
    spraying broadband hiss across the whole mix."""
    from scipy.signal import butter, lfilter
    nyq = sr / 2.0
    lo = max(20.0, min(lo, nyq * 0.90))
    hi = max(lo * 1.2, min(hi, nyq * 0.95))
    b, a = butter(order, [lo / nyq, hi / nyq], btype="band")
    return lfilter(b, a, x)


# ── Genre / mood configuration ─────────────────────────────────────────────

@dataclass
class Style:
    tempo: int
    scale_pcs: list[int]          # scale degrees relative to root (0=root)
    chords: list[list[int]]       # chord voicings as scale-degree indices (0 = chord root)
    progression: list[int]        # indexes (scale-degree of root) into the scale
    bass_pattern: list[int]       # scale-degree offsets for bass (relative to chord root)
    melody_range: tuple[int, int]
    wave_lead: str
    wave_pad: str
    wave_bass: str
    mood_labels: list[str]        # keywords that boost energy / key
    drums: bool = True            # percussive kit is inappropriate for some styles


# Chord voicings are given as scale-degree indices relative to the root.
# For a major scale [0,2,4,5,7,9,11]: a major triad is degrees [0,2,4].
STYLES: dict[str, Style] = {
    # pop: major pentatonic scale [0,2,4,7,9]; chords I, vi, IV, V
    "pop": Style(118, [0, 2, 4, 7, 9],
                 [[0, 1, 2], [0, 2, 4], [0, 1, 2], [0, 2, 4]],
                 [0, 1, 2, 3],       # roots by scale degree (I, ii, IV, V roughly)
                 [0, 0, 3, 0, 0, 0, 2, 2],
                 (5, 7), "saw", "triangle", "saw",
                 ["energy", "high", "motivation", "rise", "up", "power", "change", "techno"]),
    # rock: natural minor-ish scale; power-chord rooted triads
    "rock": Style(128, [0, 2, 3, 5, 7, 8, 10],
                  [[0, 1, 2], [0, 1, 2], [0, 1, 2], [0, 1, 2]],
                  [0, 3, 1, 0],
                  [0, 0, 3, 3, 0, 0, 2, 2],
                  (5, 7), "square", "saw", "square",
                  ["energy", "power", "strong", "drive", "rock"]),
    "electronic": Style(124, [0, 2, 4, 7, 9],
                        [[0, 1, 2], [0, 2, 4], [1, 2, 3], [0, 1, 2]],
                        [0, 1, 2, 3],
                        [0, 0, 2, 2, 0, 0, 2, 2],
                        (5, 7), "saw", "sine", "saw",
                        ["techno", "electronic", "energy", "neon", "future", "pop"]),
    "jazz": Style(96, [0, 2, 3, 5, 7, 8, 10],
                  [[0, 1, 2, 3], [1, 2, 3, 4], [0, 1, 2, 4], [2, 3, 4, 5]],
                  [0, 1, 0, 2],
                  [0, 3, 0, 3, 0, 3, 4, 3],
                  (4, 6), "sine", "sine", "triangle",
                  ["smooth", "cool", "lounge", "jazz"]),
    # No drum kit: a beat under an orchestral voicing sounds like a demo loop.
    "classical": Style(76, [0, 2, 4, 5, 7, 9, 11],
                       [[0, 1, 2], [0, 1, 2], [3, 4, 5], [2, 3, 4]],
                       [0, 1, 3, 0],
                       [0, 0, 3, 0, 0, 0, 2, 2],
                       (4, 6), "sine", "sine", "sine",
                       ["calm", "elegant", "graceful", "classical"], drums=False),
    "lofi": Style(74, [0, 2, 3, 5, 7, 9],
                  [[0, 1, 2], [1, 2, 3], [2, 3, 4], [0, 1, 2]],
                  [0, 1, 2, 0],
                  [0, 0, -1, 0, 0, 0, -2, 0],
                  (4, 6), "sine", "triangle", "sine",
                  ["chill", "calm", "study", "relax", "lofi"]),
    # No drum kit: ambient pads with a kick drum was the single biggest reason
    # "calm" prompts came back sounding like noise.
    "ambient": Style(60, [0, 3, 5, 7, 10],
                     [[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]],
                     [0, 1, 2, 3],
                     [0, 0, 0, 0, 0, 0, 0, 0],
                     (4, 6), "sine", "sine", "sine",
                     ["calm", "peace", "mood", "ambient"], drums=False),
    "cinematic": Style(72, [0, 2, 3, 5, 7, 8, 10],
                       [[0, 1, 2], [1, 2, 3], [0, 2, 4], [3, 4, 5]],
                       [0, 1, 2, 3],
                       [0, 3, 0, 3, 0, 3, 4, 3],
                       (4, 6), "saw", "sine", "saw",
                       ["epic", "drama", "tension", "climax", "cinematic"]),
}


def _mood_multiplier(mood: str, style: Style) -> float:
    m = mood.lower()
    if any(w in m for w in style.mood_labels):
        return 1.3
    return 1.0


# ── Arrangement builder ─────────────────────────────────────────────────────

@dataclass
class Voice:
    start: float
    freq: float
    dur: float
    amp: float
    wave: str = "sine"
    attack: float = 0.01
    decay: float = 0.1
    sustain: float = 0.8
    release: float = 0.15
    vibrato: float = 0.0
    cutoff: float | None = None
    fm_index: float = 0.0
    fm_ratio: float = 0.0
    pan: float = 0.0  # -1..1
    ch: str = "melody"


class Arrangement:
    def __init__(self) -> None:
        self.voices: list[Voice] = []

    def add(self, **kw: Any) -> None:
        self.voices.append(Voice(**kw))


def _render_arrangement(arr: Arrangement, total_seconds: float, sr: int = SR) -> np.ndarray:
    n = int(total_seconds * sr) + sr  # extra tail for reverb/delay
    left = np.zeros(n)
    right = np.zeros(n)

    for v in arr.voices:
        start_s = max(0, v.start)
        if v.ch in ("kick", "snare", "hat"):
            seg = _render_percussion(v, sr)
        else:
            seg = note_buffer(
                v.freq, v.dur, wave=v.wave, amp=v.amp,
                attack=v.attack, decay=v.decay, sustain=v.sustain, release=v.release,
                vibrato=v.vibrato, cutoff=v.cutoff, fm_index=v.fm_index, fm_ratio=v.fm_ratio,
                sr=sr,
            )
        s = int(start_s * sr)
        e = s + len(seg)
        if s >= n:
            continue
        if e > n:
            e = n
            seg = seg[: e - s]
        out_l = seg * (math.cos((v.pan + 1) * math.pi / 4) * math.sqrt(2))
        out_r = seg * (math.sin((v.pan + 1) * math.pi / 4) * math.sqrt(2))
        left[s:e] += out_l[: e - s]
        right[s:e] += out_r[: e - s]

    # Master bus: drop inaudible sub rumble and everything above ~16 kHz.
    # Nothing musical lives up there, so all it did was carry hiss into the
    # soft clip, where it turned into audible distortion products.
    left = _master_bus(left, sr)
    right = _master_bus(right, sr)

    # master soft clip
    left = np.tanh(left * 0.9)
    right = np.tanh(right * 0.9)
    return np.stack([left, right], axis=1)


def _master_bus(x: np.ndarray, sr: int = SR) -> np.ndarray:
    return _lowpass(_highpass(x, 30.0, sr), 16000.0, sr)


def _render_percussion(v: Voice, sr: int = SR) -> np.ndarray:
    """Render drum sounds with synthetic noise + low-frequency pitch envelope."""
    n = int(v.dur * sr)
    if n <= 0:
        return np.zeros(1)
    t = np.arange(n) / sr
    if v.ch == "kick":
        # pitch-decaying sine
        body = np.sin(2 * np.pi * v.freq * t - 2 * np.pi * 150 * t * t)
        env = np.exp(-t / 0.08)
        seg = body * env * v.amp
    elif v.ch == "snare":
        # Band-limited noise body + a tuned shell tone. Full-band white noise
        # here is what made the kit sound like a broken radio.
        noise = np.random.default_rng(int(v.start * 1000) & 0xFFFFFFFF).random(n) * 2 - 1
        noise = _bandpass(noise, 900.0, 4500.0, sr)
        shell = np.sin(2 * np.pi * 185.0 * t) * np.exp(-t / 0.03)
        body = noise * np.exp(-t / 0.06) + shell * 0.5
        seg = body * v.amp
    else:  # hat
        # Short, bright but *contained* noise. The old code differentiated raw
        # noise (np.diff), which tilts +6 dB/octave and turns a hat into a
        # burst of pure hiss that dominated the whole treble band.
        noise = np.random.default_rng(int(v.start * 1000 + 1) & 0xFFFFFFFF).random(n) * 2 - 1
        noise = _bandpass(noise, 6500.0, 11000.0, sr)
        seg = noise * np.exp(-t / 0.02) * v.amp
    return seg


def _apply_reverb(mix: np.ndarray, wet: float = 0.18, sr: int = SR) -> np.ndarray:
    from scipy.signal import fftconvolve
    ir_len = int(1.6 * sr)
    t = np.linspace(0, 1, ir_len)
    noise = np.random.default_rng(0).random(ir_len) * 2 - 1
    # Darken the tail. A white-noise impulse response convolves the *entire*
    # mix with broadband hiss, so "reverb" was really just adding noise. Real
    # rooms absorb treble first, so low-pass the noise before shaping decay.
    noise = _lowpass(noise, 3800.0, sr)
    noise = _lowpass(noise, 3800.0, sr)
    ir = noise * np.exp(-3.2 * t)
    # Small pre-delay keeps the direct sound distinct from the tail.
    pre = int(0.012 * sr)
    ir = np.concatenate([np.zeros(pre), ir])[:ir_len]
    # Energy-normalise, then match the wet loudness to the dry signal. The old
    # version normalised by absolute sum, which left the tail ~240x too quiet
    # and compensated with a magic `*10`, so `wet` never meant anything.
    ir = ir / (np.sqrt((ir ** 2).sum()) + 1e-9)
    out = np.stack([fftconvolve(mix[:, 0], ir)[:len(mix)],
                    fftconvolve(mix[:, 1], ir)[:len(mix)]], axis=1)
    rms_dry = float(np.sqrt((mix ** 2).mean())) + 1e-9
    rms_wet = float(np.sqrt((out ** 2).mean())) + 1e-9
    out = out * (rms_dry / rms_wet)
    return mix * (1 - wet) + out * wet


def _apply_delay(mix: np.ndarray, seconds: float = 0.34, feedback: float = 0.3,
                 wet: float = 0.25, sr: int = SR) -> np.ndarray:
    d = int(seconds * sr)
    n = len(mix)
    out = mix.copy()
    for ch in range(2):
        buf = np.zeros(n + d)
        buf[:n] = mix[:, ch]
        delayed = buf.copy()
        for rep in range(1, 4):
            shift = rep * d
            if shift >= n:
                break
            delayed[shift:shift + (n - shift)] += buf[:n - shift] * (feedback ** rep)
        out[:, ch] = mix[:, ch] * (1 - wet) + delayed[:n] * wet
    return out


# ── Main composition ────────────────────────────────────────────────────────

def compose(prompt: str, genre: str, mood: str, duration: float,
            lyrics: str = "") -> tuple[np.ndarray, dict[str, Any]]:
    """Compose a structured arrangement. Returns (stereo mix, metadata)."""
    style = STYLES.get(genre.lower())
    if style is None:
        style = STYLES.get("pop")
    rng = SeededRng(f"{prompt}:{genre}:{mood}")
    tempo = int(style.tempo * _mood_multiplier(mood, style))

    # Key: choose a root note deterministically from prompt
    root_pc = rng.randrange(0, 12)
    scale_pcs = style.scale_pcs
    SC = len(scale_pcs)

    def scale_note(degree: int, octave: int, root_pc: int = root_pc) -> float:
        """degree is an index (can be negative) into the scale, octave is the
        octave offset for the root (0 => around C3)."""
        idx = degree
        oct = octave
        while idx < 0:
            idx += SC
            oct -= 1
        while idx >= SC:
            idx -= SC
            oct += 1
        semitone = root_pc + scale_pcs[idx] + 12 * oct
        return _midi_freq(semitone)

    arr = Arrangement()

    total_bars = int(math.ceil(duration / bars_to_seconds(1, tempo))) + 2

    # Song form: [intro 4][verse 8][chorus 8][verse 8][chorus 8][bridge 4][chorus 8][outro 4]
    form: list[tuple[int, str]] = []
    cursor = 0
    for length, label in [(4, "intro"), (8, "verse"), (8, "chorus"),
                          (8, "verse"), (8, "chorus"), (4, "bridge"),
                          (8, "chorus"), (4, "outro")]:
        form.append((cursor, label))
        cursor += length
        if cursor >= total_bars:
            break

    bar_times = [bars_to_seconds(b, tempo) for b in range(total_bars)]

    # Chord progression: each bar gets a chord given by scale-degree root
    prog = style.progression
    prog_index = 0
    bar_chord_degree: list[int] = []  # scale-degree index for the chord root
    for b in range(total_bars):
        bar_chord_degree.append(prog[prog_index % len(prog)])
        prog_index += 1

    # ── Bass line ──
    for b in range(total_bars):
        t_start = bar_times[b]
        root_degree = bar_chord_degree[b]
        intensity = _section_intensity_for(form, b)
        pat = style.bass_pattern
        # Spread the pattern across the bar. The old code spaced entries half a
        # BAR apart, so eight notes spanned four bars and every bar's bass bled
        # into the next three — the main source of low-end mush.
        step_beats = 4.0 / max(1, len(pat))
        for half, deg in enumerate(pat):
            note_time = t_start + half * step_beats * beat_seconds(tempo)
            # bass uses the chord root + pattern offset
            freq = scale_note(root_degree + deg, 2)
            arr.add(ch="bass", start=note_time, freq=freq,
                    dur=beat_seconds(tempo) * step_beats * 0.9, amp=0.22 * intensity,
                    wave=style.wave_bass, cutoff=400, release=0.2)

    # ── Pads (sustained chord voicings) ──
    for b in range(total_bars):
        t_start = bar_times[b]
        root_degree = bar_chord_degree[b]
        chord_shape = style.chords[bar_chord_degree[b]]
        intensity = _section_intensity_for(form, b)
        if intensity < 0.3:
            continue
        for j, voicing_deg in enumerate(chord_shape):
            freq = scale_note(root_degree + voicing_deg, 3)
            arr.add(ch="pad", start=t_start, freq=freq,
                    dur=bars_to_seconds(1.0, tempo), amp=0.07 * (1 + j * 0.1),
                    wave=style.wave_pad, attack=0.6, sustain=0.9, release=1.2,
                    cutoff=1600, vibrato=0.4)

    # ── Melody (verse/chorus distinction) ──
    lo, hi = style.melody_range
    last_melody_freq: float | None = None
    for b in range(total_bars):
        t_start = bar_times[b]
        root_degree = bar_chord_degree[b]
        chord_shape = style.chords[bar_chord_degree[b]]
        intensity = _section_intensity_for(form, b)
        if intensity < 0.35:
            continue
        section = _section_name_for(form, b)
        notes_per_bar = 4 if section in ("chorus",) else 2
        if section == "bridge":
            notes_per_bar = 1
        for k in range(notes_per_bar):
            note_time = t_start + k * bars_to_seconds(1.0 / max(1, notes_per_bar), tempo)
            deg = rng.randrange(0, len(chord_shape))
            voicing_deg = chord_shape[deg]
            octave = rng.randrange(lo, hi)
            freq = scale_note(root_degree + voicing_deg, octave)
            # avoid huge leaps
            if last_melody_freq is not None and abs(freq - last_melody_freq) / last_melody_freq > 0.5:
                freq = last_melody_freq * 1.02 if freq > last_melody_freq else last_melody_freq * 0.98
            last_melody_freq = freq
            dur = bars_to_seconds(1.0 / max(1, notes_per_bar), tempo) * 0.9
            arr.add(ch="melody", start=note_time, freq=freq,
                    dur=dur, amp=0.18 * intensity,
                    wave=style.wave_lead, attack=0.02, decay=0.15, sustain=0.6,
                    release=0.2, cutoff=3200, vibrato=2.0 + rng.rand() * 1.0,
                    fm_ratio=2.0, fm_index=0.02 + rng.rand() * 0.03,
                    pan = rng.randrange(-3, 4) * 0.2)

    # ── Drums ──
    kick_times = []
    snare_times = []
    hat_times = []
    if style.drums:
        for b in range(total_bars):
            t_start = bar_times[b]
            intensity = _section_intensity_for(form, b)
            if intensity < 0.3:
                continue
            for beat_i in range(4):
                bt = t_start + beat_i * beat_seconds(tempo)
                # Kick on 1 and 3, snare on 2 and 4. A four-on-the-floor kick on
                # every beat made every genre thud identically.
                if beat_i in (0, 2):
                    kick_times.append(bt)
                if beat_i % 2 == 1:
                    snare_times.append(bt)
                # hats on offbeats
                hat_times.append(bt + beat_seconds(tempo) * 0.5)

    for t in kick_times:
        arr.add(ch="kick", start=t, freq=55, dur=0.3, amp=0.5, wave="sine",
                attack=0.001, decay=0.1, sustain=0.0, release=0.05)
    for t in snare_times:
        arr.add(ch="snare", start=t, freq=0, dur=0.12, amp=0.35,
                attack=0.001, decay=0.05, sustain=0.0, release=0.05)
    for t in hat_times:
        arr.add(ch="hat", start=t, freq=0, dur=0.04, amp=0.12,
                attack=0.001, decay=0.02, sustain=0.0, release=0.02)

    # ── Render ──
    mix = _render_arrangement(arr, min(total_bars * bars_to_seconds(1, tempo), duration) + 2, SR)
    mix = _apply_reverb(mix, wet=0.15, sr=SR)
    mix = _apply_delay(mix, wet=0.2, sr=SR)

    # normalize
    peak = np.abs(mix).max()
    if peak > 0:
        mix = mix / peak * 0.8

    # trim to requested duration exactly
    n_dur = int(duration * SR)
    if len(mix) >= n_dur:
        mix = mix[:n_dur]
    else:
        pad = np.zeros((n_dur - len(mix), 2))
        mix = np.concatenate([mix, pad])

    meta = {
        "tempo": tempo,
        "key_root_pc": root_pc,
        "genre": genre,
        "mood": mood,
        "style": style.__class__.__name__,
        "voices": {
            "kick": len(kick_times), "snare": len(snare_times),
            "hat": len(hat_times),
            "bass": sum(1 for v in arr.voices if v.ch == "bass"),
            "pad": sum(1 for v in arr.voices if v.ch == "pad"),
            "melody": sum(1 for v in arr.voices if v.ch == "melody"),
        },
    }
    return mix, meta


def _section_intensity_for(form: list[tuple[int, str]], bar: int) -> float:
    label = _section_name_for(form, bar)
    return {"intro": 0.5, "verse": 0.65, "chorus": 1.0,
            "bridge": 0.55, "outro": 0.45}.get(label, 0.6)


def _section_name_for(form: list[tuple[int, str]], bar: int) -> str:
    best = "verse"
    for start, label in form:
        if bar >= start:
            best = label
    return best


# ── WAV export ──────────────────────────────────────────────────────────────

def mix_to_wav_bytes(mix: np.ndarray, sr: int = SR) -> bytes:
    """Convert stereo float mix (-1..1) to 16-bit stereo WAV bytes."""
    data = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    interleaved = data.reshape(-1)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(interleaved.tobytes())
    return stream.getvalue()
