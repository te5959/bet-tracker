#!/usr/bin/env bash
#
# Installe et démarre UNIQUEMENT le service Phase 5 (expiration).
# À utiliser si les services Phase 1-4 sont déjà installés et actifs.
#
# Usage:
#   bash deploy/install_expire_service.sh
#
set -e

echo ">> Installation du service Phase 5 (expiration)..."
cp deploy/bet-tracker-expire.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bet-tracker-expire
systemctl start bet-tracker-expire

echo ""
echo "=========================================="
echo "Service bet-tracker-expire installé et démarré."
echo "Vérifier : systemctl status bet-tracker-expire"
echo "=========================================="
