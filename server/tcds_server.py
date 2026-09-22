#!/usr/bin/env python3

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

VERSION = "0.1.0"

app = FastAPI(
    title="TCDS Server",
    version=VERSION,
)

terminals = {}


class TerminalRegistration(BaseModel):
    terminal_id: str
    hostname: str
    mac_address: str
    ip_address: str
    architecture: str
    client_version: str


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

    terminals[terminal.terminal_id] = terminal_data

    return {
        "status": "registered",
        "terminal": terminal_data,
    }


@app.post("/api/v1/terminals/{terminal_id}/heartbeat")
def heartbeat(terminal_id: str):
    if terminal_id not in terminals:
        raise HTTPException(
            status_code=404,
            detail="Terminal not registered",
        )

    terminals[terminal_id]["last_seen"] = datetime.now(timezone.utc).isoformat()
    terminals[terminal_id]["online"] = True

    return {
        "status": "ok",
        "terminal_id": terminal_id,
        "last_seen": terminals[terminal_id]["last_seen"],
    }


@app.get("/api/v1/terminals")
def list_terminals():
    return {
        "terminals": list(terminals.values()),
    }


@app.get("/api/v1/terminals/{terminal_id}")
def get_terminal(terminal_id: str):
    if terminal_id not in terminals:
        raise HTTPException(
            status_code=404,
            detail="Terminal not registered",
        )

    return terminals[terminal_id]
