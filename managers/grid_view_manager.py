import tkinter as tk
from PIL import Image, ImageTk
import os
import threading

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
        self.grid_window = None
        self.items = []
        self.selected_items = set()
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
            text="Video Gallery",
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
            self.grid_window.destroy()
            self.grid_window = None

        self.grid_window.protocol("WM_DELETE_WINDOW", on_closing)

        self.canvas = canvas
        self.video_preview_manager = video_preview_manager

        threading.Thread(target=self._load_videos, args=(videos,), daemon=True).start()

    def _load_videos(self, videos):
        for video in videos:
            item = GridViewItem(video)
            self.items.append(item)

        self.root.after(0, self._rebuild_grid)

    def _rebuild_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

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

        for idx, item in enumerate(self.items):
            row = idx // cols
            col = idx % cols

            card = tk.Frame(
                self.grid_frame,
                bg=self.theme_provider.listbox_bg,
                relief=tk.FLAT,
                bd=0
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky='nsew')

            thumb_container = tk.Frame(
                card,
                bg="black",
                width=220,
                height=165,
                highlightbackground="#e0e0e0",
                highlightthickness=1
            )
            thumb_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
            thumb_container.pack_propagate(False)

            thumb_label = tk.Label(
                thumb_container,
                bg="black",
                fg="white",
                text="Loading...",
                font=self.theme_provider.small_font
            )
            thumb_label.pack(expand=True)

            threading.Thread(target=self._load_thumbnail, args=(item, thumb_label), daemon=True).start()

            info_frame = tk.Frame(card, bg=self.theme_provider.listbox_bg)
            info_frame.pack(fill=tk.X, padx=8, pady=8)

            name_label = tk.Label(
                info_frame,
                text=os.path.basename(item.video_path),
                bg=self.theme_provider.listbox_bg,
                fg=self.theme_provider.text_color,
                wraplength=200,
                font=self.theme_provider.normal_font,
                anchor='w',
                justify=tk.LEFT
            )
            name_label.pack(fill=tk.X)

            if idx in self.selected_items:
                card.configure(
                    bg=self.theme_provider.accent_color,
                    highlightbackground=self.theme_provider.accent_color,
                    highlightthickness=3,
                    relief=tk.SOLID
                )
                info_frame.configure(bg=self.theme_provider.accent_color)
                name_label.configure(
                    bg=self.theme_provider.accent_color,
                    fg="white",
                    font=(self.theme_provider.normal_font.actual()['family'],
                          self.theme_provider.normal_font.actual()['size'],
                          'bold')
                )
                thumb_container.configure(
                    highlightbackground=self.theme_provider.accent_color,
                    highlightthickness=2
                )
            else:
                card.configure(
                    highlightbackground="#e0e0e0",
                    highlightthickness=1
                )

            card.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            thumb_label.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            name_label.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))
            info_frame.bind("<Button-1>", lambda e, i=idx: self._toggle_select(i))

            card.bind("<Button-3>", lambda e, i=idx: self._show_context_menu(e, i))
            thumb_label.bind("<Button-3>", lambda e, i=idx: self._show_context_menu(e, i))
            name_label.bind("<Button-3>", lambda e, i=idx: self._show_context_menu(e, i))
            info_frame.bind("<Button-3>", lambda e, i=idx: self._show_context_menu(e, i))

            card.bind("<Double-Button-1>", lambda e, i=idx: self._play_single(i))
            thumb_label.bind("<Double-Button-1>", lambda e, i=idx: self._play_single(i))
            name_label.bind("<Double-Button-1>", lambda e, i=idx: self._play_single(i))
            info_frame.bind("<Double-Button-1>", lambda e, i=idx: self._play_single(i))

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

    def _show_context_menu(self, event, idx):
        context_menu = tk.Menu(self.grid_window, tearoff=0)

        if idx in self.selected_items:
            context_menu.add_command(
                label=f"Play Selected ({len(self.selected_items)} items)",
                command=self._play_selected
            )
        else:
            context_menu.add_command(
                label="Play This Video",
                command=lambda: self._play_single(idx)
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

    def _toggle_select(self, idx):
        if idx in self.selected_items:
            self.selected_items.remove(idx)
        else:
            self.selected_items.add(idx)

        self._update_card_selection(idx)
        self._update_selection_label()

    def _update_card_selection(self, idx):
        cols = self.grid_size_var.get()
        row = idx // cols
        col = idx % cols

        for widget in self.grid_frame.winfo_children():
            if isinstance(widget, tk.Frame):
                grid_info = widget.grid_info()
                if grid_info and grid_info.get('row') == row and grid_info.get('column') == col:
                    is_selected = idx in self.selected_items

                    info_frame = None
                    name_label = None
                    thumb_container = None

                    for child in widget.winfo_children():
                        if isinstance(child, tk.Frame):
                            if child.cget('bg') == 'black' or 'highlightbackground' in child.keys():
                                thumb_container = child
                            else:
                                info_frame = child
                                for label in child.winfo_children():
                                    if isinstance(label, tk.Label):
                                        name_label = label

                    if is_selected:
                        widget.configure(
                            bg=self.theme_provider.accent_color,
                            highlightbackground=self.theme_provider.accent_color,
                            highlightthickness=3,
                            relief=tk.SOLID
                        )
                        if info_frame:
                            info_frame.configure(bg=self.theme_provider.accent_color)
                        if name_label:
                            name_label.configure(
                                bg=self.theme_provider.accent_color,
                                fg="white",
                                font=(self.theme_provider.normal_font.actual()['family'],
                                      self.theme_provider.normal_font.actual()['size'],
                                      'bold')
                            )
                        if thumb_container:
                            thumb_container.configure(
                                highlightbackground=self.theme_provider.accent_color,
                                highlightthickness=2
                            )
                    else:
                        widget.configure(
                            bg=self.theme_provider.listbox_bg,
                            highlightbackground="#e0e0e0",
                            highlightthickness=1,
                            relief=tk.FLAT
                        )
                        if info_frame:
                            info_frame.configure(bg=self.theme_provider.listbox_bg)
                        if name_label:
                            name_label.configure(
                                bg=self.theme_provider.listbox_bg,
                                fg=self.theme_provider.text_color,
                                font=self.theme_provider.normal_font
                            )
                        if thumb_container:
                            thumb_container.configure(
                                highlightbackground="#e0e0e0",
                                highlightthickness=1
                            )
                    break

    def _select_all(self):
        self.selected_items = set(range(len(self.items)))
        for idx in range(len(self.items)):
            self._update_card_selection(idx)
        self._update_selection_label()

    def _clear_selection(self):
        old_selection = self.selected_items.copy()
        self.selected_items.clear()
        for idx in old_selection:
            self._update_card_selection(idx)
        self._update_selection_label()

    def _play_selected(self):
        if not self.selected_items:
            return
        videos = [self.items[i].video_path for i in sorted(self.selected_items)]
        if self.play_callback:
            self.play_callback(videos)

    def _play_single(self, idx):
        old_selection = self.selected_items.copy()
        self.selected_items = {idx}

        for old_idx in old_selection:
            if old_idx != idx:
                self._update_card_selection(old_idx)

        if idx not in old_selection:
            self._update_card_selection(idx)

        self._play_selected()