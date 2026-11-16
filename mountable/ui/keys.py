"""Input from the built-in keyboard."""

import select

KEYBOARD = "/dev/input/by-path/platform-3f804000.i2c-event"

NAMES = {
    "KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
    "KEY_ENTER": "enter", "KEY_SPACE": "enter", "KEY_ESC": "esc",
    "KEY_BACKSPACE": "esc", "KEY_GRAVE": "esc", "KEY_DELETE": "delete",
    "KEY_PAGEUP": "pageup", "KEY_PAGEDOWN": "pagedown",
    # Navigation without holding Fn: F up, X down, Z left, C right.
    "KEY_F": "up", "KEY_X": "down", "KEY_Z": "left", "KEY_C": "right",
}


class Keyboard:
    def __init__(self, device=KEYBOARD):
        import evdev
        self._evdev = evdev
        self._dev = evdev.InputDevice(device)

    def read(self, timeout):
        """Return the keys pressed within `timeout` seconds, as action names."""
        keys = []
        if not select.select([self._dev.fd], [], [], timeout)[0]:
            return keys
        for event in self._dev.read():
            if event.type != self._evdev.ecodes.EV_KEY or event.value == 0:
                continue   # ignore key releases; presses and auto-repeat both count
            code = self._evdev.ecodes.KEY.get(event.code)
            if isinstance(code, (list, tuple)):
                code = code[0]
            if code in NAMES:
                keys.append(NAMES[code])
            elif code and len(code) == 5 and code[4].isalpha():
                keys.append(code[4].lower())   # KEY_A .. KEY_Z
        return keys


class ScriptedKeys:
    """Replays a fixed key sequence, one key per frame, then signals the end."""

    def __init__(self, keys):
        self._keys = list(keys)
        self.finished = False

    def read(self, timeout):
        if not self._keys:
            self.finished = True
            return []
        return [self._keys.pop(0)]
