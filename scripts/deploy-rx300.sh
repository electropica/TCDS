#!/bin/bash

set -e

TARGET="${1:-}"

if [ -z "$TARGET" ]; then
    echo "Usage : $0 utilisateur@adresse-ip"
    exit 1
fi

echo "[TCDS] Déploiement vers $TARGET"

echo "[TCDS] Création des répertoires..."
ssh "$TARGET" "sudo mkdir -p /opt/tcds/{core,client,identity,config,logs}"

echo "[TCDS] Copie du Core..."
scp core/tcds_core.py "$TARGET:/tmp/tcds_core.py"

echo "[TCDS] Copie de l'Identity..."
scp identity/identity.py "$TARGET:/tmp/identity.py"

echo "[TCDS] Installation..."
ssh "$TARGET" '
    sudo mv /tmp/tcds_core.py /opt/tcds/core/tcds_core.py
    sudo mv /tmp/identity.py /opt/tcds/identity/identity.py

    sudo chown root:root /opt/tcds/core/tcds_core.py
    sudo chown root:root /opt/tcds/identity/identity.py

    sudo chmod 755 /opt/tcds/core/tcds_core.py
    sudo chmod 755 /opt/tcds/identity/identity.py
'

echo "[TCDS] Déploiement terminé."
