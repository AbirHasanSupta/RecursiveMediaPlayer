import tkinter as tk


class ThemeToolbarMixin:
    def _get_loop_icon(self):
        icons = {"loop_on": "⟳  ON", "loop_off": "→ OFF", "shuffle": "⤨ RND"}
        return icons.get(self.loop_mode, "⟳  ON")

    def _get_loop_tooltip(self):
        tooltips = {
            "loop_on":  "Loop: ON - Videos will repeat",
            "loop_off": "Loop: OFF - Play once then stop",
            "shuffle":  "Shuffle: ON - Random playback",
        }
        return tooltips.get(self.loop_mode, "")

    def toggle_loop_mode(self):
        modes         = ["loop_on", "loop_off", "shuffle"]
        current_index = modes.index(self.loop_mode)
        self.loop_mode = modes[(current_index + 1) % len(modes)]
        if hasattr(self, 'loop_toggle_button'):
            self.loop_toggle_button.config(text=self._get_loop_icon())
        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)
        mode_names = {"loop_on": "Loop ON", "loop_off": "Loop OFF", "shuffle": "Shuffle ON"}
        self.update_console(f"Playback mode: {mode_names[self.loop_mode]}")
        self.save_preferences()

    def _play_toolbar_font_idle(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=20, weight="bold", underline=False)

    def _play_toolbar_font_hover(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=20, weight="bold", underline=False)

    def _play_toolbar_font_active(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=20, weight="bold", underline=False)

    def _ensure_play_toolbar_fonts(self):
        """Legacy helper for initial widget creation in build_app."""
        if not getattr(self, '_play_toolbar_fonts_ready', False):
            self._play_toolbar_font = self._play_toolbar_font_idle()
            self._play_toolbar_fonts_ready = True

    def _apply_play_toolbar_idle(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        try:
            btn.config(bg=self.surface_color, fg="#2ecc71",
                       font=self._play_toolbar_font_idle())
        except tk.TclError:
            pass

    def _apply_play_toolbar_hover(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        try:
            btn.config(bg="#2ecc71", fg="#ffffff",
                       font=self._play_toolbar_font_hover())
        except tk.TclError:
            pass

    def _restore_play_toolbar_after_click(self):
        """Re-apply hover or idle after click; run deferred so Leave is processed first."""
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        if self._pointer_over_widget(btn):
            self._apply_play_toolbar_hover()
        else:
            self._apply_play_toolbar_idle()

    def _sync_play_toolbar_btn(self):
        self._restore_play_toolbar_after_click()

    def pill_accents(self, lbl):
        return (self.PILL_ACCENTS_DARK if self.dark_mode else self.PILL_ACCENTS_LIGHT)[lbl]

    def _active_tab_label(self):
        return getattr(self, '_view_tab_labels', {}).get(
            getattr(self, '_active_app_view', 'home'), 'Home')

    def _bind_toolbar_label_hover(self, btn, play=False, menu=None, command=None):
        def on_enter(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_hover_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["hover"], fg=c["fg"])

        def on_leave(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_fg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["bg"], fg=c["fg"])

        def on_press(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_active_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["active"], fg="#FFFFFF")

        def on_release(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_hover_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["hover"], fg=c["fg"])
            if menu is not None:
                try:
                    menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
                finally:
                    menu.grab_release()
            elif command is not None:
                command()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)

    def _bind_theme_toolbar_hover(self):
        btn = getattr(self, 'theme_toolbar_btn', None)
        if btn is None:
            return

        def _show_tip(e):
            if getattr(btn, '_tip_win', None): return
            x = btn.winfo_rootx() + btn.winfo_width() + 6
            y = btn.winfo_rooty() + 4
            tw = tk.Toplevel(btn)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(tw, text="Toggle Theme", bg=self.console_bg, fg=self.console_fg,
                     font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
            btn._tip_win = tw

        def _hide_tip():
            tw = getattr(btn, '_tip_win', None)
            if tw:
                try: tw.destroy()
                except: pass
                btn._tip_win = None

        def on_enter(_e):
            try: btn.config(bg=self.accent_color, fg="#ffffff")
            except tk.TclError: pass
            _show_tip(_e)

        def on_leave(_e):
            try: btn.config(bg=self.surface_color, fg=self.text_color)
            except tk.TclError: pass
            _hide_tip()

        def on_press(_e):
            try: btn.config(bg=self.accent_color, fg="#ffffff")
            except tk.TclError: pass

        def on_release(_e):
            try: btn.config(bg=self.accent_color, fg="#ffffff")
            except tk.TclError: pass
            _hide_tip()
            self._toggle_theme_menu()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)

    def _bind_play_toolbar_hover(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        self._ensure_play_toolbar_fonts()

        _tip_win = [None]

        def _show_tip(e):
            if _tip_win[0]: return
            x = btn.winfo_rootx() + btn.winfo_width() + 6
            y = btn.winfo_rooty() + 4
            tw = tk.Toplevel(btn)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(tw, text="Play Videos", bg=self.console_bg, fg=self.console_fg,
                     font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
            _tip_win[0] = tw

        def _hide_tip(e):
            if _tip_win[0]:
                try: _tip_win[0].destroy()
                except: pass
                _tip_win[0] = None

        def on_enter(_e):
            self._apply_play_toolbar_hover()
            _show_tip(_e)

        def on_leave(_e):
            self._apply_play_toolbar_idle()
            _hide_tip(_e)

        def on_press(_e):
            try:
                btn.config(bg="#27ae60", fg="#ffffff",
                           font=self._play_toolbar_font_active())
            except tk.TclError:
                pass

        def on_release(_e):
            self.global_play()
            btn.after(20, self._restore_play_toolbar_after_click)

        btn.unbind("<Enter>")
        btn.unbind("<Leave>")
        btn.unbind("<ButtonPress-1>")
        btn.unbind("<ButtonRelease-1>")
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        self._apply_play_toolbar_idle()

    def _bind_media_pill_hover(self, btn, label):
        def on_enter(_e):
            if label != self._active_tab_label():
                btn.config(bg=self.hover_color, fg=self.accent_color)

        def on_leave(_e):
            if label != self._active_tab_label():
                btn.config(bg=self.bg_color, fg=self.text_muted)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

    def _fix_toolbar_colors(self):
        if not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        if hasattr(self, 'toolbar'):
            try:
                self.toolbar.configure(bg=cc["bg"])
            except tk.TclError:
                pass
        if hasattr(self, '_toolbar_btns'):
            menus = getattr(self, '_toolbar_menus', {})
            commands = getattr(self, '_toolbar_commands', {})
            for text, btn in self._toolbar_btns.items():
                try:
                    btn.config(bg=self.surface_color, fg=self.text_color)
                except tk.TclError:
                    pass
        if hasattr(self, 'play_toolbar_btn'):
            try:
                self.play_toolbar_btn.config(bg=self.surface_color, fg=self.accent_secondary)
            except tk.TclError:
                pass
            self._bind_play_toolbar_hover()
        if hasattr(self, 'theme_toolbar_btn'):
            try:
                self.theme_toolbar_btn.config(
                    text="☀" if self.dark_mode else "🌙",
                    bg=self.surface_color, fg=self.text_color)
            except tk.TclError:
                pass
            self._bind_theme_toolbar_hover()
        if hasattr(self, 'loop_toolbar_btn'):
            try:
                self.loop_toolbar_btn.config(bg=cc["bg"], fg=cc["fg"])
                self._bind_toolbar_label_hover(self.loop_toolbar_btn, play=False)
            except tk.TclError:
                pass
        if hasattr(self, 'sleep_countdown_label'):
            try:
                self.sleep_countdown_label.config(bg=cc["bg"], fg=cc["fg"])
            except tk.TclError:
                pass
        if hasattr(self, '_media_pill_btns'):
            for lbl, btn in self._media_pill_btns.items():
                try:
                    btn.config(bg=self.bg_color)
                    getattr(btn, '_pill_container', btn.master).configure(bg=self.bg_color)
                    self._bind_media_pill_hover(btn, lbl)
                except tk.TclError:
                    pass

    def _fix_pill_colors_initial(self):
        self._fix_toolbar_colors()

    def _toggle_theme_menu(self):
        self._show_home_view()
        self.toggle_theme()

    def _toggle_loop_from_menu(self):
        self.toggle_loop_mode()
        if hasattr(self, 'loop_toolbar_btn') and hasattr(self, '_tb_colors'):
            cc = self._tb_colors()
            self.loop_toolbar_btn.config(text=self._get_loop_icon(), bg=cc["bg"], fg=cc["fg"])

    def _set_loop_mode_menu(self, mode):
        self.loop_mode = mode
        if hasattr(self, '_loop_mode_var'):
            self._loop_mode_var.set(mode)
        if self._active_player is not None:
            try:
                self._active_player.loop_mode = mode
                labels = {"loop_on": "↺  Loop", "loop_off": "→  Once", "shuffle": "⇄  Shuffle"}
                self._active_player._btn_loop.config(text=labels[mode])
            except Exception:
                pass
        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)
        self.update_console(f"Loop mode: {mode}")
        self.save_preferences()

