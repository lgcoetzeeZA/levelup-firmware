RELAY_STATE_FILE = "relay_state.txt"


def load_relay_state():
    """Returns the last saved relay state (0 or 1). Defaults to 0 (off)
    if no state has ever been saved (e.g. first boot)."""
    try:
        with open(RELAY_STATE_FILE, "r") as f:
            value = f.read().strip()
            return 1 if value == "1" else 0
    except OSError:
        return 0


def save_relay_state(value):
    try:
        with open(RELAY_STATE_FILE, "w") as f:
            f.write("1" if value else "0")
    except OSError as e:
        print("Failed to save relay state:", e)
