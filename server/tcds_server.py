#!/usr/bin/env python3
import json
import shutil
import subprocess
import tempfile
import uuid

import fitz

from datetime import datetime, timezone

from fastapi import UploadFile, File, BackgroundTasks
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from server.database import get_connection, init_database

VERSION = "0.1.0"
ONLINE_TIMEOUT = 90
MEDIA_DIR = Path("/opt/tcds/media")
PLAYLIST_DIR = Path("/opt/tcds/playlists")

DEFAULT_CONFIG = {
    "log_level": "INFO",
    "session_enabled": False,
    "ui_enabled": False,
    "media": None,
    "media_kind": "video",
    "pdf_page_duration": 10,
    "playlist": None,
}

VALID_LOG_LEVELS = {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}

app = FastAPI(


    title="TCDS Server",
    version=VERSION,
)
websocket_clients = {}
media_jobs = {}
playback_states = {}


class TerminalRegistration(BaseModel):
    terminal_id: str
    hostname: str
    mac_address: str
    ip_address: str
    architecture: str
    client_version: str


class TerminalConfigUpdate(BaseModel):
    log_level: str
    session_enabled: bool
    ui_enabled: bool
    media: str | None = None
    media_kind: str = "video"
    pdf_page_duration: int | None = None
    playlist: str | None = None


class PlaylistItem(BaseModel):
    filename: str
    duration: int | None = None


class PlaylistPayload(BaseModel):
    name: str
    items: list[PlaylistItem]


class PlaybackState(BaseModel):
    state: str = "unknown"
    mode: str = "single"
    label: str | None = None
    playlist: str | None = None
    position: int | None = None
    total: int | None = None
    page_position: int | None = None
    page_total: int | None = None


def is_terminal_online(last_seen):
    last_seen_time = datetime.fromisoformat(last_seen)
    elapsed = (
        datetime.now(timezone.utc) - last_seen_time
    ).total_seconds()

    return elapsed < ONLINE_TIMEOUT


def validate_config(config):
    log_level = config["log_level"].upper()

    if log_level not in VALID_LOG_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Niveau de log invalide: {config['log_level']}",
        )

    media_kind = config.get("media_kind", "video")
    if media_kind not in {"video", "pdf", "playlist"}:
        raise HTTPException(status_code=422, detail="Type de média invalide")

    page_duration = config.get("pdf_page_duration")
    if page_duration is not None:
        page_duration = int(page_duration)
        if not 1 <= page_duration <= 86400:
            raise HTTPException(status_code=422, detail="La durée PDF doit être comprise entre 1 et 86400 secondes")

    return {
        "log_level": log_level,
        "session_enabled": config["session_enabled"],
        "ui_enabled": config["ui_enabled"],
        "media": config.get("media"),
        "media_kind": media_kind,
        "pdf_page_duration": page_duration,
        "playlist": config.get("playlist"),
    }


@app.on_event("startup")
def startup():
    init_database()


@app.websocket("/ws/{terminal_id}")
async def websocket_endpoint(websocket: WebSocket, terminal_id: str):
    await websocket.accept()
    websocket_clients[terminal_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket_clients.get(terminal_id) is websocket:
            del websocket_clients[terminal_id]


@app.get("/api/v1/media")
def list_media():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(MEDIA_DIR.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        item = {"filename": path.name, "type": "pdf" if path.suffix.lower() == ".pdf" else "video"}
        if item["type"] == "pdf":
            pdf_dir = MEDIA_DIR / ".pdf" / path.stem
            item["pages"] = len(list(pdf_dir.glob("page-*.jpg")))
            settings_path = pdf_dir / "manifest.json"
            if settings_path.is_file():
                item["page_duration"] = json.loads(settings_path.read_text()).get("page_duration", 10)
            else:
                item["page_duration"] = 10
        entries.append(item)
    return {"media": [item["filename"] for item in entries], "details": entries}


def playlist_path(name):
    clean_name = Path(name).name
    if clean_name != name or not clean_name or clean_name in {".", ".."}:
        raise HTTPException(status_code=422, detail="Nom de playlist invalide")
    return PLAYLIST_DIR / f"{clean_name}.json"


def read_playlist(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"name": path.stem, "items": data.get("items", [])}
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f"Playlist illisible: {error}")


@app.get("/api/v1/playlists")
def list_playlists():
    PLAYLIST_DIR.mkdir(parents=True, exist_ok=True)
    playlists = [
        read_playlist(path)
        for path in sorted(PLAYLIST_DIR.glob("*.json"))
        if path.is_file()
    ]
    return {"playlists": playlists}


@app.post("/api/v1/playlists", status_code=201)
def create_playlist(payload: PlaylistPayload):
    name = payload.name.strip()
    path = playlist_path(name)
    if path.exists():
        raise HTTPException(status_code=409, detail="Cette playlist existe déjà")
    for item in payload.items:
        if not (MEDIA_DIR / item.filename).is_file() or Path(item.filename).name != item.filename:
            raise HTTPException(status_code=422, detail=f"Média introuvable: {item.filename}")
        if item.duration is not None and not 1 <= item.duration <= 86400:
            raise HTTPException(status_code=422, detail="La durée doit être comprise entre 1 et 86400 secondes")
    PLAYLIST_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": [item.model_dump() for item in payload.items]}, indent=2) + "\n", encoding="utf-8")
    return {"name": name, "items": [item.model_dump() for item in payload.items]}


@app.get("/api/v1/playlists/{name}")
def get_playlist(name: str):
    path = playlist_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    return read_playlist(path)


@app.put("/api/v1/playlists/{name}")
def update_playlist(name: str, payload: PlaylistPayload):
    path = playlist_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    if payload.name.strip() != name:
        raise HTTPException(status_code=422, detail="Le nom de playlist ne peut pas changer ici")
    for item in payload.items:
        if not (MEDIA_DIR / item.filename).is_file() or Path(item.filename).name != item.filename:
            raise HTTPException(status_code=422, detail=f"Média introuvable: {item.filename}")
        if item.duration is not None and not 1 <= item.duration <= 86400:
            raise HTTPException(status_code=422, detail="La durée doit être comprise entre 1 et 86400 secondes")
    path.write_text(json.dumps({"items": [item.model_dump() for item in payload.items]}, indent=2) + "\n", encoding="utf-8")
    return {"name": name, "items": [item.model_dump() for item in payload.items]}


@app.delete("/api/v1/playlists/{name}")
def delete_playlist(name: str):
    path = playlist_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    path.unlink()
    return {"status": "deleted", "name": name}


def process_uploaded_pdf(temp_path, filename, job_id):
    temp_path = Path(temp_path)
    job = media_jobs[job_id]
    pdf_dir = MEDIA_DIR / ".pdf" / Path(filename).stem
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        final_path = MEDIA_DIR / filename
        shutil.move(str(temp_path), final_path)
        job.update(status="rendering", progress=0, message="Conversion des pages PDF")
        document = fitz.open(str(final_path))
        pages = []
        matrix = fitz.Matrix(150 / 72, 150 / 72)
        for page_number, page in enumerate(document, start=1):
            output_path = pdf_dir / f"page-{page_number:04d}.jpg"
            page.get_pixmap(matrix=matrix, alpha=False).save(str(output_path))
            pages.append(output_path)
        document.close()
        if not pages:
            raise RuntimeError("Le PDF ne contient aucune page exploitable")
        (pdf_dir / "manifest.json").write_text(
            json.dumps({"filename": filename, "page_duration": 10}, indent=2) + "\n",
            encoding="utf-8",
        )
        job.update(status="done", progress=100, message=f"PDF prêt ({len(pages)} page(s))", filename=final_path.name, pages=len(pages))
    except Exception as exc:
        job.update(status="error", message=str(exc))
        temp_path.unlink(missing_ok=True)

def process_uploaded_media(temp_path, filename, job_id):
    temp_path = Path(temp_path)
    job = media_jobs[job_id]
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        job.update(status="analyzing", progress=0, message="Analyse vidéo")

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "format=duration:stream=codec_name,profile,width,height,pix_fmt,level",
                "-of", "json", str(temp_path),
            ],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(probe.stdout)
        video = next(
            (s for s in info.get("streams", []) if "width" in s and "height" in s),
            None,
        )
        if video is None:
            raise ValueError("Aucune piste vidéo détectée")

        duration = float(info.get("format", {}).get("duration") or 0)
        compatible = (
            video.get("codec_name") == "h264"
            and video.get("level", 999) <= 42
            and video.get("profile") == "High"
            and video.get("pix_fmt") == "yuv420p"
            and video.get("width", 99999) <= 1920
            and video.get("height", 99999) <= 1080
            and Path(filename).suffix.lower() == ".mp4"
        )

        if compatible:
            final_path = MEDIA_DIR / filename
            shutil.move(str(temp_path), final_path)
            job.update(
                status="done", progress=100,
                message="Vidéo prête (aucun encodage nécessaire)",
                filename=final_path.name,
            )
            return

        final_path = MEDIA_DIR / f"{Path(filename).stem}_tcds.mp4"
        temp_output = temp_path.parent / final_path.name
        command = [
            "ffmpeg", "-y", "-i", str(temp_path),
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,fps=30",
            "-c:v", "libx264", "-preset", "medium",
            "-profile:v", "high", "-level:v", "4.0",
            "-pix_fmt", "yuv420p",
            "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            str(temp_output),
        ]

        job.update(status="encoding", progress=0, message="Encodage en cours")
        with subprocess.Popen(
            command, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        ) as process:
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and duration > 0 and value.isdigit():
                    seconds = int(value or 0) / 1_000_000
                    job["progress"] = min(99, int(seconds / duration * 100))
                elif key == "progress" and value == "end":
                    job["progress"] = 99
            return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f"FFmpeg a échoué (code {return_code})")

        shutil.move(str(temp_output), final_path)
        job.update(
            status="done", progress=100,
            message="Encodage terminé",
            filename=final_path.name,
        )

    except Exception as exc:
        job.update(status="error", message=str(exc))
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/api/v1/media")
async def upload_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "video").name
    temp_dir = Path(tempfile.mkdtemp(prefix="tcds-upload-", dir="/tmp"))
    temp_path = temp_dir / filename

    try:
        with temp_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                destination.write(chunk)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    job_id = str(uuid.uuid4())
    media_jobs[job_id] = {
        "status": "uploaded",
        "progress": 0,
        "message": "Fichier reçu, préparation...",
        "filename": filename,
    }
    if Path(filename).suffix.lower() == ".pdf":
        background_tasks.add_task(process_uploaded_pdf, temp_path, filename, job_id)
    else:
        background_tasks.add_task(process_uploaded_media, temp_path, filename, job_id)
    return {"status": "uploaded", "filename": filename, "job_id": job_id}


@app.get("/api/v1/media/jobs/{job_id}")
def get_media_job(job_id: str):
    job = media_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return dict(job)


@app.get("/api/v1/media/{filename}")
def download_media(filename: str):
    from fastapi.responses import FileResponse
    path = MEDIA_DIR / filename
    if not path.is_file() or path.parent != MEDIA_DIR:
        raise HTTPException(status_code=404, detail="Media introuvable")
    return FileResponse(path)


@app.get("/api/v1/media/{filename}/manifest")
def pdf_manifest(filename: str):
    path = MEDIA_DIR / filename
    if path.suffix.lower() != ".pdf" or not path.is_file() or path.parent != MEDIA_DIR:
        raise HTTPException(status_code=404, detail="PDF introuvable")
    pages = sorted((MEDIA_DIR / ".pdf" / path.stem).glob("page-*.jpg"))
    if not pages:
        raise HTTPException(status_code=409, detail="PDF non converti")
    settings_path = path.parent / ".pdf" / path.stem / "manifest.json"
    page_duration = 10
    if settings_path.is_file():
        page_duration = json.loads(settings_path.read_text(encoding="utf-8")).get("page_duration", 10)
    return {"filename": filename, "pages": [p.name for p in pages], "page_duration": page_duration}


class PdfSettings(BaseModel):
    page_duration: int


@app.put("/api/v1/media/{filename}/settings")
def update_pdf_settings(filename: str, settings: PdfSettings):
    path = MEDIA_DIR / filename
    if path.suffix.lower() != ".pdf" or not path.is_file() or path.parent != MEDIA_DIR:
        raise HTTPException(status_code=404, detail="PDF introuvable")
    if not 1 <= settings.page_duration <= 86400:
        raise HTTPException(status_code=422, detail="La durée PDF doit être comprise entre 1 et 86400 secondes")
    pdf_dir = MEDIA_DIR / ".pdf" / path.stem
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pdf_dir / "manifest.json"
    manifest = {"filename": filename, "page_duration": settings.page_duration}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


@app.get("/api/v1/media/{filename}/pages/{page}")
def pdf_page(filename: str, page: str):
    path = MEDIA_DIR / ".pdf" / Path(filename).stem / page
    if path.suffix.lower() != ".jpg" or not path.is_file() or path.parent.parent != MEDIA_DIR / ".pdf":
        raise HTTPException(status_code=404, detail="Page PDF introuvable")
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="image/jpeg")

@app.delete("/api/v1/media/{filename}")
def delete_media(filename: str):
    path = MEDIA_DIR / filename
    if not path.is_file() or path.parent != MEDIA_DIR:
        raise HTTPException(status_code=404, detail="Media introuvable")
    path.unlink()
    return {"status": "deleted", "filename": filename}


@app.get("/api/v1/status")
def status():
    return {
        "status": "ok",
        "service": "tcds-server",
        "version": VERSION,
    }


@app.post("/api/v1/terminals/register", status_code=201)
def register_terminal(terminal: TerminalRegistration):
    terminal_data = terminal.model_dump()
    terminal_data["last_seen"] = datetime.now(timezone.utc).isoformat()
    terminal_data["online"] = True

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO terminals (
                terminal_id,
                hostname,
                mac_address,
                ip_address,
                architecture,
                client_version,
                last_seen,
                online
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(terminal_id) DO UPDATE SET
                hostname = excluded.hostname,
                mac_address = excluded.mac_address,
                ip_address = excluded.ip_address,
                architecture = excluded.architecture,
                client_version = excluded.client_version,
                last_seen = excluded.last_seen,
                online = excluded.online
            """,
            (
                terminal_data["terminal_id"],
                terminal_data["hostname"],
                terminal_data["mac_address"],
                terminal_data["ip_address"],
                terminal_data["architecture"],
                terminal_data["client_version"],
                terminal_data["last_seen"],
                1,
            ),
        )

        connection.commit()

        connection.execute(
            """
            INSERT OR IGNORE INTO terminal_config (
                terminal_id,
                config_version,
                config_json,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                terminal_data["terminal_id"],
                1,
                json.dumps(DEFAULT_CONFIG),
                terminal_data["last_seen"],
            ),
        )

        connection.commit()

    return {
        "status": "registered",
        "terminal": terminal_data,
    }


@app.post("/api/v1/terminals/{terminal_id}/heartbeat")
def heartbeat(terminal_id: str, playback: PlaybackState | None = None):
    last_seen = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE terminals
            SET last_seen = ?, online = 1
            WHERE terminal_id = ?
            """,
            (last_seen, terminal_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Terminal not registered",
            )

        config_row = connection.execute(
            """
            SELECT config_version
            FROM terminal_config
            WHERE terminal_id = ?
            """,
            (terminal_id,),
        ).fetchone()

        connection.commit()

    if playback is not None:
        playback_states[terminal_id] = playback.model_dump()

    if config_row is None:
        raise HTTPException(
            status_code=404,
            detail="Configuration not found",
        )

    return {
        "status": "ok",
        "terminal_id": terminal_id,
        "last_seen": last_seen,
        "config_version": config_row["config_version"],
    }


@app.get("/api/v1/terminals")
def list_terminals():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM terminals ORDER BY terminal_id"
        ).fetchall()

    terminals = []

    for row in rows:
        terminal = dict(row)
        terminal["online"] = is_terminal_online(terminal["last_seen"])
        terminal["playback"] = playback_states.get(terminal["terminal_id"])
        terminals.append(terminal)

    return {
        "terminals": terminals,
    }


@app.get("/api/v1/terminals/{terminal_id}")
def get_terminal(terminal_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM terminals WHERE terminal_id = ?",
            (terminal_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Terminal not registered",
        )

    terminal = dict(row)
    terminal["online"] = is_terminal_online(terminal["last_seen"])

    return terminal


@app.get("/api/v1/terminals/{terminal_id}/config")
def get_terminal_config(terminal_id: str):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT terminal_id, config_version, config_json
            FROM terminal_config
            WHERE terminal_id = ?
            """,
            (terminal_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Configuration not found",
        )

    return {
        "terminal_id": row["terminal_id"],
        "config_version": row["config_version"],
        "settings": json.loads(row["config_json"]),
    }

@app.put("/api/v1/terminals/{terminal_id}/config")
def update_terminal_config(
    terminal_id: str,
    config: TerminalConfigUpdate,
):
    new_config = validate_config(config.model_dump())
    updated_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        terminal_row = connection.execute(
            """
            SELECT terminal_id
            FROM terminals
            WHERE terminal_id = ?
            """,
            (terminal_id,),
        ).fetchone()

        if terminal_row is None:
            raise HTTPException(
                status_code=404,
                detail="Terminal not registered",
            )

        config_row = connection.execute(
            """
            SELECT config_version
            FROM terminal_config
            WHERE terminal_id = ?
            """,
            (terminal_id,),
        ).fetchone()

        if config_row is None:
            raise HTTPException(
                status_code=404,
                detail="Configuration not found",
            )

        new_version = config_row["config_version"] + 1

        connection.execute(
            """
            UPDATE terminal_config
            SET config_version = ?,
                config_json = ?,
                updated_at = ?
            WHERE terminal_id = ?
            """,
            (
                new_version,
                json.dumps(new_config),
                updated_at,
                terminal_id,
            ),
        )

        connection.commit()

    return {
        "status": "updated",
        "terminal_id": terminal_id,
        "config_version": new_version,
        "settings": new_config,
        "updated_at": updated_at,
    }

@app.post("/api/v1/terminals/{terminal_id}/player/start")
async def start_player(terminal_id: str):
    websocket = websocket_clients.get(terminal_id)
    if websocket is not None:
        await websocket.send_json({"command": "start"})
    return {"status": "sent", "terminal_id": terminal_id, "command": "start"}


@app.post("/api/v1/terminals/{terminal_id}/player/stop")
async def stop_player(terminal_id: str):
    websocket = websocket_clients.get(terminal_id)
    if websocket is not None:
        await websocket.send_json({"command": "stop"})
    return {"status": "sent", "terminal_id": terminal_id, "command": "stop"}
 
@app.post("/api/v1/terminals/{terminal_id}/poweroff")
async def poweroff_terminal(terminal_id: str):
    websocket = websocket_clients.get(terminal_id)
    if websocket is None:
        return {
            "status": "offline",
            "terminal_id": terminal_id,
            "command": "poweroff",
        }
    await websocket.send_json({"command": "poweroff"})
    return {
        "status": "sent",
        "terminal_id": terminal_id,
        "command": "poweroff",
    }


@app.get("/", response_class=HTMLResponse)
def web_interface():
    return """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>TCDS — Administration</title>
<style>
:root {
  color-scheme: light dark;
  --bg:#f3f6fb; --surface:#fff; --surface2:#edf2f8;
  --text:#172338; --muted:#64748b; --border:#dce4ef;
  --accent:#2563eb; --accent-hover:#1d4ed8;
  --good:#15803d; --good-bg:#dcfce7;
  --bad:#b91c1c; --bad-bg:#fee2e2;
  --shadow:0 8px 28px rgba(25,45,80,.07);
}
@media(prefers-color-scheme:dark) {
  :root {
    --bg:#101722; --surface:#192332; --surface2:#222f41;
    --text:#e5edf8; --muted:#a4b3c8; --border:#334155;
    --accent:#60a5fa; --accent-hover:#93c5fd;
    --good:#86efac; --good-bg:#153c2a;
    --bad:#fca5a5; --bad-bg:#4b2025;
    --shadow:0 8px 28px rgba(0,0,0,.15);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{background:var(--surface);border-bottom:1px solid var(--border)}
.header-inner,.main{width:min(1120px,calc(100% - 32px));margin:auto}
.header-inner{min-height:82px;display:flex;align-items:center;
  justify-content:space-between;gap:16px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:42px;height:42px;border-radius:12px;background:var(--accent);
  color:white;display:grid;place-items:center;font-weight:800;font-size:19px}
h1{font-size:21px;margin:0;letter-spacing:-.4px}
.subtitle{color:var(--muted);font-size:13px}
main{padding:28px 0 48px}
.section-head{display:flex;justify-content:space-between;align-items:center;
  gap:12px;flex-wrap:wrap;margin:30px 0 14px}
.section-head:first-child{margin-top:0}
h2{font-size:18px;margin:0;letter-spacing:-.25px}
h3{font-size:15px;margin:0 0 10px}
.muted{color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:16px;padding:20px;box-shadow:var(--shadow);min-width:0}
.stat-label{color:var(--muted);font-size:13px}
.stat-value{font-size:28px;font-weight:750;letter-spacing:-1px;margin-top:3px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,.8fr);gap:16px}
label{display:block;font-weight:600;font-size:13px;margin-bottom:7px}
input,select,button{font:inherit}
input[type=file],select{width:100%;min-width:0;padding:10px;
  border:1px solid var(--border);border-radius:10px;background:var(--surface);
  color:var(--text)}
button{border:0;border-radius:9px;padding:9px 13px;font-weight:650;
  cursor:pointer;transition:filter .15s,transform .15s}
button:hover{filter:brightness(.94)}
button:active{transform:translateY(1px)}
button:disabled{opacity:.55;cursor:not-allowed}
.primary{background:var(--accent);color:white}
.secondary{background:var(--surface2);color:var(--text)}
.danger{background:var(--bad-bg);color:var(--bad)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}
.tab-button{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.tab-button.active{background:var(--accent);color:white;border-color:var(--accent)}
.tab-panel{display:none}
.tab-panel.active{display:block}
.status{padding:10px 12px;border-radius:10px;background:var(--surface2);
  color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.status:empty{display:none}
.progress-row{margin-top:12px;font-size:13px}
progress{display:block;width:100%;height:10px;margin-top:6px;accent-color:var(--accent)}
.media-list,.terminal-list{display:grid;gap:10px}
.media-item,.terminal-item{display:flex;align-items:center;justify-content:space-between;
  gap:14px;padding:14px;border:1px solid var(--border);border-radius:12px;
  background:var(--surface)}
.media-name,.terminal-name{font-weight:650;overflow-wrap:anywhere}
.media-actions,.terminal-actions{display:flex;gap:7px;flex-wrap:wrap;flex-shrink:0}
.playlist-choice{display:flex;align-items:center;gap:8px;padding:9px 0;
  border-bottom:1px solid var(--border);font-weight:500}
.playlist-choice input[type=checkbox]{width:auto}
.playlist-choice input[type=number]{width:82px;margin-left:auto;padding:6px}
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
  padding:4px 9px;font-size:12px;font-weight:700;background:var(--surface2)}
.pill:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.pill.online{background:var(--good-bg);color:var(--good)}
.pill.offline{background:var(--bad-bg);color:var(--bad)}
.terminal-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  color:var(--muted);font-size:13px;margin-top:5px}
.empty{padding:24px;text-align:center;color:var(--muted);
  border:1px dashed var(--border);border-radius:12px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:0 16px 24px}
@media(max-width:760px){
  .stats{grid-template-columns:1fr}
  .layout{grid-template-columns:1fr}
  .media-item,.terminal-item{align-items:flex-start;flex-direction:column}
  .media-actions,.terminal-actions{width:100%}
  .media-actions button,.terminal-actions button{flex:1}
  .card{padding:16px}
}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="brand">
      <div class="logo">T</div>
      <div><h1>TCDS</h1><div class="subtitle">Administration des terminaux</div></div>
    </div>
    <div class="subtitle" id="lastRefresh">Initialisation…</div>
  </div>
</header>
<main class="main">
  <section class="stats" aria-label="État du parc">
    <div class="card"><div class="stat-label">Terminaux connus</div>
      <div class="stat-value" id="totalCount">—</div></div>
    <div class="card"><div class="stat-label">En ligne</div>
      <div class="stat-value" id="onlineCount">—</div></div>
    <div class="card"><div class="stat-label">Hors ligne</div>
      <div class="stat-value" id="offlineCount">—</div></div>
  </section>

  <section id="mediaSection">
    <div class="section-head"><h2>Bibliothèque de médias</h2>
      <span class="muted" id="mediaCount"></span></div>
    <div class="layout">
      <div class="card">
        <h3>Envoyer un média</h3>
        <label for="mediaFile">Fichier vidéo ou PDF</label>
        <input type="file" id="mediaFile" accept="video/*,.mp4,.mkv,.mov,.avi,.webm,.pdf">
        <div class="actions"><button class="primary" id="uploadButton" onclick="uploadMedia()">Envoyer le média</button></div>
        <div class="status" id="uploadStatus" role="status" aria-live="polite"></div>
        <div id="uploadProgress"></div>
      </div>
      <div class="card">
        <h3>Envoyer vers un terminal</h3>
        <label for="targetTerminal">Terminal cible</label>
        <select id="targetTerminal"><option value="">Chargement des terminaux…</option></select>
        <p class="muted">Choisissez un terminal, puis cliquez sur « Lire ». La durée des PDF se règle dans leur fiche.</p>
        <div class="status" id="mediaActionStatus" role="status" aria-live="polite"></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="media-list" id="media"><div class="empty">Chargement des médias…</div></div>
    </div>
  </section>

  <section id="terminalsSection">
    <div class="section-head">
      <h2>Terminaux RX300</h2>
      <button class="secondary" onclick="loadTerminals()">Actualiser</button>
    </div>
    <div class="terminal-list" id="terminals"><div class="empty">Chargement des terminaux…</div></div>
    <p class="muted" style="font-size:12px">Les statuts sont actualisés automatiquement toutes les 10 secondes.</p>
  </section>

  <section id="playlistsSection">
    <div class="section-head"><h2>Playlists</h2>
      <button class="secondary" onclick="loadPlaylists()">Actualiser</button></div>
    <div class="layout">
      <div class="card">
        <h3>Créer une playlist</h3>
        <label for="playlistName">Nom</label>
        <input id="playlistName" placeholder="Ex. Accueil magasin">
        <label>Médias à lire dans l'ordre</label>
        <div id="playlistBuilder" class="media-list"><div class="empty">Chargement…</div></div>
        <div class="actions"><button class="primary" onclick="createPlaylist()">Créer la playlist</button></div>
      </div>
      <div class="card">
        <h3>Playlists enregistrées</h3>
        <div id="playlists"><div class="empty">Chargement…</div></div>
      </div>
    </div>
  </section>
</main>
<footer>TCDS · Administration locale</footer>

<script>
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
  "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
}[ch]));

function playbackText(terminal) {
  const playback = terminal.playback;
  if (!playback || playback.state === "unknown") return "Lecture : en attente";
  if (playback.state !== "playing") return "Lecture : " + escapeHtml(playback.state);
  const label = escapeHtml(playback.label || "élément inconnu");
  if (playback.mode === "playlist") {
    const index = playback.position && playback.total ? ` (${playback.position}/${playback.total})` : "";
    const page = playback.page_position && playback.page_total
      ? ` — page ${playback.page_position}/${playback.page_total}` : "";
    return `Playlist « ${escapeHtml(playback.playlist || "sans nom")} » : ${label}${index}${page}`;
  }
  return "Fichier : " + label;
}

async function apiJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Erreur HTTP ${response.status}`);
  return body;
}

async function loadTerminals() {
  try {
    const data = await apiJson("/api/v1/terminals");
    const terminals = data.terminals || [];
    const select = $("targetTerminal");
    const previous = select.value;
    select.innerHTML = terminals.length
      ? terminals.map(t => `<option value="${escapeHtml(t.terminal_id)}">${escapeHtml(t.terminal_id)} — ${escapeHtml(t.hostname)}</option>`).join("")
      : '<option value="">Aucun terminal enregistré</option>';
    if (terminals.some(t => t.terminal_id === previous)) select.value = previous;

    const online = terminals.filter(t => t.online).length;
    $("totalCount").textContent = terminals.length;
    $("onlineCount").textContent = online;
    $("offlineCount").textContent = terminals.length - online;
    $("lastRefresh").textContent = "Mis à jour à " +
      new Date().toLocaleTimeString("fr-FR", {hour:"2-digit", minute:"2-digit", second:"2-digit"});

    $("terminals").innerHTML = terminals.length ? terminals.map(t => `
      <article class="terminal-item">
        <div>
          <div class="terminal-name">${escapeHtml(t.hostname || t.terminal_id)}</div>
          <div class="terminal-meta">
            <span>${escapeHtml(t.terminal_id)}</span>
            <span class="pill ${t.online ? "online" : "offline"}">${t.online ? "En ligne" : "Hors ligne"}</span>
            <span>${t.temperature != null ? escapeHtml(t.temperature) + " °C" : "Température inconnue"}</span>
            <span>${playbackText(t)}</span>
          </div>
        </div>
        <div class="terminal-actions">
          <button class="primary" data-command="start" data-id="${escapeHtml(t.terminal_id)}">Démarrer</button>
          <button class="secondary" data-command="stop" data-id="${escapeHtml(t.terminal_id)}">Arrêter</button>
          <button class="secondary" style="background:#b42318;color:white" data-command="poweroff" data-id="${escapeHtml(t.terminal_id)}">Éteindre</button>
        </div>
      </article>`).join("") : '<div class="empty">Aucun terminal enregistré.</div>';
  } catch (error) {
    $("terminals").innerHTML = `<div class="empty">Impossible de charger les terminaux : ${escapeHtml(error.message)}</div>`;
  }
}

function setupTabs() {
  const main = document.querySelector("main");
  const stats = document.querySelector(".stats");
  const media = $("mediaSection");
  const terminals = $("terminalsSection");
  const playlists = $("playlistsSection");
  const tabs = document.createElement("nav");
  tabs.className = "tabs";
  tabs.setAttribute("aria-label", "Sections TCDS");
  tabs.innerHTML = `
    <button class="tab-button active" data-tab="global">Vue globale</button>
    <button class="tab-button" data-tab="media">Médias</button>
    <button class="tab-button" data-tab="playlists">Playlists</button>`;
  const globalPanel = document.createElement("div");
  globalPanel.className = "tab-panel active";
  globalPanel.dataset.panel = "global";
  const mediaPanel = document.createElement("div");
  mediaPanel.className = "tab-panel";
  mediaPanel.dataset.panel = "media";
  const playlistsPanel = document.createElement("div");
  playlistsPanel.className = "tab-panel";
  playlistsPanel.dataset.panel = "playlists";
  main.insertBefore(tabs, main.firstElementChild);
  main.insertBefore(globalPanel, tabs.nextSibling);
  main.insertBefore(mediaPanel, globalPanel.nextSibling);
  main.insertBefore(playlistsPanel, mediaPanel.nextSibling);
  globalPanel.append(stats, terminals);
  mediaPanel.append(media);
  playlistsPanel.append(playlists);
  tabs.addEventListener("click", event => {
    const button = event.target.closest("[data-tab]");
    if (!button) return;
    const tab = button.dataset.tab;
    tabs.querySelectorAll("[data-tab]").forEach(item => item.classList.toggle("active", item === button));
    main.querySelectorAll(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.dataset.panel === tab));
  });
}

async function loadMedia() {
  try {
    const data = await apiJson("/api/v1/media");
    const media = data.media || [];
    $("mediaCount").textContent = `${media.length} fichier${media.length === 1 ? "" : "s"}`;
    $("media").innerHTML = media.length ? media.map(m => `
      <article class="media-item">
        <div class="media-name">${escapeHtml(m)}</div>
        <div class="media-actions">
          <button class="primary" data-media-action="play" data-media="${escapeHtml(m)}">Lire</button>
          <button class="danger" data-media-action="delete" data-media="${escapeHtml(m)}">Supprimer</button>
        </div>
      </article>`).join("") : '<div class="empty">Aucun média. Envoyez une vidéo pour commencer.</div>';
    for (const detail of (data.details || [])) {
      if (detail.type !== "pdf") continue;
      const article = [...$("media").querySelectorAll(".media-item")]
        .find(node => node.querySelector(".media-name")?.textContent === detail.filename);
      if (!article) continue;
      const settings = document.createElement("div");
      settings.className = "pdf-settings";
      const label = document.createElement("label");
      label.textContent = "Durée d'affichage par page (secondes)";
      const input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.max = "86400";
      input.value = detail.page_duration || 10;
      input.dataset.pdfDuration = detail.filename;
      const button = document.createElement("button");
      button.className = "secondary";
      button.textContent = "Enregistrer";
      button.dataset.mediaAction = "save-duration";
      button.dataset.media = detail.filename;
      settings.append(label, input, button);
      const hint = document.createElement("small");
      hint.className = "muted";
      hint.textContent = "Cette durée s'applique à chaque page du PDF, pas au document complet.";
      settings.appendChild(hint);
      article.insertBefore(settings, article.querySelector(".media-actions"));
    }
  } catch (error) {
    $("media").innerHTML = `<div class="empty">Impossible de charger les médias : ${escapeHtml(error.message)}</div>`;
  }
}

async function playMedia(filename) {
  const terminalId = $("targetTerminal").value;
  if (!terminalId) {
    $("mediaActionStatus").textContent = "Sélectionnez d'abord un terminal.";
    return;
  }
  try {
    const config = await apiJson(`/api/v1/terminals/${encodeURIComponent(terminalId)}/config`);
    config.settings.media = filename;
    config.settings.media_kind = filename.toLowerCase().endsWith(".pdf") ? "pdf" : "video";
    config.settings.playlist = null;
    delete config.settings.pdf_page_duration;
    await apiJson(`/api/v1/terminals/${encodeURIComponent(terminalId)}/config`, {
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(config.settings)
    });
    $("mediaActionStatus").textContent = `« ${filename} » sélectionné pour ${terminalId}.`;
  } catch (error) {
    $("mediaActionStatus").textContent = "Erreur : " + error.message;
  }
}

async function playPlaylist(name) {
  const terminalId = $("targetTerminal").value;
  if (!terminalId) {
    $("mediaActionStatus").textContent = "Sélectionnez d'abord un terminal.";
    return;
  }
  try {
    const config = await apiJson(`/api/v1/terminals/${encodeURIComponent(terminalId)}/config`);
    config.settings.media = name;
    config.settings.media_kind = "playlist";
    config.settings.playlist = name;
    await apiJson(`/api/v1/terminals/${encodeURIComponent(terminalId)}/config`, {
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(config.settings)
    });
    $("mediaActionStatus").textContent = `Playlist « ${name} » sélectionnée pour ${terminalId}.`;
  } catch (error) {
    $("mediaActionStatus").textContent = "Erreur : " + error.message;
  }
}

async function deleteMedia(filename) {
  if (!confirm(`Supprimer définitivement le média « ${filename} » ?`)) return;
  try {
    await apiJson("/api/v1/media/" + encodeURIComponent(filename), {method:"DELETE"});
    $("mediaActionStatus").textContent = `Média supprimé : ${filename}`;
    await loadMedia();
  } catch (error) {
    $("mediaActionStatus").textContent = "Erreur : " + error.message;
  }
}

async function savePdfDuration(filename, button) {
  const input = [...document.querySelectorAll("[data-pdf-duration]")]
    .find(node => node.dataset.pdfDuration === filename);
  const duration = Number(input?.value);
  if (!Number.isInteger(duration) || duration < 1 || duration > 86400) {
    $("mediaActionStatus").textContent = "La durée doit être un entier entre 1 et 86400 secondes.";
    return;
  }
  button.disabled = true;
  try {
    await apiJson("/api/v1/media/" + encodeURIComponent(filename) + "/settings", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({page_duration: duration})
    });
    $("mediaActionStatus").textContent = "Durée enregistrée pour « " + filename + " ».";
  } catch (error) {
    $("mediaActionStatus").textContent = "Erreur : " + error.message;
  } finally {
    button.disabled = false;
  }
}

async function loadPlaylistBuilder() {
  const data = await apiJson("/api/v1/media");
  const details = data.details || [];
  $("playlistBuilder").innerHTML = details.length ? details.map(detail => `
    <label class="playlist-choice">
      <input type="checkbox" data-playlist-file="${escapeHtml(detail.filename)}">
      <span>${escapeHtml(detail.filename)}</span>
      ${detail.type === "pdf" ? `<span class="muted">durée par page</span><input type="number" min="1" max="86400" value="${detail.page_duration || 10}" data-playlist-duration="${escapeHtml(detail.filename)}" aria-label="Durée par page du PDF">` : ""}
    </label>`).join("") : '<div class="empty">Ajoutez d’abord des médias.</div>';
}

async function loadPlaylists() {
  try {
    const data = await apiJson("/api/v1/playlists");
    const playlists = data.playlists || [];
    $("playlists").innerHTML = playlists.length ? playlists.map(playlist => `
      <article class="media-item">
        <div><div class="media-name">${escapeHtml(playlist.name)}</div>
        <div class="terminal-meta">${playlist.items.map(item => escapeHtml(item.filename)).join(" · ")}</div></div>
        <div class="media-actions">
          <button class="primary" data-playlist-action="play" data-playlist="${escapeHtml(playlist.name)}">Lire</button>
          <button class="danger" data-playlist-action="delete" data-playlist="${escapeHtml(playlist.name)}">Supprimer</button>
        </div>
      </article>`).join("") : '<div class="empty">Aucune playlist enregistrée.</div>';
  } catch (error) {
    $("playlists").innerHTML = `<div class="empty">Impossible de charger les playlists : ${escapeHtml(error.message)}</div>`;
  }
}

async function createPlaylist() {
  const name = $("playlistName").value.trim();
  const items = [...document.querySelectorAll("[data-playlist-file]:checked")].map(input => {
    const filename = input.dataset.playlistFile;
    const durationInput = [...document.querySelectorAll("[data-playlist-duration]")]
      .find(node => node.dataset.playlistDuration === filename);
    const item = {filename};
    if (durationInput) item.duration = Number(durationInput.value);
    return item;
  });
  if (!name || !items.length) {
    $("mediaActionStatus").textContent = "Indiquez un nom et sélectionnez au moins un média.";
    return;
  }
  try {
    await apiJson("/api/v1/playlists", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name, items})
    });
    $("playlistName").value = "";
    $("mediaActionStatus").textContent = `Playlist « ${name} » créée.`;
    await loadPlaylists();
  } catch (error) {
    $("mediaActionStatus").textContent = "Erreur : " + error.message;
  }
}

$("media").addEventListener("click", event => {
  const button = event.target.closest("button[data-media-action]");
  if (!button) return;
  if (button.dataset.mediaAction === "play") playMedia(button.dataset.media);
  if (button.dataset.mediaAction === "delete") deleteMedia(button.dataset.media);
  if (button.dataset.mediaAction === "save-duration") savePdfDuration(button.dataset.media, button);
});

$("playlists").addEventListener("click", async event => {
  const button = event.target.closest("button[data-playlist-action]");
  if (!button) return;
  const name = button.dataset.playlist;
  if (button.dataset.playlistAction === "play") playPlaylist(name);
  if (button.dataset.playlistAction === "delete" && confirm(`Supprimer la playlist « ${name} » ?`)) {
    try {
      await apiJson("/api/v1/playlists/" + encodeURIComponent(name), {method:"DELETE"});
      await loadPlaylists();
    } catch (error) {
      $("mediaActionStatus").textContent = "Erreur : " + error.message;
    }
  }
});

$("terminals").addEventListener("click", async event => {
  const button = event.target.closest("button[data-command]");
  if (!button) return;
  const command = button.dataset.command;
  const id = button.dataset.id;
  if (command === "poweroff" &&
      !confirm(`Éteindre complètement le terminal ${id} ? Il faudra le rallumer physiquement.`)) {
    return;
  }
  button.disabled = true;
  try {
    const endpoint = command === "poweroff"
      ? `/api/v1/terminals/${encodeURIComponent(id)}/poweroff`
      : `/api/v1/terminals/${encodeURIComponent(id)}/player/${command}`;
    await apiJson(endpoint, {method:"POST"});
  } catch (error) {
    alert("Commande impossible : " + error.message);
  } finally {
    button.disabled = false;
  }
});

function uploadMedia() {
  const file = $("mediaFile").files[0];
  if (!file) {
    $("uploadStatus").textContent = "Sélectionnez une vidéo avant l'envoi.";
    return;
  }

  const data = new FormData();
  data.append("file", file);
  const xhr = new XMLHttpRequest();
  $("uploadButton").disabled = true;
  $("uploadStatus").textContent = "Envoi du fichier…";
  $("uploadProgress").innerHTML =
    '<div class="progress-row">Envoi : <span id="sendPercent">0 %</span><progress id="sendProgress" value="0" max="100"></progress></div>';

  xhr.upload.onprogress = event => {
    if (!event.lengthComputable) return;
    const percent = Math.round(event.loaded / event.total * 100);
    $("sendProgress").value = percent;
    $("sendPercent").textContent = percent + " %";
  };

  xhr.onload = () => {
    if (xhr.status < 200 || xhr.status >= 300) {
      $("uploadStatus").textContent = "Erreur d'envoi : " + xhr.status + " — " + xhr.responseText;
      $("uploadButton").disabled = false;
      return;
    }

    let result;
    try { result = JSON.parse(xhr.responseText); }
    catch {
      $("uploadStatus").textContent = "Réponse serveur invalide.";
      $("uploadButton").disabled = false;
      return;
    }

    $("uploadStatus").textContent = "Fichier reçu. Préparation de la vidéo…";
    $("uploadProgress").innerHTML =
      '<div class="progress-row">Encodage : <span id="encodePercent">0 %</span><progress id="encodeProgress" value="0" max="100"></progress></div>';

    const timer = setInterval(async () => {
      try {
        const job = await apiJson("/api/v1/media/jobs/" + encodeURIComponent(result.job_id));
        const percent = Number(job.progress) || 0;
        $("uploadStatus").textContent = job.message || job.status;
        $("encodeProgress").value = percent;
        $("encodePercent").textContent = percent + " %";

        if (job.status === "done") {
          clearInterval(timer);
          $("uploadStatus").textContent = job.message || "Encodage terminé.";
          $("uploadProgress").innerHTML = "";
          $("mediaFile").value = "";
          $("uploadButton").disabled = false;
          await loadMedia();
        } else if (job.status === "error") {
          clearInterval(timer);
          $("uploadStatus").textContent = "Erreur : " + job.message;
          $("uploadProgress").innerHTML = "";
          $("uploadButton").disabled = false;
        }
      } catch (error) {
        clearInterval(timer);
        $("uploadStatus").textContent = "Suivi interrompu : " + error.message;
        $("uploadButton").disabled = false;
      }
    }, 1000);
  };

  xhr.onerror = () => {
    $("uploadStatus").textContent = "Erreur réseau pendant l'envoi.";
    $("uploadButton").disabled = false;
  };
  xhr.open("POST", "/api/v1/media");
  xhr.send(data);
}

loadTerminals();
loadMedia();
loadPlaylistBuilder();
loadPlaylists();
setupTabs();
setInterval(loadTerminals, 10000);
</script>
</body>
</html>
"""
