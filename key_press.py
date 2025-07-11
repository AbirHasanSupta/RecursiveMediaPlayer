import keyboard


def listen_keys(controller, multi_directory=True):
    keyboard.add_hotkey('esc', lambda: controller.stop_video())
    keyboard.add_hotkey('d', lambda: controller.next_video())
    keyboard.add_hotkey('a', lambda: controller.prev_video())
    keyboard.add_hotkey('w', lambda: controller.volume_up())
    keyboard.add_hotkey('s', lambda: controller.volume_down())
    keyboard.add_hotkey('space', lambda: controller.toggle_pause())
    keyboard.add_hotkey('right', lambda: controller.fast_forward())
    keyboard.add_hotkey('left', lambda: controller.rewind())
    keyboard.add_hotkey('f', lambda: controller.toggle_fullscreen())
    keyboard.add_hotkey('t', lambda: controller.take_screenshot())
    keyboard.add_hotkey('1', lambda: controller.switch_to_monitor(1))
    keyboard.add_hotkey('2', lambda: controller.switch_to_monitor(2))
    if multi_directory:
        keyboard.add_hotkey('e', lambda: controller.next_directory())
        keyboard.add_hotkey('q', lambda: controller.prev_directory())
    else:
        keyboard.wait('esc')
