import tkinter as tk
from PIL import Image, ImageTk
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import multiprocessing

from managers.resource_manager import ManagedExecutor, get_resource_manager, ManagedThread


class GridViewItem:
    def __init__(self, video_path, thumbnail_path=None):
        self.video_path = video_path
        self.thumbnail_path = thumbnail_path
        self.thumbnail_image = None


class GridViewManager:
    def __init__(self, root, theme_provider, console_callback=None):
        self.root = root
        self.theme_provider = theme_provider
        self.console_callback = console_callback
        max_workers = min(8, (multiprocessing.cpu_count() or 4))
        self.thumbnail_executor = ManagedExecutor(ThreadPoolExecutor, max_workers=max_workers)
        self.grid_window = None
        self.items = []
        self.selected_items = set()
        self.card_widgets = {}
        self.play_callback = None
        self.add_to_playlist_callback = None
        self.add_to_favourites_callback = None
        self.remove_from_favourites_callback = None
        self.is_favourite_callback = None
        self.add_to_queue_callback = None
        self.play_in_dual_player1_callback = None
        self.play_in_dual_player2_callback = None
        self.play_in_dual_player3_callback = None
        self.play_in_dual_player_win2_1_callback = None
        self.play_in_dual_player_win2_2_callback = None
        self.play_in_dual_player_win2_3_callback = None
        self.get_player_count_callback = None
        self.open_file_location_callback = None
        self.show_properties_callback = None
        self.excluded_items = set()
        self.is_loading = False
        self.loading_lock = threading.Lock()
        self.pending_tasks = set()

        self._drag_source = None
        self._drag_ghost = None
        self._drag_over_widget = None
        self._drag_type = None

        # Cache for PhotoImage objects keyed by video_path (norm) so they survive grid rebuilds
        self._photo_cache = {}

        # Pagination
        self._page = 0
        self._page_size = 50

        get_resource_manager().register_cleanup_callback(self._cleanup)

    def _cleanup(self):
        try:
            with self.loading_lock:
                self.is_loading = False
            for task in list(self.pending_tasks):
                try:
                    task.cancel()
                except:
                    pass
            if hasattr(self, 'thumbnail_executor'):
                try:
                    self.thumbnail_executor.shutdown(wait=False, cancel_futures=False)
                except:
                    pass
            self.items = []
            self.selected_items.clear()
            self.excluded_items.clear()
            self.card_widgets.clear()
            self._photo_cache.clear()
        except:
            pass

    def set_play_callback(self, callback):
        self.play_callback = callback

    def set_add_to_playlist_callback(self, callback):
        self.add_to_playlist_callback = callback

    def set_add_to_favourites_callback(self, callback):
        self.add_to_favourites_callback = callback

    def set_remove_from_favourites_callback(self, callback):
        self.remove_from_favourites_callback = callback

    def set_is_favourite_callback(self, callback):
        """callback(video_path) -> bool"""
        self.is_favourite_callback = callback

    def set_add_to_queue_callback(self, callback):
        self.add_to_queue_callback = callback

    def set_play_in_dual_player1_callback(self, callback):
        self.play_in_dual_player1_callback = callback

    def set_play_in_dual_player2_callback(self, callback):
        self.play_in_dual_player2_callback = callback

    def set_play_in_dual_player3_callback(self, callback):
        self.play_in_dual_player3_callback = callback

    def set_play_in_dual_player_win2_1_callback(self, callback):
        self.play_in_dual_player_win2_1_callback = callback

    def set_play_in_dual_player_win2_2_callback(self, callback):
        self.play_in_dual_player_win2_2_callback = callback

    def set_play_in_dual_player_win2_3_callback(self, callback):
        self.play_in_dual_player_win2_3_callback = callback

    def set_get_player_count_callback(self, callback):
        """callback() -> int: returns the current active player count (2 or 3)"""
        self.get_player_count_callback = callback

    def set_open_file_location_callback(self, callback):
        self.open_file_location_callback = callback

    def set_show_properties_callback(self, callback):
        self.show_properties_callback = callback

    def show_grid_view(self, videos, video_preview_manager=None):
        if self.grid_window and self.grid_window.winfo_exists():
            self.grid_window.lift()
            return

        with self.loading_lock:
            self.is_loading = True

        self.grid_window = tk.Toplevel(self.root)
        self.grid_window.title("Grid View - Video Gallery")
        self.grid_window.geometry("1400x900")
        self.grid_window.configure(bg=self.theme_provider.bg_color)

        self.items = []
        self.selected_items = set()
        self.excluded_items = set()
        # Clear photo cache when opening a fresh grid window
        self._photo_cache.clear()
        self._page = 0
        self._pages_cache = None

        header_frame = tk.Frame(self.grid_window, bg=self.theme_provider.bg_color, pady=15)
        header_frame.pack(fill=tk.X, padx=20, pady=(10, 0))

        title_label = tk.Label(
            header_frame,
            text="🎬 Video Gallery",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT, anchor='w')

        self.selection_label = tk.Label(
            header_frame,
            text="0 selected",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.selection_label.pack(side=tk.LEFT, padx=(15, 0))

        # Drag mode indicator
        self.drag_mode_label = tk.Label(
            header_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.accent_color
        )
        self.drag_mode_label.pack(side=tk.LEFT, padx=(15, 0))

        toolbar = tk.Frame(self.grid_window, bg=self.theme_provider.bg_color)
        toolbar.pack(fill=tk.X, padx=20, pady=(0, 15))

        left_toolbar = tk.Frame(toolbar, bg=self.theme_provider.bg_color)
        left_toolbar.pack(side=tk.LEFT, fill=tk.X)

        tk.Label(
            left_toolbar,
            text="Grid Size:",
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            font=self.theme_provider.normal_font
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.grid_size_var = tk.IntVar(value=6)
        size_spin = tk.Spinbox(
            left_toolbar,
            from_=2,
            to=10,
            textvariable=self.grid_size_var,
            width=5,
            command=lambda: self._rebuild_grid(),
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        size_spin.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(
            left_toolbar,
            text="Filter:",
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            font=self.theme_provider.normal_font
        ).pack(side=tk.LEFT, padx=(20, 8))

        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self._filter_directories())

        search_entry = tk.Entry(
            left_toolbar,
            textvariable=self.search_var,
            font=self.theme_provider.normal_font,
            width=20,
            bg="white",
            fg=self.theme_provider.text_color
        )
        search_entry.pack(side=tk.LEFT, padx=(0, 5))

        if hasattr(self.theme_provider, 'entry_bg'):
            search_entry.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                insertbackground=self.theme_provider.entry_fg,
                highlightbackground=self.theme_provider.entry_border
            )

        clear_search_btn = self.theme_provider.create_button(
            left_toolbar,
            "Clear",
            lambda: self.search_var.set(""),
            "secondary",
            "sm"
        )
        clear_search_btn.pack(side=tk.LEFT, padx=(0, 5))

        select_all_btn = self.theme_provider.create_button(
            left_toolbar,
            "Select All",
            self._select_all,
            "success",
            "sm"
        )
        select_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        clear_btn = self.theme_provider.create_button(
            left_toolbar,
            "Clear Selection",
            self._clear_selection,
            "warning",
            "sm"
        )
        clear_btn.pack(side=tk.LEFT)

        right_toolbar = tk.Frame(toolbar, bg=self.theme_provider.bg_color)
        right_toolbar.pack(side=tk.RIGHT)

        play_btn = self.theme_provider.create_button(
            right_toolbar,
            "▶ Play Selected",
            self._play_selected,
            "danger",
            "md"
        )
        play_btn.pack(side=tk.RIGHT)

        close_btn = self.theme_provider.create_button(
            right_toolbar,
            "Close",
            lambda: self.grid_window.destroy(),
            "secondary",
            "md"
        )
        close_btn.pack(side=tk.RIGHT, padx=(0, 10))

        # ── Pagination bar ────────────────────────────────────────────────────
        self._pagination_frame = tk.Frame(self.grid_window, bg=self.theme_provider.bg_color)
        self._pagination_frame.pack(fill=tk.X, padx=20, pady=(0, 8))
        self._build_pagination_bar()

        container = tk.Frame(
            self.grid_window,
            bg=self.theme_provider.bg_color,
            highlightbackground=self.theme_provider.frame_border,
            highlightthickness=1
        )
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        canvas = tk.Canvas(
            container,
            bg=self.theme_provider.bg_color,
            highlightthickness=0
        )
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)

        self.grid_frame = tk.Frame(canvas, bg=self.theme_provider.bg_color)

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_frame = canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')

        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        self.grid_frame.bind("<Configure>", on_frame_configure)

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_frame, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)

        def on_mousewheel(e):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)

        self.grid_window.bind("<Control-a>", lambda e: self._select_all())
        self.grid_window.bind("<Escape>", lambda e: self._clear_selection())
        self.grid_window.bind("<Delete>", lambda e: self._clear_selection())
        self.grid_window.bind("<Return>", lambda e: self._play_selected())

        def on_closing():
            with self.loading_lock:
                self.is_loading = False
            for task in list(self.pending_tasks):
                try:
                    task.cancel()
                except:
                    pass
            self._cancel_drag()
            try:
                canvas.unbind_all("<MouseWheel>")
            except:
                pass
            if hasattr(self, 'thumbnail_executor'):
                try:
                    self.thumbnail_executor.shutdown(wait=False, cancel_futures=True)
                except:
                    pass
            self._photo_cache.clear()
            # Note: do NOT clear vpm.lru_cache here — it should survive
            # across grid view open/close so re-opens are instant.
            try:
                self.grid_window.destroy()
            except:
                pass
            self.grid_window = None

        self.grid_window.protocol("WM_DELETE_WINDOW", on_closing)

        self.canvas = canvas
        self.video_preview_manager = video_preview_manager

        ManagedThread(target=self._load_videos, args=(videos,), name="LoadGridVideos").start()

    def _load_videos(self, videos):
        try:
            with self.loading_lock:
                if not self.is_loading:
                    return
            from collections import defaultdict
            dir_groups = defaultdict(list)
            for video in videos:
                dir_path = os.path.dirname(video)
                dir_groups[dir_path].append(video)

            self.items = []
            for dir_path in sorted(dir_groups.keys()):
                video_count = len(dir_groups[dir_path])
                self.items.append({
                    'type': 'header',
                    'path': dir_path,
                    'name': os.path.basename(dir_path) or dir_path,
                    'video_count': video_count
                })
                for video in sorted(dir_groups[dir_path]):
                    self.items.append({'type': 'video', 'path': video, 'video_item': GridViewItem(video)})

            self.all_items = self.items.copy()
            self._pages_cache = None

            # Prioritize these videos in the prefetch queue so they jump
            # ahead of other directories currently being prefetched.
            if self.video_preview_manager:
                grid_videos = [
                    it['path'] for it in self.items if it['type'] == 'video'
                ]
                if grid_videos:
                    self.video_preview_manager.prioritize_for_grid(grid_videos)

            self.root.after(0, self._rebuild_grid)
        except Exception as e:
            with self.loading_lock:
                self.is_loading = False

    def _create_drag_ghost(self, label_text, x_root, y_root):
        self._cancel_drag_ghost()
        ghost = tk.Toplevel(self.root)
        ghost.overrideredirect(True)
        ghost.attributes('-topmost', True)
        try:
            ghost.attributes('-alpha', 0.75)
        except Exception:
            pass
        lbl = tk.Label(
            ghost,
            text=label_text,
            font=self.theme_provider.small_font,
            bg=self.theme_provider.accent_color,
            fg="white",
            padx=8, pady=4,
            relief=tk.FLAT
        )
        lbl.pack()
        ghost.geometry(f"+{x_root + 14}+{y_root + 14}")
        self._drag_ghost = ghost

    def _move_drag_ghost(self, x_root, y_root):
        if self._drag_ghost:
            try:
                self._drag_ghost.geometry(f"+{x_root + 14}+{y_root + 14}")
            except Exception:
                pass

    def _cancel_drag_ghost(self):
        if self._drag_ghost:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None

    def _highlight_drop_target(self, widget, active=True):
        if widget is None:
            return
        try:
            if active:
                widget.configure(highlightbackground=self.theme_provider.accent_color,
                                 highlightthickness=2)
            else:
                widget.configure(highlightbackground=self.theme_provider.frame_border,
                                 highlightthickness=1)
        except Exception:
            pass

    def _cancel_drag(self):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None
        self._drag_source = None
        self._drag_type = None
        try:
            if self.drag_mode_label.winfo_exists():
                self.drag_mode_label.config(text="")
        except Exception:
            pass

    def _get_dir_order(self):
        seen = []
        for item in self.items:
            if item['type'] == 'header' and item['path'] not in seen:
                seen.append(item['path'])
        return seen

    def _reorder_items_by_dir(self, new_dir_order):
        by_dir = {}
        for item in self.items:
            if item['type'] == 'header':
                by_dir.setdefault(item['path'], {'header': item, 'videos': []})
                by_dir[item['path']]['header'] = item
            else:
                d = os.path.dirname(item['path'])
                by_dir.setdefault(d, {'header': None, 'videos': []})
                by_dir[d]['videos'].append(item)

        new_items = []
        for d in new_dir_order:
            if d in by_dir:
                new_items.append(by_dir[d]['header'])
                new_items.extend(by_dir[d]['videos'])
        self.items = new_items
        self._pages_cache = None
        if not self.search_var.get():
            self.all_items = self.items.copy()

    def _on_dir_header_press(self, event, dir_path, header_frame):
        self._drag_source = {'type': 'dir', 'dir_path': dir_path, 'widget': header_frame}
        self._drag_type = 'dir'
        label = os.path.basename(dir_path) or dir_path
        self._create_drag_ghost(f"📁 {label}", event.x_root, event.y_root)
        try:
            self.drag_mode_label.config(text="Dragging directory…")
        except Exception:
            pass

    def _on_dir_header_motion(self, event, dir_path):
        self._move_drag_ghost(event.x_root, event.y_root)

    def _on_dir_header_release(self, event, src_dir_path):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None

        target_dir = self._find_dir_at_root_coords(event.x_root, event.y_root)
        if target_dir and target_dir != src_dir_path:
            self._move_dir_before(src_dir_path, target_dir)
            self.root.after(0, self._rebuild_grid)

        self._drag_source = None
        self._drag_type = None
        try:
            self.drag_mode_label.config(text="")
        except Exception:
            pass

    def _find_dir_at_root_coords(self, x_root, y_root):
        for item in self.items:
            if item['type'] != 'header':
                continue
            widget = item.get('_header_widget')
            if widget is None:
                continue
            try:
                wx = widget.winfo_rootx()
                wy = widget.winfo_rooty()
                ww = widget.winfo_width()
                wh = widget.winfo_height()
                if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                    return item['path']
            except Exception:
                continue
        return None

    def _move_dir_before(self, src_dir, target_dir):
        order = self._get_dir_order()
        if src_dir not in order or target_dir not in order:
            return
        order.remove(src_dir)
        idx = order.index(target_dir)
        order.insert(idx, src_dir)
        self._reorder_items_by_dir(order)

    def _on_card_press(self, event, video_path, card_widget):
        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        if ctrl_held or shift_held:
            return
        self._drag_source = {'type': 'video', 'video_path': video_path, 'widget': card_widget}
        self._drag_type = 'video'
        label = os.path.basename(video_path)
        if len(label) > 30:
            label = label[:27] + "…"
        self._create_drag_ghost(f"▶ {label}", event.x_root, event.y_root)
        try:
            self.drag_mode_label.config(text="Dragging video…")
        except Exception:
            pass

    def _on_card_motion(self, event, video_path):
        if self._drag_type != 'video':
            return
        self._move_drag_ghost(event.x_root, event.y_root)

        target_path = self._find_card_at_root_coords(event.x_root, event.y_root)
        if target_path and target_path != video_path:
            card = self.card_widgets.get(target_path)
            if card != self._drag_over_widget:
                if self._drag_over_widget:
                    self._highlight_drop_target(self._drag_over_widget, active=False)
                self._drag_over_widget = card
                self._highlight_drop_target(card, active=True)
        else:
            if self._drag_over_widget:
                self._highlight_drop_target(self._drag_over_widget, active=False)
                self._drag_over_widget = None

    def _on_card_release(self, event, src_video_path):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None

        if self._drag_type != 'video':
            self._cancel_drag()
            return

        target_path = self._find_card_at_root_coords(event.x_root, event.y_root)
        if target_path and target_path != src_video_path:
            src_dir = os.path.dirname(src_video_path)
            tgt_dir = os.path.dirname(target_path)
            if src_dir == tgt_dir:
                self._move_video_before(src_video_path, target_path)
                self.root.after(0, self._rebuild_grid)
            else:
                pass

        self._drag_source = None
        self._drag_type = None
        try:
            self.drag_mode_label.config(text="")
        except Exception:
            pass

    def _find_card_at_root_coords(self, x_root, y_root):
        for video_path, card in self.card_widgets.items():
            try:
                wx = card.winfo_rootx()
                wy = card.winfo_rooty()
                ww = card.winfo_width()
                wh = card.winfo_height()
                if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                    return video_path
            except Exception:
                continue
        return None

    def _move_video_before(self, src_video, target_video):
        src_idx = next((i for i, it in enumerate(self.items)
                        if it['type'] == 'video' and it['path'] == src_video), None)
        tgt_idx = next((i for i, it in enumerate(self.items)
                        if it['type'] == 'video' and it['path'] == target_video), None)
        if src_idx is None or tgt_idx is None:
            return
        item = self.items.pop(src_idx)
        # Recalculate tgt_idx after removal
        tgt_idx = next((i for i, it in enumerate(self.items)
                        if it['type'] == 'video' and it['path'] == target_video), None)
        if tgt_idx is None:
            self.items.append(item)
        else:
            self.items.insert(tgt_idx, item)
        self._pages_cache = None
        if not self.search_var.get():
            self.all_items = self.items.copy()

    # ── Pagination ────────────────────────────────────────────────────────────

    def _get_page_items(self):
        """Return items for the current page, never splitting a folder across pages."""
        target = self._page_size
        pages = []
        current_page = []
        current_count = 0

        i = 0
        all_items = self.items
        while i < len(all_items):
            item = all_items[i]
            if item['type'] == 'header':
                # Collect this folder's header + all its videos
                folder_block = [item]
                i += 1
                while i < len(all_items) and all_items[i]['type'] == 'video':
                    folder_block.append(all_items[i])
                    i += 1
                folder_video_count = len(folder_block) - 1  # exclude header

                # If adding this folder would exceed the target AND we already have
                # videos on the current page, start a new page
                if current_count > 0 and current_count + folder_video_count > target:
                    pages.append(current_page)
                    current_page = []
                    current_count = 0

                current_page.extend(folder_block)
                current_count += folder_video_count
            else:
                i += 1

        if current_page:
            pages.append(current_page)

        self._pages_cache = pages
        total = len(pages)
        if total == 0:
            return []

        self._page = max(0, min(self._page, total - 1))
        return pages[self._page]

    def _total_pages(self):
        # Always recompute — cache is set fresh by _get_page_items each rebuild
        if not hasattr(self, '_pages_cache') or self._pages_cache is None:
            self._get_page_items()
        return max(1, len(self._pages_cache))

    def _next_page(self):
        if self._page < self._total_pages() - 1:
            self._page += 1
            self._rebuild_grid()
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                self.canvas.yview_moveto(0)

    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._rebuild_grid()
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                self.canvas.yview_moveto(0)

    def _jump_to_page(self):
        try:
            p = int(self._jump_var.get()) - 1
            p = max(0, min(p, self._total_pages() - 1))
            self._page = p
            self._rebuild_grid()
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                self.canvas.yview_moveto(0)
        except ValueError:
            pass

    def _build_pagination_bar(self):
        if not hasattr(self, '_pagination_frame') or not self._pagination_frame.winfo_exists():
            return
        for w in self._pagination_frame.winfo_children():
            w.destroy()

        # Force pages to be calculated so _total_pages() is accurate
        self._get_page_items()
        total_pages = self._total_pages()
        total_videos = sum(1 for i in self.items if i['type'] == 'video')

        # Page size selector
        tk.Label(
            self._pagination_frame,
            text="Per page:",
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            font=self.theme_provider.small_font
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._page_size_var = tk.StringVar(value=str(self._page_size))
        size_menu = tk.OptionMenu(
            self._pagination_frame,
            self._page_size_var,
            "25", "50", "100", "200", "500", "1000",
            command=self._on_page_size_changed
        )
        size_menu.configure(
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        size_menu.pack(side=tk.LEFT, padx=(0, 16))

        prev_btn = self.theme_provider.create_button(
            self._pagination_frame, "◀ Prev", self._prev_page, "secondary", "sm"
        )
        prev_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._page_label = tk.Label(
            self._pagination_frame,
            text=f"Page {self._page + 1} of {total_pages}  ({total_videos} videos)",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        self._page_label.pack(side=tk.LEFT, padx=(0, 6))

        next_btn = self.theme_provider.create_button(
            self._pagination_frame, "Next ▶", self._next_page, "secondary", "sm"
        )
        next_btn.pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(
            self._pagination_frame,
            text="Go:",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._jump_var = tk.StringVar(value=str(self._page + 1))
        jump_entry = tk.Entry(
            self._pagination_frame,
            textvariable=self._jump_var,
            width=4,
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        jump_entry.pack(side=tk.LEFT, padx=(0, 4))
        jump_entry.bind("<Return>", lambda e: self._jump_to_page())

    def _on_page_size_changed(self, value):
        self._page_size = int(value)
        self._page = 0
        self._pages_cache = None
        self._rebuild_grid()
        if hasattr(self, 'canvas') and self.canvas.winfo_exists():
            self.canvas.yview_moveto(0)

    def _filter_directories(self):
        self._page = 0
        self._pages_cache = None
        search_term = self.search_var.get().lower()

        if not hasattr(self, 'all_items'):
            self.all_items = self.items.copy()

        if not search_term:
            self.items = self.all_items.copy()
        else:
            self.items = []
            current_dir_items = []
            current_header = None

            for item_data in self.all_items:
                if item_data['type'] == 'header':
                    if current_header and current_dir_items:
                        self.items.append(current_header)
                        self.items.extend(current_dir_items)

                    current_header = item_data.copy()
                    current_dir_items = []

                    if search_term in item_data['name'].lower():
                        current_header['matches'] = True
                elif item_data['type'] == 'video':
                    if (current_header and current_header.get('matches')) or \
                            search_term in os.path.basename(item_data['path']).lower():
                        current_dir_items.append(item_data)

            if current_header and current_dir_items:
                self.items.append(current_header)
                self.items.extend(current_dir_items)

        self.root.after(0, self._rebuild_grid)

    def _rebuild_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.card_widgets.clear()
        cols = self.grid_size_var.get()

        self._build_pagination_bar()

        if not self.items:
            no_videos_label = tk.Label(
                self.grid_frame,
                text="No videos to display",
                font=self.theme_provider.normal_font,
                bg=self.theme_provider.bg_color,
                fg="#999999"
            )
            no_videos_label.pack(pady=50)
            return

        page_items = self._get_page_items()

        grid_row = -1
        video_col = 0

        for idx, item_data in enumerate(page_items):
            if item_data['type'] == 'header':
                grid_row += 1
                video_col = 0

                header = tk.Frame(
                    self.grid_frame,
                    bg=self.theme_provider.bg_color,
                    cursor="arrow"
                )
                header.grid(row=grid_row, column=0, columnspan=cols, sticky='ew', padx=10, pady=(20, 10))

                item_data['_header_widget'] = header

                label_frame = tk.Frame(header, bg=self.theme_provider.bg_color)
                label_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

                dir_path = item_data['path']

                drag_hint = tk.Label(
                    label_frame,
                    text="⠿",
                    font=self.theme_provider.small_font,
                    bg=self.theme_provider.bg_color,
                    fg="#aaaaaa",
                    cursor="fleur"
                )
                drag_hint.pack(side=tk.LEFT, padx=(0, 4))

                dir_label = tk.Label(
                    label_frame,
                    text=f"📁 {item_data['name']}",
                    font=(self.theme_provider.normal_font.actual()['family'], 11, 'bold'),
                    bg=self.theme_provider.bg_color,
                    fg=self.theme_provider.accent_color,
                    anchor='w',
                    cursor="hand2"
                )
                dir_label.pack(side=tk.LEFT)

                count_label = tk.Label(
                    label_frame,
                    text=f"  •  {item_data.get('video_count', 0)} video{'s' if item_data.get('video_count', 0) != 1 else ''}",
                    font=self.theme_provider.small_font,
                    bg=self.theme_provider.bg_color,
                    fg="#888888",
                    anchor='w'
                )
                count_label.pack(side=tk.LEFT)

                reorder_hint = tk.Label(
                    label_frame,
                    text=" ",
                    font=self.theme_provider.small_font,
                    bg=self.theme_provider.bg_color,
                    fg="#aaaaaa",
                    anchor='w'
                )
                reorder_hint.pack(side=tk.LEFT)

                # Only the drag icon should start drag-to-reorder operations.
                drag_hint.bind("<Button-1>",
                               lambda e, dp=dir_path, hw=header: self._on_dir_header_press(e, dp, hw))
                drag_hint.bind("<B1-Motion>",
                               lambda e, dp=dir_path: self._on_dir_header_motion(e, dp))
                drag_hint.bind("<ButtonRelease-1>",
                               lambda e, dp=dir_path: self._on_dir_header_release(e, dp))

                # Clicking the header (or its labels) should toggle selection for the directory.
                for w in [header, dir_label, count_label, reorder_hint, label_frame]:
                    w.bind("<Button-1>", lambda e, dp=dir_path: self._toggle_select_directory(dp))

                separator = tk.Frame(
                    header,
                    height=1,
                    bg=self.theme_provider.frame_border
                )
                separator.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

                grid_row += 1
                continue

            item = item_data['video_item']
            video_path = item_data['path']
            is_selected = video_path in self.selected_items
            is_excluded = video_path in self.excluded_items

            # Always derive card colours from selection/exclusion state — never use
            # stale state from a previous grid build.
            if is_selected:
                card_bg = self.theme_provider.accent_color
                card_hl = self.theme_provider.accent_color
                card_hl_thickness = 3
                info_bg = self.theme_provider.accent_color
                name_fg = "white"
                name_weight = "bold"
            elif is_excluded:
                card_bg = self.theme_provider.listbox_bg
                card_hl = "#cc4444"
                card_hl_thickness = 2
                info_bg = self.theme_provider.listbox_bg
                name_fg = "#888888"
                name_weight = "normal"
            else:
                card_bg = self.theme_provider.listbox_bg
                card_hl = self.theme_provider.frame_border
                card_hl_thickness = 1
                info_bg = self.theme_provider.listbox_bg
                name_fg = self.theme_provider.text_color
                name_weight = "normal"

            card = tk.Frame(
                self.grid_frame,
                bg=card_bg,
                relief=tk.FLAT,
                bd=0,
                highlightthickness=card_hl_thickness,
                highlightbackground=card_hl,
                cursor="hand2"
            )
            card.grid(row=grid_row, column=video_col, padx=8, pady=8, sticky='nsew')

            self.card_widgets[video_path] = card

            thumb_container = tk.Frame(
                card,
                bg="black",
                width=280,
                height=158,
                highlightthickness=2 if is_selected else 0,
                highlightbackground=self.theme_provider.accent_color if is_selected else "black"
            )
            thumb_container._is_thumb = True
            thumb_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
            thumb_container.pack_propagate(False)

            thumb_label = tk.Label(
                thumb_container,
                bg="black",
                fg="white",
                text="▶",
                font=(self.theme_provider.normal_font.actual()['family'], 24)
            )
            thumb_label.pack(expand=True)

            if is_excluded:
                excluded_badge = tk.Label(
                    thumb_container,
                    text="🚫 Excluded",
                    bg="#aa0000",
                    fg="white",
                    font=(self.theme_provider.small_font.actual()['family'], 8, 'bold'),
                    padx=4, pady=2
                )
                excluded_badge.place(relx=0.0, rely=0.0, anchor='nw')

            # --- Thumbnail loading: 3-level cache lookup, then background
            video_path_norm = os.path.normpath(video_path)
            # Level 1: local _photo_cache (survives grid rebuild within session)
            cached_photo = self._photo_cache.get(video_path_norm)
            # Level 2: shared LRU RAM cache (survives grid close/reopen)
            if cached_photo is None and self.video_preview_manager and hasattr(self.video_preview_manager, 'lru_cache'):
                cached_photo = self.video_preview_manager.lru_cache.get(video_path_norm)
                if cached_photo is not None:
                    self._photo_cache[video_path_norm] = cached_photo  # promote to local
            if cached_photo is not None:
                self._set_thumbnail(thumb_label, cached_photo)
            else:
                # Level 3: background decode/generate
                self.thumbnail_executor.submit(self._load_thumbnail, item, thumb_label, video_path_norm)

            info_frame = tk.Frame(
                card,
                bg=info_bg,
                pady=8,
                padx=10
            )
            info_frame._is_info = True
            info_frame.pack(fill=tk.X)

            name = os.path.basename(item.video_path)
            if len(name) > 35:
                name = name[:32] + "..."

            name_label = tk.Label(
                info_frame,
                text=name,
                bg=info_bg,
                fg=name_fg,
                font=(self.theme_provider.normal_font.actual()['family'], 9, name_weight),
                anchor='w',
                justify=tk.LEFT
            )
            name_label.pack(fill=tk.X)

            drag_label = tk.Label(
                info_frame,
                text=" ",
                bg=info_bg,
                fg="#aaaaaa",
                font=(self.theme_provider.small_font.actual()['family'], 7),
                anchor='w'
            )
            drag_label.pack(fill=tk.X)

            for widget in [card, thumb_container, thumb_label, name_label, info_frame]:
                widget.bind("<Button-1>",
                            lambda e, vp=video_path, cw=card: self._on_card_click_or_press(e, vp, cw))
                widget.bind("<B1-Motion>",
                            lambda e, vp=video_path: self._on_card_motion(e, vp))
                widget.bind("<ButtonRelease-1>",
                            lambda e, vp=video_path: self._on_card_release(e, vp))
                widget.bind("<Button-3>",
                            lambda e, vp=video_path: self._on_card_right_click(e, vp))
                widget.bind("<Double-Button-1>",
                            lambda e, vp=video_path: self._play_single(vp))

            drag_label.bind("<Button-1>",
                            lambda e, vp=video_path, cw=card: self._on_card_press(e, vp, cw))
            drag_label.bind("<B1-Motion>",
                            lambda e, vp=video_path: self._on_card_motion(e, vp))
            drag_label.bind("<ButtonRelease-1>",
                            lambda e, vp=video_path: self._on_card_release(e, vp))

            card.bind("<Enter>", lambda e, vp=video_path: self._on_card_enter(e, vp))
            card.bind("<Leave>", lambda e, vp=video_path: self._on_card_leave(e, vp))

            video_col += 1
            if video_col >= cols:
                video_col = 0
                grid_row += 1

        for i in range(cols):
            self.grid_frame.columnconfigure(i, weight=1, uniform="col")

        self._update_selection_label()

    def _on_card_click_or_press(self, event, video_path, card_widget):
        self._on_card_press(event, video_path, card_widget)
        self._on_card_click(event, video_path)

    def _toggle_select_directory(self, dir_path):
        video_paths_in_dir = [item_data['path'] for item_data in self.items
                              if item_data['type'] == 'video' and os.path.dirname(item_data['path']) == dir_path]

        if not video_paths_in_dir:
            return

        all_selected = all(vp in self.selected_items for vp in video_paths_in_dir)

        if all_selected:
            for vp in video_paths_in_dir:
                self.selected_items.discard(vp)
                self._update_card_selection(vp)
        else:
            for vp in video_paths_in_dir:
                self.selected_items.add(vp)
                self._update_card_selection(vp)

        self._update_selection_label()

    def _update_selection_label(self):
        if hasattr(self, 'selection_label'):
            count = len(self.selected_items)
            if count == 0:
                self.selection_label.config(text="No selection", fg="#999999")
            elif count == 1:
                self.selection_label.config(text="1 video selected", fg=self.theme_provider.accent_color)
            else:
                self.selection_label.config(text=f"{count} videos selected", fg=self.theme_provider.accent_color)

    def _on_card_right_click(self, event, video_path):
        if video_path not in self.selected_items and self.video_preview_manager:
            video_path_norm = os.path.normpath(video_path)
            self.video_preview_manager.right_clicked_item = list(self.card_widgets.keys()).index(
                video_path) if video_path in self.card_widgets else None
            if video_path_norm in self.video_preview_manager._thumbnails:
                thumbnail = self.video_preview_manager._thumbnails[video_path_norm]
                if thumbnail.is_valid() and thumbnail.thumbnail_data:
                    self.video_preview_manager.tooltip.show_preview(video_path, thumbnail.thumbnail_data, event.x_root,
                                                                    event.y_root)
                    return
            with self.video_preview_manager._lock:
                already_queued = video_path_norm in self.video_preview_manager._generation_queue
            if not already_queued:
                self.video_preview_manager._generate_thumbnail_async(video_path_norm, event.x_root, event.y_root)
            return
        self._show_context_menu(event, video_path)

    def _on_card_click(self, event, video_path):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)

        video_paths = [item_data['path'] for item_data in self.items if item_data['type'] == 'video']

        if video_path not in video_paths:
            return

        current_index = video_paths.index(video_path)

        if shift_held and self.selected_items:
            last_selected = None
            for path in reversed(video_paths):
                if path in self.selected_items:
                    last_selected = video_paths.index(path)
                    break

            if last_selected is not None:
                start = min(last_selected, current_index)
                end = max(last_selected, current_index)

                for i in range(start, end + 1):
                    path = video_paths[i]
                    self.selected_items.add(path)
                    self._update_card_selection(path)

        elif ctrl_held:
            if video_path in self.selected_items:
                self.selected_items.remove(video_path)
            else:
                self.selected_items.add(video_path)

            self._update_card_selection(video_path)

        else:
            old_selection = self.selected_items.copy()
            self.selected_items = {video_path}

            for path in old_selection:
                if path != video_path:
                    self._update_card_selection(path)

            self._update_card_selection(video_path)

        self._update_selection_label()

    def _on_card_enter(self, event, video_path):
        pass

    def _on_card_leave(self, event, video_path):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _show_context_menu(self, event, video_path):
        context_menu = tk.Menu(self.grid_window, tearoff=0)

        if not self.selected_items:
            return

        # ── Play ──────────────────────────────────────────────────────────────
        if video_path in self.selected_items:
            context_menu.add_command(
                label=f"Play Selected ({len(self.selected_items)} items)",
                command=self._play_selected
            )
        else:
            context_menu.add_command(
                label="Play This Video",
                command=lambda: self._play_single(video_path)
            )

        context_menu.add_separator()

        # ── Exclude / Include ─────────────────────────────────────────────────
        selected_excluded = [vp for vp in self.selected_items if vp in self.excluded_items]
        selected_not_excluded = [vp for vp in self.selected_items if vp not in self.excluded_items]

        if selected_not_excluded:
            label = (
                f"Exclude Selected ({len(selected_not_excluded)} items)"
                if len(selected_not_excluded) > 1
                else "Exclude This Video"
            )
            context_menu.add_command(
                label=label,
                command=self._exclude_selected
            )

        if selected_excluded:
            label = (
                f"Remove Exclusion ({len(selected_excluded)} items)"
                if len(selected_excluded) > 1
                else "Remove Exclusion"
            )
            context_menu.add_command(
                label=label,
                command=self._remove_exclusion_selected
            )

        context_menu.add_separator()

        context_menu.add_command(
            label="Select All",
            command=self._select_all
        )

        context_menu.add_command(
            label="Clear Selection",
            command=self._clear_selection
        )

        context_menu.add_separator()

        # ── Add to Playlist ───────────────────────────────────────────────────
        context_menu.add_command(
            label="Add to Playlist",
            command=self._context_add_to_playlist
        )


        context_menu.add_command(
            label="Add to Queue",
            command=self._context_add_to_queue
        )

        context_menu.add_separator()

        context_menu.add_command(
            label="▶ Win 1 › Player 1",
            command=lambda: self._context_play_in_dual_player(slot=1)
        )
        context_menu.add_command(
            label="▶ Win 1 › Player 2",
            command=lambda: self._context_play_in_dual_player(slot=2)
        )

        context_menu.add_command(
            label="▶ Win 1 › Player 3",
            command=lambda: self._context_play_in_dual_player(slot=3)
        )

        if any([self.play_in_dual_player_win2_1_callback,
                self.play_in_dual_player_win2_2_callback,
                self.play_in_dual_player_win2_3_callback]):
            context_menu.add_separator()

        if self.play_in_dual_player_win2_1_callback:
            context_menu.add_command(
                label="▶ Win 2 › Player 1",
                command=lambda: self._context_play_in_dual_player_win2(slot=1)
            )
        if self.play_in_dual_player_win2_2_callback:
            context_menu.add_command(
                label="▶ Win 2 › Player 2",
                command=lambda: self._context_play_in_dual_player_win2(slot=2)
            )
        if self.play_in_dual_player_win2_3_callback:
            context_menu.add_command(
                label="▶ Win 2 › Player 3",
                command=lambda: self._context_play_in_dual_player_win2(slot=3)
            )

        context_menu.add_separator()

        # ── File actions (single-selection only) ──────────────────────────────
        single = video_path if len(self.selected_items) == 1 else None

        if single and os.path.isfile(single):
            context_menu.add_command(
                label="Open File Location",
                command=lambda: self._context_open_file_location(single)
            )
            context_menu.add_command(
                label="Properties",
                command=lambda: self._context_show_properties(single)
            )

        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    # ── New context-menu action helpers ───────────────────────────────────────

    def _get_selected_videos(self):
        """Return selected non-excluded videos in page order."""
        return [
            it['path'] for it in self.items
            if it['type'] == 'video'
            and it['path'] in self.selected_items
            and it['path'] not in self.excluded_items
        ]

    def _context_add_to_playlist(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        if self.add_to_playlist_callback:
            self.add_to_playlist_callback(videos)

    def _context_add_to_favourites(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        if self.add_to_favourites_callback:
            self.add_to_favourites_callback(videos)

    def _context_remove_from_favourites(self):
        # Include all selected (even excluded) for removal
        videos = [
            it['path'] for it in self.items
            if it['type'] == 'video' and it['path'] in self.selected_items
        ]
        if not videos:
            return
        if self.remove_from_favourites_callback:
            self.remove_from_favourites_callback(videos)

    def _context_add_to_queue(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        if self.add_to_queue_callback:
            self.add_to_queue_callback(videos)

    def _context_play_in_dual_player(self, slot: int):
        videos = self._get_selected_videos()
        if not videos:
            return
        if slot == 1 and self.play_in_dual_player1_callback:
            self.play_in_dual_player1_callback(videos)
        elif slot == 2 and self.play_in_dual_player2_callback:
            self.play_in_dual_player2_callback(videos)
        elif slot == 3 and self.play_in_dual_player3_callback:
            self.play_in_dual_player3_callback(videos)

    def _context_play_in_dual_player_win2(self, slot: int):
        videos = self._get_selected_videos()
        if not videos:
            return
        if slot == 1 and self.play_in_dual_player_win2_1_callback:
            self.play_in_dual_player_win2_1_callback(videos)
        elif slot == 2 and self.play_in_dual_player_win2_2_callback:
            self.play_in_dual_player_win2_2_callback(videos)
        elif slot == 3 and self.play_in_dual_player_win2_3_callback:
            self.play_in_dual_player_win2_3_callback(videos)

    def _context_open_file_location(self, file_path):
        file_path = os.path.normpath(file_path)
        if self.open_file_location_callback:
            self.open_file_location_callback(file_path)
            return
        # Fallback: mirrors build_app._context_open_location
        try:
            import subprocess, sys as _sys
            if os.name == 'nt':
                subprocess.Popen(f'explorer /select,"{file_path}"')
            elif os.name == 'posix':
                if _sys.platform == 'darwin':
                    subprocess.Popen(['open', '-R', file_path])
                else:
                    subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
        except Exception as e:
            if self.console_callback:
                self.console_callback(f"Error opening file location: {e}")

    def _context_show_properties(self, file_path):
        if self.show_properties_callback:
            self.show_properties_callback(file_path)
            return
        # Fallback: mirrors build_app._context_show_properties
        try:
            from datetime import datetime as _dt
            stat_info = os.stat(file_path)
            size_mb = stat_info.st_size / (1024 * 1024)
            modified = _dt.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            info = f"File: {os.path.basename(file_path)}\n\n"
            info += f"Path: {file_path}\n\n"
            info += f"Size: {size_mb:.2f} MB ({stat_info.st_size:,} bytes)\n\n"
            info += f"Modified: {modified}\n\n"

            try:
                import cv2
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    duration = frame_count / fps if fps > 0 else 0
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    info += f"Duration: {int(duration // 60)}:{int(duration % 60):02d}\n"
                    info += f"Resolution: {width}x{height}\n"
                    info += f"FPS: {fps:.2f}\n"
                    cap.release()
            except Exception:
                pass

            import tkinter.messagebox as _mb
            _mb.showinfo("Properties", info)
        except Exception as e:
            if self.console_callback:
                self.console_callback(f"Error showing properties: {e}")

    def _exclude_selected(self):
        for vp in list(self.selected_items):
            self.excluded_items.add(vp)
            self._update_card_selection(vp)

    def _remove_exclusion_selected(self):
        for vp in list(self.selected_items):
            self.excluded_items.discard(vp)
            self._update_card_selection(vp)

    def _load_thumbnail(self, item, label, video_path_norm=None):
        """Load thumbnail — 3-level cache: LRU RAM → blob file → generate."""
        try:
            with self.loading_lock:
                if not self.is_loading:
                    return
            if video_path_norm is None:
                video_path_norm = os.path.normpath(item.video_path)

            # ── Level 1: LRU in-memory PhotoImage cache (zero I/O) ──────────
            vpm = self.video_preview_manager
            if vpm and hasattr(vpm, 'lru_cache'):
                photo = vpm.lru_cache.get(video_path_norm)
                if photo is not None:
                    self._photo_cache[video_path_norm] = photo
                    self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                    return

            # ── Level 2: blob file on disk (no base64) ───────────────────────
            if vpm:
                th = vpm._thumbnails.get(video_path_norm)
                if th and th.is_valid() and hasattr(th, 'blob_path') and th.blob_path and th.blob_path.exists():
                    photo = self._photo_from_blob(th.blob_path, getattr(th, 'is_video', False), item)
                    if photo:
                        # Populate both caches so future access is instant
                        if hasattr(vpm, 'lru_cache'):
                            vpm.lru_cache.put(video_path_norm, photo)
                        self._photo_cache[video_path_norm] = photo
                        self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                        return
                    # Blob decode failed — fall through to generation
                    # Sentinel-string fallback (old cache entries)
                    if th.thumbnail_data:
                        self._display_thumbnail_from_data(label, th.thumbnail_data, item, video_path_norm)
                        return

                # ── Level 3: generate fresh blob ────────────────────────────
                result = vpm.generator.generate_thumbnail(video_path_norm)
                if result:
                    raw_bytes, is_vid = result
                    try:
                        from managers.video_preview_manager import VideoThumbnail, _file_hash_key
                        ext = ".mp4" if is_vid else ".jpg"
                        hk = _file_hash_key(item.video_path)
                        blob_path = vpm.storage.write_blob(hk, raw_bytes, ext)
                        th_new = VideoThumbnail(item.video_path, blob_path, is_vid, hk)
                        vpm._thumbnails[video_path_norm] = th_new
                        vpm._save_thumbnails()
                        photo = self._photo_from_blob(blob_path, is_vid, item)
                        if photo:
                            if hasattr(vpm, 'lru_cache'):
                                vpm.lru_cache.put(video_path_norm, photo)
                            self._photo_cache[video_path_norm] = photo
                            self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                            return
                    except Exception:
                        pass
                    # Last resort: in-memory sentinel string only
                    import base64
                    prefix = "VIDEO:" if is_vid else "IMAGE:"
                    td = prefix + base64.b64encode(raw_bytes).decode("ascii")
                    self._display_thumbnail_from_data(label, td, item, video_path_norm)
                    return

            self.root.after(0, lambda lbl=label: lbl.winfo_exists() and lbl.configure(text="No Preview"))
        except Exception:
            self.root.after(0, lambda: label.winfo_exists() and label.configure(text="Error"))

    def _photo_from_blob(self, blob_path, is_video, item):
        """Decode a raw JPEG or MP4 blob file directly — no base64 at all."""
        import shutil, tempfile as _tf
        tmp_path = None
        try:
            if is_video:
                fd, tmp_path = _tf.mkstemp(suffix=".mp4")
                os.close(fd)
                shutil.copy2(str(blob_path), tmp_path)
                import cv2 as _cv2
                cap = _cv2.VideoCapture(tmp_path)
                ret, frame = cap.read()
                cap.release()
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                if not ret or frame is None:
                    return None
                frame_resized = _cv2.resize(frame, (240, 135))
                frame_rgb = _cv2.cvtColor(frame_resized, _cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
            else:
                pil_image = Image.open(str(blob_path))
                pil_image.thumbnail((240, 135), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(pil_image)
            item.thumbnail_image = photo
            return photo
        except Exception:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass
            return None

    def _display_thumbnail_from_data(self, label, thumbnail_data, item, video_path_norm=None):
        """Decode a base64 sentinel string ("IMAGE:…" / "VIDEO:…") into a PhotoImage.
        Only called as a fallback when no blob_path is available."""
        import tempfile, base64 as _b64
        tmp_path = None
        try:
            is_vid = thumbnail_data.startswith("VIDEO:")
            raw_b64 = thumbnail_data[6:]   # strip 6-char prefix

            if is_vid:
                video_data = _b64.b64decode(raw_b64)
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf:
                    tf.write(video_data)
                    tmp_path = tf.name
                import cv2 as _cv2
                cap = _cv2.VideoCapture(tmp_path)
                ret, frame = cap.read()
                cap.release()
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                if ret and frame is not None:
                    fr = _cv2.resize(frame, (240, 135))
                    fr_rgb = _cv2.cvtColor(fr, _cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(fr_rgb)
                    photo = ImageTk.PhotoImage(pil_image)
                    item.thumbnail_image = photo
                    if video_path_norm:
                        self._photo_cache[video_path_norm] = photo
                    self.root.after(0, lambda: self._set_thumbnail(label, photo))
                    return
            else:
                image_data = _b64.b64decode(raw_b64)
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
                    tf.write(image_data)
                    tmp_path = tf.name
                img = Image.open(tmp_path)
                img.thumbnail((240, 135), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                item.thumbnail_image = photo
                if video_path_norm:
                    self._photo_cache[video_path_norm] = photo
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                self.root.after(0, lambda: self._set_thumbnail(label, photo))
                return

        except Exception:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass
            self.root.after(0, lambda: label.winfo_exists() and label.configure(text="Error"))

    def _set_thumbnail(self, label, photo):
        try:
            if label.winfo_exists():
                label.configure(image=photo, text="")
                label.image = photo
        except:
            pass

    def _on_hover_enter(self, event, idx):
        if not self.video_preview_manager:
            return

        item = self.items[idx]
        video_path = item.video_path

        if not os.path.isfile(video_path):
            return

        video_path_norm = os.path.normpath(video_path)

        if video_path_norm in self.video_preview_manager._thumbnails:
            thumbnail = self.video_preview_manager._thumbnails[video_path_norm]
            if thumbnail.is_valid() and thumbnail.thumbnail_data:
                self.video_preview_manager.tooltip.show_preview(
                    video_path,
                    thumbnail.thumbnail_data,
                    event.x_root,
                    event.y_root
                )

    def _on_hover_leave(self, event):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _toggle_select(self, video_path):
        if video_path in self.selected_items:
            self.selected_items.remove(video_path)
        else:
            self.selected_items.add(video_path)

        self._update_card_selection(video_path)
        self._update_selection_label()

    def _update_card_selection(self, video_path):
        if video_path not in self.card_widgets:
            return

        card = self.card_widgets[video_path]
        is_selected = video_path in self.selected_items
        is_excluded = video_path in self.excluded_items

        info_frame = None
        name_label = None
        drag_label = None
        thumb_container = None

        for child in card.winfo_children():
            if isinstance(child, tk.Frame):
                if getattr(child, '_is_thumb', False) or (child.cget('bg') == 'black' and not getattr(child, '_is_info', False)):
                    thumb_container = child
                elif getattr(child, '_is_info', False) or (child.cget('bg') != 'black'):
                    info_frame = child
                    for label in child.winfo_children():
                        if isinstance(label, tk.Label):
                            if drag_label is None:
                                name_label = label
                            else:
                                drag_label = label

        if is_selected:
            card.configure(
                bg=self.theme_provider.accent_color,
                highlightbackground=self.theme_provider.accent_color,
                highlightthickness=3
            )
            if info_frame:
                info_frame.configure(bg=self.theme_provider.accent_color)
            if name_label:
                name_label.configure(
                    bg=self.theme_provider.accent_color,
                    fg="white",
                    font=(self.theme_provider.normal_font.actual()['family'], 9, 'bold')
                )
            if drag_label:
                drag_label.configure(bg=self.theme_provider.accent_color)
            if thumb_container:
                thumb_container.configure(
                    highlightbackground=self.theme_provider.accent_color,
                    highlightthickness=2
                )
        elif is_excluded:
            card.configure(
                bg=self.theme_provider.listbox_bg,
                highlightbackground="#cc4444",
                highlightthickness=2
            )
            if info_frame:
                info_frame.configure(bg=self.theme_provider.listbox_bg)
            if name_label:
                name_label.configure(
                    bg=self.theme_provider.listbox_bg,
                    fg="#888888",
                    font=(self.theme_provider.normal_font.actual()['family'], 9, 'normal')
                )
            if drag_label:
                drag_label.configure(bg=self.theme_provider.listbox_bg)
            if thumb_container:
                thumb_container.configure(
                    highlightbackground="#cc4444",
                    highlightthickness=0
                )
            self._refresh_excluded_badge(thumb_container, is_excluded=True)
        else:
            card.configure(
                bg=self.theme_provider.listbox_bg,
                highlightbackground=self.theme_provider.frame_border,
                highlightthickness=1
            )
            if info_frame:
                info_frame.configure(bg=self.theme_provider.listbox_bg)
            if name_label:
                name_label.configure(
                    bg=self.theme_provider.listbox_bg,
                    fg=self.theme_provider.text_color,
                    font=(self.theme_provider.normal_font.actual()['family'], 9, 'normal')
                )
            if drag_label:
                drag_label.configure(bg=self.theme_provider.listbox_bg)
            if thumb_container:
                thumb_container.configure(
                    highlightbackground=self.theme_provider.frame_border,
                    highlightthickness=0
                )
            self._refresh_excluded_badge(thumb_container, is_excluded=False)

    def _refresh_excluded_badge(self, thumb_container, is_excluded):
        if thumb_container is None:
            return
        for child in thumb_container.winfo_children():
            if isinstance(child, tk.Label) and getattr(child, '_is_excluded_badge', False):
                child.destroy()
        if is_excluded:
            badge = tk.Label(
                thumb_container,
                text="🚫 Excluded",
                bg="#aa0000",
                fg="white",
                font=(self.theme_provider.small_font.actual()['family'], 8, 'bold'),
                padx=4, pady=2
            )
            badge._is_excluded_badge = True
            badge.place(relx=0.0, rely=0.0, anchor='nw')

    def _select_all(self):
        page_items = self._pages_cache[self._page] if hasattr(self, '_pages_cache') and self._pages_cache else self.items
        for item_data in page_items:
            if item_data['type'] == 'video':
                video_path = item_data['path']
                self.selected_items.add(video_path)
                self._update_card_selection(video_path)
        self._update_selection_label()

    def _clear_selection(self):
        old_selection = self.selected_items.copy()
        self.selected_items.clear()
        for video_path in old_selection:
            self._update_card_selection(video_path)
        self._update_selection_label()

    def _play_selected(self):
        if not self.selected_items:
            return
        videos = [it['path'] for it in self.items
                  if it['type'] == 'video'
                  and it['path'] in self.selected_items
                  and it['path'] not in self.excluded_items]
        if not videos:
            return
        if self.play_callback:
            self.play_callback(videos)

    def _play_single(self, video_path):
        old_selection = self.selected_items.copy()
        self.selected_items = {video_path}

        for old_path in old_selection:
            if old_path != video_path:
                self._update_card_selection(old_path)

        if video_path not in old_selection:
            self._update_card_selection(video_path)

        self._update_selection_label()
        self._play_selected()