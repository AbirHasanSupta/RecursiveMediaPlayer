import tkinter as tk
from tkinter import ttk


class ThemeManagerMixin:
    def get_manager_design_tokens(self):
        """Dashboard-aligned palette for embedded manager UIs."""
        return {
            "bg": self.bg_color,
            "surface": self.surface_color,
            "surface2": self.alt_row_color,
            "header_bg": self.surface_color,
            "text": self.text_color,
            "text_muted": self.text_muted,
            "accent": self.accent_color,
            "accent_secondary": self.accent_secondary,
            "favorites_accent": getattr(self, "favorite_color", "#B8890A"),
            "queue_accent": "#34c98a" if self.dark_mode else "#06b6d4",
            "playlist_accent": "#9F7AEA" if self.dark_mode else "#7c3aed",
            "border": self.border_color,
            "divider": self.divider_color,
            "listbox_fg": self.listbox_fg,
            "listbox_select": self.listbox_select_bg,
        }

    def create_manager_context_menu(self, parent):
        if hasattr(self, "_tb_colors"):
            c = self._tb_colors()
            bg, fg, hover = c["bg"], c["fg"], c["hover"]
        else:
            bg, fg, hover = self.surface_color, self.text_color, self.hover_color
        return tk.Menu(
            parent, tearoff=0,
            bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg,
            relief="flat", bd=1, font=("Segoe UI", 10),
        )

    def configure_manager_scrollbar(self, scrollbar, tokens):
        try:
            scrollbar.configure(
                troughcolor=tokens["bg"],
                bg=tokens["divider"],
                activebackground=tokens["accent"],
            )
        except tk.TclError:
            pass

    def configure_manager_listbox(self, listbox, tokens):
        try:
            listbox.configure(
                bg=tokens["surface"],
                fg=tokens["listbox_fg"],
                selectbackground=tokens["listbox_select"],
                selectforeground="#FFFFFF",
            )
        except tk.TclError:
            pass

    def _manager_action_link_colors(self, style, tokens):
        dark = self.dark_mode
        if style == "warning":
            idle = tokens["accent_secondary"]
            hover = "#FF9A9A" if dark else "#E85555"
            active = "#C24E4E" if dark else "#C44A4A"
        elif style == "secondary":
            idle = tokens["text_muted"]
            hover = tokens["text"]
            active = tokens["text_muted"]
        elif style in ("success", "queue"):
            idle = tokens["queue_accent"]
            hover = "#5eead4" if dark else "#0d9488"
            active = "#2dd4bf" if dark else "#0f766e"
        elif style == "playlist":
            idle = tokens["playlist_accent"]
            hover = "#C4B5FD" if dark else "#6d28d9"
            active = "#A78BFA" if dark else "#5b21b6"
        elif style == "favorites":
            idle = tokens["favorites_accent"]
            hover = "#E8C547" if dark else "#B8890A"
            active = "#9A7509"
        else:
            idle = tokens["accent"]
            hover = "#9BB5FF" if dark else "#4A6CD4"
            active = "#6B8FE8" if dark else "#3d5fc4"
        return idle, hover, active

    def _manager_action_link_font(self, underline=False, bold=False):
        from tkinter.font import Font
        weight = "bold" if bold else "normal"
        return Font(family="Segoe UI", size=10, weight=weight, underline=underline)

    def _bind_manager_action_link(self, btn):
        idle = btn._link_idle
        hover = btn._link_hover
        active = btn._link_active
        command = btn._action_command

        def _parent_bg():
            try:
                return btn.master.cget("bg")
            except tk.TclError:
                return self.bg_color

        def apply_idle():
            if not btn.winfo_exists(): return
            btn.config(bg=_parent_bg(), fg=idle, font=self._manager_action_link_font())

        def apply_hover():
            if not btn.winfo_exists(): return
            btn.config(bg=_parent_bg(), fg=hover, font=self._manager_action_link_font(underline=True))

        def apply_active():
            if not btn.winfo_exists(): return
            btn.config(bg=_parent_bg(), fg=active, font=self._manager_action_link_font(bold=True))

        def on_enter(_e):
            if btn.winfo_exists(): apply_hover()

        def on_leave(_e):
            if btn.winfo_exists(): apply_idle()

        def on_press(_e):
            if btn.winfo_exists(): apply_active()

        def on_release(_e):
            if command:
                command()
            btn.after(20, lambda: apply_hover() if self._pointer_over_widget(btn) else apply_idle())

        btn.unbind("<Enter>")
        btn.unbind("<Leave>")
        btn.unbind("<ButtonPress-1>")
        btn.unbind("<ButtonRelease-1>")
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        apply_idle()

    def create_modern_button(self, parent, text, command, style="primary", size="sm"):
        tokens = self.get_manager_design_tokens()
        dark = self.dark_mode
        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = tokens["bg"]

        if style == "primary":
            bg_idle, bg_hover, bg_press = tokens["accent"], ("#9BB5FF" if dark else "#4A6CD4"), (
                "#6B8FE8" if dark else "#3d5fc4")
            fg, border = "#FFFFFF", tokens["accent"]
        elif style == "success":
            bg_idle, bg_hover, bg_press = tokens["queue_accent"], ("#5eead4" if dark else "#0d9488"), (
                "#2dd4bf" if dark else "#0f766e")
            fg, border = "#FFFFFF", tokens["queue_accent"]
        elif style == "warning":
            bg_idle, bg_hover, bg_press = parent_bg, ("#3a2020" if dark else "#FFF0F0"), (
                "#4a1818" if dark else "#FFE0E0")
            fg, border = tokens["accent_secondary"], tokens["accent_secondary"]
        elif style == "danger":
            bg_idle, bg_hover, bg_press = parent_bg, ("#3a2020" if dark else "#FFF0F0"), (
                "#4a1818" if dark else "#FFE0E0")
            fg, border = ("#FF6B6B" if dark else "#D93025"), ("#FF6B6B" if dark else "#D93025")
        elif style == "playlist":
            bg_idle, bg_hover, bg_press = tokens["playlist_accent"], ("#C4B5FD" if dark else "#6d28d9"), (
                "#A78BFA" if dark else "#5b21b6")
            fg, border = "#FFFFFF", tokens["playlist_accent"]
        else:  # secondary
            bg_idle, bg_hover, bg_press = parent_bg, tokens["surface2"], tokens["surface"]
            fg, border = tokens["text_muted"], tokens["border"]

        from tkinter.font import Font
        font = Font(family="Segoe UI", size=(9 if size == "sm" else 10), weight="bold")
        padx, pady = (12, 5) if size == "sm" else (16, 7)

        btn = tk.Label(
            parent, text=text, bg=bg_idle, fg=fg, font=font,
            padx=padx, pady=pady, cursor="hand2",
            highlightbackground=border, highlightthickness=1, relief=tk.FLAT,
        )
        btn._modern_btn = True
        btn._mb_style = style
        btn._mb_command = command

        def _idle():
            if btn.winfo_exists(): btn.config(bg=bg_idle, highlightbackground=border)

        def _hover():
            if btn.winfo_exists(): btn.config(bg=bg_hover, highlightbackground=border)

        def _press():
            if btn.winfo_exists(): btn.config(bg=bg_press)

        def _release(_e):
            if command: command()
            btn.after(20, lambda: _hover() if self._pointer_over_widget(btn) else _idle())

        btn.bind("<Enter>", lambda e: _hover())
        btn.bind("<Leave>", lambda e: _idle())
        btn.bind("<ButtonPress-1>", lambda e: _press())
        btn.bind("<ButtonRelease-1>", _release)
        return btn

    def create_manager_action_link(self, parent, text, command, style="primary"):
        tokens = self.get_manager_design_tokens()
        idle, hover, active = self._manager_action_link_colors(style, tokens)
        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = tokens["bg"]

        btn = tk.Label(
            parent, text=text,
            bg=parent_bg, fg=idle,
            font=self._manager_action_link_font(),
            padx=10, pady=6,
            cursor="hand2",
        )
        btn._manager_action_link = True
        btn._action_style = style
        btn._action_command = command
        btn._link_idle = idle
        btn._link_hover = hover
        btn._link_active = active
        self._bind_manager_action_link(btn)
        return btn

    def restyle_manager_action_links(self, root):
        tokens = self.get_manager_design_tokens()

        def _walk(widget):
            try:
                if getattr(widget, "_manager_action_link", False):
                    style = widget._action_style
                    idle, hover, active = self._manager_action_link_colors(style, tokens)
                    widget._link_idle = idle
                    widget._link_hover = hover
                    widget._link_active = active
                    self._bind_manager_action_link(widget)
                for child in widget.winfo_children():
                    _walk(child)
            except tk.TclError:
                pass

        _walk(root)

    def restyle_manager_buttons(self, root):
        def _walk(widget):
            try:
                if getattr(widget, "_manager_action_link", False):
                    return
                if isinstance(widget, tk.Button) and hasattr(widget, "_variant"):
                    colors = self.get_button_colors(widget._variant)
                    widget.configure(
                        bg=colors["bg"], fg=colors["fg"],
                        activebackground=colors["active"],
                    )
                    self._bind_button_hover(widget, widget._variant)
                for child in widget.winfo_children():
                    _walk(child)
            except tk.TclError:
                pass
        _walk(root)

    def register_manager_ui(self, manager_ui):
        if not hasattr(self, '_manager_uis'):
            self._manager_uis = []
        if manager_ui not in self._manager_uis:
            self._manager_uis.append(manager_ui)

    def _apply_theme_to_toplevels(self):
        for manager_ui in getattr(self, '_manager_uis', []):
            try:
                if hasattr(manager_ui, 'apply_theme'):
                    manager_ui.apply_theme()
            except Exception:
                pass

    def _restyle_toplevel(self, window):
        def _walk(widget):
            try:
                if isinstance(widget, tk.Button) and hasattr(widget, '_variant'):
                    colors = self.get_button_colors(widget._variant)
                    widget.configure(bg=colors['bg'], fg=colors['fg'], activebackground=colors['active'])
                    self._bind_button_hover(widget, widget._variant)
                    return

                if isinstance(widget, tk.Frame) and getattr(widget, '_accent', False):
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                if isinstance(widget, tk.Frame) and getattr(widget, '_card', False):
                    widget.configure(bg=self.listbox_bg, highlightbackground=self.frame_border)
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                if isinstance(widget, tk.Frame):
                    widget.configure(bg=self.bg_color)

                if isinstance(widget, tk.Label):
                    if getattr(widget, '_muted', False):
                        widget.configure(bg=self.bg_color, fg=self.muted_fg)
                    elif getattr(widget, '_badge', False):
                        widget.configure(bg=self.badge_bg, fg=self.badge_fg)
                    else:
                        widget.configure(bg=self.bg_color, fg=self.text_color)

                if isinstance(widget, tk.Listbox):
                    widget.configure(
                        bg=self.listbox_bg, fg=self.listbox_fg,
                        selectbackground=self.listbox_select_bg,
                    )

                if isinstance(widget, tk.Entry):
                    widget.configure(
                        bg=self.entry_bg, fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )

                if isinstance(widget, tk.Text):
                    widget.configure(bg=self.entry_bg, fg=self.entry_fg, insertbackground=self.entry_fg)

                if isinstance(widget, ttk.Treeview):
                    style_name = widget.cget("style") or "Treeview"
                    s = ttk.Style()
                    s.configure(style_name,
                                background=self.listbox_bg,
                                fieldbackground=self.listbox_bg,
                                foreground=self.listbox_fg)
                    s.map(style_name,
                          background=[("selected", self.listbox_select_bg)],
                          foreground=[("selected", "white")])

                for child in widget.winfo_children():
                    _walk(child)

            except tk.TclError:
                pass

        _walk(window)

