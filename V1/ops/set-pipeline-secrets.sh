#!/usr/bin/env bash
#
# Set the four GitHub secrets the daily pipeline needs. It asks for the two
# values it cannot read itself and never prints any value.
#
#     ops/set-pipeline-secrets.sh
#
#   DB167_ODBC             read from .env
#   CLOUDFLARE_ACCOUNT_ID  the Cloudflare account's id (not a password)
#   PIPELINE_DATABASE_URL  built from the website database's password, which
#                          it asks for (the user and database are sedb, as in
#                          ops/pull-db.sh; the host is localhost because the
#                          workflow reaches the droplet through an SSH tunnel)
#   CLOUDFLARE_API_TOKEN   asked for
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=${REPO:-Boaxes/Cascadia-DB}
ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID:-4f2aa5ca781647492809591808a182ec}

grep -q '^DB167_ODBC=.\{20,\}' .env || { echo "DB167_ODBC is not filled in in .env" >&2; exit 1; }
printf %s "$(grep '^DB167_ODBC=' .env | cut -d= -f2-)" | gh secret set DB167_ODBC --repo "$REPO"
printf %s "$ACCOUNT_ID" | gh secret set CLOUDFLARE_ACCOUNT_ID --repo "$REPO"

read -rsp "Website database password (sedb): " PW; echo
PW="$PW" python3 -c 'import os, urllib.parse as u; print("postgresql://sedb:%s@localhost:5432/sedb" % u.quote(os.environ["PW"], safe=""), end="")' \
    | gh secret set PIPELINE_DATABASE_URL --repo "$REPO"
unset PW

read -rsp "Cloudflare API token: " TOKEN; echo
printf %s "$TOKEN" | gh secret set CLOUDFLARE_API_TOKEN --repo "$REPO"
unset TOKEN
echo "Done. Secrets now set:"; gh secret list --repo "$REPO" | cut -f1
