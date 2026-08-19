#!/usr/bin/env bash
#
# Script d'installation initiale - à exécuter UNE FOIS sur le VPS Hetzner
# (Ubuntu 24.04), en tant que root, après avoir copié le projet dans
# /opt/telegram-bet-tracker.
#
# Usage sur le serveur :
#   cd /opt/telegram-bet-tracker
#   bash deploy/setup_server.sh
#
set -e

PROJECT_DIR="/opt/telegram-bet-tracker"

echo ">> Mise à jour du système..."
apt update && apt upgrade -y

echo ">> Installation de Python et outils..."
apt install -y python3 python3-pip python3-venv git

echo ">> Création de l'environnement virtuel..."
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo ">> ATTENTION : fichier .env manquant."
    echo "   Copiez .env.example vers .env et remplissez les valeurs avant de continuer :"
    echo "   cp .env.example .env && nano .env"
    exit 1
fi

echo ">> Authentification Telegram (première fois uniquement)..."
echo "   Vous allez devoir entrer votre numéro de téléphone puis le code reçu."
python main.py --backfill 1

echo ">> Installation du service systemd..."
cp deploy/bet-tracker.service /etc/systemd/system/bet-tracker.service
systemctl daemon-reload
systemctl enable bet-tracker
systemctl start bet-tracker

echo ""
echo "=========================================="
echo "Déploiement terminé."
echo "Vérifier le statut  : systemctl status bet-tracker"
echo "Voir les logs live  : journalctl -u bet-tracker -f"
echo "Voir le fichier log : tail -f $PROJECT_DIR/logs/pipeline.log"
echo "=========================================="
