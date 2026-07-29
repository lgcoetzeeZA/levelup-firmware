from machine import Pin, PWM

FULL = 1023  # ESP32 PWM duty is 10-bit (0-1023), not 0-255


class RGBLed:
    def __init__(self, red_pin, green_pin, blue_pin, freq=60):
        self.r = PWM(Pin(red_pin))
        self.g = PWM(Pin(green_pin))
        self.b = PWM(Pin(blue_pin))
        for channel in (self.r, self.g, self.b):
            channel.freq(freq)
            channel.duty(0)

    def set_rgb(self, r, g, b):
        """r, g, b: duty values 0-1023"""
        self.r.duty(r)
        self.g.duty(g)
        self.b.duty(b)

    def off(self):
        self.set_rgb(0, 0, 0)

    def set_percent(self, percent):
        """Colour-codes the tank level: red (low/empty) through to
        blue (full). Turns off if percent is None (no reading available yet)."""
        if percent is None:
            self.off()
            return

        if percent > 90:
            self.set_rgb(0, 0, FULL)              # blue
        elif percent > 80:
            self.set_rgb(0, FULL, FULL)           # cyan
        elif percent > 50:
            self.set_rgb(0, FULL, 0)              # green
        elif percent > 30:
            self.set_rgb(FULL, FULL, 0)           # yellow
        elif percent > 20:
            self.set_rgb(FULL, 520, 0)            # orange
        else:
            self.set_rgb(FULL, 0, 0)              # red
