#!/usr/bin/env bash
#
# Installe et démarre UNIQUEMENT le service du bot Telegram (Phase 6).
#
# Usage:
#   bash deploy/install_bot_service.sh
#
set -e

echo ">> Installation du service Phase 6 (bot Telegram)..."
cp deploy/bet-tracker-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bet-tracker-bot
systemctl start bet-tracker-bot

echo ""
echo "=========================================="
echo "Service bet-tracker-bot installé et démarré."
echo "Vérifier : systemctl status bet-tracker-bot"
echo "Teste en envoyant /start puis /stats à ton bot sur Telegram."
echo "=========================================="
