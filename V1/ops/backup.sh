#!/usr/bin/env bash
# Nightly database backup, kept for a fortnight.
#
#   /srv/sedb/app/ops/backup.sh
#
# Install with:
#   (crontab -l 2>/dev/null; echo "15 3 * * * /srv/sedb/app/ops/backup.sh") | crontab -
set -euo pipefail

DIR=/var/backups/sedb
KEEP_DAYS=14

install -d -m 750 "$DIR"
STAMP=$(date +%Y%m%d-%H%M)
sudo -u postgres pg_dump -Fc sedb > "$DIR/sedb-$STAMP.dump"
find "$DIR" -name 'sedb-*.dump' -mtime +$KEEP_DAYS -delete

echo "$(date -Is) wrote $DIR/sedb-$STAMP.dump ($(du -h "$DIR/sedb-$STAMP.dump" | cut -f1))"
