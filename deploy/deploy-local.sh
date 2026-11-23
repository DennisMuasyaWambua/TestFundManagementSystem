#!/usr/bin/env bash
# Build and start the production stack directly on this host.
#
# Meant for the self-hosted GitHub Actions runner living on srv100 itself: no
# SSH, no password, the runner already has a checkout of the release it
# should run. deploy.py is still there for a manual deploy from elsewhere.
set -euo pipefail

cd "$(dirname "$0")/.."

# actions/checkout wipes untracked files (git clean -ffdx) on every run, but the
# "fms" named Postgres volume survives across runs and across checkouts -- so
# the secrets that match what's actually in that volume have to live somewhere
# checkout never touches, not inside the repo's working tree.
#
# $HOME isn't always set for a systemd-managed runner service, so resolve the
# account's home directory from the password database instead of trusting it.
RUNNER_HOME="${HOME:-$(eval echo "~$(whoami)")}"
ENV_PATH="${FMS_DEPLOY_ENV_PATH:-$RUNNER_HOME/.fms-deploy.env}"
echo "== Using secrets file: $ENV_PATH (exists: $([ -f "$ENV_PATH" ] && echo yes || echo no)) =="

if [ ! -f "$ENV_PATH" ]; then
  echo "== Writing a fresh $ENV_PATH =="
  cat > "$ENV_PATH" <<EOF
POSTGRES_USER=fms
POSTGRES_PASSWORD=$(openssl rand -base64 24)
POSTGRES_DB=fms
FMS_SECRET_KEY=$(openssl rand -hex 32)
NEXT_SERVER_ACTIONS_ENCRYPTION_KEY=$(openssl rand -base64 32)
WEB_PORT=3100
API_PORT=8101
EOF
else
  # A later run can still introduce a new required key without touching a
  # secret that's already there.
  grep -q '^NEXT_SERVER_ACTIONS_ENCRYPTION_KEY=' "$ENV_PATH" ||
    echo "NEXT_SERVER_ACTIONS_ENCRYPTION_KEY=$(openssl rand -base64 32)" >> "$ENV_PATH"
fi

COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file $ENV_PATH -p fms"

echo "== Building and starting the stack =="
if ! $COMPOSE up -d --build; then
  echo "One of the one-shot steps failed; recent logs:" >&2
  $COMPOSE logs --tail=200 migrate seed
  exit 1
fi

echo "== Waiting for the API to report healthy =="
status=""
for _ in $(seq 1 30); do
  status=$($COMPOSE ps api --format '{{.Health}}' 2>/dev/null || echo "")
  [ "$status" = "healthy" ] && break
  sleep 4
done
if [ "$status" != "healthy" ]; then
  echo "API did not become healthy in time; recent logs:" >&2
  $COMPOSE logs --tail=80 api
  exit 1
fi
echo "   healthy"

echo "== Seed output (temporary passwords, only printed the first time) =="
$COMPOSE logs seed

# The nginx site rarely changes and installing it needs sudo, which this
# runner's service account need not have. Re-run with --install-nginx by
# hand (or set INSTALL_NGINX=1) after an actual change to nginx-fms.conf.
if [ "${INSTALL_NGINX:-}" = "1" ] || [ "${1:-}" = "--install-nginx" ]; then
  echo "== Installing the nginx site =="
  sudo cp deploy/nginx-fms.conf /etc/nginx/sites-available/fms
  sudo ln -sf /etc/nginx/sites-available/fms /etc/nginx/sites-enabled/fms
  sudo nginx -t
  sudo systemctl reload nginx
  echo "   nginx site installed"
fi

echo "== Verifying =="
source "$ENV_PATH"
curl -fsS "http://127.0.0.1:${API_PORT:-8101}/api/v1/health"

echo "== Done =="
