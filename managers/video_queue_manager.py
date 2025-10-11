import json
import os
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from typing import List, Optional, Callable
import uuid


class QueueEntry:
    def __init__(self, video_path: str, queue_id: str = None, added_from: str = "manual"):
        self.id = queue_id or str(uuid.uuid4())
        self.video_path = os.path.normpath(video_path)
        self.video_name = os.path.basename(self.video_path)
        self.added_from = added_from
        self.played = False

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'video_path': self.video_path,
            'added_from': self.added_from,
            'played': self.played
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueEntry':
        entry = cls(
            video_path=data.get('video_path', ''),
            queue_id=data.get('id'),
            added_from=data.get('added_from', 'manual')
        )
        entry.played = data.get('played', False)
        return entry


class QueueStorage:
    def __init__(self):
        self.queue_dir = Path.home() / "Documents" / "Recursive Media Player" / "Queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.queue_dir / "playback_queue.json"

    def save_queue(self, entries: List[QueueEntry], current_index: int = 0) -> bool:
        try:
            data = {
                'entries': [entry.to_dict() for entry in entries],
                'current_index': current_index
            }
            with open(self.queue_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving queue: {e}")
            return False

    def load_queue(self) -> tuple:
        try:
            if not self.queue_file.exists():
                return [], 0

            with open(self.queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            entries = [QueueEntry.from_dict(item) for item in data.get('entries', [])]
            current_index = data.get('current_index', 0)

            return entries, current_index
        except Exception as e:
            print(f"Error loading queue: {e}")
            return [], 0

    def clear_queue(self) -> bool:
        try:
            if self.queue_file.exists():
                self.queue_file.unlink()
            return True
        except Exception as e:
            print(f"Error clearing queue: {e}")
            return False


class QueueService:
    def __init__(self, storage: QueueStorage):
        self.storage = storage
        self._queue: List[QueueEntry] = []
        self._current_index = 0
        self._lock = threading.Lock()
        self._load_queue()

    def _load_queue(self):
        entries, index = self.storage.load_queue()
        self._queue = entries
        self._current_index = index

    def get_queue(self) -> List[QueueEntry]:
        with self._lock:
            return self._queue.copy()

    def get_current_index(self) -> int:
        with self._lock:
            return self._current_index

    def set_current_index(self, index: int):
        with self._lock:
            if 0 <= index < len(self._queue):
                self._current_index = index
                self.storage.save_queue(self._queue, self._current_index)

    def add_to_queue(self, video_paths: List[str], added_from: str = "manual") -> int:
        with self._lock:
            added_count = 0
            existing_paths = {entry.video_path for entry in self._queue}

            for video_path in video_paths:
                normalized = os.path.normpath(video_path)
                if normalized not in existing_paths:
                    entry = QueueEntry(normalized, added_from=added_from)
                    self._queue.append(entry)
                    existing_paths.add(normalized)
                    added_count += 1

            if added_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return added_count

    def play_next(self, video_paths: List[str], added_from: str = "manual") -> int:
        with self._lock:
            added_count = 0
            existing_paths = {entry.video_path for entry in self._queue}
            insert_position = self._current_index + 1

            for video_path in video_paths:
                normalized = os.path.normpath(video_path)
                if normalized not in existing_paths:
                    entry = QueueEntry(normalized, added_from=added_from)
                    self._queue.insert(insert_position, entry)
                    existing_paths.add(normalized)
                    insert_position += 1
                    added_count += 1

            if added_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return added_count

    def remove_from_queue(self, indices: List[int]) -> int:
        with self._lock:
            if not self._queue:
                return 0

            sorted_indices = sorted(set(indices), reverse=True)
            removed_count = 0

            for index in sorted_indices:
                if 0 <= index < len(self._queue):
                    self._queue.pop(index)
                    removed_count += 1

                    if index < self._current_index:
                        self._current_index -= 1
                    elif index == self._current_index and self._current_index >= len(self._queue):
                        self._current_index = max(0, len(self._queue) - 1)

            if removed_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return removed_count

    def move_items(self, indices: List[int], direction: str) -> bool:
        with self._lock:
            if not self._queue or not indices:
                return False

            indices = sorted(set(indices))

            if direction == 'up':
                if indices[0] == 0:
                    return False
                for idx in indices:
                    if idx > 0:
                        self._queue[idx], self._queue[idx - 1] = self._queue[idx - 1], self._queue[idx]
                        if self._current_index == idx:
                            self._current_index -= 1
                        elif self._current_index == idx - 1:
                            self._current_index += 1

            elif direction == 'down':
                if indices[-1] >= len(self._queue) - 1:
                    return False
                for idx in reversed(indices):
                    if idx < len(self._queue) - 1:
                        self._queue[idx], self._queue[idx + 1] = self._queue[idx + 1], self._queue[idx]
                        if self._current_index == idx:
                            self._current_index += 1
                        elif self._current_index == idx + 1:
                            self._current_index -= 1

            self.storage.save_queue(self._queue, self._current_index)
            return True

    def clear_queue(self) -> bool:
        with self._lock:
            self._queue.clear()
            self._current_index = 0
            return self.storage.clear_queue()

    def clear_played(self) -> int:
        with self._lock:
            if not self._queue:
                return 0

            original_length = len(self._queue)
            self._queue = [entry for entry in self._queue if not entry.played]
            removed = original_length - len(self._queue)

            if self._current_index >= len(self._queue):
                self._current_index = max(0, len(self._queue) - 1)

            if removed > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return removed

    def get_next_video(self) -> Optional[str]:
        with self._lock:
            if not self._queue:
                return None

            next_index = self._current_index + 1
            if next_index < len(self._queue):
                return self._queue[next_index].video_path

            return None

    def advance_queue(self) -> Optional[str]:
        with self._lock:
            if not self._queue:
                return None

            if 0 <= self._current_index < len(self._queue):
                self._queue[self._current_index].played = True

            self._current_index += 1

            if self._current_index < len(self._queue):
                video_path = self._queue[self._current_index].video_path
                self.storage.save_queue(self._queue, self._current_index)
                return video_path

            self.storage.save_queue(self._queue, self._current_index)
            return None

    def jump_to_index(self, index: int) -> Optional[str]:
        with self._lock:
            if 0 <= index < len(self._queue):
                self._current_index = index
                self.storage.save_queue(self._queue, self._current_index)
                return self._queue[index].video_path
            return None

    def get_current_video(self) -> Optional[str]:
        with self._lock:
            if 0 <= self._current_index < len(self._queue):
                return self._queue[self._current_index].video_path
            return None

    def reorder_queue(self, new_order: List[int]) -> bool:
        with self._lock:
            if len(new_order) != len(self._queue):
                return False

            try:
                current_video = None
                if 0 <= self._current_index < len(self._queue):
                    current_video = self._queue[self._current_index].video_path

                self._queue = [self._queue[i] for i in new_order]

                if current_video:
                    for i, entry in enumerate(self._queue):
                        if entry.video_path == current_video:
                            self._current_index = i
                            break

                self.storage.save_queue(self._queue, self._current_index)
                return True
            except:
                return False


class QueueUI:
    def __init__(self, parent, theme_provider, queue_service: QueueService):
        self.parent = parent
        self.theme_provider = theme_provider
        self.queue_service = queue_service

        self.queue_window = None
        self.queue_listbox = None
        self.on_play_callback = None
        self.on_jump_callback = None

        self.drag_start_index = None
        self.drag_data = None

    def show_queue_manager(self):
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.lift()
            self._refresh_queue()
            return

        self.queue_window = tk.Toplevel(self.parent)
        self.queue_window.title("Playback Queue")
        self.queue_window.geometry("800x600")
        self.queue_window.configure(bg=self.theme_provider.bg_color)

        self._setup_queue_ui()
        self._refresh_queue()

    def _setup_queue_ui(self):
        main_frame = tk.Frame(self.queue_window, bg=self.theme_provider.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        header_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        title_label = tk.Label(
            header_frame,
            text="🎬 Playback Queue",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT)

        self.queue_info_label = tk.Label(
            header_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.queue_info_label.pack(side=tk.RIGHT)

        list_frame = tk.Frame(
            main_frame,
            bg=self.theme_provider.bg_color,
            highlightbackground=self.theme_provider.frame_border,
            highlightthickness=1
        )
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.queue_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.MULTIPLE,
            yscrollcommand=scrollbar.set,
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.listbox_bg,
            fg=self.theme_provider.listbox_fg,
            selectbackground=self.theme_provider.accent_color,
            selectforeground="white",
            relief=tk.FLAT,
            bd=0
        )
        self.queue_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.queue_listbox.yview)

        self.queue_listbox.bind("<Double-Button-1>", self._on_double_click)
        self.queue_listbox.bind("<Button-1>", self._on_drag_start)
        self.queue_listbox.bind("<B1-Motion>", self._on_drag_motion)
        self.queue_listbox.bind("<ButtonRelease-1>", self._on_drag_release)

        button_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        button_frame.pack(fill=tk.X)

        left_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        left_buttons.pack(side=tk.LEFT)

        self.move_up_btn = self.theme_provider.create_button(
            left_buttons, "↑ Move Up", self._move_up, "secondary", "sm"
        )
        self.move_up_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.move_down_btn = self.theme_provider.create_button(
            left_buttons, "↓ Move Down", self._move_down, "secondary", "sm"
        )
        self.move_down_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.remove_btn = self.theme_provider.create_button(
            left_buttons, "Remove", self._remove_selected, "danger", "sm"
        )
        self.remove_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_played_btn = self.theme_provider.create_button(
            left_buttons, "Clear Played", self._clear_played, "warning", "sm"
        )
        self.clear_played_btn.pack(side=tk.LEFT)

        right_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        right_buttons.pack(side=tk.RIGHT)

        self.clear_btn = self.theme_provider.create_button(
            right_buttons, "Clear All", self._clear_queue, "warning", "md"
        )
        self.clear_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.play_btn = self.theme_provider.create_button(
            right_buttons, "▶ Play Queue", self._play_queue, "success", "md"
        )
        self.play_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.close_btn = self.theme_provider.create_button(
            right_buttons, "Close", self.queue_window.destroy, "secondary", "md"
        )
        self.close_btn.pack(side=tk.RIGHT)

    def _refresh_queue(self):
        def refresh():
            self.queue_listbox.delete(0, tk.END)

            queue = self.queue_service.get_queue()
            current_index = self.queue_service.get_current_index()

            if not queue:
                self.queue_listbox.insert(tk.END, "Queue is empty")
                self.queue_info_label.config(text="No videos in queue")
                return

            for i, entry in enumerate(queue):
                prefix = "▶ " if i == current_index else "  "
                status = " ✓" if entry.played else ""
                display = f"{prefix}{entry.video_name}{status}"

                self.queue_listbox.insert(tk.END, display)

                if i == current_index:
                    self.queue_listbox.itemconfig(i, fg=self.theme_provider.accent_color)

            unplayed = len([e for e in queue if not e.played])
            self.queue_info_label.config(
                text=f"{len(queue)} videos • {unplayed} unplayed • Playing #{current_index + 1}"
            )

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_double_click(self, event):
        selection = self.queue_listbox.curselection()
        if selection:
            index = selection[0]
            video_path = self.queue_service.jump_to_index(index)
            if video_path and self.on_jump_callback:
                self.on_jump_callback(video_path)
            self._refresh_queue()

    def _on_drag_start(self, event):
        self.drag_start_index = self.queue_listbox.nearest(event.y)
        self.drag_data = None

    def _on_drag_motion(self, event):
        if self.drag_start_index is None:
            return

        current_index = self.queue_listbox.nearest(event.y)
        if current_index != self.drag_start_index:
            self.drag_data = current_index

    def _on_drag_release(self, event):
        if self.drag_start_index is None or self.drag_data is None:
            self.drag_start_index = None
            self.drag_data = None
            return

        selection = list(self.queue_listbox.curselection())
        if not selection:
            self.drag_start_index = None
            self.drag_data = None
            return

        target = self.drag_data
        if target > max(selection):
            direction = 'down'
            moves = target - max(selection)
        elif target < min(selection):
            direction = 'up'
            moves = min(selection) - target
        else:
            self.drag_start_index = None
            self.drag_data = None
            return

        for _ in range(moves):
            self.queue_service.move_items(selection, direction)
            if direction == 'up':
                selection = [s - 1 for s in selection]
            else:
                selection = [s + 1 for s in selection]

        self._refresh_queue()

        for idx in selection:
            if 0 <= idx < self.queue_listbox.size():
                self.queue_listbox.selection_set(idx)

        self.drag_start_index = None
        self.drag_data = None

    def _move_up(self):
        selection = list(self.queue_listbox.curselection())
        if selection:
            if self.queue_service.move_items(selection, 'up'):
                self._refresh_queue()
                for idx in selection:
                    if idx > 0:
                        self.queue_listbox.selection_set(idx - 1)

    def _move_down(self):
        selection = list(self.queue_listbox.curselection())
        if selection:
            if self.queue_service.move_items(selection, 'down'):
                self._refresh_queue()
                for idx in selection:
                    if idx < self.queue_listbox.size() - 1:
                        self.queue_listbox.selection_set(idx + 1)

    def _remove_selected(self):
        selection = list(self.queue_listbox.curselection())
        if selection:
            removed = self.queue_service.remove_from_queue(selection)
            if removed > 0:
                self._refresh_queue()

    def _clear_played(self):
        removed = self.queue_service.clear_played()
        if removed > 0:
            self._refresh_queue()
            messagebox.showinfo("Success", f"Removed {removed} played videos from queue")

    def _clear_queue(self):
        result = messagebox.askyesno(
            "Confirm Clear",
            "Clear entire queue?",
            parent=self.queue_window
        )
        if result:
            self.queue_service.clear_queue()
            self._refresh_queue()

    def _play_queue(self):
        queue = self.queue_service.get_queue()
        if not queue:
            messagebox.showwarning("Empty Queue", "Queue is empty", parent=self.queue_window)
            return

        current_index = self.queue_service.get_current_index()
        videos = [entry.video_path for entry in queue[current_index:]]

        if self.on_play_callback:
            self.on_play_callback(videos)


class VideoQueueManager:
    def __init__(self, parent, theme_provider):
        self.storage = QueueStorage()
        self.service = QueueService(self.storage)
        self.ui = QueueUI(parent, theme_provider, self.service)

        self._play_callback = None

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback
        self.ui.on_play_callback = self._on_play_queue
        self.ui.on_jump_callback = self._on_jump_to_video

    def show_manager(self):
        self.ui.show_queue_manager()

    def add_to_queue(self, video_paths: List[str], added_from: str = "manual") -> int:
        return self.service.add_to_queue(video_paths, added_from)

    def play_next(self, video_paths: List[str], added_from: str = "manual") -> int:
        return self.service.play_next(video_paths, added_from)

    def get_next_video(self) -> Optional[str]:
        return self.service.get_next_video()

    def advance_queue(self) -> Optional[str]:
        return self.service.advance_queue()

    def get_current_video(self) -> Optional[str]:
        return self.service.get_current_video()

    def clear_queue(self):
        self.service.clear_queue()

    def _on_play_queue(self, videos: List[str]):
        if self._play_callback:
            self._play_callback(videos)

    def _on_jump_to_video(self, video_path: str):
        if self._play_callback:
            self._play_callback([video_path])