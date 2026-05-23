import json
import os
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime
from typing import List, Callable
import uuid

from managers.resource_manager import get_resource_manager
from utils import _responsive_geometry


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
        self._lock = threading.RLock()
        self._load_favorites()
        get_resource_manager().register_cleanup_callback(self._cleanup)

    def _cleanup(self):
        try:
            with self._lock:
                self._favorites.clear()
        except:
            pass

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
        self._on_removed_callback = None

        self.favorites_window = None
        self.current_directory = None
        self.current_directories = []
        self.favorite_entries = []
        self.dragging_index = None
        self.video_preview_manager = None
        self.grid_view_manager = None
        self.add_to_queue_callback = None
        self.add_to_playlist_callback = None
        self._embedded = False
        self._close_callback = None
        self.theme_provider.register_manager_ui(self)

    def show_favorites_manager(self, selected_directory: str = None):
        if self.favorites_window and self.favorites_window.winfo_exists():
            self.favorites_window.lift()
            if selected_directory:
                self._set_directory_scope(selected_directory)
                self._refresh_favorites_list()
            return

        self._embedded = False
        self._close_callback = None
        self.favorites_window = tk.Toplevel(self.parent)
        self.favorites_window.withdraw()
        self.favorites_window.title("Favourites")
        self.favorites_window.geometry(_responsive_geometry(self.parent, 1600, 900))
        self.favorites_window.configure(bg=self.theme_provider.bg_color)

        self._set_directory_scope(selected_directory)
        self._setup_favorites_ui()
        if selected_directory:
            self._refresh_favorites_list()

        from icon_helper import apply_icon
        apply_icon(self.favorites_window)
        self.favorites_window.deiconify()

    def _select_all(self, event=None):
        self.favorites_listbox.selection_set(0, tk.END)
        return "break"

    def _unselect_all(self, event=None):
        self.favorites_listbox.selection_clear(0, tk.END)

    def show_favorites_manager_embedded(self, parent, selected_directory: str = None, close_callback=None):
        if self.favorites_window and self.favorites_window.winfo_exists():
            self.favorites_window.destroy()
        for child in parent.winfo_children():
            child.destroy()
        self._embedded = True
        self._close_callback = close_callback
        self.favorites_window = tk.Frame(parent, bg=self.theme_provider.bg_color)
        self.favorites_window.pack(fill=tk.BOTH, expand=True)
        self._set_directory_scope(selected_directory)
        self._setup_favorites_ui()
        self._refresh_favorites_list()

    def _set_directory_scope(self, selected_directory=None):
        if isinstance(selected_directory, (list, tuple, set)):
            self.current_directories = [os.path.normpath(d) for d in selected_directory if d]
        elif selected_directory:
            self.current_directories = [os.path.normpath(selected_directory)]
        else:
            self.current_directories = []
        self.current_directory = self.current_directories[0] if self.current_directories else None

    def _is_multi_directory_scope(self):
        return len(self.current_directories) > 1

    def _close_favorites(self):
        if self.favorites_window and self.favorites_window.winfo_exists():
            self.favorites_window.destroy()
        self.favorites_window = None
        if self._embedded and self._close_callback:
            self._close_callback()

    def _get_design_tokens(self):
        return self.theme_provider.get_manager_design_tokens()

    def apply_theme(self):
        win = self.favorites_window
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        t = self._get_design_tokens()
        tp = self.theme_provider
        win.configure(bg=t["bg"])
        for attr in ("_fav_header", "_fav_body", "_fav_card", "_fav_col_hdr", "_fav_lb_row", "_fav_btn_row", "_fav_chip_bar"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            role = getattr(w, "_manager_role", "body")
            bg = t.get({"header": "header_bg", "surface": "surface", "surface2": "surface2", "body": "bg"}.get(role, "bg"), t["bg"])
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass
        if hasattr(self, "info_label"):
            self.info_label.configure(bg=t["header_bg"], fg=t["text_muted"])
        if hasattr(self, "directory_label"):
            self.directory_label.configure(bg=t["surface2"], fg=t["text_muted"])
        if hasattr(self, "favorites_listbox"):
            tp.configure_manager_listbox(self.favorites_listbox, t)
        if hasattr(self, "_fav_scrollbar"):
            tp.configure_manager_scrollbar(self._fav_scrollbar, t)
        tp.restyle_manager_buttons(win)
        tp.restyle_manager_action_links(win)
        self._refresh_favorites_list()

    def _setup_favorites_ui(self):
        tp = self.theme_provider
        t = self._get_design_tokens()

        header = tk.Frame(self.favorites_window, bg=t['header_bg'], height=58)
        header._manager_role = "header"
        self._fav_header = header
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=t['header_bg'])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        title_box = tk.Frame(h_inner, bg=t['header_bg'])
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(title_box, text="♥", font=("Segoe UI Emoji", 18),
                 bg=t['header_bg'], fg=t['favorites_accent']).pack(side=tk.LEFT, padx=(0, 10), pady=14)
        tk.Label(title_box, text="Favourites",
                 font=("Segoe UI", 15, "bold"),
                 bg=t['header_bg'], fg=t['text']).pack(side=tk.LEFT, pady=14)

        info_lbl = tk.Label(h_inner, text="",
                            font=tp.small_font, bg=t['header_bg'], fg=t['text_muted'])
        info_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        self.info_label = info_lbl

        tk.Frame(self.favorites_window, bg=t['divider'], height=1).pack(fill=tk.X)

        chip_bar = tk.Frame(self.favorites_window, bg=t['bg'])
        chip_bar._manager_role = "body"
        self._fav_chip_bar = chip_bar
        chip_bar.pack(fill=tk.X, padx=20, pady=(12, 0))
        self.directory_label = tk.Label(chip_bar, text="", font=tp.small_font,
                                        bg=t['surface2'], fg=t['text_muted'],
                                        padx=10, pady=4, relief=tk.FLAT)
        self.directory_label.pack(side=tk.LEFT)

        body = tk.Frame(self.favorites_window, bg=t['bg'])
        body._manager_role = "body"
        self._fav_body = body
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        card = tk.Frame(body, bg=t['surface'],
                        highlightbackground=t['border'], highlightthickness=1)
        card._manager_role = "surface"
        self._fav_card = card
        card.pack(fill=tk.BOTH, expand=True)

        col_hdr = tk.Frame(card, bg=t['surface2'])
        col_hdr._manager_role = "surface2"
        self._fav_col_hdr = col_hdr
        col_hdr.pack(fill=tk.X)
        tk.Label(col_hdr, text="  #    VIDEO", font=tp.small_font,
                 bg=t['surface2'], fg=t['text_muted'], pady=6, anchor="w"
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        tk.Label(col_hdr, text="drag to reorder  •  double‑click to play  ",
                 font=tp.small_font, bg=t['surface2'], fg=t['text_muted'], pady=6
                 ).pack(side=tk.RIGHT)
        tk.Frame(card, bg=t['divider'], height=1).pack(fill=tk.X)

        lb_row = tk.Frame(card, bg=t['surface'])
        lb_row._manager_role = "surface"
        self._fav_lb_row = lb_row
        lb_row.pack(fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(lb_row, width=10, relief=tk.FLAT, bd=0,
                          troughcolor=t['bg'], bg=t['divider'])
        self._fav_scrollbar = sb
        tp.configure_manager_scrollbar(sb, t)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        self.favorites_listbox = tk.Listbox(
            lb_row, selectmode=tk.MULTIPLE, yscrollcommand=sb.set,
            font=tp.normal_font, bg=t['surface'], fg=t['listbox_fg'],
            selectbackground=t['listbox_select'], selectforeground="white",
            activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0)
        self.favorites_listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        sb.config(command=self.favorites_listbox.yview)

        self.favorites_listbox.bind("<Double-Button-1>", self._on_double_click)
        self.favorites_listbox.bind("<Button-1>", self._on_mouse_down)
        self.favorites_listbox.bind("<Button-3>", self._on_right_click)
        self.favorites_listbox.bind("<B1-Motion>", self._on_mouse_drag)
        self.favorites_listbox.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.favorites_listbox.bind("<Leave>", self._on_mouse_leave)

        # ---- Buttons placed directly on body, no extra bar ----
        btn_container = tk.Frame(body, bg=t['bg'])
        btn_container._manager_role = "body"
        self._fav_btn_row = btn_container
        btn_container.pack(fill=tk.X, pady=(8, 0))

        fav_actions = tk.Frame(btn_container, bg=t["bg"])
        fav_actions.pack(side=tk.RIGHT)
        self._clear_all_btn = tp.create_manager_action_link(
            fav_actions, "✕  Clear all", self._clear_all, style="warning")
        self._clear_all_btn.pack(side=tk.LEFT)

    def _show_context_menu(self, event):
        """Show context menu for selected favorites."""
        selection = self.favorites_listbox.curselection()
        if not selection:
            return

        context_menu = self.theme_provider.create_manager_context_menu(self.favorites_window)

        context_menu.add_command(
            label=f"Play Selected ({len(selection)} favorite{'s' if len(selection) > 1 else ''})",
            command=self._play_selected
        )

        context_menu.add_separator()
        context_menu.add_command(label="Select All", command=self._select_all)
        context_menu.add_command(label="Clear Selection", command=self._unselect_all)

        context_menu.add_separator()

        context_menu.add_command(
            label="Open in Gallery",
            command=lambda: self._open_grid_view_from_selection(selection)
        )

        selected_videos = [
            self.favorite_entries[i].video_path
            for i in selection
            if 0 <= i < len(self.favorite_entries)
               and os.path.isfile(self.favorite_entries[i].video_path)
        ]

        if self.add_to_queue_callback and selected_videos:
            context_menu.add_command(
                label="Add to Queue",
                command=lambda v=selected_videos: self.add_to_queue_callback(v)
            )

        if self.add_to_playlist_callback and selected_videos:
            context_menu.add_command(
                label="Add to Playlist",
                command=lambda v=selected_videos: self.add_to_playlist_callback(v)
            )

        context_menu.add_separator()

        context_menu.add_command(
            label="Remove from Favorites",
            command=self._remove_selected
        )

        if len(selection) == 1:
            favorite = self.favorite_entries[selection[0]]
            context_menu.add_separator()
            context_menu.add_command(
                label="Copy Path",
                command=lambda: self._copy_path(favorite.video_path)
            )
            context_menu.add_command(
                label="Open File Location",
                command=lambda: self._open_location(favorite.video_path)
            )

        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def _on_mouse_leave(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def play_from_global(self):
        """Play all favorites in the current directory."""
        if not self.favorite_entries:
            return
        video_paths = [fav.video_path for fav in self.favorite_entries if os.path.isfile(fav.video_path)]
        if video_paths and self.on_play_callback:
            self.on_play_callback(video_paths)

    def _on_right_click(self, event):
        if not self.current_directory or not self.favorite_entries:
            return

        listbox = event.widget
        index = listbox.nearest(event.y)
        selection = listbox.curselection()

        # If there is a selection, check if the clicked index is in it
        if selection and index in selection:
            # Show context menu for selected items
            self._show_context_menu(event)
            return

        # Otherwise (no selection or clicked on unselected item) show preview
        if 0 <= index < len(self.favorite_entries):
            favorite = self.favorite_entries[index]
            if os.path.isfile(favorite.video_path):
                # Hide any existing preview first
                if self.video_preview_manager:
                    self.video_preview_manager.tooltip.hide_preview()
                    self.video_preview_manager.right_clicked_item = index
                    self.video_preview_manager._show_video_preview(
                        favorite.video_path, event.x_root, event.y_root
                    )

    def _open_grid_view(self):
        """Open grid view with all favorites"""
        if not self.favorite_entries:
            messagebox.showwarning("Warning", "No favorites to display", parent=self.favorites_window)
            return

        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            messagebox.showwarning("Warning", "Grid view not available", parent=self.favorites_window)
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

        if video_paths:
            self.grid_view_manager.show_grid_view(video_paths, self.video_preview_manager)
        else:
            messagebox.showwarning("No Valid Files", "No valid video files found", parent=self.favorites_window)

    def _open_grid_view_from_selection(self, selection):
        """Open grid view with selected favorites"""
        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            return

        video_paths = []
        for index in selection:
            if 0 <= index < len(self.favorite_entries):
                favorite = self.favorite_entries[index]
                if os.path.isfile(favorite.video_path):
                    video_paths.append(favorite.video_path)

        if video_paths:
            self.grid_view_manager.show_grid_view(video_paths, self.video_preview_manager)

    def _copy_path(self, file_path):
        """Copy file path to clipboard"""
        try:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(file_path)
        except Exception as e:
            print(f"Error copying path: {e}")

    def _open_location(self, file_path):
        """Open file location in explorer"""
        try:
            import subprocess
            import sys
            if os.name == 'nt':
                subprocess.Popen(f'explorer /select,"{file_path}"')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', file_path])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
        except Exception as e:
            print(f"Error opening location: {e}")

    def _refresh_favorites_list(self):
        if not self.current_directories:
            return

        def refresh():
            tp = self.theme_provider
            self.favorites_listbox.delete(0, tk.END)
            self.favorite_entries = []
            for directory in self.current_directories:
                self.favorite_entries.extend(
                    self.favorite_service.get_favorites_by_directory(directory)
                )

            if self._is_multi_directory_scope():
                dir_name = f"{len(self.current_directories)} directories"
            else:
                dir_name = os.path.basename(self.current_directory)
            self.directory_label.config(text=f"  📁  {dir_name}  ")

            if not self.favorite_entries:
                self.favorites_listbox.configure(fg=tp.muted_fg)
                self.favorites_listbox.insert(tk.END, "")
                empty_scope = "these directories" if self._is_multi_directory_scope() else "this directory"
                self.favorites_listbox.insert(tk.END, f"   No favourites in {empty_scope}.")
                self.favorites_listbox.insert(tk.END, "   Right-click a video to add one.")
                self.info_label.config(text="0 videos")
                return

            self.favorites_listbox.configure(fg=tp.listbox_fg)
            video_mapping = {}
            for i, fav in enumerate(self.favorite_entries):
                prefix = ""
                if self._is_multi_directory_scope():
                    prefix = f"{os.path.basename(fav.directory_path)} / "
                self.favorites_listbox.insert(tk.END, f"   {i + 1}.   {prefix}{fav.video_name}")
                video_mapping[i] = fav.video_path

            count = len(self.favorite_entries)
            scope_suffix = f" across {len(self.current_directories)} directories" if self._is_multi_directory_scope() else ""
            self.info_label.config(text=f"{count} video{'s' if count != 1 else ''}{scope_suffix}")

            if hasattr(self, "video_preview_manager") and self.video_preview_manager:
                self.video_preview_manager.attach_to_listbox(
                    self.favorites_listbox, video_mapping)

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
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

        index = self.favorites_listbox.nearest(event.y)

        if index < 0 or index >= len(self.favorite_entries):
            return

        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)

        current_selection = list(self.favorites_listbox.curselection())

        if shift_held and current_selection:
            self.favorites_listbox.selection_clear(0, tk.END)

            anchor = current_selection[-1] if current_selection else 0

            start = min(anchor, index)
            end = max(anchor, index)

            for i in range(start, end + 1):
                self.favorites_listbox.selection_set(i)

            return "break"

        elif ctrl_held:
            if index in current_selection:
                self.favorites_listbox.selection_clear(index)
            else:
                self.favorites_listbox.selection_set(index)

            return "break"

        else:
            self.favorites_listbox.selection_clear(0, tk.END)
            self.favorites_listbox.selection_set(index)

            if 0 <= index < len(self.favorite_entries):
                self.dragging_index = index

            return "break"

    def _on_mouse_drag(self, event):
        if self._is_multi_directory_scope():
            return
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
            if not self._is_multi_directory_scope():
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
            by_directory = {}
            for index in selection:
                if 0 <= index < len(self.favorite_entries):
                    favorite = self.favorite_entries[index]
                    by_directory.setdefault(favorite.directory_path, []).append(favorite.video_path)

            removed = 0
            for directory, video_paths in by_directory.items():
                removed += self.favorite_service.remove_multiple_from_favorites(
                    video_paths, directory
                )

            if removed > 0:
                self._refresh_favorites_list()
                if self._on_removed_callback:
                    self._on_removed_callback()

    def _clear_all(self):
        if not self.favorite_entries:
            return

        result = messagebox.askyesno(
            "Confirm Clear",
            f"Clear all {len(self.favorite_entries)} favorite(s) for the selected director{'ies' if self._is_multi_directory_scope() else 'y'}?",
            parent=self.favorites_window
        )

        if result:
            for directory in self.current_directories:
                self.favorite_service.clear_favorites_for_directory(directory)
            self._refresh_favorites_list()
            if self._on_removed_callback:
                self._on_removed_callback()


class FavoritesManager:
    def __init__(self, parent, theme_provider):
        self.storage = FavoriteStorage()
        self.service = FavoriteService(self.storage)
        self.ui = FavoritesUI(parent, theme_provider, self.service)

        self._play_callback = None
        self._on_removed_callback = None

    def set_on_removed_callback(self, callback):
        self._on_removed_callback = callback
        self.ui._on_removed_callback = callback

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback
        self.ui.on_play_callback = callback

    def show_manager(self, selected_directory: str = None):
        self.ui.show_favorites_manager(selected_directory)

    def show_embedded(self, parent, selected_directory: str = None, close_callback=None):
        self.ui.show_favorites_manager_embedded(parent, selected_directory, close_callback)
        return self.ui

    def add_to_favorites(self, video_paths: List[str], directory_path: str) -> int:
        count = self.service.add_multiple_to_favorites(video_paths, directory_path)
        if count and self.ui:
            self.ui._refresh_favorites_list()
        return count

    def remove_from_favorites(self, video_paths: List[str], directory_path: str) -> int:
        count = self.service.remove_multiple_from_favorites(video_paths, directory_path)
        if count > 0:
            if self._on_removed_callback:
                self._on_removed_callback()
            if self.ui:
                self.ui._refresh_favorites_list()
        return count

    def is_favorite(self, video_path: str, directory_path: str) -> bool:
        return self.service.is_favorite(video_path, directory_path)

    def get_favorites_for_directory(self, directory_path: str) -> List[str]:
        favorites = self.service.get_favorites_by_directory(directory_path)
        return [fav.video_path for fav in favorites]

    def set_video_preview_manager(self, preview_manager):
        self.ui.video_preview_manager = preview_manager

    def set_grid_view_manager(self, grid_view_manager):
        self.ui.grid_view_manager = grid_view_manager

    def set_add_to_queue_callback(self, callback):
        self.ui.add_to_queue_callback = callback

    def set_add_to_playlist_callback(self, callback):
        self.ui.add_to_playlist_callback = callback
