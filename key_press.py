import keyboard

hotkey_refs = []

def listen_keys(controller, multi_directory=True):
    global hotkey_refs

    cleanup_hotkeys()

    hotkey_refs.append(keyboard.add_hotkey('esc', lambda: controller.stop_video()))
    hotkey_refs.append(keyboard.add_hotkey('d', lambda: controller.next_video()))
    hotkey_refs.append(keyboard.add_hotkey('a', lambda: controller.prev_video()))
    hotkey_refs.append(keyboard.add_hotkey('w', lambda: controller.volume_up()))
    hotkey_refs.append(keyboard.add_hotkey('s', lambda: controller.volume_down()))
    hotkey_refs.append(keyboard.add_hotkey('space', lambda: controller.toggle_pause()))
    hotkey_refs.append(keyboard.add_hotkey('right', lambda: controller.fast_forward()))
    hotkey_refs.append(keyboard.add_hotkey('left', lambda: controller.rewind()))
    hotkey_refs.append(keyboard.add_hotkey('f', lambda: controller.toggle_fullscreen()))
    hotkey_refs.append(keyboard.add_hotkey('t', lambda: controller.take_screenshot()))
    hotkey_refs.append(keyboard.add_hotkey('1', lambda: controller.switch_to_monitor(1)))
    hotkey_refs.append(keyboard.add_hotkey('2', lambda: controller.switch_to_monitor(2)))

    if multi_directory:
        hotkey_refs.append(keyboard.add_hotkey('e', lambda: controller.next_directory()))
        hotkey_refs.append(keyboard.add_hotkey('q', lambda: controller.prev_directory()))


def cleanup_hotkeys():
    global hotkey_refs

    for ref in hotkey_refs:
        try:
            keyboard.remove_hotkey(ref)
        except (KeyError, ValueError):
            pass
    hotkey_refs.clear()