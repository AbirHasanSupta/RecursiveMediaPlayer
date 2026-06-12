# Recursive Video Player

A feature-rich video player with AI-powered semantic search, built for managing and playing large video collections across multiple directories.

---

## Features

### Core
- **Home Dashboard** — watch stats, recently played, top directories
- **Recursive Directory Scanning** — auto-discovers all videos in nested folders
- **Embedded Player** — full-featured playback with rotation, zoom, subtitle tracks, chapter navigation, and A-B loop
- **Resume Playback** — picks up exactly where you left off
- **Dual Player Mode** — play two videos side-by-side for comparison
- **Playlist Management** — create, reorder, and manage multiple playlists
- **Video Queue** — manual fine-grained playback ordering
- **Favorites & Annotations** — bookmark videos; add tags, ratings, and notes
- **Advanced Grid View** — visual browser with pagination, filtering, and thumbnail hover previews
- **Filter & Sort** — by resolution, size, date, duration, and more
- **Watch History & Stats** — detailed per-video tracking with charts
- **Google Drive Support** — stream or download from public Drive folders/links
- **Multi-Monitor Support** — switch output display during playback
- **Advanced Exclusion System** — exclude specific subdirectories or individual files
- **Theme Support** — light, dark, and custom themes (saved persistently)
- **Windows Shell Integration** — "Open with Recursive Video Player" in folder context menu

### AI-Powered Semantic Search
- **Natural Language Queries** — describe what you're looking for in plain English
- **Multi-Modal Engine** — combines CLIP (visual), BLIP (captions), and TF-IDF (keyword) scoring
- **Adaptive Frame Sampling** — intelligent sampling tuned to video length
- **Query Expansion** — automatic synonym and semantic expansion for better recall
- **In-App Indexing** — build and monitor the index via the **⚙ Index** button, no terminal needed
- **Stale Index Detection** — warns when new/removed videos are found; one click to update
- **Live Device Badge** — shows active compute device (GPU / CPU) in the status bar
- **Result Persistence** — query and results survive tab switches
- **Thumbnail Previews** — hover any result to preview the video frame
- **Rich Context Menu** — right-click to play, locate, add to playlist/queue/favourites, or view properties

---

## Installation

**Prerequisites:** Python 3.8+, VLC Media Player

```cmd
pip install -r requirements\requirements.txt
```

For AI search (server machine only):
```cmd
pip install -r requirements\ai_requirements.txt
```

Launch the app:
```cmd
python main.py
```

---

## AI Search Setup

The AI engine runs as a **separate HTTP server** (`src/core/ai_service.py`). It can run on the same machine or a remote GPU workstation.

```
┌──────────────────────────────┐            HTTP             ┌─────────────────────────────────┐
│   Recursive Video Player     │ ◄─────────────────────────► │   src/core/ai_service.py (srv)  │
│          main.py             │    e.g. localhost:8000       │   FastAPI · CLIP · BLIP · FAISS │
└──────────────────────────────┘                             └─────────────────────────────────┘
        UI / Playback                                           AI Indexing & Semantic Search
```

### 1 — Start the AI Server

```cmd
python src/core/ai_service.py --mode server
```

Default: `http://0.0.0.0:8000`. Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Bind address (`127.0.0.1` for local-only) |
| `--port` | `8000` | Listening port |
| `--out_dir` | `%LOCALAPPDATA%\Recursive Video Player\index_data` | Index directory to load on startup |

The server starts even without an index — you can build one from inside the app.

### 2 — Connect the App

**Settings → AI & Preprocessing** → tick **Enable AI Search** → paste the server URL (e.g. `http://localhost:8000`) → **Save Settings**.

### 3 — Build the Index

```
  Video Files
      │
      ▼
  Frame Sampling  ──►  CLIP (visual embedding)
                  ──►  BLIP (caption generation)  ──►  Sentence Embedding
                  ──►  Semantic Feature Extraction
      │
      ▼
  FAISS Index  +  TF-IDF Index  +  metadata.pkl
      │
      ▼
  AI Server loads index  ──►  Ready to search
```

**Recommended:** Click **⚙ Index** in the AI Search tab, select your video directory, and hit **Start**. Progress is shown live; the search engine loads automatically when done.

**Or via command line:**
```cmd
python src/core/ai_service.py --mode preprocess --videos_dir "C:/Videos"
python src/core/ai_service.py --mode preprocess --videos_dir "C:/Videos" --workers 2 --max_frames 60 --incremental
```

| Flag | Default | Description |
|---|---|---|
| `--videos_dir` | *(dialog)* | Root video folder |
| `--out_dir` | `%LOCALAPPDATA%\...\index_data` | Index output directory |
| `--workers` | `3` | Parallel workers (1–3 recommended) |
| `--max_frames` | `60` | Max frames sampled per video |
| `--incremental` | on | Only process new videos |
| `--force_rebuild` | — | Rebuild index from scratch |
| `--exclude_dirs` | `raw` | Comma-separated folder names to skip |

---

## AI & Preprocessing Settings

**Settings → AI & Preprocessing**

| Setting | Default | Description |
|---|---|---|
| Enable AI Search | Off | Shows the AI Search tab and activates the server connection |
| AI Server URL | *(empty)* | URL of the running `ai_service.py` server |
| AI Index Path | `%LOCALAPPDATA%\...\index_data` | Where index files are stored |
| Workers | `3` | Preprocessing parallelism |
| Max Frames per Video | `60` | Per-video frame sample cap (20–200) |
| Incremental Mode | On | Skip already-indexed videos |
| Excluded Directory Names | `raw` | Folder names to skip during indexing |

---

## Playback Hotkeys *(fully rebindable in Settings → Keyboard Shortcuts)*

| Action | Default |
|---|---|
| Pause / Resume | `Space` |
| Next / Prev video | `D` / `A` |
| Next / Prev directory | `E` / `Q` |
| Fast-forward / Rewind | `→` / `←` |
| Volume up / down | `W` / `S` |
| Speed up / down | `=` / `-` |
| Fullscreen | `F` |
| Rotate / Flip | `R` / `H` |
| Zoom in / out / reset | `Ctrl+=` / `Ctrl+-` / `Ctrl+0` |
| A-B Loop set / clear | `[` `]` / `\` |
| Screenshot | `T` |
| Gaming Mode (hover focus) | `G` |

---

## Build & Distribution

```cmd
python build.py
```

Produces `dist/RecursiveVideoPlayer/RecursiveVideoPlayer.exe` and a ZIP package.
The standalone build excludes AI models to keep the file size small; `ai_service.py` is bundled inside `_internal/` and can be run separately.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| AI Search tab missing | Enable AI Search in Settings and save |
| "No AI server URL configured" | Add the server URL in Settings → AI & Preprocessing |
| "Could not reach AI server" | Verify the server is running; check the URL, port, and firewall |
| "No index found" | Click **⚙ Index** to build one |
| Index stale after adding videos | Click **⚙ Index** → run with Incremental mode |
| Memory errors during preprocessing | Lower Workers or Max Frames in Settings |
| Hotkeys not working | Ensure the window has focus, or enable Gaming Mode (`G`) |
| VLC not found | Install VLC and ensure it is in the system PATH |