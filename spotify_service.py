"""
Servizio di integrazione Spotify per Bardo AI:
- Login 1-Click tramite finestra dedicata Spotify Web (`open.spotify.com` via Chrome/Edge CDP)
- Supporto alternativo per Client ID + Client Secret (Spotify Developer API) o incolla Cookie `sp_dc` / Token / cURL
- Lettura immediata di qualsiasi Playlist Spotify (`https://open.spotify.com/playlist/...` o `spotify:playlist:...`)
  sia tramite Spotify Web API sia tramite l'endpoint embed (`open.spotify.com/embed/playlist/...`) che funziona anche senza API key!
- Catalogo integrato di Playlist Spotify GDR 100% strumentali pronte all'uso.
"""

import base64
import json
import os
import re
import subprocess
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import httpx
import websocket

from storage import SPOTIFY_AUTH_FILE, ensure_data_dir

# Playlist Spotify GDR / Fantasy / Sci-Fi / Horror certificate e pronte all'uso
CURATED_SPOTIFY_RPG_PLAYLISTS: List[Dict[str, str]] = [
    {
        "playlistId": "37i9dQZF1DXdfOcg1fm0VG",
        "title": "🎮 Video Game Soundtracks (Spotify Official)",
        "count": "100 brani",
        "url": "https://open.spotify.com/playlist/37i9dQZF1DXdfOcg1fm0VG",
    },
    {
        "playlistId": "37i9dQZF1DWZeKCadgRdKQ",
        "title": "🐉 Deep Focus / Atmospheric Instrumental (Spotify)",
        "count": "150 brani",
        "url": "https://open.spotify.com/playlist/37i9dQZF1DWZeKCadgRdKQ",
    },
    {
        "playlistId": "37i9dQZF1DX1tz6EDao8it",
        "title": "⚔️ Epic Instrumental & Orchestral Scores (Spotify)",
        "count": "80 brani",
        "url": "https://open.spotify.com/playlist/37i9dQZF1DX1tz6EDao8it",
    },
]


class SpotifyService:
    def __init__(self) -> None:
        self.is_authenticated: bool = False
        self.auth_data: Dict[str, Any] = {}
        self.track_meta_cache: Dict[str, Dict[str, Any]] = {}
        self._load_auth()

    def _load_auth(self) -> None:
        ensure_data_dir()
        if SPOTIFY_AUTH_FILE.exists():
            try:
                with open(SPOTIFY_AUTH_FILE, "r", encoding="utf-8") as f:
                    self.auth_data = json.load(f)
                self.is_authenticated = bool(
                    self.auth_data.get("sp_dc")
                    or self.auth_data.get("access_token")
                    or (self.auth_data.get("client_id") and self.auth_data.get("client_secret"))
                    or self.auth_data.get("playlists")
                )
            except Exception as e:
                print(f"[Spotify] Errore lettura credenziali salvate: {e}")
                self.auth_data = {}
                self.is_authenticated = False
        else:
            self.auth_data = {}
            self.is_authenticated = False

    def _save_auth(self) -> None:
        ensure_data_dir()
        with open(SPOTIFY_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(self.auth_data, f, ensure_ascii=False, indent=2)
        self.is_authenticated = bool(
            self.auth_data.get("sp_dc")
            or self.auth_data.get("access_token")
            or (self.auth_data.get("client_id") and self.auth_data.get("client_secret"))
            or self.auth_data.get("playlists")
        )

    def get_auth_status(self) -> Dict[str, Any]:
        return {
            "authenticated": self.is_authenticated,
            "user_name": self.auth_data.get("user_name") or ("Account Spotify" if self.is_authenticated else ""),
            "method": self.auth_data.get("method", ""),
            "playlists_count": len(self.auth_data.get("playlists") or []),
            "auth_file_exists": SPOTIFY_AUTH_FILE.exists(),
        }

    def disconnect_account(self) -> None:
        self.auth_data = {}
        self.is_authenticated = False
        if SPOTIFY_AUTH_FILE.exists():
            try:
                SPOTIFY_AUTH_FILE.unlink()
            except Exception:
                pass

    def _get_valid_access_token(self) -> str:
        """
        Restituisce un Bearer access_token valido se disponibile (o lo rinnova tramite Client ID + Secret).
        """
        now = time.time()
        token = self.auth_data.get("access_token", "")
        expires_at = float(self.auth_data.get("token_expires_at") or 0)

        if token and (expires_at == 0 or now < expires_at - 30):
            return token

        # Se abbiamo client_id e client_secret, rinnova automaticamente il token!
        client_id = (self.auth_data.get("client_id") or "").strip()
        client_secret = (self.auth_data.get("client_secret") or "").strip()
        if client_id and client_secret:
            try:
                b64 = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
                resp = httpx.post(
                    "https://accounts.spotify.com/api/token",
                    headers={
                        "Authorization": f"Basic {b64}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"grant_type": "client_credentials"},
                    timeout=6.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_tok = data.get("access_token", "")
                    exp_in = int(data.get("expires_in") or 3600)
                    if new_tok:
                        self.auth_data["access_token"] = new_tok
                        self.auth_data["token_expires_at"] = now + exp_in
                        self._save_auth()
                        return new_tok
            except Exception as e:
                print(f"[Spotify] Errore rinnovo token Client Credentials: {e}")

        return token

    def login_via_browser_window(self, timeout_sec: int = 210) -> Dict[str, Any]:
        """
        Apre una finestra dedicata su Spotify (`accounts.spotify.com` -> `open.spotify.com`).
        Non appena l'utente effettua l'accesso:
        1. Cattura il cookie di sessione `sp_dc` e il Bearer token attivo di `open.spotify.com` via CDP.
        2. Legge il profilo utente e tutte le playlist personali dalla libreria Spotify.
        3. Chiude automaticamente la finestra e salva tutto in `data/spotify_auth.json`.
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
        profile_dir = SPOTIFY_AUTH_FILE.parent / "spotify_browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        debug_port = 9242

        cmd = [
            browser_exe,
            "--app=https://accounts.spotify.com/it/login?continue=https%3A%2F%2Fopen.spotify.com%2F",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1020,740",
        ]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, _allow_window=True
        )
        start_ts = time.time()
        captured_bearer = ""
        captured_sp_dc = ""

        try:
            while time.time() - start_ts < timeout_sec:
                if proc.poll() is not None:
                    raise ValueError("La finestra di login Spotify è stata chiusa prima di completare l'accesso.")

                try:
                    resp = httpx.get(f"http://127.0.0.1:{debug_port}/json", timeout=2.0)
                    targets = resp.json()
                    target = next(
                        (
                            t
                            for t in targets
                            if t.get("webSocketDebuggerUrl")
                            and t.get("type") == "page"
                        ),
                        None,
                    )
                    if target:
                        ws_url = target["webSocketDebuggerUrl"]
                        page_url = target.get("url", "")
                        ws = websocket.create_connection(ws_url, timeout=3.0)
                        try:
                            # 1. Controlla i cookie di Spotify
                            ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
                            raw_msg = json.loads(ws.recv())
                            cookies = raw_msg.get("result", {}).get("cookies", [])
                            for c in cookies:
                                if "spotify.com" in c.get("domain", "") and c.get("name") == "sp_dc" and c.get("value"):
                                    captured_sp_dc = c["value"]

                            # 2. Se l'utente ha fatto login ed è atterrato su open.spotify.com
                            if captured_sp_dc and "open.spotify.com" in page_url:
                                # Attendi 2.5 secondi affinché la sidebar di Spotify Web carichi le playlist
                                time.sleep(2.5)
                                js_extract = """
                                (() => {
                                    const result = { token: '', userName: '', playlists: [] };
                                    try {
                                        const sessionEl = document.getElementById('session');
                                        if (sessionEl) {
                                            const sData = JSON.parse(sessionEl.textContent);
                                            if (sData && sData.accessToken) result.token = sData.accessToken;
                                        }
                                    } catch (e) {}
                                    try {
                                        const profileBtn = document.querySelector('[data-testid="user-widget-link"]');
                                        if (profileBtn && profileBtn.getAttribute('aria-label')) {
                                            result.userName = profileBtn.getAttribute('aria-label');
                                        }
                                    } catch (e) {}
                                    try {
                                        const seen = new Set();
                                        const links = document.querySelectorAll('a[href*="/playlist/"]');
                                        links.forEach(a => {
                                            const href = a.getAttribute('href') || '';
                                            const m = href.match(/playlist\\/([a-zA-Z0-9]{22})/);
                                            if (m && !seen.has(m[1])) {
                                                seen.add(m[1]);
                                                let title = (a.textContent || a.getAttribute('aria-label') || '').trim();
                                                if (!title && a.parentElement) title = (a.parentElement.textContent || '').trim();
                                                if (title) {
                                                    result.playlists.push({
                                                        playlistId: m[1],
                                                        title: title.slice(0, 75),
                                                        count: 'Spotify',
                                                        url: 'https://open.spotify.com/playlist/' + m[1]
                                                    });
                                                }
                                            }
                                        });
                                    } catch (e) {}
                                    return JSON.stringify(result);
                                })()
                                """
                                ws.send(
                                    json.dumps(
                                        {
                                            "id": 2,
                                            "method": "Runtime.evaluate",
                                            "params": {"expression": js_extract, "returnByValue": True},
                                        }
                                    )
                                )
                                eval_msg = json.loads(ws.recv())
                                val_str = (
                                    eval_msg.get("result", {})
                                    .get("result", {})
                                    .get("value", "{}")
                                )
                                dom_data = json.loads(val_str) if isinstance(val_str, str) else {}
                                if dom_data.get("token"):
                                    captured_bearer = dom_data["token"]

                                user_name = dom_data.get("userName") or "Account Spotify"
                                playlists: List[Dict[str, Any]] = dom_data.get("playlists") or []

                                # Se abbiamo il Bearer token, interroga anche l'API ufficiale v1/me e v1/me/playlists
                                if captured_bearer:
                                    api_user, api_pls = self._fetch_user_and_playlists_with_token(captured_bearer)
                                    if api_user:
                                        user_name = api_user
                                    if api_pls:
                                        seen_ids = {p["playlistId"] for p in api_pls}
                                        for dp in playlists:
                                            if dp["playlistId"] not in seen_ids:
                                                api_pls.append(dp)
                                        playlists = api_pls

                                if not playlists:
                                    playlists = list(CURATED_SPOTIFY_RPG_PLAYLISTS)

                                self.auth_data = {
                                    "method": "browser_login",
                                    "sp_dc": captured_sp_dc,
                                    "access_token": captured_bearer,
                                    "token_expires_at": time.time() + 3500 if captured_bearer else 0,
                                    "user_name": user_name,
                                    "playlists": playlists,
                                    "updated_at": time.time(),
                                }
                                self._save_auth()
                                return {
                                    "authenticated": True,
                                    "user_name": user_name,
                                    "playlists_count": len(playlists),
                                    "playlists": playlists,
                                }
                        finally:
                            try:
                                ws.close()
                            except Exception:
                                pass
                except Exception:
                    pass

                time.sleep(1.5)

            raise ValueError("Tempo scaduto per il login Spotify (3 minuti). Riprova.")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    def _fetch_user_and_playlists_with_token(self, bearer_token: str) -> tuple[str, List[Dict[str, Any]]]:
        headers = {"Authorization": f"Bearer {bearer_token}"}
        user_name = ""
        playlists: List[Dict[str, Any]] = []
        try:
            r_me = httpx.get("https://api.spotify.com/v1/me", headers=headers, timeout=5.0)
            if r_me.status_code == 200:
                me_data = r_me.json()
                user_name = me_data.get("display_name") or me_data.get("id") or ""
        except Exception:
            pass

        try:
            r_pl = httpx.get("https://api.spotify.com/v1/me/playlists?limit=50", headers=headers, timeout=6.0)
            if r_pl.status_code == 200:
                items = r_pl.json().get("items") or []
                for item in items:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    pid = item["id"]
                    images = item.get("images") or []
                    thumb = images[0].get("url", "") if images else ""
                    total_tracks = (item.get("tracks") or {}).get("total", "")
                    playlists.append(
                        {
                            "playlistId": pid,
                            "title": item.get("name") or "Playlist Spotify",
                            "count": f"{total_tracks} brani" if total_tracks != "" else "Spotify",
                            "thumbnail": thumb,
                            "url": f"https://open.spotify.com/playlist/{pid}",
                        }
                    )
        except Exception:
            pass

        return user_name, playlists

    def connect_with_credentials_or_raw(
        self,
        client_id: str = "",
        client_secret: str = "",
        spotify_username: str = "",
        raw_input: str = "",
    ) -> Dict[str, Any]:
        """
        Metodo di connessione universale per Spotify:
        1. Accetta Client ID + Client Secret (Spotify Developer API) + eventuale username Spotify
        2. Oppure accetta testo incollato (Bearer token, Copy as cURL da open.spotify.com, cookie sp_dc, o URL di playlist Spotify).
        """
        cid = client_id.strip()
        csec = client_secret.strip()
        uname = spotify_username.strip()
        raw = raw_input.strip()

        # Caso 1: Client ID + Client Secret Spotify Developer
        if cid and csec:
            self.auth_data["client_id"] = cid
            self.auth_data["client_secret"] = csec
            self.auth_data["method"] = "client_credentials"
            tok = self._get_valid_access_token()
            if not tok:
                self.disconnect_account()
                raise ValueError("Client ID o Client Secret Spotify non validi.")

            playlists: List[Dict[str, Any]] = []
            if uname:
                # Estrai eventuale ID utente da link profilo https://open.spotify.com/user/...
                m_u = re.search(r"user/([a-zA-Z0-9_-]+)", uname)
                clean_user = m_u.group(1) if m_u else uname
                try:
                    r_up = httpx.get(
                        f"https://api.spotify.com/v1/users/{clean_user}/playlists?limit=50",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=6.0,
                    )
                    if r_up.status_code == 200:
                        for item in r_up.json().get("items") or []:
                            if item and item.get("id"):
                                pid = item["id"]
                                total_t = (item.get("tracks") or {}).get("total", "")
                                playlists.append(
                                    {
                                        "playlistId": pid,
                                        "title": item.get("name") or "Playlist Spotify",
                                        "count": f"{total_t} brani" if total_t != "" else "Spotify",
                                        "url": f"https://open.spotify.com/playlist/{pid}",
                                    }
                                )
                except Exception:
                    pass

            if not playlists:
                playlists = list(CURATED_SPOTIFY_RPG_PLAYLISTS)

            self.auth_data["user_name"] = uname or "Spotify API (Client ID)"
            self.auth_data["playlists"] = playlists
            self._save_auth()
            return {
                "authenticated": True,
                "user_name": self.auth_data["user_name"],
                "playlists_count": len(playlists),
                "playlists": playlists,
            }

        # Caso 2: Testo incollato (cURL, Bearer token, sp_dc cookie o link playlist Spotify)
        if not raw:
            raise ValueError(
                "Usa il pulsante '🟢 Accedi con Finestra Spotify' in alto, oppure inserisci Client ID/Secret o incolla un token/cookie/playlist."
            )

        cleaned = re.sub(r"\^([\"%&|^<> ])", r"\1", raw).replace('\\"', '"')

        # Cerca eventuale Bearer token (es. "Bearer BQA..." o token diretto "BQA...")
        m_bearer = re.search(r"Bearer\s+([A-Za-z0-9_-]{30,})", cleaned)
        bearer_tok = m_bearer.group(1) if m_bearer else ""
        if not bearer_tok and re.match(r"^BQ[A-Za-z0-9_-]{30,}$", cleaned.strip()):
            bearer_tok = cleaned.strip()

        # Cerca eventuale cookie sp_dc
        m_spdc = re.search(r"sp_dc=([A-Za-z0-9_-]{20,})", cleaned)
        sp_dc = m_spdc.group(1) if m_spdc else ""
        if not sp_dc and not bearer_tok and re.match(r"^[A-Za-z0-9_-]{60,200}$", cleaned.strip()):
            sp_dc = cleaned.strip()

        # Cerca eventuali link a playlist Spotify incollati
        playlist_ids = re.findall(r"playlist[:/]([a-zA-Z0-9]{22})", cleaned)

        user_name = "Account Spotify"
        playlists = list(self.auth_data.get("playlists") or [])

        if bearer_tok:
            u_name, api_pls = self._fetch_user_and_playlists_with_token(bearer_tok)
            if u_name:
                user_name = u_name
            if api_pls:
                playlists = api_pls

        for pid in dict.fromkeys(playlist_ids):
            try:
                pl_info = self.get_playlist_tracks(pid, limit=50)
                if not any(p.get("playlistId") == pid for p in playlists):
                    playlists.insert(
                        0,
                        {
                            "playlistId": pid,
                            "title": pl_info.get("title") or f"Playlist Spotify ({pid[:6]})",
                            "count": f"{pl_info.get('trackCount', 0)} brani",
                            "url": f"https://open.spotify.com/playlist/{pid}",
                        },
                    )
            except Exception:
                pass

        if not bearer_tok and not sp_dc and not playlist_ids:
            raise ValueError(
                "Nessun token Bearer, cookie 'sp_dc' o link Playlist Spotify trovato nel testo incollato."
            )

        if not playlists:
            playlists = list(CURATED_SPOTIFY_RPG_PLAYLISTS)

        self.auth_data.update(
            {
                "method": "manual_paste",
                "sp_dc": sp_dc or self.auth_data.get("sp_dc", ""),
                "access_token": bearer_tok or self.auth_data.get("access_token", ""),
                "token_expires_at": time.time() + 3500 if bearer_tok else self.auth_data.get("token_expires_at", 0),
                "user_name": user_name,
                "playlists": playlists,
                "updated_at": time.time(),
            }
        )
        self._save_auth()
        return {
            "authenticated": True,
            "user_name": user_name,
            "playlists_count": len(playlists),
            "playlists": playlists,
        }

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        """
        Restituisce le playlist Spotify dell'utente (aggiornandole se c'è un token attivo)
        più le playlist GDR curate se la lista è vuota.
        """
        tok = self._get_valid_access_token()
        if tok and self.auth_data.get("method") != "client_credentials":
            _, fresh_pls = self._fetch_user_and_playlists_with_token(tok)
            if fresh_pls:
                self.auth_data["playlists"] = fresh_pls
                self._save_auth()
                return fresh_pls

        saved = self.auth_data.get("playlists") or []
        return saved if saved else list(CURATED_SPOTIFY_RPG_PLAYLISTS)

    @staticmethod
    def is_spotify_playlist_input(text: str) -> bool:
        """
        Rileva se una stringa (URL, URI o ID) è una playlist Spotify.
        """
        t = (text or "").strip()
        if not t:
            return False
        if "spotify.com" in t.lower() or t.lower().startswith("spotify:"):
            return True
        # ID Spotify standard a 22 caratteri base62 (che non inizia con PL/VL/OL di YouTube)
        if re.match(r"^[a-zA-Z0-9]{22}$", t) and not t.startswith(("PL", "VL", "OL", "RD")):
            return True
        return False

    @staticmethod
    def extract_playlist_id(playlist_input: str) -> str:
        text = (playlist_input or "").strip()
        if not text:
            return ""
        m = re.search(r"playlist[:/]([a-zA-Z0-9]{22})", text)
        if m:
            return m.group(1)
        if re.match(r"^[a-zA-Z0-9]{22}$", text):
            return text
        return text

    @staticmethod
    def _format_duration_ms(ms: int) -> str:
        if not ms or ms <= 0:
            return ""
        total_sec = int(ms // 1000)
        return f"{total_sec // 60}:{total_sec % 60:02d}"

    def get_playlist_tracks(self, playlist_input: str, limit: int = 50) -> Dict[str, Any]:
        """
        Carica i brani di una playlist Spotify:
        1. Usa la Spotify Web API (`v1/playlists/{id}`) se è presente un token valido.
        2. Altrimenti usa l'estrattore veloce `open.spotify.com/embed/playlist/{id}` (funziona sempre senza API key!).
        """
        playlist_id = self.extract_playlist_id(playlist_input)
        if not playlist_id:
            raise ValueError("ID o URL della playlist Spotify non valido.")

        # Tentativo 1: Spotify Web API ufficiale se abbiamo un access_token valido
        tok = self._get_valid_access_token()
        if tok:
            try:
                resp = httpx.get(
                    f"https://api.spotify.com/v1/playlists/{playlist_id}",
                    headers={"Authorization": f"Bearer {tok}"},
                    timeout=6.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    pl_title = data.get("name") or "Playlist Spotify"
                    images = data.get("images") or []
                    pl_thumb = images[0].get("url", "") if images else ""
                    items = (data.get("tracks") or {}).get("items") or []
                    tracks: List[Dict[str, Any]] = []

                    for item in items:
                        t = (item or {}).get("track")
                        if not isinstance(t, dict) or not t.get("id"):
                            continue
                        tid = t["id"]
                        title = t.get("name") or "Brano Spotify"
                        artists = ", ".join(
                            a.get("name", "") for a in (t.get("artists") or []) if isinstance(a, dict) and a.get("name")
                        ) or "Spotify"
                        alb_images = ((t.get("album") or {}).get("images")) or []
                        thumb = alb_images[0].get("url", "") if alb_images else pl_thumb
                        dur_str = self._format_duration_ms(int(t.get("duration_ms") or 0))
                        vid_key = f"sp:{tid}"
                        track_obj = {
                            "videoId": vid_key,
                            "spotify_id": tid,
                            "title": title,
                            "artist": artists,
                            "duration": dur_str,
                            "thumbnail": thumb,
                            "spotify_url": f"https://open.spotify.com/track/{tid}",
                            "preview_url": t.get("preview_url") or "",
                        }
                        self.track_meta_cache[vid_key] = track_obj
                        tracks.append(track_obj)
                        if len(tracks) >= limit:
                            break

                    if tracks:
                        return {
                            "playlistId": playlist_id,
                            "title": pl_title,
                            "description": data.get("description") or "",
                            "trackCount": len(tracks),
                            "thumbnail": pl_thumb,
                            "url": f"https://open.spotify.com/playlist/{playlist_id}",
                            "tracks": tracks,
                        }
            except Exception as e:
                print(f"[Spotify] Fallback a embed per playlist '{playlist_id}': {e}")

        # Tentativo 2: Estrattore diretto da open.spotify.com/embed/playlist/{playlist_id} (Zero API Key richiesta!)
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        resp = httpx.get(
            embed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
            timeout=8.0,
        )
        if resp.status_code != 200:
            raise ValueError(f"Impossibile caricare la playlist Spotify '{playlist_id}' (HTTP {resp.status_code}).")

        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text)
        if not m:
            raise ValueError("Impossibile leggere i metadati della playlist Spotify.")

        next_data = json.loads(m.group(1))
        entity = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("state", {})
            .get("data", {})
            .get("entity", {})
        )
        pl_title = entity.get("name") or entity.get("title") or "Playlist Spotify"
        cover_sources = (entity.get("coverArt") or {}).get("sources") or []
        pl_thumb = cover_sources[0].get("url", "") if cover_sources else ""

        raw_tracks = entity.get("trackList") or []
        tracks = []
        for rt in raw_tracks:
            uri = rt.get("uri") or ""
            tid = uri.split(":")[-1] if ":" in uri else uri
            if not tid:
                continue
            title = rt.get("title") or "Brano Spotify"
            artist = (rt.get("subtitle") or "Spotify").replace("\xa0", " ")
            dur_str = self._format_duration_ms(int(rt.get("duration") or 0))
            preview_url = (rt.get("audioPreview") or {}).get("url") or ""
            vid_key = f"sp:{tid}"
            track_obj = {
                "videoId": vid_key,
                "spotify_id": tid,
                "title": title,
                "artist": artist,
                "duration": dur_str,
                "thumbnail": pl_thumb,
                "spotify_url": f"https://open.spotify.com/track/{tid}",
                "preview_url": preview_url,
            }
            self.track_meta_cache[vid_key] = track_obj
            tracks.append(track_obj)
            if len(tracks) >= limit:
                break

        if not tracks:
            raise ValueError("La playlist Spotify non contiene brani leggibili o è privata.")

        return {
            "playlistId": playlist_id,
            "title": pl_title,
            "description": "",
            "trackCount": len(tracks),
            "thumbnail": pl_thumb,
            "url": f"https://open.spotify.com/playlist/{playlist_id}",
            "tracks": tracks,
        }

    def get_track_metadata(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Recupera titolo e artista di un brano Spotify `sp:<track_id>` dalla cache o dall'embed Spotify.
        """
        if video_id in self.track_meta_cache:
            return self.track_meta_cache[video_id]

        tid = video_id[3:] if video_id.startswith("sp:") else video_id
        try:
            r = httpx.get(
                f"https://open.spotify.com/embed/track/{tid}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5.0,
            )
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
            if m:
                entity = (
                    json.loads(m.group(1))
                    .get("props", {})
                    .get("pageProps", {})
                    .get("state", {})
                    .get("data", {})
                    .get("entity", {})
                )
                title = entity.get("title") or entity.get("name") or "Brano Spotify"
                artist = (entity.get("subtitle") or "Spotify").replace("\xa0", " ")
                cover_sources = (entity.get("coverArt") or {}).get("sources") or []
                thumb = cover_sources[0].get("url", "") if cover_sources else ""
                meta = {
                    "videoId": f"sp:{tid}",
                    "spotify_id": tid,
                    "title": title,
                    "artist": artist,
                    "thumbnail": thumb,
                }
                self.track_meta_cache[f"sp:{tid}"] = meta
                return meta
        except Exception:
            pass
        return None

    def search_tracks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Cerca brani direttamente sul catalogo Spotify se è disponibile un token API valido.
        """
        tok = self._get_valid_access_token()
        if not tok:
            return []

        clean_q = query.strip()
        if "instrumental" not in clean_q.lower():
            clean_q = f"{clean_q} instrumental"

        tracks: List[Dict[str, Any]] = []
        try:
            resp = httpx.get(
                "https://api.spotify.com/v1/search",
                params={"q": clean_q, "type": "track", "limit": min(limit * 2, 30)},
                headers={"Authorization": f"Bearer {tok}"},
                timeout=6.0,
            )
            if resp.status_code == 200:
                items = (resp.json().get("tracks") or {}).get("items") or []
                for t in items:
                    if not isinstance(t, dict) or not t.get("id"):
                        continue
                    tid = t["id"]
                    title = t.get("name") or "Brano Spotify"
                    artists = ", ".join(
                        a.get("name", "") for a in (t.get("artists") or []) if isinstance(a, dict) and a.get("name")
                    ) or "Spotify"
                    alb_images = ((t.get("album") or {}).get("images")) or []
                    thumb = alb_images[0].get("url", "") if alb_images else ""
                    dur_str = self._format_duration_ms(int(t.get("duration_ms") or 0))
                    vid_key = f"sp:{tid}"
                    track_obj = {
                        "videoId": vid_key,
                        "spotify_id": tid,
                        "title": title,
                        "artist": artists,
                        "duration": dur_str,
                        "thumbnail": thumb,
                        "spotify_url": f"https://open.spotify.com/track/{tid}",
                        "preview_url": t.get("preview_url") or "",
                    }
                    self.track_meta_cache[vid_key] = track_obj
                    tracks.append(track_obj)
                    if len(tracks) >= limit:
                        break
        except Exception as e:
            print(f"[Spotify] Errore ricerca brani per '{clean_q}': {e}")
        return tracks

