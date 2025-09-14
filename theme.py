import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

class ThemeSelector:
    def get_config_path(self):
        documents_dir = Path.home() / "Documents" / "Recursive Media Player"
        documents_dir.mkdir(parents=True, exist_ok=True)
        return documents_dir / "config.json"

    def load_preferences(self):
        try:
            config_path = self.get_config_path()
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    return {
                    'dark_mode': config.get('dark_mode', False),
                    'show_videos': config.get('show_videos', True),
                    'expand_all': config.get('expand_all', True),
                    'selected_dirs': config.get('selected_dirs', []),
                    'save_directories': config.get('save_directories', False)
                }
        except Exception as e:
            self.update_console(f"Error loading config: {e}")
        return {'dark_mode': False, 'show_videos': True, 'expand_all': True, 'selected_dirs': [], 'save_directories': False}

    def save_preferences(self):
        try:
            config_path = self.get_config_path()
            config = {
                'dark_mode': self.dark_mode,
                'show_videos': self.show_videos,
                'expand_all': self.expand_all_var.get() if hasattr(self, 'expand_all_var') else True,
                'selected_dirs': getattr(self, 'selected_dirs', []),
                'save_directories': self.save_directories
            }
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            self.update_console(f"Error saving config: {e}")

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.save_preferences()
        self.apply_theme()

    def apply_theme(self):
        if self.dark_mode:
            self.bg_color = "#2B2B2B"
            self.accent_color = "#4A9EFF"
            self.text_color = "#A9B7C6"
            self.listbox_bg = "#313335"
            self.listbox_fg = "#A9B7C6"
            self.listbox_select_bg = "#214283"
            self.console_bg = "#1E1F22"
            self.console_fg = "#BCBEC4"
            self.frame_border = "#323232"
            self.header_color = "#BBBBBB"
        else:
            self.bg_color = "#f5f5f5"
            self.accent_color = "#3498db"
            self.text_color = "#333333"
            self.listbox_bg = "white"
            self.listbox_fg = "#333333"
            self.listbox_select_bg = "#3498db"
            self.console_bg = "#2c3e50"
            self.console_fg = "#ecf0f1"
            self.frame_border = "#cccccc"
            self.header_color = "#333333"

        if hasattr(self, 'theme_button'):
            self.theme_button.config(text="Light Mode" if self.dark_mode else "Dark Mode")

        self.root.configure(bg=self.bg_color)
        self.main_frame.configure(bg=self.bg_color)
        self.content_frame.configure(bg=self.bg_color)

        for section in ['dir_section', 'exclusion_section', 'status_frame', 'button_frame']:
            if hasattr(self, section):
                getattr(self, section).configure(bg=self.bg_color)

        for frame_attr in dir(self):
            if frame_attr.endswith('_frame') and hasattr(self, frame_attr):
                frame = getattr(self, frame_attr)
                if isinstance(frame, tk.Frame):
                    frame.configure(bg=self.bg_color)

        for label_attr in dir(self):
            if label_attr.endswith('_label') and hasattr(self, label_attr):
                label = getattr(self, label_attr)
                if isinstance(label, tk.Label):
                    if 'header' in label_attr or label.cget('font') == str(self.header_font):
                        label.configure(bg=self.bg_color, fg=self.header_color)
                    else:
                        label.configure(bg=self.bg_color, fg=self.text_color)

        if hasattr(self, 'dir_listbox'):
            self.dir_listbox.configure(
                bg=self.listbox_bg,
                fg=self.listbox_fg,
                selectbackground=self.listbox_select_bg,
                selectforeground="white",
                highlightbackground=self.frame_border
            )

        if hasattr(self, 'exclusion_listbox'):
            self.exclusion_listbox.configure(
                bg=self.listbox_bg,
                fg=self.listbox_fg,
                selectbackground="#CC7832",
                selectforeground="white",
                highlightbackground=self.frame_border
            )

        if hasattr(self, 'console_text'):
            self.console_text.configure(
                bg=self.console_bg,
                fg=self.console_fg,
                selectbackground="#214283",
                selectforeground="white",
                insertbackground=self.console_fg
            )

        if hasattr(self, 'scrollbar'):
            if self.dark_mode:
                self.scrollbar.configure(bg=self.bg_color, troughcolor=self.listbox_bg)

        if hasattr(self, 'exclusion_scrollbar'):
            if self.dark_mode:
                self.exclusion_scrollbar.configure(bg=self.bg_color, troughcolor=self.listbox_bg)

        if hasattr(self, 'console_scrollbar'):
            if self.dark_mode:
                self.console_scrollbar.configure(bg=self.console_bg, troughcolor=self.console_bg)

        self.update_container_borders()

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
            foreground=[("active", self.text_color), ("selected", self.accent_color)],
            background=[("active", self.bg_color)]
        )

        self.update_all_buttons()
        self.update_frames_recursive(self.root)

    def update_all_buttons(self):
        for attr_name in dir(self):
            if attr_name.endswith('_button') and hasattr(self, attr_name):
                button = getattr(self, attr_name)
                if isinstance(button, tk.Button):
                    if hasattr(button, '_variant'):
                        variant = button._variant
                    else:
                        text = button.cget('text').lower()
                        if 'exclude' in text and 'all' in text:
                            variant = 'warning'
                        elif 'exclude' in text:
                            variant = 'danger'
                        elif 'include' in text:
                            variant = 'success'
                        elif 'play' in text:
                            variant = 'danger'
                        elif 'add' in text:
                            variant = 'primary'
                        else:
                            variant = 'secondary'

                    colors = self.get_button_colors(variant)
                    button.configure(
                        bg=colors['bg'],
                        fg=colors['fg'],
                        activebackground=colors['active']
                    )

    def get_button_colors(self, variant):
        if self.dark_mode:
            variants = {
                "primary": {"bg": "#365880", "fg": "#A9B7C6", "active": "#4A6BA3"},
                "success": {"bg": "#499C54", "fg": "white", "active": "#5AAE66"},
                "danger": {"bg": "#C75450", "fg": "white", "active": "#E06862"},
                "warning": {"bg": "#CC7832", "fg": "white", "active": "#D68843"},
                "secondary": {"bg": "#4C5052", "fg": "#A9B7C6", "active": "#5C6164"},
                "dark": {"bg": "#3A3A3C", "fg": "#A9B7C6", "active": "#4A4A4C"},
                "theme": {"bg": "#5C6164", "fg": "#FFFFFF", "active": "#6C7174"}
            }
        else:
            variants = {
                "primary": {"bg": "#2d89ef", "fg": "white", "active": "#1e70cf"},
                "success": {"bg": "#27ae60", "fg": "white", "active": "#229954"},
                "danger": {"bg": "#e74c3c", "fg": "white", "active": "#c0392b"},
                "warning": {"bg": "#f39c12", "fg": "white", "active": "#e67e22"},
                "secondary": {"bg": "#95a5a6", "fg": "white", "active": "#7f8c8d"},
                "dark": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"},
                "theme": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"}
            }
        return variants.get(variant, variants["primary"])

    def update_container_borders(self):
        if hasattr(self, 'dir_frame'):
            for child in self.dir_frame.winfo_children():
                if isinstance(child, tk.Frame) and any(isinstance(x, tk.Listbox) for x in child.winfo_children()):
                    child.configure(bg=self.bg_color, highlightbackground=self.frame_border, highlightthickness=1)
                    break

        if hasattr(self, 'exclusion_frame'):
            for child in self.exclusion_frame.winfo_children():
                if isinstance(child, tk.Frame) and any(isinstance(x, tk.Listbox) for x in child.winfo_children()):
                    child.configure(bg=self.bg_color, highlightbackground=self.frame_border, highlightthickness=1)
                    break

        for child in self.main_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tk.Frame):
                    for subsubchild in subchild.winfo_children():
                        if isinstance(subsubchild, tk.Frame) and any(
                                isinstance(x, tk.Text) for x in subsubchild.winfo_children()):
                            subchild.configure(bg=self.bg_color, highlightbackground=self.frame_border,
                                               highlightthickness=1)
                            break

    def update_frames_recursive(self, widget):
        try:
            if isinstance(widget, (tk.Frame, tk.Toplevel)):
                widget.configure(bg=self.bg_color)
            elif isinstance(widget, tk.Label):
                widget.configure(bg=self.bg_color, fg=self.text_color)

            for child in widget.winfo_children():
                self.update_frames_recursive(child)
        except tk.TclError:
            pass

