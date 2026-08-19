# Déploiement sur VPS Hetzner

## 1. Copier le projet sur le serveur

Depuis ta machine locale, une fois le serveur créé et son IP connue :

```bash
scp -r telegram-bet-tracker root@<IP_DU_SERVEUR>:/opt/telegram-bet-tracker
```

(Si tu utilises un mot de passe au lieu d'une clé SSH, `scp` te le demandera.)

## 2. Se connecter au serveur

```bash
ssh root@<IP_DU_SERVEUR>
```

## 3. Configurer les variables d'environnement

```bash
cd /opt/telegram-bet-tracker
cp .env.example .env
nano .env
```

Remplir au minimum :
- `TELEGRAM_API_ID` et `TELEGRAM_API_HASH` (à obtenir sur https://my.telegram.org/apps)
- `TELEGRAM_TARGET_GROUP` (username sans @ ou ID numérique du groupe)

Sauvegarder (Ctrl+O, Entrée, Ctrl+X dans nano).

## 4. Lancer le script d'installation

```bash
bash deploy/setup_server.sh
```

Ce script va :
- installer Python et les dépendances,
- te demander ton **numéro de téléphone** puis le **code reçu par Telegram** (authentification Telethon, une seule fois),
- installer et démarrer le service systemd `bet-tracker`, configuré pour redémarrer automatiquement en cas de crash ou de reboot du serveur.

## 5. Vérifier que ça tourne

```bash
systemctl status bet-tracker      # statut du service
journalctl -u bet-tracker -f      # logs en direct (Ctrl+C pour quitter)
tail -f logs/pipeline.log         # journal applicatif (section 16)
```

Publie une image de test dans le groupe Telegram et vérifie qu'elle
apparaît dans les logs et dans `storage/images/`.

## Commandes utiles

| Action | Commande |
|---|---|
| Redémarrer le service | `systemctl restart bet-tracker` |
| Arrêter le service | `systemctl stop bet-tracker` |
| Voir les images capturées | `ls storage/images/` |
| Inspecter la base | `sqlite3 storage/bets.db "SELECT * FROM raw_images;"` |
| Mettre à jour le code (après modif locale) | `scp -r telegram-bet-tracker root@<IP>:/opt/telegram-bet-tracker` puis `systemctl restart bet-tracker` sur le serveur |

## Sécurité de base (recommandé, pas obligatoire pour tester)

```bash
# Créer un utilisateur non-root dédié (au lieu de tout faire en root)
adduser bettracker
usermod -aG sudo bettracker

# Pare-feu minimal (autoriser seulement SSH)
ufw allow OpenSSH
ufw enable
```
