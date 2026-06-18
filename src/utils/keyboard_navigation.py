"""Shared keyboard navigation helpers for list, tree, and grid UIs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, Optional, Sequence

TEXT_INPUT_CLASSES = (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, tk.Spinbox)


def is_text_input(widget) -> bool:
    if widget is None:
        return False
    try:
        return isinstance(widget, TEXT_INPUT_CLASSES)
    except tk.TclError:
        return False


def widget_in_container(widget, container) -> bool:
    if widget is None or container is None:
        return False
    try:
        if not container.winfo_exists():
            return False
        current = widget
        while current:
            if current == container:
                return True
            current = current.master
    except tk.TclError:
        return False
    return False


def is_workspace_zone(app) -> bool:
    return getattr(app, '_keyboard_focus_zone', None) == 'workspace'


def claim_workspace_focus(app, focus_widget=None):
    if hasattr(app, '_set_keyboard_focus_zone'):
        app._set_keyboard_focus_zone('workspace')
    if focus_widget is not None:
        try:
            if focus_widget.winfo_exists():
                focus_widget.configure(takefocus=1)
                focus_widget.focus_force()
        except (tk.TclError, AttributeError):
            pass


def bind_focus_target(container, focus_target, skip_widgets: Optional[Iterable] = None):
    skip = set(skip_widgets or ())

    def _on_click(event):
        if event.widget in skip:
            return
        try:
            focus_target.focus_set()
        except tk.TclError:
            pass

    try:
        container.bind("<Button-1>", _on_click, add="+")
    except tk.TclError:
        pass


def bind_keyboard_zone(container, zone: str, on_zone_change: Callable[[str], None],
                       skip_widgets: Optional[Iterable] = None):
    skip = set(skip_widgets or ())

    def _on_click(event):
        if event.widget in skip:
            return
        on_zone_change(zone)

    try:
        container.bind("<Button-1>", _on_click, add="+")
    except tk.TclError:
        pass


# ---------- anchor helpers ----------
def _get_anchor(tree):
    return getattr(tree, '_selection_anchor', None)


def _set_anchor(tree, iid):
    tree._selection_anchor = iid


def _select_range(tree, iids, anchor_idx, new_idx):
    """Select all items between anchor_idx and new_idx (inclusive)."""
    if not iids:
        return
    start, end = min(anchor_idx, new_idx), max(anchor_idx, new_idx)
    to_select = iids[start:end+1]
    tree.selection_set(to_select)
    tree.focus(iids[new_idx])
    tree.see(iids[new_idx])


def navigate_flat_tree(tree: ttk.Treeview, direction: str, *, shift_held: bool = False,
                       skip_iids: Optional[set] = None) -> bool:
    skip = skip_iids or set()
    children = [iid for iid in tree.get_children("") if iid not in skip]
    if not children:
        return False

    focused = tree.focus()
    if not focused or focused not in children:
        if tree.selection():
            focused = tree.selection()[0]
        else:
            focused = children[0]

    if focused not in children:
        focused = children[0]

    try:
        idx = children.index(focused)
    except ValueError:
        idx = 0

    if direction == "up":
        idx = max(0, idx - 1)
    elif direction == "down":
        idx = min(len(children) - 1, idx + 1)
    else:
        return False

    new_iid = children[idx]

    if shift_held:
        anchor = _get_anchor(tree)
        if anchor is None or anchor not in children:
            anchor = focused
        try:
            anchor_idx = children.index(anchor)
        except ValueError:
            anchor_idx = idx
        _select_range(tree, children, anchor_idx, idx)
    else:
        tree.selection_set(new_iid)
        _set_anchor(tree, new_iid)
        tree.focus(new_iid)
        tree.see(new_iid)

    return True


def navigate_hierarchical_tree(
    tree: ttk.Treeview,
    direction: str,
    *,
    shift_held: bool = False,
    all_iids_fn: Optional[Callable[[], Sequence[str]]] = None,
    arrows_expand: bool = True,
) -> bool:
    if all_iids_fn is None:
        def all_iids_fn():
            result = []
            def _walk(parent):
                for iid in tree.get_children(parent):
                    result.append(iid)
                    _walk(iid)
            _walk("")
            return result

    all_iids = list(all_iids_fn())
    if not all_iids:
        return False

    focused = tree.focus()
    if not focused or focused not in all_iids:
        if tree.selection():
            focused = tree.selection()[0]
        else:
            focused = all_iids[0]

    if focused not in all_iids:
        focused = all_iids[0]

    if direction in ("up", "down"):
        try:
            idx = all_iids.index(focused)
        except ValueError:
            idx = 0
        if direction == "up":
            idx = max(0, idx - 1)
        else:
            idx = min(len(all_iids) - 1, idx + 1)
        new_iid = all_iids[idx]

        if shift_held:
            anchor = _get_anchor(tree)
            if anchor is None or anchor not in all_iids:
                anchor = focused
            try:
                anchor_idx = all_iids.index(anchor)
            except ValueError:
                anchor_idx = idx
            _select_range(tree, all_iids, anchor_idx, idx)
        else:
            tree.selection_set(new_iid)
            _set_anchor(tree, new_iid)
            tree.focus(new_iid)
            tree.see(new_iid)
        return True

    if not arrows_expand:
        return False

    if direction == "left":
        if tree.get_children(focused):
            if tree.item(focused, "open"):
                tree.item(focused, open=False)
                return True
        parent = tree.parent(focused)
        if parent:
            tree.selection_set(parent)
            _set_anchor(tree, parent)
            tree.focus(parent)
            tree.see(parent)
            return True
        return False

    if direction == "right":
        if tree.get_children(focused):
            if not tree.item(focused, "open"):
                tree.item(focused, open=True)
                return True
            child = tree.get_children(focused)[0]
            tree.selection_set(child)
            _set_anchor(tree, child)
            tree.focus(child)
            tree.see(child)
            return True
        return False

    return False


def bind_tree_keyboard(
    tree: ttk.Treeview,
    *,
    on_activate: Optional[Callable[[str], None]] = None,
    hierarchical: bool = False,
    all_iids_fn: Optional[Callable[[], Sequence[str]]] = None,
    skip_iids: Optional[set] = None,
    arrows_expand: bool = True,
    is_active: Optional[Callable[[], bool]] = None,
):
    def _handle(event):
        if is_active is not None and not is_active():
            return
        keysym = event.keysym
        shift_held = bool(event.state & 0x1)

        if keysym in ("Up", "Down", "Left", "Right"):
            direction = keysym.lower()
            if hierarchical:
                handled = navigate_hierarchical_tree(
                    tree, direction,
                    shift_held=shift_held,
                    all_iids_fn=all_iids_fn,
                    arrows_expand=arrows_expand,
                )
            else:
                handled = navigate_flat_tree(
                    tree, direction,
                    shift_held=shift_held,
                    skip_iids=skip_iids,
                )
            if handled:
                return "break"
            return

        if keysym in ("Return", "KP_Enter") and on_activate:
            iid = tree.focus() or (tree.selection()[0] if tree.selection() else None)
            if iid:
                on_activate(iid)
            return "break"

    key_seqs = ["<Up>", "<Down>", "<Return>", "<KP_Enter>"]
    if arrows_expand:
        key_seqs.extend(["<Left>", "<Right>"])
    for seq in key_seqs:
        tree.bind(seq, _handle, add="+")


def bind_listbox_keyboard(listbox: tk.Listbox, *, on_activate: Optional[Callable[[int], None]] = None,
                          is_active: Optional[Callable[[], bool]] = None):
    def _handle(event):
        if is_active is not None and not is_active():
            return
        keysym = event.keysym
        size = listbox.size()
        if size <= 0:
            return "break"

        cur = listbox.curselection()
        idx = cur[0] if cur else 0

        if keysym == "Up":
            idx = max(0, idx - 1)
        elif keysym == "Down":
            idx = min(size - 1, idx + 1)
        elif keysym in ("Return", "KP_Enter"):
            if on_activate and cur:
                on_activate(cur[0])
            return "break"
        else:
            return

        listbox.selection_clear(0, tk.END)
        listbox.selection_set(idx)
        listbox.activate(idx)
        listbox.see(idx)
        return "break"

    for seq in ("<Up>", "<Down>", "<Return>", "<KP_Enter>"):
        listbox.bind(seq, _handle, add="+")


class FocusRing:
    """Cycle focus among registered widgets with Ctrl+Tab; use arrows/Enter/Esc in each."""

    def __init__(self, container=None, on_escape=None,
                 accent_color="#5E81F4", border_color="#E2E8F0"):
        self._entries: list = []
        self._focus_idx = -1
        self._container = container
        self._on_escape = on_escape
        self._accent_color = accent_color
        self._border_color = border_color

    def register(self, widget, key: str, *, activate=None, up=None, down=None,
                 left=None, right=None):
        self._entries = [e for e in self._entries if e['key'] != key]
        try:
            widget.configure(takefocus=1)
        except (tk.TclError, AttributeError):
            pass
        widget.bind("<FocusIn>", lambda e, w=widget: self._on_focus_in(w), add="+")
        widget.bind("<FocusOut>", lambda e, w=widget: self._on_focus_out(w), add="+")
        widget.bind("<Return>", lambda e: self._activate(), add="+")
        widget.bind("<KP_Enter>", lambda e: self._activate(), add="+")
        widget.bind("<Escape>", lambda e: self._escape(), add="+")
        if not is_text_input(widget):
            widget.bind("<Up>", lambda e: self._step(1), add="+")
            widget.bind("<Down>", lambda e: self._step(-1), add="+")
            widget.bind("<Left>", lambda e: self._nav_or_step(False), add="+")
            widget.bind("<Right>", lambda e: self._nav_or_step(True), add="+")
        self._entries.append({
            'key': key, 'widget': widget,
            'activate': activate, 'up': up, 'down': down,
            'left': left, 'right': right,
        })

    def _visible_entries(self):
        return [e for e in self._entries
                if e['widget'].winfo_exists() and e['widget'].winfo_ismapped()]

    def _entry_for(self, widget):
        for e in self._entries:
            if e['widget'] == widget:
                return e
        return None

    def _on_focus_in(self, widget):
        sep = getattr(widget, '_focus_separator', None)
        if sep is not None:
            try:
                sep.config(bg=self._accent_color)
                widget.config(highlightthickness=0)
            except tk.TclError:
                pass
            return
        try:
            widget.configure(highlightthickness=2,
                             highlightbackground=self._accent_color,
                             highlightcolor=self._accent_color)
        except tk.TclError:
            pass
        visible = self._visible_entries()
        for i, e in enumerate(visible):
            if e['widget'] == widget:
                self._focus_idx = i
                break

    def _on_focus_out(self, widget):
        sep = getattr(widget, '_focus_separator', None)
        if sep is not None:
            try:
                sep.config(bg=self._border_color)
            except tk.TclError:
                pass
            return
        try:
            widget.configure(highlightthickness=1,
                             highlightbackground=self._border_color,
                             highlightcolor=self._border_color)
        except tk.TclError:
            pass

    def _activate(self):
        visible = self._visible_entries()
        if 0 <= self._focus_idx < len(visible):
            fn = visible[self._focus_idx].get('activate')
            if fn:
                fn()
        return "break"

    def _step(self, delta):
        visible = self._visible_entries()
        if 0 <= self._focus_idx < len(visible):
            entry = visible[self._focus_idx]
            fn = entry['up'] if delta > 0 else entry['down']
            if fn:
                fn()
                return "break"
        return "break"

    def _nav_or_step(self, forward):
        visible = self._visible_entries()
        if 0 <= self._focus_idx < len(visible):
            entry = visible[self._focus_idx]
            fn = entry['right'] if forward else entry['left']
            if fn:
                fn()
                return "break"
        self.cycle(reverse=not forward)
        return "break"

    def _escape(self):
        if self._on_escape:
            self._on_escape()
        return "break"

    def cycle(self, reverse=False) -> bool:
        visible = self._visible_entries()
        if not visible:
            return False
        try:
            focused = visible[0]['widget'].winfo_toplevel().focus_get()
        except tk.TclError:
            focused = None
        cur_idx = next((i for i, e in enumerate(visible) if e['widget'] == focused), -1)
        if cur_idx < 0:
            new_idx = len(visible) - 1 if reverse else 0
        else:
            new_idx = (cur_idx + (-1 if reverse else 1)) % len(visible)
        visible[new_idx]['widget'].focus_set()
        self._focus_idx = new_idx
        return True

    def handle_ctrl_tab(self, event=None, reverse=False) -> bool:
        if self._container is not None:
            try:
                focused = event.widget.winfo_toplevel().focus_get() if event else None
            except tk.TclError:
                focused = None
            if focused is not None and not widget_in_container(focused, self._container):
                return False
        return self.cycle(reverse=reverse)

    def is_in_ring(self, widget) -> bool:
        if widget is None:
            return False
        for e in self._entries:
            if e['widget'] == widget:
                return True
        return False

    def visible_widgets(self):
        return [e['widget'] for e in self._visible_entries()]

    def at_boundary(self, focused, reverse=False) -> bool:
        visible = self._visible_entries()
        if not visible:
            return True
        cur_idx = next((i for i, e in enumerate(visible) if e['widget'] == focused), -1)
        if cur_idx < 0:
            return False
        if reverse:
            return cur_idx == 0
        return cur_idx == len(visible) - 1

    def focus_key(self, key: str):
        for e in self._entries:
            if e['key'] == key and e['widget'].winfo_exists():
                e['widget'].focus_set()
                return True
        return False


def preview_coords_for_widget(widget):
    try:
        return (
            widget.winfo_rootx() + max(10, widget.winfo_width() // 2),
            widget.winfo_rooty() + max(10, widget.winfo_height() // 2),
        )
    except tk.TclError:
        return 100, 100


def preview_coords_for_tree_item(tree, iid):
    try:
        bbox = tree.bbox(iid)
        if bbox:
            x, y, w, h = bbox
            return tree.winfo_rootx() + x + w // 2, tree.winfo_rooty() + y + h // 2
        return tree.winfo_rootx() + 10, tree.winfo_rooty() + 10
    except tk.TclError:
        return 100, 100


def scroll_widget_into_view(canvas: tk.Canvas, widget, padding: int = 8):
    if canvas is None or widget is None:
        return
    try:
        if not canvas.winfo_exists() or not widget.winfo_exists():
            return
        canvas.update_idletasks()
        canvas_height = canvas.winfo_height()
        widget_y = widget.winfo_y()
        widget_h = widget.winfo_height()
        top = canvas.canvasy(0)
        bottom = top + canvas_height
        if widget_y < top + padding:
            canvas.yview_moveto(max(0, (widget_y - padding) / max(1, canvas.bbox("all")[3])))
        elif widget_y + widget_h > bottom - padding:
            target = widget_y + widget_h - canvas_height + padding
            total = max(1, canvas.bbox("all")[3])
            canvas.yview_moveto(max(0, target / total))
    except (tk.TclError, TypeError, ZeroDivisionError):
        pass