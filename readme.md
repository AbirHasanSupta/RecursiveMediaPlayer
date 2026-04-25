# Recursive Video Player

A sophisticated video player application with AI-powered semantic search capabilities, designed for managing and playing large video collections across multiple directories.

## Features

### Core Functionality
- **Recursive Directory Scanning**: Automatically discovers videos in directory trees
- **Multi-Monitor Support**: Switch between monitors during playback
- **Advanced Exclusion System**: Exclude specific subdirectories and videos from playback
- **Resume Playback**: Continue from where you last left off with smart resume capabilities
- **Theme Support**: Light, dark, and custom themes
- **Playlist Management**: Create, edit, and manage multiple video playlists
- **Watch History Tracking**: Detailed tracking of watched videos and playback positions
- **Video Preview Generation**: Hover-based video previews and visual thumbnails
- **Advanced Grid View**: Visual explorer for browsing video collections
- **Advanced Filter & Sort**: Filter by resolution, size, or date, and sort by various criteria
- **Google Drive Support**: Stream and download videos directly from public Google Drive folders or links
- **Voice Commands**: Control playback and navigation using natural voice commands
- **Dual Player Mode**: Play and compare two videos side-by-side
- **Favorites System**: Bookmark and organize your favorite videos for quick access
- **Video Queue**: Manual queue management for fine-tuned playback order
- **Settings Management**: Persistent save/load for all user and application preferences
- **Customizable Keyboard Shortcuts**: Reassign any hotkey from the Settings → Keyboard Shortcuts tab; changes apply instantly without restarting

### AI-Powered Search
- **Semantic Video Search**: Find videos using natural language descriptions
- **Multi-Modal Analysis**: Combines visual (CLIP), textual (BLIP captions), and TF-IDF search
- **Intelligent Frame Sampling**: Adaptive sampling based on video length and content
- **Query Expansion**: Automatic synonym and semantic expansion for better results
- **Resource-Efficient Preprocessing**: Smart batching and memory management for large collections

### Playback Controls
- **Keyboard Shortcuts**: Comprehensive, fully remappable hotkey support for all playback functions
- **Variable Speed Playback**: 0.25x to 2.0x speed control with visual slider
- **Screenshot Capture**: Save screenshots with automatic naming
- **File Management**: Copy current video path to clipboard
- **Chapter Navigation**: Jump between video chapters
- **Subtitle Control**: Cycle through subtitle tracks or disable them entirely

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
- SpeechRecognition (for voice commands)
- PyAudio (for voice commands)

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
5. Run the application: `python app.py`

## Usage

### Basic Video Playback

1. **Launch the application**:
   ```cmd
   python app.py
   ```
2. **Add directories**: Click "Add Directory" to select folders containing videos
3. **Configure exclusions** (optional): Select directories/videos to exclude from playback
4. **Start playback**: Click "Play Videos" to begin

### Keyboard Controls During Playback

All shortcuts listed below are the **defaults**. Every binding can be changed in **Settings → Keyboard Shortcuts** — click any key badge to reassign it. If you assign a key that is already in use, the two actions automatically swap bindings.

#### ▶ Playback

| Key           | Action                          |
|---------------|---------------------------------|
| `Space`       | Pause / Resume                  |
| `Esc`         | Stop playback                   |
| `Right Arrow` | Fast-forward 200 ms             |
| `Left Arrow`  | Rewind 200 ms                   |

#### 📁 Navigation

| Key | Action             |
|-----|--------------------|
| `D` | Next video         |
| `A` | Previous video     |
| `E` | Next directory     |
| `Q` | Previous directory |

#### 🔊 Audio

| Key           | Action            |
|---------------|-------------------|
| `W`           | Volume up (+10)   |
| `S`           | Volume down (-10) |
| `M`           | Toggle mute       |
| `Mouse Wheel` | Volume up / down  |

#### ⚡ Speed

| Key | Action                    |
|-----|---------------------------|
| `=` | Increase speed (+0.25×)   |
| `-` | Decrease speed (−0.25×)   |
| `0` | Reset speed to 1.0×       |

#### 🖼 Display

| Key        | Action                                        |
|------------|-----------------------------------------------|
| `F`        | Toggle fullscreen                             |
| `1`        | Switch to monitor 1                           |
| `2`        | Switch to monitor 2                           |
| `I`        | Toggle info overlay                           |
| `R`        | Rotate video 90° clockwise (cycles 0→90→180→270) |
| `Ctrl+=`   | Zoom in (+10%)                                |
| `Ctrl+-`   | Zoom out (−10%)                               |
| `Ctrl+0`   | Reset zoom to 100%                            |

#### 📖 Chapters

| Key | Action          |
|-----|-----------------|
| `N` | Next chapter    |
| `B` | Previous chapter |

#### 💬 Subtitles

| Key      | Action                |
|----------|-----------------------|
| `U`      | Cycle subtitle track  |
| `Ctrl+U` | Disable subtitles     |

#### 🛠 Tools

| Key      | Action                     |
|----------|----------------------------|
| `T`      | Take screenshot            |
| `Ctrl+C` | Copy current video path    |
| `V`      | Toggle voice commands      |

### Customising Keyboard Shortcuts

1. Open **Settings** (gear icon or menu)
2. Go to the **Keyboard Shortcuts** tab
3. Click the key badge next to any action — a capture dialog appears
4. Press the new key or combo (`Ctrl`, `Shift` modifiers supported)
5. If the key is already assigned elsewhere, the two actions **swap automatically**
6. Press **Esc** to cancel without changing anything
7. Click **Save Settings** — new bindings take effect immediately in the player

Use **Reset Shortcuts to Defaults** at the bottom of the tab to restore all bindings at once.

## AI Search System

### Prerequisites for AI Search
The AI search functionality requires preprocessed video indices. You need to run the preprocessing step before using AI search features.

### Preprocessing Videos
Generate AI search indices for your video collection:
```cmd
python enhanced_model.py --mode preprocess
python enhanced_model.py --mode preprocess --videos_dir "C:/Videos" --out_dir "./index_data"
python enhanced_model.py --mode preprocess --videos_dir "C:/Videos" --out_dir "./index_data" --workers 3 --max_frames 60 --incremental
```

#### Preprocessing Parameters
- `--videos_dir`: Path to video directory (optional - GUI dialog if not provided)
- `--out_dir`: Output directory for index files (default: `C:/Users/[User]/Documents/Recursive Media Player/index_data`)
- `--workers`: Number of parallel workers (default: 3, recommended 1-3 for stability)
- `--max_frames`: Maximum frames to analyze per video (default: 60)
- `--incremental`: Add to existing index rather than rebuilding (default: enabled)
- `--force_rebuild`: Force complete rebuild of indices

#### Preprocessing Output
- `clip_index.faiss` - Visual similarity index
- `text_index.faiss` - Text/caption similarity index
- `metadata.pkl` - Video metadata and captions
- `tfidf_index.pkl` - Text search index

### Using AI Search

#### In the GUI Application
1. Click "AI Mode" button after preprocessing is complete
2. Select a directory from your added directories
3. Enter search queries in the AI search box
4. Results show matching videos with relevance scores
5. Click "Play Videos" to play the search results

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
The application saves all preferences automatically, including:
- Selected directories and exclusion lists
- Theme preference
- Playback position (if resume enabled)
- UI layout preferences
- **Custom keyboard shortcut bindings**
- Dual player mode toggle
- Watch history enabled/disabled
- Video preview duration and enabled state
- AI preprocessing preferences (workers, max frames, batch size, GPU acceleration, incremental mode)
- Auto watch-history cleanup period

### Configuration Files

The application uses specific locations for different types of data:

#### Application Settings
- **Main Settings**: `%APPDATA%\Recursive Media Player\app_settings.json` (Windows)
- **Linux/macOS**: `~/.config/Recursive Media Player/app_settings.json` or `~/Library/Application Support/...`

#### Session & History Data
- **Resume Positions**: `%LOCALAPPDATA%\Recursive Media Player\Resume\playback_positions.json`
- **Watch History**: `%LOCALAPPDATA%\Recursive Media Player\History\watch_history.json`
- **AI Search Indices**: `%LOCALAPPDATA%\Recursive Media Player\index_data\` (Default, configurable in Settings)
- **Screenshots**: `~/Documents/Recursive Media Player/Screenshots/`

#### User Content
- **Playlists**: `~/Documents/Recursive Media Player/Playlists/playlists.json`
- **Favorites**: `~/Documents/Recursive Media Player/Favorites/favorites.json`

## File Structure

```
Recursive Video Player/
├── app.py                    # Main GUI application entry point
├── build_app.py              # Extended application features and UI
├── enhanced_model.py         # AI search system and model logic
├── vlc_player_controller.py  # Video playback controller and VLC integration
├── key_press.py              # Global keyboard hotkey handling
├── theme.py                  # Theme and UI styling configuration
├── utils.py                  # Utility functions for file and video processing
├── managers/                 # Specialized management systems
│   ├── dual_player_manager.py     # Side-by-side video playback
│   ├── favorites_manager.py       # Favorites system and UI
│   ├── filter_sort_manager.py     # Advanced filtering/sorting logic
│   ├── google_drive_manager.py    # Google Drive integration
│   ├── grid_view_manager.py       # Visual video browser
│   ├── playlist_manager.py        # Playlist creation and management
│   ├── resume_playback_manager.py # Playback session recovery
│   ├── settings_manager.py        # Persistent application settings and hotkey config
│   ├── video_preview_manager.py   # Thumbnail and hover-preview logic
│   ├── video_queue_manager.py     # Manual video queue
│   ├── voice_command_manager.py   # Voice recognition and control
│   └── watch_history_manager.py   # Playback history tracking
├── requirements/
│   ├── requirements.txt      # Core dependencies
│   └── ai_requirements.txt   # AI/ML dependencies
└── README.md                 # This file
```

## Performance Notes

### AI Search Performance
- **Preprocessing**: Can take significant time for large collections (hours for thousands of videos)
- **Memory Usage**: Requires 4-8GB RAM during preprocessing
- **GPU Acceleration**: Supports CUDA for faster processing
- **Incremental Updates**: Add new videos without full reprocessing

### System Requirements
- **Minimum**: 4GB RAM, dual-core CPU
- **Recommended**: 8GB+ RAM, dedicated GPU for AI features
- **Storage**: ~100MB index data per 1000 videos

## Troubleshooting

### Common Issues

**VLC not found**: Ensure VLC Media Player is installed and in system PATH

**AI search not working**: Verify all AI dependencies are installed and preprocessing completed

**Memory errors during preprocessing**: Reduce `--workers` parameter or `--max_frames`

**Hotkeys not working**: Ensure the application window has focus. If a shortcut conflicts with another app, reassign it in Settings → Keyboard Shortcuts