"""
Server FastAPI per Bardo AI - Assistente Musicale Vocale per Giochi di Ruolo con YouTube Music.
"""

import random
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from storage import load_config, save_config, reset_default_profiles
from ytmusic_service import YTMusicService
from analyzer import HybridAnalyzer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Bardo AI - RPG Music Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ytm_service = YTMusicService()
analyzer = HybridAnalyzer()


# --- Modelli Pydantic ---

class AnalyzeRequest(BaseModel):
    text: str
    profile_id: Optional[str] = None
    current_mood_id: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    active_profile_id: Optional[str] = None
    analyzer: Optional[Dict[str, Any]] = None
    audio: Optional[Dict[str, Any]] = None


class ProfileSaveRequest(BaseModel):
    profile: Dict[str, Any]


class YTMusicConnectRequest(BaseModel):
    headers_raw: str


class PinTrackRequest(BaseModel):
    profile_id: str
    mood_id: str
    track: Dict[str, Any]


class SavePlaylistRequest(BaseModel):
    playlist_input: str
    assign_to_profile_id: Optional[str] = None
    assign_to_mood_id: Optional[str] = None


# --- Funzioni di supporto ---

def resolve_mood_tracks(
    profile: Dict[str, Any],
    mood_id: str,
    custom_query: str = ""
) -> Dict[str, Any]:
    """
    Recupera i brani da riprodurre per una specifica atmosfera:
    1. Se l'utente ha associato una playlist YouTube Music personalizzata all'atmosfera, carica quella.
    2. Include eventuali brani fissati (pinned_tracks) dall'utente in cima.
    3. Altrimenti cerca automaticamente su YouTube Music usando le query dell'atmosfera (o la query AI).
    """
    moods = profile.get("moods", {})
    if mood_id not in moods:
        raise ValueError(f"Atmosfera '{mood_id}' non trovata nel profilo.")

    mood = moods[mood_id]
    tracks: List[Dict[str, Any]] = []
    source_label = "Ricerca automatica YouTube Music"

    # 1. Brani fissati dall'utente per questa atmosfera
    pinned = mood.get("pinned_tracks") or []
    for t in pinned:
        if isinstance(t, dict) and t.get("videoId"):
            tracks.append(t)

    # 2. Playlist YouTube Music personalizzata associata all'atmosfera
    custom_pl = (mood.get("custom_playlist") or "").strip()
    if custom_pl and not custom_query:
        try:
            pl_info = ytm_service.get_playlist_tracks(custom_pl, limit=35)
            pl_tracks = pl_info.get("tracks") or []
            if pl_tracks:
                random.shuffle(pl_tracks)
                seen = {t["videoId"] for t in tracks}
                for pt in pl_tracks:
                    if pt["videoId"] not in seen:
                        tracks.append(pt)
                        seen.add(pt["videoId"])
                source_label = f"Playlist YT Music: {pl_info.get('title', custom_pl)}"
        except Exception as e:
            print(f"[Bardo] Fallback su ricerca automatica, errore playlist '{custom_pl}': {e}")

    # 3. Se non ci sono abbastanza brani, cerca su YouTube Music
    if len(tracks) < 4:
        queries = mood.get("queries") or [f"{mood.get('name', 'rpg')} instrumental music"]
        chosen_query = custom_query.strip() if custom_query.strip() else random.choice(queries)
        searched = ytm_service.search_tracks(chosen_query, limit=12)
        seen = {t["videoId"] for t in tracks}
        for st in searched:
            if st["videoId"] not in seen:
                tracks.append(st)
                seen.add(st["videoId"])
        if not custom_pl:
            source_label = f"YouTube Music ({chosen_query})"

    return {
        "mood": mood,
        "source": source_label,
        "tracks": tracks
    }


# --- Endpoint API ---

@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    cfg = load_config()
    return {
        "config": cfg,
        "ytmusic_auth": ytm_service.get_auth_status()
    }


@app.post("/api/config")
def update_config(req: ConfigUpdateRequest) -> Dict[str, Any]:
    cfg = load_config()
    if req.active_profile_id and req.active_profile_id in cfg["profiles"]:
        cfg["active_profile_id"] = req.active_profile_id
    if req.analyzer:
        cfg["analyzer"].update(req.analyzer)
    if req.audio:
        cfg["audio"].update(req.audio)
    save_config(cfg)
    return {"status": "ok", "config": cfg}


@app.post("/api/profiles/reset")
def api_reset_profiles() -> Dict[str, Any]:
    cfg = reset_default_profiles()
    return {"status": "ok", "config": cfg}


@app.post("/api/profile/save")
def save_profile(req: ProfileSaveRequest) -> Dict[str, Any]:
    cfg = load_config()
    profile = req.profile
    pid = profile.get("id")
    if not pid:
        raise HTTPException(status_code=400, detail="ID profilo mancante.")
    cfg["profiles"][pid] = profile
    save_config(cfg)
    return {"status": "ok", "config": cfg}


@app.delete("/api/profile/{profile_id}")
def delete_profile(profile_id: str) -> Dict[str, Any]:
    cfg = load_config()
    if len(cfg["profiles"]) <= 1:
        raise HTTPException(status_code=400, detail="Impossibile eliminare l'unico profilo rimasto.")
    if profile_id in cfg["profiles"]:
        del cfg["profiles"][profile_id]
        if cfg["active_profile_id"] == profile_id:
            cfg["active_profile_id"] = next(iter(cfg["profiles"].keys()))
        save_config(cfg)
    return {"status": "ok", "config": cfg}


@app.post("/api/analyze")
async def analyze_speech(req: AnalyzeRequest) -> Dict[str, Any]:
    cfg = load_config()
    pid = req.profile_id or cfg.get("active_profile_id", "fantasy_dnd")
    profile = cfg["profiles"].get(pid) or next(iter(cfg["profiles"].values()))

    result = await analyzer.analyze(
        raw_text=req.text,
        profile=profile,
        analyzer_cfg=cfg.get("analyzer", {}),
        current_mood_id=req.current_mood_id
    )

    mood_id = result.get("mood_id")
    if mood_id and mood_id in profile.get("moods", {}):
        # Se è una nuova atmosfera o un comando forzato, carica subito i brani
        if mood_id != req.current_mood_id or result.get("force_change"):
            try:
                custom_q = result.get("custom_search_query", "")
                playback = resolve_mood_tracks(profile, mood_id, custom_query=custom_q)
                result["playback"] = playback
            except Exception as e:
                result["playback_error"] = str(e)

    return result


@app.get("/api/mood-tracks/{profile_id}/{mood_id}")
def get_mood_tracks(
    profile_id: str,
    mood_id: str,
    custom_query: str = Query(default="")
) -> Dict[str, Any]:
    cfg = load_config()
    profile = cfg["profiles"].get(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profilo non trovato.")
    try:
        return resolve_mood_tracks(profile, mood_id, custom_query=custom_query)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/ytmusic/search")
def search_ytmusic(
    q: str = Query(..., min_length=1),
    type: str = Query(default="tracks")
) -> Dict[str, Any]:
    if type == "playlists":
        return {"playlists": ytm_service.search_playlists(q, limit=10)}
    return {"tracks": ytm_service.search_tracks(q, limit=15)}


@app.get("/api/ytmusic/playlist")
def get_ytmusic_playlist(id_or_url: str = Query(..., min_length=2)) -> Dict[str, Any]:
    try:
        return ytm_service.get_playlist_tracks(id_or_url, limit=40)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ytmusic/save-playlist")
def save_user_playlist(req: SavePlaylistRequest) -> Dict[str, Any]:
    """
    Verifica e salva una playlist YouTube Music nella libreria dell'app e,
    opzionalmente, la associa subito a un'atmosfera.
    """
    try:
        pl_data = ytm_service.get_playlist_tracks(req.playlist_input, limit=25)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cfg = load_config()
    saved = cfg["audio"].setdefault("saved_playlists", [])
    pl_entry = {
        "playlistId": pl_data["playlistId"],
        "title": pl_data["title"],
        "trackCount": pl_data["trackCount"],
        "thumbnail": pl_data["thumbnail"],
        "url": pl_data["url"]
    }
    # Evita duplicati
    saved = [p for p in saved if p.get("playlistId") != pl_entry["playlistId"]]
    saved.insert(0, pl_entry)
    cfg["audio"]["saved_playlists"] = saved

    if req.assign_to_profile_id and req.assign_to_mood_id:
        prof = cfg["profiles"].get(req.assign_to_profile_id)
        if prof and req.assign_to_mood_id in prof.get("moods", {}):
            prof["moods"][req.assign_to_mood_id]["custom_playlist"] = pl_data["playlistId"]

    save_config(cfg)
    return {"status": "ok", "playlist": pl_data, "config": cfg}


@app.get("/api/ytmusic/user-playlists")
def get_user_playlists() -> Dict[str, Any]:
    return {
        "authenticated": ytm_service.is_authenticated,
        "playlists": ytm_service.get_user_playlists(limit=40)
    }


@app.post("/api/ytmusic/connect")
def connect_ytmusic(req: YTMusicConnectRequest) -> Dict[str, Any]:
    try:
        res = ytm_service.connect_with_headers(req.headers_raw)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ytmusic/disconnect")
def disconnect_ytmusic() -> Dict[str, Any]:
    ytm_service.disconnect_account()
    return {"authenticated": False}


@app.post("/api/mood/pin-track")
def pin_track_to_mood(req: PinTrackRequest) -> Dict[str, Any]:
    cfg = load_config()
    prof = cfg["profiles"].get(req.profile_id)
    if not prof or req.mood_id not in prof.get("moods", {}):
        raise HTTPException(status_code=404, detail="Profilo o atmosfera non trovati.")
    mood = prof["moods"][req.mood_id]
    pinned = mood.setdefault("pinned_tracks", [])
    vid = req.track.get("videoId")
    if vid and not any(t.get("videoId") == vid for t in pinned):
        pinned.insert(0, req.track)
        save_config(cfg)
    return {"status": "ok", "pinned_tracks": pinned, "config": cfg}


@app.post("/api/mood/unpin-track")
def unpin_track_from_mood(req: PinTrackRequest) -> Dict[str, Any]:
    cfg = load_config()
    prof = cfg["profiles"].get(req.profile_id)
    if not prof or req.mood_id not in prof.get("moods", {}):
        raise HTTPException(status_code=404, detail="Profilo o atmosfera non trovati.")
    mood = prof["moods"][req.mood_id]
    vid = req.track.get("videoId")
    mood["pinned_tracks"] = [t for t in mood.get("pinned_tracks", []) if t.get("videoId") != vid]
    save_config(cfg)
    return {"status": "ok", "pinned_tracks": mood["pinned_tracks"], "config": cfg}


@app.get("/api/ytmusic/stream/{video_id}")
def get_direct_stream(video_id: str) -> Dict[str, Any]:
    try:
        return ytm_service.get_direct_audio_url(video_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossibile estrarre stream audio: {str(e)}")


# --- Servire il Frontend ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
