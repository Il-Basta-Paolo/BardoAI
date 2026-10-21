"""
Servizio di integrazione con YouTube Music (tramite ytmusicapi e yt-dlp).
Supporta:
- Ricerca brani, video e playlist su YouTube Music (anche senza login)
- Login 1-Click tramite finestra dedicata Google / YouTube Music (Edge/Chrome App Mode + CDP)
- Parser universale per Cookie / cURL / Request Headers (calcola automaticamente SAPISIDHASH)
- Lettura delle playlist personali dell'account YouTube Music o tramite link/ID playlist
- Estrazione URL stream audio diretto tramite yt-dlp
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

# Impedisci a yt-dlp (e a qualsiasi sottoprocesso interno come 'ver' o 'deno')
# di far lampeggiare finestre console nere quando l'app gira come .exe su Windows
if sys.platform == "win32":
    _orig_popen_init = subprocess.Popen.__init__

    def _silent_popen_init(self, *args, **kwargs):
        if not kwargs.pop("_allow_window", False):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _silent_popen_init  # type: ignore

import httpx
import websocket
from ytmusicapi import YTMusic
from ytmusicapi.helpers import get_authorization
import yt_dlp

from storage import YTMUSIC_AUTH_FILE, DATA_DIR, ensure_data_dir
from spotify_service import SpotifyService


class YTMusicService:
    def __init__(self) -> None:
        self.ytm: YTMusic = YTMusic()
        self.spotify: SpotifyService = SpotifyService()
        self.active_provider: str = "spotify" if self.spotify.is_authenticated else "ytmusic"
        self.is_authenticated: bool = False
        self._search_cache: Dict[str, Dict[str, Any]] = {}
        self._stream_cache: Dict[str, Dict[str, Any]] = {}
        self._ydl_lock = threading.Lock()
        self._ydl = yt_dlp.YoutubeDL({
            "format": "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 6,
        })
        self._reload_client()

    def _reload_client(self) -> None:
        ensure_data_dir()
        if YTMUSIC_AUTH_FILE.exists():
            try:
                self.ytm = YTMusic(str(YTMUSIC_AUTH_FILE))
                self.is_authenticated = True
                return
            except Exception as e:
                print(f"[YTMusic] Impossibile caricare auth file, uso modalita ospite: {e}")
        self.ytm = YTMusic()
        self.is_authenticated = False

    def get_auth_status(self) -> Dict[str, Any]:
        return {
            "authenticated": self.is_authenticated,
            "auth_file_exists": YTMUSIC_AUTH_FILE.exists()
        }

    @staticmethod
    def _save_auth_cookie_string(cookie_str: str, authuser: str = "0") -> None:
        """
        Costruisce e salva il file `ytmusic_auth.json` completo partendo dalla stringa Cookie.
        Calcola automaticamente l'header `authorization: SAPISIDHASH ...` richiesto da ytmusicapi.
        """
        m = re.search(r"(?:__Secure-3PAPISID|SAPISID)=([^;\s\"']+)", cookie_str)
        if not m:
            raise ValueError(
                "Cookie di sessione Google (__Secure-3PAPISID) non trovato. "
                "Assicurati di aver effettuato l'accesso su music.youtube.com."
            )
        sapisid = m.group(1).strip()
        if "__Secure-3PAPISID=" not in cookie_str:
            cookie_str = f"__Secure-3PAPISID={sapisid}; " + cookie_str

        origin = "https://music.youtube.com"
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
            "x-goog-authuser": authuser,
            "cookie": cookie_str,
            "authorization": get_authorization(f"{sapisid} {origin}"),
        }
        ensure_data_dir()
        with open(YTMUSIC_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(headers, f, indent=2)

    def login_with_browser_window(self, timeout_sec: int = 180) -> Dict[str, Any]:
        """
        Apre una finestra dedicata di Microsoft Edge o Google Chrome su music.youtube.com.
        Non appena l'utente effettua il login con il proprio account Google, cattura automaticamente
        i cookie di sessione tramite DevTools Protocol locale, salva l'autenticazione e chiude la finestra.
        """
        browser_candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        browser_exe = next((p for p in browser_candidates if os.path.exists(p)), None)
        if not browser_exe:
            raise ValueError("Microsoft Edge o Google Chrome non trovato sul sistema.")

        ensure_data_dir()
        profile_dir = DATA_DIR / "ytm_browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        debug_port = 9239

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

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, _allow_window=True)
        start_ts = time.time()

        try:
            while time.time() - start_ts < timeout_sec:
                if proc.poll() is not None:
                    raise ValueError("La finestra di login è stata chiusa prima di completare l'accesso.")

                try:
                    resp = httpx.get(f"http://127.0.0.1:{debug_port}/json", timeout=2.0)
                    targets = resp.json()
                    ws_url = next(
                        (t.get("webSocketDebuggerUrl") for t in targets if t.get("webSocketDebuggerUrl")),
                        None,
                    )
                    if ws_url:
                        ws = websocket.create_connection(ws_url, timeout=3)
                        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
                        raw_msg = json.loads(ws.recv())
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
                        # Verifica che ci sia anche SID / __Secure-3PSID per garantire login completo
                        has_sid = any(
                            c.get("name") in ("SID", "__Secure-3PSID", "LOGIN_INFO") and c.get("value")
                            for c in yt_cookies
                        )

                        if has_sapisid and has_sid:
                            cookie_pairs = [f"{c['name']}={c['value']}" for c in yt_cookies]
                            cookie_str = "; ".join(cookie_pairs)
                            self._save_auth_cookie_string(cookie_str)
                            self._reload_client()
                            playlists = self.get_user_playlists(limit=30)
                            return {
                                "authenticated": True,
                                "playlists_count": len(playlists),
                                "playlists": playlists,
                            }
                except Exception:
                    pass

                time.sleep(1.5)

            raise ValueError("Tempo scaduto per il login (3 minuti). Riprova.")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    def connect_with_headers(self, raw_input: str) -> Dict[str, Any]:
        """
        Parser universale: accetta qualsiasi formato incollato dall'utente:
        - "Copy as cURL (cmd / bash)"
        - "Copy as fetch"
        - Request Headers di Chrome / Edge / Firefox (anche su più righe o senza authorization)
        - File cookies.txt (Netscape) o stringa Cookie diretta
        """
        text = raw_input.strip()
        if not text:
            raise ValueError("Il testo incollato è vuoto.")

        # Rimuovi gli escape di cURL Windows (^" , ^% , ^& , ecc.)
        cleaned = re.sub(r"\^([\"%&|^<> ])", r"\1", text)
        cleaned = cleaned.replace("\\\"", "\"")

        cookie_str = ""
        authuser = "0"

        # Caso 1: Formato Netscape cookies.txt (righe separate da tab con .youtube.com)
        if ".youtube.com\t" in cleaned:
            pairs = []
            for line in cleaned.splitlines():
                if ".youtube.com" in line and not line.startswith("#"):
                    parts = line.strip().split("\t")
                    if len(parts) >= 7:
                        pairs.append(f"{parts[5]}={parts[6]}")
            cookie_str = "; ".join(pairs)

        # Caso 2: Contiene direttamenente __Secure-3PAPISID=... o SAPISID=...
        if not cookie_str:
            # Cerca una riga o valore con __Secure-3PAPISID
            for line in cleaned.splitlines():
                if "__Secure-3PAPISID=" in line or "SAPISID=" in line:
                    # Estrai la porzione di cookie
                    line_clean = re.sub(r"^.*?[cC]ookie['\"\s:=-]+", "", line).strip(" '\"\r\n;,")
                    if "=" in line_clean:
                        cookie_str = line_clean
                        break

        m_auth = re.search(r"x-goog-authuser['\"\s:]+(\d+)", cleaned, re.IGNORECASE)
        if m_auth:
            authuser = m_auth.group(1)

        if not cookie_str:
            raise ValueError(
                "Non ho trovato il cookie '__Secure-3PAPISID' nel testo incollato. "
                "Usa il pulsante '🔑 Accedi con Finestra Google / YouTube Music' qui sopra per entrare con un clic!"
            )

        try:
            self._save_auth_cookie_string(cookie_str, authuser=authuser)
            self._reload_client()
            playlists = self.get_user_playlists(limit=30)
            return {
                "authenticated": True,
                "playlists_count": len(playlists),
                "playlists": playlists,
            }
        except Exception as e:
            self.disconnect_account()
            raise ValueError(f"Autenticazione non riuscita: {e}")

    def disconnect_account(self) -> None:
        if YTMUSIC_AUTH_FILE.exists():
            try:
                YTMUSIC_AUTH_FILE.unlink()
            except Exception:
                pass
        self._reload_client()

    @staticmethod
    def extract_playlist_id(playlist_input: str) -> str:
        text = playlist_input.strip()
        if not text:
            return ""
        if "http://" in text or "https://" in text or "youtube.com" in text:
            try:
                parsed = urlparse(text)
                qs = parse_qs(parsed.query)
                if "list" in qs and qs["list"]:
                    return qs["list"][0]
            except Exception:
                pass
            match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", text)
            if match:
                return match.group(1)
        return text

    def _format_track(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        video_id = item.get("videoId")
        if not video_id:
            return None

        title = item.get("title") or "Traccia Sconosciuta"
        artists_list = item.get("artists") or []
        if isinstance(artists_list, list) and artists_list:
            artist = ", ".join(a.get("name", "") for a in artists_list if isinstance(a, dict) and a.get("name"))
        else:
            artist = item.get("author") or "YouTube Music"

        thumbnails = item.get("thumbnails") or []
        thumbnail = ""
        if isinstance(thumbnails, list) and thumbnails:
            thumbnail = thumbnails[-1].get("url", "")
        if not thumbnail:
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        duration = item.get("duration") or ""
        return {
            "videoId": video_id,
            "title": title,
            "artist": artist or "YouTube Music",
            "duration": duration,
            "thumbnail": thumbnail,
            "ytmusic_url": f"https://music.youtube.com/watch?v={video_id}"
        }

    @staticmethod
    def _is_track_matching_tone(track: Dict[str, Any], tone_profile: str = "") -> bool:
        """
        Filtra rigorosamente i risultati di YouTube Music garantendo:
        1. SOLO MUSICA 100% STRUMENTALE (niente cantato, niente parole, niente cori cantati, niente feat. vocali).
        2. Niente podcast, audiolibri, episodi parlati o remix fuori contesto.
        3. Coerenza con il ritmo e il tono della scena (es. vieta brani lenti/ambient in combattimento).
        """
        title_low = (track.get("title") or "").lower()
        artist_low = (track.get("artist") or "").lower()
        combined = f"{title_low} {artist_low}"
        is_explicit_instrumental = "instrumental" in title_low or "no vocal" in title_low or "karaoke" in title_low

        # 1. Escludi SEMPRE podcast, episodi parlati, audiolibri, vlog, slowed+reverb
        junk_markers = (
            "podcast", "episodio", "episode", "actual play", "audiobook",
            "hoerspiel", "hörspiel", "roman", "kapitel", "chapter",
            "vlog", "reacts", "interview", "trap remix", "slowed", "reverb",
            "8-bit", "chip-tune", "asmr", "rap beat",
        )
        if any(jm in combined for jm in junk_markers):
            return False

        # 2. VETO RIGIDO ANTI-CANTATO / ANTI-PAROLE: solo musica strumentale!
        vocal_markers = (
            "with lyrics", "lyrics", "lyric video", "vocal", "vocals", "singing",
            "sung by", "singer", "feat.", "feat ", "ft.", "ft ",
            "choir", "chant", "chanting", "soprano", "tenor", "opera",
            "percival", "miracle of sound", "danheim", "wardruna", "heilung",
            "sabaton", "powerwolf", "nightwish", "evanescence", "linkin park",
            "imagine dragons", "skillet", "halocene", "malukah", "peter hollens",
            "priscilla", "wolven storm", "steel for humans", "silver for monsters",
            "banana tiger", "raphael's final act", "weeping dawn", "song of balduran",
            "the cove battle siren", "jennifer chao", "julie elven", "merethe soltvedt",
            "bard song", "tavern song", "sea shanty", "shanties",
        )
        if any(vm in combined for vm in vocal_markers):
            return False

        # Alcuni brani celebri hanno una versione cantata e una versione "(Instrumental)"
        vocal_unless_instrumental = (
            "down by the river",
            "i want to live",
            "dragonborn",
            "victory",
            "sixteen strikes",
            "fields of ard skellig",
        )
        if any(vui in title_low for vui in vocal_unless_instrumental) and not is_explicit_instrumental:
            return False

        # 3. Controllo coerenza Ritmo & Tono della scena
        if tone_profile in ("fast_combat", "epic_boss"):
            # In combattimento o boss fight, vieta assolutamente brani lenti, ambient, villaggi o riposo!
            calm_markers = (
                "ambient", "ambience", "village", "relax", "sleep", "peaceful",
                "calm", "tavern", "inn", "campfire", "lullaby", "secunda",
                "masser", "atmospheres", "far horizons", "kyne", "gwent",
                "banjo", "meditation", "study", "piano cover", "guitar cover",
                "light version", "explore the ruins",
            )
            if any(cm in combined for cm in calm_markers):
                return False

        elif tone_profile in ("calm_rest", "exploration", "upbeat_tavern", "city"):
            # Durante riposo, esplorazione o taverna, vieta brani di boss fight, horror o metallo pesante
            aggressive_markers = (
                "boss fight", "final boss", "combat", "metal cover", "terror",
                "nightmare", "horror", "slayer", "bloodborne", "godskin",
            )
            if any(am in combined for am in aggressive_markers):
                return False

        return True

    def search_tracks(self, query: str, limit: int = 12, tone_profile: str = "") -> List[Dict[str, Any]]:
        clean_q = query.strip()
        if "instrumental" not in clean_q.lower():
            clean_q = f"{clean_q} instrumental"

        cache_key = f"{self.active_provider}:{clean_q.lower()}:{limit}:{tone_profile}"
        now = time.time()
        if cache_key in self._search_cache:
            cached = self._search_cache[cache_key]
            if now - cached["ts"] < 1800 and cached["tracks"]:
                return cached["tracks"]

        tracks: List[Dict[str, Any]] = []
        seen_ids = set()

        # 1. Se il provider attivo è Spotify ed è presente un token API valido, cerca prima su Spotify!
        if self.active_provider == "spotify":
            sp_results = self.spotify.search_tracks(clean_q, limit=limit * 2)
            for sp_t in sp_results:
                if sp_t["videoId"] not in seen_ids and self._is_track_matching_tone(sp_t, tone_profile):
                    seen_ids.add(sp_t["videoId"])
                    tracks.append(sp_t)
                    if len(tracks) >= limit:
                        break

        # 2. Integra con YouTube Music se servono altri brani
        if len(tracks) < limit:
            for search_filter in ["songs", "videos"]:
                try:
                    results = self.ytm.search(clean_q, filter=search_filter, limit=limit * 2)
                    for item in results:
                        formatted = self._format_track(item)
                        if (
                            formatted
                            and formatted["videoId"] not in seen_ids
                            and self._is_track_matching_tone(formatted, tone_profile)
                        ):
                            seen_ids.add(formatted["videoId"])
                            tracks.append(formatted)
                            if len(tracks) >= limit:
                                break
                except Exception as e:
                    print(f"[YTMusic] Errore ricerca ({search_filter}) per '{clean_q}': {e}")
                if len(tracks) >= limit:
                    break

        if len(tracks) < 3:
            try:
                results = self.ytm.search(clean_q, limit=limit * 2)
                for item in results:
                    formatted = self._format_track(item)
                    if (
                        formatted
                        and formatted["videoId"] not in seen_ids
                        and self._is_track_matching_tone(formatted, tone_profile)
                    ):
                        seen_ids.add(formatted["videoId"])
                        tracks.append(formatted)
                        if len(tracks) >= limit:
                            break
            except Exception as e:
                print(f"[YTMusic] Errore ricerca generica per '{clean_q}': {e}")

        if tracks:
            self._search_cache[cache_key] = {"ts": now, "tracks": tracks}
        return tracks

    def search_playlists(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        playlists: List[Dict[str, Any]] = []
        try:
            results = self.ytm.search(query, filter="playlists", limit=limit)
            for item in results:
                browse_id = item.get("browseId") or item.get("playlistId")
                if not browse_id:
                    continue
                playlist_id = browse_id[2:] if browse_id.startswith("VL") else browse_id
                thumbs = item.get("thumbnails") or []
                thumb = thumbs[-1].get("url", "") if thumbs else ""
                playlists.append({
                    "playlistId": playlist_id,
                    "title": item.get("title", "Playlist YouTube Music"),
                    "author": item.get("author", "YouTube Music"),
                    "itemCount": item.get("itemCount", ""),
                    "thumbnail": thumb,
                    "url": f"https://music.youtube.com/playlist?list={playlist_id}"
                })
        except Exception as e:
            print(f"[YTMusic] Errore ricerca playlist per '{query}': {e}")
        return playlists

    def get_playlist_tracks(self, playlist_input: str, limit: int = 40) -> Dict[str, Any]:
        # Se l'input è una playlist Spotify (URL open.spotify.com/playlist/..., URI spotify:playlist:... o ID 22 char),
        # usa automaticamente il motore Spotify!
        if self.spotify.is_spotify_playlist_input(playlist_input):
            return self.spotify.get_playlist_tracks(playlist_input, limit=limit)

        playlist_id = self.extract_playlist_id(playlist_input)
        if not playlist_id:
            raise ValueError("ID o URL della playlist non valido.")

        if playlist_id.startswith("VL"):
            playlist_id = playlist_id[2:]

        try:
            pl_data = self.ytm.get_playlist(playlist_id, limit=limit)
            raw_tracks = pl_data.get("tracks") or []
            tracks = []
            for item in raw_tracks:
                formatted = self._format_track(item)
                if formatted:
                    tracks.append(formatted)

            thumbs = pl_data.get("thumbnails") or []
            thumb = thumbs[-1].get("url", "") if thumbs else (tracks[0]["thumbnail"] if tracks else "")

            return {
                "playlistId": playlist_id,
                "title": pl_data.get("title") or "Playlist YouTube Music",
                "description": pl_data.get("description") or "",
                "trackCount": len(tracks),
                "thumbnail": thumb,
                "url": f"https://music.youtube.com/playlist?list={playlist_id}",
                "tracks": tracks
            }
        except Exception as e:
            try:
                return self._get_playlist_via_ytdlp(playlist_id, limit=limit)
            except Exception:
                raise ValueError(f"Impossibile caricare la playlist '{playlist_id}': {str(e)}")

    def _get_playlist_via_ytdlp(self, playlist_id: str, limit: int = 30) -> Dict[str, Any]:
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "playlistend": limit,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = info.get("entries") or []
            tracks = []
            for entry in entries:
                vid = entry.get("id")
                if not vid:
                    continue
                tracks.append({
                    "videoId": vid,
                    "title": entry.get("title") or "Traccia",
                    "artist": entry.get("uploader") or entry.get("channel") or "YouTube Music",
                    "duration": str(entry.get("duration") or ""),
                    "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "ytmusic_url": f"https://music.youtube.com/watch?v={vid}"
                })
            return {
                "playlistId": playlist_id,
                "title": info.get("title") or "Playlist YouTube",
                "description": info.get("description") or "",
                "trackCount": len(tracks),
                "thumbnail": tracks[0]["thumbnail"] if tracks else "",
                "url": f"https://music.youtube.com/playlist?list={playlist_id}",
                "tracks": tracks
            }

    def get_user_playlists(self, limit: int = 30) -> List[Dict[str, Any]]:
        if not self.is_authenticated:
            return []
        try:
            raw = self.ytm.get_library_playlists(limit=limit)
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
                    "url": f"https://music.youtube.com/playlist?list={pid}"
                })
            return playlists
        except Exception as e:
            print(f"[YTMusic] Errore lettura playlist utente: {e}")
            return []

    def get_direct_audio_url(self, video_id: str) -> Dict[str, Any]:
        now = time.time()
        if video_id in self._stream_cache:
            cached = self._stream_cache[video_id]
            if now - cached["ts"] < 3600:
                return cached["data"]

        # Se è un brano proveniente da Spotify (`sp:<spotify_track_id>`), risolve il flusso audio completo
        # preservando titolo, artista e copertina originali di Spotify!
        sp_meta: Optional[Dict[str, Any]] = None
        target_yt_id = video_id
        if video_id.startswith("sp:"):
            sp_meta = self.spotify.get_track_metadata(video_id)
            if sp_meta:
                q_str = f"{sp_meta.get('artist', '')} {sp_meta.get('title', '')}".strip()
                resolved_id = ""
                for s_filter in ("songs", "videos"):
                    try:
                        res = self.ytm.search(q_str, filter=s_filter, limit=2)
                        if res and res[0].get("videoId"):
                            resolved_id = res[0]["videoId"]
                            break
                    except Exception:
                        pass
                if resolved_id:
                    target_yt_id = resolved_id
                else:
                    target_yt_id = f"ytsearch1:{q_str} audio"

        url = (
            target_yt_id
            if target_yt_id.startswith("ytsearch1:")
            else f"https://music.youtube.com/watch?v={target_yt_id}"
        )
        with self._ydl_lock:
            if video_id in self._stream_cache:
                cached = self._stream_cache[video_id]
                if now - cached["ts"] < 3600:
                    return cached["data"]
            info = self._ydl.extract_info(url, download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            data = {
                "videoId": video_id,
                "stream_url": info.get("url"),
                "title": (sp_meta.get("title") if sp_meta else None) or info.get("title") or "Traccia",
                "artist": (sp_meta.get("artist") if sp_meta else None) or info.get("artist") or info.get("uploader") or "Spotify / YT Music",
                "duration": info.get("duration") or 0,
                "thumbnail": (sp_meta.get("thumbnail") if sp_meta and sp_meta.get("thumbnail") else None)
                or info.get("thumbnail")
                or f"https://i.ytimg.com/vi/{target_yt_id}/hqdefault.jpg",
            }
            self._stream_cache[video_id] = {"ts": now, "data": data}
            return data
