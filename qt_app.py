import sys
import os
import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSplitter, QCheckBox, QSpinBox,
    QTextEdit, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QCoreApplication

from utils import gather_videos_with_directories, is_video
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory
from key_press import listen_keys, cleanup_hotkeys


class QtDirectorySelector(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Recursive Video Player (PyQt)")
        self.resize(1200, 800)

        self.selected_dirs = []
        self.excluded_subdirs = {}
        self.excluded_videos = {}
        self.controller = None
        self.player_thread = None
        self.keys_thread = None
        self.video_count = 0
        self.current_selected_dir_index = None
        self.current_view_items = []
        self.show_videos = True
        self.show_only_excluded = False
        self.current_max_depth = 20

        self._build_ui()

        self.scan_cache = {}
        self.pending_scans = set()

        self.log(f"Scanner ready")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("TopBar")
        bar_layout = QHBoxLayout(top_bar)
        bar_layout.setContentsMargins(12, 12, 12, 12)
        bar_layout.setSpacing(8)
        self.btn_add_dir = QPushButton("Add Directory")
        self.btn_remove_dir = QPushButton("Remove Selected")
        self.btn_play = QPushButton("Play Videos")
        self.btn_play.setObjectName("PrimaryButton")
        bar_layout.addWidget(self.btn_add_dir)
        bar_layout.addWidget(self.btn_remove_dir)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.btn_play)
        root_layout.addWidget(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_widget.setObjectName("LeftPanel")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        self.list_dirs = QListWidget()
        self.list_dirs.setAlternatingRowColors(True)
        _lbl_dirs = QLabel("Selected Directories")
        _lbl_dirs.setObjectName("SectionTitle")
        left_layout.addWidget(_lbl_dirs)
        left_layout.addWidget(self.list_dirs, 2)

        options_row = QHBoxLayout()
        self.chk_show_videos = QCheckBox("Show Videos")
        self.chk_show_videos.setChecked(True)
        self.chk_only_excluded = QCheckBox("Excluded Only")
        options_row.addWidget(self.chk_show_videos)
        options_row.addWidget(self.chk_only_excluded)
        options_row.addStretch(1)
        options_row.addWidget(QLabel("Max Depth:"))
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(1, 50)
        self.spin_depth.setValue(20)
        options_row.addWidget(self.spin_depth)
        left_layout.addLayout(options_row)

        self.list_subdirs = QListWidget()
        self.list_subdirs.setAlternatingRowColors(True)
        _lbl_subs = QLabel("Subdirectories & Videos")
        _lbl_subs.setObjectName("SectionTitle")
        left_layout.addWidget(_lbl_subs)
        left_layout.addWidget(self.list_subdirs, 3)

        actions_row1 = QHBoxLayout()
        self.btn_exclude = QPushButton("Exclude Selected")
        self.btn_exclude.setObjectName("DangerButton")
        self.btn_include = QPushButton("Include Selected")
        self.btn_include.setObjectName("SuccessButton")
        self.btn_exclude_all = QPushButton("Exclude All")
        self.btn_exclude_all.setObjectName("WarningButton")
        actions_row1.addWidget(self.btn_exclude)
        actions_row1.addWidget(self.btn_include)
        actions_row1.addWidget(self.btn_exclude_all)
        actions_row1.addStretch(1)
        left_layout.addLayout(actions_row1)

        actions_row2 = QHBoxLayout()
        self.btn_expand = QPushButton("Expand All")
        self.btn_collapse = QPushButton("Collapse All")
        self.btn_toggle_videos = QPushButton("Hide Videos")
        self.btn_toggle_excluded = QPushButton("Excluded Only")
        self.btn_clear_exclusions = QPushButton("Clear All Exclusions")
        self.btn_clear_exclusions.setObjectName("WarningButton")
        actions_row2.addWidget(self.btn_expand)
        actions_row2.addWidget(self.btn_collapse)
        actions_row2.addWidget(self.btn_clear_exclusions)
        actions_row2.addStretch(1)
        left_layout.addLayout(actions_row2)

        left_widget.setLayout(left_layout)

        right_widget = QWidget()
        right_widget.setObjectName("RightPanel")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)
        _lbl_console = QLabel("Console")
        _lbl_console.setObjectName("SectionTitle")
        right_layout.addWidget(_lbl_console)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        right_layout.addWidget(self.console, 1)

        console_btn_row = QHBoxLayout()
        self.btn_clear_console = QPushButton("Clear Console")
        console_btn_row.addWidget(self.btn_clear_console)
        console_btn_row.addStretch(1)
        right_layout.addLayout(console_btn_row)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root_layout.addWidget(splitter, 1)

        status_row = QHBoxLayout()
        status_container = QWidget()
        status_container.setObjectName("StatusBar")
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(12, 8, 12, 8)
        self.lbl_status = QLabel("Ready")
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch(1)
        root_layout.addWidget(status_container)

        self.btn_add_dir.clicked.connect(self.add_directory)
        self.btn_remove_dir.clicked.connect(self.remove_directory)
        self.btn_play.clicked.connect(self.play_videos)
        self.list_dirs.currentRowChanged.connect(self.on_directory_select)
        self.chk_show_videos.toggled.connect(self.refresh_subdirs_view)
        self.chk_only_excluded.toggled.connect(self.refresh_subdirs_view)
        self.spin_depth.valueChanged.connect(self.on_depth_changed)
        self.btn_exclude.clicked.connect(self.exclude_selected)
        self.btn_include.clicked.connect(self.include_selected)
        self.btn_exclude_all.clicked.connect(self.exclude_all)
        self.btn_expand.clicked.connect(self.expand_all)
        self.btn_collapse.clicked.connect(self.collapse_all)
        self.btn_toggle_videos.clicked.connect(self.toggle_videos)
        self.btn_toggle_excluded.clicked.connect(self.toggle_excluded_only)
        self.btn_clear_exclusions.clicked.connect(self.clear_all_exclusions)
        self.btn_clear_console.clicked.connect(self.clear_console)
        self.list_subdirs.itemDoubleClicked.connect(self.on_subitem_double_clicked)
        self.list_subdirs.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def log(self, message: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.console.append(f"[{timestamp}] {message}")

    def set_status(self, text: str):
        self.lbl_status.setText(text)

    def add_directory(self):
        dlg = QFileDialog(self, "Select Directory")
        dlg.setFileMode(QFileDialog.FileMode.Directory)
        dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
        if dlg.exec():
            dirs = dlg.selectedFiles()
            for d in dirs:
                if d and d not in self.selected_dirs:
                    self.selected_dirs.append(d)
                    self.list_dirs.addItem(d)
                    self.load_subdirectories(d)
            self.update_video_count()

    def remove_directory(self):
        row = self.list_dirs.currentRow()
        if row >= 0:
            dir_path = self.selected_dirs.pop(row)
            self.list_dirs.takeItem(row)
            if dir_path in self.excluded_subdirs:
                del self.excluded_subdirs[dir_path]
            for v in list(self.excluded_videos.keys()):
                if v.startswith(dir_path):
                    del self.excluded_videos[v]
            if dir_path in self.current_subdirs_mapping:
                del self.current_subdirs_mapping[dir_path]
            self.refresh_subdirs_view()
            self.update_video_count()

    def on_depth_changed(self, value):
        self.current_max_depth = value
        self.refresh_subdirs_view()

    def on_directory_select(self, row):
        self.current_selected_dir_index = row
        self.refresh_subdirs_view()

    def refresh_subdirs_view(self):
        self.list_subdirs.clear()
        self.current_view_items = []
        row = self.list_dirs.currentRow()
        if row < 0 or row >= len(self.selected_dirs):
            return
        base_dir = self.selected_dirs[row]
        show_videos = self.chk_show_videos.isChecked()
        only_excluded = self.chk_only_excluded.isChecked()

        excluded_dir_set = set(self.excluded_subdirs.get(base_dir, []))
        excluded_vid_set = set(self.excluded_videos.get(base_dir, []))

        max_depth = self.current_max_depth
        base = os.path.abspath(base_dir)
        base_sep = os.sep
        try:
            for root, dirs, files in os.walk(base):
                rel = os.path.relpath(root, base)
                depth = 0 if rel == '.' else rel.count(base_sep) + 1
                if depth > max_depth:
                    dirs[:] = []
                    continue
                indent_level = 0 if rel == '.' else rel.count(base_sep) + 1
                name = os.path.basename(root) if rel != '.' else os.path.basename(base)
                include_dir = (not only_excluded) or (root in excluded_dir_set)
                if include_dir:
                    label = ("  " * indent_level) + "📁 " + name
                    if root in excluded_dir_set:
                        label += "  [EXCLUDED]"
                    self.list_subdirs.addItem(label)
                    self.current_view_items.append(root)
                if show_videos:
                    try:
                        with os.scandir(root) as it:
                            for entry in it:
                                if entry.is_file() and is_video(entry.name):
                                    full = entry.path
                                    include_vid = (not only_excluded) or (full in excluded_vid_set)
                                    if include_vid:
                                        vlabel = ("  " * (indent_level + 1)) + "🎬 " + entry.name
                                        if full in excluded_vid_set:
                                            vlabel += "  [EXCLUDED]"
                                        self.list_subdirs.addItem(vlabel)
                                        self.current_view_items.append(full)
                    except PermissionError:
                        pass
        except Exception:
            pass

        self.update_video_count()

    def update_video_count(self):
        videos = []
        video_to_dir = {}
        directories = []
        for base_dir in self.selected_dirs:
            v, m, ds = gather_videos_with_directories(base_dir)
            subs_excl = set(self.excluded_subdirs.get(base_dir, []))
            for d in ds:
                include_dir = True
                for ex in subs_excl:
                    if d.startswith(ex):
                        include_dir = False
                        break
                if include_dir:
                    directories.append(d)
            for video, dir_path in m.items():
                if any(video.startswith(ex) for ex in subs_excl):
                    continue
                if video in self.excluded_videos.get(base_dir, []):
                    continue
                videos.append(video)
                video_to_dir[video] = dir_path
        self.video_count = len(videos)
        self.set_status(f"Videos ready: {self.video_count}")

    def load_subdirectories(self, directory):
        self.refresh_subdirs_view()

    def play_videos(self):
        videos = []
        video_to_dir = {}
        directories = []
        for base_dir in self.selected_dirs:
            v, m, ds = gather_videos_with_directories(base_dir)
            subs_excl = set(self.excluded_subdirs.get(base_dir, []))
            for d in ds:
                if not any(d.startswith(ex) for ex in subs_excl):
                    directories.append(d)
            for video, dir_path in m.items():
                if any(video.startswith(ex) for ex in subs_excl):
                    continue
                if video in self.excluded_videos.get(base_dir, []):
                    continue
                videos.append(video)
                video_to_dir[video] = dir_path

        if not videos:
            QMessageBox.information(self, "No Videos", "No videos to play with current settings.")
            return

        if self.controller:
            try:
                self.controller.stop()
            except Exception:
                pass

        self.controller = VLCPlayerControllerForMultipleDirectory(
            videos, video_to_dir, directories,
            logger=lambda msg: self.log(str(msg))
        )
        self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
        self.player_thread.start()

        def key_thread():
            listen_keys(self.controller, multi_directory=True)
        self.keys_thread = threading.Thread(target=key_thread, daemon=True)
        self.keys_thread.start()

        self.log("Started playback. Use keyboard: A/D prev/next, Space pause, F fullscreen, arrows seek, 1/2 monitor, T screenshot, W/S volume, Q/E prev/next dir.")

    def closeEvent(self, event):
        try:
            if self.controller:
                self.controller.stop()
        except Exception:
            pass
        try:
            cleanup_hotkeys()
        except Exception:
            pass
        super().closeEvent(event)

    def _get_current_base_dir(self):
        row = self.list_dirs.currentRow()
        if row < 0 or row >= len(self.selected_dirs):
            return None
        return self.selected_dirs[row]

    def exclude_selected(self):
        base_dir = self._get_current_base_dir()
        if not base_dir:
            QMessageBox.information(self, "Information", "Please select a directory first.")
            return
        sel_rows = [i.row() for i in self.list_subdirs.selectedIndexes()]
        if not sel_rows:
            QMessageBox.information(self, "Information", "Please select items to exclude.")
            return
        self.excluded_subdirs.setdefault(base_dir, [])
        self.excluded_videos.setdefault(base_dir, [])
        excl_dirs = set(self.excluded_subdirs[base_dir])
        excl_vids = set(self.excluded_videos[base_dir])
        changed = 0
        for r in sel_rows:
            if r < 0 or r >= len(self.current_view_items):
                continue
            p = self.current_view_items[r]
            if os.path.isdir(p):
                if p not in excl_dirs:
                    self.excluded_subdirs[base_dir].append(p)
                    excl_dirs.add(p)
                    changed += 1
            else:
                if p not in excl_vids:
                    self.excluded_videos[base_dir].append(p)
                    excl_vids.add(p)
                    changed += 1
        if changed:
            self.log(f"Excluded {changed} item(s) from '{os.path.basename(base_dir)}'")
        self.refresh_subdirs_view()

    def include_selected(self):
        base_dir = self._get_current_base_dir()
        if not base_dir:
            QMessageBox.information(self, "Information", "Please select a directory first.")
            return
        sel_rows = [i.row() for i in self.list_subdirs.selectedIndexes()]
        if not sel_rows:
            QMessageBox.information(self, "Information", "Please select items to include.")
            return
        changed = 0
        if base_dir in self.excluded_subdirs:
            dirs_list = self.excluded_subdirs[base_dir]
        else:
            dirs_list = []
        if base_dir in self.excluded_videos:
            vids_list = self.excluded_videos[base_dir]
        else:
            vids_list = []
        for r in sel_rows:
            if r < 0 or r >= len(self.current_view_items):
                continue
            p = self.current_view_items[r]
            if os.path.isdir(p):
                if p in dirs_list:
                    dirs_list.remove(p)
                    changed += 1
            else:
                if p in vids_list:
                    vids_list.remove(p)
                    changed += 1
        if dirs_list:
            self.excluded_subdirs[base_dir] = dirs_list
        elif base_dir in self.excluded_subdirs:
            del self.excluded_subdirs[base_dir]
        if vids_list:
            self.excluded_videos[base_dir] = vids_list
        elif base_dir in self.excluded_videos:
            del self.excluded_videos[base_dir]
        if changed:
            self.log(f"Included {changed} item(s) in '{os.path.basename(base_dir)}'")
        self.refresh_subdirs_view()

    def exclude_all(self):
        base_dir = self._get_current_base_dir()
        if not base_dir:
            QMessageBox.information(self, "Information", "Please select a directory first.")
            return
        self.excluded_subdirs.setdefault(base_dir, [])
        if base_dir not in self.excluded_subdirs[base_dir]:
            self.excluded_subdirs[base_dir].append(base_dir)
        self.log(f"Excluded ALL in '{os.path.basename(base_dir)}'")
        self.refresh_subdirs_view()

    def expand_all(self):
        self.spin_depth.setValue(50)

    def collapse_all(self):
        self.spin_depth.setValue(1)

    def toggle_videos(self):
        self.chk_show_videos.setChecked(not self.chk_show_videos.isChecked())
        self.btn_toggle_videos.setText("Hide Videos" if self.chk_show_videos.isChecked() else "Show Videos")

    def toggle_excluded_only(self):
        self.chk_only_excluded.setChecked(not self.chk_only_excluded.isChecked())
        self.btn_toggle_excluded.setText("Show All" if self.chk_only_excluded.isChecked() else "Excluded Only")

    def clear_all_exclusions(self):
        base_dir = self._get_current_base_dir()
        if not base_dir:
            QMessageBox.information(self, "Information", "Please select a directory first.")
            return
        had = 0
        if base_dir in self.excluded_subdirs:
            had += len(self.excluded_subdirs[base_dir])
            del self.excluded_subdirs[base_dir]
        if base_dir in self.excluded_videos:
            had += len(self.excluded_videos[base_dir])
            del self.excluded_videos[base_dir]
        if had:
            self.log(f"Cleared all {had} exclusions for '{os.path.basename(base_dir)}'")
        self.refresh_subdirs_view()

    def on_subitem_double_clicked(self, item):
        row = self.list_dirs.currentRow()
        if row < 0 or row >= len(self.selected_dirs):
            return
        base_dir = self.selected_dirs[row]
        idx = self.list_subdirs.currentRow()
        if idx < 0 or idx >= len(self.current_view_items):
            return
        p = self.current_view_items[idx]
        if os.path.isdir(p):
            lst = self.excluded_subdirs.setdefault(base_dir, [])
        else:
            lst = self.excluded_videos.setdefault(base_dir, [])
        if p in lst:
            lst.remove(p)
            self.log(f"Included 1 item in '{os.path.basename(base_dir)}'")
        else:
            lst.append(p)
            self.log(f"Excluded 1 item from '{os.path.basename(base_dir)}'")
        self.refresh_subdirs_view()

    def clear_console(self):
        self.console.clear()
        self.log("Console cleared")


def run_qt_app():
    try:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
    except Exception:
        pass

    app = QApplication(sys.argv)
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    app.setStyleSheet("""
    /* Base */
    QMainWindow { background-color: #0b1020; }
    QWidget { color: #e5e7eb; }

    /* Top Bar */
    QWidget#TopBar { background-color: #111827; border-bottom: 1px solid #1f2937; }

    /* Panels */
    QWidget#LeftPanel { background-color: #0b1220; }
    QWidget#RightPanel { background-color: #0b142a; }
    QWidget#StatusBar { background-color: #0f172a; border-top: 1px solid #1f2937; }

    /* Section titles with different accents */
    QLabel#SectionTitle { font-size: 13px; font-weight: 600; margin: 2px 0 4px 0; }
    QWidget#LeftPanel QLabel#SectionTitle { color: #60a5fa; }
    QWidget#RightPanel QLabel#SectionTitle { color: #a78bfa; }

    /* Buttons */
    QPushButton {
        background-color: #1f2937;
        color: #e5e7eb;
        border: 1px solid #374151;
        padding: 7px 12px;
        border-radius: 8px;
    }
    QPushButton:hover { background-color: #273449; border-color: #3b82f6; }
    QPushButton:pressed { background-color: #1e3a8a; }
    QPushButton#PrimaryButton {
        background-color: #3b82f6;
        border: 1px solid #2563eb;
        color: #0b1220;
        font-weight: 600;
    }
    QPushButton#PrimaryButton:hover { background-color: #60a5fa; border-color: #3b82f6; }
    QPushButton#PrimaryButton:pressed { background-color: #2563eb; }
    QPushButton#DangerButton, QPushButton#WarningButton, QPushButton#SuccessButton { color: #0b1220; font-weight: 600; }
    QPushButton#DangerButton { background-color: #f87171; border: 1px solid #ef4444; }
    QPushButton#DangerButton:hover { background-color: #fca5a5; }
    QPushButton#WarningButton { background-color: #fbbf24; border: 1px solid #f59e0b; }
    QPushButton#WarningButton:hover { background-color: #fcd34d; }
    QPushButton#SuccessButton { background-color: #34d399; border: 1px solid #10b981; }
    QPushButton#SuccessButton:hover { background-color: #6ee7b7; }

    /* Lists and text areas */
    QListWidget, QTextEdit, QSpinBox {
        background-color: #0b1220;
        color: #e5e7eb;
        border: 1px solid #374151;
        border-radius: 8px;
    }
    QListWidget { alternate-background-color: #111827; }
    QListWidget::item:selected { background: #3b82f6; color: #0b1220; }
    QTextEdit:focus, QSpinBox:focus, QListWidget:focus { border-color: #60a5fa; }

    /* Checkboxes */
    QCheckBox { color: #e5e7eb; }
    QCheckBox::indicator {
        width: 16px; height: 16px;
        border: 1px solid #64748b;
        border-radius: 3px;
        background: #0b1220;
    }
    QCheckBox::indicator:hover { border-color: #60a5fa; }
    QCheckBox::indicator:checked {
        background: #3b82f6;
        border-color: #2563eb;
    }

    /* Splitter */
    QSplitter::handle { background-color: #374151; }
    QSplitter::handle:hover { background-color: #3b82f6; }

    /* Scrollbars */
    QScrollBar:vertical {
        background: #0b1220; width: 10px; margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #334155; min-height: 24px; border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover { background: #3b82f6; }
    QScrollBar:horizontal {
        background: #0b1220; height: 10px; margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: #334155; min-width: 24px; border-radius: 4px;
    }
    QScrollBar::handle:horizontal:hover { background: #3b82f6; }
    """)

    win = QtDirectorySelector()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_qt_app()
