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
            focus_widget.configure(takefocus=1)
            focus_widget.focus_set()
        except tk.TclError:
            pass


def bind_focus_target(container, focus_target, skip_widgets: Optional[Iterable] = None):
    """Focus *focus_target* when *container* is clicked (except skipped widgets)."""
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
    """Track which UI region should receive keyboard navigation."""
    skip = set(skip_widgets or ())

    def _on_click(event):
        if event.widget in skip:
            return
        on_zone_change(zone)

    try:
        container.bind("<Button-1>", _on_click, add="+")
    except tk.TclError:
        pass


def navigate_flat_tree(tree: ttk.Treeview, direction: str, *, skip_iids: Optional[set] = None) -> bool:
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

    iid = children[idx]
    tree.selection_set(iid)
    tree.focus(iid)
    tree.see(iid)
    return True


def navigate_hierarchical_tree(
    tree: ttk.Treeview,
    direction: str,
    *,
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
        iid = all_iids[idx]
        tree.selection_set(iid)
        tree.focus(iid)
        tree.see(iid)
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
    """Bind arrow keys and Enter on a tree widget."""

    def _handle(event):
        if is_active is not None and not is_active():
            return
        keysym = event.keysym
        if keysym in ("Up", "Down", "Left", "Right"):
            direction = keysym.lower()
            if hierarchical:
                handled = navigate_hierarchical_tree(
                    tree, direction,
                    all_iids_fn=all_iids_fn,
                    arrows_expand=arrows_expand,
                )
            else:
                handled = navigate_flat_tree(tree, direction, skip_iids=skip_iids)
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
