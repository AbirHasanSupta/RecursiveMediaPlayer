import tkinter as tk

class Toast:
    def __init__(self, root, theme_provider):
        self.root = root
        self.tp = theme_provider
        self._stack = []

    def show(self, message, kind="info", duration=3000):
        cfg = {
            "info":    {"bar": "#4f8ef7", "icon": "ℹ",  "icon_bg": "#1a2f5e", "bg": "#0f1b38", "fg": "#e8f0ff"},
            "success": {"bar": "#22c55e", "icon": "✓",  "icon_bg": "#052e16", "bg": "#071a0e", "fg": "#dcfce7"},
            "warning": {"bar": "#f59e0b", "icon": "⚠",  "icon_bg": "#3d2000", "bg": "#231300", "fg": "#fef3c7"},
            "error":   {"bar": "#ef4444", "icon": "✕",  "icon_bg": "#3b0a0a", "bg": "#200505", "fg": "#fee2e2"},
        }
        c = cfg.get(kind, cfg["info"])

        toast = tk.Toplevel(self.root)
        toast.wm_overrideredirect(True)
        toast.attributes("-alpha", 0.0)
        toast.attributes("-topmost", True)
        try:
            toast.attributes("-transparentcolor", "")
        except Exception:
            pass

        # Outer shell — slim modern card
        # Fixed: use c["bar"] directly instead of c["bar"] + "55"
        shell = tk.Frame(toast, bg=c["bg"], bd=0, highlightthickness=1,
                         highlightbackground=c["bar"])
        shell.pack(fill=tk.BOTH, expand=True)

        # Left accent bar
        bar = tk.Frame(shell, bg=c["bar"], width=4)
        bar.pack(side=tk.LEFT, fill=tk.Y)

        # Icon pill
        icon_frame = tk.Frame(shell, bg=c["icon_bg"], width=36, height=36)
        icon_frame.pack(side=tk.LEFT, padx=(10, 0), pady=10)
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text=c["icon"], bg=c["icon_bg"], fg=c["bar"],
                 font=("Segoe UI", 12, "bold")).place(relx=0.5, rely=0.5, anchor="center")

        # Message
        tk.Label(shell, text=message, bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 9), wraplength=240, justify=tk.LEFT,
                 anchor="w").pack(side=tk.LEFT, padx=(10, 16), pady=12)

        toast.update_idletasks()
        w = max(toast.winfo_reqwidth(), 280)
        h = toast.winfo_reqheight()

        try:
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
        except Exception:
            root_x, root_y, root_w, root_h = 0, 0, 800, 600

        offset_y = sum(t[1] + 8 for t in self._stack if t[0].winfo_exists())
        x_pos = root_x + root_w - w - 20
        y_pos = root_y + root_h - h - 20 - offset_y
        toast.geometry(f"{w}x{h}+{x_pos}+{y_pos}")

        entry = [toast, h]
        self._stack.append(entry)

        def _remove_from_stack():
            if entry in self._stack:
                self._stack.remove(entry)

        def fade_in(alpha=0.0):
            if not toast.winfo_exists():
                return
            alpha = min(alpha + 0.1, 1.0)
            toast.attributes("-alpha", alpha)
            if alpha < 1.0:
                toast.after(12, lambda: fade_in(alpha))
            else:
                toast.after(duration, fade_out)

        def fade_out(alpha=1.0):
            if not toast.winfo_exists():
                _remove_from_stack()
                return
            alpha = max(alpha - 0.07, 0.0)
            toast.attributes("-alpha", alpha)
            if alpha > 0.0:
                toast.after(14, lambda: fade_out(alpha))
            else:
                toast.destroy()
                _remove_from_stack()

        # Dismiss on click
        for w_ in shell.winfo_children():
            w_.bind("<Button-1>", lambda e: fade_out(toast.attributes("-alpha")))
        shell.bind("<Button-1>", lambda e: fade_out(toast.attributes("-alpha")))

        fade_in()

    def info(self, title, message, duration=3000):
        self.show(message, "info", duration)

    def success(self, title=None, message="", duration=3000):
        # handle both success("msg") and success("title", "msg")
        if message == "":
            message = title
        self.show(message, "success", duration)

    def warning(self, title, message, duration=3000):
        self.show(message, "warning", duration)

    def error(self, title, message, duration=3000):
        self.show(message, "error", duration)