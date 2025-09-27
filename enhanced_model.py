"""
High-Accuracy Video Semantic Search with Smart Resource Management
-----------------------------------------------------------------

Maintains accuracy while solving resource issues:
- Sequential model loading to prevent memory overflow
- Batch processing with memory management
- Multi-modal ensemble scoring (CLIP + BLIP + text similarity)
- Advanced semantic feature extraction
- Query expansion and synonym matching
- Temporal consistency scoring
- Smart frame sampling with multiple strategies
"""

import argparse
import os
import json
import pickle
import gc
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any, Tuple
import concurrent.futures
import re
import psutil

import numpy as np
import cv2

import torch
from transformers import (
    CLIPProcessor, CLIPModel,
    BlipProcessor, BlipForConditionalGeneration,
    AutoTokenizer, AutoModel
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.corpus import wordnet
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer

# Safe NLTK download with error handling
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('corpora/wordnet')
    nltk.data.find('taggers/averaged_perceptron_tagger')
except LookupError:
    try:
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)
        nltk.download('wordnet', quiet=True)
        nltk.download('averaged_perceptron_tagger', quiet=True)
        print("NLTK data downloaded successfully")
    except Exception as e:
        print(f"Warning: NLTK download failed: {e}")

try:
    from deepface import DeepFace

    _DEEPFACE_AVAILABLE = True
except Exception:
    _DEEPFACE_AVAILABLE = False

import faiss


def get_memory_info():
    """Get detailed memory information"""
    process = psutil.Process()
    mem = process.memory_info()
    vm = psutil.virtual_memory()
    gpu_mem = 0
    if torch.cuda.is_available():
        gpu_mem = torch.cuda.memory_allocated() / 1024 ** 3
    return {
        'ram_used_gb': mem.rss / 1024 ** 3,
        'ram_available_gb': vm.available / 1024 ** 3,
        'gpu_used_gb': gpu_mem
    }


def norm_l2(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


def adaptive_frame_sampling(video_path: str, base_interval: float = 1.0, max_frames: int = 60):
    """Intelligent frame sampling based on video characteristics"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    print(f"Video: {duration:.1f}s, {total_frames} frames, targeting {max_frames} samples")

    if duration <= 5:  # Very short video - dense sampling
        intervals = [0.25, 0.5]
    elif duration <= 15:  # Short video - sample more densely
        intervals = [0.5, 1.0]
    elif duration <= 45:  # Medium video
        intervals = [1.0, 2.0]
    elif duration <= 120:  # Long video
        intervals = [2.0, 4.0]
    else:  # Very long video - sample key moments
        intervals = [3.0, 6.0]

    # Collect sampling points
    sample_points = set()
    for interval in intervals:
        step_frames = max(1, int(interval * fps))
        for i in range(0, min(total_frames, max_frames * step_frames), step_frames):
            sample_points.add(i)

    # Ensure we don't exceed max_frames
    sample_points = sorted(list(sample_points))[:max_frames]

    for frame_idx in sample_points:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            timestamp = frame_idx / fps
            yield timestamp, frame

    cap.release()


def enhanced_caption_generation(frame_rgb, blip_model, blip_processor, device):
    """Generate detailed captions with multiple prompting strategies"""
    captions = []

    try:
        # Standard caption
        inputs = blip_processor(images=frame_rgb, return_tensors="pt").to(device)
        with torch.no_grad():
            caption_ids = blip_model.generate(**inputs, max_new_tokens=40, num_beams=3,
                                               do_sample=False)
            standard_caption = blip_processor.decode(caption_ids[0], skip_special_tokens=True)
            if standard_caption and len(standard_caption) > 5:
                captions.append(standard_caption)
    except Exception as e:
        print(f"Standard caption failed: {e}")

    # Question-based prompting for specific details
    questions = [
        "What is the person wearing?",
        "What colors are prominent in this image?",
        "What activity is happening?",
        "What objects are visible?",
        "What are the colors of the dress that the person wearing?"
    ]

    for question in questions:
        try:
            inputs = blip_processor(images=frame_rgb, text=question, return_tensors="pt").to(device)
            with torch.no_grad():
                answer_ids = blip_model.generate(**inputs, max_new_tokens=25, temperature=0.5)
                answer = blip_processor.decode(answer_ids[0], skip_special_tokens=True)
                # Clean up answer
                if answer and len(answer) > 3:
                    # Remove question from answer if present
                    clean_answer = answer.replace(question.lower(), "").strip()
                    if clean_answer and clean_answer.lower() not in ['yes', 'no', 'maybe', 'unknown']:
                        captions.append(f"{question.split('?')[0]}: {clean_answer}")
        except Exception:
            continue

    # Combine all captions
    if captions:
        return " | ".join(captions)
    else:
        return "video frame content"


def extract_advanced_semantic_features(caption: str, lemmatizer: WordNetLemmatizer = None) -> List[str]:
    """Extract comprehensive semantic features"""
    if not lemmatizer:
        try:
            lemmatizer = WordNetLemmatizer()
        except:
            lemmatizer = None

    try:
        # Preprocessing
        caption_clean = re.sub(r'[^\w\s]', ' ', caption.lower())

        # Tokenization with fallback
        try:
            words = word_tokenize(caption_clean)
        except:
            words = caption_clean.split()

        # Filter and lemmatize
        meaningful_words = []
        for word in words:
            if len(word) > 2:
                if lemmatizer:
                    try:
                        lemmatized = lemmatizer.lemmatize(word)
                        meaningful_words.append(lemmatized)
                    except:
                        meaningful_words.append(word)
                else:
                    meaningful_words.append(word)


        visual_terms = [
            # People
            'person', 'woman', 'man', 'girl', 'boy', 'female', 'male', 'dancer', 'performer',
            # Clothing & Fashion
            'clothing', 'outfit', 'dress', 'shirt', 'top', 'blouse', 'skirt', 'pants', 'jeans',
            'shorts', 'leggings', 'hoodie', 'jacket', 'sweater', 'tank', 'crop', 'mini', 'maxi',
            'bra', 'underwear', 'fishnet', 'panty', 'bikini', 'lingerie', 'swimwear', 'bodysuit',
            # Colors
            'color', 'red', 'blue', 'green', 'black', 'white', 'pink', 'purple', 'yellow',
            'orange', 'brown', 'gray', 'grey', 'silver', 'gold', 'navy', 'maroon',
            # Actions & Movement
            'dancing', 'dance', 'moving', 'posing', 'standing', 'sitting', 'walking', 'jumping',
            'spinning', 'twirling', 'gesture', 'motion', 'performance',
            # Room & Environment
            'room', 'bedroom', 'living', 'background', 'wall', 'floor', 'mirror', 'window',
            'lighting', 'indoor', 'home', 'studio', 'space',
            # Style & Appearance
            'style', 'fashion', 'trendy', 'casual', 'formal', 'cute', 'pretty', 'elegant',
            'sporty', 'vintage', 'modern', 'chic'
        ]
        expanded_terms = set(meaningful_words)

        for word in meaningful_words[:15]:  # Limit expansion to prevent explosion
            if word in visual_terms or len(word) > 4:
                try:
                    synsets = wordnet.synsets(word)
                    for syn in synsets[:2]:
                        for lemma in syn.lemmas()[:2]:
                            synonym = lemma.name().replace('_', ' ')
                            if len(synonym) > 2:
                                expanded_terms.add(synonym)
                except:
                    continue

        return list(expanded_terms)

    except Exception as e:
        # Ultimate fallback
        return re.sub(r'[^\w\s]', ' ', caption.lower()).split()


# Worker state - simplified but comprehensive
_worker_state = {
    'device': None,
    'clip_model': None,
    'clip_processor': None,
    'blip_model': None,
    'blip_processor': None,
    'sentence_model': None,
    'sentence_tokenizer': None,
    'lemmatizer': None,
    'worker_id': None
}


def _init_high_accuracy_worker(worker_id: int = 0, device: str = None):
    """Initialize worker with sequential model loading to prevent memory issues"""
    global _worker_state

    _worker_state['worker_id'] = worker_id

    # Smart device allocation - use CPU for some workers to balance load
    if device:
        dev = device
    elif worker_id == 0:  # Primary worker gets GPU
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    else:  # Secondary workers use CPU to avoid GPU memory conflicts
        dev = "cpu"

    _worker_state['device'] = dev

    print(f"Worker {worker_id} initializing on {dev}")
    mem_before = get_memory_info()
    print(f"Memory before: RAM {mem_before['ram_used_gb']:.2f}GB, GPU {mem_before['gpu_used_gb']:.2f}GB")

    try:
        # Load models sequentially with memory monitoring
        # 1. CLIP
        print(f"Worker {worker_id}: Loading CLIP...")
        clip_name = "D:/models/models/clip-vit-base-patch32"
        _worker_state['clip_model'] = CLIPModel.from_pretrained(clip_name).to(dev)
        _worker_state['clip_processor'] = CLIPProcessor.from_pretrained(clip_name)

        if dev == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

        mem_after_clip = get_memory_info()
        print(f"After CLIP: RAM {mem_after_clip['ram_used_gb']:.2f}GB, GPU {mem_after_clip['gpu_used_gb']:.2f}GB")

        # 2. BLIP
        print(f"Worker {worker_id}: Loading BLIP...")
        blip_name = "D:/models/models/blip-image-captioning-base"
        _worker_state['blip_model'] = BlipForConditionalGeneration.from_pretrained(blip_name).to(dev)
        _worker_state['blip_processor'] = BlipProcessor.from_pretrained(blip_name)

        if dev == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

        # 3. Sentence transformer (only for primary worker to save memory)
        if worker_id == 0:
            try:
                print(f"Worker {worker_id}: Loading sentence transformer...")
                sentence_model_name = "D:/models/models/all-MiniLM-L6-v2"
                _worker_state['sentence_tokenizer'] = AutoTokenizer.from_pretrained(sentence_model_name)
                _worker_state['sentence_model'] = AutoModel.from_pretrained(sentence_model_name).to(dev)
            except Exception as e:
                print(f"Sentence transformer failed, using CLIP text encoder: {e}")
                _worker_state['sentence_model'] = None
                _worker_state['sentence_tokenizer'] = None

        # 4. Lemmatizer
        try:
            _worker_state['lemmatizer'] = WordNetLemmatizer()
        except:
            _worker_state['lemmatizer'] = None

        mem_final = get_memory_info()
        print(f"Worker {worker_id} ready: RAM {mem_final['ram_used_gb']:.2f}GB, GPU {mem_final['gpu_used_gb']:.2f}GB")

    except Exception as e:
        print(f"Worker {worker_id} initialization failed: {e}")
        raise


def mean_pooling(model_output, attention_mask):
    """Mean pooling for sentence transformers"""
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)


def _process_video_high_accuracy(args: Tuple[str, int, int]) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]]]:
    """High-accuracy video processing with memory management"""
    video_path, max_frames, worker_id = args
    global _worker_state

    print(f"Worker {_worker_state['worker_id']}: Processing {video_path} (max {max_frames} frames)")

    # Get models from worker state
    clip_model = _worker_state['clip_model']
    clip_processor = _worker_state['clip_processor']
    blip_model = _worker_state['blip_model']
    blip_processor = _worker_state['blip_processor']
    sentence_model = _worker_state['sentence_model']
    sentence_tokenizer = _worker_state['sentence_tokenizer']
    lemmatizer = _worker_state['lemmatizer']
    device = _worker_state['device']

    clip_embeddings = []
    text_embeddings = []
    metadata = []

    try:
        frame_count = 0
        for timestamp, frame_bgr in adaptive_frame_sampling(video_path, max_frames=max_frames):
            try:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

                # 1. CLIP image embedding
                clip_inputs = clip_processor(images=frame_rgb, return_tensors="pt").to(device)
                with torch.no_grad():
                    clip_emb = clip_model.get_image_features(**clip_inputs).cpu().numpy().astype(np.float32)
                clip_embeddings.append(clip_emb.reshape(-1))

                # 2. Enhanced caption generation
                enhanced_caption = enhanced_caption_generation(frame_rgb, blip_model, blip_processor, device)

                # 3. Semantic feature extraction
                semantic_features = extract_advanced_semantic_features(enhanced_caption, lemmatizer)

                # 4. Text embedding (sentence transformer or CLIP fallback)
                if sentence_model and sentence_tokenizer:
                    try:
                        encoded = sentence_tokenizer(enhanced_caption, padding=True, truncation=True,
                                                     return_tensors='pt').to(device)
                        with torch.no_grad():
                            model_output = sentence_model(**encoded)
                            text_emb = mean_pooling(model_output, encoded['attention_mask']).cpu().numpy().astype(
                                np.float32)
                        text_embeddings.append(text_emb.reshape(-1))
                    except Exception:
                        # Fallback to CLIP text embedding
                        text_inputs = clip_processor(text=[enhanced_caption], return_tensors="pt",
                                                     padding=True, truncation=True).to(device)
                        with torch.no_grad():
                            text_emb = clip_model.get_text_features(**text_inputs).cpu().numpy().astype(np.float32)
                        text_embeddings.append(text_emb.reshape(-1))
                else:
                    # Use CLIP text embedding
                    text_inputs = clip_processor(text=[enhanced_caption], return_tensors="pt",
                                                 padding=True, truncation=True).to(device)
                    with torch.no_grad():
                        text_emb = clip_model.get_text_features(**text_inputs).cpu().numpy().astype(np.float32)
                    text_embeddings.append(text_emb.reshape(-1))

                # 5. Optional emotion analysis (only if DeepFace available and not too memory intensive)
                mood = None
                if _DEEPFACE_AVAILABLE and device == "cuda" and frame_count % 5 == 0:  # Sample emotions sparsely
                    try:
                        analysis = DeepFace.analyze(frame_bgr, actions=["emotion"], enforce_detection=False)
                        if isinstance(analysis, list):
                            analysis = analysis[0]
                        mood = analysis.get('dominant_emotion')
                    except Exception:
                        mood = None

                # Store metadata
                metadata.append({
                    'video_path': os.path.abspath(video_path),
                    'timestamp': float(timestamp),
                    'caption': enhanced_caption,
                    'semantic_features': semantic_features,
                    'mood': mood
                })

                frame_count += 1

                # Memory management every few frames
                if frame_count % 10 == 0:
                    if device == "cuda":
                        torch.cuda.empty_cache()
                    gc.collect()

                    if frame_count % 20 == 0:  # Less frequent memory reporting
                        mem = get_memory_info()
                        print(f"Worker {_worker_state['worker_id']}: Processed {frame_count} frames, "
                              f"RAM: {mem['ram_used_gb']:.2f}GB, GPU: {mem['gpu_used_gb']:.2f}GB")

            except Exception as e:
                print(f"Frame processing error at {timestamp}s: {e}")
                continue

        print(f"Worker {_worker_state['worker_id']}: Completed {video_path} with {frame_count} frames")

    except Exception as e:
        print(f"Video processing error for {video_path}: {e}")

    # Convert to arrays with error handling
    if clip_embeddings:
        clip_array = np.vstack(clip_embeddings).astype(np.float32)
    else:
        clip_array = np.zeros((0, 512), dtype=np.float32)

    if text_embeddings:
        text_array = np.vstack(text_embeddings).astype(np.float32)
    else:
        # Match the expected dimension
        expected_dim = 512 if not sentence_model else 384
        text_array = np.zeros((0, expected_dim), dtype=np.float32)

    return clip_array, text_array, metadata


class HighAccuracyVideoIndexer:
    """High-accuracy indexer with incremental preprocessing support"""

    def __init__(self):
        self.clip_embeddings: List[np.ndarray] = []
        self.text_embeddings: List[np.ndarray] = []
        self.frame_metadata: List[Dict[str, Any]] = []
        self.next_id = 0  # Track next available ID

    def generate_thumbnails_during_processing(self, video_path, frame_rgb, timestamp):
        """Generate thumbnail during video processing"""
        if not hasattr(self, 'thumbnail_generator'):
            from enhanced_features import ThumbnailGenerator
            self.thumbnail_generator = ThumbnailGenerator()

        # Generate thumbnail from current frame if at 10% mark
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                duration = frame_count / fps
                cap.release()

                # Check if this timestamp is around 10% of video
                target_time = duration * 0.1
                if abs(timestamp - target_time) < 2.0:  # Within 2 seconds
                    # Save thumbnail
                    video_name = Path(video_path).stem
                    thumbnail_path = self.thumbnail_generator.thumbnail_dir / f"{video_name}_{hash(video_path) % 100000}.jpg"

                    frame_resized = cv2.resize(frame_rgb, self.thumbnail_generator.thumbnail_size)
                    frame_bgr = cv2.cvtColor(frame_resized, cv2.COLOR_RGB2BGR)
                    cv2.imwrite(str(thumbnail_path), frame_bgr)

                    return str(thumbnail_path)
        except:
            pass

        return None

    def load_existing_indices(self, out_dir: Path) -> bool:
        """Load existing indices if they exist"""
        clip_index_path = out_dir / "clip_index.faiss"
        text_index_path = out_dir / "text_index.faiss"
        metadata_path = out_dir / "metadata.pkl"
        tfidf_path = out_dir / "tfidf_index.pkl"

        # Check if all required files exist
        required_files = [clip_index_path, text_index_path, metadata_path, tfidf_path]
        if not all(f.exists() for f in required_files):
            print("No existing index found - starting fresh")
            return False

        try:
            print("Loading existing indices...")

            # Load metadata first to get existing data
            with open(metadata_path, 'rb') as f:
                existing_metadata = pickle.load(f)

            # Extract existing embeddings and metadata
            self.frame_metadata = []
            for i, video_path in enumerate(existing_metadata['video_paths']):
                self.frame_metadata.append({
                    'id': existing_metadata['ids'][i],
                    'video_path': video_path,
                    'timestamp': existing_metadata['timestamps'][i],
                    'caption': existing_metadata['captions'][i],
                    'semantic_features': existing_metadata['semantic_features'][i],
                    'mood': existing_metadata['moods'][i] if i < len(existing_metadata['moods']) else None
                })

            # Set next_id to continue from where we left off
            if existing_metadata['ids'].size > 0:
                self.next_id = int(existing_metadata['ids'].max()) + 1
            else:
                self.next_id = 0

            print(f"Loaded existing index with {len(self.frame_metadata)} frames")
            print(f"Next ID will be: {self.next_id}")

            # Load existing FAISS indices to extract embeddings
            clip_index = faiss.read_index(str(clip_index_path))
            text_index = faiss.read_index(str(text_index_path))

            # Extract embeddings from FAISS indices
            # Note: This is a simplified approach - in production you might want to store embeddings separately
            n_vectors = clip_index.ntotal
            if n_vectors > 0:
                # Reconstruct embeddings (this works for IndexFlatIP)
                if hasattr(clip_index, 'index') and hasattr(clip_index.index, 'reconstruct_n'):
                    # For IndexIDMap with IndexFlatIP
                    clip_embeddings = clip_index.index.reconstruct_n(0, n_vectors)
                    text_embeddings = text_index.index.reconstruct_n(0, n_vectors)
                elif hasattr(clip_index, 'reconstruct_n'):
                    # For direct IndexFlatIP
                    clip_embeddings = clip_index.reconstruct_n(0, n_vectors)
                    text_embeddings = text_index.reconstruct_n(0, n_vectors)
                else:
                    print("Warning: Cannot extract embeddings from existing index type")
                    clip_embeddings = np.zeros((0, 512), dtype=np.float32)
                    text_embeddings = np.zeros((0, 384), dtype=np.float32)

                # Convert to list of individual embeddings
                if clip_embeddings.size > 0:
                    self.clip_embeddings = [clip_embeddings[i:i + 1] for i in range(clip_embeddings.shape[0])]
                if text_embeddings.size > 0:
                    self.text_embeddings = [text_embeddings[i:i + 1] for i in range(text_embeddings.shape[0])]

            return True

        except Exception as e:
            print(f"Error loading existing indices: {e}")
            print("Starting fresh...")
            self.clip_embeddings = []
            self.text_embeddings = []
            self.frame_metadata = []
            self.next_id = 0
            return False

    def get_existing_video_paths(self) -> set:
        """Get set of video paths already processed"""
        return set(os.path.abspath(meta['video_path']) for meta in self.frame_metadata)

    def process_video_folder(self, videos_dir: str, workers: int = 3, max_frames_per_video: int = 60,
                             out_dir: str = None, incremental: bool = True):
        """Process videos with incremental support"""
        videos_dir = Path(videos_dir)

        if out_dir and incremental:
            out_dir_path = Path(out_dir)
            self.load_existing_indices(out_dir_path)

        video_extensions = ['.mp4', '.mov', '.mkv', '.avi', '.webm', '.wmv', '.flv', '.m4v', '.3gp', '.ogv']
        video_files = []

        print(f"Recursively scanning {videos_dir} for video files...")

        def should_skip_path(path: Path) -> bool:
            """Check if path contains any 'raw' directory (case insensitive)"""
            for part in path.parts:
                if part.lower() == 'raw':
                    return True
            return False

        for ext in video_extensions:
            pattern = f"**/*{ext}"
            found_files = [f for f in videos_dir.glob(pattern) if not should_skip_path(f)]
            video_files.extend(found_files)

            pattern_upper = f"**/*{ext.upper()}"
            found_files_upper = [f for f in videos_dir.glob(pattern_upper) if not should_skip_path(f)]
            video_files.extend(found_files_upper)

        video_files = list(set(str(p) for p in video_files if p.is_file()))
        video_files.sort()

        # Filter out already processed videos if incremental
        if incremental:
            existing_paths = self.get_existing_video_paths()
            new_video_files = []
            skipped_existing = 0

            for video_file in video_files:
                abs_path = os.path.abspath(video_file)
                if abs_path not in existing_paths:
                    new_video_files.append(video_file)
                else:
                    skipped_existing += 1

            video_files = new_video_files
            print(f"Incremental mode: Skipped {skipped_existing} already processed videos")

        # Report skipped 'Raw' directories
        def count_all_videos_including_raw():
            """Count total videos including those in Raw directories"""
            all_videos = []
            for ext in video_extensions:
                all_videos.extend(list(videos_dir.glob(f"**/*{ext}")))
                all_videos.extend(list(videos_dir.glob(f"**/*{ext.upper()}")))
            return len(set(str(p) for p in all_videos if p.is_file()))

        def find_raw_directories():
            """Find all Raw directories that were skipped"""
            raw_dirs = set()
            for path in videos_dir.rglob("*"):
                if path.is_dir() and path.name.lower() == 'raw':
                    raw_dirs.add(str(path.relative_to(videos_dir)))
            return raw_dirs

        total_videos_including_raw = count_all_videos_including_raw()
        total_after_raw_filter = len(video_files) + (len(self.get_existing_video_paths()) if incremental else 0)
        skipped_videos_count = total_videos_including_raw - total_after_raw_filter
        raw_directories = find_raw_directories()

        if skipped_videos_count > 0:
            print(f"Skipped {skipped_videos_count} videos from {len(raw_directories)} 'Raw' directories:")
            for raw_dir in sorted(raw_directories):
                print(f"  - Skipped: {raw_dir}/")

        print(f"Found {len(video_files)} new video files to process")
        if incremental:
            print(f"Total videos in index after processing: {len(self.get_existing_video_paths()) + len(video_files)}")

        if not video_files:
            print("No new video files to process")
            return

        directories_found = set()
        for video_file in video_files:
            rel_dir = os.path.relpath(os.path.dirname(video_file), videos_dir)
            if rel_dir != '.':
                directories_found.add(rel_dir)

        if directories_found:
            print(f"Processing new videos from {len(directories_found)} subdirectories:")
            for directory in sorted(directories_found)[:10]:
                count = sum(1 for vf in video_files if os.path.dirname(vf).endswith(directory.replace('/', os.sep)))
                print(f"  {directory}: {count} videos")
            if len(directories_found) > 10:
                print(f"  ... and {len(directories_found) - 10} more directories")

        mem_info = get_memory_info()
        print(f"Available RAM: {mem_info['ram_available_gb']:.2f}GB")

        # Each worker needs ~4-6GB RAM, adjust accordingly
        # max_safe_workers = max(1, min(workers, int(mem_info['ram_available_gb'] // 4)))
        max_safe_workers = max(1, min(3, workers))
        print(f"Using {max_safe_workers} workers (requested: {workers})")

        tasks = [(vf, max_frames_per_video, i % max_safe_workers) for i, vf in enumerate(video_files)]

        with concurrent.futures.ProcessPoolExecutor(
                max_workers=max_safe_workers,
                initializer=_init_high_accuracy_worker,
                initargs=(0,)
        ) as executor:
            global_id = self.next_id

            futures = [executor.submit(_process_video_high_accuracy, task) for task in tasks]

            for i, future in enumerate(concurrent.futures.as_completed(futures, timeout=None)):
                try:
                    clip_arr, text_arr, meta_list = future.result(timeout=1800)

                    if clip_arr.size > 0:
                        for j in range(clip_arr.shape[0]):
                            self.clip_embeddings.append(clip_arr[j:j + 1])

                    if text_arr.size > 0:
                        for j in range(text_arr.shape[0]):
                            self.text_embeddings.append(text_arr[j:j + 1])

                    for meta in meta_list:
                        meta['id'] = global_id
                        self.frame_metadata.append(meta)
                        global_id += 1

                    print(
                        f"Completed video {i + 1}/{len(video_files)}, total frames in index: {len(self.frame_metadata)}")

                except Exception as e:
                    print(f"Video processing failed: {e}")
                    continue

            # Update next_id for future incremental runs
            self.next_id = global_id

    def build_high_accuracy_indices(self, clip_index_path: str, text_index_path: str):
        """Build optimized indices (now handles incremental data)"""
        if not self.clip_embeddings:
            print("No embeddings to index")
            return

        # CLIP index
        clip_X = np.vstack(self.clip_embeddings).astype(np.float32)
        clip_X = norm_l2(clip_X)

        # Text index
        text_X = np.vstack(self.text_embeddings).astype(np.float32)
        text_X = norm_l2(text_X)

        n_vectors = clip_X.shape[0]
        ids = np.array([m['id'] for m in self.frame_metadata], dtype=np.int64)

        print(
            f"Building indices for {n_vectors} total vectors ({n_vectors - (self.next_id - len(self.frame_metadata))} new)")

        # CLIP Index with accuracy-focused parameters
        if n_vectors > 5000:
            nlist = min(2048, max(256, int(np.sqrt(n_vectors) * 1.5)))
            quantizer = faiss.IndexFlatIP(clip_X.shape[1])
            clip_index = faiss.IndexIVFFlat(quantizer, clip_X.shape[1], nlist)
            clip_index.train(clip_X)
            clip_index.nprobe = max(32, nlist // 4)
        else:
            clip_index = faiss.IndexFlatIP(clip_X.shape[1])

        clip_id_map = faiss.IndexIDMap(clip_index)
        clip_id_map.add_with_ids(clip_X, ids)
        faiss.write_index(clip_id_map, clip_index_path)

        # Text Index
        if n_vectors > 5000:
            nlist = min(2048, max(256, int(np.sqrt(n_vectors) * 1.5)))
            quantizer = faiss.IndexFlatIP(text_X.shape[1])
            text_index = faiss.IndexIVFFlat(quantizer, text_X.shape[1], nlist)
            text_index.train(text_X)
            text_index.nprobe = max(32, nlist // 4)
        else:
            text_index = faiss.IndexFlatIP(text_X.shape[1])

        text_id_map = faiss.IndexIDMap(text_index)
        text_id_map.add_with_ids(text_X, ids)
        faiss.write_index(text_id_map, text_index_path)

        print("Incremental indices built successfully")

    def build_comprehensive_text_index(self, text_index_path: str):
        """Build comprehensive text index (handles all data including existing)"""
        captions = [m.get("caption", "") for m in self.frame_metadata]
        semantic_features = [" ".join(m.get("semantic_features", [])) for m in self.frame_metadata]

        combined_texts = [f"{caption} {features}" for caption, features in zip(captions, semantic_features)]

        vectorizer = TfidfVectorizer(
            max_features=15000,
            stop_words='english',
            ngram_range=(1, 3),
            min_df=1,
            max_df=0.9,
            strip_accents='ascii',
            sublinear_tf=True,
            use_idf=True
        )

        tfidf_matrix = vectorizer.fit_transform(combined_texts)

        with open(text_index_path, 'wb') as f:
            pickle.dump({
                'vectorizer': vectorizer,
                'tfidf_matrix': tfidf_matrix,
                'captions': captions,
                'semantic_features': semantic_features
            }, f, protocol=pickle.HIGHEST_PROTOCOL)

        print("Comprehensive text index built with all data")

    def save_metadata(self, metadata_path: str):
        """Save comprehensive metadata (all data including existing)"""
        video_stats = defaultdict(lambda: {'captions': [], 'moods': [], 'semantic_features': []})

        for m in self.frame_metadata:
            vp = os.path.abspath(m['video_path'])
            video_stats[vp]['captions'].append(m.get('caption', ''))
            if m.get('mood'):
                video_stats[vp]['moods'].append(m['mood'])
            video_stats[vp]['semantic_features'].extend(m.get('semantic_features', []))

        for vp, stats in video_stats.items():
            stats['dominant_mood'] = Counter(stats['moods']).most_common(1)[0][0] if stats['moods'] else None
            stats['unique_semantic_features'] = list(set(stats['semantic_features']))

        metadata = {
            'ids': np.array([m['id'] for m in self.frame_metadata], dtype=np.int32),
            'video_paths': [m['video_path'] for m in self.frame_metadata],
            'timestamps': np.array([m['timestamp'] for m in self.frame_metadata], dtype=np.float32),
            'captions': [m.get('caption', '') for m in self.frame_metadata],
            'semantic_features': [m.get('semantic_features', []) for m in self.frame_metadata],
            'moods': [m.get('mood') for m in self.frame_metadata],
            'video_stats': dict(video_stats),
            'next_id': self.next_id  # Save next_id for future incremental runs
        }

        with open(metadata_path, 'wb') as f:
            pickle.dump(metadata, f, protocol=pickle.HIGHEST_PROTOCOL)

        print(f"Comprehensive metadata saved ({len(self.frame_metadata)} total frames)")


def get_directory_stats(video_files, base_dir):
    """Get statistics about directory structure and video distribution"""
    stats = {
        'total_videos': len(video_files),
        'directories': defaultdict(int),
        'max_depth': 0,
        'total_size': 0
    }

    base_path = Path(base_dir)

    for video_file in video_files:
        try:
            video_path = Path(video_file)
            rel_path = video_path.relative_to(base_path)
            depth = len(rel_path.parts) - 1
            stats['max_depth'] = max(stats['max_depth'], depth)

            if depth == 0:
                dir_key = "root"
            else:
                dir_key = str(rel_path.parent)
            stats['directories'][dir_key] += 1

            if os.path.exists(video_file):
                stats['total_size'] += os.path.getsize(video_file)

        except (ValueError, OSError):
            continue

    return stats



class HighAccuracyVideoSearcher:
    """High-accuracy searcher with multi-modal fusion"""

    def __init__(self, clip_index_path: str, text_index_path: str, metadata_path: str, tfidf_path: str):
        print("Initializing high-accuracy video searcher...")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Load search models
        self.clip_model = CLIPModel.from_pretrained("D:/models/models/clip-vit-base-patch32").to(self.device)
        self.clip_processor = CLIPProcessor.from_pretrained("D:/models/models/clip-vit-base-patch32")

        try:
            self.sentence_tokenizer = AutoTokenizer.from_pretrained("D:/models/models/all-MiniLM-L6-v2")
            self.sentence_model = AutoModel.from_pretrained("D:/models/models/all-MiniLM-L6-v2").to(self.device)
        except:
            self.sentence_model = None
            self.sentence_tokenizer = None

        self.lemmatizer = WordNetLemmatizer()

        # Load indices
        self.clip_index = faiss.read_index(clip_index_path)
        self.text_index = faiss.read_index(text_index_path)

        # Load metadata
        with open(metadata_path, 'rb') as f:
            self.metadata = pickle.load(f)

        with open(tfidf_path, 'rb') as f:
            tfidf_data = pickle.load(f)
            self.vectorizer = tfidf_data['vectorizer']
            self.tfidf_matrix = tfidf_data['tfidf_matrix']

        print("High-accuracy searcher ready!")

    def expand_query_advanced(self, query: str) -> str:
        """Advanced query expansion with synonyms and related terms"""
        try:
            words = word_tokenize(query.lower())
            expanded = set(words)

            for word in words:
                # Add synonyms
                synsets = wordnet.synsets(word)
                for syn in synsets[:2]:
                    for lemma in syn.lemmas()[:2]:
                        synonym = lemma.name().replace('_', ' ')
                        if len(synonym) > 2:
                            expanded.add(synonym)

                # Add lemmatized form
                try:
                    lemmatized = self.lemmatizer.lemmatize(word)
                    expanded.add(lemmatized)
                except:
                    pass

            return " ".join(expanded)
        except:
            return query

    def search_with_high_accuracy(self, query: str, top_k: int = 20,
                                  clip_weight: float = 0.35, text_weight: float = 0.35, tfidf_weight: float = 0.3):
        """High-accuracy multi-modal search"""
        print(f"High-accuracy search for: '{query}'")

        # Query expansion
        expanded_query = self.expand_query_advanced(query)

        # Get embeddings
        with torch.no_grad():
            # CLIP embedding
            clip_inputs = self.clip_processor(text=[query], return_tensors="pt", padding=True).to(self.device)
            clip_emb = self.clip_model.get_text_features(**clip_inputs).cpu().numpy().astype(np.float32)
            clip_emb = norm_l2(clip_emb)

            # Expanded query CLIP embedding
            exp_clip_inputs = self.clip_processor(text=[expanded_query], return_tensors="pt", padding=True).to(
                self.device)
            exp_clip_emb = self.clip_model.get_text_features(**exp_clip_inputs).cpu().numpy().astype(np.float32)
            exp_clip_emb = norm_l2(exp_clip_emb)

            # Text embedding (sentence transformer if available)
            if self.sentence_model and self.sentence_tokenizer:
                encoded = self.sentence_tokenizer(query, padding=True, truncation=True, return_tensors='pt').to(
                    self.device)
                model_output = self.sentence_model(**encoded)
                text_emb = mean_pooling(model_output, encoded['attention_mask']).cpu().numpy().astype(np.float32)
                text_emb = norm_l2(text_emb)

                exp_encoded = self.sentence_tokenizer(expanded_query, padding=True, truncation=True,
                                                      return_tensors='pt').to(self.device)
                exp_model_output = self.sentence_model(**exp_encoded)
                exp_text_emb = mean_pooling(exp_model_output, exp_encoded['attention_mask']).cpu().numpy().astype(
                    np.float32)
                exp_text_emb = norm_l2(exp_text_emb)
            else:
                text_emb = clip_emb
                exp_text_emb = exp_clip_emb

        # Multi-modal search with larger candidate pool for reranking
        search_k = min(top_k * 3, 200)

        # CLIP searches
        clip_scores, clip_ids = self.clip_index.search(clip_emb, search_k)
        exp_clip_scores, exp_clip_ids = self.clip_index.search(exp_clip_emb, search_k)

        # Text embedding searches
        text_scores, text_ids = self.text_index.search(text_emb, search_k)
        exp_text_scores, exp_text_ids = self.text_index.search(exp_text_emb, search_k)

        # TF-IDF search
        query_vec = self.vectorizer.transform([query])
        exp_query_vec = self.vectorizer.transform([expanded_query])

        tfidf_scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        exp_tfidf_scores = cosine_similarity(exp_query_vec, self.tfidf_matrix).flatten()

        # Collect all candidates with their scores
        candidates = {}

        # Process CLIP results
        for score, idx in zip(clip_scores[0], clip_ids[0]):
            if idx >= 0 and idx < len(self.metadata['ids']):
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['clip'] = float(score)

        for score, idx in zip(exp_clip_scores[0], exp_clip_ids[0]):
            if idx >= 0 and idx < len(self.metadata['ids']):
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['exp_clip'] = float(score)

        # Process text embedding results
        for score, idx in zip(text_scores[0], text_ids[0]):
            if idx >= 0 and idx < len(self.metadata['ids']):
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['text'] = float(score)

        for score, idx in zip(exp_text_scores[0], exp_text_ids[0]):
            if idx >= 0 and idx < len(self.metadata['ids']):
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['exp_text'] = float(score)

        # Add TF-IDF scores for top candidates
        tfidf_top_indices = np.argsort(tfidf_scores)[-search_k:][::-1]
        exp_tfidf_top_indices = np.argsort(exp_tfidf_scores)[-search_k:][::-1]

        for idx in tfidf_top_indices:
            if idx < len(self.metadata['ids']) and tfidf_scores[idx] > 0.05:
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['tfidf'] = float(tfidf_scores[idx])

        for idx in exp_tfidf_top_indices:
            if idx < len(self.metadata['ids']) and exp_tfidf_scores[idx] > 0.05:
                candidates[idx] = candidates.get(idx, {})
                candidates[idx]['exp_tfidf'] = float(exp_tfidf_scores[idx])

        # Multi-modal fusion with enhanced scoring
        final_scores = {}
        for idx, scores in candidates.items():
            # Get best score from each modality
            clip_score = max(scores.get('clip', 0), scores.get('exp_clip', 0))
            text_score = max(scores.get('text', 0), scores.get('exp_text', 0))
            tfidf_score = max(scores.get('tfidf', 0), scores.get('exp_tfidf', 0))

            # Weighted combination
            final_score = (clip_weight * clip_score +
                           text_weight * text_score +
                           tfidf_weight * tfidf_score)

            # Consistency bonus - reward frames that score well across multiple modalities
            non_zero_scores = sum(1 for s in [clip_score, text_score, tfidf_score] if s > 0.1)
            consistency_bonus = 0.05 * max(0, non_zero_scores - 1)

            final_scores[idx] = final_score + consistency_bonus

        # Aggregate by video with temporal clustering
        video_aggregates = defaultdict(list)
        for idx in final_scores:
            video_path = os.path.abspath(self.metadata['video_paths'][idx])
            timestamp = self.metadata['timestamps'][idx]
            score = final_scores[idx]
            video_aggregates[video_path].append({
                'timestamp': timestamp,
                'score': score,
                'idx': idx
            })

        # Compute video-level scores with temporal consistency
        video_final_scores = {}
        for video_path, frame_data in video_aggregates.items():
            # Sort by timestamp
            frame_data.sort(key=lambda x: x['timestamp'])

            # Base score: sum of all frame scores
            base_score = sum(f['score'] for f in frame_data)

            # Temporal clustering bonus
            temporal_bonus = 0
            if len(frame_data) > 1:
                # Group frames that are close in time
                clusters = []
                current_cluster = [frame_data[0]]

                for frame in frame_data[1:]:
                    if frame['timestamp'] - current_cluster[-1]['timestamp'] <= 10.0:  # 10 second window
                        current_cluster.append(frame)
                    else:
                        clusters.append(current_cluster)
                        current_cluster = [frame]
                clusters.append(current_cluster)

                # Bonus for having multiple relevant clusters
                if len(clusters) > 1:
                    temporal_bonus = 0.1 * (len(clusters) - 1)

                # Bonus for high-scoring clusters
                for cluster in clusters:
                    avg_cluster_score = np.mean([f['score'] for f in cluster])
                    if avg_cluster_score > 0.3 and len(cluster) >= 2:
                        temporal_bonus += 0.05

            video_final_scores[video_path] = base_score + temporal_bonus

        # Rank videos and return results
        ranked_videos = sorted(video_final_scores.keys(),
                               key=lambda v: video_final_scores[v],
                               reverse=True)

        results = []
        for video_path in ranked_videos[:top_k]:
            # Get best frame for this video
            best_frame = max(video_aggregates[video_path], key=lambda f: f['score'])

            results.append({
                'video_path': video_path,
                'timestamp': best_frame['timestamp'],
                'caption': self.metadata['captions'][best_frame['idx']],
                'score': video_final_scores[video_path],
                'frame_count': len(video_aggregates[video_path])
            })

        return results

    def query_filtered_by_directory(self, text: str, filter_directory: str, top_k: int = 20,
                                    clip_weight: float = 0.35, text_weight: float = 0.35, tfidf_weight: float = 0.3):
        """Search and filter results to only include videos from specified directory"""
        all_results = self.search_with_high_accuracy(text, top_k=top_k * 3,
                                                     clip_weight=clip_weight, text_weight=text_weight,
                                                     tfidf_weight=tfidf_weight)

        filter_directory = os.path.normpath(filter_directory)
        filtered_results = []

        for result in all_results:
            video_norm = os.path.normpath(result['video_path'])

            if (video_norm.startswith(filter_directory + os.sep) or
                    video_norm == filter_directory or
                    os.path.commonpath([filter_directory, video_norm]) == filter_directory):
                filtered_results.append(result)

        return filtered_results[:top_k]

    def has_videos_from_directory(self, directory_path: str) -> bool:
        """Check if the index contains any videos from the specified directory"""
        directory_path = os.path.normpath(directory_path)

        for video_path in self.metadata['video_paths']:
            video_norm = os.path.normpath(video_path)
            if (video_norm.startswith(directory_path + os.sep) or
                    video_norm == directory_path or
                    os.path.commonpath([directory_path, video_norm]) == directory_path):
                return True
        return False

    def get_video_count_for_directory(self, directory_path: str) -> int:
        """Get total number of unique videos in index from specified directory"""
        directory_path = os.path.normpath(directory_path)
        unique_videos = set()

        for video_path in self.metadata['video_paths']:
            video_norm = os.path.normpath(video_path)
            if (video_norm.startswith(directory_path + os.sep) or
                    video_norm == directory_path or
                    os.path.commonpath([directory_path, video_norm]) == directory_path):
                unique_videos.add(video_norm)

        return len(unique_videos)

    def query(self, text: str, top_k: int = 50, mood: str = None, allow_nsfw: bool = True, caption_weight: float = 0.4):
        """Wrapper method to match search_model.py interface"""
        results = self.search_with_high_accuracy(text, top_k,
                                                 clip_weight=1 - caption_weight,
                                                 text_weight=caption_weight,
                                                 tfidf_weight=0.0)

        video_paths = [r['video_path'] for r in results]
        video_counts = {r['video_path']: r['frame_count'] for r in results}
        video_scores = {r['video_path']: r['score'] for r in results}

        return video_paths, video_counts, video_scores


def select_video_directory():
    """Manually select video directory using file dialog"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        print("Opening directory selection dialog...")
        directory = filedialog.askdirectory(
            title="Select Video Directory for Preprocessing",
            initialdir=os.path.expanduser("~")
        )

        root.destroy()

        if directory:
            print(f"Selected directory: {directory}")
            return directory
        else:
            print("No directory selected. Exiting...")
            return None

    except ImportError:
        print("tkinter not available. Please provide --videos_dir argument.")
        return None
    except Exception as e:
        print(f"Error in directory selection: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="High-Accuracy Video Search with Resource Management")
    parser.add_argument("--mode", choices=["preprocess", "search"], required=True)
    parser.add_argument("--videos_dir", default=None, help="Video directory (will prompt if not provided)")
    parser.add_argument("--out_dir", default=r"C:\Users\Abir\Documents\Recursive Media Player\index_data",
                        help="Output directory for index files")
    parser.add_argument("--workers", type=int, default=3, help="Number of workers (recommend 1-3 for high accuracy)")
    parser.add_argument("--max_frames", type=int, default=60, help="Max frames per video")
    parser.add_argument("--recursive", action="store_true", default=True, help="Recursively process subdirectories")
    parser.add_argument("--incremental", action="store_true", default=True,
                        help="Incremental preprocessing (append to existing)")
    parser.add_argument("--force_rebuild", action="store_true", help="Force complete rebuild (ignore existing indices)")
    parser.add_argument("--query", type=str)
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--clip_weight", type=float, default=0.35)
    parser.add_argument("--text_weight", type=float, default=0.35)
    parser.add_argument("--tfidf_weight", type=float, default=0.3)
    parser.add_argument("--keep_alive", action="store_true", help="Interactive mode")
    args = parser.parse_args()

    if args.mode == "preprocess":
        if args.videos_dir:
            videos_dir_path = args.videos_dir
        else:
            print("No video directory specified. Opening directory selection dialog...")
            videos_dir_path = select_video_directory()
            if not videos_dir_path:
                print("No directory selected. Cannot proceed with preprocessing.")
                return

        videos_dir = Path(videos_dir_path)
        if not videos_dir.exists():
            print(f"Error: Directory {videos_dir} does not exist")
            return

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Index data will be saved to: {out_dir}")

        print("Starting high-accuracy recursive video preprocessing...")
        print(f"Processing videos from: {videos_dir}")

        mem_info = get_memory_info()
        print(
            f"System memory: {mem_info['ram_available_gb']:.1f}GB available, {mem_info['gpu_used_gb']:.1f}GB GPU used")

        print(f"Analyzing directory structure of: {videos_dir}")

        video_extensions = ['.mp4', '.mov', '.mkv', '.avi', '.webm', '.wmv', '.flv', '.m4v', '.3gp', '.ogv']
        all_videos = []
        for ext in video_extensions:
            all_videos.extend(list(videos_dir.glob(f"**/*{ext}")))
            all_videos.extend(list(videos_dir.glob(f"**/*{ext.upper()}")))

        all_videos = [str(p) for p in set(all_videos) if p.is_file()]

        if not all_videos:
            print("No video files found in directory tree")
            return

        dir_stats = get_directory_stats(all_videos, str(videos_dir))
        print(f"Directory Analysis:")
        print(f"  Total videos: {dir_stats['total_videos']}")
        print(f"  Max directory depth: {dir_stats['max_depth']}")
        print(f"  Total size: {dir_stats['total_size'] / (1024 ** 3):.2f} GB")
        print(f"  Videos distributed across {len(dir_stats['directories'])} directories")

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        incremental_mode = args.incremental and not args.force_rebuild

        if incremental_mode:
            print("Starting incremental video preprocessing...")
        else:
            print("Starting complete video preprocessing...")

        indexer = HighAccuracyVideoIndexer()
        indexer.process_video_folder(
            str(videos_dir),
            args.workers,
            args.max_frames,
            out_dir=str(out_dir),
            incremental=incremental_mode
        )

        print("Building indices...")
        indexer.build_high_accuracy_indices(
            str(out_dir / "clip_index.faiss"),
            str(out_dir / "text_index.faiss")
        )
        indexer.build_comprehensive_text_index(str(out_dir / "tfidf_index.pkl"))
        indexer.save_metadata(str(out_dir / "metadata.pkl"))

        print(f"Preprocessing complete! Total frames in index: {len(indexer.frame_metadata)}")

        final_mem = get_memory_info()
        print(f"Recursive preprocessing complete!")
        print(f"Final memory: {final_mem['ram_used_gb']:.1f}GB RAM, {final_mem['gpu_used_gb']:.1f}GB GPU")
        print(f"Processed {len(indexer.frame_metadata)} frames from {dir_stats['total_videos']} videos")
        print(f"Index files saved to: {out_dir}")



    elif args.mode == "search":
        if not args.query:
            print("Provide --query for search")
            return

        default_out_dir = r"C:\Users\Abir\Documents\Recursive Media Player\index_data"
        out_dir_to_use = args.out_dir if args.out_dir != "./index_data" else default_out_dir
        clip_index_path = str(Path(out_dir_to_use) / "clip_index.faiss")
        text_index_path = str(Path(out_dir_to_use) / "text_index.faiss")
        metadata_path = str(Path(out_dir_to_use) / "metadata.pkl")
        tfidf_path = str(Path(out_dir_to_use) / "tfidf_index.pkl")
        required_files = [clip_index_path, text_index_path, metadata_path, tfidf_path]
        missing_files = [f for f in required_files if not os.path.exists(f)]

        if missing_files:
            print(f"Error: Missing index files in {out_dir_to_use}:")
            for f in missing_files:
                print(f"  - {f}")
            print("Please run preprocessing first.")
            return

        searcher = HighAccuracyVideoSearcher(clip_index_path, text_index_path, metadata_path, tfidf_path)

        if args.keep_alive:
            print("High-accuracy search ready! Type queries (or 'quit' to exit):")
            while True:
                user_input = input("\n> ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    break
                if user_input:
                    results, counts, scores = searcher.query(user_input, args.top_k, caption_weight=0.4)
                    print(f"\nTop {len(results)} results:")
                    for i, result_path in enumerate(results):
                        print(
                            f"{i + 1}. {result_path} (frames: {counts[result_path]}, score: {scores[result_path]:.3f})")

        else:
            results, counts, scores = searcher.query(args.query, args.top_k, caption_weight=0.4)

            output_data = {
                "results": results,
                "counts": {k: int(v) for k, v in counts.items()},
                "scores": {k: float(v) for k, v in scores.items()}
            }

            print(json.dumps(output_data, indent=2))


if __name__ == "__main__":
    main()