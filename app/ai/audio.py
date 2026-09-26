"""
Lightweight Audio Processing Engine for Raspberry Pi.
Monitors RMS volume, peak energy, and spectral centroid (screaming/crying detection).
Includes a 10s circular pre-event ring buffer and privacy-preserving ephemeral processing.
"""

import time
import math
import threading
from collections import deque
import numpy as np
from typing import Dict, Any, Optional, List
from app.config.settings import load_config


class AudioAnalyzer:
    """Threaded audio analyzer with spectral feature extraction."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Audio stream settings
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.rms_threshold = 0.35
        self.peak_threshold = 0.70
        self.screaming_freq_min = 1500
        self.screaming_freq_max = 3500

        # Ring buffer for 10s pre-event audio frames
        # 16000 samples/sec / 1024 ~ 15.6 chunks/sec * 10s = ~160 chunks
        self.ring_buffer = deque(maxlen=160)

        # Real-time metrics
        self.current_rms = 0.0
        self.current_peak = 0.0
        self.dominant_frequency = 0.0
        self.last_audio_event = None
        self.last_event_time = 0.0

        # Demo simulation flag
        self._demo_audio_trigger: Optional[str] = None

    def start(self):
        """Start audio listening thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._audio_loop, daemon=True, name="AudioMonitor")
        self._thread.start()

    def stop(self):
        """Stop audio thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def trigger_demo_sound(self, sound_type: str = "screaming"):
        """Trigger simulated audio event for testing: 'screaming', 'loud_noise', 'impact'."""
        self._demo_audio_trigger = sound_type

    def _audio_loop(self):
        """Audio capture loop. Uses hardware mic if available, else synthetic simulation."""
        cfg = load_config()
        audio_cfg = cfg.get("audio", {})
        self.rms_threshold = float(audio_cfg.get("rms_threshold", 0.35))
        self.peak_threshold = float(audio_cfg.get("peak_threshold", 0.70))

        # Check if PyAudio is available
        pyaudio_stream = None
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            dev_idx = audio_cfg.get("listen_device_index", -1)
            pyaudio_stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=None if dev_idx < 0 else dev_idx,
                frames_per_buffer=self.chunk_size
            )
            print("[Audio] PyAudio stream opened successfully.")
        except Exception:
            pyaudio_stream = None
            print("[Audio] PyAudio hardware mic unavailable. Running in synthetic/simulated audio mode.")

        sim_tick = 0
        while self._running:
            try:
                if pyaudio_stream is not None:
                    raw_data = pyaudio_stream.read(self.chunk_size, exception_on_overflow=False)
                    audio_chunk = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                else:
                    # Synthetic ambient audio generation (subtle room noise + simulated triggers)
                    sim_tick += 1
                    t = np.linspace(0, self.chunk_size / self.sample_rate, self.chunk_size, False)
                    # Baseline background hum
                    audio_chunk = np.random.normal(0, 0.015, self.chunk_size).astype(np.float32)

                    # Check for manual trigger or periodic test scream
                    if self._demo_audio_trigger == "screaming":
                        # High pitched 2200 Hz tone + harmonics + noise
                        scream = 0.65 * np.sin(2 * np.pi * 2200 * t) + 0.3 * np.sin(2 * np.pi * 1800 * t)
                        audio_chunk += scream.astype(np.float32)
                        self._demo_audio_trigger = None
                    elif self._demo_audio_trigger == "impact":
                        audio_chunk[:200] += np.random.uniform(-0.85, 0.85, 200).astype(np.float32)
                        self._demo_audio_trigger = None
                    elif self._demo_audio_trigger == "loud_noise":
                        audio_chunk += np.random.uniform(-0.55, 0.55, self.chunk_size).astype(np.float32)
                        self._demo_audio_trigger = None

                    time.sleep(self.chunk_size / self.sample_rate)

                # Process features
                self._analyze_chunk(audio_chunk)

            except Exception as e:
                time.sleep(0.1)

        if pyaudio_stream:
            try:
                pyaudio_stream.stop_stream()
                pyaudio_stream.close()
            except Exception:
                pass

    def _analyze_chunk(self, chunk: np.ndarray):
        """Extract RMS, peak, and spectral features from chunk."""
        if len(chunk) == 0:
            return

        rms = float(np.sqrt(np.mean(chunk**2)))
        peak = float(np.max(np.abs(chunk)))

        # FFT for dominant frequency
        dominant_freq = 0.0
        try:
            fft_data = np.abs(np.fft.rfft(chunk))
            freqs = np.fft.rfftfreq(len(chunk), 1.0 / self.sample_rate)
            peak_idx = np.argmax(fft_data[1:]) + 1  # Ignore DC
            dominant_freq = float(freqs[peak_idx])
        except Exception:
            pass

        with self._lock:
            self.current_rms = round(rms, 3)
            self.current_peak = round(peak, 3)
            self.dominant_frequency = round(dominant_freq, 1)
            self.ring_buffer.append(chunk)

            # Safety event detection logic
            now = time.time()
            if now - self.last_event_time > 3.0:  # 3s cooldown
                if peak > self.peak_threshold and (self.screaming_freq_min <= dominant_freq <= self.screaming_freq_max):
                    self.last_audio_event = {
                        "type": "SCREAM_DETECTED",
                        "severity": "CRITICAL",
                        "confidence": 0.88,
                        "rms": self.current_rms,
                        "freq": self.dominant_frequency
                    }
                    self.last_event_time = now
                elif peak > self.peak_threshold:
                    self.last_audio_event = {
                        "type": "IMPACT_BANG",
                        "severity": "WARNING",
                        "confidence": 0.82,
                        "rms": self.current_rms,
                        "peak": self.current_peak
                    }
                    self.last_event_time = now
                elif rms > self.rms_threshold:
                    self.last_audio_event = {
                        "type": "LOUD_NOISE",
                        "severity": "WARNING",
                        "confidence": 0.75,
                        "rms": self.current_rms
                    }
                    self.last_event_time = now

    def pop_event(self) -> Optional[Dict[str, Any]]:
        """Fetch and clear any pending audio safety event."""
        with self._lock:
            ev = self.last_audio_event
            self.last_audio_event = None
            return ev

    def get_metrics(self) -> Dict[str, Any]:
        """Return real-time audio monitor stats."""
        with self._lock:
            return {
                "rms": self.current_rms,
                "peak": self.current_peak,
                "dominant_freq": self.dominant_frequency,
                "status": "active" if self._running else "stopped"
            }
