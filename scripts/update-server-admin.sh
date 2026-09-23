#!/bin/bash
set -euo pipefail

ROOT="/opt/tcds/source"
FILE="$ROOT/server/tcds_server.py"
BACKUP="$FILE.bak"

cd "$ROOT"

echo "[INFO] Vérification du dépôt..."

if [ ! -f "$FILE" ]; then
    echo "[ERREUR] Fichier introuvable : $FILE"
    exit 1
fi

if ! grep -q 'def heartbeat(terminal_id: str):' "$FILE"; then
    echo "[ERREUR] Version inattendue de tcds_server.py"
    exit 1
fi

if grep -q 'def update_terminal_config(' "$FILE"; then
    echo "[INFO] La gestion de configuration est déjà présente."
    exit 0
fi

echo "[INFO] Sauvegarde : $BACKUP"
cp -a "$FILE" "$BACKUP"

echo "[INFO] Ajout de l'API d'administration..."

python3 - "$FILE" <<'PY'
from pathlib import Path
import sys

file = Path(sys.argv[1])
content = file.read_text(encoding="utf-8")

content = content.replace(
'''DEFAULT_CONFIG = {
    "log_level": "INFO",
    "session_enabled": False,
    "ui_enabled": False,
}
''',
'''DEFAULT_CONFIG = {
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
''',
1,
)

content = content.replace(
'''def is_terminal_online(last_seen):
    last_seen_time = datetime.fromisoformat(last_seen)
    elapsed = (datetime.now(timezone.utc) - last_seen_time).total_seconds()
    return elapsed < ONLINE_TIMEOUT
''',
'''def is_terminal_online(last_seen):
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
''',
1,
)

content = content.replace(
'''class TerminalRegistration(BaseModel):
    terminal_id: str
    hostname: str
    mac_address: str
    ip_address: str
    architecture: str
    client_version: str
''',
'''class TerminalRegistration(BaseModel):
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
''',
1,
)

endpoint = '''

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
'''

if '@app.put("/api/v1/terminals/{terminal_id}/config")' in content:
    raise SystemExit(
        "[ERREUR] L'endpoint existe déjà mais n'a pas été détecté."
    )

content = content.rstrip() + endpoint + "\n"

file.write_text(content, encoding="utf-8")
PY

echo "[INFO] Vérification syntaxique..."
python3 -m py_compile "$FILE"

echo "[INFO] Vérification Git..."
git diff --check

echo
echo "[OK] Modification terminée."
echo
echo "========== DIFF =========="
git diff -- "$FILE"
echo "=========================="
echo
echo "[INFO] Sauvegarde disponible : $BACKUP"
