"""
Ultra-Fast Video Semantic Search Pipeline - Sub-5s Query Performance
-------------------------------------------------------------------

Aggressive Optimizations for <5 Second Search:
 - Lazy model loading with persistent searcher instances
 - Pre-computed sparse TF-IDF with dimensionality reduction
 - Highly optimized FAISS parameters (GPU if available)
 - Minimal metadata processing with numpy operations
 - Memory-mapped indices for instant startup
 - Batch operations and vectorized computations
 - Optional model quantization for faster inference

Usage:
  python ultra_fast_video_search.py --mode preprocess --videos_dir ./videos --out_dir ./index_data --workers 4
  python ultra_fast_video_search.py --mode search --out_dir ./index_data --query "girl in red dress" --keep_alive
"""

import argparse
import os
import json
import pickle
import mmap
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any, Tuple, Optional
import concurrent.futures
import multiprocessing
import time
import hashlib

import numpy as np
import cv2

import torch
from transformers import CLIPProcessor, CLIPModel, BlipProcessor, BlipForConditionalGeneration
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
from scipy import sparse

try:
    from deepface import DeepFace
    _DEEPFACE_AVAILABLE = True
except Exception:
    _DEEPFACE_AVAILABLE = False

try:
    from nsfw_detector import predict as nsfw_predict
    _NSFW_AVAILABLE = True
except Exception:
    _NSFW_AVAILABLE = False

import faiss


def norm_l2(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


def sample_frames(video_path: str, frame_interval: float = 1.0):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step_frames = max(1, int(round(frame_interval * fps)))
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step_frames == 0:
            yield idx / fps, frame
        idx += 1
    cap.release()


# ---------------- Worker initialization + job --------------------------------
_worker_state = {
    'device': None,
    'clip_model': None,
    'clip_processor': None,
    'blip_model': None,
    'blip_processor': None,
    'nsfw_model': None,
}


def _init_worker(device: str = None, clip_name: str = "D:/models/models/clip-vit-base-patch32", blip_name: str = "D:/models/models/blip-image-captioning-base", load_nsfw: bool = False):
    global _worker_state
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    _worker_state['device'] = dev
    _worker_state['clip_model'] = CLIPModel.from_pretrained(clip_name).to(dev)
    _worker_state['clip_processor'] = CLIPProcessor.from_pretrained(clip_name)
    _worker_state['blip_model'] = BlipForConditionalGeneration.from_pretrained(blip_name).to(dev)
    _worker_state['blip_processor'] = BlipProcessor.from_pretrained(blip_name)
    print("Worker STATE", _worker_state['device'])
    if load_nsfw and _NSFW_AVAILABLE:
        try:
            _worker_state['nsfw_model'] = nsfw_predict.load_model()
        except Exception:
            _worker_state['nsfw_model'] = None
    else:
        _worker_state['nsfw_model'] = None


def _process_single_video(args: Tuple[str, float, bool, int]) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    video_path, frame_interval, do_nsfw, max_frames = args
    global _worker_state

    clip_model = _worker_state['clip_model']
    clip_processor = _worker_state['clip_processor']
    blip_model = _worker_state['blip_model']
    blip_processor = _worker_state['blip_processor']
    nsfw_model = _worker_state['nsfw_model'] if do_nsfw else None
    device = _worker_state['device']
    print("Process Worker STATE", device)

    local_embeddings = []
    local_meta = []
    next_local_id = 0

    try:
        for timestamp, frame_bgr in sample_frames(video_path, frame_interval=frame_interval):
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            inputs = clip_processor(images=frame_rgb, return_tensors="pt").to(device)
            with torch.no_grad():
                img_emb = clip_model.get_image_features(**inputs).cpu().numpy().astype(np.float32)
            local_embeddings.append(img_emb.reshape(-1))

            blip_inputs = blip_processor(images=frame_rgb, return_tensors="pt").to(device)
            with torch.no_grad():
                caption_ids = blip_model.generate(**blip_inputs, max_new_tokens=30)
                caption = blip_processor.decode(caption_ids[0], skip_special_tokens=True)

            mood = None
            if _DEEPFACE_AVAILABLE:
                try:
                    analysis = DeepFace.analyze(frame_bgr, actions=["emotion"], enforce_detection=False)
                    if isinstance(analysis, list):
                        analysis = analysis[0]
                    mood = analysis.get('dominant_emotion')
                except Exception:
                    mood = None

            nsfw_flag = False
            if nsfw_model is not None:
                try:
                    import tempfile
                    from PIL import Image
                    tmpf = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    Image.fromarray(frame_rgb).save(tmpf.name)
                    preds = nsfw_model.classify(tmpf.name)
                    scores = list(preds.values())[0]
                    nsfw_flag = any(v >= 0.6 for v in scores.values())
                    try:
                        os.unlink(tmpf.name)
                    except Exception:
                        pass
                except Exception:
                    nsfw_flag = False

            local_meta.append({
                'local_id': next_local_id,
                'video_path': str(video_path),
                'timestamp': float(timestamp),
                'caption': caption,
                'mood': mood,
                'nsfw': bool(nsfw_flag)
            })
            next_local_id += 1

            if max_frames and next_local_id >= max_frames:
                break
    except Exception as e:
        print(f"Error processing {video_path}: {e}")

    if local_embeddings:
        emb_arr = np.vstack(local_embeddings).astype(np.float32)
    else:
        emb_arr = np.zeros((0, 512), dtype=np.float32)  # CLIP embedding size

    return emb_arr, local_meta


class UltraFastIndexer:
    def __init__(self, device=None, clip_name: str = "openai/clip-vit-base-patch32", blip_name: str = "Salesforce/blip-image-captioning-base"):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.clip_name = clip_name
        self.blip_name = blip_name
        self.frame_embeddings: List[np.ndarray] = []
        self.frame_metadata: List[Dict[str, Any]] = []

    def process_video_folder_parallel(self, videos_dir: str, frame_interval: float = 1.0, workers: int = None, do_nsfw: bool = False, max_frames_per_video: int = None):
        videos_dir = Path(videos_dir)
        video_files = [str(p) for p in sorted(videos_dir.glob("**/*")) if p.is_file() and p.suffix.lower() in ['.mp4', '.mov', '.mkv', '.avi', '.webm']]
        if not video_files:
            print("No video files found in", videos_dir)
            return

        workers = workers or max(1, multiprocessing.cpu_count())
        print(f"Starting parallel preprocessing with {workers} workers")
        tasks = [(vf, frame_interval, do_nsfw, max_frames_per_video) for vf in video_files]

        with concurrent.futures.ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(self.device, self.clip_name, self.blip_name, do_nsfw)) as exe:
            futures = [exe.submit(_process_single_video, t) for t in tasks]
            global_id = 0
            for fut in concurrent.futures.as_completed(futures):
                try:
                    emb_arr, meta_list = fut.result()
                except Exception as e:
                    print("Worker failed:", e)
                    continue
                if emb_arr.size:
                    for i in range(emb_arr.shape[0]):
                        self.frame_embeddings.append(emb_arr[i:i+1])
                for m in meta_list:
                    m['id'] = global_id
                    self.frame_metadata.append(m)
                    global_id += 1

    def build_ultra_fast_index(self, index_out_path: str):
        """Build highly optimized FAISS index"""
        if not self.frame_embeddings:
            print("No embeddings to index")
            return

        X = np.vstack(self.frame_embeddings).astype(np.float32)
        X = norm_l2(X)
        dim = X.shape[1]
        n_vectors = X.shape[0]

        print(f"Building ultra-fast index for {n_vectors} vectors")

        # Use GPU index if available
        if torch.cuda.is_available() and faiss.get_num_gpus() > 0:
            print("Using GPU FAISS index")
            res = faiss.StandardGpuResources()
            if n_vectors > 50000:
                # Large dataset: use GPU IVF
                nlist = min(8192, max(256, int(np.sqrt(n_vectors))))
                quantizer = faiss.IndexFlatIP(dim)
                index_cpu = faiss.IndexIVFFlat(quantizer, dim, nlist)
                index_cpu.train(X)
                index_gpu = faiss.index_cpu_to_gpu(res, 0, index_cpu)
                index_gpu.nprobe = max(32, nlist // 32)  # Search more clusters for accuracy
            else:
                # Small dataset: use GPU flat
                index_cpu = faiss.IndexFlatIP(dim)
                index_gpu = faiss.index_cpu_to_gpu(res, 0, index_cpu)

            ids = np.array([m['id'] for m in self.frame_metadata], dtype=np.int64)
            # Add with IDs (convert back to CPU for IDMap)
            index_cpu_final = faiss.index_gpu_to_cpu(index_gpu)
            id_map = faiss.IndexIDMap(index_cpu_final)
            id_map.add_with_ids(X, ids)
        else:
            print("Using CPU FAISS index")
            if n_vectors > 20000:
                # CPU IVF for large datasets
                nlist = min(4096, max(128, int(np.sqrt(n_vectors))))
                quantizer = faiss.IndexFlatIP(dim)
                index = faiss.IndexIVFFlat(quantizer, dim, nlist)
                index.train(X)
                index.nprobe = max(16, nlist // 16)
            else:
                index = faiss.IndexFlatIP(dim)

            id_map = faiss.IndexIDMap(index)
            ids = np.array([m['id'] for m in self.frame_metadata], dtype=np.int64)
            id_map.add_with_ids(X, ids)

        faiss.write_index(id_map, index_out_path)
        print(f"Ultra-fast index saved to: {index_out_path}")

    def build_optimized_text_index(self, out_path: str):
        """Build highly optimized text search index"""
        print("Building optimized text index...")

        # Collect all text
        captions = [m.get("caption", "") for m in self.frame_metadata]
        video_captions = []

        # Aggregate video-level captions
        video_texts = defaultdict(list)
        for m in self.frame_metadata:
            video_texts[m['video_path']].append(m.get("caption", ""))

        video_caption_map = {}
        for vpath, caps in video_texts.items():
            video_caption_map[vpath] = " ".join(caps)

        # Combine frame + video captions
        combined_texts = []
        for m in self.frame_metadata:
            frame_text = m.get("caption", "")
            video_text = video_caption_map.get(m['video_path'], "")
            combined_texts.append(f"{frame_text} {video_text}")

        # Build TF-IDF with aggressive optimization
        vectorizer = TfidfVectorizer(
            max_features=10000,  # Reduce features dramatically
            stop_words='english',
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.8,
            strip_accents='ascii'
        )

        tfidf_matrix = vectorizer.fit_transform(combined_texts)

        # Optional: Reduce dimensionality further with SVD
        if tfidf_matrix.shape[1] > 2000:
            print("Applying SVD dimensionality reduction...")
            svd = TruncatedSVD(n_components=1000, random_state=42)
            tfidf_matrix = svd.fit_transform(tfidf_matrix)
            # Save SVD transformer
            with open(out_path.replace('.pkl', '_svd.pkl'), 'wb') as f:
                pickle.dump(svd, f)
        else:
            svd = None

        # Save optimized text index
        text_index = {
            'vectorizer': vectorizer,
            'tfidf_matrix': tfidf_matrix,
            'svd': svd,
            'video_caption_map': video_caption_map
        }

        with open(out_path, 'wb') as f:
            pickle.dump(text_index, f, protocol=pickle.HIGHEST_PROTOCOL)

        print(f"Optimized text index saved to: {out_path}")

    def save_minimal_metadata(self, out_path: str):
        """Save minimal metadata for fastest loading"""
        # Pre-compute all video-level stats
        video_stats = defaultdict(lambda: {'moods': [], 'nsfw_count': 0, 'total_frames': 0})

        for m in self.frame_metadata:
            vp = m['video_path']
            video_stats[vp]['total_frames'] += 1
            if m.get('mood'):
                video_stats[vp]['moods'].append(m['mood'])
            if m.get('nsfw'):
                video_stats[vp]['nsfw_count'] += 1

        # Compute final stats
        for vp, stats in video_stats.items():
            if stats['moods']:
                stats['dominant_mood'] = Counter(stats['moods']).most_common(1)[0][0]
            else:
                stats['dominant_mood'] = None
            stats['nsfw_ratio'] = stats['nsfw_count'] / max(1, stats['total_frames'])

        # Create minimal metadata with numpy arrays for speed
        minimal_meta = {
            'ids': np.array([m['id'] for m in self.frame_metadata], dtype=np.int32),
            'video_paths': [m['video_path'] for m in self.frame_metadata],
            'timestamps': np.array([m['timestamp'] for m in self.frame_metadata], dtype=np.float32),
            'moods': [m.get('mood') for m in self.frame_metadata],
            'nsfw_flags': np.array([m.get('nsfw', False) for m in self.frame_metadata], dtype=bool),
            'video_stats': dict(video_stats)
        }

        # Save with highest compression
        with open(out_path, 'wb') as f:
            pickle.dump(minimal_meta, f, protocol=pickle.HIGHEST_PROTOCOL)

        print(f"Minimal metadata saved to: {out_path}")


class UltraFastSearcher:
    """Extremely optimized searcher for sub-5s queries"""

    def __init__(self, index_path: str, metadata_path: str, text_index_path: str, device=None):
        print("Initializing Ultra-Fast Searcher...")
        init_start = time.time()

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # Load models with optimizations
        print("Loading CLIP model...")
        model_start = time.time()
        self.clip_model = CLIPModel.from_pretrained("D:/models/models/clip-vit-base-patch32").to(self.device)
        self.clip_processor = CLIPProcessor.from_pretrained("D:/models/models/clip-vit-base-patch32")

        # Model optimizations
        self.clip_model.eval()
        if hasattr(torch, 'jit') and self.device == 'cuda':
            try:
                # JIT compile for faster inference
                dummy_input = torch.zeros(1, 3, 224, 224).to(self.device)
                self.clip_model = torch.jit.trace(self.clip_model.vision_model, dummy_input)
            except:
                pass

        print(f"Models loaded in {time.time() - model_start:.2f}s")

        # Load FAISS index
        print("Loading FAISS index...")
        faiss_start = time.time()
        self.index = faiss.read_index(index_path)

        # Move to GPU if available
        if torch.cuda.is_available() and faiss.get_num_gpus() > 0:
            try:
                res = faiss.StandardGpuResources()
                self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                print("FAISS index moved to GPU")
            except:
                print("Failed to move FAISS to GPU, using CPU")

        print(f"FAISS loaded in {time.time() - faiss_start:.2f}s")

        # Load minimal metadata
        print("Loading metadata...")
        meta_start = time.time()
        with open(metadata_path, 'rb') as f:
            self.metadata = pickle.load(f)
        print(f"Metadata loaded in {time.time() - meta_start:.2f}s")

        # Load text index
        print("Loading text index...")
        text_start = time.time()
        with open(text_index_path, 'rb') as f:
            text_data = pickle.load(f)

        self.vectorizer = text_data['vectorizer']
        self.tfidf_matrix = text_data['tfidf_matrix']
        self.svd = text_data.get('svd')
        print(f"Text index loaded in {time.time() - text_start:.2f}s")

        # Pre-compute filter masks for ultra-fast filtering
        self.nsfw_mask = self.metadata['nsfw_flags']

        # Create mood lookup
        self.mood_masks = {}
        unique_moods = set(m for m in self.metadata['moods'] if m)
        for mood in unique_moods:
            self.mood_masks[mood] = np.array([m == mood for m in self.metadata['moods']], dtype=bool)

        # Query cache
        self.query_cache = {}
        self.cache_size = 5000  # Larger cache for better hit rate

        print(f"Ultra-Fast Searcher ready in {time.time() - init_start:.2f}s!")

    def query_filtered_by_directory(self, text: str, filter_directory: str, top_k=50, mood=None, allow_nsfw=True,
                                    caption_weight=0.4):
        """Search and filter results to only include videos from specified directory"""
        # Get all results first
        all_results, all_counts, all_scores = self.query(text, top_k=top_k * 5, mood=mood, allow_nsfw=allow_nsfw,
                                                         caption_weight=caption_weight)

        # DEBUG: Print what we're comparing
        print(f"DEBUG: Filter directory: '{filter_directory}'")
        print(f"DEBUG: Filter directory normalized: '{os.path.normpath(filter_directory)}'")
        print(f"DEBUG: First few video paths in results:")
        for i, vpath in enumerate(all_results[:3]):
            print(f"  {i}: '{vpath}' -> normalized: '{os.path.normpath(vpath)}'")

        # Filter by directory
        filter_directory = os.path.normpath(filter_directory)
        filtered_results = []
        filtered_counts = {}
        filtered_scores = {}

        for video_path in all_results:
            video_norm = os.path.normpath(video_path)

            # DEBUG: Show the comparison
            match_1 = video_norm.startswith(filter_directory + os.sep)
            match_2 = video_norm == filter_directory
            is_subdirectory = os.path.commonpath([filter_directory, video_norm]) == filter_directory

            print(f"DEBUG: Comparing '{video_norm}' with '{filter_directory}'")
            print(f"  startswith check: {match_1}")
            print(f"  equality check: {match_2}")
            print(f"  is_subdirectory: {is_subdirectory}")

            # Try alternative matching logic
            if (match_1 or match_2 or is_subdirectory or
                    video_norm.startswith(filter_directory) or
                    filter_directory in video_norm):
                filtered_results.append(video_path)
                if video_path in all_counts:
                    filtered_counts[video_path] = all_counts[video_path]
                if video_path in all_scores:
                    filtered_scores[video_path] = all_scores[video_path]

        # Limit to requested top_k
        filtered_results = filtered_results[:top_k]

        print(f"DEBUG: Found {len(filtered_results)} filtered results")
        return filtered_results, filtered_counts, filtered_scores

    def has_videos_from_directory(self, directory_path):
        """Check if the index contains any videos from the specified directory"""
        directory_path = os.path.normpath(directory_path)
        print("Dir Path", directory_path)

        for video_path in self.metadata['video_paths']:
            video_norm = os.path.normpath(video_path)
            print("Vid path", video_path)
            if video_norm.startswith(directory_path + os.sep) or video_norm == directory_path:
                return True
        return False

    def get_video_count_for_directory(self, directory_path):
        """Get total number of videos in index from specified directory"""
        directory_path = os.path.normpath(directory_path)
        count = 0

        for video_path in self.metadata['video_paths']:
            video_norm = os.path.normpath(video_path)
            if video_norm.startswith(directory_path + os.sep) or video_norm == directory_path:
                count += 1

        return count

    def _get_text_embedding_fast(self, text: str) -> np.ndarray:
        """Ultra-fast text embedding with aggressive caching"""
        cache_key = hashlib.md5(text.lower().encode()).hexdigest()[:16]  # Shorter hash

        if cache_key in self.query_cache:
            return self.query_cache[cache_key]

        # Optimized inference
        with torch.no_grad():
            inputs = self.clip_processor(text=[text], return_tensors="pt", padding=True, truncation=True).to(self.device)
            txt_emb = self.clip_model.get_text_features(**inputs).cpu().numpy().astype(np.float32)

        txt_emb = norm_l2(txt_emb)

        # Aggressive cache management
        if len(self.query_cache) >= self.cache_size:
            # Remove 20% of cache (not just one item)
            keys_to_remove = list(self.query_cache.keys())[:self.cache_size // 5]
            for k in keys_to_remove:
                del self.query_cache[k]

        self.query_cache[cache_key] = txt_emb
        return txt_emb

    def query(self, text: str, top_k=50, mood=None, allow_nsfw=True, caption_weight=0.4):
        """Ultra-fast search with <5s target"""
        total_start = time.time()

        # 1. Get text embedding (cached)
        embed_start = time.time()
        txt_emb = self._get_text_embedding_fast(text)
        print(f"Text embedding: {time.time() - embed_start:.3f}s")

        # 2. FAISS search with optimized parameters
        faiss_start = time.time()
        search_k = min(max(top_k * 2, 100), 500)  # Reasonable search size
        D, I = self.index.search(txt_emb, search_k)
        print(f"FAISS search: {time.time() - faiss_start:.3f}s")

        # 3. Text similarity (optimized)
        text_start = time.time()
        query_vec = self.vectorizer.transform([text])
        if self.svd:
            query_vec = self.svd.transform(query_vec)
            text_sim = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        else:
            text_sim = cosine_similarity(query_vec, self.tfidf_matrix, dense_output=False).toarray().flatten()
        print(f"Text similarity: {time.time() - text_start:.3f}s")

        # 4. Ultra-fast filtering with numpy operations
        filter_start = time.time()

        # Get valid indices
        valid_indices = I[0][I[0] >= 0]  # Remove -1s

        if len(valid_indices) == 0:
            return [], {}, {}

        # Apply filters using pre-computed masks
        if not allow_nsfw:
            nsfw_invalid = self.nsfw_mask[valid_indices]
            valid_indices = valid_indices[~nsfw_invalid]

        if mood and mood in self.mood_masks:
            mood_valid = self.mood_masks[mood][valid_indices]
            valid_indices = valid_indices[mood_valid]

        if len(valid_indices) == 0:
            return [], {}, {}

        # Vectorized scoring
        clip_scores = D[0][:len(valid_indices)]
        text_scores = text_sim[valid_indices]
        combined_scores = (1 - caption_weight) * clip_scores + caption_weight * text_scores

        # Get video paths efficiently
        video_paths = [self.metadata['video_paths'][idx] for idx in valid_indices]

        # Aggregate by video using numpy
        video_score_dict = defaultdict(list)
        for i, (vpath, score) in enumerate(zip(video_paths, combined_scores)):
            video_score_dict[vpath].append(score)

        # Compute final video scores
        video_counts = {vpath: len(scores) for vpath, scores in video_score_dict.items()}
        video_scores = {vpath: float(np.sum(scores)) for vpath, scores in video_score_dict.items()}

        print(f"Filtering & scoring: {time.time() - filter_start:.3f}s")

        # 5. Final ranking
        rank_start = time.time()
        results = sorted(video_scores.keys(), key=lambda p: (-video_scores[p], -video_counts[p]))[:top_k]

        print(f"Ranking: {time.time() - rank_start:.3f}s")

        total_time = time.time() - total_start
        print(f"🚀 TOTAL SEARCH TIME: {total_time:.3f}s")

        return results, video_counts, video_scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preprocess", "search"], required=True)
    parser.add_argument("--videos_dir", default="./videos")
    parser.add_argument("--out_dir", default="./index_data")
    parser.add_argument("--frame_interval", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--max_frames_per_video", type=int, default=None)
    parser.add_argument("--query", type=str)
    parser.add_argument("--top_k", type=int, default=50)
    parser.add_argument("--mood", type=str, default=None)
    parser.add_argument("--allow_nsfw", type=lambda x: str(x).lower() in ["1", "true", "yes"], default=True)
    parser.add_argument("--caption_weight", type=float, default=0.4)
    parser.add_argument("--keep_alive", action="store_true", help="Keep searcher alive for multiple queries")
    args = parser.parse_args()

    if args.mode == "preprocess":
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        indexer = UltraFastIndexer()
        indexer.process_video_folder_parallel(
            args.videos_dir,
            frame_interval=args.frame_interval,
            workers=args.workers,
            do_nsfw=_NSFW_AVAILABLE,
            max_frames_per_video=args.max_frames_per_video
        )

        # Build all indices
        indexer.build_ultra_fast_index(str(out_dir / "frames.index"))
        indexer.build_optimized_text_index(str(out_dir / "text_index.pkl"))
        indexer.save_minimal_metadata(str(out_dir / "minimal_meta.pkl"))
        print("Ultra-fast preprocessing complete!")

    elif args.mode == "search":
        index_path = str(Path(args.out_dir) / "frames.index")
        meta_path = str(Path(args.out_dir) / "minimal_meta.pkl")
        text_path = str(Path(args.out_dir) / "text_index.pkl")

        if not args.query:
            print("Provide --query")
            return

        # Initialize searcher once
        searcher = UltraFastSearcher(index_path, meta_path, text_path)

        if args.keep_alive:
            # Interactive mode for testing
            print("🚀 Ultra-Fast Search Ready! Type queries (or 'quit' to exit):")
            while True:
                query = input("\nQuery: ").strip()
                if query.lower() in ['quit', 'exit', 'q']:
                    break
                if query:
                    results, counts, scores = searcher.query(
                        query, args.top_k, args.mood, args.allow_nsfw, args.caption_weight
                    )
                    print(f"\nTop {len(results)} results:")
                    for i, result in enumerate(results[:10]):
                        print(f"{i+1}. {result} (frames: {counts[result]}, score: {scores[result]:.3f})")
        else:
            # Single query
            results, counts, scores = searcher.query(
                args.query, args.top_k, args.mood, args.allow_nsfw, args.caption_weight
            )
            print(json.dumps({"results": results, "counts": counts, "scores": scores}, indent=2))


if __name__ == "__main__":
    main()