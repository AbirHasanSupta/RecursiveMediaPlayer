import tkinter as tk
from PIL import Image, ImageTk
import os
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing

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
        self.thumbnail_executor = ThreadPoolExecutor(max_workers=max_workers)
        self.grid_window = None
        self.items = []
        self.selected_items = set()
        self.card_widgets = {}
        self.play_callback = None

    def set_play_callback(self, callback):
        self.play_callback = callback

    def show_grid_view(self, videos, video_preview_manager=None):
        if self.grid_window and self.grid_window.winfo_exists():
            self.grid_window.lift()
            return

        self.grid_window = tk.Toplevel(self.root)
        self.grid_window.title("Grid View - Video Gallery")
        self.grid_window.geometry("1400x900")
        self.grid_window.configure(bg=self.theme_provider.bg_color)

        self.items = []
        self.selected_items = set()

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
            bg="white",
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
            "secondary",
            "sm"
        )
        select_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        clear_btn = self.theme_provider.create_button(
            left_toolbar,
            "Clear Selection",
            self._clear_selection,
            "secondary",
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
            "lg"
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
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))


        self.grid_window.bind("<Control-a>", lambda e: self._select_all())
        self.grid_window.bind("<Escape>", lambda e: self._clear_selection())
        self.grid_window.bind("<Delete>", lambda e: self._clear_selection())
        self.grid_window.bind("<Return>", lambda e: self._play_selected())

        def on_closing():
            if hasattr(self, 'thumbnail_executor'):
                self.thumbnail_executor.shutdown(wait=False, cancel_futures=True)
            self.grid_window.destroy()
            self.grid_window = None

        self.grid_window.protocol("WM_DELETE_WINDOW", on_closing)

        self.canvas = canvas
        self.video_preview_manager = video_preview_manager

        threading.Thread(target=self._load_videos, args=(videos,), daemon=True).start()

    def _load_videos(self, videos):
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

        self.root.after(0, self._rebuild_grid)

    def _filter_directories(self):
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

        grid_row = -1
        video_col = 0

        for idx, item_data in enumerate(self.items):
            if item_data['type'] == 'header':
                grid_row += 1
                video_col = 0

                header = tk.Frame(
                    self.grid_frame,
                    bg=self.theme_provider.bg_color
                )
                header.grid(row=grid_row, column=0, columnspan=cols, sticky='ew', padx=10, pady=(20, 10))

                label_frame = tk.Frame(header, bg=self.theme_provider.bg_color)
                label_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

                tk.Label(
                    label_frame,
                    text=f"📁 {item_data['name']}",
                    font=(self.theme_provider.normal_font.actual()['family'], 11, 'bold'),
                    bg=self.theme_provider.bg_color,
                    fg=self.theme_provider.accent_color,
                    anchor='w'
                ).pack(side=tk.LEFT)

                tk.Label(
                    label_frame,
                    text=f"  •  {item_data.get('video_count', 0)} video{'s' if item_data.get('video_count', 0) != 1 else ''}",
                    font=self.theme_provider.small_font,
                    bg=self.theme_provider.bg_color,
                    fg="#888888",
                    anchor='w'
                ).pack(side=tk.LEFT)

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

            card = tk.Frame(
                self.grid_frame,
                bg=self.theme_provider.accent_color if is_selected else self.theme_provider.listbox_bg,
                relief=tk.FLAT,
                bd=0,
                highlightthickness=3 if is_selected else 1,
                highlightbackground=self.theme_provider.accent_color if is_selected else self.theme_provider.frame_border
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

            self.thumbnail_executor.submit(self._load_thumbnail, item, thumb_label)

            info_frame = tk.Frame(
                card,
                bg=self.theme_provider.accent_color if is_selected else self.theme_provider.listbox_bg,
                pady=8,
                padx=10
            )
            info_frame.pack(fill=tk.X)

            name = os.path.basename(item.video_path)
            if len(name) > 35:
                name = name[:32] + "..."

            name_label = tk.Label(
                info_frame,
                text=name,
                bg=self.theme_provider.accent_color if is_selected else self.theme_provider.listbox_bg,
                fg="white" if is_selected else self.theme_provider.text_color,
                font=(self.theme_provider.normal_font.actual()['family'], 9, 'bold' if is_selected else 'normal'),
                anchor='w',
                justify=tk.LEFT
            )
            name_label.pack(fill=tk.X)

            for widget in [card, thumb_container, thumb_label, name_label, info_frame]:
                widget.bind("<Button-1>", lambda e, vp=video_path: self._toggle_select(vp))
                widget.bind("<Button-3>", lambda e, vp=video_path: self._show_context_menu(e, vp))
                widget.bind("<Double-Button-1>", lambda e, vp=video_path: self._play_single(vp))

            video_col += 1
            if video_col >= cols:
                video_col = 0
                grid_row += 1

        for i in range(cols):
            self.grid_frame.columnconfigure(i, weight=1, uniform="col")

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

    def _show_context_menu(self, event, video_path):
        context_menu = tk.Menu(self.grid_window, tearoff=0)

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

        context_menu.add_command(
            label="Select All",
            command=self._select_all
        )

        context_menu.add_command(
            label="Clear Selection",
            command=self._clear_selection
        )

        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def _load_thumbnail(self, item, label):
        try:
            if self.video_preview_manager:
                video_path_norm = os.path.normpath(item.video_path)

                if video_path_norm in self.video_preview_manager._thumbnails:
                    thumbnail = self.video_preview_manager._thumbnails[video_path_norm]
                    if thumbnail.is_valid() and thumbnail.thumbnail_data:
                        self._display_thumbnail_from_data(label, thumbnail.thumbnail_data, item)
                        return

                thumbnail_data = self.video_preview_manager.generator.generate_thumbnail(item.video_path)

                if thumbnail_data:
                    from managers.video_preview_manager import VideoThumbnail
                    thumbnail = VideoThumbnail(item.video_path, thumbnail_data)
                    self.video_preview_manager._thumbnails[video_path_norm] = thumbnail
                    self.video_preview_manager._save_thumbnails()

                    self._display_thumbnail_from_data(label, thumbnail_data, item)
                    return

            self.root.after(0, lambda: label.configure(text="No Preview"))
        except Exception as e:
            self.root.after(0, lambda: label.configure(text="Error"))

    def _display_thumbnail_from_data(self, label, thumbnail_data, item):
        try:
            import tempfile
            import base64

            is_video = thumbnail_data.startswith("VIDEO:")

            if is_video:
                image_b64 = thumbnail_data[6:] if thumbnail_data.startswith("IMAGE:") else \
                thumbnail_data.split("IMAGE:")[-1] if "IMAGE:" in thumbnail_data else None
                if not image_b64:
                    video_b64 = thumbnail_data[6:]
                    video_data = base64.b64decode(video_b64)

                    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                        temp_file.write(video_data)
                        temp_path = temp_file.name

                    import cv2
                    cap = cv2.VideoCapture(temp_path)
                    ret, frame = cap.read()
                    cap.release()

                    try:
                        os.unlink(temp_path)
                    except:
                        pass

                    if ret and frame is not None:
                        frame_resized = cv2.resize(frame, (190, 140))
                        frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                        pil_image = Image.fromarray(frame_rgb)
                        photo = ImageTk.PhotoImage(pil_image)
                        item.thumbnail_image = photo
                        self.root.after(0, lambda: self._set_thumbnail(label, photo))
                        return

            image_b64 = thumbnail_data[6:] if thumbnail_data.startswith("IMAGE:") else thumbnail_data
            image_data = base64.b64decode(image_b64)

            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_file.write(image_data)
                temp_path = temp_file.name

            img = Image.open(temp_path)
            img.thumbnail((190, 140), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            item.thumbnail_image = photo

            try:
                os.unlink(temp_path)
            except:
                pass

            self.root.after(0, lambda: self._set_thumbnail(label, photo))

        except Exception as e:
            self.root.after(0, lambda: label.configure(text="Error"))

    def _set_thumbnail(self, label, photo):
        try:
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

        info_frame = None
        name_label = None
        thumb_container = None

        for child in card.winfo_children():
            if isinstance(child, tk.Frame):
                if child.cget('bg') == 'black' or 'highlightbackground' in child.keys():
                    thumb_container = child
                else:
                    info_frame = child
                    for label in child.winfo_children():
                        if isinstance(label, tk.Label):
                            name_label = label

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
            if thumb_container:
                thumb_container.configure(
                    highlightbackground=self.theme_provider.accent_color,
                    highlightthickness=2
                )
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
            if thumb_container:
                thumb_container.configure(
                    highlightbackground=self.theme_provider.frame_border,
                    highlightthickness=0
                )

    def _select_all(self):
        for item_data in self.items:
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
        videos = sorted(list(self.selected_items))
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