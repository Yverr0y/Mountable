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


# Text entry. Letters and digits are the plain US ones. The Sym layer sends key
# codes whose usual meaning is something else; what they type is set by the
# vendor's keymap, read from the system with this copy as the fallback.
VENDOR_KEYMAP = "/usr/share/keymaps/tca8418_keypad_m5stack_keymap.map"
SYMBOLS = {
    26: "!", 27: "@", 39: "#", 40: "$", 41: "%", 43: "^", 51: "&", 52: "*", 53: "(", 94: ")",
    55: "~", 69: "`", 70: "_", 71: "-", 72: "+", 73: "=", 74: "[", 75: "]", 76: "{", 77: "}",
    79: ";", 80: ":", 81: "'", 82: '"', 83: "<", 85: ">", 86: "\\", 89: "|",
    90: ",", 91: ".", 92: "/", 93: "?",
}
KEYSYMS = {
    "exclam": "!", "at": "@", "numbersign": "#", "dollar": "$", "percent": "%",
    "asciicircum": "^", "ampersand": "&", "asterisk": "*", "parenleft": "(", "parenright": ")",
    "asciitilde": "~", "grave": "`", "underscore": "_", "minus": "-", "plus": "+", "equal": "=",
    "bracketleft": "[", "bracketright": "]", "braceleft": "{", "braceright": "}",
    "semicolon": ";", "colon": ":", "apostrophe": "'", "quotedbl": '"', "less": "<",
    "greater": ">", "backslash": "\\", "bar": "|", "comma": ",", "period": ".", "slash": "/",
    "question": "?", "space": " ",
}
SHIFTED_DIGITS = dict(zip("1234567890", "!@#$%^&*()"))
EDITING = {"KEY_ENTER": "enter", "KEY_KPENTER": "enter", "KEY_ESC": "esc",
           "KEY_BACKSPACE": "backspace", "KEY_DELETE": "backspace"}
SHIFT = ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT")


def load_symbols(path=VENDOR_KEYMAP):
    """The Sym layer's characters by key code: lines like "keycode 26 = exclam"."""
    symbols = dict(SYMBOLS)
    try:
        with open(path) as f:
            for line in f:
                words = line.split("#")[0].split()
                if len(words) >= 4 and words[0] == "keycode" and words[2] == "=" and words[3] in KEYSYMS:
                    symbols[int(words[1])] = KEYSYMS[words[3]]
    except (OSError, ValueError):
        pass
    return symbols


class Keyboard:
    def __init__(self, device=KEYBOARD):
        import evdev
        self._evdev = evdev
        self._dev = evdev.InputDevice(device)
        self._shift = any(name in SHIFT for name, _ in self._dev.active_keys(verbose=True))
        self._symbols = load_symbols()
        # While set, keys are returned as the characters they type (plus
        # "enter", "esc" and "backspace") instead of as navigation actions.
        self.text = False

    def _typed(self, name, number):
        if name in EDITING:
            return EDITING[name]
        if number in self._symbols:
            return self._symbols[number]
        key = name[4:]   # after "KEY_"
        if len(key) == 1 and key.isalpha():
            return key if self._shift else key.lower()
        if len(key) == 1 and key.isdigit():
            return SHIFTED_DIGITS[key] if self._shift else key
        return " " if name == "KEY_SPACE" else None

    def read(self, timeout):
        """Return the keys pressed within `timeout` seconds, as action names."""
        keys = []
        if not select.select([self._dev.fd], [], [], timeout)[0]:
            return keys
        for event in self._dev.read():
            if event.type != self._evdev.ecodes.EV_KEY:
                continue
            code = self._evdev.ecodes.KEY.get(event.code)
            if isinstance(code, (list, tuple)):
                code = code[0]
            if code in SHIFT:
                self._shift = event.value != 0
            if event.value == 0 or not code:
                continue   # ignore key releases; presses and auto-repeat both count
            if self.text:
                typed = self._typed(code, event.code)
                # A key held a moment too long must not type twice.
                if typed and (event.value == 1 or typed == "backspace"):
                    keys.append(typed)
            elif code in NAMES:
                keys.append(NAMES[code])
            elif len(code) == 5 and code[4].isalpha():
                keys.append(code[4].lower())   # KEY_A .. KEY_Z
        return keys


class ScriptedKeys:
    """Replays a fixed key sequence, one key per frame, then signals the end."""

    def __init__(self, keys):
        self._keys = list(keys)
        self.finished = False
        self.text = False

    def read(self, timeout):
        if not self._keys:
            self.finished = True
            return []
        return [self._keys.pop(0)]
