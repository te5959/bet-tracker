#!/usr/bin/env bash
#
# Installe et démarre les services Phase 2, 3, 4 en continu.
# À exécuter depuis /opt/telegram-bet-tracker, en root.
#
# Usage:
#   bash deploy/install_pipeline_services.sh
#
set -e

echo ">> Installation des services systemd (Phase 2, 3, 4, 5)..."
cp deploy/bet-tracker-analyze.service /etc/systemd/system/
cp deploy/bet-tracker-route.service /etc/systemd/system/
cp deploy/bet-tracker-match.service /etc/systemd/system/
cp deploy/bet-tracker-expire.service /etc/systemd/system/

systemctl daemon-reload

for svc in bet-tracker-analyze bet-tracker-route bet-tracker-match bet-tracker-expire; do
    systemctl enable "$svc"
    systemctl start "$svc"
done

echo ""
echo "=========================================="
echo "Services installés et démarrés :"
echo "  - bet-tracker          (Phase 1 : capture Telegram)"
echo "  - bet-tracker-analyze  (Phase 2 : analyse IA)"
echo "  - bet-tracker-route    (Phase 3 : création des paris)"
echo "  - bet-tracker-match    (Phase 4 : matching des gains)"
echo "  - bet-tracker-expire   (Phase 5 : expiration des paris trop anciens)"
echo ""
echo "Vérifier le statut de tous :"
echo "  systemctl status bet-tracker bet-tracker-analyze bet-tracker-route bet-tracker-match bet-tracker-expire"
echo ""
echo "Voir les logs en direct (tous confondus) :"
echo "  tail -f logs/pipeline.log"
echo "=========================================="
