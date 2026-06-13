"""
High-Accuracy Video Semantic Search with Smart Resource Management
+ AI-Powered Natural Language Query Parser (Hybrid Rule-Based + Qwen2.5-0.5B)
------------------------------------------------------------------------------

Maintains accuracy while solving resource issues:
- Sequential model loading to prevent memory overflow
- Batch processing with memory management
- Multi-modal ensemble scoring (SigLIP + BLIP + mxbai text similarity)
- Scene-aware frame sampling with perceptual hash deduplication
- BM25 sparse retrieval
- Cross-encoder reranking

AI Query Parser (two-tier, RULE-PRIMARY):
- Tier 1 (PRIMARY): Rule-based regex+keyword parser — accurate for structured queries
- Tier 2 (FALLBACK): Qwen2.5-0.5B-Instruct on GPU — handles complex unstructured language
- No content filtering — parses all queries faithfully
- Per-video metadata extraction (duration, file size, resolution, etc.)
- /search/ai endpoint for natural language filters/sorting
- Automatic fallback to semantic search if parsing fails
"""

import argparse
import os
import json
import pickle
import gc
import subprocess
import sys
import threading
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any, Tuple, Optional
import concurrent.futures
import psutil

import numpy as np
import cv2

import torch
import re

from sentence_transformers import SentenceTransformer, CrossEncoder
from transformers import (
    SiglipModel, SiglipProcessor,
    BlipProcessor, BlipForConditionalGeneration,
    AutoTokenizer, AutoModelForCausalLM,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.corpus import wordnet
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from rank_bm25 import BM25Okapi
import imagehash
from PIL import Image as PILImage

import faiss
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import uvicorn

MODEL_SIGLIP   = "google/siglip-so400m-patch14-384"
MODEL_BLIP = "Salesforce/blip-image-captioning-large"
MODEL_EMBED    = "mixedbread-ai/mxbai-embed-large-v1"
MODEL_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"

SIGLIP_DIM = 1152
EMBED_DIM  = 1024

_NLTK_RESOURCES = {
    'tokenizers/punkt_tab': 'punkt_tab',
    'corpora/wordnet': 'wordnet',
    'taggers/averaged_perceptron_tagger': 'averaged_perceptron_tagger',
}
for _path, _pkg in _NLTK_RESOURCES.items():
    try:
        nltk.data.find(_path)
    except LookupError:
        nltk.download(_pkg, quiet=True)

_api_searcher = None
_server_out_dir: str = ""   # set at --mode server startup

# ── Preprocessing state ──────────────────────────────────────────────────────
# Shared between the /index/* endpoints and the background subprocess thread.
_preprocess_lock = threading.Lock()
_preprocess_state: dict = {
    "running": False,
    "pending_lines": [],   # lines not yet polled by client
    "done": False,
    "success": False,
    "error": None,
    "_process": None,      # subprocess.Popen handle
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=_lifespan)


@app.get("/status")
async def api_status():
    """Lightweight readiness probe — polled by AIServerBridge at startup."""
    global _api_searcher
    if _api_searcher is None:
        return {"status": "no_index"}
    try:
        unique_videos = len(set(_api_searcher.metadata["video_paths"]))
        device = str(_api_searcher.device)
    except Exception:
        unique_videos = 0
        device = "unknown"
    return {"status": "ready", "device": device, "video_count": unique_videos}


@app.post("/search")
async def api_search(req: Request):
    global _api_searcher
    payload = await req.json()
    query_text = payload.get("query", "").strip()
    top_k = int(payload.get("top_k", 20))
    directory = payload.get("directory")
    qid = payload.get("_qid")
    try:
        if directory:
            results, counts, scores = _api_searcher.query_filtered_by_directory(
                query_text, directory, top_k, caption_weight=0.4
            )
        else:
            results, counts, scores = _api_searcher.query(
                query_text, top_k, caption_weight=0.4
            )

        results = [r for r in results if os.path.isfile(r)]
        result_set = set(results)
        counts = {k: v for k, v in counts.items() if k in result_set}
        scores = {k: v for k, v in scores.items() if k in result_set}

        # ----- DEBUG PRINT START -----
        print(f"\n[SEARCH] Query: '{query_text}', top_k={top_k}, directory={directory}")
        searcher = _api_searcher
        for rank, (path, score) in enumerate(
            sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k], start=1
        ):
            cnt = counts.get(path, 0)
            meta = searcher.video_metadata.get(path, {})
            dur = meta.get('duration', 0)
            size_mb = meta.get('file_size', 0) / (1024 * 1024)
            res = meta.get('resolution', (0, 0))
            fps_val = meta.get('fps', 0)
            total_frames_val = meta.get('total_frames', 0)
            ext = meta.get('extension', '')
            dir_ = meta.get('directory', '')
            print(f"  #{rank}: {path}")
            print(f"        score={score:.4f}  frames_matched={cnt}  dir='{dir_}'  "
                  f"size={size_mb:.1f}MB  dur={dur:.1f}s  "
                  f"res={res[0]}x{res[1]}  fps={fps_val:.1f}  total_frames={total_frames_val}  ext={ext}")
        print("---")
        # ----- DEBUG PRINT END -----

        response = {
            "results": results,
            "counts": counts,
            "scores": {k: float(v) for k, v in scores.items()},
        }
        if qid is not None:
            response["_qid"] = qid
        return response
    except Exception as exc:
        return {"error": str(exc), "results": [], "counts": {}, "scores": {}}


# ── Indexing (preprocessing) endpoints ──────────────────────────────────────

@app.post("/index/start")
async def api_index_start(req: Request):
    """Start preprocessing in a background subprocess. Non-blocking."""
    global _preprocess_state, _preprocess_lock
    payload = await req.json()
    with _preprocess_lock:
        if _preprocess_state["running"]:
            return {"status": "already_running"}
        _preprocess_state.update({
            "running": True,
            "pending_lines": [],
            "done": False,
            "success": False,
            "error": None,
            "_process": None,
        })
    threading.Thread(
        target=_run_preprocess_subprocess, args=(payload,), daemon=True
    ).start()
    return {"status": "started"}


@app.get("/index/status")
async def api_index_status():
    """Poll preprocessing progress. Lines are consumed (cleared) on each call."""
    global _preprocess_state, _preprocess_lock
    with _preprocess_lock:
        lines = list(_preprocess_state["pending_lines"])
        _preprocess_state["pending_lines"].clear()
        return {
            "running": _preprocess_state["running"],
            "lines": lines,
            "done": _preprocess_state["done"],
            "success": _preprocess_state["success"],
            "error": _preprocess_state["error"],
        }


@app.post("/index/cancel")
async def api_index_cancel():
    """Terminate a running preprocessing subprocess."""
    global _preprocess_state, _preprocess_lock
    proc = _preprocess_state.get("_process")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    with _preprocess_lock:
        _preprocess_state.update({
            "running": False,
            "done": True,
            "success": False,
            "error": "cancelled",
        })
    return {"status": "cancelled"}


@app.post("/index/reload")
async def api_index_reload(req: Request):
    """Reload the in-memory searcher after a new index has been built."""
    global _api_searcher, _server_out_dir
    payload = await req.json()
    out_dir = payload.get("out_dir") or _server_out_dir
    clip_path  = str(Path(out_dir) / "clip_index.faiss")
    text_path  = str(Path(out_dir) / "text_index.faiss")
    meta_path  = str(Path(out_dir) / "metadata.pkl")
    tfidf_path = str(Path(out_dir) / "tfidf_index.pkl")
    missing = [f for f in [clip_path, text_path, meta_path, tfidf_path]
               if not os.path.exists(f)]
    if missing:
        return {"status": "no_index", "error": f"Missing files: {missing}"}
    try:
        _api_searcher = HighAccuracyVideoSearcher(
            clip_path, text_path, meta_path, tfidf_path
        )
        unique_videos = len(set(_api_searcher.metadata["video_paths"]))
        device = str(_api_searcher.device)
        return {"status": "reloaded", "device": device, "video_count": unique_videos}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Rule-Based Query Parser (Tier 1 — PRIMARY) ──────────────────────────────
class RuleBasedQueryParser:
    """Rule‑based parser, now the primary tier. Highly accurate for structured
    video‑search queries. Extended with filename/name filters and other patterns."""

    _SIZE_MULTIPLIERS = {
        'b': 1, 'byte': 1, 'bytes': 1,
        'kb': 1024, 'kilobyte': 1024, 'kilobytes': 1024,
        'mb': 1024**2, 'megabyte': 1024**2, 'megabytes': 1024**2,
        'gb': 1024**3, 'gigabyte': 1024**3, 'gigabytes': 1024**3,
        'tb': 1024**4, 'terabyte': 1024**4, 'terabytes': 1024**4,
    }

    _DURATION_MULTIPLIERS = {
        's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
        'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
    }

    _RESOLUTION_MAP = {
        '480p': (854, 480), 'sd': (854, 480),
        '720p': (1280, 720), 'hd': (1280, 720),
        '1080p': (1920, 1080), 'fullhd': (1920, 1080), 'full hd': (1920, 1080), 'fhd': (1920, 1080),
        '1440p': (2560, 1440), '2k': (2560, 1440), 'qhd': (2560, 1440),
        '4k': (3840, 2160), 'uhd': (3840, 2160), '2160p': (3840, 2160),
        '8k': (7680, 4320), '4320p': (7680, 4320),
    }

    _SORT_PATTERNS = {
        'duration':  r'\b(longest|shortest|duration|length)\b',
        'file_size': r'\b(biggest|smallest|largest|heaviest|lightest|file.?size)\b',
        'resolution': r'\b(highest.?res|lowest.?res|resolution|most.?pixels)\b',
        'fps':       r'\b(highest.?fps|lowest.?fps|framerate|frame.?rate|smoothest)\b',
        'frames':    r'\b(most.?frames|fewest.?frames|frame.?count)\b',
    }

    _EXTENSIONS = {
        'mp4', 'mkv', 'avi', 'mov', 'webm', 'wmv', 'flv', 'm4v', '3gp', 'ogv',
    }

    # Confidence heuristics – if any of these conditions is true, the parse is
    # considered uncertain and we return None (fallback to LLM).
    _LOW_CONFIDENCE_PATTERNS = [
        re.compile(r'\bcontaining\s*$', re.IGNORECASE),  # search_text is only "containing"
        re.compile(r'^\d{4}$'),                          # search_text is a year
        re.compile(r'^[a-z]$', re.IGNORECASE),           # single letter
    ]

    def parse(self, query: str) -> Optional[dict]:
        """Attempt to parse the query with rules. Returns dict or None if uncertain."""
        q = query.strip()
        if not q:
            return None
        ql = q.lower()

        intent = None
        sort_by = "none"
        order = "desc"
        filters = []
        top_k = 10
        search_text = ""
        used_quoted = set()
        filter_phrase = ""

        top_k_explicit = False  # NEW: track whether user gave a number

        # ── 1. Extract top_k ──────────────────────────────────────────────
        tk_match = re.search(
            r'\b(?:top|first|show\s+(?:me\s+)?|give\s+(?:me\s+)?|find\s+|get\s+|need\s+)(\d+)\b', ql
        )
        if tk_match:
            top_k = int(tk_match.group(1))
            top_k_explicit = True
        else:
            tk_match2 = re.search(
                r'\b(?:only\s+|just\s+)?(\d+)\s+(?:videos?|files?|results?|clips?)\b', ql
            )
            if tk_match2:
                top_k = int(tk_match2.group(1))
                top_k_explicit = True
            else:
                tk_match3 = re.search(
                    r'\b(?:show|give|get|find|fetch|list|want|need)\b.{0,30}\b(\d+)\b', ql
                )
                if tk_match3:
                    top_k = int(tk_match3.group(1))
                    top_k_explicit = True
                else:
                    bare_num = re.match(r'^(\d+)\s+(.+)', ql)
                    if bare_num:
                        candidate_num = int(bare_num.group(1))
                        if not filters and candidate_num > 0:
                            top_k = candidate_num
                            top_k_explicit = True
                            ql = bare_num.group(2).strip()
                            sub_parse = self.parse(ql)
                            if sub_parse:
                                sub_parse['top_k'] = top_k
                                return sub_parse

        # ── 1b. “all videos” – only override top_k if no explicit number ──
        if (not top_k_explicit
                and re.search(r'\b(?:all|every|whole)\s+(?:the\s+)?(?:indexed\s+)?videos?\b',
                              ql, re.IGNORECASE)):
            top_k = 1000000  # sentinel for “return everything”
            intent = "metadata_filter"
            ql = re.sub(r'\b(?:all|every|whole)\s+(?:the\s+)?(?:indexed\s+)?videos?\b',
                        '', ql, flags=re.IGNORECASE)
            if not ql.strip():
                return {
                    "intent": intent,
                    "sort_by": "none",
                    "order": "desc",
                    "filters": [],
                    "top_k": top_k,
                    "search_text": "",
                }

        # ── 2. Detect sort intent ─────────────────────────────────────────
        for field, pattern in self._SORT_PATTERNS.items():
            if re.search(pattern, ql):
                sort_by = field
                intent = "metadata_sort"
                if re.search(r'\b(shortest|smallest|lightest|lowest|fewest|least|asc)\b', ql):
                    order = "asc"
                else:
                    order = "desc"
                break

        # ── 3. Size filters ───────────────────────────────────────────────
        size_patterns = [
            (r'(?:over|above|greater\s+than|more\s+than|bigger\s+than|larger\s+than|exceeding|>)\s*'
             r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'gt'),
            (r'(?:under|below|less\s+than|smaller\s+than|lighter\s+than|<)\s*'
             r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lt'),
            (r'(?:at\s+least|minimum|min)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'gte'),
            (r'(?:at\s+most|maximum|max)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lte'),
        ]
        for pattern, op in size_patterns:
            m = re.search(pattern, ql)
            if m:
                val_str, unit_str = m.group(1), m.group(2).lower().rstrip('s')
                unit_key = unit_str if unit_str in self._SIZE_MULTIPLIERS else unit_str + 's'
                if unit_key in self._SIZE_MULTIPLIERS or unit_str in self._SIZE_MULTIPLIERS:
                    multiplier = self._SIZE_MULTIPLIERS.get(unit_str,
                                                            self._SIZE_MULTIPLIERS.get(unit_key, 0))
                    if multiplier > 1:
                        value = float(val_str) * multiplier
                        filters.append({"field": "file_size", "operator": op, "value": value})
                        if intent is None:
                            intent = "metadata_filter"

        # ── 4. Duration filters (including "no longer than") ──────────────
        dur_patterns = [
            (r'(?:longer|more)\s+than\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'gt'),
            (r'(?:shorter|less)\s+than\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lt'),
            (r'(?:no\s+longer\s+than)\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lte'),
            (r'(?:over|above|>)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'gt'),
            (r'(?:under|below|<)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lt'),
            (r'(?:at\s+least|minimum)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'gte'),
            (r'(?:at\s+most|maximum)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)', 'lte'),
        ]
        for pattern, op in dur_patterns:
            m = re.search(pattern, ql)
            if m:
                val_str, unit_str = m.group(1), m.group(2).lower()
                if unit_str in self._DURATION_MULTIPLIERS:
                    value = float(val_str) * self._DURATION_MULTIPLIERS[unit_str]
                    if not any(f['field'] == 'duration' for f in filters):
                        filters.append({"field": "duration", "operator": op, "value": value})
                        if intent is None:
                            intent = "metadata_filter"

        # ── 5. Directory / path filter ───────────────────────────────────
        dir_syn = r'(?:directory|folder|dir|path)'
        dir_verb = r'(?:contains?|containing|with|has|named?|includes?|including)'

        dir_match_obj = re.search(
            rf'{dir_syn}\s+{dir_verb}\s+["\']([^"\']{{2,}})["\']', ql
        )
        if not dir_match_obj:
            dir_match_obj = re.search(
                rf'{dir_syn}\s+{dir_verb}\s+(.+)', ql
            )
        if dir_match_obj:
            full_match = dir_match_obj.group(0)
            raw_val = dir_match_obj.group(1).strip()
            dir_name = re.sub(r'[.\s]+$', '', raw_val)
            if dir_name and len(dir_name) > 1:
                filters.append({"field": "directory", "operator": "contains", "value": dir_name})
                used_quoted.add(dir_name)
                if intent is None:
                    intent = "metadata_filter"
                filter_phrase += ' ' + full_match
        else:
            dir_match = re.search(
                r'(?:in(?:\s+the)?|from(?:\s+the)?|inside(?:\s+the)?)\s+'
                r'["\']?([\w\s.-]+?)["\']?\s+(?:folder|directory|dir|path)',
                ql
            )
            if not dir_match:
                dir_match = re.search(
                    rf'(?:folder|directory|dir)\s+(?:named?|called?)?\s*["\']?([\w\s.-]+?)["\']?(?:\s|$)',
                    ql
                )
            if dir_match:
                full_match = dir_match.group(0)
                dir_name = dir_match.group(1).strip()
                if dir_name and len(dir_name) > 1:
                    filters.append({"field": "directory", "operator": "contains", "value": dir_name})
                    if intent is None:
                        intent = "metadata_filter"
                    filter_phrase += ' ' + full_match

        # ── 6. Extension filter ───────────────────────────────────────────
        ext_match = re.search(
            r'\b(?:that\s+are|only|format|type|extension)\s+\.?(' +
            '|'.join(self._EXTENSIONS) + r')\b', ql
        )
        if not ext_match:
            ext_match = re.search(
                r'\b\.?(' + '|'.join(self._EXTENSIONS) + r')\s+(?:files?|videos?|clips?)\b', ql
            )
        if not ext_match:
            ext_match = re.search(
                r'\b(' + '|'.join(self._EXTENSIONS) + r')\s+(?:videos?|files?|clips?)\b', ql
            )
        if ext_match:
            ext = ext_match.group(1).lower()
            if not ext.startswith('.'):
                ext = '.' + ext
            filters.append({"field": "extension", "operator": "eq", "value": ext})
            if intent is None:
                intent = "metadata_filter"

        # ── 7. Resolution filter (enhanced with strict inequality) ────────
        for alias, (w, h) in self._RESOLUTION_MAP.items():
            if alias in ql:
                filters.append({"field": "resolution_height", "operator": "gte", "value": h})
                if intent is None:
                    intent = "metadata_filter"
                break
        if re.search(r'\b(high\s?quality|hq)\b', ql):
            filters.append({"field": "resolution_height", "operator": "gte", "value": 720})
            if intent is None:
                intent = "metadata_filter"

        res_match = re.search(r'resolution\s+(?:higher|greater|more)\s+than\s+(\d{3,4})p', ql)
        if res_match:
            height = int(res_match.group(1))
            filters = [f for f in filters if f.get('field') != 'resolution_height']
            filters.append({"field": "resolution_height", "operator": "gt", "value": height})
            if intent is None:
                intent = "metadata_filter"

        # ── 8. Filename/name filter ───────────────────────────────────────
        name_match = re.search(
            r'(?:file|video|clip)\s+(?:named?|called?)\s+["\']([^"\']+)["\']', ql
        )
        if not name_match:
            name_match = re.search(
                r'(?:file|video|clip)\s+(?:named?|called?)\s+(\w+)', ql
            )
        if not name_match:
            name_match = re.search(
                r'name\s+(?:contains?|with|has)\s+["\']([^"\']+)["\']', ql
            )
        if not name_match:
            name_match = re.search(
                r'name\s+(?:contains?|with|has)\s+(\w+)', ql
            )
        if not name_match:
            name_match = re.search(
                r'(?:videos?|files?)\s+with\s+["\']([^"\']+)["\']\s+in\s+the\s+name', ql
            )
        if not name_match:
            name_match = re.search(
                r'(?:videos?|files?)\s+with\s+(\w+)\s+in\s+the\s+name', ql
            )
        if name_match:
            fname = name_match.group(1).strip()
            if fname:
                filters.append({"field": "filename", "operator": "contains", "value": fname})
                if intent is None:
                    intent = "metadata_filter"

        # ── 9. Content remnant extraction (enhanced) ─────────────────────
        if filter_phrase:
            ql_clean = ql
            for phrase in filter_phrase.strip().split('  '):
                if phrase.strip():
                    ql_clean = ql_clean.replace(phrase.strip(), ' ')
        else:
            ql_clean = ql

        content_remnant = ql_clean
        remove_patterns = [
            r'\b(?:i\s+want\s+(?:you\s+(?:to\s+)?)?|please\s+|could\s+you\s+|can\s+you\s+)(?:give|show|find|get|fetch|list|provide)?\s*(?:me\s+)?',
            r'\b(?:need\s+all\s+|need\s+|want\s+all\s+|want\s+)',
            r'\b(?:show|find|get|give|search|look|display|list|fetch|provide)\s+(?:me\s+)?',
            r'\b(?:me|the|my|for|a|an|and|or|with|that|are|is|of|to|in|from|by|be|it|its|only|just|all|any|some|every|each|which|where|when|how|what|who|only|inside|named|called)\b',
            r'\b(?:top|first|videos?|files?|clips?|results?|folder|directory|dir|path|file|video|clip|name)\b',
            r'\b(?:contains?|containing|includes?|including)\b',
            r'\b(?:over|under|above|below|more|less|than|at|least|most|longer|shorter|bigger|smaller|no\s+longer)\b',
            r'\b(?:longest|shortest|biggest|smallest|largest|heaviest|lightest|highest|lowest)\b',
            r'\b(?:resolution|duration|length|size|fps|framerate|frames?|high\s?quality|hq)\b',
            r'\b(?:' + '|'.join(self._EXTENSIONS) + r')\b',
            r'\d+(?:\.\d+)?\s*(?:' + '|'.join(
                list(self._SIZE_MULTIPLIERS.keys()) + list(self._DURATION_MULTIPLIERS.keys())) + r')\b',
            r'\d+',
        ]
        for pat in remove_patterns:
            content_remnant = re.sub(pat, ' ', content_remnant, flags=re.IGNORECASE)

        filter_related_words = {
            'more', 'less', 'higher', 'lower', 'longer', 'shorter',
            'bigger', 'smaller', 'heavier', 'lighter', 'larger', 'smaller',
            'greater', 'above', 'below', 'over', 'under', 'at least', 'at most',
            'minimum', 'maximum', 'higher than', 'lower than', 'combined',
            'combine', 'merge', 'both', 'together', 'including', 'excluding',
            'respectively', 'etc'
        }
        for word in filter_related_words:
            content_remnant = re.sub(rf'\b{re.escape(word)}\b', ' ', content_remnant, flags=re.IGNORECASE)

        content_remnant = re.sub(r'\s+', ' ', content_remnant).strip()

        quotes = re.findall(r'["\']([^"\']{2,})["\']', q)
        for quote_val in quotes:
            if quote_val not in used_quoted and quote_val not in content_remnant:
                content_remnant += ' ' + quote_val

        content_remnant = re.sub(r"""['"\s]+""", ' ', content_remnant).strip()
        content_remnant = re.sub(r'\b[a-z]\b', '', content_remnant).strip()
        content_remnant = re.sub(r'\s+', ' ', content_remnant).strip()

        if len(content_remnant) > 3:
            search_text = content_remnant
            if intent == "metadata_filter" or intent == "metadata_sort":
                intent = "combined"
            elif intent is None:
                intent = "content_search"

        # ── 10. Confidence checks ────────────────────────────────────────
        if intent is None and not filters and sort_by == "none" and not search_text:
            return None

        if search_text and any(pat.search(search_text) for pat in self._LOW_CONFIDENCE_PATTERNS):
            return None

        if intent is None:
            if search_text:
                intent = "content_search"
            elif filters:
                intent = "metadata_filter"
            else:
                intent = "content_search"

        result = {
            "intent": intent,
            "sort_by": sort_by,
            "order": order,
            "filters": filters,
            "top_k": top_k,
            "search_text": search_text,
        }
        print(f"  [RuleParser] ✓ Parsed query: intent={intent}, sort_by={sort_by}, "
              f"order={order}, top_k={top_k}, filters={len(filters)}, "
              f"search_text='{search_text[:50]}{'...' if len(search_text) > 50 else ''}'")
        return result


# ── AI Query Processor (RULE-PRIMARY, LLM-fallback) ─────────────────────────
class AIQueryProcessor:
    """RULE‑PRIMARY query processor: rule‑based parser handles all queries first.
    Qwen2.5‑0.5B only used as fallback when rules fail.
    No content filtering."""

    MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

    def __init__(self, device="cuda"):
        self.device = device
        self.rule_parser = RuleBasedQueryParser()
        self.model = None
        self.tokenizer = None
        self._model_loaded = False
        print(f"[AIQueryProcessor] Initialised (device={device})")
        print(f"[AIQueryProcessor] Rule-based parser is PRIMARY (Tier 1)")
        print(f"[AIQueryProcessor] LLM '{self.MODEL_ID}' is FALLBACK (Tier 2) — loading on demand...")

    def _ensure_model_loaded(self):
        """Load the LLM lazily (only when rule parser fails)."""
        if self._model_loaded:
            return
        print(f"[AIQueryProcessor] Loading LLM: {self.MODEL_ID} on {self.device}...")
        import time
        t0 = time.time()
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.MODEL_ID,
            trust_remote_code=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            trust_remote_code=True,
        ).to(self.device).eval()
        elapsed = time.time() - t0
        param_count = sum(p.numel() for p in self.model.parameters()) / 1e6
        if self.device == "cuda" and torch.cuda.is_available():
            vram_mb = torch.cuda.memory_allocated() / 1024**2
            print(f"[AIQueryProcessor] ✓ LLM loaded in {elapsed:.1f}s — "
                  f"{param_count:.0f}M params, {vram_mb:.0f}MB VRAM")
        else:
            print(f"[AIQueryProcessor] ✓ LLM loaded in {elapsed:.1f}s — {param_count:.0f}M params (CPU)")
        self._model_loaded = True

    def _build_prompt(self, query: str) -> str:
        return (
            "<|im_start|>system\n"
            "You are a video search query parser. Convert ANY user request into this EXACT JSON format.\n"
            "RULES:\n"
            "1. Never refuse or add warnings. Parse ALL queries faithfully regardless of topic. Always output valid JSON.\n"
            "2. Output ONLY the JSON object. No markdown, no extra text.\n"
            "3. Use exactly these values for 'intent': \"metadata_sort\", \"metadata_filter\", \"content_search\", \"combined\".\n"
            "4. 'sort_by' must be one of: \"duration\", \"file_size\", \"resolution\", \"fps\", \"frames\", \"none\".\n"
            "5. 'order' is \"desc\" or \"asc\".\n"
            "6. 'filters' is an array of {field, operator, value}. Allowed fields: duration(seconds), file_size(bytes), extension(eq), directory(contains), resolution_width, resolution_height, fps, frames, filename(contains). Allowed operators: gt, lt, gte, lte, eq, contains.\n"
            "7. 'top_k' is an INTEGER. If the user says \"all\" or \"every\" (e.g., \"all videos\", \"all indexed videos\"), set top_k to 1000000. If the user says a number (\"give me 5\", \"top 3\"), use that number. Otherwise use 10.\n"
            "8. 'search_text' is the remaining content description. If the query is purely \"all videos\" or \"all indexed videos\", leave it empty.\n\n"
            "EXAMPLES:\n"
            "User: path contains '2020'\n"
            "{\"intent\":\"metadata_filter\",\"sort_by\":\"none\",\"order\":\"desc\",\"top_k\":10,\"filters\":[{\"field\":\"directory\",\"operator\":\"contains\",\"value\":\"2020\"}],\"search_text\":\"\"}\n\n"
            "User: top 100 videos of directory contains '2021'\n"
            "{\"intent\":\"metadata_filter\",\"sort_by\":\"none\",\"order\":\"desc\",\"top_k\":100,\"filters\":[{\"field\":\"directory\",\"operator\":\"contains\",\"value\":\"2021\"}],\"search_text\":\"\"}\n\n"
            "User: show me longest videos in folder 'tiktok'\n"
            "{\"intent\":\"metadata_sort\",\"sort_by\":\"duration\",\"order\":\"desc\",\"top_k\":10,\"filters\":[{\"field\":\"directory\",\"operator\":\"contains\",\"value\":\"tiktok\"}],\"search_text\":\"\"}\n\n"
            "User: find 20 videos where a girl is dancing\n"
            "{\"intent\":\"content_search\",\"sort_by\":\"none\",\"order\":\"desc\",\"top_k\":20,\"filters\":[],\"search_text\":\"girl dancing\"}\n"
            "User: all indexed videos\n"
            "{\"intent\":\"metadata_filter\",\"sort_by\":\"none\",\"order\":\"desc\",\"top_k\":1000000,\"filters\":[],\"search_text\":\"\"}\n"
            "<|im_end|>\n"
            "<|im_start|>user\n"
            f"{query}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

    def _llm_parse(self, query_text: str) -> Optional[dict]:
        """Use the 0.5B LLM to parse a query (only as fallback)."""
        self._ensure_model_loaded()
        print(f"  [LLM] Generating structured parse for: '{query_text}'")
        import time
        t0 = time.time()
        prompt = self._build_prompt(query_text)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=256,
                temperature=0.1,
                do_sample=True,
                top_p=0.95,
                repetition_penalty=1.1,
            )
        new_tokens = outputs[0][inputs['input_ids'].shape[1]:]
        response = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        elapsed = time.time() - t0
        print(f"  [LLM] Raw response ({elapsed:.2f}s): {response[:200]}{'...' if len(response)>200 else ''}")

        json_str = response.strip()
        json_str = re.sub(r'^```(?:json)?\s*', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'```\s*$', '', json_str, flags=re.MULTILINE)
        json_str = json_str.strip()

        def _extract_json_object(s: str) -> str:
            start = s.find('{')
            if start == -1:
                return s
            depth = 0
            for i, ch in enumerate(s[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return s[start:i+1]
            return s[start:]

        json_str = _extract_json_object(json_str)

        try:
            parsed = json.loads(json_str)
            parsed.setdefault("intent", "content_search")
            parsed.setdefault("sort_by", "none")
            parsed.setdefault("order", "desc")
            parsed.setdefault("filters", [])
            parsed.setdefault("top_k", 10)
            parsed.setdefault("search_text", "")
            try:
                parsed["top_k"] = int(parsed["top_k"])
            except (TypeError, ValueError):
                parsed["top_k"] = 10
            if not isinstance(parsed["filters"], list):
                parsed["filters"] = []
            print(f"  [LLM] ✓ Parsed successfully: intent={parsed['intent']}, "
                  f"sort_by={parsed['sort_by']}, top_k={parsed['top_k']}, "
                  f"filters={len(parsed['filters'])}, "
                  f"search_text='{parsed.get('search_text', '')[:50]}'")
            return parsed
        except json.JSONDecodeError as je:
            print(f"  [LLM] ✗ Failed to parse JSON ({je}): {json_str[:200]}")
            return None

    def parse_query(self, query_text: str) -> Optional[dict]:
        """Parse a natural language query.
        Tier 1 (PRIMARY): Rule‑based parser.
        Tier 2 (FALLBACK): LLM — only if rules fail.
        """
        print(f"[AIQueryProcessor] Parsing: '{query_text}'")

        # Tier 1: rule parser (primary)
        result = self.rule_parser.parse(query_text)
        if result is not None:
            print(f"[AIQueryProcessor] → Resolved by rule-based parser (Tier 1 primary)")
            print(f"  Result: {json.dumps(result, indent=2)}")
            return result

        # Tier 2: LLM (fallback)
        print(f"[AIQueryProcessor] → Rule parser returned None, falling back to LLM (Tier 2)...")
        llm_result = self._llm_parse(query_text)
        if llm_result is not None:
            print(f"[AIQueryProcessor] → Resolved by LLM (Tier 2 fallback)")
            print(f"  Result: {json.dumps(llm_result, indent=2)}")
            return llm_result

        # All tiers failed — fallback to pure content search
        print(f"[AIQueryProcessor] → All tiers failed, falling back to pure content search")
        fallback = {
            "intent": "content_search",
            "sort_by": "none",
            "order": "desc",
            "filters": [],
            "top_k": 10,
            "search_text": query_text,
        }
        print(f"  Fallback: {json.dumps(fallback, indent=2)}")
        return fallback


# ── Global AI processor (lazy loaded) ────────────────────────────────────────
_ai_processor = None

def get_ai_processor():
    global _ai_processor
    if _ai_processor is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[get_ai_processor] Creating AIQueryProcessor on {device}")
        _ai_processor = AIQueryProcessor(device=device)
    return _ai_processor


# ── New AI search endpoint ───────────────────────────────────────────────────
@app.post("/search/ai")
async def api_search_ai(req: Request):
    global _api_searcher
    payload = await req.json()
    query_text = payload.get("query", "").strip()
    directory = payload.get("directory")  # optional manual directory filter
    qid = payload.get("_qid")

    if _api_searcher is None:
        return {"error": "No index loaded", "results": [], "counts": {}, "scores": {}}

    proc = get_ai_processor()
    parsed = proc.parse_query(query_text)
    if parsed is None:
        # Fallback to normal semantic search
        results, counts, scores = _api_searcher.query(query_text, top_k=20, caption_weight=0.4)
    else:
        # Merge explicit directory filter if provided in API request
        if directory:
            parsed.setdefault("filters", []).append({
                "field": "directory", "operator": "contains", "value": directory
            })
        try:
            results, counts, scores = _api_searcher.ai_search(parsed, caption_weight=0.4)
        except Exception as e:
            return {"error": str(e), "results": [], "counts": {}, "scores": {}}

    results = [r for r in results if os.path.isfile(r)]
    result_set = set(results)
    counts = {k: v for k, v in counts.items() if k in result_set}
    scores = {k: v for k, v in scores.items() if k in result_set}

    # ----- DEBUG PRINT START -----
    print(f"\n[SEARCH/AI] Query: '{query_text}'")
    if parsed:
        print(f"  Parsed: intent={parsed.get('intent')}, sort_by={parsed.get('sort_by')}, "
              f"order={parsed.get('order')}, top_k={parsed.get('top_k')}, "
              f"filters={json.dumps(parsed.get('filters'))}, "
              f"search_text='{parsed.get('search_text')}'")
    searcher = _api_searcher
    for rank, path in enumerate(results, start=1):
        score = scores.get(path, 0.0)
        cnt = counts.get(path, 0)
        meta = searcher.video_metadata.get(path, {})
        dur = meta.get('duration', 0)
        size_mb = meta.get('file_size', 0) / (1024 * 1024)
        res = meta.get('resolution', (0, 0))
        fps_val = meta.get('fps', 0)
        total_frames_val = meta.get('total_frames', 0)
        ext = meta.get('extension', '')
        dir_ = meta.get('directory', '')
        print(f"  #{rank}: {path}")
        print(f"        score={score:.4f}  frames_matched={cnt}  dir='{dir_}'  "
              f"size={size_mb:.1f}MB  dur={dur:.1f}s  "
              f"res={res[0]}x{res[1]}  fps={fps_val:.1f}  total_frames={total_frames_val}  ext={ext}")
    print("---")
    # ----- DEBUG PRINT END -----

    response = {
        "results": results,
        "counts": counts,
        "scores": {k: float(v) for k, v in scores.items()},
    }
    if qid:
        response["_qid"] = qid
    return response


# ── Video metadata extraction helper ─────────────────────────────────────────
def extract_video_meta(video_path: str, videos_dir: str) -> Optional[dict]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0.0
    width  = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    try:
        file_size = os.path.getsize(video_path)
    except OSError:
        file_size = 0
    rel_path = os.path.relpath(video_path, videos_dir)
    directory = os.path.dirname(rel_path) if os.path.dirname(rel_path) else "root"
    ext = Path(video_path).suffix.lower()
    return {
        "video_path": os.path.abspath(video_path),
        "duration": duration,
        "file_size": file_size,
        "resolution": (int(width), int(height)),
        "fps": fps,
        "total_frames": total_frames,
        "extension": ext,
        "directory": directory
    }


# ── Original helper functions (unchanged) ────────────────────────────────────
def get_memory_info():
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

def extract_advanced_semantic_features(caption: str, lemmatizer=None) -> List[str]:
    try:
        caption_clean = re.sub(r'[^\w\s]', ' ', caption.lower())
        try:
            words = word_tokenize(caption_clean)
        except Exception:
            words = caption_clean.split()
        meaningful_words = []
        for word in words:
            if len(word) > 2:
                if lemmatizer:
                    try:
                        meaningful_words.append(lemmatizer.lemmatize(word))
                    except Exception:
                        meaningful_words.append(word)
                else:
                    meaningful_words.append(word)
        visual_terms = {
            'person', 'woman', 'man', 'girl', 'boy', 'dancer', 'performer',
            'lady', 'female', 'male', 'model', 'beauty', 'couple',
            'clothing', 'outfit', 'dress', 'shirt', 'top', 'blouse', 'skirt', 'pants',
            'shorts', 'leggings', 'hoodie', 'jacket', 'bra', 'underwear', 'bikini',
            'lingerie', 'swimwear', 'bodysuit', 'fishnet', 'panty', 'panties',
            'thong', 'corset', 'stockings', 'garter', 'negligee', 'nightgown',
            'topless', 'shirtless', 'braless', 'barefoot',
            'naked', 'nude', 'nudity', 'bare', 'exposed', 'uncovered',
            'skin', 'body', 'chest', 'breast', 'breasts', 'boob', 'boobs',
            'butt', 'buttocks', 'rear', 'behind', 'booty',
            'cleavage', 'navel', 'belly', 'stomach', 'abdomen', 'midriff',
            'thigh', 'thighs', 'leg', 'legs', 'hip', 'hips', 'waist',
            'shoulder', 'shoulders', 'back', 'spine',
            'curves', 'curvy', 'figure', 'physique', 'slim', 'petite', 'voluptuous',
            'sensual', 'intimate',
            'sexy', 'seductive', 'provocative',
            'stripping', 'strip', 'dancing', 'grinding',
            'showering', 'bathing', 'undressing',
            'red', 'blue', 'green', 'black', 'white', 'pink', 'purple', 'yellow',
            'dance', 'posing', 'standing', 'sitting', 'walking',
            'room', 'bedroom', 'indoor', 'studio', 'mirror', 'bathroom', 'shower',
            'pool', 'beach', 'ocean', 'water', 'bed', 'toilet', 'kitchen', 'couch',
            'style', 'fashion', 'casual', 'cute', 'elegant', 'hot',
        }
        expanded = set(meaningful_words)
        _FASHION_COLOUR_SYNONYMS = {
            'top': ['shirt', 'blouse', 'crop top', 'tank top'],
            'skirt': ['miniskirt', 'miniskirt', 'pleated skirt'],
            'yellow': ['gold', 'amber', 'mustard'],
            'pink': ['rose', 'fuchsia', 'magenta'],
            'black': ['dark', 'ebony'],
            'white': ['ivory', 'cream', 'snow'],
            'blue': ['navy', 'azure', 'cobalt'],
            'green': ['emerald', 'lime', 'olive'],
            'red': ['crimson', 'scarlet', 'ruby'],
            'purple': ['violet', 'lavender', 'plum'],
            'bra': ['brassiere', 'lingerie', 'undergarment'],
            'bikini': ['swimsuit', 'swimwear', 'two piece'],
            'shorts': ['hot pants', 'short pants'],
        }

        # After tokenizing, expand with these synonyms:
        for word in meaningful_words[:15]:
            if word in visual_terms or len(word) > 4:
                try:
                    for syn in wordnet.synsets(word)[:2]:
                        for lemma in syn.lemmas()[:2]:
                            s = lemma.name().replace('_', ' ')
                            if len(s) > 2:
                                expanded.add(s)
                except Exception:
                    continue
            # NEW: add fashion/colour synonyms
            for syn in _FASHION_COLOUR_SYNONYMS.get(word, []):
                expanded.add(syn)
        return list(expanded)
    except Exception:
        return re.sub(r'[^\w\s]', ' ', caption.lower()).split()

def scene_aware_frame_sampling(video_path: str, max_frames: int = 60):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return
    fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return

    prev_hist, boundaries = None, [0]
    step = max(1, int(fps * 0.5))
    for idx in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.normalize(cv2.calcHist([gray], [0], None, [64], [0, 256]), None).flatten()
        if prev_hist is not None:
            if cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA) > 0.4:
                boundaries.append(idx)
        prev_hist = hist
    boundaries.append(total - 1)

    candidates = set()
    for b in boundaries:
        candidates.add(min(b, total - 1))
        if b + int(fps) < total:
            candidates.add(b + int(fps))
    fill_step = max(1, total // max(1, max_frames - len(candidates)))
    for i in range(0, total, fill_step):
        candidates.add(i)
        if len(candidates) >= max_frames * 2:
            break

    seen_hashes, yielded = [], 0
    for idx in sorted(candidates):
        if yielded >= max_frames:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        h = imagehash.phash(PILImage.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if any(h - sh < 8 for sh in seen_hashes[-5:]):
            continue
        seen_hashes.append(h)
        yield idx / fps, frame
        yielded += 1

    cap.release()

def blip_caption_generation(frame_rgb, blip_model, blip_processor, device):
    pil = PILImage.fromarray(frame_rgb)
    captions = []
    try:
        inputs = blip_processor(images=pil, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        if device == "cuda":
            inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}
        with torch.no_grad():
            out = blip_model.generate(**inputs, max_new_tokens=100, num_beams=3, do_sample=False)
        caption = blip_processor.decode(out[0], skip_special_tokens=True)
        if caption and len(caption) > 5:
            captions.append(caption)
    except Exception as e:
        print(f"BLIP caption failed: {e}")

    questions = [
        "What is the person wearing?",
        "What colors are prominent?",
        "What activity is happening?",
        "What objects are visible?",
        "How much skin is exposed?",
        "Is the person clothed or unclothed?",
    ]
    for question in questions:
        try:
            inputs = blip_processor(images=pil, text=question, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            if device == "cuda":
                inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}
            with torch.no_grad():
                out = blip_model.generate(**inputs, max_new_tokens=40, num_beams=3)
            answer = blip_processor.decode(out[0], skip_special_tokens=True)
            clean = answer.replace(question.lower(), "").strip()
            if clean and len(clean) > 3 and clean.lower() not in {'yes', 'no', 'maybe', 'unknown'}:
                captions.append(f"{question.rstrip('?')}: {clean}")
        except Exception:
            continue

    return " | ".join(captions) if captions else "video frame"

_worker_state = {
    'device': None,
    'siglip_model': None,
    'siglip_processor': None,
    'blip_model': None,
    'blip_processor': None,
    'embed_model': None,
    'lemmatizer': None,
    'worker_id': None,
}

def _init_high_accuracy_worker(worker_id: int = 0, device: str = None):
    global _worker_state
    _worker_state['worker_id'] = worker_id
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if worker_id > 0:
        dev = "cpu"
    _worker_state['device'] = dev

    print(f"Worker {worker_id} on {dev}")

    print(f"Worker {worker_id}: loading SigLIP-SO400M...")
    _worker_state['siglip_model'] = SiglipModel.from_pretrained(
        MODEL_SIGLIP,
        dtype=torch.float16 if dev == "cuda" else torch.float32,
    ).to(dev).eval()
    _worker_state['siglip_processor'] = SiglipProcessor.from_pretrained(MODEL_SIGLIP, use_fast=True)
    if dev == "cuda": torch.cuda.empty_cache(); gc.collect()

    print(f"Worker {worker_id}: loading BLIP-large...")
    _worker_state['blip_model'] = BlipForConditionalGeneration.from_pretrained(
        MODEL_BLIP,
        torch_dtype=torch.float16 if dev == "cuda" else torch.float32,
    ).to(dev).eval()
    _worker_state['blip_processor'] = BlipProcessor.from_pretrained(MODEL_BLIP)
    if dev == "cuda": torch.cuda.empty_cache(); gc.collect()

    print(f"Worker {worker_id}: loading mxbai-embed-large-v1...")
    _worker_state['embed_model'] = SentenceTransformer(MODEL_EMBED, device=dev)

    try:
        _worker_state['lemmatizer'] = WordNetLemmatizer()
    except Exception:
        _worker_state['lemmatizer'] = None

    mem = get_memory_info()
    print(f"Worker {worker_id} ready — RAM {mem['ram_used_gb']:.2f}GB GPU {mem['gpu_used_gb']:.2f}GB")

def _process_video_high_accuracy(args: Tuple[str, int, int]) -> Tuple[np.ndarray, np.ndarray, List[Dict]]:
    video_path, max_frames, worker_id = args
    global _worker_state

    siglip_model       = _worker_state['siglip_model']
    siglip_processor   = _worker_state['siglip_processor']
    blip_model         = _worker_state['blip_model']
    blip_processor     = _worker_state['blip_processor']
    embed_model        = _worker_state['embed_model']
    lemmatizer         = _worker_state['lemmatizer']
    device             = _worker_state['device']

    siglip_embeddings, text_embeddings, metadata = [], [], []

    try:
        for frame_count, (timestamp, frame_bgr) in enumerate(
            scene_aware_frame_sampling(video_path, max_frames=max_frames)
        ):
            try:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                pil = PILImage.fromarray(frame_rgb)

                pv = siglip_processor(images=pil, return_tensors="pt").pixel_values
                pv = pv.to(device, dtype=siglip_model.dtype)
                with torch.no_grad():
                    img_emb = siglip_model.get_image_features(pixel_values=pv).cpu().float().numpy()
                siglip_embeddings.append(img_emb.reshape(-1))

                caption = blip_caption_generation(frame_rgb, blip_model, blip_processor, device)
                semantic_features = extract_advanced_semantic_features(caption, lemmatizer)

                text_emb = embed_model.encode(caption, normalize_embeddings=True, convert_to_numpy=True)
                text_embeddings.append(text_emb.reshape(-1).astype(np.float32))

                metadata.append({
                    'video_path': os.path.abspath(video_path),
                    'timestamp': float(timestamp),
                    'caption': caption,
                    'semantic_features': semantic_features,
                })

                if frame_count % 10 == 0 and device == "cuda":
                    torch.cuda.empty_cache()
                    gc.collect()

            except Exception as e:
                print(f"Frame {timestamp:.1f}s error: {e}")
                continue

        print(f"Worker {worker_id}: done {video_path} — {len(metadata)} frames")

    except Exception as e:
        print(f"Video error {video_path}: {e}")

    siglip_arr = np.vstack(siglip_embeddings).astype(np.float32) if siglip_embeddings else np.zeros((0, SIGLIP_DIM), dtype=np.float32)
    text_arr   = np.vstack(text_embeddings).astype(np.float32)   if text_embeddings   else np.zeros((0, EMBED_DIM),   dtype=np.float32)
    return siglip_arr, text_arr, metadata


class HighAccuracyVideoIndexer:
    """High-accuracy indexer with incremental preprocessing support"""

    def __init__(self):
        self.clip_embeddings: List[np.ndarray] = []
        self.text_embeddings: List[np.ndarray] = []
        self.frame_metadata: List[Dict[str, Any]] = []
        self.next_id = 0
        self.video_metadata: Dict[str, dict] = {}

    def load_existing_indices(self, out_dir: Path) -> bool:
        clip_index_path = out_dir / "clip_index.faiss"
        text_index_path = out_dir / "text_index.faiss"
        metadata_path = out_dir / "metadata.pkl"
        tfidf_path = out_dir / "tfidf_index.pkl"

        required_files = [clip_index_path, text_index_path, metadata_path, tfidf_path]
        if not all(f.exists() for f in required_files):
            print("No existing index found - starting fresh")
            return False

        try:
            print("Loading existing indices...")
            with open(metadata_path, 'rb') as f:
                existing_metadata = pickle.load(f)
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
            if existing_metadata['ids'].size > 0:
                self.next_id = int(existing_metadata['ids'].max()) + 1
            else:
                self.next_id = 0

            video_meta_path = out_dir / "video_meta.pkl"
            if video_meta_path.exists():
                with open(video_meta_path, 'rb') as f:
                    self.video_metadata = pickle.load(f)

            print(f"Loaded existing index with {len(self.frame_metadata)} frames, {len(self.video_metadata)} videos")

            clip_index = faiss.read_index(str(clip_index_path))
            text_index = faiss.read_index(str(text_index_path))
            n_vectors = clip_index.ntotal
            if n_vectors > 0:
                if hasattr(clip_index, 'index') and hasattr(clip_index.index, 'reconstruct_n'):
                    clip_embeddings = clip_index.index.reconstruct_n(0, n_vectors)
                    text_embeddings = text_index.index.reconstruct_n(0, n_vectors)
                elif hasattr(clip_index, 'reconstruct_n'):
                    clip_embeddings = clip_index.reconstruct_n(0, n_vectors)
                    text_embeddings = text_index.reconstruct_n(0, n_vectors)
                else:
                    print("Warning: Cannot extract embeddings from existing index type")
                    clip_embeddings = np.zeros((0, SIGLIP_DIM), dtype=np.float32)
                    text_embeddings = np.zeros((0, EMBED_DIM), dtype=np.float32)

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
            self.video_metadata = {}
            return False

    def get_existing_video_paths(self) -> set:
        return set(os.path.abspath(meta['video_path']) for meta in self.frame_metadata)

    def process_video_folder(self, videos_dir: str, workers: int = 3, max_frames_per_video: int = 60,
                             out_dir: str = None, incremental: bool = True, excluded_dirs: str = "raw"):
        videos_dir = Path(videos_dir)
        if out_dir and incremental:
            out_dir_path = Path(out_dir)
            self.load_existing_indices(out_dir_path)

        video_extensions = ['.mp4', '.mov', '.mkv', '.avi', '.webm', '.wmv', '.flv', '.m4v', '.3gp', '.ogv']
        video_files = []
        print(f"Recursively scanning {videos_dir} for video files...")

        excluded_names = {
            name.strip().lower()
            for name in excluded_dirs.split(',')
            if name.strip()
        }

        def should_skip_path(path: Path) -> bool:
            for part in path.parts:
                if part.lower() in excluded_names:
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

        print(f"Found {len(video_files)} new video files to process")
        if not video_files:
            print("No new video files to process")
            return

        print("Extracting video metadata...")
        for vf in video_files:
            meta = extract_video_meta(vf, str(videos_dir))
            if meta:
                self.video_metadata[os.path.abspath(vf)] = meta
        print(f"Video metadata extracted for {len(self.video_metadata)} total videos")

        mem_info = get_memory_info()
        print(f"Available RAM: {mem_info['ram_available_gb']:.2f}GB")
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
                    print(f"Completed video {i + 1}/{len(video_files)}, total frames in index: {len(self.frame_metadata)}")
                except Exception as e:
                    print(f"Video processing failed: {e}")
                    continue
            self.next_id = global_id

    def build_high_accuracy_indices(self, clip_index_path: str, text_index_path: str):
        if not self.clip_embeddings:
            print("No embeddings to index")
            return
        clip_X = np.vstack(self.clip_embeddings).astype(np.float32)
        clip_X = norm_l2(clip_X)
        text_X = np.vstack(self.text_embeddings).astype(np.float32)
        text_X = norm_l2(text_X)
        n_vectors = clip_X.shape[0]
        ids = np.array([m['id'] for m in self.frame_metadata], dtype=np.int64)
        print(f"Building indices for {n_vectors} total vectors")
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
        captions = [m.get("caption", "") for m in self.frame_metadata]
        sem_feats = [" ".join(m.get("semantic_features", [])) for m in self.frame_metadata]
        combined = [f"{c} {s}" for c, s in zip(captions, sem_feats)]
        vectorizer = TfidfVectorizer(
            max_features=15000, stop_words='english', ngram_range=(1, 3),
            min_df=1, max_df=0.9, strip_accents='ascii', sublinear_tf=True, use_idf=True
        )
        tfidf_matrix = vectorizer.fit_transform(combined)
        with open(text_index_path, 'wb') as f:
            pickle.dump({
                'vectorizer': vectorizer,
                'tfidf_matrix': tfidf_matrix,
                'captions': captions,
                'semantic_features': sem_feats,
            }, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"TF-IDF index built: {len(captions)} documents")

    def save_metadata(self, metadata_path: str):
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
            'next_id': self.next_id
        }
        with open(metadata_path, 'wb') as f:
            pickle.dump(metadata, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"Comprehensive metadata saved ({len(self.frame_metadata)} total frames)")


def get_directory_stats(video_files, base_dir):
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
    """High-accuracy searcher with multi-modal fusion and metadata filtering."""

    def __init__(self, clip_index_path: str, text_index_path: str, metadata_path: str, tfidf_path: str):
        print("Initializing searcher...")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32

        self.siglip_model = SiglipModel.from_pretrained(MODEL_SIGLIP, dtype=dtype).to(self.device).eval()
        self.siglip_processor = SiglipProcessor.from_pretrained(MODEL_SIGLIP)
        self.embed_model = SentenceTransformer(MODEL_EMBED, device=self.device)

        try:
            self.reranker = CrossEncoder(MODEL_RERANKER, max_length=512, device=self.device)
        except Exception:
            self.reranker = None
            print("Reranker unavailable, skipping")

        try:
            self.lemmatizer = WordNetLemmatizer()
        except Exception:
            self.lemmatizer = None

        self.clip_index = faiss.read_index(clip_index_path)
        self.text_index = faiss.read_index(text_index_path)

        with open(metadata_path, 'rb') as f:
            self.metadata = pickle.load(f)

        with open(tfidf_path, 'rb') as f:
            sparse_data = pickle.load(f)

        if 'bm25' in sparse_data:
            self.bm25 = sparse_data['bm25']
            self.bm25_captions = sparse_data['captions']
            self.vectorizer = None
            self.tfidf_matrix = None
        else:
            self.bm25 = None
            self.vectorizer   = sparse_data['vectorizer']
            self.tfidf_matrix = sparse_data['tfidf_matrix']

        video_meta_path = Path(metadata_path).parent / "video_meta.pkl"
        if video_meta_path.exists():
            with open(video_meta_path, 'rb') as f:
                self.video_metadata = pickle.load(f)
        else:
            self.video_metadata = {}
            print("Warning: video_meta.pkl not found — metadata filters will be empty.")

        for path, meta in self.video_metadata.items():
            if meta.get('directory', '') == 'root':
                parent = os.path.basename(os.path.dirname(path))
                if parent and parent != os.path.basename(path):
                    meta['directory'] = parent

        print("Searcher ready!")

    _QUERY_SYNONYMS = {
        # Nudity & exposure
        'naked': ['nude', 'bare', 'unclothed', 'undressed', 'exposed', 'without clothes', 'nudity'],
        'nude': ['naked', 'bare', 'unclothed', 'undressed', 'exposed', 'nudity'],
        'topless': ['shirtless', 'bare chest', 'no top', 'uncovered chest', 'exposed chest', 'braless'],
        'shirtless': ['topless', 'bare chest', 'no shirt', 'uncovered torso', 'braless'],
        'braless': ['topless', 'no bra', 'bare chest', 'shirtless'],
        'barefoot': ['no shoes', 'bare feet', 'shoeless'],
        # Clothing & lingerie
        'bikini': ['swimsuit', 'swimwear', 'two piece', 'bathing suit', 'beachwear'],
        'bra': ['brassiere', 'underwear', 'lingerie', 'undergarment', 'intimate apparel'],
        'underwear': ['panties', 'panty', 'underpants', 'lingerie', 'undergarment', 'intimate apparel'],
        'lingerie': ['underwear', 'intimate apparel', 'negligee', 'nightwear', 'bra', 'panties'],
        'thong': ['g-string', 'underwear', 'panties', 'lingerie', 'intimate'],
        'corset': ['bustier', 'bodice', 'lingerie', 'waist trainer'],
        'stockings': ['thigh highs', 'hosiery', 'nylons', 'fishnet', 'garter'],
        'garter': ['garter belt', 'stockings', 'suspender belt', 'lingerie'],
        'negligee': ['nightgown', 'nightwear', 'sleepwear', 'lingerie', 'nightie'],
        'nightgown': ['negligee', 'nightwear', 'sleepwear', 'nightie'],
        'fishnet': ['mesh', 'net stockings', 'fishnet stockings', 'see through'],
        'bodysuit': ['one piece', 'leotard', 'catsuit', 'body'],
        # Body parts
        'butt': ['buttocks', 'rear', 'behind', 'backside', 'bottom', 'booty'],
        'booty': ['butt', 'buttocks', 'rear', 'behind', 'backside'],
        'boobs': ['breasts', 'breast', 'chest', 'bust', 'boob', 'cleavage'],
        'breasts': ['breast', 'chest', 'bust', 'boobs', 'boob', 'cleavage'],
        'cleavage': ['chest', 'bust', 'breasts', 'boobs', 'neckline', 'décolletage'],
        'navel': ['belly button', 'bellybutton', 'stomach', 'midriff', 'abdomen'],
        'belly': ['stomach', 'tummy', 'abdomen', 'midriff', 'navel'],
        'midriff': ['belly', 'stomach', 'abdomen', 'waist', 'midsection'],
        'thigh': ['thighs', 'upper leg', 'leg'],
        'hip': ['hips', 'waist', 'pelvis', 'curves'],
        'waist': ['midsection', 'midriff', 'waistline', 'hips'],
        'shoulder': ['shoulders', 'bare shoulder', 'off shoulder'],
        'curves': ['curvy', 'voluptuous', 'shapely', 'hourglass', 'figure'],
        'curvy': ['curves', 'voluptuous', 'shapely', 'thick', 'hourglass'],
        'voluptuous': ['curvy', 'busty', 'full figured', 'shapely', 'thick'],
        'petite': ['slim', 'small', 'tiny', 'slender', 'delicate'],
        'slim': ['slender', 'thin', 'petite', 'lean', 'fit'],
        # Intimate situations
        'intimate': ['close', 'private', 'personal', 'sensual', 'romantic'],
        'sensual': ['sexy', 'seductive', 'intimate', 'passionate'],
        'sexy': ['seductive', 'sensual', 'provocative', 'alluring', 'hot', 'attractive'],
        'seductive': ['sexy', 'sensual', 'provocative', 'alluring', 'tempting'],
        'provocative': ['sexy', 'seductive', 'suggestive', 'teasing', 'alluring'],
        'strip': ['stripping', 'undressing', 'taking off clothes', 'disrobing'],
        'stripping': ['strip', 'undressing', 'disrobing', 'taking off clothes', 'striptease'],
        'undressing': ['stripping', 'taking off clothes', 'disrobing', 'removing clothes'],
        'showering': ['bathing', 'washing', 'shower', 'bath', 'wet'],
        'bathing': ['showering', 'washing', 'bath', 'shower', 'wet', 'soaking'],
        'dancing': ['dance', 'grinding', 'moving', 'performing'],
        'grinding': ['dancing', 'rubbing', 'close dancing', 'lap dance'],
        # Locations
        'beach': ['ocean', 'seaside', 'shore', 'sand', 'waterfront', 'coastal'],
        'pool': ['swimming', 'poolside', 'water', 'swim', 'jacuzzi'],
        'bedroom': ['bed', 'room', 'boudoir', 'private room'],
        'bathroom': ['shower', 'bath', 'washroom', 'toilet', 'restroom'],
        'shower': ['showering', 'bathroom', 'bathing', 'wet'],
        'bed': ['bedroom', 'mattress', 'lying down', 'sheets'],
        'couch': ['sofa', 'settee', 'loveseat', 'living room'],
        'kitchen': ['counter', 'cooking', 'home'],
    }

    def expand_query_advanced(self, query: str) -> str:
        try:
            words = word_tokenize(query.lower())
            expanded = set(words)
            for word in words:
                for syn in wordnet.synsets(word)[:2]:
                    for lemma in syn.lemmas()[:2]:
                        s = lemma.name().replace('_', ' ')
                        if len(s) > 2:
                            expanded.add(s)
                if self.lemmatizer:
                    try:
                        expanded.add(self.lemmatizer.lemmatize(word))
                    except Exception:
                        pass
                if word in self._QUERY_SYNONYMS:
                    expanded.update(self._QUERY_SYNONYMS[word])
            return " ".join(expanded)
        except Exception:
            return query

    def search_with_high_accuracy(self, query: str, top_k: int = 20,
                                   clip_weight: float = 0.40, text_weight: float = 0.35, tfidf_weight: float = 0.25):
        search_k = min(top_k * 5, 300)
        expanded_query = self.expand_query_advanced(query)

        def _siglip(text):
            inp = self.siglip_processor(text=[text], return_tensors="pt", padding="max_length", truncation=True)
            inp = {k: v.to(self.device) for k, v in inp.items()}
            with torch.no_grad():
                return norm_l2(self.siglip_model.get_text_features(**inp).cpu().float().numpy().astype(np.float32))

        siglip_q     = _siglip(query)
        siglip_q_exp = _siglip(expanded_query)

        embed_q = self.embed_model.encode(
            f"Represent this sentence for searching relevant passages: {query}",
            normalize_embeddings=True, convert_to_numpy=True,
        ).reshape(1, -1).astype(np.float32)
        embed_q_exp = self.embed_model.encode(
            f"Represent this sentence for searching relevant passages: {expanded_query}",
            normalize_embeddings=True, convert_to_numpy=True,
        ).reshape(1, -1).astype(np.float32)

        clip_s,  clip_i  = self.clip_index.search(siglip_q,     search_k)
        clip_se, clip_ie = self.clip_index.search(siglip_q_exp, search_k)
        text_s,  text_i  = self.text_index.search(embed_q,      search_k)
        text_se, text_ie = self.text_index.search(embed_q_exp,  search_k)

        if self.bm25:
            raw     = np.array(self.bm25.get_scores(query.lower().split()))
            raw_exp = np.array(self.bm25.get_scores(expanded_query.lower().split()))
            mn = min(raw.min(), raw_exp.min())
            mx = max(raw.max(), raw_exp.max()) + 1e-9
            sparse_norm     = (raw     - mn) / (mx - mn)
            sparse_norm_exp = (raw_exp - mn) / (mx - mn)
        else:
            sparse_norm     = cosine_similarity(self.vectorizer.transform([query]),          self.tfidf_matrix).flatten()
            sparse_norm_exp = cosine_similarity(self.vectorizer.transform([expanded_query]), self.tfidf_matrix).flatten()

        n = len(self.metadata['ids'])
        candidates: Dict[int, Dict] = {}

        for s, idx in zip(clip_s[0],  clip_i[0]):
            if 0 <= idx < n: candidates.setdefault(idx, {})['clip'] = float(s)
        for s, idx in zip(clip_se[0], clip_ie[0]):
            if 0 <= idx < n:
                d = candidates.setdefault(idx, {})
                d['clip'] = max(d.get('clip', 0), float(s))
        for s, idx in zip(text_s[0],  text_i[0]):
            if 0 <= idx < n: candidates.setdefault(idx, {})['text'] = float(s)
        for s, idx in zip(text_se[0], text_ie[0]):
            if 0 <= idx < n:
                d = candidates.setdefault(idx, {})
                d['text'] = max(d.get('text', 0), float(s))
        for idx in np.argsort(sparse_norm)[-search_k:][::-1]:
            v = float(sparse_norm[idx])
            if v > 0.01: candidates.setdefault(int(idx), {})['sparse'] = v
        for idx in np.argsort(sparse_norm_exp)[-search_k:][::-1]:
            v = float(sparse_norm_exp[idx])
            if v > 0.01:
                d = candidates.setdefault(int(idx), {})
                d['sparse'] = max(d.get('sparse', 0), v)

        frame_scores: Dict[int, float] = {}
        for idx, s in candidates.items():
            cs, ts, ss = s.get('clip', 0), s.get('text', 0), s.get('sparse', 0)
            base = clip_weight * cs + text_weight * ts + tfidf_weight * ss
            consistency = 0.05 * max(0, sum(1 for x in [cs, ts, ss] if x > 0.1) - 1)
            frame_scores[idx] = base + consistency

        video_agg: Dict[str, list] = defaultdict(list)
        for idx, score in frame_scores.items():
            vp = os.path.abspath(self.metadata['video_paths'][idx])
            video_agg[vp].append({'idx': idx, 'score': score, 'timestamp': float(self.metadata['timestamps'][idx])})

        video_scores: Dict[str, float] = {}
        for vp, frames in video_agg.items():
            frames.sort(key=lambda f: f['timestamp'])
            sorted_s = sorted([f['score'] for f in frames], reverse=True)
            base = 0.6 * sorted_s[0] + 0.4 * float(np.mean(sorted_s[:3]))
            temporal_bonus = 0.0
            if len(frames) > 1:
                clusters, cur = [], [frames[0]]
                for fr in frames[1:]:
                    if fr['timestamp'] - cur[-1]['timestamp'] <= 10.0:
                        cur.append(fr)
                    else:
                        clusters.append(cur); cur = [fr]
                clusters.append(cur)
                if len(clusters) > 1:
                    temporal_bonus += 0.05 * (len(clusters) - 1)
                for cl in clusters:
                    if len(cl) >= 2 and float(np.mean([f['score'] for f in cl])) > 0.3:
                        temporal_bonus += 0.03
            video_scores[vp] = base + temporal_bonus

        ranked = sorted(video_scores, key=lambda v: video_scores[v], reverse=True)

        if self.reranker and len(ranked) > 1:
            pool = ranked[:min(50, len(ranked))]
            pairs = [(query, self.metadata['captions'][max(video_agg[vp], key=lambda f: f['score'])['idx']])
                     for vp in pool]
            logits = self.reranker.predict(pairs)
            orig_max = max(video_scores[v] for v in pool) or 1.0
            for i, vp in enumerate(pool):
                norm_orig   = video_scores[vp] / orig_max
                norm_rerank = float(1 / (1 + np.exp(-float(logits[i]))))
                video_scores[vp] = 0.35 * norm_orig + 0.65 * norm_rerank
            ranked = sorted(video_scores, key=lambda v: video_scores[v], reverse=True)

        results = []
        for vp in ranked[:top_k]:
            best = max(video_agg[vp], key=lambda f: f['score'])
            results.append({
                'video_path': vp,
                'timestamp':  best['timestamp'],
                'caption':    self.metadata['captions'][best['idx']],
                'score':      video_scores[vp],
                'frame_count': len(video_agg[vp]),
            })
        return results

    def query_filtered_by_directory(self, text: str, filter_directory: str, top_k: int = 20,
                                    clip_weight: float = 0.40, text_weight: float = 0.35, tfidf_weight: float = 0.25,
                                    caption_weight: float = 0.4):
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

    def query(self, text: str, top_k: int = 50, mood=None, allow_mature=True, caption_weight: float = 0.4):
        results = self.search_with_high_accuracy(text, top_k)
        return (
            [r['video_path'] for r in results],
            {r['video_path']: r['frame_count'] for r in results},
            {r['video_path']: r['score'] for r in results},
        )

    def _apply_metadata_filters(self, candidate_paths: list, filters: list) -> list:
        """Filter video paths by metadata conditions, with token-based AND for directory."""
        if not filters:
            return candidate_paths
        filtered = []
        for path in candidate_paths:
            meta = self.video_metadata.get(path)
            if not meta:
                continue
            ok = True
            for cond in filters:
                field = cond.get("field")
                op = cond.get("operator")
                val = cond.get("value")

                if field == "resolution_width":
                    actual = meta.get("resolution", (0, 0))[0]
                elif field == "resolution_height":
                    actual = meta.get("resolution", (0, 0))[1]
                elif field == "directory":
                    actual = path  # full path to the video file
                elif field == "filename":
                    actual = os.path.basename(path)
                elif field in meta:
                    actual = meta[field]
                else:
                    ok = False;
                    break

                # string comparisons (directory, extension, filename)
                if field in {"directory", "extension", "filename"}:
                    actual_str = str(actual).lower().replace("\\", "/")
                    val_str = str(val).lower().replace("\\", "/") if isinstance(val, str) else str(val).lower()
                    try:
                        if field == "directory" and op == "contains":
                            # NEW: token-based AND match – every word must appear in the path
                            tokens = re.findall(r'\w+', val_str)
                            if not tokens:
                                # fallback to simple substring if no word characters
                                if val_str not in actual_str:
                                    ok = False;
                                    break
                            else:
                                for token in tokens:
                                    if token not in actual_str:
                                        ok = False
                                        break
                        elif op == "eq":
                            if actual_str != val_str: ok = False; break
                        elif op == "contains":
                            if val_str not in actual_str: ok = False; break
                        elif op == "in":
                            if actual_str not in [str(v).lower() for v in val]: ok = False; break
                    except TypeError:
                        ok = False;
                        break
                else:
                    # numeric / other comparisons
                    try:
                        if op == "gt" and not (actual > val):
                            ok = False; break
                        elif op == "lt" and not (actual < val):
                            ok = False; break
                        elif op == "gte" and not (actual >= val):
                            ok = False; break
                        elif op == "lte" and not (actual <= val):
                            ok = False; break
                        elif op == "eq" and not (actual == val):
                            ok = False; break
                        elif op == "contains" and str(val).lower() not in str(actual).lower():
                            ok = False; break
                        elif op == "in" and not (actual in val):
                            ok = False; break
                    except TypeError:
                        ok = False;
                        break
            if ok:
                filtered.append(path)
        return filtered

    def _metadata_sort(self, paths: list, sort_by: str, order: str = "desc") -> list:
        if sort_by == "none":
            return paths
        def get_val(p):
            meta = self.video_metadata.get(p, {})
            if sort_by in meta:
                return meta[sort_by]
            elif sort_by == "resolution":
                w, h = meta.get("resolution", (0,0))
                return w * h
            return 0
        return sorted(paths, key=get_val, reverse=(order == "desc"))

    def _filter_by_gender(self, video_paths: List[str], require_man: bool = False, require_no_woman: bool = False) -> \
    List[str]:
        """
        Filter videos based on gender presence using captions.
        - require_no_woman: exclude any video where a woman is mentioned in any frame caption.
        - require_man: only include videos where at least one frame mentions a man.
        """
        if not require_man and not require_no_woman:
            return video_paths

        man_keywords = {'man', 'men', 'male', 'boy', 'guy', 'dude'}
        woman_keywords = {'woman', 'women', 'female', 'girl', 'lady', 'gal'}

        filtered = []
        for vp in video_paths:
            # Get all frame indices for this video
            indices = [i for i, path in enumerate(self.metadata['video_paths']) if os.path.abspath(path) == vp]
            captions = [self.metadata['captions'][i].lower() for i in indices]
            semantic_features = [self.metadata['semantic_features'][i] for i in indices]

            # Flatten semantic features list
            all_words = set()
            for feats in semantic_features:
                if isinstance(feats, list):
                    all_words.update(f.lower() for f in feats)
            caption_text = ' '.join(captions)
            all_words.update(caption_text.split())

            has_man = any(kw in all_words for kw in man_keywords)
            has_woman = any(kw in all_words for kw in woman_keywords)

            if require_no_woman and has_woman:
                continue
            if require_man and not has_man:
                continue
            filtered.append(vp)

        return filtered

    def ai_search(self, parsed_query: dict, caption_weight=0.4):
        """
        Execute a search based on the structured query.
        Returns: (results, counts, scores)
        """
        # --- Sanitisation ---
        valid_intents = {"metadata_sort", "metadata_filter", "content_search", "combined"}
        intent = parsed_query.get("intent", "content_search")
        if intent not in valid_intents:
            intent = "content_search" if parsed_query.get("search_text", "").strip() else "metadata_filter"

        valid_sort_fields = {"duration", "file_size", "resolution", "fps", "frames", "none"}
        sort_by = parsed_query.get("sort_by", "none")
        if sort_by not in valid_sort_fields:
            sort_by = "none"

        # ---- FIX: treat the sentinel value as “unlimited” ----
        UNLIMITED_SENTINEL = 1000000
        raw_top_k = int(parsed_query.get("top_k", 10))
        if raw_top_k >= UNLIMITED_SENTINEL:
            # Return all matching videos. Use a safe upper bound.
            top_k = max(1, len(self.video_metadata) + 1)
        else:
            top_k = max(1, min(raw_top_k, 5000))

        filters = parsed_query.get("filters", [])
        order = parsed_query.get("order", "desc")
        search_text = parsed_query.get("search_text", "").strip()
        # --- End sanitisation ---

        # --- Conjunction handling (X and Y) ---
        if " and " in search_text.lower() and not filters:
            parts = [p.strip() for p in re.split(r'\s+and\s+', search_text, flags=re.IGNORECASE)]
            if len(parts) == 2:
                retrieval_top_k = min(2000, max(500, len(self.video_metadata) * 5))
                res1, cnt1, scr1 = self.query(parts[0], top_k=retrieval_top_k, caption_weight=caption_weight)
                res2, cnt2, scr2 = self.query(parts[1], top_k=retrieval_top_k, caption_weight=caption_weight)
                common_videos = set(res1) & set(res2)
                if common_videos:
                    combined_scores = {vp: scr1.get(vp, 0) + scr2.get(vp, 0) for vp in common_videos}
                    final_set = sorted(combined_scores, key=combined_scores.get, reverse=True)[:top_k]
                    counts = {vp: cnt1.get(vp, 0) + cnt2.get(vp, 0) for vp in final_set}
                    scores = {vp: float(combined_scores[vp]) for vp in final_set}
                    return final_set, counts, scores

        all_videos = list(self.video_metadata.keys())
        if not all_videos:
            all_videos = list(set(self.metadata['video_paths']))

        filtered = self._apply_metadata_filters(all_videos, filters)

        # --- Gender‑based filtering (negation / exclusivity) ---
        gender_query = search_text.lower()
        if "no woman" in gender_query or "no women" in gender_query:
            filtered = self._filter_by_gender(filtered, require_no_woman=True)
            search_text = re.sub(r'\bno\s+woman\w*\b', '', search_text, flags=re.IGNORECASE).strip()
        elif "only man" in gender_query or "only men" in gender_query:
            filtered = self._filter_by_gender(filtered, require_man=True, require_no_woman=True)
            search_text = re.sub(r'\bonly\s+man\w*\b', '', search_text, flags=re.IGNORECASE).strip()
        elif "only woman" in gender_query or "only women" in gender_query:
            filtered = self._filter_by_gender(filtered, require_man=False, require_no_woman=False)
            # Actually "only woman" means no man, and at least one woman – we can refine later if needed
            search_text = re.sub(r'\bonly\s+woman\w*\b', '', search_text, flags=re.IGNORECASE).strip()

        has_directory_filter = any(f.get("field") == "directory" for f in filters)
        if has_directory_filter:
            retrieval_top_k = min(2000, max(500, len(filtered) * 10))
        else:
            retrieval_top_k = top_k * 3

        if search_text and filtered:
            results_full, counts_full, scores_full = self.query(
                search_text, top_k=retrieval_top_k, caption_weight=caption_weight
            )
            final_set = [vp for vp in results_full if vp in filtered]
            if not final_set:
                final_set = sorted(filtered, key=lambda vp: vp.lower())
            scores = {vp: scores_full.get(vp, 0.0) for vp in final_set}
            counts = {vp: counts_full.get(vp, 1) for vp in final_set}
        else:
            # metadata-only query: all scores = 1.0
            final_set = sorted(filtered, key=lambda vp: vp.lower())
            scores = {vp: 1.0 for vp in final_set}
            counts = {vp: 1 for vp in final_set}

        if sort_by != "none":
            final_set = self._metadata_sort(final_set, sort_by, order)

        # ---- FIX: conditional slicing ----
        if search_text or raw_top_k < UNLIMITED_SENTINEL:
            # Normal case: respect top_k (even the large safe bound for unlimited content queries)
            final_set = final_set[:top_k]
        # else: raw_top_k >= SENTINEL and no search_text → return everything (no slicing)

        return final_set, counts, scores


def select_video_directory():
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


def _run_preprocess_subprocess(payload: dict) -> None:
    global _preprocess_state, _preprocess_lock
    out_dir       = str(payload.get("out_dir", ""))
    videos_dir    = str(payload.get("videos_dir", ""))
    workers       = int(payload.get("workers", 3))
    max_frames    = int(payload.get("max_frames", 60))
    force_rebuild = bool(payload.get("force_rebuild", False))
    exclude_dirs  = str(payload.get("exclude_dirs", "raw"))

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--mode", "preprocess",
        "--videos_dir", videos_dir,
        "--out_dir", out_dir,
        "--workers", str(workers),
        "--max_frames", str(max_frames),
        "--exclude_dirs", exclude_dirs,
    ]
    if force_rebuild:
        cmd.append("--force_rebuild")
    else:
        cmd.append("--incremental")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with _preprocess_lock:
            _preprocess_state["_process"] = proc

        for raw in proc.stdout:
            line = raw.strip()
            if line:
                with _preprocess_lock:
                    _preprocess_state["pending_lines"].append(line)

        return_code = proc.wait()
        success = (return_code == 0)
        with _preprocess_lock:
            _preprocess_state.update({
                "running": False,
                "done": True,
                "success": success,
                "error": None if success else f"exit code {return_code}",
            })

    except Exception as exc:
        with _preprocess_lock:
            _preprocess_state.update({
                "running": False,
                "done": True,
                "success": False,
                "error": str(exc),
            })


def main():
    parser = argparse.ArgumentParser(description="High-Accuracy Video Search with Resource Management + AI")
    parser.add_argument("--mode", choices=["preprocess", "search", "server"], required=True)
    parser.add_argument("--videos_dir", default=None, help="Video directory (will prompt if not provided)")
    parser.add_argument("--out_dir", default=str(__import__("pathlib").Path(__import__("os").environ.get("LOCALAPPDATA", __import__("pathlib").Path.home() / "AppData" / "Local")) / "Recursive Video Player" / "index_data"),
                        help="Output directory for index files")
    parser.add_argument("--workers", type=int, default=3, help="Number of workers (recommend 1-3 for high accuracy)")
    parser.add_argument("--max_frames", type=int, default=60, help="Max frames per video")
    parser.add_argument("--recursive", action="store_true", default=True, help="Recursively process subdirectories")
    parser.add_argument("--incremental", action="store_true", default=True,
                        help="Incremental preprocessing (append to existing)")
    parser.add_argument("--force_rebuild", action="store_true", help="Force complete rebuild (ignore existing indices)")
    parser.add_argument("--exclude_dirs", type=str, default="raw",
                        help="Comma-separated directory names to exclude (case-insensitive exact match)")
    parser.add_argument("--query", type=str)
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--clip_weight", type=float, default=0.35)
    parser.add_argument("--text_weight", type=float, default=0.35)
    parser.add_argument("--tfidf_weight", type=float, default=0.3)
    parser.add_argument("--keep_alive", action="store_true", help="Interactive mode")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
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
            incremental=incremental_mode,
            excluded_dirs=args.exclude_dirs,
        )

        print("Building indices...")
        indexer.build_high_accuracy_indices(
            str(out_dir / "clip_index.faiss"),
            str(out_dir / "text_index.faiss")
        )
        indexer.build_comprehensive_text_index(str(out_dir / "tfidf_index.pkl"))
        indexer.save_metadata(str(out_dir / "metadata.pkl"))

        # Save video-level metadata (NEW)
        if indexer.video_metadata:
            with open(out_dir / "video_meta.pkl", 'wb') as f:
                pickle.dump(indexer.video_metadata, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"Video metadata saved: {len(indexer.video_metadata)} videos")

        print(f"Preprocessing complete! Total frames in index: {len(indexer.frame_metadata)}")

        final_mem = get_memory_info()
        print(f"Recursive preprocessing complete!")
        print(f"Final memory: {final_mem['ram_used_gb']:.1f}GB RAM, {final_mem['gpu_used_gb']:.1f}GB GPU")
        print(f"Processed {len(indexer.frame_metadata)} frames from {dir_stats['total_videos']} videos")
        print(f"Index files saved to: {out_dir}")

    elif args.mode == "search":
        if not args.query and not args.keep_alive:
            print("Provide --query for search")
            return

        default_out_dir = str(__import__("pathlib").Path(__import__("os").environ.get("LOCALAPPDATA", __import__("pathlib").Path.home() / "AppData" / "Local")) / "Recursive Video Player" / "index_data")
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
            import json as _json
            import sys as _sys

            unique_videos = len(set(searcher.metadata['video_paths']))
            ready_msg = {
                "status": "ready",
                "device": str(searcher.device),
                "video_count": unique_videos,
            }
            print(_json.dumps(ready_msg), flush=True)

            while True:
                try:
                    raw = _sys.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    break

                if not raw:
                    break

                raw = raw.strip()
                if not raw:
                    continue

                try:
                    payload = _json.loads(raw)
                except _json.JSONDecodeError:
                    error_out = {"error": "invalid JSON", "results": [], "counts": {}, "scores": {}}
                    print(_json.dumps(error_out), flush=True)
                    continue

                if payload.get("quit"):
                    break

                query_text = payload.get("query", "").strip()
                if not query_text:
                    continue

                top_k = int(payload.get("top_k", args.top_k))
                qid = payload.get("_qid")
                directory = payload.get("directory")

                try:
                    if directory:
                        results, counts, scores = searcher.query_filtered_by_directory(
                            query_text, directory, top_k, caption_weight=0.4
                        )
                    else:
                        results, counts, scores = searcher.query(
                            query_text, top_k, caption_weight=0.4
                        )

                    results = [r for r in results if os.path.isfile(r)]
                    result_set = set(results)
                    counts = {k: v for k, v in counts.items() if k in result_set}
                    scores = {k: v for k, v in scores.items() if k in result_set}

                    response = {
                        "results": results,
                        "counts": counts,
                        "scores": {k: float(v) for k, v in scores.items()},
                    }
                    if qid is not None:
                        response["_qid"] = qid

                except Exception as exc:
                    response = {
                        "error": str(exc),
                        "results": [],
                        "counts": {},
                        "scores": {},
                    }
                    if qid is not None:
                        response["_qid"] = qid

                print(_json.dumps(response), flush=True)

        else:
            results, counts, scores = searcher.query(args.query, args.top_k, caption_weight=0.4)

            results = [r for r in results if os.path.isfile(r)]
            result_set = set(results)
            counts = {k: v for k, v in counts.items() if k in result_set}
            scores = {k: v for k, v in scores.items() if k in result_set}

            output_data = {
                "results": results,
                "counts": {k: int(v) for k, v in counts.items()},
                "scores": {k: float(v) for k, v in scores.items()}
            }

            print(json.dumps(output_data, indent=2))

    elif args.mode == "server":
        global _api_searcher, _server_out_dir
        out_dir_to_use = args.out_dir
        _server_out_dir = out_dir_to_use
        clip_index_path = str(Path(out_dir_to_use) / "clip_index.faiss")
        text_index_path = str(Path(out_dir_to_use) / "text_index.faiss")
        metadata_path   = str(Path(out_dir_to_use) / "metadata.pkl")
        tfidf_path      = str(Path(out_dir_to_use) / "tfidf_index.pkl")
        missing_files   = [f for f in [clip_index_path, text_index_path,
                                       metadata_path, tfidf_path]
                           if not os.path.exists(f)]
        if missing_files:
            print(f"No index found in {out_dir_to_use} — server starting without search.")
            print("Use POST /index/start to build an index, then POST /index/reload.")
            _api_searcher = None
        else:
            _api_searcher = HighAccuracyVideoSearcher(
                clip_index_path, text_index_path, metadata_path, tfidf_path
            )
        print(f"FastAPI server starting on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()