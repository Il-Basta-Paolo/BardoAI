"""
MusicService — ricerca brani, playlist e risoluzione verso stream riproducibili.
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

from __future__ import annotations

__author__ = "Paolo Basta"

import base64
import difflib
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from storage import LOCAL_MUSIC_DIR, SecretVault, YTMUSIC_AUTH_FILE, DATA_DIR, ensure_data_dir
from ytdlp_manager import YtDlpManager

try:
    from ytmusicapi import YTMusic
    from ytmusicapi.helpers import get_authorization
except Exception:  # pragma: no cover
    YTMusic = None  # type: ignore
    get_authorization = None  # type: ignore

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None  # type: ignore

LOCAL_EXTS = {".mp3", ".ogg", ".flac", ".opus", ".m4a", ".wav"}

# --------------------------------------------------------------------------- filtri
_JUNK_TERMS = [
    "podcast", "episodio", "episode", "actual play", "audiobook", "hörspiel", "hoerspiel",
    "kapitel", "chapter", "vlog", "reacts", "reaction", "interview", "trap remix",
    "slowed", "sped up", "nightcore", "8-bit", "8 bit", "chiptune", "asmr", "rap beat", "tutorial",
]
_VOCAL_TERMS = [
    "with lyrics", "lyrics", "lyric video", "vocal", "vocals", "singing", "sung by", "singer",
    "feat", "ft", "featuring", "soprano", "tenor", "cover song",
    "percival", "miracle of sound", "danheim", "wardruna", "heilung", "sabaton", "powerwolf",
    "nightwish", "evanescence", "linkin park", "imagine dragons", "skillet", "halocene", "malukah",
    "peter hollens", "priscilla", "wolven storm", "steel for humans", "silver for monsters",
    "jennifer chao", "julie elven", "merethe soltvedt",
]
_VOCAL_UNLESS_INSTRUMENTAL = [
    "chant", "chanting", "choir", "opera", "bard song", "tavern song", "sea shanty", "shanties",
    "down by the river", "i want to live", "dragonborn", "sixteen strikes", "fields of ard skellig",
]
_CALM_TERMS = [
    "ambient", "ambience", "village", "relax", "relaxing", "sleep", "peaceful", "calm", "tavern", "inn",
    "campfire", "lullaby", "secunda", "masser", "far horizons", "kyne", "gwent", "meditation", "study",
    "piano cover", "guitar cover", "light version", "explore the ruins",
]
_AGGRESSIVE_TERMS = ["boss fight", "final boss", "combat", "metal cover", "terror", "nightmare", "horror", "slayer", "bloodborne"]
_INSTRUMENTAL_MARKERS = ["instrumental", "no vocals", "no vocal", "karaoke", "ost", "soundtrack", "score"]


def _terms_regex(terms: List[str]) -> re.Pattern:
    # \b ai bordi: confronto a parola intera / frase intera, mai sottostringa
    alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])", re.IGNORECASE)


_JUNK_RE = _terms_regex(_JUNK_TERMS)
_VOCAL_RE = _terms_regex(_VOCAL_TERMS)
_VUI_RE = _terms_regex(_VOCAL_UNLESS_INSTRUMENTAL)
_CALM_RE = _terms_regex(_CALM_TERMS)
_AGGR_RE = _terms_regex(_AGGRESSIVE_TERMS)
_INSTR_RE = _terms_regex(_INSTRUMENTAL_MARKERS)


def is_track_acceptable(title: str, artist: str = "", tone_profile: str = "") -> bool:
    """True se il brano è (plausibilmente) strumentale e coerente col tono della scena."""
    title_low = (title or "").lower()
    combined = f"{title_low} {(artist or '').lower()}"
    explicit_instr = bool(re.search(r"(?<![a-z])(instrumental|no vocals?|karaoke)(?![a-z])", title_low))
    if _JUNK_RE.search(combined):
        return False
    # "no vocals"/"without vocals" non sono marcatori vocali; "feat."/"ft." in una versione
    # esplicitamente "(Instrumental)" restano accettabili (la base è comunque strumentale)
    cleaned = re.sub(r"(?<![a-z])(no|without|senza)\s+vocals?(?![a-z])", " ", combined)
    m = _VOCAL_RE.search(cleaned)
    if m and not (explicit_instr and m.group(0).lower() in ("feat", "ft", "featuring")):
        return False
    if _VUI_RE.search(title_low) and not explicit_instr:
        return False
    if tone_profile in ("fast_combat", "epic_boss") and _CALM_RE.search(combined):
        return False
    if tone_profile in ("calm_rest", "exploration", "upbeat_tavern", "city") and _AGGR_RE.search(combined):
        return False
    return True


is_instrumental_candidate = is_track_acceptable


def clean_music_title(title: str) -> str:
    """Rimuove suffissi comuni dai titoli YouTube come [HD], (Official Video), ecc."""
    t = re.sub(r"\[.*?\]|\(.*?\)", "", title or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t or title



def parse_duration(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip()
    if not s:
        return 0.0
    try:
        parts = [int(p) for p in s.split(":")]
    except ValueError:
        return 0.0
    total = 0
    for p in parts:
        total = total * 60 + p
    return float(total)


# --------------------------------------------------------------------------- Spotify
class SpotifyCatalog:
    """Lettura metadati Spotify via API ufficiale (Client Credentials) o embed pubblico."""

    def __init__(self) -> None:
        self._token = ""
        self._token_exp = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def credentials() -> tuple[str, str]:
        return SecretVault.get_secret("spotify_client_id"), SecretVault.get_secret("spotify_client_secret")

    @staticmethod
    def set_credentials(client_id: str, client_secret: str) -> None:
        SecretVault.set_secret("spotify_client_id", client_id)
        SecretVault.set_secret("spotify_client_secret", client_secret)

    def has_credentials(self) -> bool:
        cid, sec = self.credentials()
        return bool(cid and sec)

    def _access_token(self) -> str:
        """Token Client Credentials, rinnovato automaticamente prima della scadenza."""
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            cid, sec = self.credentials()
            if not (cid and sec):
                return ""
            b64 = base64.b64encode(f"{cid}:{sec}".encode()).decode()
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {b64}"},
                data={"grant_type": "client_credentials"},
                timeout=8.0,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Credenziali Spotify non valide (HTTP {r.status_code})")
            data = r.json()
            self._token = data.get("access_token", "")
            self._token_exp = time.time() + int(data.get("expires_in") or 3600)
            return self._token

    def test_credentials(self) -> bool:
        with self._lock:
            self._token = ""
        return bool(self._access_token())

    @staticmethod
    def is_spotify_input(text: str) -> bool:
        t = (text or "").strip().lower()
        return "spotify.com" in t or t.startswith("spotify:")

    @staticmethod
    def extract_playlist_id(text: str) -> str:
        m = re.search(r"playlist[:/]([a-zA-Z0-9]{22})", text or "")
        if m:
            return m.group(1)
        t = (text or "").strip()
        return t if re.fullmatch(r"[a-zA-Z0-9]{22}", t) else ""

    def playlist(self, text: str, limit: int = 50) -> Dict[str, Any]:
        pid = self.extract_playlist_id(text)
        if not pid:
            raise ValueError("Link della playlist Spotify non valido.")
        tok = ""
        try:
            tok = self._access_token()
        except Exception:
            tok = ""
        if tok:
            r = httpx.get(
                f"https://api.spotify.com/v1/playlists/{pid}",
                params={"fields": "name,images,tracks.items(track(name,duration_ms,artists(name),album(images)))"},
                headers={"Authorization": f"Bearer {tok}"},
                timeout=10.0,
            )
            if r.status_code == 200:
                d = r.json()
                tracks = []
                for it in (d.get("tracks") or {}).get("items") or []:
                    t = (it or {}).get("track") or {}
                    if not t.get("name"):
                        continue
                    imgs = (t.get("album") or {}).get("images") or []
                    tracks.append({
                        "title": t["name"],
                        "artist": ", ".join(a.get("name", "") for a in t.get("artists") or []),
                        "duration_seconds": (t.get("duration_ms") or 0) / 1000.0,
                        "thumbnail": imgs[0]["url"] if imgs else "",
                        "source": "spotify",
                    })
                    if len(tracks) >= limit:
                        break
                return {"title": d.get("name") or "Playlist Spotify", "tracks": tracks, "playlistId": pid}
        # Embed pubblico (nessuna credenziale richiesta)
        r = httpx.get(f"https://open.spotify.com/embed/playlist/{pid}",
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0, follow_redirects=True)
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
        if r.status_code != 200 or not m:
            raise RuntimeError("Impossibile leggere la playlist Spotify (privata o non disponibile).")
        entity = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        tracks = []
        for rt in entity.get("trackList") or []:
            if not rt.get("title"):
                continue
            tracks.append({
                "title": rt["title"],
                "artist": (rt.get("subtitle") or "").replace("\xa0", " "),
                "duration_seconds": (rt.get("duration") or 0) / 1000.0,
                "thumbnail": "",
                "source": "spotify",
            })
            if len(tracks) >= limit:
                break
        if not tracks:
            raise RuntimeError("La playlist Spotify è vuota o privata.")
        return {"title": entity.get("name") or "Playlist Spotify", "tracks": tracks, "playlistId": pid}


def find_system_browser() -> Optional[str]:
    """Cerca l'eseguibile di Microsoft Edge o Google Chrome su Windows."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        candidates.append(str(Path(localapp) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
        candidates.append(str(Path(localapp) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _find_free_port(preferred: int = 9239) -> int:
    """Trova una porta TCP locale libera per il Chrome DevTools Protocol."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _kill_process_tree(pid: int) -> None:
    """Termina in modo sicuro l'intero albero di processi (browser + schede figlie) su Windows."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:
            pass
    try:
        import signal

        sig = getattr(signal, "SIGTERM", 9)
        os.kill(pid, sig)
    except Exception:
        pass


# --------------------------------------------------------------------------- servizio
class MusicService:
    def __init__(self, ytdlp: YtDlpManager) -> None:
        self.ytdlp = ytdlp
        self.spotify = SpotifyCatalog()
        self.ytm = None
        self._ytm_lock = threading.Lock()
        self._search_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._resolve_cache: Dict[str, str] = {}

    @property
    def is_authenticated(self) -> bool:
        """True se il file ytmusic_auth.json esiste ed è valido."""
        return YTMUSIC_AUTH_FILE.is_file()

    def get_auth_status(self) -> Dict[str, Any]:
        """Restituisce lo stato corrente di autenticazione per la UI."""
        auth_ok = self.is_authenticated
        return {
            "authenticated": auth_ok,
            "auth_file": str(YTMUSIC_AUTH_FILE),
            "auth_file_exists": auth_ok,
        }

    def reload_client(self) -> None:
        """Ricarica il client YTMusic (autenticato o ospite) azzerando le cache."""
        with self._ytm_lock:
            self.ytm = None
            self._search_cache.clear()
            self._resolve_cache.clear()
        self._client()

    def disconnect_account(self) -> None:
        """Rimuove il file di autenticazione locale e il profilo browser temporaneo."""
        with self._ytm_lock:
            if YTMUSIC_AUTH_FILE.exists():
                try:
                    YTMUSIC_AUTH_FILE.unlink(missing_ok=True)
                except Exception:
                    pass
            prof = DATA_DIR / "ytm_browser_profile"
            if prof.exists():
                try:
                    shutil.rmtree(prof, ignore_errors=True)
                except Exception:
                    pass
            self.ytm = None
            self._search_cache.clear()
            self._resolve_cache.clear()
        self._client()

    def _client(self):
        with self._ytm_lock:
            if self.ytm is None and YTMusic is not None:
                try:
                    if YTMUSIC_AUTH_FILE.is_file():
                        self.ytm = YTMusic(str(YTMUSIC_AUTH_FILE))
                    else:
                        self.ytm = YTMusic()
                except Exception as e:
                    print(f"[Music] Inizializzazione YTMusic fallita ({e}), uso modalità ospite")
                    try:
                        self.ytm = YTMusic()
                    except Exception:
                        self.ytm = None
            return self.ytm

    @staticmethod
    def _save_auth_cookie_string(cookie_str: str, authuser: str = "0") -> None:
        """Costruisce e salva il file ytmusic_auth.json partendo dalla stringa Cookie."""
        m = re.search(r"(?:__Secure-3PAPISID|SAPISID)=([^;\s\"']+)", cookie_str)
        if not m:
            raise ValueError(
                "Cookie di sessione Google (__Secure-3PAPISID o SAPISID) non trovato. "
                "Assicurati di aver effettuato l'accesso su music.youtube.com."
            )
        sapisid = m.group(1).strip()
        if "__Secure-3PAPISID=" not in cookie_str:
            cookie_str = f"__Secure-3PAPISID={sapisid}; " + cookie_str

        origin = "https://music.youtube.com"
        auth_header = ""
        if get_authorization is not None:
            try:
                auth_header = get_authorization(f"{sapisid} {origin}")
            except Exception:
                pass

        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "accept": "*/*",
            "accept-encoding": "gzip, deflate",
            "content-type": "application/json",
            "content-encoding": "gzip",
            "origin": origin,
            "x-origin": origin,
            "x-goog-authuser": str(authuser),
            "cookie": cookie_str,
        }
        if auth_header:
            headers["authorization"] = auth_header

        ensure_data_dir()
        with open(YTMUSIC_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(headers, f, indent=2, ensure_ascii=False)

    def save_manual_headers(self, raw_input: str) -> None:
        """Salva headers/cookie incollati manualmente dall'utente."""
        text = raw_input.strip()
        if not text:
            raise ValueError("Il testo incollato è vuoto.")
        if text.startswith("{") and text.endswith("}"):
            data = json.loads(text)
            ensure_data_dir()
            with open(YTMUSIC_AUTH_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif "cookie:" in text.lower() or "sapisid" in text.lower() or "__secure" in text.lower():
            cookie_match = re.search(r"cookie:\s*(.+)", text, re.IGNORECASE)
            cookie_str = cookie_match.group(1).strip() if cookie_match else text
            self._save_auth_cookie_string(cookie_str)
        else:
            try:
                from ytmusicapi.auth.browser import setup_browser
                setup_browser(filepath=str(YTMUSIC_AUTH_FILE), headers_raw=text)
            except Exception as e:
                raise ValueError(f"Impossibile interpretare gli headers: {e}") from e
        self.reload_client()

    def login_with_browser_window(
        self,
        timeout_sec: int = 180,
        cancel_event: Optional[threading.Event] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Apre una finestra browser dedicata su music.youtube.com.
        Intercetta l'accesso tramite Chrome DevTools Protocol (CDP),
        salva i cookie in ytmusic_auth.json, chiude il browser e ricarica il client.
        """
        browser_exe = find_system_browser()
        if not browser_exe:
            raise RuntimeError("Nessun browser compatibile trovato (richiesto Microsoft Edge o Google Chrome).")

        if websocket is None:
            raise RuntimeError("Modulo 'websocket-client' non installato.")

        ensure_data_dir()
        profile_dir = DATA_DIR / "ytm_browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        debug_port = _find_free_port(9239)

        cmd = [
            browser_exe,
            "--app=https://music.youtube.com",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=980,720",
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        start_ts = time.time()

        try:
            while time.time() - start_ts < timeout_sec:
                if cancel_event and cancel_event.is_set():
                    _kill_process_tree(proc.pid)
                    raise RuntimeError("Accesso annullato dall'utente.")

                if proc.poll() is not None:
                    raise RuntimeError("Finestra di accesso chiusa prima del completamento.")

                if progress_cb:
                    elapsed = int(time.time() - start_ts)
                    progress_cb(f"In attesa del login su YouTube Music... ({elapsed}s)")

                try:
                    resp = httpx.get(f"http://127.0.0.1:{debug_port}/json", timeout=2.0)
                    targets = resp.json()
                    # Preferisce target di tipo 'page', altrimenti ripiega su qualsiasi target valido
                    ws_url = next(
                        (t.get("webSocketDebuggerUrl") for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")),
                        None,
                    ) or next(
                        (t.get("webSocketDebuggerUrl") for t in targets if t.get("webSocketDebuggerUrl")),
                        None,
                    )
                    if ws_url:
                        ws = websocket.create_connection(ws_url, timeout=3)
                        raw_msg = {}
                        try:
                            ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
                            for _ in range(5):
                                msg = json.loads(ws.recv())
                                if msg.get("id") == 1:
                                    raw_msg = msg
                                    break
                        finally:
                            ws.close()

                        cookies = raw_msg.get("result", {}).get("cookies", [])
                        yt_cookies = [
                            c for c in cookies
                            if "youtube.com" in c.get("domain", "")
                        ]
                        has_sapisid = any(
                            c.get("name") in ("__Secure-3PAPISID", "SAPISID") and c.get("value")
                            for c in yt_cookies
                        )
                        has_sid = any(
                            c.get("name") in ("SID", "__Secure-3PSID", "LOGIN_INFO") and c.get("value")
                            for c in yt_cookies
                        )

                        if has_sapisid and has_sid:
                            cookie_pairs = [f"{c['name']}={c['value']}" for c in yt_cookies]
                            cookie_str = "; ".join(cookie_pairs)
                            self._save_auth_cookie_string(cookie_str)
                            _kill_process_tree(proc.pid)
                            self.reload_client()
                            return {"status": "success", "message": "Accesso completato con successo!"}
                except Exception:
                    pass

                if cancel_event:
                    cancel_event.wait(1.0)
                else:
                    time.sleep(1.0)

            _kill_process_tree(proc.pid)
            raise TimeoutError("Tempo scaduto per l'accesso (timeout 3 minuti).")
        finally:
            if proc.poll() is None:
                _kill_process_tree(proc.pid)

    def get_user_playlists(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Recupera le playlist personali dell'utente dall'account connesso."""
        client = self._client()
        if not self.is_authenticated or client is None:
            return []
        try:
            raw = client.get_library_playlists(limit=limit)
            playlists = []
            for item in raw:
                pid = item.get("playlistId")
                if not pid:
                    continue
                thumbs = item.get("thumbnails") or []
                thumb = thumbs[-1].get("url", "") if thumbs else ""
                playlists.append({
                    "playlistId": pid,
                    "title": item.get("title", "La mia playlist"),
                    "count": item.get("count", ""),
                    "thumbnail": thumb,
                    "url": f"https://music.youtube.com/playlist?list={pid}",
                })
            return playlists
        except Exception as e:
            print(f"[Music] Errore lettura playlist personali: {e}")
            return []

    @staticmethod
    def _format_ytm_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        vid = item.get("videoId")
        if not vid:
            return None
        artists = item.get("artists") or []
        artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")) or item.get("author") or "YouTube"
        thumbs = item.get("thumbnails") or []
        return {
            "videoId": vid,
            "title": item.get("title") or "Brano",
            "artist": artist,
            "duration": item.get("duration") or "",
            "duration_seconds": float(item.get("duration_seconds") or parse_duration(item.get("duration"))),
            "thumbnail": (thumbs[-1].get("url") if thumbs else "") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "source": "youtube",
        }

    # ------------------------------------------------------------- ricerca
    def search_tracks(self, query: str, limit: int = 12, tone_profile: str = "") -> List[Dict[str, Any]]:
        q = query.strip()
        if "instrumental" not in q.lower():
            q += " instrumental"
        key = f"{q.lower()}|{limit}|{tone_profile}"
        hit = self._search_cache.get(key)
        if hit and time.time() - hit[0] < 1800:
            return list(hit[1])

        tracks: List[Dict[str, Any]] = []
        seen: set[str] = set()
        client = self._client()
        if client is not None:
            for flt in ("songs", "videos"):
                try:
                    for item in client.search(q, filter=flt, limit=limit * 2):
                        t = self._format_ytm_item(item)
                        if t and t["videoId"] not in seen and is_track_acceptable(t["title"], t["artist"], tone_profile):
                            seen.add(t["videoId"])
                            tracks.append(t)
                except Exception as e:
                    print(f"[Music] ricerca {flt} fallita: {e}")
                if len(tracks) >= limit:
                    break
        if len(tracks) < 3:
            for t in self.ytdlp.search_video_ids(q, limit=limit):
                if t["videoId"] not in seen and is_track_acceptable(t["title"], t["artist"], tone_profile):
                    seen.add(t["videoId"])
                    t.update({"thumbnail": f"https://i.ytimg.com/vi/{t['videoId']}/hqdefault.jpg", "source": "youtube"})
                    tracks.append(t)
        tracks = tracks[:limit]
        if tracks:
            self._search_cache[key] = (time.time(), tracks)
        return tracks

    # ------------------------------------------------------------ playlist
    @staticmethod
    def extract_yt_playlist_id(text: str) -> str:
        t = (text or "").strip()
        if "list=" in t:
            try:
                qs = parse_qs(urlparse(t).query)
                if qs.get("list"):
                    return qs["list"][0]
            except Exception:
                pass
            m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", t)
            if m:
                return m.group(1)
        return t[2:] if t.startswith("VL") else t

    def load_playlist(self, text: str, limit: int = 40) -> Dict[str, Any]:
        """Carica una playlist YouTube/YT Music o Spotify (i brani Spotify vengono risolti in modo pigro)."""
        if SpotifyCatalog.is_spotify_input(text):
            return self.spotify.playlist(text, limit=limit)
        pid = self.extract_yt_playlist_id(text)
        if not pid:
            raise ValueError("Link o ID della playlist non valido.")
        client = self._client()
        if client is not None:
            try:
                pl = client.get_playlist(pid, limit=limit)
                tracks = [t for t in (self._format_ytm_item(i) for i in pl.get("tracks") or []) if t]
                if tracks:
                    return {"title": pl.get("title") or "Playlist", "tracks": tracks, "playlistId": pid}
            except Exception as e:
                print(f"[Music] ytmusicapi playlist fallita, uso yt-dlp: {e}")
        info = self.ytdlp.playlist_entries(pid, limit=limit)
        tracks = [{
            "videoId": e["id"], "title": e.get("title") or "Brano",
            "artist": e.get("channel") or e.get("uploader") or "YouTube",
            "duration_seconds": float(e.get("duration") or 0),
            "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg", "source": "youtube",
        } for e in info.get("entries") or [] if e.get("id")]
        return {"title": info.get("title") or "Playlist", "tracks": tracks, "playlistId": pid}

    # ------------------------------------------------- Spotify → YouTube
    def resolve_to_video_id(self, track: Dict[str, Any], tone_profile: str = "") -> str:
        """Per i brani senza videoId (es. Spotify) trova il miglior candidato YouTube."""
        if track.get("videoId"):
            return track["videoId"]
        key = f"{track.get('artist','')}|{track.get('title','')}".lower()
        if key in self._resolve_cache:
            return self._resolve_cache[key]
        target_dur = float(track.get("duration_seconds") or 0)
        query = f"{track.get('artist','')} {track.get('title','')}".strip()
        candidates: List[Dict[str, Any]] = []
        client = self._client()
        if client is not None:
            for flt in ("songs", "videos"):
                try:
                    candidates += [t for t in (self._format_ytm_item(i) for i in client.search(query, filter=flt, limit=6)) if t]
                except Exception:
                    pass
        if not candidates:
            candidates = self.ytdlp.search_video_ids(query, limit=6)

        def score(c: Dict[str, Any]) -> float:
            s = difflib.SequenceMatcher(None, (track.get("title") or "").lower(), (c.get("title") or "").lower()).ratio() * 3.0
            if not is_track_acceptable(c.get("title", ""), c.get("artist", ""), tone_profile):
                s -= 5.0
            if _INSTR_RE.search(c.get("title", "")):
                s += 0.5
            cd = float(c.get("duration_seconds") or 0)
            if target_dur and cd:
                diff = abs(cd - target_dur)
                s += 2.0 if diff <= 5 else (1.0 if diff <= 15 else (-1.0 if diff > 60 else 0.0))
            return s

        if not candidates:
            raise RuntimeError(f"Nessun audio trovato per '{query}'")
        best = max(candidates, key=score)
        if score(best) < 0:
            raise RuntimeError(f"Nessun candidato strumentale affidabile per '{query}'")
        vid = best["videoId"]
        self._resolve_cache[key] = vid
        track["videoId"] = vid
        return vid

    # ------------------------------------------------------- libreria locale
    @staticmethod
    def local_tracks(mood_id: str) -> List[Dict[str, Any]]:
        candidates: List[Path] = []
        folder = LOCAL_MUSIC_DIR / mood_id
        if folder.exists():
            candidates = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in LOCAL_EXTS]
        if not candidates and LOCAL_MUSIC_DIR.exists():
            candidates = [p for p in LOCAL_MUSIC_DIR.rglob("*") if p.is_file() and p.suffix.lower() in LOCAL_EXTS]
        random.shuffle(candidates)
        return [
            {
                "local_path": str(p),
                "title": p.stem,
                "artist": "Libreria locale",
                "source": "local",
                "thumbnail": "",
            }
            for p in candidates
        ]

    def resolve_playable(self, track: Dict[str, Any], tone_profile: str = "") -> Dict[str, Any]:
        """Restituisce {uri, duration, http_headers, skip_segments} per qualsiasi tipo di brano."""
        if track.get("local_path"):
            return {
                "uri": track["local_path"],
                "title": track.get("title", "Traccia locale"),
                "artist": track.get("artist", "Libreria locale"),
                "duration": float(track.get("duration_seconds", 0.0)),
                "http_headers": {},
                "skip_segments": [],
                "cached": True,
            }
        vid = self.resolve_to_video_id(track, tone_profile)
        res = self.ytdlp.resolve_stream(vid)
        if not res.get("title") and track.get("title"):
            res["title"] = track["title"]
        if not res.get("artist") and track.get("artist"):
            res["artist"] = track["artist"]
        return res
