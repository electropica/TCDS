#!/usr/bin/env python3
import json

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from server.database import get_connection, init_database

VERSION = "0.1.0"
ONLINE_TIMEOUT = 90

DEFAULT_CONFIG = {
    "log_level": "INFO",
    "session_enabled": False,
    "ui_enabled": False,
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

    return {
        "log_level": log_level,
        "session_enabled": config["session_enabled"],
        "ui_enabled": config["ui_enabled"],
    }


@app.on_event("startup")
def startup():
    init_database()


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
def heartbeat(terminal_id: str):
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
