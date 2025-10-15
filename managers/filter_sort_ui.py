"""
UI Integration for Advanced Filtering and Sorting
Integrates with existing Recursive Video Player interface
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading


class FilterSortUI:
    """UI components for filter and sort functionality"""

    def __init__(self, parent, theme_provider, filter_sort_manager, on_apply_callback):
        self.parent = parent
        self.theme_provider = theme_provider
        self.manager = filter_sort_manager
        self.on_apply_callback = on_apply_callback

        self.filter_window = None
        self.app_instance = None

    def show_filter_dialog(self):
        """Show advanced filter dialog"""
        if self.filter_window and self.filter_window.winfo_exists():
            self.filter_window.lift()
            return

        self.filter_window = tk.Toplevel(self.parent)
        self.filter_window.title("Advanced Filters & Sorting")
        self.filter_window.geometry("1600x900")
        self.filter_window.configure(bg=self.theme_provider.bg_color)
        self.filter_window.minsize(700, 450)

        self._setup_filter_ui()

    def _setup_filter_ui(self):
        """Setup filter UI components"""
        main_frame = tk.Frame(self.filter_window, bg=self.theme_provider.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Header with title and action buttons
        header_frame = tk.Frame(main_frame, bg=self.theme_provider.bg_color)
        header_frame.pack(fill=tk.X, padx=20, pady=(20, 10))

        title_label = tk.Label(
            header_frame,
            text="🔧 Advanced Filters & Sorting",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        title_label.pack(side=tk.LEFT)

        # Action buttons on the right side of header
        button_container = tk.Frame(header_frame, bg=self.theme_provider.bg_color)
        button_container.pack(side=tk.RIGHT)

        reset_btn = self.theme_provider.create_button(
            button_container,
            "Reset All",
            self._reset_filters,
            "warning",
            "sm"
        )
        reset_btn.pack(side=tk.LEFT, padx=(0, 5))

        cancel_btn = self.theme_provider.create_button(
            button_container,
            "Cancel",
            self.filter_window.destroy,
            "secondary",
            "sm"
        )
        cancel_btn.pack(side=tk.LEFT, padx=(0, 5))

        apply_btn = self.theme_provider.create_button(
            button_container,
            "Apply",
            self._apply_filters,
            "success",
            "sm"
        )
        apply_btn.pack(side=tk.LEFT)

        # Create notebook for organized sections
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Quick Filters Tab
        quick_tab = self._create_quick_filters_tab(notebook)
        notebook.add(quick_tab, text="Quick Filters")

        # Sort Options Tab
        sort_tab = self._create_sort_options_tab(notebook)
        notebook.add(sort_tab, text="Sort Options")

        # Advanced Filters Tab
        advanced_tab = self._create_advanced_filters_tab(notebook)
        notebook.add(advanced_tab, text="Advanced Filters")

        # Statistics Tab
        stats_tab = self._create_statistics_tab(notebook)
        notebook.add(stats_tab, text="Statistics")



    def _create_quick_filters_tab(self, parent):
        """Create quick filters tab"""
        frame = tk.Frame(parent, bg=self.theme_provider.bg_color)

        container = tk.Frame(frame, bg=self.theme_provider.bg_color, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            container,
            text="Quick Filter Presets:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        label.pack(anchor='w', pady=(0, 10))

        self.quick_filter_var = tk.StringVar(value='all')

        quick_filters = self.manager.get_quick_filter_names()

        # Group filters by category
        categories = {
            'General': ['all'],
            'Recently Added': ['recent_7days', 'recent_30days'],
            'Playback History': ['played_today', 'played_week', 'never_played', 'frequently_played'],
            'Quality': ['hd_videos', 'full_hd_videos'],
            'Duration': ['short_videos', 'long_videos'],
            'File Size': ['large_files']
        }

        for category, filter_keys in categories.items():
            cat_frame = tk.LabelFrame(
                container,
                text=category,
                font=self.theme_provider.normal_font,
                bg=self.theme_provider.bg_color,
                fg=self.theme_provider.text_color,
                padx=10,
                pady=10
            )
            cat_frame.pack(fill=tk.X, pady=(0, 10))

            for key, name in quick_filters:
                if key in filter_keys:
                    radio = ttk.Radiobutton(
                        cat_frame,
                        text=name,
                        variable=self.quick_filter_var,
                        value=key,
                        style="TRadiobutton"
                    )
                    radio.pack(anchor='w', pady=2)

        return frame

    def _create_sort_options_tab(self, parent):
        """Create sort options tab"""
        frame = tk.Frame(parent, bg=self.theme_provider.bg_color)

        container = tk.Frame(frame, bg=self.theme_provider.bg_color, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            container,
            text="Sort Videos By:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        label.pack(anchor='w', pady=(0, 10))

        self.sort_var = tk.StringVar(value='name_asc')

        sort_options = self.manager.get_sort_options()

        # Group sort options by category
        categories = {
            'Name': ['name_asc', 'name_desc'],
            'Date': ['date_modified_desc', 'date_modified_asc', 'date_created_desc', 'date_created_asc'],
            'Size': ['size_desc', 'size_asc'],
            'Duration': ['duration_desc', 'duration_asc'],
            'Resolution': ['resolution_desc', 'resolution_asc'],
            'Playback': ['play_count_desc', 'play_count_asc', 'last_played_desc', 'last_played_asc', 'watch_time_desc'],
            'Other': ['random']
        }

        for category, sort_keys in categories.items():
            cat_frame = tk.LabelFrame(
                container,
                text=category,
                font=self.theme_provider.normal_font,
                bg=self.theme_provider.bg_color,
                fg=self.theme_provider.text_color,
                padx=10,
                pady=10
            )
            cat_frame.pack(fill=tk.X, pady=(0, 10))

            for key, name in sort_options:
                if key in sort_keys:
                    radio = ttk.Radiobutton(
                        cat_frame,
                        text=name,
                        variable=self.sort_var,
                        value=key,
                        style="TRadiobutton"
                    )
                    radio.pack(anchor='w', pady=2)

        return frame

    def _create_advanced_filters_tab(self, parent):
        """Create advanced filters tab"""
        frame = tk.Frame(parent, bg=self.theme_provider.bg_color)

        # Scrollable container
        canvas = tk.Canvas(frame, bg=self.theme_provider.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.theme_provider.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        container = tk.Frame(scrollable_frame, bg=self.theme_provider.bg_color, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        # File Size Section
        size_frame = tk.LabelFrame(
            container,
            text="File Size",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        size_frame.pack(fill=tk.X, pady=(0, 10))

        size_row = tk.Frame(size_frame, bg=self.theme_provider.bg_color)
        size_row.pack(fill=tk.X)

        tk.Label(size_row, text="Min (MB):", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=12, anchor='w').pack(side=tk.LEFT)
        self.min_size_entry = tk.Entry(size_row, width=10)
        self.min_size_entry.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(size_row, text="Max (MB):", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=12, anchor='w').pack(side=tk.LEFT)
        self.max_size_entry = tk.Entry(size_row, width=10)
        self.max_size_entry.pack(side=tk.LEFT)

        # Duration Section
        duration_frame = tk.LabelFrame(
            container,
            text="Duration",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        duration_frame.pack(fill=tk.X, pady=(0, 10))

        dur_row = tk.Frame(duration_frame, bg=self.theme_provider.bg_color)
        dur_row.pack(fill=tk.X)

        tk.Label(dur_row, text="Min (sec):", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=12, anchor='w').pack(side=tk.LEFT)
        self.min_duration_entry = tk.Entry(dur_row, width=10)
        self.min_duration_entry.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(dur_row, text="Max (sec):", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=12, anchor='w').pack(side=tk.LEFT)
        self.max_duration_entry = tk.Entry(dur_row, width=10)
        self.max_duration_entry.pack(side=tk.LEFT)

        # Resolution Section
        res_frame = tk.LabelFrame(
            container,
            text="Resolution",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        res_frame.pack(fill=tk.X, pady=(0, 10))

        self.resolution_vars = {}
        resolutions = ['4K', '2K', '1080p', '720p', '480p', 'SD']

        res_grid = tk.Frame(res_frame, bg=self.theme_provider.bg_color)
        res_grid.pack(fill=tk.X)

        for i, res in enumerate(resolutions):
            var = tk.BooleanVar()
            self.resolution_vars[res] = var
            check = ttk.Checkbutton(
                res_grid,
                text=res,
                variable=var,
                style="Modern.TCheckbutton"
            )
            check.grid(row=i // 3, column=i % 3, sticky='w', padx=5, pady=2)

        # Modified Date Section
        date_frame = tk.LabelFrame(
            container,
            text="Date Modified",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        date_frame.pack(fill=tk.X, pady=(0, 10))

        date_row = tk.Frame(date_frame, bg=self.theme_provider.bg_color)
        date_row.pack(fill=tk.X)

        tk.Label(date_row, text="Within last (days):", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=18, anchor='w').pack(side=tk.LEFT)
        self.modified_days_entry = tk.Entry(date_row, width=10)
        self.modified_days_entry.pack(side=tk.LEFT)

        # Text Search Section
        search_frame = tk.LabelFrame(
            container,
            text="Text Search",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        search_frame.pack(fill=tk.X, pady=(0, 10))

        search_row1 = tk.Frame(search_frame, bg=self.theme_provider.bg_color)
        search_row1.pack(fill=tk.X, pady=(0, 5))

        tk.Label(search_row1, text="Filename contains:", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=18, anchor='w').pack(side=tk.LEFT)
        self.filename_search_entry = tk.Entry(search_row1)
        self.filename_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        search_row2 = tk.Frame(search_frame, bg=self.theme_provider.bg_color)
        search_row2.pack(fill=tk.X)

        tk.Label(search_row2, text="Path contains:", bg=self.theme_provider.bg_color,
                 fg=self.theme_provider.text_color, width=18, anchor='w').pack(side=tk.LEFT)
        self.path_search_entry = tk.Entry(search_row2)
        self.path_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        return frame

    def _create_statistics_tab(self, parent):
        """Create statistics tab"""
        frame = tk.Frame(parent, bg=self.theme_provider.bg_color)

        container = tk.Frame(frame, bg=self.theme_provider.bg_color, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            container,
            text="Collection Statistics",
            font=self.theme_provider.header_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        label.pack(anchor='w', pady=(0, 10))

        desc_label = tk.Label(
            container,
            text="View detailed statistics about your video collection including size, duration, resolution, and playback data.",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666",
            wraplength=700,
            justify=tk.LEFT
        )
        desc_label.pack(anchor='w', pady=(0, 20))

        self.stats_text = tk.Text(
            container,
            height=18,
            wrap=tk.WORD,
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground=self.theme_provider.frame_border,
            state=tk.DISABLED
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        refresh_btn = self.theme_provider.create_button(
            container,
            "Refresh Statistics",
            self._refresh_statistics,
            "primary",
            "md"
        )
        refresh_btn.pack()

        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.insert(tk.END, "📊 Collection Statistics\n\n")
        self.stats_text.insert(tk.END,
                               "Click 'Refresh Statistics' to calculate statistics for your current video selection.\n\n")
        self.stats_text.insert(tk.END, "Statistics include:\n")
        self.stats_text.insert(tk.END, "• Total videos, size, and duration\n")
        self.stats_text.insert(tk.END, "• Average file size and duration\n")
        self.stats_text.insert(tk.END, "• Playback statistics\n")
        self.stats_text.insert(tk.END, "• Resolution distribution\n")
        self.stats_text.insert(tk.END, "• Codec information\n")
        self.stats_text.config(state=tk.DISABLED)

        return frame

    def _create_action_buttons(self, parent):
        """This method is no longer used - buttons moved to header"""
        pass

    def _reset_filters(self):
        """Reset all filters to default"""
        self.quick_filter_var.set('all')
        self.sort_var.set('name_asc')

        self.min_size_entry.delete(0, tk.END)
        self.max_size_entry.delete(0, tk.END)
        self.min_duration_entry.delete(0, tk.END)
        self.max_duration_entry.delete(0, tk.END)
        self.modified_days_entry.delete(0, tk.END)
        self.filename_search_entry.delete(0, tk.END)
        self.path_search_entry.delete(0, tk.END)

        for var in self.resolution_vars.values():
            var.set(False)

    def _apply_filters(self):
        """Apply selected filters and sort"""
        # Apply quick filter
        quick_filter_key = self.quick_filter_var.get()
        self.manager.apply_quick_filter(quick_filter_key)

        # If not using 'all' quick filter, apply advanced filters on top
        if quick_filter_key == 'all':
            # Apply advanced filters
            filter_criteria = self.manager.current_filter

            # Size filters
            try:
                min_size = self.min_size_entry.get().strip()
                if min_size:
                    filter_criteria.min_size_mb = float(min_size)
            except ValueError:
                pass

            try:
                max_size = self.max_size_entry.get().strip()
                if max_size:
                    filter_criteria.max_size_mb = float(max_size)
            except ValueError:
                pass

            # Duration filters
            try:
                min_dur = self.min_duration_entry.get().strip()
                if min_dur:
                    filter_criteria.min_duration_seconds = float(min_dur)
            except ValueError:
                pass

            try:
                max_dur = self.max_duration_entry.get().strip()
                if max_dur:
                    filter_criteria.max_duration_seconds = float(max_dur)
            except ValueError:
                pass

            # Resolution filter
            selected_resolutions = [res for res, var in self.resolution_vars.items() if var.get()]
            filter_criteria.resolution_categories = selected_resolutions

            # Date filter
            try:
                mod_days = self.modified_days_entry.get().strip()
                if mod_days:
                    filter_criteria.modified_within_days = int(mod_days)
            except ValueError:
                pass

            # Text search
            filter_criteria.filename_contains = self.filename_search_entry.get().strip()
            filter_criteria.path_contains = self.path_search_entry.get().strip()

        # Apply sort
        sort_key = self.sort_var.get()
        self.manager.set_sort(sort_key)

        # Close dialog and apply
        self.filter_window.destroy()

        if self.on_apply_callback:
            self.on_apply_callback()

    def _refresh_statistics(self):
        """Refresh collection statistics"""
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, "Calculating statistics...\n\n")
        self.stats_text.config(state=tk.DISABLED)

        if hasattr(self, 'refresh_stats_btn'):
            self.refresh_stats_btn = None

        def calculate_stats():
            try:
                if hasattr(self.parent, 'master') and hasattr(self.parent.master, 'get_all_videos_for_statistics'):
                    video_paths = self.parent.master.get_all_videos_for_statistics()
                else:
                    video_paths = self._get_videos_from_app()

                if not video_paths:
                    def show_no_videos():
                        self.stats_text.config(state=tk.NORMAL)
                        self.stats_text.delete(1.0, tk.END)
                        self.stats_text.insert(tk.END, "No videos found.\n\n")
                        self.stats_text.insert(tk.END, "Please select a directory with videos first.")
                        self.stats_text.config(state=tk.DISABLED)

                    self.parent.after(0, show_no_videos)
                    return

                stats = self.manager.get_video_statistics(video_paths)

                def display_stats():
                    self.stats_text.config(state=tk.NORMAL)
                    self.stats_text.delete(1.0, tk.END)

                    self.stats_text.insert(tk.END, "📊 COLLECTION OVERVIEW\n", "header")
                    self.stats_text.insert(tk.END, "=" * 50 + "\n\n")

                    self.stats_text.insert(tk.END, f"Total Videos: {stats['total_videos']}\n", "bold")
                    self.stats_text.insert(tk.END, f"Total Size: {stats['total_size_gb']:.2f} GB\n", "bold")
                    self.stats_text.insert(tk.END, f"Total Duration: {stats['total_duration_hours']:.2f} hours\n",
                                           "bold")
                    self.stats_text.insert(tk.END, "\n")

                    self.stats_text.insert(tk.END, "📈 AVERAGES\n", "header")
                    self.stats_text.insert(tk.END, "-" * 50 + "\n")
                    self.stats_text.insert(tk.END, f"Average File Size: {stats['avg_size_mb']:.2f} MB\n")
                    self.stats_text.insert(tk.END, f"Average Duration: {stats['avg_duration_minutes']:.2f} minutes\n")
                    self.stats_text.insert(tk.END, "\n")

                    self.stats_text.insert(tk.END, "🎬 PLAYBACK STATISTICS\n", "header")
                    self.stats_text.insert(tk.END, "-" * 50 + "\n")
                    self.stats_text.insert(tk.END, f"Played Videos: {stats['played_count']}\n")
                    self.stats_text.insert(tk.END, f"Never Played: {stats['never_played_count']}\n")
                    played_percent = (stats['played_count'] / stats['total_videos'] * 100) if stats[
                                                                                                  'total_videos'] > 0 else 0
                    self.stats_text.insert(tk.END, f"Played Percentage: {played_percent:.1f}%\n")
                    self.stats_text.insert(tk.END, "\n")

                    self.stats_text.insert(tk.END, "📺 RESOLUTION DISTRIBUTION\n", "header")
                    self.stats_text.insert(tk.END, "-" * 50 + "\n")
                    res_dist = stats['resolution_distribution']
                    if res_dist:
                        for res, count in sorted(res_dist.items(), key=lambda x: x[1], reverse=True):
                            percentage = (count / stats['total_videos'] * 100) if stats['total_videos'] > 0 else 0
                            self.stats_text.insert(tk.END, f"{res}: {count} videos ({percentage:.1f}%)\n")
                    else:
                        self.stats_text.insert(tk.END, "No resolution data available\n")
                    self.stats_text.insert(tk.END, "\n")

                    self.stats_text.insert(tk.END, "🎞️ CODEC DISTRIBUTION\n", "header")
                    self.stats_text.insert(tk.END, "-" * 50 + "\n")
                    codec_dist = stats['codec_distribution']
                    if codec_dist:
                        for codec, count in sorted(codec_dist.items(), key=lambda x: x[1], reverse=True)[:5]:
                            if codec and codec != "unknown":
                                percentage = (count / stats['total_videos'] * 100) if stats['total_videos'] > 0 else 0
                                self.stats_text.insert(tk.END, f"{codec}: {count} videos ({percentage:.1f}%)\n")
                    else:
                        self.stats_text.insert(tk.END, "No codec data available\n")

                    self.stats_text.tag_configure("header", font=("Segoe UI", 11, "bold"), foreground="#2d89ef")
                    self.stats_text.tag_configure("bold", font=("Segoe UI", 10, "bold"))

                    self.stats_text.config(state=tk.DISABLED)

                self.parent.after(0, display_stats)

            except Exception as e:
                def show_error():
                    self.stats_text.config(state=tk.NORMAL)
                    self.stats_text.delete(1.0, tk.END)
                    self.stats_text.insert(tk.END, f"Error calculating statistics:\n\n{str(e)}\n\n")
                    self.stats_text.insert(tk.END, "Please make sure you have selected a directory with videos.")
                    self.stats_text.config(state=tk.DISABLED)

                self.parent.after(0, show_error)

        threading.Thread(target=calculate_stats, daemon=True).start()

    def _get_videos_from_app(self):
        try:
            if hasattr(self, 'app_instance'):
                return self.app_instance.get_all_videos_for_statistics()

            if hasattr(self.theme_provider, 'get_all_videos_for_statistics'):
                return self.theme_provider.get_all_videos_for_statistics()

            root = self.parent
            attempts = 0
            while root and attempts < 10:
                if hasattr(root, 'get_all_videos_for_statistics'):
                    return root.get_all_videos_for_statistics()
                if hasattr(root, 'master'):
                    root = root.master
                else:
                    break
                attempts += 1

        except Exception as e:
            print(f"Error getting videos from app: {e}")

        return []