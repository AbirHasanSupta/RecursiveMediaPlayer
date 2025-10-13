import json
import os
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime
from typing import List, Callable
import uuid


class FavoriteEntry:
    def __init__(self, video_path: str, directory_path: str, favorite_id: str = None, added_date: str = None, order: int = None):
        self.id = favorite_id or str(uuid.uuid4())
        self.video_path = os.path.normpath(video_path)
        self.directory_path = os.path.normpath(directory_path)
        self.video_name = os.path.basename(self.video_path)
        self.added_date = added_date or datetime.now().isoformat()
        self.order = order if order is not None else 0

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'video_path': self.video_path,
            'directory_path': self.directory_path,
            'added_date': self.added_date,
            'order': self.order
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'FavoriteEntry':
        return cls(
            video_path=data.get('video_path', ''),
            directory_path=data.get('directory_path', ''),
            favorite_id=data.get('id'),
            added_date=data.get('added_date'),
            order=data.get('order', 0)
        )


class FavoriteStorage:
    def __init__(self):
        self.favorites_dir = Path.home() / "Documents" / "Recursive Media Player" / "Favorites"
        self.favorites_dir.mkdir(parents=True, exist_ok=True)
        self.favorites_file = self.favorites_dir / "favorites.json"

    def save_favorites(self, favorites: List[FavoriteEntry]) -> bool:
        try:
            data = [fav.to_dict() for fav in favorites]
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving favorites: {e}")
            return False

    def load_favorites(self) -> List[FavoriteEntry]:
        try:
            if not self.favorites_file.exists():
                return []

            with open(self.favorites_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return [FavoriteEntry.from_dict(item) for item in data]
        except Exception as e:
            print(f"Error loading favorites: {e}")
            return []


class FavoriteService:
    def __init__(self, storage: FavoriteStorage):
        self.storage = storage
        self._favorites: List[FavoriteEntry] = []
        self._lock = threading.Lock()
        self._load_favorites()

    def _load_favorites(self):
        self._favorites = self.storage.load_favorites()

    def get_all_favorites(self) -> List[FavoriteEntry]:
        with self._lock:
            return self._favorites.copy()

    def get_favorites_by_directory(self, directory_path: str) -> List[FavoriteEntry]:
        directory_path = os.path.normpath(directory_path)
        with self._lock:
            favorites = [fav for fav in self._favorites if fav.directory_path == directory_path]
            return sorted(favorites, key=lambda x: x.order)

    def add_to_favorites(self, video_path: str, directory_path: str) -> bool:
        video_path = os.path.normpath(video_path)
        directory_path = os.path.normpath(directory_path)

        with self._lock:
            for fav in self._favorites:
                if fav.video_path == video_path and fav.directory_path == directory_path:
                    return False

            dir_favorites = [f for f in self._favorites if f.directory_path == directory_path]
            next_order = max([f.order for f in dir_favorites], default=-1) + 1

            entry = FavoriteEntry(video_path, directory_path, order=next_order)
            self._favorites.append(entry)
            self.storage.save_favorites(self._favorites)
            return True

    def add_multiple_to_favorites(self, video_paths: List[str], directory_path: str) -> int:
        directory_path = os.path.normpath(directory_path)
        added_count = 0

        with self._lock:
            existing_paths = {fav.video_path for fav in self._favorites
                              if fav.directory_path == directory_path}

            dir_favorites = [f for f in self._favorites if f.directory_path == directory_path]
            next_order = max([f.order for f in dir_favorites], default=-1) + 1

            for video_path in video_paths:
                video_path = os.path.normpath(video_path)
                if video_path not in existing_paths:
                    entry = FavoriteEntry(video_path, directory_path, order=next_order)
                    self._favorites.append(entry)
                    existing_paths.add(video_path)
                    added_count += 1
                    next_order += 1

            if added_count > 0:
                self.storage.save_favorites(self._favorites)

        return added_count

    def remove_from_favorites(self, video_path: str, directory_path: str) -> bool:
        video_path = os.path.normpath(video_path)
        directory_path = os.path.normpath(directory_path)

        with self._lock:
            for i, fav in enumerate(self._favorites):
                if fav.video_path == video_path and fav.directory_path == directory_path:
                    self._favorites.pop(i)
                    self._reorder_favorites(directory_path)
                    self.storage.save_favorites(self._favorites)
                    return True
            return False

    def remove_multiple_from_favorites(self, video_paths: List[str], directory_path: str) -> int:
        directory_path = os.path.normpath(directory_path)
        removed_count = 0

        with self._lock:
            video_paths_norm = {os.path.normpath(vp) for vp in video_paths}
            entries_to_remove = []

            for fav in self._favorites:
                if fav.directory_path == directory_path and fav.video_path in video_paths_norm:
                    entries_to_remove.append(fav)

            for entry in entries_to_remove:
                self._favorites.remove(entry)
                removed_count += 1

            if removed_count > 0:
                self._reorder_favorites(directory_path)
                self.storage.save_favorites(self._favorites)

        return removed_count

    def reorder_favorites(self, directory_path: str, new_order: List[str]) -> bool:
        directory_path = os.path.normpath(directory_path)

        with self._lock:
            dir_favorites = {fav.video_path: fav for fav in self._favorites
                           if fav.directory_path == directory_path}

            for order, video_path in enumerate(new_order):
                video_path = os.path.normpath(video_path)
                if video_path in dir_favorites:
                    dir_favorites[video_path].order = order

            return self.storage.save_favorites(self._favorites)

    def _reorder_favorites(self, directory_path: str):
        dir_favorites = [f for f in self._favorites if f.directory_path == directory_path]
        dir_favorites.sort(key=lambda x: x.order)
        for i, fav in enumerate(dir_favorites):
            fav.order = i

    def is_favorite(self, video_path: str, directory_path: str) -> bool:
        video_path = os.path.normpath(video_path)
        directory_path = os.path.normpath(directory_path)

        with self._lock:
            for fav in self._favorites:
                if fav.video_path == video_path and fav.directory_path == directory_path:
                    return True
            return False

    def clear_favorites_for_directory(self, directory_path: str) -> bool:
        directory_path = os.path.normpath(directory_path)

        with self._lock:
            self._favorites = [f for f in self._favorites if f.directory_path != directory_path]
            return self.storage.save_favorites(self._favorites)

    def clear_all_favorites(self) -> bool:
        with self._lock:
            self._favorites.clear()
            return self.storage.save_favorites(self._favorites)


class FavoritesUI:
    def __init__(self, parent, theme_provider, favorite_service: FavoriteService, on_play_callback: Callable = None):
        self.parent = parent
        self.theme_provider = theme_provider
        self.favorite_service = favorite_service
        self.on_play_callback = on_play_callback

        self.favorites_window = None
        self.current_directory = None
        self.favorite_entries = []
        self.dragging_index = None

    def show_favorites_manager(self, selected_directory: str = None):
        if self.favorites_window and self.favorites_window.winfo_exists():
            self.favorites_window.lift()
            if selected_directory:
                self.current_directory = selected_directory
                self._refresh_favorites_list()
            return

        self.favorites_window = tk.Toplevel(self.parent)
        self.favorites_window.title("Favorites Manager")
        self.favorites_window.geometry("900x600")
        self.favorites_window.configure(bg=self.theme_provider.bg_color)

        self.current_directory = selected_directory
        self._setup_favorites_ui()
        if selected_directory:
            self._refresh_favorites_list()

    def _setup_favorites_ui(self):
        main_frame = tk.Frame(self.favorites_window, bg=self.theme_provider.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        header_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        title_label = tk.Label(
            header_frame,
            text="⭐ Favorites Manager",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT)

        self.info_label = tk.Label(
            header_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.info_label.pack(side=tk.RIGHT)

        self.directory_label = tk.Label(
            main_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.directory_label.pack(anchor='w', pady=(0, 10))

        list_frame = tk.Frame(
            main_frame,
            bg=self.theme_provider.bg_color,
            highlightbackground="#cccccc",
            highlightthickness=1
        )
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.favorites_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.MULTIPLE,
            yscrollcommand=scrollbar.set,
            font=self.theme_provider.normal_font,
            bg="white",
            fg=self.theme_provider.text_color,
            selectbackground=self.theme_provider.accent_color,
            selectforeground="white",
            relief=tk.FLAT,
            bd=0
        )
        self.favorites_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.favorites_listbox.yview)

        self.favorites_listbox.bind('<Double-Button-1>', self._on_double_click)
        self.favorites_listbox.bind('<Button-1>', self._on_mouse_down)
        self.favorites_listbox.bind('<B1-Motion>', self._on_mouse_drag)
        self.favorites_listbox.bind('<ButtonRelease-1>', self._on_mouse_release)

        button_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        button_frame.pack(fill=tk.X)

        left_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        left_buttons.pack(side=tk.LEFT)

        self.play_selected_btn = self.theme_provider.create_button(
            left_buttons, "▶ Play Selected", self._play_selected, "success", "md"
        )
        self.play_selected_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.play_all_btn = self.theme_provider.create_button(
            left_buttons, "▶ Play All", self._play_all, "primary", "md"
        )
        self.play_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.remove_btn = self.theme_provider.create_button(
            left_buttons, "Remove Selected", self._remove_selected, "danger", "md"
        )
        self.remove_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_btn = self.theme_provider.create_button(
            left_buttons, "Clear All", self._clear_all, "warning", "md"
        )
        self.clear_btn.pack(side=tk.LEFT)

        right_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        right_buttons.pack(side=tk.RIGHT)

        self.close_btn = self.theme_provider.create_button(
            right_buttons, "Close", self.favorites_window.destroy, "secondary", "md"
        )
        self.close_btn.pack(side=tk.RIGHT)

    def _refresh_favorites_list(self):
        if not self.current_directory:
            return

        def refresh():
            self.favorites_listbox.delete(0, tk.END)
            self.favorite_entries = self.favorite_service.get_favorites_by_directory(self.current_directory)

            if not self.favorite_entries:
                self.favorites_listbox.insert(tk.END, "No favorites in this directory")
                self.info_label.config(text="No favorites")
                self.directory_label.config(text="")
                return

            for i, favorite in enumerate(self.favorite_entries):
                display_name = f"{i + 1}. ▶ {favorite.video_name}"
                self.favorites_listbox.insert(tk.END, display_name)

            self.info_label.config(text=f"{len(self.favorite_entries)} favorite(s)")
            self.directory_label.config(
                text=f"Directory: {os.path.basename(self.current_directory)}"
            )

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_double_click(self, event):
        selection = self.favorites_listbox.curselection()
        if not selection or not self.favorite_entries:
            return

        index = selection[0]
        if 0 <= index < len(self.favorite_entries):
            favorite = self.favorite_entries[index]
            if os.path.isfile(favorite.video_path):
                if self.on_play_callback:
                    self.on_play_callback([favorite.video_path])
            else:
                messagebox.showwarning(
                    "File Not Found",
                    f"Video file not found:\n{favorite.video_path}",
                    parent=self.favorites_window
                )

    def _on_mouse_down(self, event):
        index = self.favorites_listbox.nearest(event.y)
        if 0 <= index < len(self.favorite_entries):
            self.dragging_index = index

    def _on_mouse_drag(self, event):
        if self.dragging_index is None or not self.favorite_entries:
            return

        current_index = self.favorites_listbox.nearest(event.y)
        if current_index != self.dragging_index and 0 <= current_index < len(self.favorite_entries):
            self.favorite_entries[self.dragging_index], self.favorite_entries[current_index] = \
                self.favorite_entries[current_index], self.favorite_entries[self.dragging_index]

            self.favorites_listbox.delete(0, tk.END)
            for i, favorite in enumerate(self.favorite_entries):
                display_name = f"{i + 1}. ▶ {favorite.video_name}"
                self.favorites_listbox.insert(tk.END, display_name)

            self.dragging_index = current_index
            self.favorites_listbox.selection_set(current_index)

    def _on_mouse_release(self, event):
        if self.dragging_index is not None and self.favorite_entries:
            new_order = [fav.video_path for fav in self.favorite_entries]
            self.favorite_service.reorder_favorites(self.current_directory, new_order)
            self.dragging_index = None

    def _play_selected(self):
        selection = self.favorites_listbox.curselection()
        if not selection or not self.favorite_entries:
            messagebox.showwarning(
                "Warning",
                "Please select favorites to play",
                parent=self.favorites_window
            )
            return

        video_paths = []
        missing_files = []

        for index in selection:
            if 0 <= index < len(self.favorite_entries):
                favorite = self.favorite_entries[index]
                if os.path.isfile(favorite.video_path):
                    video_paths.append(favorite.video_path)
                else:
                    missing_files.append(favorite.video_name)

        if missing_files:
            messagebox.showwarning(
                "Missing Files",
                f"The following files were not found:\n" + "\n".join(missing_files[:5]),
                parent=self.favorites_window
            )

        if video_paths and self.on_play_callback:
            self.on_play_callback(video_paths)
        elif not video_paths:
            messagebox.showwarning(
                "No Valid Files",
                "No valid video files found in selection",
                parent=self.favorites_window
            )

    def _play_all(self):
        if not self.favorite_entries:
            messagebox.showwarning(
                "Warning",
                "No favorites to play",
                parent=self.favorites_window
            )
            return

        video_paths = []
        missing_files = []

        for favorite in self.favorite_entries:
            if os.path.isfile(favorite.video_path):
                video_paths.append(favorite.video_path)
            else:
                missing_files.append(favorite.video_name)

        if missing_files:
            messagebox.showwarning(
                "Missing Files",
                f"{len(missing_files)} file(s) not found",
                parent=self.favorites_window
            )

        if video_paths and self.on_play_callback:
            self.on_play_callback(video_paths)
        elif not video_paths:
            messagebox.showwarning(
                "No Valid Files",
                "No valid video files found",
                parent=self.favorites_window
            )

    def _remove_selected(self):
        selection = self.favorites_listbox.curselection()
        if not selection or not self.favorite_entries:
            messagebox.showwarning(
                "Warning",
                "Please select favorites to remove",
                parent=self.favorites_window
            )
            return

        result = messagebox.askyesno(
            "Confirm Remove",
            f"Remove {len(selection)} favorite(s)?",
            parent=self.favorites_window
        )

        if result:
            video_paths = []
            for index in selection:
                if 0 <= index < len(self.favorite_entries):
                    video_paths.append(self.favorite_entries[index].video_path)

            removed = self.favorite_service.remove_multiple_from_favorites(
                video_paths, self.current_directory
            )

            if removed > 0:
                self._refresh_favorites_list()

    def _clear_all(self):
        if not self.favorite_entries:
            return

        result = messagebox.askyesno(
            "Confirm Clear",
            f"Clear all {len(self.favorite_entries)} favorite(s) for this directory?",
            parent=self.favorites_window
        )

        if result:
            self.favorite_service.clear_favorites_for_directory(self.current_directory)
            self._refresh_favorites_list()


class FavoritesManager:
    def __init__(self, parent, theme_provider):
        self.storage = FavoriteStorage()
        self.service = FavoriteService(self.storage)
        self.ui = FavoritesUI(parent, theme_provider, self.service)

        self._play_callback = None

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback
        self.ui.on_play_callback = callback

    def show_manager(self, selected_directory: str = None):
        self.ui.show_favorites_manager(selected_directory)

    def add_to_favorites(self, video_paths: List[str], directory_path: str) -> int:
        return self.service.add_multiple_to_favorites(video_paths, directory_path)

    def remove_from_favorites(self, video_paths: List[str], directory_path: str) -> int:
        return self.service.remove_multiple_from_favorites(video_paths, directory_path)

    def is_favorite(self, video_path: str, directory_path: str) -> bool:
        return self.service.is_favorite(video_path, directory_path)

    def get_favorites_for_directory(self, directory_path: str) -> List[str]:
        favorites = self.service.get_favorites_by_directory(directory_path)
        return [fav.video_path for fav in favorites]