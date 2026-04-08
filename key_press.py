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
        else:
            pass
    return wrapped


def listen_keys(controller):
    global hotkey_refs, _mouse_scroll_hook

    cleanup_hotkeys()

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

    _mouse_scroll_hook = keyboard.on_press(lambda e: None)  # placeholder replaced below
    try:
        import mouse as _mouse_lib
        _mouse_scroll_hook = _mouse_lib.hook(
            lambda e: _on_mouse_scroll(e)
            if isinstance(e, _mouse_lib.WheelEvent) else None
        )
    except Exception:
        pass  # 'mouse' package not available; wheel via overlay only

    hotkey_refs.append(keyboard.add_hotkey('esc', _guarded(lambda: controller.stop_video())))
    hotkey_refs.append(keyboard.add_hotkey('d', _guarded(lambda: controller.next_video())))
    hotkey_refs.append(keyboard.add_hotkey('a', _guarded(lambda: controller.prev_video())))
    hotkey_refs.append(keyboard.add_hotkey('w', _guarded(lambda: controller.volume_up())))
    hotkey_refs.append(keyboard.add_hotkey('s', _guarded(lambda: controller.volume_down())))
    hotkey_refs.append(keyboard.add_hotkey('m', _guarded(lambda: controller.toggle_mute())))
    hotkey_refs.append(keyboard.add_hotkey('space', _guarded(lambda: controller.toggle_pause())))
    hotkey_refs.append(keyboard.add_hotkey('right', _guarded(lambda: controller.fast_forward())))
    hotkey_refs.append(keyboard.add_hotkey('left', _guarded(lambda: controller.rewind())))
    hotkey_refs.append(keyboard.add_hotkey('f', _guarded(lambda: controller.toggle_fullscreen())))
    hotkey_refs.append(keyboard.add_hotkey('t', _guarded(lambda: controller.take_screenshot())))
    hotkey_refs.append(keyboard.add_hotkey('1', _guarded(lambda: controller.switch_to_monitor(1))))
    hotkey_refs.append(keyboard.add_hotkey('2', _guarded(lambda: controller.switch_to_monitor(2))))
    hotkey_refs.append(keyboard.add_hotkey('=', _guarded(lambda: controller.increase_speed())))
    hotkey_refs.append(keyboard.add_hotkey('-', _guarded(lambda: controller.decrease_speed())))
    hotkey_refs.append(keyboard.add_hotkey('0', _guarded(lambda: controller.reset_speed_hotkey())))
    hotkey_refs.append(keyboard.add_hotkey('ctrl+c', _guarded(lambda: controller.copy_current_video())))
    hotkey_refs.append(keyboard.add_hotkey('i', _guarded(lambda: controller.toggle_overlay())))
    hotkey_refs.append(keyboard.add_hotkey('e', _guarded(lambda: controller.next_directory())))
    hotkey_refs.append(keyboard.add_hotkey('q', _guarded(lambda: controller.prev_directory())))
    hotkey_refs.append(keyboard.add_hotkey('v', _guarded(lambda: controller.toggle_voice_commands() if hasattr(controller, 'toggle_voice_commands') else None)))

    hotkey_refs.append(keyboard.add_hotkey('r', _guarded(lambda: controller.rotate_video('right'))))
    hotkey_refs.append(keyboard.add_hotkey('ctrl+=', _guarded(lambda: controller.zoom_video(1))))
    hotkey_refs.append(keyboard.add_hotkey('ctrl+shift+equal', _guarded(lambda: controller.zoom_video(1))))
    hotkey_refs.append(keyboard.add_hotkey('ctrl+-', _guarded(lambda: controller.zoom_video(-1))))
    hotkey_refs.append(keyboard.add_hotkey('ctrl+0',  _guarded(lambda: controller.zoom_video(0))))


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
    try:
        keyboard.unhook_all()
    except:
        pass

    if _mouse_scroll_hook is not None:
        try:
            import mouse as _mouse_lib
            _mouse_lib.unhook(_mouse_scroll_hook)
        except Exception:
            pass
    _mouse_scroll_hook = None

get_resource_manager().register_cleanup_callback(cleanup_hotkeys)