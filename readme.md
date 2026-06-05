# Recursive Video Player

A sophisticated video player application with AI-powered semantic search capabilities, designed for managing and playing large video collections across multiple directories.

## Features

### Core Functionality
- **Home Dashboard**: Central hub with watch statistics, recently played videos, and top directories
- **Recursive Directory Scanning**: Automatically discovers videos in directory trees
- **Multi-Monitor Support**: Switch between monitors during playback
- **Advanced Exclusion System**: Exclude specific subdirectories and videos from playback
- **Resume Playback**: Continue from where you last left off with smart resume capabilities
- **Theme Support**: Light, dark, and custom themes (persistently saved)
- **Playlist Management**: Create, edit, and manage multiple video playlists
- **Watch History & Statistics**: Detailed tracking of watched videos with visual charts and metrics
- **Video Preview Generation**: Hover-based video previews and visual thumbnails
- **Advanced Grid View**: Visual explorer for browsing video collections with pagination and filtering
- **Advanced Filter & Sort**: Filter by resolution, size, or date, and sort by various criteria
- **Google Drive Support**: Stream and download videos directly from public Google Drive folders or links
- **Dual Player Mode**: Play and compare two videos side-by-side
- **Embedded Player**: Integrated, high-performance video playback with rich controls, rotation, zoom, and subtitle support
- **Favorites System**: Bookmark and organize your favorite videos for quick access
- **Video Queue**: Manual queue management for fine-tuned playback order
- **Annotation & Metadata**: Add tags, ratings, and bookmarks to your video collection
- **Settings Management**: Persistent save/load for all user and application preferences
- **Windows Shell Integration**: Register the player in the Windows folder context menu for quick access

### AI-Powered Search
- **Semantic Video Search**: Find videos using natural language descriptions
- **Multi-Modal Analysis**: Combines visual (CLIP), textual (BLIP captions), and TF-IDF search
- **Intelligent Frame Sampling**: Adaptive sampling based on video length and content
- **Query Expansion**: Automatic synonym and semantic expansion for better results
- **Resource-Efficient Preprocessing**: Smart batching and memory management for large collections
- **In-App Indexing Dialog**: Launch and monitor preprocessing directly from the UI via the **⚙ Index** button — no command line required
- **Stale Index Detection**: Automatically detects new or removed videos since last index build and prompts for an update
- **Device Badge**: Live GPU/CPU/MPS indicator showing which compute device the AI engine is using
- **Result Persistence**: Search results and query are preserved when switching to other tabs and restored on return
- **Thumbnail Previews**: Hover over any search result to see a video thumbnail preview
- **Rich Context Menu**: Right-click any result to play, open in Gallery, add to playlist, add to queue, add/remove from favourites, open file location, view properties, or show in the directory panel
- **Directory Name Exclusion**: Skip subdirectories matching comma-separated name patterns (e.g. `raw, temp`) during indexing — configurable in **Settings > AI & Preprocessing**

### Playback Controls
- **Keyboard Shortcuts**: Comprehensive hotkey support for all functions
- **Variable Speed Playback**: 0.25x to 2.0x speed control with visual slider
- **Screenshot Capture**: Save screenshots with automatic naming
- **File Management**: Copy current video path to clipboard

## Installation

### Prerequisites
- Python 3.8 or higher
- VLC Media Player installed on your system

### Required Dependencies
```cmd
pip install -r requirements\requirements.txt
pip install -r requirements\ai_requirements.txt
```

#### Core Dependencies
- vlc-python
- screeninfo
- tkinter (usually included with Python)
- pywin32 (for win32clipboard, win32con)
- keyboard
- opencv-python
- numpy

#### AI Search Dependencies (Optional)
- torch
- transformers
- scikit-learn
- nltk
- faiss-cpu  # or faiss-gpu for GPU acceleration
- deepface
- Pillow

### Installation Steps
1. Clone or download the project files
2. Install Python dependencies: `pip install -r requirements\requirements.txt`
3. (Optional) For AI search: `pip install -r requirements\ai_requirements.txt`
4. Ensure VLC Media Player is installed and accessible
5. Run the application:
   ```cmd
   python build_app.py
   ```

### Windows Shell Integration (Optional)

You can add "Open with Recursive Video Player" to your Windows folder context menu:

1. Build the application first (see [Building the Executable](#building-the-executable))
2. Run the registration script as Administrator:
   ```cmd
   python register_context_menu.py
   ```
To remove it:
   ```cmd
   python register_context_menu.py unregister
   ```

## Usage

### Basic Video Playback

1. **Launch the application**:
   ```cmd
   python build_app.py
   ```
2. **Add directories**: Click "Add Directory" to select folders containing videos
3. **Configure exclusions** (optional): Select directories/videos to exclude from playback
4. **Start playback**: Click "Play Videos" to begin

### Keyboard Controls During Playback

The application features comprehensive hotkey support. All shortcuts can be customized in the **Settings > Shortcuts** tab.

## AI Search System

### Prerequisites for AI Search
The AI search functionality requires preprocessed video indices. Build the index before using AI search — either via the in-app dialog (recommended) or the command line.

### Building the Index

#### Option 1 — In-App (Recommended)
1. Navigate to the **AI Search** tab from the top navigation bar
2. Click the **⚙ Index** button next to the search bar
3. Select the video directory to index in the dialog that opens
4. Adjust worker count, max frames, and incremental mode if needed, then click **Start**
5. Progress is shown live; close the dialog when complete — the search engine loads automatically

Preprocessing settings (index path, workers, max frames, incremental mode, excluded directory names) can also be configured in advance under **Settings > AI & Preprocessing**.

#### Option 2 — Command Line
```cmd
python enhanced_model.py --mode preprocess
python enhanced_model.py --mode preprocess --videos_dir "C:/Videos" --out_dir "./index_data"
python enhanced_model.py --mode preprocess --videos_dir "C:/Videos" --out_dir "./index_data" --workers 3 --max_frames 60 --incremental
```

#### Preprocessing Parameters
- `--videos_dir`: Path to video directory (optional — GUI dialog shown if omitted)
- `--out_dir`: Output directory for index files (default: `%LOCALAPPDATA%\Recursive Media Player\index_data`)
- `--workers`: Number of parallel workers (default: 3, recommended 1–3 for stability)
- `--max_frames`: Maximum frames to analyze per video (default: 60)
- `--incremental`: Add to existing index rather than rebuilding (default: enabled)
- `--force_rebuild`: Force complete rebuild of indices
- `--exclude_dirs`: Comma-separated directory name patterns to skip (e.g. `raw,temp`)

#### Preprocessing Output
- `clip_index.faiss` — Visual similarity index
- `text_index.faiss` — Text/caption similarity index
- `metadata.pkl` — Video metadata and captions
- `tfidf_index.pkl` — Text search index

### Using AI Search

#### In the GUI Application
1. Navigate to the **AI Search** tab from the top navigation bar
2. The status bar shows index state: video count, index age, compute device (GPU/CPU/MPS), and any staleness warnings
3. If the index is stale (new or removed videos detected), a warning is shown — click **⚙ Index** to update
4. Enter a natural language query in the search box and press Enter or click **Search**
5. Results display with relevance scores and thumbnail previews on hover
6. Right-click any result for context menu actions, or double-click to play
7. Results and the current query are preserved if you switch to another tab and return

#### Command Line Search
```cmd
python enhanced_model.py --mode search --query "man in red shirt walking"
python enhanced_model.py --mode search --query "man in red shirt walking" --top_k 10 --clip_weight 0.4 --text_weight 0.4 --tfidf_weight 0.2
python enhanced_model.py --mode search --query "walking" --keep_alive
```

#### Search Parameters
- `--query`: Search text (natural language description)
- `--top_k`: Number of results to return (default: 20)
- `--clip_weight`: Visual similarity weight (default: 0.35)
- `--text_weight`: Caption similarity weight (default: 0.35)
- `--tfidf_weight`: Keyword matching weight (default: 0.3)
- `--keep_alive`: Interactive mode for multiple searches

### Example Search Queries

The AI search understands natural language descriptions:
```cmd
python enhanced_model.py --mode search --query "man wearing blue shirt"
python enhanced_model.py --mode search --query "person in black clothing"
python enhanced_model.py --mode search --query "dancing performance"
python enhanced_model.py --mode search --query "someone exercising or working out"
python enhanced_model.py --mode search --query "outdoor nature setting"
python enhanced_model.py --mode search --query "bright colorful scene"
python enhanced_model.py --mode search --query "red and pink colors"
python enhanced_model.py --mode search --query "woman in white dress dancing indoors"
```

## Configuration

### Settings
The application saves preferences automatically:
- Selected directories
- Exclusion lists
- Theme preference
- Hotkey customizations (rebindable in the **Shortcuts** tab)
- Playback position (if resume enabled)
- UI layout preferences

### AI & Preprocessing Settings
Accessible via **Settings > AI & Preprocessing**:
- **AI Index Path**: Directory where index files are stored (default: `%LOCALAPPDATA%\Recursive Media Player\index_data`)
- **Workers**: Number of parallel preprocessing workers (default: 3)
- **Max Frames per Video**: Frame sample limit per video (default: 60, range: 20–200)
- **Incremental Mode**: When enabled, only new videos are added to the existing index rather than rebuilding from scratch (default: on)
- **Excluded Directory Names**: Comma-separated subfolder name patterns to skip during indexing (default: `raw`)

## Build and Distribution

The project includes a build system to create a standalone Windows executable.

### Building the Executable

1. Ensure `pyinstaller` is installed: `pip install pyinstaller`
2. Run the build script:
   ```cmd
   python build.py
   ```
This script will:
- Write version information to `version.py`.
- Clean previous build artifacts (`build`, `dist`, `__pycache__`).
- Install/Update `pyinstaller`.
- Build the standalone executable using `video_player.spec`.
- Create a distribution ZIP package: `RecursiveVideoPlayer-vX.X.X.zip`.

The output executable will be located at `dist/RecursiveVideoPlayer/RecursiveVideoPlayer.exe`.

*Note: The standalone build intentionally excludes AI features to maintain a smaller file size and reduce system requirements.*

## Performance Notes

### AI Search Performance
- **Preprocessing**: Can take significant time for large collections (hours for thousands of videos)
- **Memory Usage**: Requires 4-8GB RAM during preprocessing
- **GPU Acceleration**: Supports CUDA for faster processing; device in use is shown in the AI Search status bar
- **Incremental Updates**: Add new videos without full reprocessing

### System Requirements
- **Minimum**: 4GB RAM, dual-core CPU
- **Recommended**: 8GB+ RAM, dedicated GPU for AI features
- **Storage**: ~100MB index data per 1000 videos

## Troubleshooting

### Common Issues

**VLC not found**: Ensure VLC Media Player is installed and in system PATH

**AI search not working**: Verify all AI dependencies are installed and the index has been built (status bar in the AI Search tab will indicate if no index is found)

**AI Search tab shows "No index found"**: Click **⚙ Index** to build the index, or run `python enhanced_model.py --mode preprocess` from the command line

**Index appears stale after adding new videos**: The status bar will show a warning — click **⚙ Index** and run with incremental mode to update without a full rebuild

**Memory errors during preprocessing**: Reduce the Workers setting or Max Frames per Video in **Settings > AI & Preprocessing**, or use the `--workers` and `--max_frames` CLI flags

**Certain subdirectories are being indexed unintentionally**: Add the folder name to the Excluded Directory Names field in **Settings > AI & Preprocessing** (e.g. `raw, backup, temp`)

**Search engine not loading after indexing**: The bridge process starts automatically when the AI Search tab is opened; check that `enhanced_model.py` is present in the project root or that `ai_search.exe` exists alongside the executable

**Hotkeys not working**: Ensure the application window has focus