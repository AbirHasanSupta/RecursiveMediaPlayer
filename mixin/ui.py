try:
    from version import __version__, __commit__, __build__
except ImportError:
    __version__ = __commit__ = __build__ = "dev"
import os
import random as _random
from datetime import datetime, timedelta
from tkinter import ttk
from tkinter.font import Font
import tkinter as tk

from managers.resource_manager import ManagedThread
from mixin.theme_core import ThemeCoreMixin


class UIMixin:
    def setup_theme(self):
        # Dashboard-aligned palette (apply_theme refines for dark mode)
        self.bg_color = "#F7F9FC"
        self.surface_color = "#FFFFFF"
        self.accent_color = "#5E81F4"
        self.accent_secondary = "#FF6B6B"
        self.text_color = "#1E2A3A"
        self.text_muted = "#5B6C8F"
        self.border_color = "#E2E8F0"
        self.hover_color = "#EDF2F7"
        self.listbox_bg = "#FFFFFF"
        self.listbox_fg = self.text_color
        self.listbox_select_bg = self.accent_color
        self.console_bg = "#1E2A3A"
        self.console_fg = "#F7F9FC"
        self.frame_border = self.border_color
        self.header_color = self.text_color
        self.entry_bg = "#FFFFFF"
        self.entry_fg = self.text_color
        self.entry_border = "#E2E8F0"
        self.muted_fg = self.text_muted
        self.alt_row_color = "#F7F9FC"
        self.badge_bg = "#EDF2F7"
        self.badge_fg = self.text_color
        self.divider_color = "#E2E8F0"
        self.excluded_color = "#C44A4A"
        self.favorite_color = "#8F6B08"

        style = ttk.Style()
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
        style.configure(
            "Modern.TCheckbutton",
            background=self.bg_color,
            foreground=self.text_color,
            font=("Segoe UI", 10),
            padding=4
        )
        style.map(
            "Modern.TCheckbutton",
            foreground=[("active", self.text_color)],
            background=[("active", self.bg_color)]
        )

        self.create_custom_buttons()

        self.header_font = Font(family="Segoe UI", size=12, weight="bold")
        self.normal_font = Font(family="Segoe UI", size=10)
        self.small_font = Font(family="Segoe UI", size=9)
        self.mono_font = Font(family="Consolas", size=9)
        self.tree_font = Font(family="Segoe UI", size=10)
        self.tree_font_bold = Font(family="Segoe UI", size=10, weight="bold")
        self.tree_font_italic = Font(family="Segoe UI", size=10, slant="italic")
        self.tree_font_excl_video = Font(
            family="Segoe UI", size=10, slant="italic", overstrike=True)

    def create_custom_buttons(self):
        self.button_variants = {
            "primary": {"bg": "#2d89ef", "fg": "white", "active": "#1e70cf"},
            "success": {"bg": "#27ae60", "fg": "white", "active": "#229954"},
            "danger": {"bg": "#e74c3c", "fg": "white", "active": "#c0392b"},
            "warning": {"bg": "#f39c12", "fg": "white", "active": "#e67e22"},
            "secondary": {"bg": "#95a5a6", "fg": "white", "active": "#7f8c8d"},
            "dark": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"}
        }
        self.button_bg = self.button_variants["primary"]["bg"]
        self.button_fg = self.button_variants["primary"]["fg"]
        self.button_active_bg = self.button_variants["primary"]["active"]
        self.accent_button_bg = self.button_variants["danger"]["bg"]
        self.accent_button_fg = self.button_variants["danger"]["fg"]
        self.accent_button_active_bg = self.button_variants["danger"]["active"]

    def create_button(self, parent, text, command, variant="primary", size="md", font=None):
        colors = self.get_button_colors(variant)
        bg = colors["bg"]
        fg = colors["fg"]
        active_bg = colors["active"]

        if font is None:
            if size == "sm":
                use_font = self.small_font
                padx, pady = 12, 6
            elif size == "lg":
                use_font = Font(family=self.normal_font.actual().get("family", "Segoe UI"),
                                size=self.normal_font.actual().get("size", 10) + 2,
                                weight="bold")
                padx, pady = 16, 10
            else:
                use_font = self.normal_font
                padx, pady = 14, 8
        else:
            use_font = font
            padx, pady = (14, 8) if size == "md" else ((12, 6) if size == "sm" else (16, 10))

        btn = tk.Button(
            parent, text=text, command=command, font=use_font,
            bg=bg, fg=fg, activebackground=active_bg, activeforeground=fg,
            relief=tk.FLAT, bd=0, padx=padx, pady=pady,
            cursor="hand2", highlightthickness=0
        )
        btn._variant = variant
        self._bind_button_hover(btn, variant)
        return btn

    def apply_theme(self):
        dir_w = self.dir_section.winfo_width() if hasattr(self, 'dir_section') else 0

        ThemeCoreMixin.apply_theme(self)

        self._reapply_tree_columns()

        if dir_w > 10:
            self.dir_section.config(width=dir_w)
            self.dir_section.pack_propagate(False)

    def _reapply_tree_columns(self):
        if not hasattr(self, 'exclusion_tree'):
            return
        self.exclusion_tree.configure(columns=())
        self.exclusion_tree.column("#0", minwidth=200, stretch=True, anchor="w")

    def setup_main_layout(self):
        self._active_app_view = "home"
        self.active_embedded_manager = None
        self.embedded_view_frame = None
        self._directory_panel_mode = "expanded"
        self._dir_panel_width = 380
        self.main_frame = tk.Frame(self.root, bg=self.bg_color, padx=16, pady=14)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.content_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        self.content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        self._sidebar_panel = tk.Frame(self.content_frame, bg=self.surface_color, width=48)
        self._sidebar_panel.pack(side=tk.LEFT, fill=tk.Y)
        self._sidebar_panel.pack_propagate(False)
        self._sidebar_divider = tk.Frame(self.content_frame, bg=self.border_color, width=1)
        self._sidebar_divider.pack(side=tk.LEFT, fill=tk.Y)

        self.workspace_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        self.workspace_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.workspace_header = tk.Frame(self.workspace_frame, bg=self.bg_color)
        self.workspace_header.pack(fill=tk.X, pady=(0, 10))

        title_block = tk.Frame(self.workspace_header, bg=self.bg_color)
        title_block.pack(side=tk.LEFT, fill=tk.Y)
        self.workspace_title_label = tk.Label(
            title_block, text="Home", font=self.header_font,
            bg=self.bg_color, fg=self.text_color
        )
        # title label intentionally not packed — each view has its own header
        self.workspace_context_label = tk.Label(
            title_block, text="Welcome to Recursive Video Player",
            font=self.normal_font, bg=self.bg_color, fg=self.text_muted
        )
        self.workspace_context_label.pack(anchor="w", pady=(4, 0))

        self.workspace_nav = tk.Frame(self.workspace_header, bg=self.bg_color)
        self.workspace_nav.pack(side=tk.RIGHT, anchor="e")

        # Global Search Bar in workspace header
        self._setup_global_search_bar(self.workspace_nav)

        self.workspace_body = tk.Frame(self.workspace_frame, bg=self.bg_color)
        self.workspace_body.pack(fill=tk.BOTH, expand=True)

    def setup_console_section(self):
        self.console_section = tk.Frame(self.main_frame, bg=self.bg_color)
        if self.show_console:
            self.console_section.pack(fill=tk.X, pady=(0, 15))
        console_section = self.console_section

        self.console_header_frame = tk.Frame(console_section, bg=self.bg_color)
        self.console_header_frame.pack(fill=tk.X, pady=(0, 10))
        console_header_frame = self.console_header_frame

        self.console_header_label = tk.Label(console_header_frame, text="Player Console",
                                             font=self.header_font, bg=self.bg_color, fg=self.text_color)
        self.console_header_label.pack(side=tk.LEFT, anchor='w')

        self.clear_console_button = self.create_button(
            console_header_frame, text="Clear", command=self.clear_console,
            variant="dark", size="sm"
        )
        self.clear_console_button.pack(side=tk.LEFT, padx=(10, 0), anchor='w')

        # Outer container with subtle border
        self.console_container = tk.Frame(console_section, bg=self.bg_color,
                                     highlightbackground=self.border_color,
                                     highlightthickness=1, bd=0)
        self.console_container.pack(fill=tk.X, pady=(0, 10))
        console_container = self.console_container

        # Inner padding frame
        self.console_inner_pad = tk.Frame(console_container, bg=self.bg_color, padx=8, pady=8)
        self.console_inner_pad.pack(fill=tk.BOTH, expand=True)
        inner_pad = self.console_inner_pad

        self.console_frame = tk.Frame(inner_pad, bg=self.bg_color)
        self.console_frame.pack(fill=tk.BOTH, expand=True)
        console_frame = self.console_frame

        self.console_scrollbar = tk.Scrollbar(console_frame)
        self.console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.console_text = tk.Text(
            console_frame, height=10, wrap=tk.WORD,
            yscrollcommand=self.console_scrollbar.set,
            font=self.mono_font, bg=self.console_bg, fg=self.console_fg,
            insertbackground=self.console_fg, selectbackground="#214283",
            selectforeground="white", relief=tk.FLAT, bd=0,
            padx=10, pady=10, state=tk.DISABLED
        )
        self.console_text.pack(fill=tk.BOTH, expand=True)
        self.console_scrollbar.config(command=self.console_text.yview)

        self.update_console("Video Player Console Ready")
        self.update_console(f"version:{__version__}  commit:{__commit__}  built:{__build__}")
        self.update_console("Select directories and click 'Play Videos' to start")

    def update_console(self, message):
        def _update():
            self.console_text.config(state=tk.NORMAL)
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.console_text.see(tk.END)
            self.console_text.config(state=tk.DISABLED)
        self.root.after(0, _update)

    def clear_console(self):
        self.console_text.config(state=tk.NORMAL)
        self.console_text.delete(1.0, tk.END)
        self.console_text.config(state=tk.DISABLED)

    def toggle_console(self):
        self.show_console = not self.show_console
        if self.show_console:
            self.console_section.pack(fill=tk.X, pady=(0, 15), before=self.button_frame)
        else:
            self.console_section.pack_forget()
        try:
            self._view_menu.entryconfig(0, label="Hide Console" if self.show_console else "Show Console")
        except Exception:
            pass
        self.save_preferences()

    def setup_directory_section(self):
        self.dir_section = tk.Frame(self.content_frame, bg=self.bg_color)
        self.dir_section.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 0), before=self.workspace_frame)
        self.dir_section.config(width=self._dir_panel_width)
        self.dir_section.pack_propagate(False)

        self._dir_resizer = tk.Frame(self.content_frame, bg=self.border_color, width=4, cursor="sb_h_double_arrow")
        self._dir_resizer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), before=self.workspace_frame)
        self._dir_resizer.pack_propagate(False)

        self._dir_resizer_dragging = False
        self._dir_resizer_start_x = 0
        self._dir_resizer_start_w = 0

        def _on_resizer_enter(e):
            self._dir_resizer.config(bg=self.accent_color)

        def _on_resizer_leave(e):
            self._dir_resizer.config(bg=self.border_color if not self._dir_resizer_dragging else self.accent_color)

        def _on_resizer_press(e):
            self._dir_resizer_dragging = True
            self._dir_resizer_start_x = e.x_root
            self._dir_resizer_start_w = self.dir_section.winfo_width()
            self._dir_resizer.config(bg=self.accent_color)

        def _on_resizer_drag(e):
            if not self._dir_resizer_dragging:
                return
            delta = e.x_root - self._dir_resizer_start_x
            new_w = max(83, min(700, self._dir_resizer_start_w + delta))
            self._dir_panel_width = new_w
            self.dir_section.config(width=new_w)

        def _on_resizer_release(e):
            self._dir_resizer_dragging = False
            self._dir_resizer.config(bg=self.border_color)

        self._dir_resizer.bind("<Enter>", _on_resizer_enter)
        self._dir_resizer.bind("<Leave>", _on_resizer_leave)
        self._dir_resizer.bind("<ButtonPress-1>", _on_resizer_press)
        self._dir_resizer.bind("<B1-Motion>", _on_resizer_drag)
        self._dir_resizer.bind("<ButtonRelease-1>", _on_resizer_release)

        self._sb_toggle_btn = self._create_sidebar_icon_btn(
            self._sidebar_panel, "◁", self._toggle_directory_panel, tooltip="Toggle Panel")
        self._sb_toggle_btn.pack(fill=tk.X, pady=(12, 0))

        self._sb_add_btn = self._create_sidebar_icon_btn(
            self._sidebar_panel, "+", self.add_directory, tooltip="Add Directory")
        self._sb_add_btn.pack(fill=tk.X, pady=(2, 0))

        dir_header_frame = tk.Frame(self.dir_section, bg=self.bg_color)
        dir_header_frame.pack(fill=tk.X, pady=(0, 6))

        self.dir_header_label = tk.Label(dir_header_frame, text="Directories",
                                         font=self.header_font, bg=self.bg_color, fg=self.text_color)
        self.dir_header_label.pack(side=tk.LEFT, anchor='w')

        _tree_actions = [
            ("▤", "Toggle Videos", self.toggle_videos_visibility),
            ("⊟", "Collapse All", self._collapse_all_tree_nodes),
            ("⊞", "Expand All", self._expand_all_tree_nodes),
            ("⊡", "Open in Gallery", self._show_grid_view),
            ("−", "Hide Panel", self._toggle_directory_panel),
        ]
        self._dir_action_btns = {}
        for icon, tip, cmd in reversed(_tree_actions):
            b = self._create_panel_action_btn(dir_header_frame, icon, cmd, tip)
            b.pack(side=tk.RIGHT, padx=(0, 2))
            self._dir_action_btns[tip] = b

        self._refresh_dir_action_states()

        # Search bar
        search_wrap = tk.Frame(
            self.dir_section,
            bg=self.entry_bg,
            highlightbackground=self.entry_border,
            highlightthickness=1,
        )
        search_wrap.pack(fill=tk.X, pady=(0, 6), padx=6)

        search_icon = tk.Label(
            search_wrap, text="⌕",
            bg=self.entry_bg, fg=self.text_muted,
            font=("Segoe UI", 11), padx=6, pady=0,
        )
        search_icon.pack(side=tk.LEFT)

        self.search_entry = tk.Entry(
            search_wrap,
            font=self.small_font,
            bg=self.entry_bg, fg=self.entry_fg,
            relief=tk.FLAT, bd=0,
            highlightthickness=0,
            insertbackground=self.accent_color,
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)
        self.search_entry.bind('<KeyRelease>', self.on_search_changed)

        def _search_focus_in(e):
            search_wrap.config(highlightbackground=self.accent_color, highlightthickness=1)
            search_icon.config(fg=self.accent_color)

        def _search_focus_out(e):
            search_wrap.config(highlightbackground=self.entry_border, highlightthickness=1)
            search_icon.config(fg=self.text_muted)

        self.search_entry.bind('<FocusIn>', _search_focus_in)
        self.search_entry.bind('<FocusOut>', _search_focus_out)
        self._search_wrap = search_wrap
        self._search_icon = search_icon

        self.dir_frame = tk.Frame(self.dir_section, bg=self.bg_color)
        self.dir_frame.pack(fill=tk.BOTH, expand=True)

        self.dir_tree_container = tk.Frame(
            self.dir_frame, bg=self.listbox_bg,
            highlightbackground=self.border_color, highlightthickness=1)
        self.dir_tree_container.pack(fill=tk.BOTH, expand=True)

        self.exclusion_scrollbar = ttk.Scrollbar(
            self.dir_tree_container, orient=tk.VERTICAL,
            style="ExclusionTree.Vertical.TScrollbar")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "ExclusionTree.Vertical.TScrollbar",
            gripcount=0,
            borderwidth=0,
            relief="flat",
            arrowsize=10,
            width=5
        )

        self.exclusion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.exclusion_tree = ttk.Treeview(
            self.dir_tree_container,
            style="ExclusionTree.Treeview",
            selectmode="extended",
            show="tree",
            columns=(),
            yscrollcommand=self.exclusion_scrollbar.set,
        )
        self.exclusion_scrollbar.config(command=self.exclusion_tree.yview)
        self.exclusion_tree.column("#0", minwidth=200, stretch=True, anchor="w")
        self.exclusion_tree.pack(fill=tk.BOTH, expand=True)

        # Shim: dir_listbox API backed by dir_tree iid->root-dir mapping
        self._dir_root_iids = []   # ordered list of iids for root dirs
        self._dir_iid_selected = set()
        self._dir_iid_counter = 0
        self._tree_iid_counter = 0
        self._dir_iid_selected = set()

        class _DirListboxShim:
            def __init__(shim, owner):
                shim.owner = owner

            def insert(shim, pos, display_name):
                idx = len(shim.owner._dir_root_iids)
                iid = f"__root_{shim.owner._dir_iid_counter}__"
                shim.owner._dir_iid_counter += 1
                shim.owner._dir_root_iids.append(iid)
                shim.owner.exclusion_tree.insert(
                    "", tk.END, iid=iid,
                    text=f"📁 {display_name}", tags=("folder",), open=False
                )
                shim.owner.current_subdirs_mapping[iid] = shim.owner.selected_dirs[idx] if idx < len(
                    shim.owner.selected_dirs) else display_name

            def delete(shim, index):
                if 0 <= index < len(shim.owner._dir_root_iids):
                    iid = shim.owner._dir_root_iids.pop(index)
                    # Collect all descendant iids before deleting
                    def _collect_all(parent):
                        result = []
                        try:
                            for child in shim.owner.exclusion_tree.get_children(parent):
                                result.append(child)
                                result.extend(_collect_all(child))
                        except Exception:
                            pass
                        return result
                    descendants = _collect_all(iid)
                    try:
                        shim.owner.exclusion_tree.delete(iid)
                    except Exception:
                        pass
                    for d in descendants + [iid]:
                        if d in shim.owner.current_subdirs_mapping:
                            del shim.owner.current_subdirs_mapping[d]

            def curselection(shim):
                sel = list(shim.owner.exclusion_tree.selection())
                result = []
                for iid in sel:
                    if iid in shim.owner._dir_root_iids:
                        result.append(shim.owner._dir_root_iids.index(iid))
                return tuple(sorted(set(result)))

            def selection_clear(shim, first, last=None):
                if last is None:
                    try:
                        shim.owner.exclusion_tree.selection_remove(shim.owner._dir_root_iids[first])
                    except Exception:
                        pass
                else:
                    for i in range(first, min(last + 1, len(shim.owner._dir_root_iids))):
                        try:
                            shim.owner.exclusion_tree.selection_remove(shim.owner._dir_root_iids[i])
                        except Exception:
                            pass

            def selection_set(shim, index):
                if 0 <= index < len(shim.owner._dir_root_iids):
                    shim.owner.exclusion_tree.selection_add(shim.owner._dir_root_iids[index])

            def activate(shim, index):
                if 0 <= index < len(shim.owner._dir_root_iids):
                    shim.owner.exclusion_tree.focus(shim.owner._dir_root_iids[index])

            def nearest(shim, y):
                iid = shim.owner.exclusion_tree.identify_row(y)
                if iid and iid in shim.owner._dir_root_iids:
                    return shim.owner._dir_root_iids.index(iid)
                return -1

            def size(shim):
                return len(shim.owner._dir_root_iids)

            def get(shim, index):
                if 0 <= index < len(shim.owner._dir_root_iids):
                    iid = shim.owner._dir_root_iids[index]
                    return shim.owner.exclusion_tree.item(iid, "text")
                return ""

            def yview(shim):
                return shim.owner.exclusion_tree.yview()

            def bind(shim, *args, **kwargs):
                pass  # bindings handled on exclusion_tree directly

            def configure(shim, **kwargs):
                pass  # tree is a Treeview; theme applies via _configure_tree_style

            config = configure  # tk alias

        self.dir_listbox = _DirListboxShim(self)

        # Bind events on the tree
        self._selection_anchor = None
        self.exclusion_tree.bind("<Button-1>", self._on_tree_left_click_unified)
        self.exclusion_tree.bind("<Double-Button-1>", self._on_double_click)
        self.exclusion_tree.bind("<Button-3>", self._on_tree_right_click_unified)
        self.exclusion_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.exclusion_tree.bind("<<TreeviewClose>>", self._on_tree_close)
        self.exclusion_tree.bind("<Control-a>",
                                 lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[1])
        self.exclusion_tree.bind("<Control-A>",
                                 lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[1])
        self.exclusion_tree.bind("<Delete>", self._on_key_toggle_exclusion)
        self.exclusion_tree.bind("<space>", self._on_key_toggle_exclusion)
        self._drag_root_iid = None
        self._drag_start_y = None
        self.exclusion_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.exclusion_tree.bind("<ButtonRelease-1>", self._on_drag_release)

        self._hovered_iid = None

        def _on_tree_motion(e):
            iid = self.exclusion_tree.identify_row(e.y)
            if iid == self._hovered_iid:
                return
            if self._hovered_iid:
                tags = list(self.exclusion_tree.item(self._hovered_iid, "tags"))
                if "hover" in tags:
                    tags.remove("hover")
                    self.exclusion_tree.item(self._hovered_iid, tags=tags)
            self._hovered_iid = iid
            if iid:
                tags = list(self.exclusion_tree.item(iid, "tags"))
                if "hover" not in tags:
                    tags.append("hover")
                    self.exclusion_tree.item(iid, tags=tags)

        def _on_tree_leave(e):
            if self._hovered_iid:
                tags = list(self.exclusion_tree.item(self._hovered_iid, "tags"))
                if "hover" in tags:
                    tags.remove("hover")
                    self.exclusion_tree.item(self._hovered_iid, tags=tags)
            self._hovered_iid = None

        self._tree_hover_motion = _on_tree_motion
        self._tree_hover_leave = _on_tree_leave
        self.exclusion_tree.bind("<Motion>", _on_tree_motion)
        self.exclusion_tree.bind("<Leave>", _on_tree_leave)

        self.exclusion_buttons_frame = tk.Frame(self.dir_section, bg=self.bg_color)
        self.exclusion_buttons_frame.pack(fill=tk.X, pady=(6, 0))

        self.search_frame = tk.Frame(self.dir_section, bg=self.bg_color)  # kept for compat

    def setup_exclusion_section(self):
        self._set_workspace_title("Home", self._selected_directory_summary())

        self._reapply_tree_columns()
        self._configure_tree_style()

        self.show_videos_var = tk.BooleanVar(value=self.show_videos)
        self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
        self.expand_all_var = tk.BooleanVar(value=self.expand_all_default)
        self.save_directories_var = tk.BooleanVar(value=True)
        self.speed_var = tk.DoubleVar(value=1.0)

    def setup_status_section(self):
        pass

    def setup_action_buttons(self):
        self._view_tab_labels = {
            "home": "Home",
            "gallery": "Gallery",
            "playlist": "Playlist",
            "queue": "Queue",
            "favourites": "Favourites",
            "history": "History",
            "tags": "Tags & Ratings",
        }
        # Add emoji variations if needed to match PILL_ACCENTS keys exactly if they were changed
        # But the UI labels in _make_media_pill are "Home", "Gallery", "Playlist", etc.
        # and theme.py uses those same strings.

        def _tb_colors():
            return {
                "bg": self.surface_color,
                "fg": self.text_color,
                "hover": self.hover_color,
                "hover_bg": self.hover_color,
                "hover_fg": self.text_color,
                "active": self.accent_color,
                "border": self.border_color,
                "play_fg": self.accent_secondary,
                "play_hover_bg": "#FF5555",
                "play_active_bg": "#E04444",
                "play_text": self.accent_secondary,
                "play_text_hover": "#FF8A8A" if self.dark_mode else "#E85555",
                "play_text_active": "#A83C3C" if self.dark_mode else "#9E3333",
            }

        self._tb_colors = _tb_colors
        self.toolbar = tk.Frame(self.root, bg=_tb_colors()["bg"])
        self.toolbar.pack_propagate(False)
        self._toolbar_btns = {}
        self._toolbar_menus = {}
        self._toolbar_commands = {}

        for pill_label in ["Home", "Gallery", "Playlist", "Favourites", "Queue", "Tags & Ratings", "History"]:
            self._make_media_pill(pill_label)

        sb = self._sidebar_panel

        def make_dropdown_menu(entries):
            c = _tb_colors()
            menu = tk.Menu(self.root, tearoff=0,
                           bg=c["bg"], fg=c["fg"],
                           activebackground=c["hover"],
                           activeforeground=c["fg"],
                           relief="flat", bd=1, font=("Segoe UI", 10))
            for entry in entries:
                if entry is None:
                    menu.add_separator()
                else:
                    lbl, cmd = entry
                    menu.add_command(label=lbl, command=cmd)
            return menu

        def _sb_sep():
            tk.Frame(sb, bg=self.border_color, height=1).pack(fill=tk.X, padx=10, pady=(5, 5))

        def _sb_btn(icon, tip, menu=None, command=None):
            btn = tk.Label(
                sb, text=icon,
                bg=self.surface_color, fg=self.text_color,
                font=("Segoe UI", 15, "bold"), anchor="center",
                pady=10, cursor="hand2",
                relief=tk.FLAT, bd=0, highlightthickness=0,
            )
            btn.pack(fill=tk.X, pady=(2, 0))
            _tip_win = [None]

            def _show_tip(e):
                if _tip_win[0]: return
                x = btn.winfo_rootx() + btn.winfo_width() + 6
                y = btn.winfo_rooty() + 4
                tw = tk.Toplevel(btn)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                tk.Label(tw, text=tip, bg=self.console_bg, fg=self.console_fg,
                         font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
                _tip_win[0] = tw

            def _hide_tip(e):
                if _tip_win[0]:
                    try: _tip_win[0].destroy()
                    except: pass
                    _tip_win[0] = None

            def on_enter(e):
                btn.config(bg=self.accent_color, fg="#ffffff")
                _show_tip(e)

            def on_leave(e):
                btn.config(bg=self.surface_color, fg=self.text_color)
                _hide_tip(e)

            def on_press(e):
                btn.config(bg=self.accent_color, fg="#ffffff")

            def on_release(e):
                btn.config(bg=self.accent_color, fg="#ffffff")
                if menu is not None:
                    try:
                        menu.tk_popup(btn.winfo_rootx() + btn.winfo_width() + 4, btn.winfo_rooty())
                    finally:
                        menu.grab_release()
                elif command is not None:
                    command()

            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            btn.bind("<ButtonPress-1>", on_press)
            btn.bind("<ButtonRelease-1>", on_release)
            return btn

        _sb_sep()

        file_menu = make_dropdown_menu([

            ("Add Directory", self.add_directory),
            ("Add Google Drive Link", self.add_drive_link),
        ])
        self._toolbar_menus["File"] = file_menu
        self._toolbar_btns["File"] = _sb_btn("📁", "File", menu=file_menu)

        self._view_menu = make_dropdown_menu([
            ("Hide Console" if self.show_console else "Show Console", self.toggle_console),
            None,
            ("Filter / Sort", self._show_filter_dialog),
        ])
        self._toolbar_menus["View"] = self._view_menu
        self._toolbar_btns["View"] = _sb_btn("☰", "View", menu=self._view_menu)

        self._loop_mode_var = tk.StringVar(value=self.loop_mode)
        c = _tb_colors()
        _sel_color = self.accent_color
        loop_sub = tk.Menu(self.root, tearoff=0,
                           bg=c["bg"], fg=c["fg"],
                           activebackground=c["hover"],
                           activeforeground=c["fg"],
                           selectcolor=_sel_color,
                           relief="flat", bd=1, font=("Segoe UI", 10))
        for mode, lbl in [("loop_on", "Loop On"), ("loop_off", "Loop Off"), ("shuffle", "Shuffle")]:
            loop_sub.add_radiobutton(label=lbl, variable=self._loop_mode_var, value=mode,
                                     command=lambda m=mode: self._set_loop_mode_menu(m))
        playback_menu = tk.Menu(self.root, tearoff=0,
                                bg=c["bg"], fg=c["fg"],
                                activebackground=c["hover"],
                                activeforeground=c["fg"],
                                relief="flat", bd=1, font=("Segoe UI", 10))
        playback_menu.add_cascade(label="Loop Mode", menu=loop_sub)
        playback_menu.add_separator()
        self.smart_resume_var = tk.BooleanVar(value=self.smart_resume_enabled)
        playback_menu.add_checkbutton(
            label="Smart Resume",
            variable=self.smart_resume_var,
            command=self.toggle_smart_resume,
            selectcolor=_sel_color,
        )
        self._toolbar_menus["Playback"] = playback_menu
        self._toolbar_btns["Playback"] = _sb_btn("↺", "Playback", menu=playback_menu)

        _sb_sep()
        self._ensure_play_toolbar_fonts()
        self.play_toolbar_btn = tk.Label(
            sb, text="▶",
            bg=self.surface_color, fg="#2ecc71",
            font=("Segoe UI", 20, "bold"), pady=12, cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0, anchor="center"
        )
        self.play_toolbar_btn.pack(fill=tk.X, pady=(6, 0))
        self._bind_play_toolbar_hover()

        _sb_sep()

        self._toolbar_btns["Settings"] = _sb_btn("⚙", "Settings", command=self._show_settings)
        self._toolbar_btns["Settings"].pack_forget()

        self.theme_toolbar_btn = tk.Label(
            sb, text="🌙" if not self.dark_mode else "☀",
            bg=self.surface_color, fg=self.text_color,
            font=("Segoe UI", 15, "bold"), pady=10, cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0, anchor="center"
        )
        self._bind_theme_toolbar_hover()

        self.theme_toolbar_btn.pack(fill=tk.X, side=tk.BOTTOM, pady=(2, 10))
        self._toolbar_btns["Settings"].pack(fill=tk.X, side=tk.BOTTOM, pady=(18, 2))
        self._bind_play_toolbar_hover()

        self.button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        self.button_frame.pack(fill=tk.X)

    def _make_media_pill(self, label):
        container = tk.Frame(self.workspace_nav, bg=self.bg_color)
        container.pack(side=tk.LEFT, padx=2)

        btn = tk.Label(container, text=label,
                       bg=self.bg_color, fg=self.text_muted,
                       font=("Segoe UI", 10, "normal"),
                       padx=14, pady=3, cursor="hand2")
        btn.pack(fill=tk.X)
        btn._pill_container = container

        def on_press(_e):
            btn.config(fg=self.accent_color, font=("Segoe UI", 10, "bold"))

        def on_release(_e):
            cmd = {
                "Home": self._show_home_view,
                "Gallery": self._show_grid_view,
                "Playlist": self._manage_playlists,
                "Queue": self._show_queue_manager,
                "Favourites": self._show_favorites_manager,
                "Tags & Ratings": self._show_annotation_browser,
                "History": self._show_watch_history,
            }[label]
            cmd()

        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        self._bind_media_pill_hover(btn, label)

        self._media_pill_btns[label] = btn
        if not hasattr(self, '_media_pill_labels'):
            self._media_pill_labels = {}
        self._media_pill_labels[label] = label
        return btn

    def _create_panel_action_btn(self, parent, icon, command, tooltip=None):
        btn = tk.Label(
            parent, text=icon,
            bg=self.bg_color, fg=self.text_muted,
            font=("Segoe UI", 12), pady=3, padx=4,
            cursor="hand2", relief=tk.FLAT, bd=0,
        )
        btn._active = False

        def _on_enter(_e):
            btn.config(bg=self.hover_color, fg=self.accent_color)

        def _on_leave(_e):
            if btn._active:
                btn.config(bg=self.hover_color, fg=self.accent_color)
            else:
                btn.config(bg=self.bg_color, fg=self.text_muted)

        def _on_click(_e):
            command()
            self._refresh_dir_action_states()

        btn.bind("<Enter>", _on_enter)
        btn.bind("<Leave>", _on_leave)
        btn.bind("<Button-1>", _on_click)

        if tooltip:
            import tkinter as _tk
            _tip = [None]

            def _show(e):
                if _tip[0]: return
                x = btn.winfo_rootx()
                y = btn.winfo_rooty() + btn.winfo_height() + 2
                tw = _tk.Toplevel(btn)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                _tk.Label(tw, text=tooltip, bg=self.console_bg, fg=self.console_fg,
                          font=("Segoe UI", 9), padx=7, pady=3).pack()
                _tip[0] = tw

            def _hide(e):
                if _tip[0]:
                    try:
                        _tip[0].destroy()
                    except:
                        pass
                    _tip[0] = None

            btn.bind("<Enter>", lambda e: (_show(e), _on_enter(e)))
            btn.bind("<Leave>", lambda e: (_hide(e), _on_leave(e)))
        return btn

    def _configure_tree_style(self):
        self._configure_directory_ttk_styles()

    def _toggle_annotation_columns(self, enabled):
        pass

    def _setup_global_search_bar(self, parent):
        search_wrap = tk.Frame(
            parent,
            bg=self.bg_color,
            highlightbackground=self.entry_border,
            highlightthickness=1,
        )
        search_wrap.pack(side=tk.RIGHT, padx=(10, 0), pady=0)
        self._global_search_wrap = search_wrap

        self.global_search_icon = tk.Label(
            search_wrap, text="⌕",
            bg=self.bg_color, fg=self.text_muted,
            font=("Segoe UI", 11), padx=6, pady=0,
        )
        self.global_search_icon.pack(side=tk.LEFT)

        self.global_search_entry = tk.Entry(
            search_wrap,
            font=self.small_font,
            bg=self.bg_color, fg=self.entry_fg,
            relief=tk.FLAT, bd=0,
            highlightthickness=0,
            width=30,
            insertbackground=self.accent_color,
        )
        self.global_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)
        self.global_search_entry.bind('<KeyRelease>', self._on_global_search_changed)

        def _search_focus_in(e):
            search_wrap.config(highlightbackground=self.accent_color, highlightthickness=1)
            self.global_search_icon.config(fg=self.accent_color)

        def _search_focus_out(e):
            search_wrap.config(highlightbackground=self.entry_border, highlightthickness=1)
            self.global_search_icon.config(fg=self.text_muted)

        self.global_search_entry.bind('<FocusIn>', _search_focus_in)
        self.global_search_entry.bind('<FocusOut>', _search_focus_out)

    def _set_workspace_title(self, title, subtitle=None):
        if hasattr(self, "workspace_title_label"):
            self.workspace_title_label.config(text=title)
        if hasattr(self, "workspace_context_label"):
            self.workspace_context_label.config(text=subtitle or self._selected_directory_summary())

    def _selected_directory_summary(self):
        if not hasattr(self, "dir_listbox"):
            return "No directory selected"
        selection = self.dir_listbox.curselection()
        if not selection:
            return "No directory selected"
        names = []
        for idx in selection[:2]:
            if idx < len(self.selected_dirs):
                names.append(os.path.basename(self.selected_dirs[idx]) or self.selected_dirs[idx])
        if len(selection) > 2:
            names.append(f"+{len(selection) - 2} more")
        total = 0
        for idx in selection:
            if idx < len(self.selected_dirs):
                d = self.selected_dirs[idx]
                cache = self.scan_cache.get(d)
                if cache:
                    videos, _, _ = cache
                    total += sum(1 for v in videos if not self.is_video_excluded(d, v))
        return "Directory: " + ", ".join(names) + f"({total} videos)"

    def _refresh_media_pill_state(self):
        active_view = getattr(self, '_active_app_view', 'home')
        active_label = self._view_tab_labels.get(active_view, "Home")
        for lbl, btn in self._media_pill_btns.items():
            is_active = (lbl == active_label)
            container = getattr(btn, '_pill_container', btn.master)
            for child in container.winfo_children():
                if isinstance(child, tk.Frame) and getattr(child, '_underline', False):
                    child.destroy()
            if is_active:
                btn.config(
                    bg=self.bg_color, fg=self.accent_color,
                    font=("Segoe UI", 10, "bold"))
                underline = tk.Frame(container, bg=self.accent_color, height=2)
                underline._underline = True
                underline.pack(fill=tk.X)
            else:
                btn.config(
                    bg=self.bg_color, fg=self.text_muted,
                    font=("Segoe UI", 10, "normal"))
            container.configure(bg=self.bg_color)
            self._bind_media_pill_hover(btn, lbl)

    def _ensure_embedded_view_frame(self):
        if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
            return self.embedded_view_frame
        self.embedded_view_frame = tk.Frame(self.workspace_body, bg=self.bg_color)
        return self.embedded_view_frame

    def _show_home_view(self):
        self._cleanup_active_manager()
        if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
            self.embedded_view_frame.destroy()
        self.embedded_view_frame = None
        if hasattr(self, 'exclusion_section') and self.exclusion_section.winfo_ismapped():
            self.exclusion_section.pack_forget()

        self._set_workspace_title("Home", "Welcome to Recursive Video Player")
        self._active_app_view = "home"
        self._refresh_media_pill_state()

        # Re-apply global search to new manager if query exists
        if hasattr(self, 'global_search_entry'):
            query = self.global_search_entry.get().strip().lower()
            if query and self.active_embedded_manager and hasattr(self.active_embedded_manager, 'apply_search'):
                self.active_embedded_manager.apply_search(query)

        self._render_home_dashboard()

    def _render_home_dashboard(self):
        frame = self._ensure_embedded_view_frame()
        for child in frame.winfo_children():
            child.destroy()
        frame.pack(fill=tk.BOTH, expand=True)

        bg = self.bg_color
        surface = self.surface_color
        surface2 = self.alt_row_color
        border = self.border_color
        text_pri = self.text_color
        text_sec = self.text_muted
        accent = self.accent_color
        accent2 = self.accent_secondary

        frame.configure(bg=bg)

        def _bind_hover(card_f, inner_f, cmd, col):
            def _enter(e):
                card_f.config(bg=self.hover_color, highlightbackground=col)
                inner_f.config(bg=self.hover_color)
                for w in inner_f.winfo_children():
                    try:
                        if isinstance(w, tk.Label) and w.cget("bg") == surface:
                            w.config(bg=self.hover_color)
                    except Exception:
                        pass
            def _leave(e):
                card_f.config(bg=surface, highlightbackground=border)
                inner_f.config(bg=surface)
                for w in inner_f.winfo_children():
                    try:
                        if isinstance(w, tk.Label) and w.cget("bg") == self.hover_color:
                            w.config(bg=surface)
                    except Exception:
                        pass
            for w in [card_f, inner_f] + list(inner_f.winfo_children()):
                try:
                    w.bind("<Button-1>", lambda e, fn=cmd: fn())
                    w.bind("<Enter>", _enter)
                    w.bind("<Leave>", _leave)
                except Exception:
                    pass

        total_dirs = len(self.selected_dirs)
        total_lib_vids = sum(
            sum(1 for v in (self.scan_cache.get(d) or ([],))[0]
                if not self.is_video_excluded(d, v))
            for d in self.selected_dirs
        ) if hasattr(self, 'scan_cache') else 0

        canvas = tk.Canvas(frame, bg=bg, highlightthickness=0, bd=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=bg)
        inner_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(inner_win, width=e.width)
        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        pad = tk.Frame(inner, bg=bg)
        pad.pack(fill=tk.BOTH, expand=True, padx=1, pady=(35, 20))

        hero = tk.Frame(pad, bg=surface)
        hero.pack(fill=tk.X, pady=(0, 18))
        tk.Frame(hero, bg=accent2, height=3).pack(fill=tk.X, side=tk.TOP)
        hero_inner = tk.Frame(hero, bg=surface)
        hero_inner.pack(fill=tk.X, padx=24, pady=18)

        left_hero = tk.Frame(hero_inner, bg=surface)
        left_hero.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(left_hero, text="Recursive Video Player",
                 font=Font(family="Segoe UI", size=20, weight="bold"),
                 bg=surface, fg=text_pri).pack(anchor="w")
        tk.Label(left_hero, text="Your personal media library · fast, organised, beautiful",
                 font=Font(family="Segoe UI", size=10),
                 bg=surface, fg=text_sec).pack(anchor="w", pady=(4, 0))

        play_btn = tk.Label(hero_inner, text="▶  Play All",
                            font=Font(family="Segoe UI", size=10, weight="bold"),
                            bg=accent2, fg="#ffffff", padx=16, pady=8, cursor="hand2")
        play_btn.pack(side=tk.RIGHT, anchor="center")
        play_btn.bind("<Button-1>", lambda e: self.play_videos())
        play_btn.bind("<Enter>", lambda e: play_btn.config(bg=accent))
        play_btn.bind("<Leave>", lambda e: play_btn.config(bg=accent2))

        body_row = tk.Frame(pad, bg=bg)
        body_row.pack(fill=tk.BOTH, expand=True)
        body_row.columnconfigure(0, weight=5)
        body_row.columnconfigure(1, weight=3)

        left_col = tk.Frame(body_row, bg=bg)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right_col = tk.Frame(body_row, bg=bg)
        right_col.grid(row=0, column=1, sticky="nsew")

        stat_data = [
            ("📁", str(total_dirs), "Directories", accent, None),
            ("🎬", str(total_lib_vids), "Videos", accent2, None),
            ("📅", "—", "Watched Today", "#06b6d4", self._show_watch_history),
            ("✓", "—", "Avg Completion", "#34c98a", self._show_watch_history),
        ]

        stats_row = tk.Frame(left_col, bg=bg)
        stats_row.pack(fill=tk.X, pady=(0, 14))
        for i in range(4):
            stats_row.columnconfigure(i, weight=1, uniform="sc")

        today_val_lbl = avg_val_lbl = None
        for i, (icon, val, lbl, col, cmd) in enumerate(stat_data):
            card = tk.Frame(stats_row, bg=surface,
                            highlightbackground=border, highlightthickness=1,
                            cursor="hand2" if cmd else "")
            card.grid(row=0, column=i, padx=(0 if i == 0 else 8, 0), sticky="nsew")
            tk.Frame(card, bg=col, width=4).pack(side=tk.LEFT, fill=tk.Y)
            body = tk.Frame(card, bg=surface)
            body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=12)
            tk.Label(body, text=icon, font=Font(family="Segoe UI Emoji", size=13),
                     bg=surface, fg=col).pack(anchor="w")
            val_lbl = tk.Label(body, text=val,
                               font=Font(family="Segoe UI", size=16, weight="bold"),
                               bg=surface, fg=text_pri)
            val_lbl.pack(anchor="w", pady=(2, 0))
            tk.Label(body, text=lbl, font=Font(family="Segoe UI", size=8),
                     bg=surface, fg=text_sec).pack(anchor="w")
            if i == 0: self._home_dirs_label = val_lbl
            if i == 1: self._home_vids_label = val_lbl
            if i == 2: today_val_lbl = val_lbl
            if i == 3: avg_val_lbl = val_lbl
            if cmd:
                for w in (card, body, val_lbl):
                    w.bind("<Button-1>", lambda e, c=cmd: c())
                    w.bind("<Enter>", lambda e, f=card: f.config(bg=self.hover_color, highlightbackground=accent))
                    w.bind("<Leave>", lambda e, f=card: f.config(bg=surface, highlightbackground=border))

        all_actions = [
            ("🖼", "Gallery", "Browse as grid", accent, self._show_grid_view),
            ("🎵", "Playlist", "Manage playlists", "#7c3aed", self._manage_playlists),
            ("⭐", "Favourites", "Your starred videos", "#f5a623", self._show_favorites_manager),
            ("🕐", "History", "Recently watched", "#34c98a", self._show_watch_history),
            ("📋", "Queue", "Up next", "#06b6d4", self._show_queue_manager),
            ("🏷", "Tags & Ratings", "Annotate & filter", accent2, self._show_annotation_browser),
        ]
        rng = _random.Random(self._qa_seed)
        actions = rng.sample(all_actions, 3)

        qa_lbl_row = tk.Frame(left_col, bg=bg)
        qa_lbl_row.pack(fill=tk.X, pady=(0, 10))
        tk.Label(qa_lbl_row, text="Quick Actions",
                 font=Font(family="Segoe UI", size=11, weight="bold"),
                 bg=bg, fg=text_pri).pack(side=tk.LEFT)
        tk.Frame(qa_lbl_row, bg=border, height=1).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0), pady=6)

        qa_frame = tk.Frame(left_col, bg=bg)
        qa_frame.pack(fill=tk.X)
        for ci in range(3):
            qa_frame.columnconfigure(ci, weight=1, uniform="qa")

        for ci, (icon, title, sub, col, cmd) in enumerate(actions):
            card = tk.Frame(qa_frame, bg=surface,
                            highlightbackground=border, highlightthickness=1,
                            cursor="hand2")
            card.grid(row=0, column=ci, padx=(0 if ci == 0 else 10, 0), sticky="nsew")
            inner_card = tk.Frame(card, bg=surface)
            inner_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
            tk.Label(inner_card, text=icon,
                     font=Font(family="Segoe UI Emoji", size=18),
                     bg=col, fg="#ffffff", width=3, pady=5).pack(anchor="w")
            tk.Label(inner_card, text=title,
                     font=Font(family="Segoe UI", size=11, weight="bold"),
                     bg=surface, fg=text_pri).pack(anchor="w", pady=(7, 0))
            tk.Label(inner_card, text=sub,
                     font=Font(family="Segoe UI", size=9),
                     bg=surface, fg=text_sec).pack(anchor="w", pady=(2, 0))
            _bind_hover(card, inner_card, cmd, col)

        analytics_card = tk.Frame(right_col, bg=surface,
                                  highlightbackground=border, highlightthickness=1)
        analytics_card.pack(fill=tk.BOTH, expand=True)
        tk.Frame(analytics_card, bg=accent, height=3).pack(fill=tk.X, side=tk.TOP)
        ac_inner = tk.Frame(analytics_card, bg=surface)
        ac_inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        tk.Label(ac_inner, text="Watch Analytics",
                 font=Font(family="Segoe UI", size=10, weight="bold"),
                 bg=surface, fg=text_pri).pack(anchor="w", pady=(0, 10))

        ms_row = tk.Frame(ac_inner, bg=surface)
        ms_row.pack(fill=tk.X, pady=(0, 12))
        ms_row.columnconfigure(0, weight=1)
        ms_row.columnconfigure(1, weight=1)

        week_val_lbl = pct_val_lbl = None
        for mci, (mv, ml, mc) in enumerate([("—", "This week", "#7c3aed"), ("—", "Coverage", accent2)]):
            mf = tk.Frame(ms_row, bg=surface2)
            mf.grid(row=0, column=mci, padx=(0 if mci == 0 else 6, 0), sticky="nsew")
            lbl_w = tk.Label(mf, text=mv,
                             font=Font(family="Segoe UI", size=14, weight="bold"),
                             bg=surface2, fg=mc)
            lbl_w.pack(padx=10, pady=(8, 0), anchor="w")
            tk.Label(mf, text=ml,
                     font=Font(family="Segoe UI", size=8),
                     bg=surface2, fg=text_sec).pack(padx=10, pady=(0, 8), anchor="w")
            if mci == 0: week_val_lbl = lbl_w
            if mci == 1: pct_val_lbl = lbl_w

        tk.Label(ac_inner, text="Last 7 days",
                 font=Font(family="Segoe UI", size=8, weight="bold"),
                 bg=surface, fg=text_sec).pack(anchor="w", pady=(0, 4))

        bar_h = 40
        bar_canvas = tk.Canvas(ac_inner, bg=surface, height=bar_h + 18,
                               highlightthickness=0, bd=0)
        bar_canvas.pack(fill=tk.X, pady=(0, 12))

        _day_counts = [0] * 7

        def _draw_bars(counts=None):
            if counts is None:
                counts = _day_counts
            bar_canvas.delete("all")
            w = bar_canvas.winfo_width() or 300
            max_v = max(counts) if any(counts) else 1
            n = len(counts)
            gap = 5
            bw = max(4, (w - gap * (n + 1)) // n)
            today_date_l = datetime.now().date()
            for k, v in enumerate(counts):
                delta = n - 1 - k
                dl = (today_date_l - timedelta(days=delta)).strftime("%a")
                x0 = gap + k * (bw + gap)
                x1 = x0 + bw
                y1 = 2 + bar_h
                filled = max(3, int((v / max_v) * bar_h)) if max_v else 3
                bar_canvas.create_rectangle(x0, 2, x1, y1, fill=surface2, outline="", width=0)
                bcol = accent2 if k == n - 1 else accent
                bar_canvas.create_rectangle(x0, y1 - filled, x1, y1, fill=bcol, outline="", width=0)
                bar_canvas.create_text(x0 + bw // 2, y1 + 9, text=dl,
                                       fill=text_sec, font=("Segoe UI", 7))

        bar_canvas.bind("<Configure>", lambda e: _draw_bars())
        bar_canvas.after(60, _draw_bars)

        tk.Frame(ac_inner, bg=border, height=1).pack(fill=tk.X, pady=(0, 8))
        tk.Label(ac_inner, text="Top directories",
                 font=Font(family="Segoe UI", size=8, weight="bold"),
                 bg=surface, fg=text_sec).pack(anchor="w", pady=(0, 6))

        top_dirs_frame = tk.Frame(ac_inner, bg=surface)
        top_dirs_frame.pack(fill=tk.X)
        tk.Label(top_dirs_frame, text="Loading…",
                 font=Font(family="Segoe UI", size=8),
                 bg=surface, fg=text_sec).pack(anchor="w")

        cw_placeholder = tk.Frame(pad, bg=bg)
        cw_placeholder.pack(fill=tk.X)

        tip_bg = surface2
        tip = tk.Frame(pad, bg=tip_bg, highlightbackground=border, highlightthickness=1)
        tip.pack(fill=tk.X, pady=(14, 0))
        tip_inner = tk.Frame(tip, bg=tip_bg)
        tip_inner.pack(fill=tk.X, padx=14, pady=8)
        tk.Label(tip_inner, text="💡",
                 font=Font(family="Segoe UI Emoji", size=10),
                 bg=tip_bg, fg=accent).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(tip_inner,
                 text="Click  +  on the panel header to add a folder, then pick any action above to explore your library.",
                 font=Font(family="Segoe UI", size=9),
                 bg=tip_bg, fg=text_sec,
                 wraplength=680, justify="left").pack(side=tk.LEFT)

        def _load_stats():
            try:
                h_stats = {}
                all_hist = []
                if hasattr(self, 'watch_history_manager'):
                    try:
                        h_stats = self.watch_history_manager.get_history_stats()
                        all_hist = self.watch_history_manager.service.get_all_history()
                    except Exception:
                        pass

                t_today = h_stats.get('today_count', 0)
                t_week = h_stats.get('week_count', 0)
                t_unique = h_stats.get('unique_videos', 0)

                tracked = [e.completion_percentage for e in all_hist if e.completion_percentage > 0]
                t_avg_pct = (sum(tracked) / len(tracked)) if tracked else 0.0

                t_pct_watched = (t_unique / total_lib_vids * 100) if total_lib_vids > 0 else 0.0

                t_day_counts = [0] * 7
                today_date = datetime.now().date()
                for e in all_hist:
                    try:
                        delta = (today_date - datetime.fromisoformat(e.watched_at).date()).days
                        if 0 <= delta < 7:
                            t_day_counts[6 - delta] += 1
                    except Exception:
                        pass

                dir_counts = {}
                for e in all_hist:
                    dk = os.path.basename(e.directory_path) or e.directory_path
                    dir_counts[dk] = dir_counts.get(dk, 0) + 1
                t_top_dirs = sorted(dir_counts.items(), key=lambda x: x[1], reverse=True)[:4]

                cw_seen = set()
                t_cw_entries = []
                for cw_e in sorted(all_hist, key=lambda x: x.watched_at, reverse=True):
                    cw_pct = float(cw_e.completion_percentage or 0)
                    if (cw_e.video_path not in cw_seen
                            and os.path.isfile(cw_e.video_path)
                            and 5 < cw_pct < 91):
                        cw_seen.add(cw_e.video_path)
                        t_cw_entries.append(cw_e)
                    if len(t_cw_entries) >= 4:
                        break

                self.root.after(0, lambda: _apply_stats(
                    t_today, t_week, t_avg_pct, t_pct_watched,
                    t_day_counts, t_top_dirs, t_cw_entries
                ))
            except Exception:
                pass

        def _apply_stats(t_today, t_week, t_avg_pct, t_pct_watched,
                         t_day_counts, t_top_dirs, t_cw_entries):
            try:
                if not frame.winfo_exists():
                    return

                # stat cards
                if today_val_lbl and today_val_lbl.winfo_exists():
                    today_val_lbl.config(text=str(t_today))
                if avg_val_lbl and avg_val_lbl.winfo_exists():
                    avg_val_lbl.config(text=f"{t_avg_pct:.0f}%")
                if week_val_lbl and week_val_lbl.winfo_exists():
                    week_val_lbl.config(text=str(t_week))
                if pct_val_lbl and pct_val_lbl.winfo_exists():
                    pct_val_lbl.config(text=f"{t_pct_watched:.0f}%")

                _day_counts[:] = t_day_counts
                _draw_bars(counts=t_day_counts)

                for child in top_dirs_frame.winfo_children():
                    child.destroy()
                bar_colors = [accent, accent2, "#7c3aed", "#06b6d4"]
                if t_top_dirs:
                    max_dc = t_top_dirs[0][1]
                    for ti, (dname, dcount) in enumerate(t_top_dirs):
                        rf = tk.Frame(top_dirs_frame, bg=surface)
                        rf.pack(fill=tk.X, pady=2)
                        tk.Label(rf,
                                 text=dname[:18] + ("…" if len(dname) > 18 else ""),
                                 font=Font(family="Segoe UI", size=8),
                                 bg=surface, fg=text_pri, anchor="w", width=18).pack(side=tk.LEFT)
                        bg_bar = tk.Frame(rf, bg=surface2, height=8)
                        bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
                        bg_bar.pack_propagate(False)
                        _col = bar_colors[ti % len(bar_colors)]
                        _ratio = dcount / max_dc if max_dc else 0

                        def _fill(p=bg_bar, r=_ratio, c=_col):
                            p.update_idletasks()
                            pw = p.winfo_width() or 80
                            tk.Frame(p, bg=c, width=max(4, int(pw * r)), height=8).place(x=0, y=0)

                        bg_bar.after(90, _fill)
                        tk.Label(rf, text=str(dcount),
                                 font=Font(family="Segoe UI", size=8),
                                 bg=surface, fg=text_sec).pack(side=tk.LEFT)
                else:
                    tk.Label(top_dirs_frame, text="No watch history yet.",
                             font=Font(family="Segoe UI", size=8),
                             bg=surface, fg=text_sec).pack(anchor="w")

                for child in cw_placeholder.winfo_children():
                    child.destroy()

                if not t_cw_entries:
                    return

                if hasattr(self, 'video_preview_manager'):
                    self.video_preview_manager.prefetch_cw_previews(
                        [(e.video_path, float(e.duration_watched or 0)) for e in t_cw_entries]
                    )

                cw_hdr = tk.Frame(cw_placeholder, bg=bg)
                cw_hdr.pack(fill=tk.X, pady=(16, 8))
                tk.Label(cw_hdr, text="Continue Watching",
                         font=Font(family="Segoe UI", size=11, weight="bold"),
                         bg=bg, fg=text_pri).pack(side=tk.LEFT)
                tk.Frame(cw_hdr, bg=border, height=1).pack(
                    side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0), pady=6)
                _see_all_lbl = tk.Label(cw_hdr, text="See all →",
                                        font=Font(family="Segoe UI", size=9),
                                        bg=bg, fg=accent, cursor="hand2")
                _see_all_lbl.pack(side=tk.RIGHT)
                _see_all_lbl.bind("<Button-1>", lambda e: self._show_watch_history())
                _see_all_lbl.bind("<Enter>", lambda e: _see_all_lbl.config(fg=accent2))
                _see_all_lbl.bind("<Leave>", lambda e: _see_all_lbl.config(fg=accent))

                cw_grid = tk.Frame(cw_placeholder, bg=bg)
                cw_grid.pack(fill=tk.X)
                for _cw_ci in range(len(t_cw_entries)):
                    cw_grid.columnconfigure(_cw_ci, weight=1, uniform="cw")

                for _cw_ci, _cw_entry in enumerate(t_cw_entries):
                    _cw_fname = os.path.splitext(os.path.basename(_cw_entry.video_path))[0]
                    _cw_name_disp = (_cw_fname[:26] + "…") if len(_cw_fname) > 26 else _cw_fname
                    _cw_pct = min(100.0, max(0.0, float(_cw_entry.completion_percentage or 0)))
                    _cw_dur = _cw_entry.get_duration_formatted() if _cw_entry.duration_watched else ""
                    try:
                        _cw_delta = datetime.now() - datetime.fromisoformat(_cw_entry.watched_at)
                        if _cw_delta.days == 0:
                            _cw_hrs = _cw_delta.seconds // 3600
                            _cw_time = (f"{_cw_delta.seconds // 60}m ago"
                                        if _cw_hrs == 0 else f"{_cw_hrs}h ago")
                        elif _cw_delta.days == 1:
                            _cw_time = "Yesterday"
                        else:
                            _cw_time = f"{_cw_delta.days}d ago"
                    except Exception:
                        _cw_time = ""

                    _cw_bar_col = ("#34c98a" if _cw_pct >= 80
                                   else (accent if _cw_pct >= 35 else accent2))

                    _cw_card = tk.Frame(cw_grid, bg=surface,
                                        highlightbackground=border, highlightthickness=1,
                                        cursor="hand2")
                    _cw_card.grid(row=0, column=_cw_ci,
                                  padx=(0 if _cw_ci == 0 else 8, 0), sticky="nsew")
                    _cw_card.pack_propagate(False)
                    _cw_card.configure(height=110)

                    _accent_bar = tk.Frame(_cw_card, bg=_cw_bar_col, width=4)
                    _accent_bar.pack(side=tk.LEFT, fill=tk.Y)

                    _cw_body = tk.Frame(_cw_card, bg=surface)
                    _cw_body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                  padx=(10, 10), pady=10)

                    tk.Label(_cw_body, text=_cw_name_disp,
                             font=Font(family="Segoe UI", size=9, weight="bold"),
                             bg=surface, fg=text_pri, anchor="w").pack(fill=tk.X)

                    _cw_meta = tk.Frame(_cw_body, bg=surface)
                    _cw_meta.pack(fill=tk.X, pady=(2, 6))
                    tk.Label(_cw_meta, text=_cw_time,
                             font=Font(family="Segoe UI", size=8),
                             bg=surface, fg=text_sec).pack(side=tk.LEFT)
                    if _cw_dur:
                        tk.Label(_cw_meta, text=f"  ·  {_cw_dur}",
                                 font=Font(family="Segoe UI", size=8),
                                 bg=surface, fg=text_sec).pack(side=tk.LEFT)

                    _cw_prog_bg = tk.Frame(_cw_body, bg=surface2, height=4)
                    _cw_prog_bg.pack(fill=tk.X)
                    _cw_prog_bg.pack_propagate(False)

                    def _fill_cw_prog(p=_cw_prog_bg, r=_cw_pct / 100, c=_cw_bar_col):
                        p.update_idletasks()
                        pw = p.winfo_width() or 80
                        tk.Frame(p, bg=c, width=max(2, int(pw * r)), height=4).place(x=0, y=0)

                    _cw_prog_bg.after(130, _fill_cw_prog)

                    _cw_bot = tk.Frame(_cw_body, bg=surface)
                    _cw_bot.pack(fill=tk.X, pady=(6, 0))
                    tk.Label(_cw_bot, text=f"{_cw_pct:.0f}%",
                             font=Font(family="Segoe UI", size=8, weight="bold"),
                             bg=surface, fg=_cw_bar_col).pack(side=tk.LEFT, anchor="center")
                    _cw_resume = tk.Label(_cw_bot, text="▶  Resume",
                                          font=Font(family="Segoe UI", size=8, weight="bold"),
                                          bg=_cw_bar_col, fg="#ffffff",
                                          padx=10, pady=3, cursor="hand2")
                    _cw_resume.pack(side=tk.RIGHT, anchor="center")

                    def _do_play_cw(path=_cw_entry.video_path):
                        self._play_continue_watching_video(path)

                    for _cw_w in (_cw_card, _cw_body, _cw_resume, _accent_bar):
                        _cw_w.bind("<Button-1>", lambda e, fn=_do_play_cw: fn())

                    def _cw_right_click(e, path=_cw_entry.video_path, entry=_cw_entry):
                        if not hasattr(self, 'video_preview_manager'):
                            return
                        vpm = self.video_preview_manager
                        resume_sec = 0.0
                        try:
                            if entry.duration_watched:
                                resume_sec = float(entry.duration_watched)
                        except Exception:
                            pass
                        cached_td = vpm.cw_preview_cache.get(path, resume_sec)
                        if cached_td:
                            vpm.tooltip.show_preview(path, cached_td, e.x_root, e.y_root)
                        else:
                            vpm.show_preview_at_position(path, resume_sec, e.x_root, e.y_root)

                    def _cw_hide_tooltip(e):
                        if hasattr(self, 'video_preview_manager'):
                            self.video_preview_manager.tooltip.hide_preview()

                    def _bind_cw_rc(w):
                        w.bind("<Button-3>", _cw_right_click)
                        for _ch in w.winfo_children():
                            _bind_cw_rc(_ch)

                    _bind_cw_rc(_cw_card)

                    def _cw_enter(e, card=_cw_card, body=_cw_body,
                                  bc=_cw_bar_col, sf=surface, hc=self.hover_color):
                        card.config(bg=hc, highlightbackground=bc, highlightthickness=2)
                        body.config(bg=hc)
                        for _w in body.winfo_children():
                            try:
                                if isinstance(_w, (tk.Label, tk.Frame)) and _w.cget("bg") == sf:
                                    _w.config(bg=hc)
                            except Exception:
                                pass
                            if isinstance(_w, tk.Frame):
                                for _ww in _w.winfo_children():
                                    try:
                                        if isinstance(_ww, tk.Label) and _ww.cget("bg") == sf:
                                            _ww.config(bg=hc)
                                    except Exception:
                                        pass

                    def _cw_leave(e, card=_cw_card, body=_cw_body,
                                  bd=border, sf=surface, hc=self.hover_color):
                        _cw_hide_tooltip(e)
                        card.config(bg=sf, highlightbackground=bd, highlightthickness=1)
                        body.config(bg=sf)
                        for _w in body.winfo_children():
                            try:
                                if isinstance(_w, (tk.Label, tk.Frame)) and _w.cget("bg") == hc:
                                    _w.config(bg=sf)
                            except Exception:
                                pass
                            if isinstance(_w, tk.Frame):
                                for _ww in _w.winfo_children():
                                    try:
                                        if isinstance(_ww, tk.Label) and _ww.cget("bg") == hc:
                                            _ww.config(bg=sf)
                                    except Exception:
                                        pass

                    for _cw_w in (_cw_card, _cw_body, _accent_bar):
                        _cw_w.bind("<Enter>", _cw_enter)
                        _cw_w.bind("<Leave>", _cw_leave)

            except Exception:
                pass

        ManagedThread(target=_load_stats, name="HomeDashboardStats").start()

    def draw_slider(self):
        if not hasattr(self, 'speed_canvas'):
            return
        self.speed_canvas.delete("all")
        canvas_width = self.speed_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = self.slider_width
        canvas_height = 6
        track_y = canvas_height // 2
        self.speed_canvas.create_rectangle(0, track_y - 1, canvas_width, track_y + 1,
                                           fill="#e0e0e0", outline="", tags="track")
        progress = (self.slider_current - self.slider_min) / (self.slider_max - self.slider_min)
        handle_x = progress * canvas_width
        self.speed_canvas.create_rectangle(0, track_y - 1, handle_x, track_y + 1,
                                           fill=self.accent_color, outline="", tags="progress")
        handle_radius = 8
        self.speed_canvas.create_oval(
            handle_x - handle_radius, track_y - handle_radius,
            handle_x + handle_radius, track_y + handle_radius,
            fill="gray", outline=self.accent_color, width=2, tags="handle"
        )
        for speed in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            marker_progress = (speed - self.slider_min) / (self.slider_max - self.slider_min)
            marker_x = marker_progress * canvas_width
            if speed == 1.0:
                self.speed_canvas.create_oval(marker_x - 2, track_y - 2, marker_x + 2, track_y + 2,
                                              fill=self.accent_color, outline="", tags="marker")
            else:
                self.speed_canvas.create_oval(marker_x - 1, track_y - 1, marker_x + 1, track_y + 1,
                                              fill="#cccccc", outline="", tags="marker")

    def on_slider_configure(self, event):   self.draw_slider()

    def on_slider_click(self, event):       self.dragging = True; self.update_slider_from_mouse(event.x)

    def on_slider_drag(self, event):
        if self.dragging: self.update_slider_from_mouse(event.x)

    def on_slider_release(self, event):     self.dragging = False

    def update_slider_from_mouse(self, x):
        canvas_width = self.speed_canvas.winfo_width()
        if canvas_width <= 1:
            return
        progress  = max(0, min(1, x / canvas_width))
        new_value = self.slider_min + progress * (self.slider_max - self.slider_min)
        new_value = round(new_value * 4) / 4
        new_value = max(self.slider_min, min(self.slider_max, new_value))
        if new_value != self.slider_current:
            self.slider_current = new_value
            self.speed_var.set(new_value)
            self.speed_display.config(text=f"{new_value}×")
            if self.controller:
                self.controller.set_playback_rate(new_value)
                self.update_console(f"Playback speed set to {new_value}×")
            self.draw_slider()

    def reset_speed(self):
        self.slider_current = 1.0
        self.speed_var.set(1.0)
        self.speed_display.config(text="1.0×")
        if self.controller:
            self.controller.set_playback_rate(1.0)
            self.update_console("Playback speed reset to 1.0×")
        self.draw_slider()

