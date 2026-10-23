"""
YtDlpManager — yt-dlp come ESEGUIBILE ESTERNO aggiornabile (non congelato nell'exe).
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

__author__ = "Paolo Basta"

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from storage import AUDIO_CACHE_DIR, BIN_DIR, ensure_data_dir

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
SPONSORBLOCK_API = "https://sponsor.ajay.app/api/skipSegments"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
STREAM_URL_TTL = 3 * 3600  # gli URL googlevideo scadono dopo ~6h
AUDIO_EXTS = (".opus", ".webm", ".m4a", ".mp3", ".ogg")


class YtDlpManager:
    def __init__(self, status_cb: Optional[Callable[[str], None]] = None) -> None:
        ensure_data_dir()
        self.status_cb = status_cb
        self.exe_path = BIN_DIR / "yt-dlp.exe"
        self.deno_path = BIN_DIR / "deno.exe"
        self.cache_enabled = True
        self.cache_max_mb = 500
        self.sponsorblock_enabled = True

        self._ready = threading.Event()
        self._url_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._url_cache_lock = threading.Lock()
        self._video_locks: Dict[str, threading.Lock] = {}
        self._video_locks_guard = threading.Lock()
        self._downloads_in_progress: set[str] = set()
        self._js_runtime_supported: Optional[bool] = None

    # ------------------------------------------------------------- utilità
    def _status(self, msg: str) -> None:
        print(f"[yt-dlp] {msg}")
        if self.status_cb:
            try:
                self.status_cb(msg)
            except Exception:
                pass

    def _lock_for(self, video_id: str) -> threading.Lock:
        with self._video_locks_guard:
            if video_id not in self._video_locks:
                self._video_locks[video_id] = threading.Lock()
            return self._video_locks[video_id]

    @staticmethod
    def _download_file(url: str, target: Path, timeout: float = 120.0) -> None:
        tmp = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        os.replace(tmp, target)

    # ------------------------------------------------------- bootstrap
    def ensure_ready_async(self, auto_update: bool = True) -> None:
        threading.Thread(target=self._bootstrap, args=(auto_update,), daemon=True, name="ytdlp-bootstrap").start()

    def _bootstrap(self, auto_update: bool) -> None:
        try:
            if not self.exe_path.exists():
                self._status("Scarico yt-dlp (prima esecuzione)...")
                self._download_file(YTDLP_URL, self.exe_path)
                self._status("yt-dlp installato.")
            elif auto_update:
                self._status("Controllo aggiornamenti yt-dlp...")
                res = subprocess.run(
                    [str(self.exe_path), "-U"],
                    capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW,
                )
                out = (res.stdout or "") + (res.stderr or "")
                if "Updated yt-dlp" in out:
                    self._status("yt-dlp aggiornato all'ultima versione.")
        except Exception as e:
            self._status(f"Impossibile scaricare/aggiornare yt-dlp: {e}")
        finally:
            self._ready.set()
        # Runtime JS (deno) richiesto da yt-dlp per alcune estrazioni YouTube: in background
        try:
            if not self.deno_path.exists() and not shutil.which("deno"):
                self._status("Scarico il runtime JavaScript (deno) per yt-dlp...")
                data = httpx.get(DENO_URL, follow_redirects=True, timeout=180.0).content
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    with zf.open("deno.exe") as src, open(self.deno_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                self._status("Runtime deno installato.")
        except Exception as e:
            self._status(f"Runtime deno non disponibile ({e}): alcune estrazioni potrebbero fallire.")

    def version(self) -> str:
        if not self.exe_path.exists():
            return "non installato"
        try:
            r = subprocess.run([str(self.exe_path), "--version"], capture_output=True, text=True,
                               timeout=15, creationflags=NO_WINDOW)
            return (r.stdout or "").strip() or "sconosciuta"
        except Exception:
            return "sconosciuta"

    def _base_cmd(self) -> List[str]:
        cmd = [str(self.exe_path), "--no-warnings", "--no-playlist", "--socket-timeout", "10"]
        deno = self.deno_path if self.deno_path.exists() else (Path(shutil.which("deno")) if shutil.which("deno") else None)
        if deno and self._js_runtime_supported is not False:
            cmd += ["--js-runtimes", f"deno:{deno}"]
        return cmd

    def _run(self, args: List[str], timeout: float = 45.0) -> subprocess.CompletedProcess:
        self._ready.wait(timeout=60)
        if not self.exe_path.exists():
            raise RuntimeError("yt-dlp non è installato (controlla la connessione internet).")
        cmd = self._base_cmd() + args
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        if res.returncode != 0 and "--js-runtimes" in cmd and "no such option" in (res.stderr or "").lower():
            self._js_runtime_supported = False
            cmd = self._base_cmd() + args
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                 creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        return res

    # ------------------------------------------------------------- cache
    def cached_file(self, video_id: str) -> Optional[Path]:
        if not self.cache_enabled:
            return None
        for ext in AUDIO_EXTS:
            p = AUDIO_CACHE_DIR / f"{video_id}{ext}"
            if p.exists() and p.stat().st_size > 50_000:
                try:
                    os.utime(p, None)  # aggiorna atime/mtime per la LRU
                except Exception:
                    pass
                return p
        return None

    def cache_in_background(self, video_id: str) -> None:
        if not self.cache_enabled or self.cached_file(video_id) or video_id in self._downloads_in_progress:
            return
        self._downloads_in_progress.add(video_id)

        def worker() -> None:
            try:
                out_tmpl = str(AUDIO_CACHE_DIR / f"{video_id}.%(ext)s")
                self._run(["-f", "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio", "-o", out_tmpl,
                           "--no-part", f"https://www.youtube.com/watch?v={video_id}"], timeout=600)
                self._enforce_cache_limit()
            except Exception as e:
                print(f"[yt-dlp] cache fallita per {video_id}: {e}")
            finally:
                self._downloads_in_progress.discard(video_id)

        threading.Thread(target=worker, daemon=True, name=f"cache-{video_id}").start()

    def _enforce_cache_limit(self) -> None:
        files = [p for p in AUDIO_CACHE_DIR.iterdir() if p.is_file() and p.suffix in AUDIO_EXTS]
        total = sum(p.stat().st_size for p in files)
        limit = max(50, int(self.cache_max_mb)) * 1024 * 1024
        if total <= limit:
            return
        for p in sorted(files, key=lambda f: f.stat().st_mtime):
            try:
                total -= p.stat().st_size
                p.unlink()
            except Exception:
                continue
            if total <= limit * 0.9:
                break

    def cache_size_mb(self) -> float:
        try:
            return sum(p.stat().st_size for p in AUDIO_CACHE_DIR.iterdir() if p.is_file()) / (1024 * 1024)
        except Exception:
            return 0.0

    def clear_cache(self) -> None:
        for p in AUDIO_CACHE_DIR.iterdir():
            try:
                p.unlink()
            except Exception:
                pass

    # ------------------------------------------------------ sponsorblock
    def skip_segments(self, video_id: str) -> List[Tuple[float, float]]:
        if not self.sponsorblock_enabled:
            return []
        try:
            r = httpx.get(
                SPONSORBLOCK_API,
                params={"videoID": video_id, "categories": json.dumps(["sponsor", "selfpromo", "intro", "outro", "interaction", "music_offtopic"])},
                timeout=4.0,
            )
            if r.status_code != 200:
                return []
            return [(float(s["segment"][0]), float(s["segment"][1])) for s in r.json() if "segment" in s]
        except Exception:
            return []

    # ------------------------------------------------------------ estrazione
    def resolve_stream(self, video_id: str) -> Dict[str, Any]:
        """
        Restituisce {uri, title, duration, http_headers, skip_segments}.
        Preferisce il file in cache; altrimenti estrae l'URL diretto con yt-dlp.
        """
        cached = self.cached_file(video_id)
        segments = self.skip_segments(video_id)
        if cached:
            return {"uri": str(cached), "title": "", "duration": 0.0, "http_headers": {}, "skip_segments": segments, "cached": True}

        now = time.time()
        with self._url_cache_lock:
            hit = self._url_cache.get(video_id)
            if hit and now - hit[0] < STREAM_URL_TTL:
                data = dict(hit[1])
                data["skip_segments"] = segments
                return data

        with self._lock_for(video_id):  # lock per singolo video, non globale
            with self._url_cache_lock:
                hit = self._url_cache.get(video_id)
                if hit and time.time() - hit[0] < STREAM_URL_TTL:
                    return dict(hit[1], skip_segments=segments)
            res = self._run(["-f", "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio", "-j",
                             f"https://www.youtube.com/watch?v={video_id}"])
            if res.returncode != 0 or not res.stdout.strip():
                err = (res.stderr or "").strip().splitlines()[-1:] or ["errore sconosciuto"]
                raise RuntimeError(f"yt-dlp: {err[0][:200]}")
            info = json.loads(res.stdout.strip().splitlines()[-1])
            data = {
                "uri": info.get("url"),
                "title": info.get("title") or "",
                "duration": float(info.get("duration") or 0.0),
                "http_headers": info.get("http_headers") or {},
                "skip_segments": segments,
                "cached": False,
            }
            if not data["uri"]:
                raise RuntimeError("yt-dlp non ha restituito un URL audio")
            with self._url_cache_lock:
                self._url_cache[video_id] = (time.time(), data)
        self.cache_in_background(video_id)
        return data

    def search_video_ids(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Ricerca di riserva su YouTube via yt-dlp (se ytmusicapi non risponde)."""
        res = self._run(["--flat-playlist", "-J", f"ytsearch{limit}:{query}"], timeout=40)
        if res.returncode != 0:
            return []
        try:
            entries = json.loads(res.stdout).get("entries") or []
        except Exception:
            return []
        return [
            {
                "videoId": e.get("id"),
                "title": e.get("title") or "",
                "artist": e.get("channel") or e.get("uploader") or "YouTube",
                "duration_seconds": float(e.get("duration") or 0),
            }
            for e in entries if e.get("id")
        ]

    def playlist_entries(self, playlist_id: str, limit: int = 50) -> Dict[str, Any]:
        res = self._run(["--flat-playlist", "-J", "--playlist-end", str(limit),
                         f"https://www.youtube.com/playlist?list={playlist_id}"], timeout=60)
        if res.returncode != 0:
            raise RuntimeError((res.stderr or "Playlist non leggibile").strip()[-200:])
        info = json.loads(res.stdout)
        return info
