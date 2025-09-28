import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
import uuid


class WatchHistoryEntry:
    """Data class for watch history entry following Single Responsibility Principle"""

    def __init__(self, video_path: str, watched_at: str = None, duration_watched: int = 0,
                 total_duration: int = 0, completion_percentage: float = 0.0):
        self.id = str(uuid.uuid4())
        self.video_path = os.path.normpath(video_path)
        self.watched_at = watched_at or datetime.now().isoformat()
        self.duration_watched = duration_watched  # in seconds
        self.total_duration = total_duration  # in seconds
        self.completion_percentage = completion_percentage
        self.video_name = os.path.basename(self.video_path)
        self.directory_path = os.path.dirname(self.video_path)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'video_path': self.video_path,
            'watched_at': self.watched_at,
            'duration_watched': self.duration_watched,
            'total_duration': self.total_duration,
            'completion_percentage': self.completion_percentage,
            'video_name': self.video_name,
            'directory_path': self.directory_path
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'WatchHistoryEntry':
        entry = cls(
            video_path=data.get('video_path', ''),
            watched_at=data.get('watched_at'),
            duration_watched=data.get('duration_watched', 0),
            total_duration=data.get('total_duration', 0),
            completion_percentage=data.get('completion_percentage', 0.0)
        )
        entry.id = data.get('id', str(uuid.uuid4()))
        return entry

    def get_watch_date_formatted(self) -> str:
        try:
            dt = datetime.fromisoformat(self.watched_at)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return self.watched_at

    def get_duration_formatted(self) -> str:
        if self.duration_watched == 0:
            return "Not tracked"

        hours = self.duration_watched // 3600
        minutes = (self.duration_watched % 3600) // 60
        seconds = self.duration_watched % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def is_recently_watched(self, hours: int = 24) -> bool:
        try:
            watched_time = datetime.fromisoformat(self.watched_at)
            return datetime.now() - watched_time < timedelta(hours=hours)
        except:
            return False


class WatchHistoryStorage:
    """Handles watch history persistence following Single Responsibility Principle"""

    def __init__(self):
        self.history_dir = Path.home() / "Documents" / "Recursive Media Player" / "History"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.history_dir / "watch_history.json"
        self.max_entries = 1000  # Limit history size

    def save_history(self, entries: List[WatchHistoryEntry]) -> bool:
        try:
            # Keep only the most recent entries
            sorted_entries = sorted(entries, key=lambda x: x.watched_at, reverse=True)
            limited_entries = sorted_entries[:self.max_entries]

            data = [entry.to_dict() for entry in limited_entries]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving watch history: {e}")
            return False

    def load_history(self) -> List[WatchHistoryEntry]:
        try:
            if not self.history_file.exists():
                return []

            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            entries = [WatchHistoryEntry.from_dict(item) for item in data]
            # Sort by watched time, most recent first
            return sorted(entries, key=lambda x: x.watched_at, reverse=True)
        except Exception as e:
            print(f"Error loading watch history: {e}")
            return []


class WatchHistoryService:
    """Business logic for watch history operations following Single Responsibility Principle"""

    def __init__(self, storage: WatchHistoryStorage):
        self.storage = storage
        self._history: List[WatchHistoryEntry] = []
        self._load_history()
        self._lock = threading.Lock()

    def _load_history(self):
        self._history = self.storage.load_history()

    def get_all_history(self) -> List[WatchHistoryEntry]:
        with self._lock:
            return self._history.copy()

    def add_watch_entry(self, video_path: str, duration_watched: int = 0,
                        total_duration: int = 0) -> WatchHistoryEntry:
        with self._lock:
            # Check if this video was already watched recently (within last 5 minutes)
            video_path_norm = os.path.normpath(video_path)
            now = datetime.now()

            for entry in self._history:
                if (entry.video_path == video_path_norm and
                        entry.is_recently_watched(hours=0) and
                        (now - datetime.fromisoformat(entry.watched_at)).total_seconds() < 300):
                    # Update existing recent entry instead of creating new one
                    entry.duration_watched = duration_watched
                    entry.total_duration = total_duration
                    if total_duration > 0:
                        entry.completion_percentage = (duration_watched / total_duration) * 100
                    entry.watched_at = now.isoformat()
                    self.storage.save_history(self._history)
                    return entry

            # Create new entry
            completion_percentage = 0.0
            if total_duration > 0:
                completion_percentage = (duration_watched / total_duration) * 100

            entry = WatchHistoryEntry(
                video_path=video_path_norm,
                duration_watched=duration_watched,
                total_duration=total_duration,
                completion_percentage=completion_percentage
            )

            self._history.insert(0, entry)  # Add to beginning (most recent)
            self.storage.save_history(self._history)
            return entry

    def remove_entry(self, entry_id: str) -> bool:
        with self._lock:
            for entry in self._history:
                if entry.id == entry_id:
                    self._history.remove(entry)
                    self.storage.save_history(self._history)
                    return True
            return False

    def remove_entries(self, entry_ids: List[str]) -> int:
        with self._lock:
            removed_count = 0
            entries_to_remove = []

            for entry in self._history:
                if entry.id in entry_ids:
                    entries_to_remove.append(entry)

            for entry in entries_to_remove:
                self._history.remove(entry)
                removed_count += 1

            if removed_count > 0:
                self.storage.save_history(self._history)

            return removed_count

    def clear_all_history(self) -> bool:
        with self._lock:
            self._history.clear()
            self.storage.save_history(self._history)
            return True

    def get_history_by_date_range(self, days: int) -> List[WatchHistoryEntry]:
        with self._lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            return [entry for entry in self._history
                    if datetime.fromisoformat(entry.watched_at) >= cutoff_date]

    def get_unique_videos_count(self) -> int:
        with self._lock:
            unique_paths = set(entry.video_path for entry in self._history)
            return len(unique_paths)


class WatchHistoryUI:
    """UI components for watch history management following Interface Segregation Principle"""

    def __init__(self, parent, theme_provider, history_service: WatchHistoryService):
        self.parent = parent
        self.theme_provider = theme_provider
        self.history_service = history_service

        self.history_window = None
        self.history_listbox = None
        self.current_entries: List[WatchHistoryEntry] = []
        self.filter_var = None

    def show_history_manager(self):
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.lift()
            return

        self.history_window = tk.Toplevel(self.parent)
        self.history_window.title("Watch History")
        self.history_window.geometry("900x600")
        self.history_window.configure(bg=self.theme_provider.bg_color)

        self._setup_history_ui()
        self._refresh_history_list()

    def _setup_history_ui(self):
        # Main container
        main_frame = tk.Frame(self.history_window, bg=self.theme_provider.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Header with stats
        header_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 20))

        title_label = tk.Label(
            header_frame,
            text="Watch History",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT)

        # Stats label
        self.stats_label = tk.Label(
            header_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.stats_label.pack(side=tk.RIGHT)

        # Filter frame
        filter_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        filter_frame.pack(fill=tk.X, pady=(0, 15))

        filter_label = tk.Label(
            filter_frame,
            text="Filter:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        filter_label.pack(side=tk.LEFT, padx=(0, 10))

        self.filter_var = tk.StringVar(value="all")

        filter_options = [
            ("All History", "all"),
            ("Today", "today"),
            ("Last 7 days", "week"),
            ("Last 30 days", "month")
        ]

        for text, value in filter_options:
            radio = ttk.Radiobutton(
                filter_frame,
                text=text,
                variable=self.filter_var,
                value=value,
                command=self._apply_filter
            )
            radio.pack(side=tk.LEFT, padx=(0, 15))

        # History list
        list_frame = tk.Frame(
            main_frame,
            bg=self.theme_provider.bg_color,
            highlightbackground=self.theme_provider.frame_border,
            highlightthickness=1
        )
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Create treeview for better data display
        columns = ('video', 'directory', 'watched_at', 'duration', 'completion')

        self.history_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)

        # Define column headings and widths
        self.history_tree.heading('video', text='Video Name')
        self.history_tree.heading('directory', text='Directory')
        self.history_tree.heading('watched_at', text='Watched At')
        self.history_tree.heading('duration', text='Duration')
        self.history_tree.heading('completion', text='Completion')

        self.history_tree.column('video', width=200, minwidth=150)
        self.history_tree.column('directory', width=200, minwidth=150)
        self.history_tree.column('watched_at', width=150, minwidth=120)
        self.history_tree.column('duration', width=100, minwidth=80)
        self.history_tree.column('completion', width=100, minwidth=80)

        # Scrollbars for treeview
        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.history_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.history_tree.xview)

        self.history_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Pack treeview and scrollbars
        self.history_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # Button frame
        button_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        button_frame.pack(fill=tk.X)

        # Left side buttons
        left_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        left_buttons.pack(side=tk.LEFT)

        self.remove_selected_btn = self.theme_provider.create_button(
            left_buttons, "Remove Selected", self._remove_selected, "danger", "md"
        )
        self.remove_selected_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.play_selected_btn = self.theme_provider.create_button(
            left_buttons, "Play Selected", self._play_selected_video, "success", "md"
        )
        self.play_selected_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_all_btn = self.theme_provider.create_button(
            left_buttons, "Clear All History", self._clear_all_history, "warning", "md"
        )
        self.clear_all_btn.pack(side=tk.LEFT)

        # Right side buttons
        right_buttons = tk.Frame(button_frame, bg=self.theme_provider.bg_color)
        right_buttons.pack(side=tk.RIGHT)

        self.refresh_btn = self.theme_provider.create_button(
            right_buttons, "Refresh", self._refresh_history_list, "secondary", "md"
        )
        self.refresh_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.close_btn = self.theme_provider.create_button(
            right_buttons, "Close", self.history_window.destroy, "secondary", "md"
        )
        self.close_btn.pack(side=tk.RIGHT)

    def _refresh_history_list(self):
        """Refresh the history list display"""

        def refresh():
            # Clear existing items
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)

            # Apply current filter
            self._apply_filter()

            # Update stats
            total_entries = len(self.history_service.get_all_history())
            unique_videos = self.history_service.get_unique_videos_count()
            filtered_count = len(self.current_entries)

            stats_text = f"Total: {total_entries} entries | Unique videos: {unique_videos}"
            if filtered_count != total_entries:
                stats_text += f" | Showing: {filtered_count}"

            self.stats_label.config(text=stats_text)

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _apply_filter(self):
        """Apply the selected filter to the history list"""
        filter_value = self.filter_var.get()

        if filter_value == "all":
            self.current_entries = self.history_service.get_all_history()
        elif filter_value == "today":
            self.current_entries = self.history_service.get_history_by_date_range(1)
        elif filter_value == "week":
            self.current_entries = self.history_service.get_history_by_date_range(7)
        elif filter_value == "month":
            self.current_entries = self.history_service.get_history_by_date_range(30)

        # Update treeview
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for entry in self.current_entries:
            # Format completion percentage
            completion_text = f"{entry.completion_percentage:.1f}%" if entry.completion_percentage > 0 else "N/A"

            # Insert into treeview
            self.history_tree.insert('', tk.END, values=(
                entry.video_name,
                os.path.basename(entry.directory_path),
                entry.get_watch_date_formatted(),
                entry.get_duration_formatted(),
                completion_text
            ), tags=(entry.id,))

    def _play_selected_video(self):
        """Play selected video from history"""
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a video to play")
            return

        if len(selection) > 1:
            messagebox.showwarning("Warning", "Please select only one video to play")
            return

        # Get entry ID from selection
        item = selection[0]
        tags = self.history_tree.item(item, 'tags')
        if not tags:
            return

        entry_id = tags[0]

        # Find the entry
        selected_entry = None
        for entry in self.current_entries:
            if entry.id == entry_id:
                selected_entry = entry
                break

        if not selected_entry:
            messagebox.showerror("Error", "Could not find selected video entry")
            return

        if not os.path.exists(selected_entry.video_path):
            messagebox.showerror("Error", f"Video file not found:\n{selected_entry.video_path}")
            return

        # Call the play callback if it exists
        if hasattr(self, 'play_callback') and self.play_callback:
            self.play_callback([selected_entry.video_path])
        else:
            messagebox.showinfo("Info", f"Would play: {selected_entry.video_name}")

    def _remove_selected(self):
        """Remove selected history entries"""
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select entries to remove")
            return

        entry_ids = []
        for item in selection:
            tags = self.history_tree.item(item, 'tags')
            if tags:
                entry_ids.append(tags[0])

        if not entry_ids:
            return

        removed_count = self.history_service.remove_entries(entry_ids)
        if removed_count > 0:
            self._refresh_history_list()

    def _clear_all_history(self):
        """Clear all watch history"""
        total_entries = len(self.history_service.get_all_history())
        if total_entries == 0:
            return

        result = messagebox.askyesno(
            "Confirm Clear All",
            f"Are you sure you want to clear all {total_entries} entries from watch history?\n\n"
            "This action cannot be undone."
        )

        if result:
            self.history_service.clear_all_history()
            messagebox.showinfo("Success", "All watch history has been cleared")
            self._refresh_history_list()


class WatchHistoryManager:
    """Main watch history manager following Dependency Inversion Principle"""

    def __init__(self, parent, theme_provider):
        self.storage = WatchHistoryStorage()
        self.service = WatchHistoryService(self.storage)
        self.ui = WatchHistoryUI(parent, theme_provider, self.service)
        self.ui.play_callback = None

        self._last_video_path = None
        self._last_start_time = None

    def show_manager(self):
        """Show the watch history manager window"""
        self.ui.show_history_manager()

    def set_play_callback(self, callback):
        """Set callback for playing videos from history"""
        self.ui.play_callback = callback

    def track_video_start(self, video_path: str):
        """Track when a video starts playing"""
        self._last_video_path = video_path
        self._last_start_time = datetime.now()

    def track_video_end(self, video_path: str, duration_watched: int = 0, total_duration: int = 0):
        """Track when a video ends or changes"""
        if video_path and os.path.exists(video_path):
            self.service.add_watch_entry(video_path, duration_watched, total_duration)

    def track_video_playback(self, video_path: str):
        """Simple tracking method for basic playback logging"""
        if video_path and os.path.exists(video_path):
            self.service.add_watch_entry(video_path)

    def get_recent_videos(self, count: int = 10) -> List[WatchHistoryEntry]:
        """Get recently watched videos"""
        all_history = self.service.get_all_history()
        return all_history[:count]

    def get_history_stats(self) -> Dict:
        """Get watch history statistics"""
        all_history = self.service.get_all_history()
        unique_videos = self.service.get_unique_videos_count()

        return {
            'total_entries': len(all_history),
            'unique_videos': unique_videos,
            'today_count': len(self.service.get_history_by_date_range(1)),
            'week_count': len(self.service.get_history_by_date_range(7)),
            'month_count': len(self.service.get_history_by_date_range(30))
        }