#!/bin/bash

set -e

TARGET="${1:-}"
SSH_KEY="/root/.ssh/tcds-rx300"

if [ -z "$TARGET" ]; then
    echo "Usage : $0 utilisateur@adresse-ip"
    exit 1
fi

if [ ! -f "$SSH_KEY" ]; then
    echo "[ERREUR] Clé SSH introuvable : $SSH_KEY"
    exit 1
fi

echo "[TCDS] Déploiement vers $TARGET"

SSH="ssh -i $SSH_KEY"
SCP="scp -i $SSH_KEY"

echo "[TCDS] Création des répertoires..."
    $SSH "$TARGET" "sudo mkdir -p /opt/tcds/player /opt/tcds/media"
$SSH "$TARGET" "sudo mkdir -p /opt/tcds/{core,client,identity,config,logs}"

echo "[TCDS] Copie du Core..."
$SCP core/tcds_core.py "$TARGET:/tmp/tcds_core.py"

echo "[TCDS] Copie du Client..."
$SCP client/tcds_client.py "$TARGET:/tmp/tcds_client.py"

echo "[TCDS] Copie du Player..."
$SCP player/tcds_player.py "$TARGET:/tmp/tcds_player.py"
$SCP config/tcds-player.conf "$TARGET:/tmp/tcds-player.conf"
$SCP config/systemd/tcds-player.service "$TARGET:/tmp/tcds-player.service"
echo "[TCDS] Copie du service systemd Client..."
$SCP config/systemd/tcds-client.service "$TARGET:/tmp/tcds-client.service"

echo "[TCDS] Copie de l'Identity..."
$SCP identity/identity.py "$TARGET:/tmp/identity.py"

echo "[TCDS] Installation..."
$SSH "$TARGET" '
    sudo mv /tmp/tcds_core.py /opt/tcds/core/tcds_core.py
    sudo mv /tmp/tcds_client.py /opt/tcds/client/tcds_client.py
    sudo mv /tmp/tcds_player.py /opt/tcds/player/tcds_player.py
    sudo mv /tmp/tcds-player.conf /opt/tcds/config/tcds-player.conf
    sudo mv /tmp/tcds-player.service /etc/systemd/system/tcds-player.service
    sudo mv /tmp/tcds-client.service /etc/systemd/system/tcds-client.service

    sudo mv /tmp/identity.py /opt/tcds/identity/identity.py

    sudo chown root:root /opt/tcds/core/tcds_core.py
    sudo chown root:root /opt/tcds/client/tcds_client.py
    sudo chown root:root /opt/tcds/identity/identity.py
    sudo chown root:root /opt/tcds/player/tcds_player.py
    sudo chmod 755 /opt/tcds/player/tcds_player.py
    sudo chmod 644 /etc/systemd/system/tcds-player.service
    sudo systemctl enable --now tcds-player.service

    sudo chmod 755 /opt/tcds/core/tcds_core.py
    sudo chmod 755 /opt/tcds/client/tcds_client.py
    sudo chmod 644 /etc/systemd/system/tcds-client.service

    sudo chmod 755 /opt/tcds/identity/identity.py

    sudo systemctl daemon-reload
    sudo systemctl enable --now tcds-client.service
    sudo systemctl restart tcds-client.service

'

echo "[TCDS] Déploiement terminé."
