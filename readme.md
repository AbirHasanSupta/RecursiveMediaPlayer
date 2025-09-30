# Recursive Video Player

A sophisticated video player application with AI-powered semantic search capabilities, designed for managing and playing large video collections across multiple directories.

## Features

### Core Functionality
- **Recursive Directory Scanning**: Automatically discovers videos in directory trees
- **Multi-Monitor Support**: Switch between monitors during playback
- **Advanced Exclusion System**: Exclude specific subdirectories and videos from playback
- **Resume Playback**: Continue from where you last left off
- **Theme Support**: Light and dark mode themes
- **Playlist Management**: Create and manage video playlists
- **Watch History Tracking**: Tracks watched videos and playback positions
- **Video Preview Generation**: Preview videos before playback
- **Settings Management**: Save and load user/app preferences

### AI-Powered Search
- **Semantic Video Search**: Find videos using natural language descriptions
- **Multi-Modal Analysis**: Combines visual (CLIP), textual (BLIP captions), and TF-IDF search
- **Intelligent Frame Sampling**: Adaptive sampling based on video length and content
- **Query Expansion**: Automatic synonym and semantic expansion for better results
- **Resource-Efficient Preprocessing**: Smart batching and memory management for large collections

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
- win32clipboard
- win32con
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
5. Run the application: `python exe_app.py`

## Usage

### Basic Video Playback

1. **Launch the application**:
   ```cmd
   python exe_app.py
   ```
2. **Add directories**: Click "Add Directory" to select folders containing videos
3. **Configure exclusions** (optional): Select directories/videos to exclude from playback
4. **Start playback**: Click "Play Videos" to begin

### Keyboard Controls During Playback

| Key         | Action                  |
|-------------|-------------------------|
| `Space`     | Pause/Resume            |
| `D`         | Next video              |
| `A`         | Previous video          |
| `E`         | Next directory          |
| `Q`         | Previous directory      |
| `W`         | Volume up               |
| `S`         | Volume down             |
| `Right Arrow` | Fast forward (200ms)  |
| `Left Arrow`  | Rewind (200ms)        |
| `F`         | Toggle fullscreen       |
| `1`         | Switch to monitor 1     |
| `2`         | Switch to monitor 2     |
| `+/=`       | Increase playback speed |
| `-`         | Decrease playback speed |
| `0`         | Reset speed to 1.0x     |
| `T`         | Take screenshot         |
| `Ctrl+C`    | Copy current video path |
| `Esc`       | Stop playback           |

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
The application saves preferences automatically:
- Selected directories
- Exclusion lists  
- Theme preference
- Playback position (if resume enabled)
- UI layout preferences

### Configuration Files
- Config: `~/Documents/Recursive Media Player/config.json`
- Screenshots: `~/Documents/Recursive Media Player/Screenshots/`
- AI Indices: `~/Documents/Recursive Media Player/index_data/` (default)

## File Structure

```
Recursive Video Player/
├── exe_app.py                # Main GUI application
├── enhanced_model.py         # AI search system
├── vlc_player_controller.py  # Video playback controller
├── key_press.py              # Keyboard input handling
├── theme.py                  # Theme and configuration management  
├── utils.py                  # Utility functions
├── managers/                 # Playlist, history, resume, settings, preview managers
│   ├── playlist_manager.py
│   ├── resume_playback_manager.py
│   ├── settings_manager.py
│   ├── video_preview_manager.py
│   └── watch_history_manager.py
├── requirements/
│   ├── requirements.txt      # Core dependencies
│   └── ai_requirements.txt   # AI/ML dependencies
├── build/                    # Build artifacts and executable
│   └── video_player/
│       └── RecursiveVideoPlayer.exe
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

**Hotkeys not working**: Ensure application window has focus

