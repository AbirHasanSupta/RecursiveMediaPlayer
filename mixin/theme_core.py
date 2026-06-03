import base64
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font


class ThemeCoreMixin:
    def _apply_menubar_colors(self):
        if not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        if hasattr(self, 'toolbar'):
            try:
                self.toolbar.config(bg=cc["bg"])
                for child in self.toolbar.winfo_children():
                    if isinstance(child, tk.Label):
                        is_play = hasattr(self, 'play_toolbar_btn') and child is self.play_toolbar_btn
                        if is_play:
                            self._apply_play_toolbar_idle()
                        else:
                            child.config(bg=cc["bg"], fg=cc["fg"])
            except tk.TclError:
                pass

        def restyle_menu(m):
            try:
                m.configure(
                    bg=cc["bg"], fg=cc["fg"],
                    activebackground=cc["hover"],
                    activeforeground=cc["fg"])
                end = m.index("end")
                if end is not None:
                    for i in range(end + 1):
                        try:
                            sub = m.nametowidget(m.entrycget(i, "menu"))
                            restyle_menu(sub)
                        except Exception:
                            pass
            except Exception:
                pass

        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Menu):
                restyle_menu(widget)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.save_preferences()
        self.apply_theme()

    def apply_theme(self):
        if self.dark_mode:
            self.bg_color = "#0F1217"
            self.surface_color = "#1A1E26"
            self.accent_color = "#7B9CFF"
            self.accent_secondary = "#FF8A8A"
            self.text_color = "#E2E8F0"
            self.text_muted = "#8A99B5"
            self.border_color = "#2A303C"
            self.hover_color = "#252C38"
            self.listbox_bg = "#1A1E26"
            self.listbox_fg = "#E2E8F0"
            self.listbox_select_bg = "#7B9CFF"
            self.console_bg = "#1A1E26"
            self.console_fg = "#E2E8F0"
            self.entry_bg = "#1A1E26"
            self.entry_fg = "#E2E8F0"
            self.entry_border = "#2A303C"
            self.alt_row_color = "#252C38"
            self.badge_bg = "#2A303C"
            self.badge_fg = "#E2E8F0"
            self.divider_color = "#2A303C"
        else:
            self.bg_color = "#F7F9FC"
            self.surface_color = "#FFFFFF"
            self.accent_color = "#5E81F4"
            self.accent_secondary = "#FF6B6B"
            self.text_color = "#1E2A3A"
            self.text_muted = "#5B6C8F"
            self.border_color = "#E2E8F0"
            self.hover_color = "#EDF2F7"
            self.listbox_bg = "#FFFFFF"
            self.listbox_fg = "#1E2A3A"
            self.listbox_select_bg = "#5E81F4"
            self.console_bg = "#1E2A3A"
            self.console_fg = "#F7F9FC"
            self.entry_bg = "#FFFFFF"
            self.entry_fg = "#1E2A3A"
            self.entry_border = "#E2E8F0"
            self.alt_row_color = "#F7F9FC"
            self.badge_bg = "#EDF2F7"
            self.badge_fg = "#1E2A3A"
            self.divider_color = "#E2E8F0"

        self.muted_fg = self.text_muted
        self.frame_border = self.border_color
        self.header_color = self.text_color
        self.excluded_color = "#C24E4E" if self.dark_mode else "#C44A4A"
        self.favorite_color = "#B8890A" if self.dark_mode else "#8F6B08"

        # Apply colours to root and main frames
        self.root.configure(bg=self.bg_color)

        # Update global search bar if it exists
        if hasattr(self, 'global_search_entry'):
            self.global_search_entry.config(
                bg=self.bg_color, fg=self.entry_fg,
                insertbackground=self.accent_color
            )
        if hasattr(self, 'global_search_icon'):
            self.global_search_icon.config(bg=self.bg_color, fg=self.text_muted)
        if hasattr(self, '_global_search_wrap'):
            self._global_search_wrap.config(
                bg=self.bg_color, highlightbackground=self.entry_border
            )

        self.main_frame.configure(bg=self.bg_color)
        self.content_frame.configure(bg=self.bg_color)
        for section in ['dir_section', 'status_frame', 'button_frame']:
            if hasattr(self, section):
                getattr(self, section).configure(bg=self.bg_color)

        # Update labels
        for label_attr in dir(self):
            if label_attr.endswith('_label') and hasattr(self, label_attr):
                label = getattr(self, label_attr)
                if isinstance(label, tk.Label):
                    label.configure(bg=self.bg_color, fg=self.text_color)

        # Directory panel tree + scrollbar (ttk needs explicit styling on Windows)
        if hasattr(self, 'exclusion_tree'):
            self._configure_directory_ttk_styles()
        elif hasattr(self, '_configure_tree_style'):
            self._configure_tree_style()

        # Console
        if hasattr(self, 'console_text'):
            self.console_text.configure(
                bg=self.console_bg, fg=self.console_fg,
                selectbackground="#214283", selectforeground="white",
                insertbackground=self.console_fg,
            )

        # Entries
        for entry_attr in dir(self):
            if entry_attr.endswith('_entry') and hasattr(self, entry_attr):
                entry = getattr(self, entry_attr)
                if isinstance(entry, tk.Entry):
                    entry.configure(
                        bg=self.entry_bg, fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )

        # Buttons
        self.update_all_buttons()

        self._apply_workspace_chrome_theme()
        self._apply_ttk_chrome_theme()

        # Toolbar and pills
        if hasattr(self, '_fix_toolbar_colors'):
            self._fix_toolbar_colors()
        if hasattr(self, '_refresh_media_pill_state'):
            self._refresh_media_pill_state()

        self._apply_menubar_colors()
        self._apply_theme_to_toplevels()

        # Reload home dashboard if visible
        if getattr(self, '_active_app_view', None) == 'home':
            if hasattr(self, 'exclusion_section') and self.exclusion_section.winfo_ismapped():
                self.exclusion_section.pack_forget()
            self._render_home_dashboard()

    def _ensure_ttk_native_theme(self):
        native = getattr(self, '_ttk_native_theme', None)
        if native:
            return native
        style = ttk.Style()
        names = style.theme_names()
        if 'vista' in names:
            native = 'vista'
        elif 'xpnative' in names:
            native = 'xpnative'
        else:
            native = 'default'
        self._ttk_native_theme = native
        return native

    def _apply_ttk_chrome_theme(self):
        try:
            style = ttk.Style()
            style.configure("TFrame", background=self.bg_color)
            style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
            style.configure(
                "Modern.TCheckbutton",
                background=self.bg_color,
                foreground=self.text_color,
                font=("Segoe UI", 10),
                padding=4,
            )
            style.map(
                "Modern.TCheckbutton",
                foreground=[("active", self.text_color), ("disabled", self.text_muted)],
                background=[("active", self.bg_color)],
            )
        except Exception:
            pass

    def _apply_workspace_chrome_theme(self):
        frame_names = (
            'workspace_frame', 'workspace_header', 'workspace_body', 'workspace_nav',
            'content_frame', 'dir_section', 'dir_frame',
            'exclusion_buttons_frame', 'embedded_view_frame', 'console_section',
            'console_header_frame', 'console_container', 'console_inner_pad', 'console_frame',
        )
        for name in frame_names:
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(bg=self.bg_color)
                except tk.TclError:
                    pass

        for name in ('workspace_title_label', 'dir_header_label'):
            label = getattr(self, name, None)
            if isinstance(label, tk.Label):
                label.configure(bg=self.bg_color, fg=self.text_color)

        context = getattr(self, 'workspace_context_label', None)
        if isinstance(context, tk.Label):
            context.configure(bg=self.bg_color, fg=self.muted_fg)

        header = getattr(self, 'workspace_header', None)
        if header is not None:
            self._restyle_frame_subtree(header, skip_toolbar=False)

        if hasattr(self, 'dir_section'):
            self._restyle_directory_panel()

        if hasattr(self, 'embedded_view_frame') and self.embedded_view_frame is not None:
            try:
                if self.embedded_view_frame.winfo_exists():
                    self.embedded_view_frame.configure(bg=self.bg_color)
            except tk.TclError:
                pass

        self.update_container_borders()
        self._style_sidebar()

    def _pointer_over_widget(self, widget):
        try:
            if not widget.winfo_exists():
                return False
            px, py = widget.winfo_pointerxy()
            wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
            return wx <= px <= (wx + widget.winfo_width()) and wy <= py <= (wy + widget.winfo_height())
        except tk.TclError:
            return False

