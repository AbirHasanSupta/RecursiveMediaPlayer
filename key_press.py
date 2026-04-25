import os
import ctypes
import keyboard

from managers.resource_manager import get_resource_manager

hotkey_refs = []
_mouse_scroll_hook = None

_user32 = ctypes.windll.user32 if hasattr(ctypes, 'windll') else None
_kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, 'windll') else None


def _get_foreground_pid():
    if not _user32 or not _kernel32:
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return None


def _is_app_in_foreground():
    fg_pid = _get_foreground_pid()
    if fg_pid is None:
        return False
    try:
        return fg_pid == os.getpid()
    except Exception:
        return False


def _guarded(fn):
    def wrapped():
        if _is_app_in_foreground():
            try:
                fn()
            except Exception:
                pass
    return wrapped


# ---------------------------------------------------------------------------
# Default hotkeys — used when no settings object is supplied.
# Must stay in sync with DEFAULT_HOTKEYS in settings_manager.py.
# ---------------------------------------------------------------------------
_DEFAULT_HOTKEYS = {
    "toggle_pause":      "space",
    "stop_video":        "esc",
    "fast_forward":      "right",
    "rewind":            "left",
    "next_video":        "d",
    "prev_video":        "a",
    "next_directory":    "e",
    "prev_directory":    "q",
    "volume_up":         "w",
    "volume_down":       "s",
    "toggle_mute":       "m",
    "increase_speed":    "=",
    "decrease_speed":    "-",
    "reset_speed":       "0",
    "toggle_fullscreen": "f",
    "monitor_1":         "1",
    "monitor_2":         "2",
    "toggle_overlay":    "i",
    "rotate_right":      "r",
    "zoom_in":           "ctrl+=",
    "zoom_out":          "ctrl+-",
    "zoom_reset":        "ctrl+0",
    "take_screenshot":   "t",
    "copy_video_path":   "ctrl+c",
    "toggle_voice":      "v",
    "next_chapter":      "n",
    "prev_chapter":      "b",
    "cycle_subtitle":    "u",
    "disable_subtitles": "ctrl+u",
}

# Mapping from action-id -> (controller_method_name, extra_positional_args)
_ACTION_MAP = {
    "toggle_pause":      ("toggle_pause",         ()),
    "stop_video":        ("stop_video",            ()),
    "fast_forward":      ("fast_forward",          ()),
    "rewind":            ("rewind",                ()),
    "next_video":        ("next_video",            ()),
    "prev_video":        ("prev_video",            ()),
    "next_directory":    ("next_directory",        ()),
    "prev_directory":    ("prev_directory",        ()),
    "volume_up":         ("volume_up",             ()),
    "volume_down":       ("volume_down",           ()),
    "toggle_mute":       ("toggle_mute",           ()),
    "increase_speed":    ("increase_speed",        ()),
    "decrease_speed":    ("decrease_speed",        ()),
    "reset_speed":       ("reset_speed_hotkey",    ()),
    "toggle_fullscreen": ("toggle_fullscreen",     ()),
    "monitor_1":         ("switch_to_monitor",     (1,)),
    "monitor_2":         ("switch_to_monitor",     (2,)),
    "toggle_overlay":    ("toggle_overlay",        ()),
    "rotate_right":      ("rotate_video",          ("right",)),
    "zoom_in":           ("zoom_video",            (1,)),
    "zoom_out":          ("zoom_video",            (-1,)),
    "zoom_reset":        ("zoom_video",            (0,)),
    "take_screenshot":   ("take_screenshot",       ()),
    "copy_video_path":   ("copy_current_video",    ()),
    "toggle_voice":      ("toggle_voice_commands", ()),
    "next_chapter":      ("next_chapter",          ()),
    "prev_chapter":      ("prev_chapter",          ()),
    "cycle_subtitle":    ("cycle_subtitle_track",  ()),
    "disable_subtitles": ("disable_subtitles",     ()),
}


def listen_keys(controller, hotkeys: dict = None):
    """Register all hotkeys from *hotkeys* (falls back to _DEFAULT_HOTKEYS).

    Call this function (or the convenience wrapper reload_hotkeys) whenever
    the user saves new key bindings in Settings.
    """
    global hotkey_refs, _mouse_scroll_hook

    cleanup_hotkeys()

    hk = hotkeys if isinstance(hotkeys, dict) else _DEFAULT_HOTKEYS

    # ── mouse-wheel volume control ──────────────────────────────────────────
    def _on_mouse_scroll(event):
        if not _is_app_in_foreground():
            return
        try:
            if getattr(controller, 'running', False) and getattr(controller, 'player', None):
                if event.delta > 0:
                    controller.volume_up()
                else:
                    controller.volume_down()
        except Exception:
            pass

    # ── mouse-wheel hook (optional mouse package) ──────────────────────────
    try:
        import mouse as _mouse_lib
        _mouse_scroll_hook = _mouse_lib.hook(
            lambda e: _on_mouse_scroll(e)
            if isinstance(e, _mouse_lib.WheelEvent) else None
        )
    except Exception:
        _mouse_scroll_hook = None  # 'mouse' package not available

    # ── register one hotkey per action ─────────────────────────────────────
    for action_id, (method_name, extra_args) in _ACTION_MAP.items():
        # Use the user's binding; only fall back to default when the value is
        # explicitly None (not when it is an empty string, which means "unbound").
        combo = hk.get(action_id) if hk.get(action_id) is not None else _DEFAULT_HOTKEYS.get(action_id)
        if not combo:
            continue  # action has no binding

        def _make_callback(mname, args):
            def _cb():
                method = getattr(controller, mname, None)
                if method is None:
                    return
                try:
                    method(*args)
                except Exception:
                    pass
            return _guarded(_cb)

        try:
            ref = keyboard.add_hotkey(combo, _make_callback(method_name, extra_args))
            hotkey_refs.append(ref)
        except Exception as e:
            print(f"[key_press] Could not register hotkey '{combo}' for '{action_id}': {e}")


def reload_hotkeys(controller, hotkeys: dict = None):
    """Convenience wrapper — call this after the user saves new key bindings.

    Typical usage in your settings-changed callback::

        def on_settings_changed(settings):
            reload_hotkeys(controller, settings.hotkeys)
    """
    listen_keys(controller, hotkeys)


def cleanup_hotkeys():
    global hotkey_refs, _mouse_scroll_hook

    for ref in hotkey_refs:
        try:
            keyboard.remove_hotkey(ref)
        except (KeyError, ValueError, AttributeError):
            pass
        except Exception as e:
            print(f"Error removing hotkey: {e}")

    hotkey_refs.clear()
    # NOTE: keyboard.unhook_all() is intentionally NOT called here because it
    # would also remove hooks registered by other parts of the app (e.g. the
    # mouse-scroll hook).  Individual refs are removed in the loop above.

    if _mouse_scroll_hook is not None:
        try:
            import mouse as _mouse_lib
            _mouse_lib.unhook(_mouse_scroll_hook)
        except Exception:
            pass
    _mouse_scroll_hook = None


get_resource_manager().register_cleanup_callback(cleanup_hotkeys)