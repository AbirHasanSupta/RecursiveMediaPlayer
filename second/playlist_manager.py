import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Callable
import uuid


class PlaylistData:
    """Data class for playlist information following Single Responsibility Principle"""

    def __init__(self, playlist_id: str = None, name: str = "", description: str = "", videos: List[str] = None):
        self.id = playlist_id or str(uuid.uuid4())
        self.name = name
        self.description = description
        self.videos = videos or []
        self.created_date = datetime.now().isoformat()
        self.modified_date = self.created_date

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'videos': self.videos,
            'created_date': self.created_date,
            'modified_date': self.modified_date
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PlaylistData':
        playlist = cls(
            playlist_id=data.get('id'),
            name=data.get('name', ''),
            description=data.get('description', ''),
            videos=data.get('videos', [])
        )
        playlist.created_date = data.get('created_date', datetime.now().isoformat())
        playlist.modified_date = data.get('modified_date', playlist.created_date)
        return playlist


class PlaylistStorage:
    """Handles playlist persistence following Single Responsibility Principle"""

    def __init__(self):
        self.playlists_dir = Path.home() / "Documents" / "Recursive Media Player" / "Playlists"
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        self.playlists_file = self.playlists_dir / "playlists.json"

    def save_playlists(self, playlists: List[PlaylistData]) -> bool:
        try:
            data = [playlist.to_dict() for playlist in playlists]
            with open(self.playlists_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving playlists: {e}")
            return False

    def load_playlists(self) -> List[PlaylistData]:
        try:
            if not self.playlists_file.exists():
                return []

            with open(self.playlists_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return [PlaylistData.from_dict(item) for item in data]
        except Exception as e:
            print(f"Error loading playlists: {e}")
            return []


class PlaylistService:
    """Business logic for playlist operations following Single Responsibility Principle"""

    def __init__(self, storage: PlaylistStorage):
        self.storage = storage
        self._playlists: List[PlaylistData] = []
        self._load_playlists()

    def _load_playlists(self):
        self._playlists = self.storage.load_playlists()

    def get_all_playlists(self) -> List[PlaylistData]:
        return self._playlists.copy()

    def create_playlist(self, name: str, description: str = "", videos: List[str] = None) -> PlaylistData:
        playlist = PlaylistData(name=name, description=description, videos=videos or [])
        self._playlists.append(playlist)
        self.storage.save_playlists(self._playlists)
        return playlist

    def update_playlist(self, playlist_id: str, name: str = None, description: str = None,
                        videos: List[str] = None) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if not playlist:
            return False

        if name is not None:
            playlist.name = name
        if description is not None:
            playlist.description = description
        if videos is not None:
            playlist.videos = videos

        playlist.modified_date = datetime.now().isoformat()
        self.storage.save_playlists(self._playlists)
        return True

    def delete_playlist(self, playlist_id: str) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if playlist:
            self._playlists.remove(playlist)
            self.storage.save_playlists(self._playlists)
            return True
        return False

    def get_playlist_by_id(self, playlist_id: str) -> Optional[PlaylistData]:
        for playlist in self._playlists:
            if playlist.id == playlist_id:
                return playlist
        return None

    def add_videos_to_playlist(self, playlist_id: str, videos: List[str]) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if not playlist:
            return False

        # Add only unique videos
        for video in videos:
            if video not in playlist.videos:
                playlist.videos.append(video)

        playlist.modified_date = datetime.now().isoformat()
        self.storage.save_playlists(self._playlists)
        return True


class PlaylistUI:
    """UI components for playlist management following Interface Segregation Principle"""

    def __init__(self, parent, theme_provider, playlist_service: PlaylistService, on_play_callback: Callable = None):
        self.parent = parent
        self.theme_provider = theme_provider
        self.playlist_service = playlist_service
        self.on_play_callback = on_play_callback

        self.current_playlist: Optional[PlaylistData] = None
        self.playlist_window = None

    def show_playlist_manager(self):
        if self.playlist_window and self.playlist_window.winfo_exists():
            self.playlist_window.lift()
            return

        self.playlist_window = tk.Toplevel(self.parent)
        self.playlist_window.title("Playlist Manager")
        self.playlist_window.geometry("1000x600")
        self.playlist_window.configure(bg=self.theme_provider.bg_color)

        self._setup_playlist_manager_ui()
        self._refresh_playlist_list()

    def _setup_playlist_manager_ui(self):
        # Main container
        main_frame = tk.Frame(self.playlist_window, bg=self.theme_provider.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Header
        header_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        title_label = tk.Label(
            header_frame,
            text="Playlist Manager",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT)

        # Content frame with two panels
        content_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left panel - Playlists
        left_panel = tk.Frame(content_frame, bg=self.theme_provider.bg_color)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        playlist_label = tk.Label(
            left_panel,
            text="Playlists",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        playlist_label.pack(anchor='w', pady=(0, 10))

        # Playlist listbox with scrollbar
        playlist_container = tk.Frame(
            left_panel,
            bg=self.theme_provider.bg_color,
            highlightbackground=self.theme_provider.frame_border,
            highlightthickness=1
        )
        playlist_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        playlist_scrollbar = tk.Scrollbar(playlist_container)
        playlist_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.playlist_listbox = tk.Listbox(
            playlist_container,
            yscrollcommand=playlist_scrollbar.set,
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.listbox_bg,
            fg=self.theme_provider.listbox_fg,
            selectbackground=self.theme_provider.accent_color,
            selectforeground="white",
            relief=tk.FLAT,
            bd=0
        )
        self.playlist_listbox.pack(fill=tk.BOTH, expand=True)
        self.playlist_listbox.bind('<<ListboxSelect>>', self._on_playlist_select)
        playlist_scrollbar.config(command=self.playlist_listbox.yview)

        # Playlist buttons
        playlist_btn_frame = tk.Frame(left_panel, bg=self.theme_provider.bg_color)
        playlist_btn_frame.pack(fill=tk.X)

        self.new_playlist_btn = self.theme_provider.create_button(
            playlist_btn_frame, "New Playlist", self._create_new_playlist, "primary", "sm"
        )
        self.new_playlist_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.delete_playlist_btn = self.theme_provider.create_button(
            playlist_btn_frame, "Delete", self._delete_playlist, "danger", "sm"
        )
        self.delete_playlist_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.play_playlist_btn = self.theme_provider.create_button(
            playlist_btn_frame, "Play Playlist", self._play_playlist, "success", "sm"
        )
        self.play_playlist_btn.pack(side=tk.RIGHT)

        # Right panel - Videos
        right_panel = tk.Frame(content_frame, bg=self.theme_provider.bg_color)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Playlist info frame
        info_frame = tk.Frame(right_panel, bg=self.theme_provider.bg_color)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.playlist_info_label = tk.Label(
            info_frame,
            text="Select a playlist to view videos",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.playlist_info_label.pack(anchor='w')

        # Edit playlist info button
        self.edit_info_btn = self.theme_provider.create_button(
            info_frame, "Edit Info", self._edit_playlist_info, "secondary", "sm"
        )
        self.edit_info_btn.pack(side=tk.RIGHT)
        self.edit_info_btn.pack_forget()  # Initially hidden

        # Videos listbox with scrollbar
        video_container = tk.Frame(
            right_panel,
            bg=self.theme_provider.bg_color,
            highlightbackground=self.theme_provider.frame_border,
            highlightthickness=1
        )
        video_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        video_scrollbar = tk.Scrollbar(video_container)
        video_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.video_listbox = tk.Listbox(
            video_container,
            yscrollcommand=video_scrollbar.set,
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.listbox_bg,
            fg=self.theme_provider.listbox_fg,
            selectbackground=self.theme_provider.accent_color,
            selectforeground="white",
            selectmode=tk.MULTIPLE,
            relief=tk.FLAT,
            bd=0
        )
        self.video_listbox.pack(fill=tk.BOTH, expand=True)
        video_scrollbar.config(command=self.video_listbox.yview)

        # Video management buttons
        video_btn_frame = tk.Frame(right_panel, bg=self.theme_provider.bg_color)
        video_btn_frame.pack(fill=tk.X)

        self.remove_video_btn = self.theme_provider.create_button(
            video_btn_frame, "Remove Selected", self._remove_selected_videos, "danger", "sm"
        )
        self.remove_video_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.move_up_btn = self.theme_provider.create_button(
            video_btn_frame, "Move Up", self._move_videos_up, "secondary", "sm"
        )
        self.move_up_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.move_down_btn = self.theme_provider.create_button(
            video_btn_frame, "Move Down", self._move_videos_down, "secondary", "sm"
        )
        self.move_down_btn.pack(side=tk.LEFT)

    def _refresh_playlist_list(self):
        """Refresh the playlist list in UI thread"""

        def refresh():
            # Store current selection
            current_selection = self.playlist_listbox.curselection()
            current_playlist_id = None
            if current_selection and self.current_playlist:
                current_playlist_id = self.current_playlist.id

            self.playlist_listbox.delete(0, tk.END)
            playlists = self.playlist_service.get_all_playlists()

            selection_to_restore = None
            for i, playlist in enumerate(playlists):
                display_text = f"{playlist.name} ({len(playlist.videos)} videos)"
                self.playlist_listbox.insert(tk.END, display_text)

                # Check if this was the previously selected playlist
                if current_playlist_id and playlist.id == current_playlist_id:
                    selection_to_restore = i

            if not playlists:
                self.playlist_listbox.insert(tk.END, "No playlists created yet")
                self.current_playlist = None
                self.playlist_info_label.config(text="Select a playlist to view videos")
                self.edit_info_btn.pack_forget()
            elif selection_to_restore is not None:
                # Restore previous selection
                self.playlist_listbox.selection_set(selection_to_restore)
                self.playlist_listbox.activate(selection_to_restore)

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _refresh_video_list(self):
        """Refresh the video list for current playlist"""

        def refresh():
            # Store current video selection
            current_selection = list(self.video_listbox.curselection())

            # Detach preview from old mapping
            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.detach_from_listbox(self.video_listbox)

            self.video_listbox.delete(0, tk.END)

            if not self.current_playlist:
                return

            # Create video mapping for preview
            video_mapping = {}
            for i, video in enumerate(self.current_playlist.videos):
                display_name = os.path.basename(video)
                self.video_listbox.insert(tk.END, display_name)
                video_mapping[i] = video

                # Restore selection if it was previously selected
                if i in current_selection:
                    self.video_listbox.selection_set(i)

            # Attach preview with new mapping
            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.attach_to_listbox(self.video_listbox, video_mapping)

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_playlist_select(self, event):
        # Prevent recursive calls
        if hasattr(self, '_selecting_playlist'):
            return

        selection = self.playlist_listbox.curselection()
        if not selection:
            return

        playlists = self.playlist_service.get_all_playlists()
        if selection[0] >= len(playlists):
            return

        self._selecting_playlist = True
        try:
            self.current_playlist = playlists[selection[0]]
            self._refresh_video_list()

            info_text = f"{self.current_playlist.name}"
            if self.current_playlist.description:
                info_text += f" - {self.current_playlist.description}"
            info_text += f" ({len(self.current_playlist.videos)} videos)"

            self.playlist_info_label.config(text=info_text)
            self.edit_info_btn.pack(side=tk.RIGHT)
        finally:
            delattr(self, '_selecting_playlist')

    def _create_new_playlist(self):
        dialog = PlaylistInfoDialog(self.playlist_window, self.theme_provider)
        result = dialog.show()

        if result:
            name, description = result
            self.playlist_service.create_playlist(name, description)
            self._refresh_playlist_list()

    def _edit_playlist_info(self):
        if not self.current_playlist:
            return

        dialog = PlaylistInfoDialog(
            self.playlist_window,
            self.theme_provider,
            self.current_playlist.name,
            self.current_playlist.description
        )
        result = dialog.show()

        if result:
            name, description = result
            self.playlist_service.update_playlist(
                self.current_playlist.id,
                name=name,
                description=description
            )
            self.current_playlist.name = name
            self.current_playlist.description = description
            self._refresh_playlist_list()
            self._on_playlist_select(None)  # Refresh info display

    def _delete_playlist(self):
        if not self.current_playlist:
            messagebox.showwarning("Warning", "Please select a playlist to delete")
            return

        result = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete playlist '{self.current_playlist.name}'?"
        )

        if result:
            self.playlist_service.delete_playlist(self.current_playlist.id)
            self.current_playlist = None
            self._refresh_playlist_list()
            self._refresh_video_list()
            self.playlist_info_label.config(text="Select a playlist to view videos")
            self.edit_info_btn.pack_forget()

    def _remove_selected_videos(self):
        if not self.current_playlist:
            return

        selection = self.video_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select videos to remove")
            return

        # Remove in reverse order to maintain indices
        for index in reversed(selection):
            if 0 <= index < len(self.current_playlist.videos):
                self.current_playlist.videos.pop(index)

        self.playlist_service.update_playlist(
            self.current_playlist.id,
            videos=self.current_playlist.videos
        )

        self._refresh_video_list()

        current_selection = self.playlist_listbox.curselection()
        if current_selection:
            playlists = self.playlist_service.get_all_playlists()
            if current_selection[0] < len(playlists):
                playlist = playlists[current_selection[0]]
                new_display_text = f"{playlist.name} ({len(playlist.videos)} videos)"
                self.playlist_listbox.delete(current_selection[0])
                self.playlist_listbox.insert(current_selection[0], new_display_text)
                self.playlist_listbox.selection_set(current_selection[0])
                self.playlist_listbox.activate(current_selection[0])

    def _move_videos_up(self):
        if not self.current_playlist:
            return

        selection = self.video_listbox.curselection()
        if not selection or selection[0] == 0:
            return

        videos = self.current_playlist.videos
        for index in selection:
            if index > 0:
                videos[index], videos[index - 1] = videos[index - 1], videos[index]

        self.playlist_service.update_playlist(
            self.current_playlist.id,
            videos=videos
        )
        self._refresh_video_list()

        # Restore selection
        for index in selection:
            if index > 0:
                self.video_listbox.selection_set(index - 1)

    def _move_videos_down(self):
        if not self.current_playlist:
            return

        selection = list(self.video_listbox.curselection())
        if not selection or selection[-1] >= len(self.current_playlist.videos) - 1:
            return

        videos = self.current_playlist.videos
        for index in reversed(selection):
            if index < len(videos) - 1:
                videos[index], videos[index + 1] = videos[index + 1], videos[index]

        self.playlist_service.update_playlist(
            self.current_playlist.id,
            videos=videos
        )
        self._refresh_video_list()

        # Restore selection
        for index in selection:
            if index < len(videos) - 1:
                self.video_listbox.selection_set(index + 1)

    def _play_playlist(self):
        if not self.current_playlist or not self.current_playlist.videos:
            messagebox.showwarning("Warning", "Playlist is empty or not selected")
            return

        if self.on_play_callback:
            self.on_play_callback(self.current_playlist.videos)


class PlaylistInfoDialog:
    """Dialog for editing playlist information"""

    def __init__(self, parent, theme_provider, name: str = "", description: str = ""):
        self.parent = parent
        self.theme_provider = theme_provider
        self.result = None
        self.name_entry = None
        self.description_entry = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Playlist Information")
        self.dialog.geometry("400x250")
        self.dialog.configure(bg=theme_provider.bg_color)
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center the dialog
        self.dialog.geometry("+%d+%d" % (
            parent.winfo_rootx() + 50,
            parent.winfo_rooty() + 50
        ))

        self._setup_dialog(name, description)

    def _setup_dialog(self, name: str, description: str):
        main_frame = tk.Frame(self.dialog, bg=self.theme_provider.bg_color, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Name field
        name_label = tk.Label(
            main_frame,
            text="Playlist Name:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        name_label.pack(anchor='w', pady=(0, 5))

        self.name_entry = tk.Entry(
            main_frame,
            font=self.theme_provider.normal_font,
            bg="white",
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        self.name_entry.pack(fill=tk.X, pady=(0, 15))
        self.name_entry.insert(0, name)

        # Description field
        desc_label = tk.Label(
            main_frame,
            text="Description (optional):",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        desc_label.pack(anchor='w', pady=(0, 5))

        self.description_entry = tk.Text(
            main_frame,
            font=self.theme_provider.normal_font,
            bg="white",
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground="#e0e0e0",
            height=4
        )
        self.description_entry.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        self.description_entry.insert("1.0", description)

        # Buttons
        btn_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        btn_frame.pack(fill=tk.X)

        cancel_btn = self.theme_provider.create_button(
            btn_frame, "Cancel", self._cancel, "secondary", "md"
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(5, 0))

        ok_btn = self.theme_provider.create_button(
            btn_frame, "OK", self._ok, "primary", "md"
        )
        ok_btn.pack(side=tk.RIGHT)

        # Focus and bindings
        self.name_entry.focus_set()
        self.dialog.bind('<Return>', lambda e: self._ok())
        self.dialog.bind('<Escape>', lambda e: self._cancel())

    def _ok(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Please enter a playlist name")
            return

        description = self.description_entry.get("1.0", tk.END).strip()
        self.result = (name, description)
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self):
        self.parent.wait_window(self.dialog)
        return self.result


class PlaylistManager:
    """Main playlist manager following Dependency Inversion Principle"""

    def __init__(self, parent, theme_provider):
        self.storage = PlaylistStorage()
        self.service = PlaylistService(self.storage)
        self.ui = PlaylistUI(parent, theme_provider, self.service, self._on_play_playlist)
        if hasattr(theme_provider, 'video_preview_manager'):
            self.ui.video_preview_manager = theme_provider.video_preview_manager

        self._play_callback = None

    def set_play_callback(self, callback: Callable):
        """Set callback for playing playlists"""
        self._play_callback = callback

    def show_manager(self):
        """Show the playlist manager window"""
        self.ui.show_playlist_manager()

    def add_videos_to_playlist(self, videos: List[str], selected_videos: List[str] = None):
        """Add videos to playlist with selection dialog"""
        if not videos and not selected_videos:
            messagebox.showwarning("Warning", "No videos to add to playlist")
            return

        videos_to_add = selected_videos if selected_videos else videos

        playlists = self.service.get_all_playlists()

        if not playlists:
            # No existing playlists, create new one
            dialog = PlaylistInfoDialog(self.ui.parent, self.ui.theme_provider)
            result = dialog.show()

            if result:
                name, description = result
                self.service.create_playlist(name, description, videos_to_add)
                messagebox.showinfo("Success", f"Created playlist '{name}' with {len(videos_to_add)} videos")
        else:
            # Show selection dialog for existing playlists
            self._show_add_to_playlist_dialog(videos_to_add, playlists)

    def _show_add_to_playlist_dialog(self, videos: List[str], playlists: List[PlaylistData]):
        """Show dialog to select playlist or create new one"""
        dialog = tk.Toplevel(self.ui.parent)
        dialog.title("Add to Playlist")
        dialog.geometry("400x300")
        dialog.configure(bg=self.ui.theme_provider.bg_color)
        dialog.transient(self.ui.parent)
        dialog.grab_set()

        # Center dialog
        dialog.geometry("+%d+%d" % (
            self.ui.parent.winfo_rootx() + 50,
            self.ui.parent.winfo_rooty() + 50
        ))

        main_frame = tk.Frame(dialog, bg=self.ui.theme_provider.bg_color, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = tk.Label(
            main_frame,
            text=f"Add {len(videos)} videos to playlist:",
            font=self.ui.theme_provider.normal_font,
            bg=self.ui.theme_provider.bg_color,
            fg=self.ui.theme_provider.text_color
        )
        title_label.pack(anchor='w', pady=(0, 10))

        # Playlist selection
        listbox_frame = tk.Frame(
            main_frame,
            bg=self.ui.theme_provider.bg_color,
            highlightbackground=self.ui.theme_provider.frame_border,
            highlightthickness=1
        )
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        scrollbar = tk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        playlist_listbox = tk.Listbox(
            listbox_frame,
            yscrollcommand=scrollbar.set,
            font=self.ui.theme_provider.normal_font,
            bg=self.ui.theme_provider.listbox_bg,
            fg=self.ui.theme_provider.listbox_fg,
            selectbackground=self.ui.theme_provider.accent_color,
            relief=tk.FLAT,
            bd=0
        )
        playlist_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=playlist_listbox.yview)

        for playlist in playlists:
            playlist_listbox.insert(tk.END, f"{playlist.name} ({len(playlist.videos)} videos)")

        # Buttons
        btn_frame = tk.Frame(main_frame, bg=self.ui.theme_provider.bg_color)
        btn_frame.pack(fill=tk.X)

        def create_new():
            dialog.destroy()
            info_dialog = PlaylistInfoDialog(self.ui.parent, self.ui.theme_provider)
            result = info_dialog.show()

            if result:
                name, description = result
                self.service.create_playlist(name, description, videos)
                messagebox.showinfo("Success", f"Created playlist '{name}' with {len(videos)} videos")

        def add_to_existing():
            selection = playlist_listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a playlist")
                return

            selected_playlist = playlists[selection[0]]
            self.service.add_videos_to_playlist(selected_playlist.id, videos)
            messagebox.showinfo("Success", f"Added {len(videos)} videos to '{selected_playlist.name}'")
            dialog.destroy()

        new_btn = self.ui.theme_provider.create_button(
            btn_frame, "Create New", create_new, "primary", "md"
        )
        new_btn.pack(side=tk.LEFT)

        cancel_btn = self.ui.theme_provider.create_button(
            btn_frame, "Cancel", dialog.destroy, "secondary", "md"
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(5, 0))

        add_btn = self.ui.theme_provider.create_button(
            btn_frame, "Add to Selected", add_to_existing, "success", "md"
        )
        add_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.ui.parent.wait_window(dialog)

    def _on_play_playlist(self, videos: List[str]):
        """Handle playlist playback"""
        if self._play_callback:
            self._play_callback(videos)