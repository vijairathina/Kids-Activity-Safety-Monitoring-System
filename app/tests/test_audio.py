"""
Unit Tests for Audio Analyzer Features and Spectral Extraction.
"""

import unittest
import numpy as np
from app.ai.audio import AudioAnalyzer


class TestAudioAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = AudioAnalyzer()

    def test_rms_and_peak_calculation(self):
        """Analyze high energy signal for RMS and Peak values."""
        # 1024 samples of a sine wave with amplitude 0.8
        t = np.linspace(0, 1024 / 16000, 1024, False)
        signal = (0.8 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

        self.analyzer._analyze_chunk(signal)
        self.assertGreater(self.analyzer.current_peak, 0.75)
        self.assertGreater(self.analyzer.current_rms, 0.4)

    def test_scream_frequency_detection(self):
        """Test scream frequency identification in the 1500-3500 Hz band."""
        t = np.linspace(0, 1024 / 16000, 1024, False)
        # 2400 Hz tone represents loud child scream pitch
        signal = (0.9 * np.sin(2 * np.pi * 2400 * t)).astype(np.float32)

        self.analyzer._analyze_chunk(signal)
        # Dominant frequency should be close to 2400 Hz
        self.assertAlmostEqual(self.analyzer.dominant_frequency, 2400.0, delta=150.0)


if __name__ == "__main__":
    unittest.main()
