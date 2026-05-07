#!/usr/bin/env python3
"""
Peniru - Mouse & Keyboard Macro Recorder
Version: 1.0
Developer: Ruoloc

A modern, dark-themed macro recorder with advanced playback controls.
GUI rewritten from tkinter → PySide6.
"""

import sys
import threading
import time
import json
import random
import math
from pathlib import Path
from collections import deque

# ─────────────────────────────────────────────
# PySide6 imports
# ─────────────────────────────────────────────
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QListWidget, QTreeWidget,
    QTreeWidgetItem, QRadioButton, QButtonGroup, QSpinBox, QFrame,
    QSplitter, QMessageBox, QInputDialog, QSizePolicy,
    QAbstractItemView, QSystemTrayIcon, QMenu, QScrollArea,
    QCheckBox, QColorDialog, QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QEvent, QSize, QPointF
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPixmap, QPainter, QBrush, QPen,
    QPolygonF, QAction, QKeySequence,
)

# ─────────────────────────────────────────────
# DEPENDENCY IMPORTS (with graceful error messages)
# ─────────────────────────────────────────────
try:
    from pynput import mouse as pynput_mouse, keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("[WARNING] pynput not installed. Recording disabled. Run: pip install pynput")

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("[WARNING] pyautogui not installed. Playback disabled. Run: pip install pyautogui")

try:
    from PIL import Image as PILImage, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[INFO] Pillow not installed. Tray icon will be plain. Run: pip install pillow")

# ─────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────
APP_NAME      = "Peniru"
APP_VERSION   = "1.0"
APP_DEV       = "Ruoloc"
MACRO_DIR     = Path.home() / ".peniru" / "macros"
SETTINGS_FILE = Path.home() / ".peniru" / "settings.json"
MACRO_DIR.mkdir(parents=True, exist_ok=True)

MOUSE_MOVE_THRESHOLD = 5
SCROLL_MULTIPLIER    = 120

DEFAULT_HOTKEYS = {
    "start_record": "f6",
    "stop_record":  "f7",
    "play_macro":   "f8",
    "stop_play":    "f9",
    "emergency":    "escape",
}

SPEED_OPTIONS = [0.5, 1.0, 2.0, 5.0]
SPEED_LABELS  = ["0.5×", "1×", "2×", "5×"]

# Common keys that the user can pick from when editing an event's action
COMMON_KEYS = [
    # Letters
    *(chr(c) for c in range(ord('a'), ord('z') + 1)),
    # Digits
    *(str(d) for d in range(10)),
    # Function keys
    *(f"f{i}" for i in range(1, 13)),
    # Modifiers
    "ctrl_l", "ctrl_r", "shift_l", "shift_r",
    "alt_l", "alt_r", "alt_gr",
    "cmd_l", "cmd_r",        # Windows / Cmd keys
    # Whitespace / common
    "space", "enter", "tab", "backspace", "delete", "esc",
    # Locks
    "caps_lock", "num_lock", "scroll_lock",
    # Navigation
    "home", "end", "page_up", "page_down", "insert",
    "left", "right", "up", "down",
    # Misc
    "print_screen", "pause",
]

C = {
    "bg":          "#0a0a0f",
    "surface":     "#111118",
    "surface2":    "#18181f",
    "surface3":    "#202028",
    "border":      "#2c2c3e",
    "border_hi":   "#3d3d55",
    "accent":      "#7c5cfc",
    "accent2":     "#5b3dd4",
    "accent_glow": "#a48bff",
    "accent_dim":  "#3a2d7a",
    "red":         "#f05c5c",
    "red_dim":     "#6b1c1c",
    "yellow":      "#f0c040",
    "orange":      "#f08a3c",
    "green":       "#3deba0",
    "green_dim":   "#1a5c40",
    "text":        "#eeeef5",
    "text_dim":    "#8080a8",
    "text_muted":  "#44445a",
    "recording":   "#f05c5c",
    "playing":     "#3deba0",
    "idle":        "#606080",
}

# Default icon colour – can be changed globally at runtime via PeniruApp._set_icon_color()
ICON_COLOR = C["text"]   # #eeeef5

# ═════════════════════════════════════════════
#  MODULE 1 – RECORDER
# ═════════════════════════════════════════════
class Recorder:
    """Captures mouse and keyboard events with timestamps."""

    def __init__(self):
        self.events          = []
        self.is_recording    = False
        self._start_time     = 0.0
        self._last_mouse_pos = (0, 0)
        self._mouse_listener    = None
        self._keyboard_listener = None
        self._lock = threading.Lock()

    def start(self):
        if self.is_recording:
            return
        with self._lock:
            self.events.clear()
            self._start_time     = time.perf_counter()
            self._last_mouse_pos = (0, 0)
            self.is_recording    = True
        if not PYNPUT_AVAILABLE:
            print("[Recorder] pynput unavailable – cannot record.")
            return
        self._mouse_listener = pynput_mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self._keyboard_listener = pynput_keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self):
        if not self.is_recording:
            return self.events
        self.is_recording = False
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        self._mouse_listener    = None
        self._keyboard_listener = None
        return self.events

    def get_events(self):
        return list(self.events)

    def _ts(self):
        return (time.perf_counter() - self._start_time) * 1000

    def _on_mouse_move(self, x, y):
        if not self.is_recording:
            return
        lx, ly = self._last_mouse_pos
        if math.hypot(x - lx, y - ly) < MOUSE_MOVE_THRESHOLD:
            return
        self._last_mouse_pos = (x, y)
        with self._lock:
            self.events.append({"type": "mouse_move", "x": x, "y": y, "time": self._ts()})

    def _on_mouse_click(self, x, y, button, pressed):
        if not self.is_recording:
            return
        with self._lock:
            self.events.append({
                "type": "mouse_click", "x": x, "y": y,
                "button": button.name, "pressed": pressed, "time": self._ts(),
            })

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not self.is_recording:
            return
        with self._lock:
            self.events.append({
                "type": "mouse_scroll", "x": x, "y": y,
                "dx": dx, "dy": dy, "time": self._ts(),
            })

    def _on_key_press(self, key):
        if not self.is_recording:
            return
        with self._lock:
            self.events.append({"type": "key_press", "key": self._key_name(key), "time": self._ts()})

    def _on_key_release(self, key):
        if not self.is_recording:
            return
        with self._lock:
            self.events.append({"type": "key_release", "key": self._key_name(key), "time": self._ts()})

    @staticmethod
    def _key_name(key):
        try:
            return key.char
        except AttributeError:
            return str(key).replace("Key.", "")


# ═════════════════════════════════════════════
#  MODULE 2 – PLAYER
# ═════════════════════════════════════════════
class Player:
    """Replays recorded macro events with precise timing."""

    def __init__(self):
        self.is_playing  = False
        self._stop_event = threading.Event()
        self._thread     = None

    def play(self, events, speed=1.0, loops=1,
             humanize=False, on_done=None, on_status=None):
        if self.is_playing or not events:
            return
        self.is_playing = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(events, speed, loops, humanize, on_done, on_status),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.is_playing = False

    def _run(self, events, speed, loops, humanize, on_done, on_status):
        loop_count = 0
        try:
            while not self._stop_event.is_set():
                loop_count += 1
                if on_status:
                    info = f"Loop {loop_count}" if loops != 1 else "Playing"
                    on_status(info)
                self._play_once(events, speed, humanize)
                if self._stop_event.is_set():
                    break
                if loops != 0 and loop_count >= loops:
                    break
        finally:
            self.is_playing = False
            if on_done:
                on_done()

    def _play_once(self, events, speed, humanize):
        if not PYAUTOGUI_AVAILABLE:
            print("[Player] pyautogui unavailable – cannot play.")
            return
        t_start = time.perf_counter()
        t0 = events[0]["time"] if events else 0
        for evt in events:
            if self._stop_event.is_set():
                return
            target_offset = (evt["time"] - t0) / (speed * 1000)
            if humanize:
                target_offset += random.uniform(-0.02, 0.02)
            elapsed = time.perf_counter() - t_start
            wait = target_offset - elapsed
            if wait > 0:
                deadline = time.perf_counter() + wait
                if wait > 0.005:
                    time.sleep(wait - 0.003)
                while time.perf_counter() < deadline:
                    pass
            if self._stop_event.is_set():
                return
            self._dispatch(evt, humanize)

    @staticmethod
    def _dispatch(evt, humanize):
        etype = evt["type"]
        if etype == "mouse_move":
            x, y = evt["x"], evt["y"]
            if humanize:
                x += random.randint(-3, 3); y += random.randint(-3, 3)
            pyautogui.moveTo(x, y, duration=0)
        elif etype == "mouse_click":
            x, y = evt["x"], evt["y"]
            if humanize:
                x += random.randint(-2, 2); y += random.randint(-2, 2)
            btn = evt.get("button", "left")
            if evt["pressed"]:
                pyautogui.mouseDown(x=x, y=y, button=btn)
            else:
                pyautogui.mouseUp(x=x, y=y, button=btn)
        elif etype == "mouse_scroll":
            pyautogui.scroll(int(evt["dy"] * SCROLL_MULTIPLIER), x=evt["x"], y=evt["y"])
        elif etype in ("key_press", "key_release"):
            key = Player._normalize_key(evt.get("key", ""))
            if not key:
                return
            try:
                if etype == "key_press":
                    pyautogui.keyDown(key)
                else:
                    pyautogui.keyUp(key)
            except Exception:
                pass

    _PYNPUT_TO_PYAUTOGUI = {
        "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
        "shift_l": "shiftleft", "shift_r": "shiftright",
        "alt_l": "altleft", "alt_r": "altright", "alt_gr": "altright",
        "cmd": "winleft", "cmd_l": "winleft", "cmd_r": "winright",
        "caps_lock": "capslock", "num_lock": "numlock",
        "scroll_lock": "scrolllock", "print_screen": "printscreen",
        "page_up": "pageup", "page_down": "pagedown",
        "esc": "escape", "enter": "return",
        "left": "left", "right": "right", "up": "up", "down": "down",
        "backspace": "backspace", "tab": "tab", "delete": "delete",
        "home": "home", "end": "end", "insert": "insert",
        "space": "space", "pause": "pause",
        "media_play_pause": "playpause", "media_volume_mute": "volumemute",
        "media_volume_up": "volumeup", "media_volume_down": "volumedown",
        "media_next": "nexttrack", "media_previous": "prevtrack",
        **{f"f{i}": f"f{i}" for i in range(1, 21)},
    }

    @staticmethod
    def _normalize_key(key: str) -> str:
        if key.startswith("Key."):
            key = key[4:]
        if len(key) >= 3 and key[0] == "'" and key[-1] == "'":
            key = key[1:-1]
        return Player._PYNPUT_TO_PYAUTOGUI.get(key.lower(), key)


# ═════════════════════════════════════════════
#  MODULE 3 – MACRO MANAGER
# ═════════════════════════════════════════════
class MacroManager:
    @staticmethod
    def save(name: str, events: list) -> bool:
        try:
            path = MACRO_DIR / f"{name}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"name": name, "events": events}, f, indent=2)
            return True
        except Exception as e:
            print(f"[MacroManager] Save error: {e}")
            return False

    @staticmethod
    def load(name: str) -> list:
        try:
            path = MACRO_DIR / f"{name}.json"
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("events", [])
        except Exception as e:
            print(f"[MacroManager] Load error: {e}")
            return []

    @staticmethod
    def delete(name: str) -> bool:
        try:
            (MACRO_DIR / f"{name}.json").unlink(missing_ok=True)
            return True
        except Exception as e:
            print(f"[MacroManager] Delete error: {e}")
            return False

    @staticmethod
    def list_macros() -> list:
        return sorted(p.stem for p in MACRO_DIR.glob("*.json"))


# ═════════════════════════════════════════════
#  MODULE 4 – SETTINGS
# ═════════════════════════════════════════════
class Settings:
    # Default colour palette (mirrors C[] at startup)
    DEFAULT_COLORS = {}   # filled after C is defined below

    def __init__(self):
        self.hotkeys  = dict(DEFAULT_HOTKEYS)
        self.colors   = {}
        self.hide_in_tray    = False
        self.start_minimized = False
        self._init_colors()
        self._load()

    def _init_colors(self):
        self.colors = {
            "gui_bg":               C["bg"],
            "titlebar_bg":          C["surface"],
            "titlebar_border":      C["border"],
            "font_color":           C["text"],
            "font_dim_color":       C["text_dim"],
            "icon_color":           C["text"],
            "icon_box_bg":          C["surface3"],   # NEW – background of each icon button
            "ctrl_container_bg":    C["surface2"],
            "ctrl_container_border":C["border"],
            "hk_container_bg":      C["surface2"],
            "hk_container_border":  C["border"],
            "panel_bg":             C["surface"],
            "panel_border":         C["border"],
            "accent":               C["accent"],
            "footer_bg":            C["surface"],
        }

    def _load(self):
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                self.hotkeys.update(data.get("hotkeys", {}))
                for k, v in data.get("colors", {}).items():
                    if k in self.colors:
                        self.colors[k] = v
                self.hide_in_tray    = data.get("hide_in_tray", False)
                self.start_minimized = data.get("start_minimized", False)
        except Exception:
            pass

    def save(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SETTINGS_FILE, "w") as f:
                json.dump({
                    "hotkeys":         self.hotkeys,
                    "colors":          self.colors,
                    "hide_in_tray":    self.hide_in_tray,
                    "start_minimized": self.start_minimized,
                }, f, indent=2)
        except Exception as e:
            print(f"[Settings] Save error: {e}")


# ═════════════════════════════════════════════
#  MODULE 5 – HOTKEY DAEMON
# ═════════════════════════════════════════════
class HotkeyDaemon:
    def __init__(self, settings: Settings):
        self.settings   = settings
        self._callbacks = {}
        self._listener  = None
        self._pressed   = set()

    def set_callback(self, action: str, fn):
        self._callbacks[action] = fn

    def start(self):
        if not PYNPUT_AVAILABLE:
            return
        self._listener = pynput_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()

    def _on_press(self, key):
        name = self._key_name(key)
        if name in self._pressed:
            return
        self._pressed.add(name)
        self._fire(name)

    def _on_release(self, key):
        self._pressed.discard(self._key_name(key))

    def _fire(self, name):
        for action, key in self.settings.hotkeys.items():
            if key.lower() == name.lower():
                cb = self._callbacks.get(action)
                if cb:
                    cb()

    @staticmethod
    def _key_name(key):
        try:
            return key.char or ""
        except AttributeError:
            return str(key).replace("Key.", "")


# ═════════════════════════════════════════════
#  SIGNALS (for cross-thread UI updates)
# ═════════════════════════════════════════════
class AppSignals(QObject):
    status_changed    = Signal(str, str)   # (text, color_hex)
    events_updated    = Signal()
    poll_recording    = Signal(int)        # event count
    play_finished     = Signal()           # fired from player thread when playback ends
    hotkey_triggered  = Signal(str)        # fired from pynput thread → dispatched on main thread


# ═════════════════════════════════════════════
#  GLOBAL STYLESHEET
# ═════════════════════════════════════════════
APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C["bg"]};
    color: {C["text"]};
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 10pt;
}}
QLabel {{
    color: {C["text"]};
    background: transparent;
}}
QPushButton {{
    background-color: {C["surface3"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 5px;
    padding: 7px 14px;
    font-size: 9pt;
}}
QPushButton:hover {{
    background-color: {C["border_hi"]};
    border-color: {C["accent"]};
}}
QPushButton:pressed {{
    background-color: {C["accent_dim"]};
}}
QPushButton:disabled {{
    color: {C["text_muted"]};
    background-color: {C["surface2"]};
}}
QPushButton#bigBtn {{
    font-size: 10pt;
    font-weight: bold;
    padding: 12px 8px;
    border-radius: 6px;
}}
QPushButton#accentBtn {{
    background-color: {C["accent"]};
    border-color: {C["accent2"]};
    color: {C["text"]};
    font-weight: bold;
}}
QPushButton#accentBtn:hover {{
    background-color: {C["accent_glow"]};
}}
QPushButton#redBtn {{
    background-color: {C["red"]};
    border-color: #c03030;
    color: white;
    font-weight: bold;
}}
QPushButton#redBtn:hover {{
    background-color: #ff7070;
}}
QPushButton#emergBtn {{
    background-color: {C["red_dim"]};
    color: {C["red"]};
    border: 1px solid {C["red"]};
    font-size: 11pt;
    font-weight: bold;
    padding: 14px;
    border-radius: 6px;
}}
QPushButton#emergBtn:hover {{
    background-color: #8b2020;
    color: white;
}}
QPushButton#hotkeyBtn {{
    background-color: {C["surface3"]};
    color: {C["accent_glow"]};
    font-weight: bold;
    font-size: 9pt;
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid {C["border"]};
}}
QPushButton#hotkeyBtn:hover {{
    background-color: {C["border_hi"]};
    border-color: {C["accent_glow"]};
}}
QRadioButton {{
    background-color: {C["surface3"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
    padding: 4px 10px;
    spacing: 0px;
}}
QRadioButton:hover {{
    background-color: {C["border_hi"]};
}}
QRadioButton:checked {{
    background-color: {C["accent2"]};
    color: {C["text"]};
    border-color: {C["accent"]};
}}
QRadioButton::indicator {{
    width: 0px;
    height: 0px;
}}

/* ── Segmented control (Playback Speed group) ── */
QWidget#segCtl, QWidget#segCtlLoop {{
    background-color: {C["surface2"]};
    border: 1px solid {C["border"]};
    border-radius: 7px;
}}
QWidget#segCtlLoop QPushButton#segBtn {{
    min-width: 60px;
}}
QPushButton#segBtn {{
    background-color: transparent;
    color: {C["text_dim"]};
    border: none;
    border-radius: 4px;
    padding: 5px 0;
    min-width: 44px;
    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 9pt;
    font-weight: 500;
    text-align: center;
}}
QPushButton#segBtn:hover {{
    background-color: {C["surface3"]};
    color: {C["text"]};
}}
QPushButton#segBtn:checked {{
    background-color: {C["accent2"]};
    color: {C["text"]};
    font-weight: bold;
}}
QPushButton#segBtn:checked:hover {{
    background-color: {C["accent"]};
}}
QListWidget {{
    background-color: {C["surface2"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
    font-size: 10pt;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 3px;
}}
QListWidget::item:selected {{
    background-color: {C["accent_dim"]};
    color: {C["accent_glow"]};
}}
QListWidget::item:hover {{
    background-color: {C["surface3"]};
}}
QTreeWidget {{
    background-color: {C["surface2"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
    font-size: 9pt;
    outline: none;
    alternate-background-color: {C["surface"]};
}}
QTreeWidget::item {{
    padding: 4px 2px;
}}
QTreeWidget::item:selected {{
    background-color: {C["accent_dim"]};
    color: {C["accent_glow"]};
}}
QHeaderView::section {{
    background-color: {C["surface3"]};
    color: {C["text_dim"]};
    border: none;
    border-right: 1px solid {C["border"]};
    padding: 4px 6px;
    font-size: 8pt;
    font-weight: bold;
}}
QSpinBox {{
    background-color: {C["surface3"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
    padding: 3px 6px;
    font-family: 'Consolas', monospace;
    font-size: 9pt;
}}
QSpinBox:disabled {{
    color: {C["text_muted"]};
    background-color: {C["surface2"]};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {C["border"]};
    width: 16px;
    border-radius: 2px;
}}
QScrollBar:vertical {{
    background: {C["surface2"]};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C["border_hi"]};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QFrame#panel {{
    background-color: {C["surface"]};
    border: 1px solid {C["border"]};
    border-radius: 8px;
}}
QFrame#separator {{
    background-color: {C["border"]};
}}
QFrame#titleBar {{
    background-color: {C["surface"]};
    border-bottom: 1px solid {C["border"]};
}}
QPushButton#titleIconBtn {{
    background-color: {C["surface"]};
    border: none;
    border-radius: 0;
    color: {C["text_dim"]};
    font-size: 14pt;
    padding: 0;
    min-width: 36px;
    min-height: 42px;
}}
QPushButton#titleIconBtn:hover {{
    background-color: {C["surface3"]};
    color: {C["text"]};
}}
QPushButton#titleIconBtn:pressed {{
    background-color: {C["border"]};
}}
QPushButton#navBtn {{
    background-color: {C["surface"]};
    border: none;
    border-radius: 0;
    border-bottom: 2px solid transparent;
    color: {C["text_dim"]};
    font-size: 9pt;
    font-weight: 500;
    padding: 0 12px;
    min-height: 42px;
}}
QPushButton#navBtn:hover {{
    background-color: {C["surface3"]};
    color: {C["text"]};
    border-bottom: 2px solid {C["border_hi"]};
}}
QPushButton#navBtn:checked {{
    background-color: {C["surface2"]};
    color: {C["text"]};
    border-bottom: 2px solid {C["accent"]};
    font-weight: bold;
}}
QPushButton#navBtn:checked:hover {{
    background-color: {C["surface3"]};
}}
QPushButton#winBtnMin, QPushButton#winBtnMax {{
    background-color: {C["surface"]};
    border: none;
    border-radius: 0;
    color: {C["text_dim"]};
    font-size: 11pt;
    padding: 0;
    min-width: 46px;
    min-height: 42px;
}}
QPushButton#winBtnMin:hover, QPushButton#winBtnMax:hover {{
    background-color: {C["surface3"]};
    color: {C["text"]};
}}
QPushButton#winBtnMin:pressed, QPushButton#winBtnMax:pressed {{
    background-color: {C["border"]};
}}
QPushButton#winBtnClose {{
    background-color: {C["surface"]};
    border: none;
    border-radius: 0;
    color: {C["text_dim"]};
    font-size: 11pt;
    padding: 0;
    min-width: 46px;
    min-height: 42px;
}}
QPushButton#winBtnClose:hover {{
    background-color: {C["red"]};
    color: white;
}}
QPushButton#winBtnClose:pressed {{
    background-color: {C["red_dim"]};
    color: white;
}}
QFrame#footer {{
    background-color: {C["surface"]};
    border-top: 1px solid {C["border"]};
}}
QMenu {{
    background-color: {C["surface2"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {C["accent_dim"]};
    color: {C["accent_glow"]};
}}
QToolTip {{
    background-color: {C["surface3"]};
    color: {C["text_dim"]};
    border: 1px solid {C["border"]};
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 8pt;
}}
"""


RESIZE_EDGE = 6   # px from window border that counts as a resize zone

# ═════════════════════════════════════════════
#  CUSTOM TITLE BAR
# ═════════════════════════════════════════════
class CustomTitleBar(QFrame):
    """
    Frameless custom title bar with:
      - Logo + app name + version badge (left)
      - Draggable centre region
      - Status pill + settings placeholder (right)
      - Minimise / Maximise-Restore / Close window buttons (far right)
      - Double-click to maximise/restore
      - Right-click context menu (restore / minimise / maximise / close)
    """

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._win      = parent_window
        self._drag_pos = None
        self.setObjectName("titleBar")
        self.setFixedHeight(42)
        self._build()

    # ── Layout ────────────────────────────────
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(0)

        # — Logo circle —
        logo = QLabel()
        logo.setFixedSize(24, 24)
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(C["accent"])))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 24, 24)
        p.setBrush(QBrush(QColor(C["accent2"])))
        p.drawEllipse(6, 6, 12, 12)
        p.end()
        logo.setPixmap(pix)
        logo.setFixedHeight(42)
        lay.addWidget(logo)

        lay.addSpacing(6)

        # — VS Code-style navigation buttons —
        self._nav_buttons = []
        nav_items = [
            ("Macros",   0),
            ("Vision",   1),
            ("Settings", 2),
            ("Help",     3),
        ]
        for label, page_idx in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setChecked(page_idx == 0)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, idx=page_idx: self._win._switch_page(idx)
            )
            lay.addWidget(btn)
            self._nav_buttons.append(btn)

        # — Stretch (draggable region) —
        lay.addStretch(1)

        # — Window control buttons (minimise / maximise / close) —
        for obj_name, symbol, tip, slot in [
            ("winBtnMin",   "─",  "Minimise",           self._win._handle_minimize_click),
            ("winBtnMax",   "□",  "Maximise / Restore",  self._win._toggle_maximise),
            ("winBtnClose", "✕",  "Close",               self._win.close),
        ]:
            btn = QPushButton(symbol)
            btn.setObjectName(obj_name)
            btn.setFixedSize(46, 42)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def set_active_page(self, idx: int):
        """Update the checked state of nav buttons to reflect the active page."""
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)

    # ── Drag support ──────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() == Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._win._toggle_maximise()
        super().mouseDoubleClickEvent(e)

    # ── Right-click context menu ──────────────
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        act_restore  = menu.addAction("Restore")
        act_min      = menu.addAction("Minimise")
        act_max      = menu.addAction("Maximise")
        menu.addSeparator()
        act_close    = menu.addAction("Close")

        act_restore.setEnabled(self._win.isMaximized() or self._win.isMinimized())
        act_max.setEnabled(not self._win.isMaximized())

        chosen = menu.exec(e.globalPos())
        if chosen == act_restore:
            self._win.showNormal()
        elif chosen == act_min:
            self._win.showMinimized()
        elif chosen == act_max:
            self._win.showMaximized()
        elif chosen == act_close:
            self._win.close()


# ═════════════════════════════════════════════
#  SETTINGS WINDOW
# ═════════════════════════════════════════════
class SettingsWindow(QWidget):
    """
    Standalone settings window for Peniru.
    Covers: colour customisation per UI section, tray behaviour, and misc toggles.
    """
    applied = Signal()   # emitted when the user clicks Apply / OK

    # Each entry is:  (list_of_settings_keys, label, tooltip)
    # When the user picks a colour, it is applied to every key in the list.
    # The first key is also used to read back the *current* colour for the
    # swatch (so combined pickers always display a single representative shade).
    COLOR_SECTIONS = [
        ("🖥  Window & Title Bar", [
            (["gui_bg", "titlebar_bg", "titlebar_border"],
             "Window & Title Bar Background",
             "Main window, title bar and the thin border under it."),
        ]),
        ("🔤  Text & Fonts", [
            (["font_color"],     "Primary Text Colour",
             "Labels, headings, and most visible text."),
            (["font_dim_color"], "Dim / Secondary Text Colour",
             "Subtitles, hints, and less-prominent labels."),
        ]),
        ("🎮  Control & Hotkey Containers", [
            (["ctrl_container_bg", "ctrl_container_border",
              "hk_container_bg",   "hk_container_border"],
             "Container Background & Border",
             "Background and border of the icon-button box and the hotkey box."),
        ]),
        ("🗂  Side Panels (Macro Library & Event Editor)", [
            (["panel_bg", "panel_border"],
             "Panel Background & Border",
             "Background and border of the left and right side panels."),
        ]),
        ("🎨  Icons", [
            (["icon_color"],   "Icon Symbol Colour",
             "Colour of the SVG icons drawn inside the Record / Play buttons."),
            (["icon_box_bg"],  "Icon Button Background",
             "Background of each individual icon button (not the icon itself)."),
        ]),
        ("🔻  Footer Bar", [
            (["footer_bg"], "Footer Background",
             "Background of the narrow status bar at the bottom."),
        ]),
    ]

    def __init__(self, app_window, settings: "Settings", embedded: bool = False):
        super().__init__()
        self._app    = app_window
        self._sett   = settings
        self._embedded = embedded
        # Working copy so Cancel discards changes
        self._draft  = dict(settings.colors)
        self._swatches: dict[str, QPushButton] = {}

        if not embedded:
            self.setWindowTitle("Peniru — Settings")
            self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
            # A wider default + smaller minimum width so the colour-row contents
            # (label + tip + swatch) all fit on one line without horizontal scroll.
            self.setMinimumSize(560, 520)
            self.resize(680, 640)
        self._build()
        if not embedded:
            self._center()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                  (screen.height() - self.height()) // 2)

    # ── Build ──────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {C["bg"]};
                color: {C["text"]};
                font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
                font-size: 10pt;
            }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {C["surface2"]}; width: 7px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {C["border_hi"]}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QFrame#settSection {{
                background-color: {C["surface"]};
                border: 1px solid {C["border"]};
                border-radius: 10px;
            }}
            QPushButton#swatchBtn {{
                border: 2px solid {C["border_hi"]};
                border-radius: 6px;
                min-width: 52px; min-height: 26px;
                max-width: 52px; max-height: 26px;
            }}
            QPushButton#swatchBtn:hover {{
                border-color: {C["accent"]};
            }}
            QPushButton {{
                background-color: {C["surface3"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 9pt;
            }}
            QPushButton:hover {{
                background-color: {C["border_hi"]};
                border-color: {C["accent"]};
            }}
            QPushButton#applyBtn {{
                background-color: {C["accent"]};
                border-color: {C["accent2"]};
                color: white;
                font-weight: bold;
            }}
            QPushButton#applyBtn:hover {{ background-color: {C["accent_glow"]}; }}
            QPushButton#resetBtn {{
                background-color: {C["surface2"]};
                color: {C["text_dim"]};
            }}
            QCheckBox {{
                color: {C["text"]};
                font-size: 9pt;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {C["border_hi"]};
                border-radius: 3px;
                background: {C["surface3"]};
            }}
            QCheckBox::indicator:checked {{
                background-color: {C["accent"]};
                border-color: {C["accent"]};
            }}
        """)

        # ── Header ── (only shown in floating window mode)
        if not self._embedded:
            hdr = QFrame()
            hdr.setFixedHeight(52)
            hdr.setStyleSheet(f"background: {C['surface']}; border-bottom: 1px solid {C['border']};")
            hdr_lay = QHBoxLayout(hdr)
            hdr_lay.setContentsMargins(20, 0, 20, 0)
            title_lbl = QLabel("⚙  Settings")
            title_lbl.setStyleSheet(f"color: {C['text']}; font-size: 13pt; font-weight: bold; background: transparent;")
            hdr_lay.addWidget(title_lbl)
            hdr_lay.addStretch()
            root.addWidget(hdr)

        # ── Scrollable body ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_w = QWidget()
        body_w.setStyleSheet("background: transparent;")
        body_lay = QVBoxLayout(body_w)
        body_lay.setContentsMargins(16, 16, 16, 16)
        body_lay.setSpacing(12)
        scroll.setWidget(body_w)
        root.addWidget(scroll, 1)

        # ── Colour sections ──
        for section_title, items in self.COLOR_SECTIONS:
            self._add_color_section(body_lay, section_title, items)

        # ── Behaviour section ──
        self._add_behaviour_section(body_lay)

        body_lay.addStretch()

        # ── Bottom button bar ──
        btn_bar = QFrame()
        btn_bar.setFixedHeight(54)
        btn_bar.setStyleSheet(f"background: {C['surface']}; border-top: 1px solid {C['border']};")
        btn_lay = QHBoxLayout(btn_bar)
        btn_lay.setContentsMargins(16, 0, 16, 0)
        btn_lay.setSpacing(8)

        reset_btn = QPushButton("↺  Reset All Colours")
        reset_btn.setObjectName("resetBtn")
        reset_btn.clicked.connect(self._reset_colors)
        btn_lay.addWidget(reset_btn)

        btn_lay.addStretch()

        if not self._embedded:
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.close)
            btn_lay.addWidget(cancel_btn)

        ok_label = "Apply" if self._embedded else "Apply & Close"
        ok_btn = QPushButton(ok_label)
        ok_btn.setObjectName("applyBtn")
        if self._embedded:
            ok_btn.clicked.connect(self._apply_embedded)
        else:
            ok_btn.clicked.connect(self._apply_and_close)
        btn_lay.addWidget(ok_btn)

        root.addWidget(btn_bar)

    # ── Colour section builder ─────────────────
    def _add_color_section(self, parent_lay, title, items):
        frame = QFrame()
        frame.setObjectName("settSection")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(0)

        # Section title
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {C['text']}; font-size: 9pt; font-weight: bold; "
            f"background: transparent; padding-bottom: 6px;"
        )
        lay.addWidget(title_lbl)

        for i, (keys, label, tooltip) in enumerate(items):
            # `keys` may be a single string (legacy) or a list of strings.
            # All keys in the list are updated together by the same picker.
            if isinstance(keys, str):
                keys = [keys]
            primary_key = keys[0]

            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {C['border']}; border: none; margin: 2px 0;")
                lay.addWidget(sep)

            row = QHBoxLayout()
            row.setContentsMargins(0, 5, 0, 5)
            row.setSpacing(10)

            # Label – fixed-width-ish, takes only what it needs
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(f"color: {C['text']}; background: transparent; font-size: 9pt;")
            name_lbl.setToolTip(tooltip)
            name_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            row.addWidget(name_lbl, 0)

            # Tip text – stretches with the window so the row auto-fits.
            tip_lbl = QLabel(tooltip)
            tip_lbl.setStyleSheet(f"color: {C['text_muted']}; background: transparent; font-size: 8pt;")
            tip_lbl.setWordWrap(True)
            tip_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(tip_lbl, 1)

            # Swatch – pinned to the right edge
            swatch = QPushButton()
            swatch.setObjectName("swatchBtn")
            swatch.setToolTip(f"Click to change: {label}")
            swatch.setCursor(Qt.PointingHandCursor)
            color_val = self._draft.get(primary_key, "#ffffff")
            swatch.setStyleSheet(
                f"QPushButton#swatchBtn {{ background-color: {color_val}; "
                f"border: 2px solid {C['border_hi']}; border-radius: 6px; }}"
                f"QPushButton#swatchBtn:hover {{ border-color: {C['accent']}; }}"
            )
            # Capture the *list* of keys so the picker updates them all.
            swatch.clicked.connect(lambda checked=False, ks=keys: self._pick_color(ks))
            row.addWidget(swatch, 0)

            # Index every key to the same swatch so a colour change reflects
            # in the UI even if multiple keys map to one picker.
            for k in keys:
                self._swatches[k] = swatch

            lay.addLayout(row)

        parent_lay.addWidget(frame)

    # ── Behaviour section ──────────────────────
    def _add_behaviour_section(self, parent_lay):
        frame = QFrame()
        frame.setObjectName("settSection")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)

        title_lbl = QLabel("🔧  Behaviour & System Tray")
        title_lbl.setStyleSheet(
            f"color: {C['text']}; font-size: 9pt; font-weight: bold; "
            f"background: transparent; padding-bottom: 4px;"
        )
        lay.addWidget(title_lbl)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C['border']}; border: none;")
        lay.addWidget(sep)

        # Hide to tray toggle
        self._tray_check = QCheckBox(
            "Minimise to System Tray  (hide from taskbar when minimised)")
        self._tray_check.setChecked(self._sett.hide_in_tray)
        self._tray_check.setToolTip(
            "When enabled, clicking Minimise hides the window to the tray icon "
            "instead of keeping it in the taskbar.")
        lay.addWidget(self._tray_check)

        # Start minimised toggle
        self._startmin_check = QCheckBox("Start minimised to tray on launch")
        self._startmin_check.setChecked(self._sett.start_minimized)
        self._startmin_check.setToolTip(
            "When enabled, the app window opens hidden in the tray on startup.")
        lay.addWidget(self._startmin_check)

        note = QLabel(
            "ℹ  Double-click the tray icon to restore the window at any time.")
        note.setStyleSheet(
            f"color: {C['text_muted']}; font-size: 8pt; background: transparent;")
        lay.addWidget(note)

        parent_lay.addWidget(frame)

    # ── Colour picker ──────────────────────────
    def _pick_color(self, keys):
        """Pick a colour and apply it to every settings key in `keys`."""
        if isinstance(keys, str):
            keys = [keys]
        primary_key = keys[0]
        initial = QColor(self._draft.get(primary_key, "#ffffff"))
        chosen  = QColorDialog.getColor(
            initial, self, f"Choose colour")
        if not chosen.isValid():
            return
        hex_val = chosen.name()
        # Update draft for every linked key
        for k in keys:
            self._draft[k] = hex_val
        # Refresh the swatch button (one swatch shared across all linked keys)
        swatch = self._swatches[primary_key]
        swatch.setStyleSheet(
            f"QPushButton#swatchBtn {{ background-color: {hex_val}; "
            f"border: 2px solid {C['border_hi']}; border-radius: 6px; }}"
            f"QPushButton#swatchBtn:hover {{ border-color: {C['accent']}; }}"
        )

    # ── Reset ──────────────────────────────────
    def _reset_colors(self):
        self._sett._init_colors()
        self._draft = dict(self._sett.colors)
        # Refresh swatches – iterate over unique swatch buttons (since several
        # keys may point to the same swatch in the combined-picker layout).
        seen = set()
        for key, swatch in self._swatches.items():
            if id(swatch) in seen:
                continue
            seen.add(id(swatch))
            color_val = self._draft.get(key, "#ffffff")
            swatch.setStyleSheet(
                f"QPushButton#swatchBtn {{ background-color: {color_val}; "
                f"border: 2px solid {C['border_hi']}; border-radius: 6px; }}"
                f"QPushButton#swatchBtn:hover {{ border-color: {C['accent']}; }}"
            )

    # ── Apply ──────────────────────────────────
    def _apply_embedded(self):
        """Apply settings without closing (for embedded/page mode)."""
        self._sett.colors.update(self._draft)
        self._sett.hide_in_tray    = self._tray_check.isChecked()
        self._sett.start_minimized = self._startmin_check.isChecked()
        self._sett.save()
        self.applied.emit()

    def _apply_and_close(self):
        self._sett.colors.update(self._draft)
        self._sett.hide_in_tray    = self._tray_check.isChecked()
        self._sett.start_minimized = self._startmin_check.isChecked()
        self._sett.save()
        self.applied.emit()
        self.close()


# ═════════════════════════════════════════════
#  MAIN APPLICATION (PySide6 GUI)
# ═════════════════════════════════════════════
class PeniruApp(QMainWindow):

    def __init__(self):
        super().__init__()
        # Core modules
        self.recorder = Recorder()
        self.player   = Player()
        self.manager  = MacroManager()
        self.settings = Settings()
        self.hotkeys  = HotkeyDaemon(self.settings)
        self.signals  = AppSignals()

        # State
        self.current_events = []
        self.current_macro  = None
        self._speed_idx     = 1
        self._loop_mode     = "once"
        self._loop_count    = 1
        self._humanize      = False
        self._rebinding_action = None

        # Icon button state
        self._icon_color = ICON_COLOR   # global icon colour, changed via _set_icon_color()
        self._icon_btns  = []           # list of all icon buttons for batch colour updates

        # Track currently-applied "live" colours so that subsequent settings
        # changes can string-replace them in widget stylesheets.
        # These start at the original palette values and follow user changes.
        self._applied_text_color = C["text"]
        self._applied_dim_color  = C["text_dim"]
        self._applied_icon_box_bg = C["surface3"]

        # Edge-resize state
        self._rz_dir        = None   # active direction, e.g. "br", "r", "t" …
        self._rz_start_pos  = None   # QPoint – global cursor position at drag start
        self._rz_start_geom = None   # QRect  – window geometry at drag start
        self._rz_cursor_set = False  # whether we pushed an override cursor

        # Timers
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._do_poll_recording)

        # Connect cross-thread signals
        self.signals.status_changed.connect(self._apply_status)
        self.signals.events_updated.connect(self._refresh_event_editor)
        self.signals.play_finished.connect(self._on_play_done)
        self.signals.hotkey_triggered.connect(self._dispatch_hotkey)

        self._build_ui()
        self._wire_hotkeys()
        self.hotkeys.start()
        self._setup_tray()

        # Apply any saved colour customisations from disk so the user's last
        # choices show up immediately on launch (instead of only after they
        # re-open Settings and click Apply).
        try:
            self._apply_settings()
        except Exception as e:
            print(f"[PeniruApp] Initial settings apply failed: {e}")

        # Install application-level mouse filter AFTER everything is built
        # so the app instance is fully initialised.
        QApplication.instance().installEventFilter(self)

    # ─────────────────────────────────────────
    # WINDOW SETUP
    # ─────────────────────────────────────────
    def _build_ui(self):
        # Remove the native OS frame – we draw our own title bar
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)
        self.setMinimumSize(820, 600)
        self._center_window()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top accent stripe
        accent = QFrame()
        accent.setFixedHeight(2)
        accent.setStyleSheet(f"background-color: {C['accent']}; border: none;")
        root_layout.addWidget(accent)

        self._build_titlebar(root_layout)
        self._build_body(root_layout)
        self._build_footer(root_layout)

    def _center_window(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width()  - 1000) // 2
        y = (screen.height() - 700)  // 2
        self.move(x, y)

    # ─────────────────────────────────────────
    # TITLE BAR
    # ─────────────────────────────────────────
    def _build_titlebar(self, parent_layout):
        self._title_bar = CustomTitleBar(self)
        parent_layout.addWidget(self._title_bar)

        # Thin separator line below the title bar
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {C['border']}; border: none;")
        parent_layout.addWidget(sep)

    def _toggle_maximise(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ─────────────────────────────────────────
    # BODY (paged stacked widget)
    # ─────────────────────────────────────────
    def _build_body(self, parent_layout):
        self._page_stack = QStackedWidget()

        # ── Page 0: Macros ──
        macros_page = QWidget()
        macros_layout = QHBoxLayout(macros_page)
        macros_layout.setContentsMargins(10, 10, 10, 10)
        macros_layout.setSpacing(8)
        self._build_left_panel(macros_layout)
        self._build_center_panel(macros_layout)
        self._build_right_panel(macros_layout)
        self._page_stack.addWidget(macros_page)   # index 0

        # ── Page 1: Vision (blank) ──
        self._page_stack.addWidget(
            self._build_blank_page("Vision", "👁", "Vision features coming soon.")
        )  # index 1

        # ── Page 2: Settings (embedded) ──
        self._embedded_settings = SettingsWindow(self, self.settings, embedded=True)
        self._embedded_settings.applied.connect(self._apply_settings)
        self._page_stack.addWidget(self._embedded_settings)  # index 2

        # ── Page 3: Help (blank) ──
        self._page_stack.addWidget(
            self._build_blank_page("Help", "❓", "Help documentation coming soon.")
        )  # index 3

        parent_layout.addWidget(self._page_stack, 1)

    def _build_blank_page(self, title: str, icon: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            f"color: {C['text_muted']}; font-size: 52pt; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {C['text_dim']}; font-size: 20pt; font-weight: bold; background: transparent;")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet(
            f"color: {C['text_muted']}; font-size: 10pt; background: transparent;")
        msg_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg_lbl)

        return page

    def _switch_page(self, idx: int):
        """Switch the main content area to the given page index."""
        self._page_stack.setCurrentIndex(idx)
        if hasattr(self, "_title_bar"):
            self._title_bar.set_active_page(idx)

    # ── LEFT: Macro Library ───────────────────
    def _build_left_panel(self, parent_layout):
        pane = self._panel(220)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._section_header(layout, "MACRO LIBRARY")

        self.macro_list = QListWidget()
        self.macro_list.setAlternatingRowColors(True)
        self.macro_list.itemDoubleClicked.connect(lambda: self._load_macro())
        layout.addWidget(self.macro_list, 1)

        for label, fn in [("Save", self._save_macro),
                           ("Load", self._load_macro),
                           ("Delete", self._delete_macro)]:
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            layout.addWidget(btn)

        self._refresh_macro_list()
        parent_layout.addWidget(pane)

    # ── CENTER: Controls ──────────────────────
    def _build_center_panel(self, parent_layout):
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        # ── Side-by-side containers row ────────
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignTop)

        self._build_control_container(row)
        self._build_hotkey_container(row)

        layout.addLayout(row)

        sep = self._separator()
        layout.addWidget(sep)

        # Controls grid
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        # Speed
        grid.addWidget(self._dim_label("Playback Speed"), 0, 0)
        self._speed_group = QButtonGroup(self)
        self._speed_group.setExclusive(True)
        speed_buttons = []
        for i, lbl in enumerate(SPEED_LABELS):
            btn = QPushButton(lbl)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setChecked(i == self._speed_idx)
            btn.setCursor(Qt.PointingHandCursor)
            btn.toggled.connect(lambda checked, idx=i: self._on_speed_change(idx) if checked else None)
            self._speed_group.addButton(btn, i)
            speed_buttons.append(btn)

        spd_inner = QWidget()
        spd_inner.setObjectName("segCtl")
        inner_lay = QHBoxLayout(spd_inner)
        inner_lay.setContentsMargins(3, 3, 3, 3)
        inner_lay.setSpacing(2)
        for btn in speed_buttons:
            inner_lay.addWidget(btn)

        spd_w = QWidget()
        outer_lay = QHBoxLayout(spd_w)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.addWidget(spd_inner)
        outer_lay.addStretch()
        grid.addWidget(spd_w, 0, 1)

        # Loop mode
        grid.addWidget(self._dim_label("Loop Mode"), 1, 0)
        self._loop_group = QButtonGroup(self)
        self._loop_group.setExclusive(True)
        loop_buttons = []
        for val, lbl in [("once", "Once"), ("infinite", "∞ Loop"), ("custom", "Custom")]:
            btn = QPushButton(lbl)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setChecked(val == self._loop_mode)
            btn.setCursor(Qt.PointingHandCursor)
            btn.toggled.connect(lambda checked, v=val: self._on_loop_change(v) if checked else None)
            self._loop_group.addButton(btn)
            loop_buttons.append(btn)

        loop_inner = QWidget()
        loop_inner.setObjectName("segCtlLoop")
        loop_inner_lay = QHBoxLayout(loop_inner)
        loop_inner_lay.setContentsMargins(3, 3, 3, 3)
        loop_inner_lay.setSpacing(2)
        for btn in loop_buttons:
            loop_inner_lay.addWidget(btn)

        self._loop_spin = QSpinBox()
        self._loop_spin.setRange(1, 9999)
        self._loop_spin.setValue(self._loop_count)
        self._loop_spin.setEnabled(False)
        self._loop_spin.setFixedWidth(65)
        self._loop_spin.valueChanged.connect(lambda v: setattr(self, "_loop_count", v))

        loop_w = QWidget()
        loop_outer_lay = QHBoxLayout(loop_w)
        loop_outer_lay.setContentsMargins(0, 0, 0, 0)
        loop_outer_lay.setSpacing(8)
        loop_outer_lay.addWidget(loop_inner)
        loop_outer_lay.addWidget(self._loop_spin)
        loop_outer_lay.addStretch()
        grid.addWidget(loop_w, 1, 1)

        # Humanisation
        grid.addWidget(self._dim_label("Humanisation"), 2, 0)
        self._human_btn = QPushButton("OFF")
        self._human_btn.setCheckable(True)
        self._human_btn.setFixedWidth(60)
        self._human_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {C["surface3"]}; color: {C["text_dim"]};
                          font-weight: bold; font-family: Consolas; border-radius: 4px; }}
            QPushButton:checked {{ background-color: {C["accent"]}; color: {C["text"]}; }}
        """)
        self._human_btn.toggled.connect(self._on_humanize_toggle)
        grid.addWidget(self._human_btn, 2, 1, Qt.AlignLeft)

        layout.addLayout(grid)

        layout.addStretch()
        parent_layout.addWidget(pane, 1)

    def _big_btn(self, text, fn, base_color=None, active_color=None, press_color=None):
        """
        Create a chunky action button.
          base_color   : default (idle) background — defaults to grey surface3
          active_color : optional, applied via _set_btn_active(True)
          press_color  : background while mouse is held down (purely visual feedback)
        """
        btn = QPushButton(text)
        btn.setObjectName("bigBtn")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn._base_color   = base_color   or C["surface3"]
        btn._active_color = active_color
        btn._press_color  = press_color  or C["accent_dim"]
        self._apply_btn_style(btn, active=False)
        btn.clicked.connect(fn)
        return btn

    # ─────────────────────────────────────────
    # ICON CONTROL CONTAINER
    # ─────────────────────────────────────────
    def _build_control_container(self, parent_layout):
        """
        One rounded outer container holding four square icon buttons in a 2×2 grid.
        """
        outer = QFrame()
        outer.setObjectName("ctrlContainer")
        outer.setStyleSheet(f"""
            QFrame#ctrlContainer {{
                background-color: {C["surface2"]};
                border: 1px solid {C["border"]};
                border-radius: 16px;
            }}
        """)

        outer_layout = QGridLayout(outer)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(8)

        self._rec_btn   = self._icon_btn("record",    "Start Recording",  self._start_recording,
                                          active_bg=C["red_dim"],   press_bg="#7a2020")
        self._stop_rec  = self._icon_btn("stop_rec",  "Stop Recording",   self._stop_recording,
                                          press_bg="#3a1515")
        self._play_btn  = self._icon_btn("play",      "Play Macro",       self._play_macro,
                                          active_bg=C["green_dim"], press_bg="#1f6644")
        self._stop_play = self._icon_btn("stop_play", "Stop Playback",    self._stop_playback,
                                          press_bg=C["accent_dim"])

        outer_layout.addWidget(self._rec_btn,   0, 0)
        outer_layout.addWidget(self._stop_rec,  0, 1)
        outer_layout.addWidget(self._play_btn,  1, 0)
        outer_layout.addWidget(self._stop_play, 1, 1)

        self._ctrl_container = outer
        parent_layout.addWidget(outer)

    def _build_hotkey_container(self, parent_layout):
        """
        Rounded container beside the control container, showing hotkey assignments.
        Stretches to fill the remaining horizontal space.
        """
        outer = QFrame()
        outer.setObjectName("hotkeyContainer")
        outer.setStyleSheet(f"""
            QFrame#hotkeyContainer {{
                background-color: {C["surface2"]};
                border: 1px solid {C["border"]};
                border-radius: 16px;
            }}
        """)
        outer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        inner = QVBoxLayout(outer)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(6)

        self._hk_buttons = {}
        actions = [
            ("start_record", "Start Rec"),
            ("stop_record",  "Stop Rec"),
            ("play_macro",   "Play"),
            ("stop_play",    "Stop"),
            ("emergency",    "Emergency"),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)

        for row_i, (action, label) in enumerate(actions):
            lbl = self._dim_label(label)
            grid.addWidget(lbl, row_i, 0)

            btn = QPushButton(self.settings.hotkeys[action].upper())
            btn.setObjectName("hotkeyBtn")
            btn.setToolTip("Click to change")
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked=False, a=action: self._rebind_hotkey(a))
            grid.addWidget(btn, row_i, 1)
            self._hk_buttons[action] = btn

        inner.addLayout(grid)

        self._hk_container = outer
        parent_layout.addWidget(outer, 1)   # stretch=1 so it fills leftover space

    def _icon_btn(self, icon_type: str, tooltip: str, fn,
                  active_bg: str = None, press_bg: str = None):
        """Create a square icon-only button inside its own rounded box."""
        btn = QPushButton()
        btn.setFixedSize(68, 68)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        # Custom attributes
        btn._icon_type  = icon_type
        btn._base_bg    = C["surface3"]
        btn._active_bg  = active_bg
        btn._press_bg   = press_bg or C["accent_dim"]
        btn._press_color = press_bg or C["accent_dim"]   # compat with _flash_btn_press
        btn.setStyleSheet(self._icon_btn_style(C["surface3"]))
        self._update_btn_icon(btn)
        btn.clicked.connect(fn)
        self._icon_btns.append(btn)
        return btn

    def _icon_btn_style(self, bg: str) -> str:
        """Return a stylesheet string for a square rounded-corner icon button."""
        return f"""
            QPushButton {{
                background-color: {bg};
                border-radius: 12px;
                border: 1px solid {C["border_hi"]};
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {self._lighter(bg, 18)};
                border-color: {C["accent"]};
            }}
            QPushButton:pressed {{
                background-color: {self._lighter(bg, -12)};
                border-color: {C["accent2"]};
            }}
        """

    def _make_icon_pixmap(self, icon_type: str, color: str, size: int = 34) -> QPixmap:
        """Draw and return a QPixmap for the given icon type in the given colour."""
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        c  = QColor(color)
        m  = size * 0.16          # margin
        s  = size - 2.0 * m       # drawable size
        cx = size / 2.0
        cy = size / 2.0

        if icon_type == "record":
            # Filled circle (record dot)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            r = s * 0.40
            p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        elif icon_type == "stop_rec":
            # Filled square (stop) with a tiny circle in top-right corner
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            sq = s * 0.75
            p.drawRoundedRect(int(cx - sq / 2), int(cy - sq / 2),
                               int(sq), int(sq), 4, 4)
            # Small accent dot (record indicator)
            dot_r = size * 0.10
            dot_x = cx + sq / 2 - dot_r * 0.3
            dot_y = cy - sq / 2 - dot_r * 0.3
            p.setBrush(QBrush(QColor(C["red"])))
            p.drawEllipse(int(dot_x - dot_r), int(dot_y - dot_r),
                           int(dot_r * 2), int(dot_r * 2))

        elif icon_type == "play":
            # Right-pointing filled triangle (play)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            x0 = m + s * 0.10
            triangle = QPolygonF([
                QPointF(x0,          m),
                QPointF(x0,          m + s),
                QPointF(m + s * 0.90, cy),
            ])
            p.drawPolygon(triangle)

        elif icon_type == "stop_play":
            # Two vertical bars (pause)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            bw  = s * 0.22
            gap = s * 0.18
            x1  = cx - bw - gap / 2
            x2  = cx + gap / 2
            for bx in (x1, x2):
                p.drawRoundedRect(int(bx), int(m), int(bw), int(s), 3, 3)

        elif icon_type == "emergency":
            # Power-off symbol: arc + vertical line
            pen = QPen(c, size * 0.085)
            pen.setCapStyle(Qt.RoundCap)
            p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            r = s * 0.38
            # Arc — open at top (starts at ~40°, spans 280°)
            p.drawArc(int(cx - r), int(cy - r),
                       int(r * 2), int(r * 2),
                       50 * 16, 260 * 16)
            # Vertical line from centre upward
            line_top = cy - r * 0.95
            line_bot = cy - r * 0.15
            p.drawLine(int(cx), int(line_top), int(cx), int(line_bot))

        p.end()
        return pix

    def _update_btn_icon(self, btn):
        """Re-render and apply the icon for an icon button using the current icon colour."""
        pix  = self._make_icon_pixmap(btn._icon_type, self._icon_color)
        icon = QIcon(pix)
        btn.setIcon(icon)
        btn.setIconSize(QSize(34, 34))

    def _set_icon_color(self, color: str):
        """Change the colour of every icon button's icon globally."""
        self._icon_color = color
        for btn in self._icon_btns:
            self._update_btn_icon(btn)

    def _pick_icon_color(self):
        """Open a colour picker and apply the chosen colour to all icons."""
        initial = QColor(self._icon_color)
        chosen  = QColorDialog.getColor(initial, self, "Choose Icon Colour")
        if chosen.isValid():
            self._set_icon_color(chosen.name())

    def _apply_btn_style(self, btn, active: bool):
        """Repaint the button for its current state (idle vs active)."""
        bg = btn._active_color if (active and btn._active_color) else btn._base_color
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {C["text"]};
                font-size: 10pt;
                font-weight: bold;
                padding: 12px 8px;
                border-radius: 6px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {self._lighter(bg, 22)};
            }}
            QPushButton:pressed {{
                background-color: {btn._press_color};
            }}
            QPushButton:disabled {{
                color: {C["text_muted"]};
                background-color: {C["surface2"]};
            }}
        """)

    def _set_btn_active(self, btn, active: bool):
        """Toggle a button between its idle and active colour."""
        if hasattr(btn, '_icon_type'):
            # Icon button — change box background colour
            bg = (btn._active_bg if (active and btn._active_bg) else btn._base_bg)
            btn.setStyleSheet(self._icon_btn_style(bg))
        else:
            self._apply_btn_style(btn, active)

    @staticmethod
    def _lighter(hex_color: str, amount: int) -> str:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return "#{:02x}{:02x}{:02x}".format(
            max(0, min(255, r + amount)),
            max(0, min(255, g + amount)),
            max(0, min(255, b + amount)),
        )

    # ── RIGHT: Event Editor ───────────────────
    def _build_right_panel(self, parent_layout):
        pane = self._panel(240)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._section_header(layout, "EVENT EDITOR")

        self.event_tree = QTreeWidget()
        self.event_tree.setColumnCount(3)
        self.event_tree.setHeaderLabels(["#", "Type", "Delay (ms)"])
        self.event_tree.setAlternatingRowColors(True)
        self.event_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.event_tree.setRootIsDecorated(False)
        self.event_tree.header().setDefaultSectionSize(70)
        self.event_tree.setColumnWidth(0, 32)
        self.event_tree.setColumnWidth(1, 130)
        self.event_tree.setColumnWidth(2, 70)
        self.event_tree.itemDoubleClicked.connect(self._on_event_double_click)
        layout.addWidget(self.event_tree, 1)

        for label, fn in [("Refresh Events", self._refresh_event_editor),
                           ("Clear",          self._clear_events)]:
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            layout.addWidget(btn)

        parent_layout.addWidget(pane)

    # ── FOOTER ────────────────────────────────
    def _build_footer(self, parent_layout):
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(36)
        self._footer = footer
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 0, 16, 0)

        left = QLabel(f"Peniru  ·  v{APP_VERSION}  ·  {APP_DEV}")
        left.setStyleSheet(f"color: {C['text_muted']}; font-size: 8pt; background: transparent;")
        layout.addWidget(left)

        layout.addStretch()

        # Status indicator (bottom-right)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color: {C['idle']}; font-size: 12pt; background: transparent; padding-right: 6px;"
        )
        layout.addWidget(self._status_dot)

        self._status_label = QLabel("Idle")
        self._status_label.setStyleSheet(
            f"color: {C['text_dim']}; font-size: 10pt; font-weight: bold; background: transparent;"
        )
        layout.addWidget(self._status_label)

        parent_layout.addWidget(footer)

    # ── HOTKEY CONFIG SECTION ─────────────────
    def _build_hotkey_section(self, parent_layout):
        self._hk_buttons = {}
        actions = [
            ("start_record", "Start Rec"),
            ("stop_record",  "Stop Rec"),
            ("play_macro",   "Play"),
            ("stop_play",    "Stop"),
            ("emergency",    "Emergency"),
        ]
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        for row_i, (action, label) in enumerate(actions):
            lbl = self._dim_label(label)
            grid.addWidget(lbl, row_i, 0)

            btn = QPushButton(self.settings.hotkeys[action].upper())
            btn.setObjectName("hotkeyBtn")
            btn.setToolTip("Click to change")
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked=False, a=action: self._rebind_hotkey(a))
            grid.addWidget(btn, row_i, 1)
            self._hk_buttons[action] = btn

        w = QWidget()
        w.setLayout(grid)
        parent_layout.addWidget(w)

    # ─────────────────────────────────────────
    # WIDGET HELPERS
    # ─────────────────────────────────────────
    def _panel(self, min_width=None):
        f = QFrame()
        f.setObjectName("panel")
        if min_width:
            f.setMinimumWidth(min_width)
            f.setMaximumWidth(min_width + 60)
        return f

    def _section_header(self, layout, text):
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 4, 0, 2)

        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background-color: {C['accent']}; border-radius: 2px;")
        row.addWidget(bar)

        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 8pt; font-weight: bold; background: transparent;")
        row.addWidget(lbl)
        row.addStretch()

        layout.addLayout(row)

        sep = self._separator()
        layout.addWidget(sep)

    def _separator(self):
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {C['border']}; border: none;")
        return sep

    def _dim_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 9pt; background: transparent;")
        return lbl

    # ─────────────────────────────────────────
    # SETTINGS WINDOW
    # ─────────────────────────────────────────
    def _open_settings(self):
        if hasattr(self, "_settings_win") and self._settings_win.isVisible():
            self._settings_win.raise_()
            self._settings_win.activateWindow()
            return
        self._settings_win = SettingsWindow(self, self.settings)
        self._settings_win.applied.connect(self._apply_settings)
        self._settings_win.show()

    def _apply_settings(self):
        """Re-apply all colours from settings.colors to the live UI."""
        sc = self.settings.colors

        # ── Control container ──
        if hasattr(self, "_ctrl_container"):
            self._ctrl_container.setStyleSheet(f"""
                QFrame#ctrlContainer {{
                    background-color: {sc['ctrl_container_bg']};
                    border: 1px solid {sc['ctrl_container_border']};
                    border-radius: 16px;
                }}
            """)

        # ── Hotkey container ──
        if hasattr(self, "_hk_container"):
            self._hk_container.setStyleSheet(f"""
                QFrame#hotkeyContainer {{
                    background-color: {sc['hk_container_bg']};
                    border: 1px solid {sc['hk_container_border']};
                    border-radius: 16px;
                }}
            """)

        # ── Title bar ──
        if hasattr(self, "_title_bar"):
            tb_bg = sc.get("titlebar_bg", C["surface"])
            tb_border = sc.get("titlebar_border", C["border"])
            self._title_bar.setStyleSheet(f"""
                QFrame#titleBar {{
                    background-color: {tb_bg};
                    border-bottom: 1px solid {tb_border};
                }}
                QPushButton#winBtnMin, QPushButton#winBtnMax {{
                    background-color: {tb_bg};
                    color: {C["text_dim"]};
                    border: none;
                    border-radius: 0;
                    font-size: 11pt;
                    padding: 0;
                    min-width: 46px;
                    min-height: 42px;
                }}
                QPushButton#winBtnMin:hover, QPushButton#winBtnMax:hover {{
                    background-color: {C["surface3"]};
                    color: {C["text"]};
                }}
                QPushButton#winBtnMin:pressed, QPushButton#winBtnMax:pressed {{
                    background-color: {C["border"]};
                }}
                QPushButton#winBtnClose {{
                    background-color: {tb_bg};
                    color: {C["text_dim"]};
                    border: none;
                    border-radius: 0;
                    font-size: 11pt;
                    padding: 0;
                    min-width: 46px;
                    min-height: 42px;
                }}
                QPushButton#winBtnClose:hover {{
                    background-color: {C["red"]};
                    color: white;
                }}
                QPushButton#winBtnClose:pressed {{
                    background-color: {C["red_dim"]};
                    color: white;
                }}
                QPushButton#navBtn {{
                    background-color: {tb_bg};
                    border: none;
                    border-radius: 0;
                    border-bottom: 2px solid transparent;
                    color: {C["text_dim"]};
                    font-size: 9pt;
                    font-weight: 500;
                    padding: 0 12px;
                    min-height: 42px;
                }}
                QPushButton#navBtn:hover {{
                    background-color: {C["surface3"]};
                    color: {C["text"]};
                    border-bottom: 2px solid {C["border_hi"]};
                }}
                QPushButton#navBtn:checked {{
                    background-color: {C["surface2"]};
                    color: {C["text"]};
                    border-bottom: 2px solid {C["accent"]};
                    font-weight: bold;
                }}
                QPushButton#navBtn:checked:hover {{
                    background-color: {C["surface3"]};
                }}
            """)

        # ── Footer ──
        if hasattr(self, "_footer"):
            self._footer.setStyleSheet(
                f"QFrame#footer {{ background-color: {sc['footer_bg']}; "
                f"border-top: 1px solid {sc['panel_border']}; }}"
            )

        # ── Central widget / window background ──
        if self.centralWidget():
            self.centralWidget().setStyleSheet(
                f"QWidget {{ background-color: {sc['gui_bg']}; }}"
            )

        # ── Icon symbol colour ──
        self._set_icon_color(sc["icon_color"])

        # ── Icon button background colour ──
        new_icon_bg = sc.get("icon_box_bg", C["surface3"])
        for btn in self._icon_btns:
            btn._base_bg = new_icon_bg
            is_active = (
                (btn is getattr(self, "_rec_btn",  None) and self.recorder.is_recording) or
                (btn is getattr(self, "_play_btn", None) and self.player.is_playing)
            )
            self._set_btn_active(btn, is_active)
        self._applied_icon_box_bg = new_icon_bg

        # ── Side panels — re-style via objectName ──
        for child in self.findChildren(QFrame, "panel"):
            child.setStyleSheet(
                f"QFrame#panel {{ background-color: {sc['panel_bg']}; "
                f"border: 1px solid {sc['panel_border']}; border-radius: 8px; }}"
            )

        # ── Font colours – primary text + dim text ──
        # We do this by string-replacing the *previously applied* colour with
        # the new one in every label's inline stylesheet. This works no matter
        # how many times the user changes the colours.
        old_text = self._applied_text_color
        old_dim  = self._applied_dim_color
        new_text = sc.get("font_color",     C["text"])
        new_dim  = sc.get("font_dim_color", C["text_dim"])

        if old_text != new_text or old_dim != new_dim:
            for child in self.findChildren(QLabel):
                ss = child.styleSheet()
                if not ss:
                    continue
                new_ss = ss
                if old_text != new_text:
                    new_ss = new_ss.replace(
                        f"color: {old_text}", f"color: {new_text}")
                if old_dim != new_dim:
                    new_ss = new_ss.replace(
                        f"color: {old_dim}",  f"color: {new_dim}")
                if new_ss != ss:
                    child.setStyleSheet(new_ss)
            # Status label (footer) is updated dynamically via _apply_status,
            # so we also nudge it now to use the new dim colour as its base.
            if hasattr(self, "_status_label"):
                self._status_label.setStyleSheet(
                    f"color: {new_dim}; font-size: 10pt; "
                    f"font-weight: bold; background: transparent;"
                )
            self._applied_text_color = new_text
            self._applied_dim_color  = new_dim

    # ─────────────────────────────────────────
    # TRAY MINIMISE SUPPORT
    # ─────────────────────────────────────────
    def _handle_minimize_click(self):
        """
        Click handler for the title-bar minimise button.

        If the user has 'Minimise to System Tray' enabled, we bypass the
        normal showMinimized() path entirely and just hide() the window.
        Hiding (as opposed to minimising) removes the entry from the OS
        taskbar, leaving only the tray icon — which is what the user expects.
        """
        if self.settings.hide_in_tray and hasattr(self, "_tray"):
            self.hide()
            try:
                self._tray.showMessage(
                    "Peniru", "Minimised to tray. Double-click the icon to restore.",
                    QSystemTrayIcon.Information, 2000
                )
            except Exception:
                pass
        else:
            self.showMinimized()

    def changeEvent(self, event):
        """
        Catch any *other* path that minimises the window (Win+D, system menu,
        a left-click on the taskbar icon, etc.) and re-route it to the tray
        when 'Minimise to System Tray' is enabled.

        We restore the window state to Normal (so when it's shown again it
        isn't still minimised) and then hide it, which removes the taskbar
        entry entirely.
        """
        from PySide6.QtCore import QEvent as _QE
        if (event.type() == _QE.WindowStateChange
                and self.isMinimized()
                and self.settings.hide_in_tray
                and hasattr(self, "_tray")):
            # Defer to next event-loop tick so Qt finishes the state change
            # before we override it. Without the QTimer we can leave the
            # taskbar entry behind on some platforms.
            QTimer.singleShot(0, self._hide_to_tray_from_minimised)
            return
        super().changeEvent(event)

    def _hide_to_tray_from_minimised(self):
        """Move from minimised → fully hidden (no taskbar entry)."""
        # Un-minimise first so the window's restored state is Normal,
        # otherwise the next show() would re-display it as minimised.
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.hide()
        if hasattr(self, "_tray"):
            try:
                self._tray.showMessage(
                    "Peniru", "Minimised to tray. Double-click the icon to restore.",
                    QSystemTrayIcon.Information, 2000
                )
            except Exception:
                pass

    # ─────────────────────────────────────────
    # SYSTEM TRAY
    # ─────────────────────────────────────────
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(C["accent"])))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, 28, 28)
        p.end()

        self._tray = QSystemTrayIcon(QIcon(pix), self)
        menu = QMenu()
        menu.addAction("Show / Restore", self._restore_from_tray)
        menu.addSeparator()
        menu.addAction("Settings", self._open_settings)
        menu.addSeparator()
        menu.addAction("Exit", self.close)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.DoubleClick else None)
        self._tray.show()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ─────────────────────────────────────────
    # HOTKEY DAEMON WIRING
    # ─────────────────────────────────────────
    def _wire_hotkeys(self):
        # Emit a signal from the pynput thread; _dispatch_hotkey runs on the
        # main thread via Qt's AutoConnection (QueuedConnection cross-thread).
        # Do NOT use QTimer.singleShot here — pynput's listener is a plain
        # Python thread with no Qt event loop, so the timer silently never fires.
        for action in ("start_record", "stop_record", "play_macro",
                       "stop_play", "emergency"):
            self.hotkeys.set_callback(
                action,
                lambda a=action: self.signals.hotkey_triggered.emit(a)
            )

    _HOTKEY_ACTIONS = {
        "start_record": "_start_recording",
        "stop_record":  "_stop_recording",
        "play_macro":   "_play_macro",
        "stop_play":    "_stop_playback",
        "emergency":    "_emergency_stop",
    }

    _HOTKEY_BUTTONS = {
        "start_record": "_rec_btn",
        "stop_record":  "_stop_rec",
        "play_macro":   "_play_btn",
        "stop_play":    "_stop_play",
    }

    def _dispatch_hotkey(self, action: str):
        """Called on the main thread when a hotkey is pressed."""
        # Flash the corresponding button so hotkey presses look identical
        # to manual button clicks (brief press-colour highlight).
        btn_attr = self._HOTKEY_BUTTONS.get(action)
        if btn_attr and hasattr(self, btn_attr):
            self._flash_btn_press(getattr(self, btn_attr))

        method_name = self._HOTKEY_ACTIONS.get(action)
        if method_name:
            getattr(self, method_name)()

    def _flash_btn_press(self, btn, duration_ms: int = 150):
        """Briefly show a button's press colour (hotkey visual feedback)."""
        if hasattr(btn, '_icon_type'):
            # Icon button: flash the press background then restore
            btn.setStyleSheet(self._icon_btn_style(btn._press_bg))
            QTimer.singleShot(
                duration_ms,
                lambda b=btn: self._set_btn_active(
                    b,
                    (b is self._rec_btn  and self.recorder.is_recording) or
                    (b is self._play_btn and self.player.is_playing)
                )
            )
        elif hasattr(btn, '_press_color'):
            # _big_btn: override with press colour, then restore proper active state
            pc = btn._press_color
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {pc};
                    color: {C["text"]};
                    font-size: 10pt; font-weight: bold;
                    padding: 12px 8px;
                    border-radius: 6px; border: none;
                }}
            """)
            QTimer.singleShot(
                duration_ms,
                lambda b=btn: self._apply_btn_style(
                    b,
                    (b is self._rec_btn  and self.recorder.is_recording) or
                    (b is self._play_btn and self.player.is_playing)
                )
            )

    # ─────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────
    def _set_status(self, text, color=None):
        # Safe to call from any thread
        self.signals.status_changed.emit(text, color or C["idle"])

    def _apply_status(self, text, color):
        self._status_label.setText(text)
        self._status_dot.setStyleSheet(
            f"color: {color}; font-size: 12pt; background: transparent; padding-right: 6px;")

    # ─────────────────────────────────────────
    # RECORDER ACTIONS
    # ─────────────────────────────────────────
    def _start_recording(self):
        if self.recorder.is_recording:
            return
        if self.player.is_playing:
            self._set_status("Busy – Stop playback first", C["yellow"])
            return
        self.current_events = []
        self.recorder.start()
        self._set_status("Recording…", C["recording"])
        self._set_btn_active(self._rec_btn, True)      # turn red
        self._poll_timer.start(300)

    def _do_poll_recording(self):
        if self.recorder.is_recording:
            n = len(self.recorder.events)
            self._set_status(f"Recording… {n} events", C["recording"])
        else:
            self._poll_timer.stop()

    def _stop_recording(self):
        if not self.recorder.is_recording:
            return
        self._poll_timer.stop()
        self.current_events = self.recorder.stop()
        self._refresh_event_editor()
        self._set_status(f"Idle  ({len(self.current_events)} events)", C["idle"])
        self._set_btn_active(self._rec_btn, False)     # back to grey

    # ─────────────────────────────────────────
    # PLAYER ACTIONS
    # ─────────────────────────────────────────
    def _play_macro(self):
        if not self.current_events:
            QMessageBox.warning(self, "No Macro", "Record or load a macro first.")
            return
        if self.player.is_playing:
            return
        speed    = SPEED_OPTIONS[self._speed_idx]
        humanize = self._humanize
        loops    = (0 if self._loop_mode == "infinite"
                    else (self._loop_count if self._loop_mode == "custom" else 1))
        self._set_status("Playing…", C["playing"])
        self._set_btn_active(self._play_btn, True)     # turn green
        self.player.play(
            events=list(self.current_events),
            speed=speed, loops=loops, humanize=humanize,
            on_done=self.signals.play_finished.emit,
            on_status=lambda s: self._set_status(s, C["playing"]),
        )

    def _stop_playback(self):
        self.player.stop()
        self._set_status("Idle", C["idle"])
        self._set_btn_active(self._play_btn, False)    # back to grey

    def _emergency_stop(self):
        if self.recorder.is_recording:
            self._poll_timer.stop()
            self.recorder.stop()
        self.player.stop()
        self._set_status("Idle", C["idle"])
        self._set_btn_active(self._rec_btn,  False)    # reset both
        self._set_btn_active(self._play_btn, False)
    def _on_play_done(self):
        self._set_status("Idle", C["idle"])
        self._set_btn_active(self._play_btn, False)    # back to grey

    # ─────────────────────────────────────────
    # MACRO MANAGER ACTIONS
    # ─────────────────────────────────────────
    def _save_macro(self):
        if not self.current_events:
            QMessageBox.warning(self, "Empty", "No events to save.")
            return
        name, ok = QInputDialog.getText(self, "Save Macro", "Macro name:")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        if self.manager.save(name, self.current_events):
            self.current_macro = name
            self._refresh_macro_list()
        else:
            QMessageBox.critical(self, "Error", "Could not save macro.")

    def _load_macro(self):
        items = self.macro_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Select", "Select a macro from the list.")
            return
        name = items[0].text()
        events = self.manager.load(name)
        if not events:
            QMessageBox.critical(self, "Error", f"Could not load '{name}'.")
            return
        self.current_events = events
        self.current_macro  = name
        self._refresh_event_editor()
        self._set_status(f"Loaded: {name}  ({len(events)} events)", C["idle"])

    def _delete_macro(self):
        items = self.macro_list.selectedItems()
        if not items:
            return
        name = items[0].text()
        reply = QMessageBox.question(self, "Delete", f"Delete '{name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.manager.delete(name)
            self._refresh_macro_list()

    def _refresh_macro_list(self):
        self.macro_list.clear()
        for name in self.manager.list_macros():
            self.macro_list.addItem(name)

    # ─────────────────────────────────────────
    # EVENT EDITOR
    # ─────────────────────────────────────────
    @staticmethod
    def _pretty_key_name(key: str) -> str:
        """Return a human-friendly label for a pynput-style key name."""
        if not key:
            return "?"
        mapping = {
            "ctrl_l": "Left Ctrl", "ctrl_r": "Right Ctrl",
            "shift_l": "Left Shift", "shift_r": "Right Shift",
            "alt_l": "Left Alt", "alt_r": "Right Alt", "alt_gr": "Alt Gr",
            "cmd": "Win", "cmd_l": "Left Win", "cmd_r": "Right Win",
            "caps_lock": "Caps Lock", "num_lock": "Num Lock",
            "scroll_lock": "Scroll Lock", "print_screen": "Print Screen",
            "page_up": "Page Up", "page_down": "Page Down",
            "esc": "Esc", "enter": "Enter", "space": "Space",
            "backspace": "Backspace", "tab": "Tab", "delete": "Delete",
            "home": "Home", "end": "End", "insert": "Insert",
            "left": "←", "right": "→", "up": "↑", "down": "↓",
            "pause": "Pause",
        }
        if key in mapping:
            return mapping[key]
        if len(key) == 1:
            return key.upper()
        if len(key) <= 3 and key.startswith("f") and key[1:].isdigit():
            return key.upper()    # F1 .. F12
        return key.replace("_", " ").title()

    @staticmethod
    def _format_event_type(evt: dict) -> str:
        """Return a human-friendly description for an event."""
        t = evt.get("type", "")
        if t == "mouse_move":
            return "Mouse Move"
        if t == "mouse_click":
            btn   = evt.get("button", "left").capitalize()
            verb  = "Click" if evt.get("pressed") else "Release"
            return f"{btn} {verb}"
        if t == "mouse_scroll":
            dy = evt.get("dy", 0)
            return "Scroll Up" if dy > 0 else "Scroll Down"
        if t in ("key_press", "key_release"):
            nice = PeniruApp._pretty_key_name(evt.get("key", ""))
            return f"{nice} ↑" if t == "key_release" else nice
        return t.replace("_", " ").title()

    def _refresh_event_editor(self):
        self.event_tree.clear()
        prev_t = 0
        for i, evt in enumerate(self.current_events):
            delay  = evt["time"] - prev_t
            prev_t = evt["time"]
            etype  = self._format_event_type(evt)
            item = QTreeWidgetItem([str(i + 1), etype, f"{delay:.0f}"])
            item.setTextAlignment(0, Qt.AlignCenter)
            item.setTextAlignment(2, Qt.AlignCenter)
            self.event_tree.addTopLevelItem(item)

    def _clear_events(self):
        reply = QMessageBox.question(self, "Confirm", "Clear all recorded events?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.current_events.clear()
            self.event_tree.clear()
            self._set_status("Events cleared", C["idle"])

    # ── Double-click dispatcher ──────────────────
    def _on_event_double_click(self, item, column):
        """Type column → edit action; Delay column → edit timing."""
        if column == 1:
            self._edit_event_action()
        elif column == 2:
            self._edit_event_delay()

    def _selected_event_index(self):
        items = self.event_tree.selectedItems()
        if not items:
            return -1
        idx = self.event_tree.indexOfTopLevelItem(items[0])
        if idx < 0 or idx >= len(self.current_events):
            return -1
        return idx

    def _edit_event_delay(self, *_):
        idx = self._selected_event_index()
        if idx < 0:
            return
        prev_ms = self.current_events[idx - 1]["time"] if idx > 0 else 0
        cur_ms  = self.current_events[idx]["time"] - prev_ms
        new_ms, ok = QInputDialog.getDouble(
            self, "Edit Delay",
            f"New delay for event #{idx + 1}  (ms):",
            value=round(cur_ms), min=0, max=60000, decimals=0)
        if not ok:
            return
        diff_ms = new_ms - cur_ms
        for j in range(idx, len(self.current_events)):
            self.current_events[j]["time"] += diff_ms
        self._refresh_event_editor()

    # ── Action editor ────────────────────────────
    def _edit_event_action(self, *_):
        idx = self._selected_event_index()
        if idx < 0:
            return
        evt = self.current_events[idx]
        t   = evt.get("type", "")

        if t in ("key_press", "key_release"):
            self._edit_key_event(idx, evt)
        elif t == "mouse_click":
            self._edit_mouse_click_event(idx, evt)
        elif t == "mouse_scroll":
            self._edit_scroll_event(idx, evt)
        elif t == "mouse_move":
            QMessageBox.information(
                self, "Not editable",
                "Mouse-move events are auto-recorded positions.\n"
                "Edit the delay if you want to change timing.")
        else:
            QMessageBox.information(self, "Not editable",
                                    f"Cannot edit '{t}' events from here.")

    def _edit_key_event(self, idx: int, evt: dict):
        """Pick a new key from a sorted list of common keys."""
        labels  = [self._pretty_key_name(k) for k in COMMON_KEYS]
        cur_key = evt.get("key", "")
        try:
            cur_idx = COMMON_KEYS.index(cur_key)
        except ValueError:
            cur_idx = 0
        choice, ok = QInputDialog.getItem(
            self, "Change Key",
            f"Replace '{self._pretty_key_name(cur_key)}' with:",
            labels, cur_idx, False)
        if not ok or not choice:
            return
        # Map back from pretty label → raw key
        new_key = COMMON_KEYS[labels.index(choice)]
        evt["key"] = new_key
        self._refresh_event_editor()

    def _edit_mouse_click_event(self, idx: int, evt: dict):
        """Change the mouse button (left/right/middle) of a click event."""
        opts   = ["Left", "Right", "Middle"]
        raw    = ["left", "right", "middle"]
        cur_btn = evt.get("button", "left")
        try:
            cur_i = raw.index(cur_btn)
        except ValueError:
            cur_i = 0
        choice, ok = QInputDialog.getItem(
            self, "Change Mouse Button",
            "Mouse button:", opts, cur_i, False)
        if not ok:
            return
        evt["button"] = raw[opts.index(choice)]
        self._refresh_event_editor()

    def _edit_scroll_event(self, idx: int, evt: dict):
        """Flip scroll direction up ⇄ down."""
        opts = ["Scroll Up", "Scroll Down"]
        cur  = 0 if evt.get("dy", 1) > 0 else 1
        choice, ok = QInputDialog.getItem(
            self, "Change Scroll Direction",
            "Direction:", opts, cur, False)
        if not ok:
            return
        evt["dy"] = 1 if choice == "Scroll Up" else -1
        self._refresh_event_editor()

    # ─────────────────────────────────────────
    # EDGE-RESIZE HELPERS
    # ─────────────────────────────────────────
    _EDGE_CURSORS = {
        "t":  Qt.SizeVerCursor,  "b":  Qt.SizeVerCursor,
        "l":  Qt.SizeHorCursor,  "r":  Qt.SizeHorCursor,
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
    }

    def _edge_at(self, gpos):
        """Return resize direction for a global cursor position, or None."""
        if self.isMaximized() or self.isMinimized():
            return None
        m = RESIZE_EDGE
        g = self.geometry()
        x, y = gpos.x(), gpos.y()
        # Only act when cursor is within margin of the window border
        if not (g.left() - m <= x <= g.right() + m and
                g.top()  - m <= y <= g.bottom() + m):
            return None
        on_l = x <= g.left()   + m
        on_r = x >= g.right()  - m
        on_t = y <= g.top()    + m
        on_b = y >= g.bottom() - m
        if on_t and on_l: return "tl"
        if on_t and on_r: return "tr"
        if on_b and on_l: return "bl"
        if on_b and on_r: return "br"
        if on_l: return "l"
        if on_r: return "r"
        if on_t: return "t"
        if on_b: return "b"
        return None

    def _apply_resize(self, gpos):
        """Resize the window based on current drag direction."""
        dx = gpos.x() - self._rz_start_pos.x()
        dy = gpos.y() - self._rz_start_pos.y()
        g  = self._rz_start_geom
        mw, mh = self.minimumWidth(), self.minimumHeight()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        d = self._rz_dir
        if "r" in d:
            w = max(mw, g.width() + dx)
        if "b" in d:
            h = max(mh, g.height() + dy)
        if "l" in d:
            nw = max(mw, g.width() - dx)
            x  = g.x() + g.width() - nw
            w  = nw
        if "t" in d:
            nh = max(mh, g.height() - dy)
            y  = g.y() + g.height() - nh
            h  = nh
        self.setGeometry(x, y, w, h)

    # ─────────────────────────────────────────
    # HOTKEY REBINDING
    # ─────────────────────────────────────────
    def _rebind_hotkey(self, action):
        """Install a one-shot key capture via event filter."""
        self._rebinding_action = action
        btn = self._hk_buttons[action]
        btn.setText("Press a key…")
        btn.setStyleSheet(btn.styleSheet() + f"color: {C['yellow']};")
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        # ── 1. Hotkey rebinding (key capture) ─────────────────────────────
        if self._rebinding_action and event.type() == QEvent.KeyPress:
            key = event.key()
            # Ignore pure modifiers
            if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
                       Qt.Key_AltGr, Qt.Key_Super_L, Qt.Key_Super_R):
                return True
            ksym   = self._qt_key_to_name(key)
            action = self._rebinding_action
            self._rebinding_action = None
            self.removeEventFilter(self)

            self.settings.hotkeys[action] = ksym
            self.settings.save()

            btn = self._hk_buttons[action]
            btn.setText(ksym.upper())
            btn.setStyleSheet("")
            btn.setObjectName("hotkeyBtn")
            btn.setStyle(btn.style())

            self.hotkeys.stop()
            self.hotkeys.settings = self.settings
            self.hotkeys.start()
            return True

        # ── 2. Edge-resize (application-level mouse events) ───────────────
        t = event.type()

        if t == QEvent.MouseMove:
            try:
                gpos = event.globalPosition().toPoint()
            except AttributeError:
                return super().eventFilter(obj, event)

            if self._rz_dir:
                # Active resize drag – keep updating geometry
                self._apply_resize(gpos)
                return True

            # No drag: update resize cursor when near window edges
            d = self._edge_at(gpos)
            if d:
                cursor = self._EDGE_CURSORS[d]
                if self._rz_cursor_set:
                    QApplication.changeOverrideCursor(cursor)
                else:
                    QApplication.setOverrideCursor(cursor)
                    self._rz_cursor_set = True
            elif self._rz_cursor_set:
                QApplication.restoreOverrideCursor()
                self._rz_cursor_set = False

        elif t == QEvent.MouseButtonPress:
            try:
                if event.button() == Qt.LeftButton:
                    gpos = event.globalPosition().toPoint()
                    d    = self._edge_at(gpos)
                    if d:
                        self._rz_dir        = d
                        self._rz_start_pos  = gpos
                        self._rz_start_geom = self.geometry()
                        return True   # swallow – don't pass to child widgets
            except AttributeError:
                pass

        elif t == QEvent.MouseButtonRelease:
            if self._rz_dir:
                try:
                    if event.button() == Qt.LeftButton:
                        self._rz_dir = self._rz_start_pos = self._rz_start_geom = None
                        if self._rz_cursor_set:
                            QApplication.restoreOverrideCursor()
                            self._rz_cursor_set = False
                        return True
                except AttributeError:
                    pass

        return super().eventFilter(obj, event)

    @staticmethod
    def _qt_key_to_name(key: int) -> str:
        mapping = {
            Qt.Key_F1: "f1", Qt.Key_F2: "f2", Qt.Key_F3: "f3", Qt.Key_F4: "f4",
            Qt.Key_F5: "f5", Qt.Key_F6: "f6", Qt.Key_F7: "f7", Qt.Key_F8: "f8",
            Qt.Key_F9: "f9", Qt.Key_F10: "f10", Qt.Key_F11: "f11", Qt.Key_F12: "f12",
            Qt.Key_Escape: "escape", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
            Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
            Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
            Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down",
            Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
            Qt.Key_CapsLock: "caps_lock", Qt.Key_NumLock: "num_lock",
            Qt.Key_Space: "space", Qt.Key_Pause: "pause",
        }
        if key in mapping:
            return mapping[key]
        # Regular chars
        s = QKeySequence(key).toString().lower()
        return s if s else f"key_{key}"

    # ─────────────────────────────────────────
    # CONTROL CALLBACKS
    # ─────────────────────────────────────────
    def _on_speed_change(self, idx):
        self._speed_idx = idx

    def _on_loop_change(self, mode):
        self._loop_mode = mode
        self._loop_spin.setEnabled(mode == "custom")

    def _on_humanize_toggle(self, checked):
        self._humanize = checked
        self._human_btn.setText("ON " if checked else "OFF")

    # ─────────────────────────────────────────
    # WINDOW CLOSE
    # ─────────────────────────────────────────
    def closeEvent(self, event):
        self._emergency_stop()
        self.hotkeys.stop()
        if hasattr(self, "_tray"):
            self._tray.hide()
        event.accept()

    def run(self):
        pass   # Qt uses app.exec() – kept for API compatibility


# ═════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(APP_STYLESHEET)

    window = PeniruApp()
    # Respect the "start minimised to tray" toggle: skip show() and let
    # the tray icon be the only entry point until the user double-clicks it.
    if window.settings.start_minimized and hasattr(window, "_tray"):
        # Don't call show() – the window stays hidden, no taskbar entry.
        pass
    else:
        window.show()

    sys.exit(app.exec())