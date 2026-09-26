"""
Raspberry Pi GPIO Hardware Buzzer / Relay Alert Controller.
Gracefully falls back to mock buzzer when not running on Raspberry Pi hardware.
"""

import time
import threading
from app.config.settings import load_config


class GPIOBuzzer:
    """Controls local physical alert buzzer on Raspberry Pi GPIO."""

    def __init__(self):
        self._gpio = None
        self._is_pi = False
        self._pin = 18
        self._init_gpio()

    def _init_gpio(self):
        """Attempt to initialize Raspberry Pi GPIO."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setwarnings(False)
            self._is_pi = True
            print("[GPIO] Raspberry Pi GPIO initialized.")
        except Exception:
            self._is_pi = False
            # print("[GPIO] Non-RPi environment. Using simulated GPIO buzzer.")

    def trigger_buzzer(self, duration: float = 0.8):
        """Activate buzzer asynchronously for specified duration."""
        cfg = load_config()
        gpio_cfg = cfg.get("alerts", {}).get("gpio", {})
        if not gpio_cfg.get("enabled", False):
            return

        pin = int(gpio_cfg.get("buzzer_pin", self._pin))
        dur = float(gpio_cfg.get("duration_sec", duration))

        t = threading.Thread(target=self._beep, args=(pin, dur), daemon=True)
        t.start()

    def _beep(self, pin: int, duration: float):
        if self._is_pi and self._gpio:
            try:
                self._gpio.setup(pin, self._gpio.OUT)
                self._gpio.output(pin, self._gpio.HIGH)
                time.sleep(duration)
                self._gpio.output(pin, self._gpio.LOW)
            except Exception as e:
                print(f"[GPIO] Buzzer error: {e}")
        else:
            # Simulated beep in logs
            # print(f"[GPIO Mock] BEEP on pin {pin} for {duration}s")
            pass

    def cleanup(self):
        """Release GPIO pins."""
        if self._is_pi and self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
