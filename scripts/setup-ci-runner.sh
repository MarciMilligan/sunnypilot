#!/usr/bin/env bash
# Provision an AGNOS device (comma 3/3X) that hosts a GitHub Actions runner.
#
# AGNOS mounts /home as a 100MB overlay and /tmp as a 150MB tmpfs, but the model
# build workflows create a ~2GB uv venv at ${HOME}/venv and stage wheels through
# TMPDIR. Point HOME, TMPDIR and the uv cache at /data so builds have room, and
# so uv can hardlink from its cache instead of copying across filesystems.
#
# Runner.Listener loads $RUNNER_ROOT/.env into the job environment at startup,
# so this needs no workflow changes and survives AGNOS updates.
#
# Safe to re-run. Register the runner and install its service first.

set -e

RUNNER_ROOT="${RUNNER_ROOT:-/data/actions-runner}"
RUNNER_USER="${RUNNER_USER:-$(id -un)}"
RUNNER_HOME="${RUNNER_HOME:-/data/runner-home}"
UV_ROOT="${UV_ROOT:-/data/uv}"
ENV_FILE="$RUNNER_ROOT/.env"

if [ ! -d "$RUNNER_ROOT" ]; then
  echo "error: no runner at $RUNNER_ROOT" >&2
  echo "register the runner first, or set RUNNER_ROOT" >&2
  exit 1
fi

# svc.sh records the systemd unit name here when the service is installed.
SERVICE=""
if [ -f "$RUNNER_ROOT/.service" ]; then
  SERVICE="$(cat "$RUNNER_ROOT/.service")"
fi

if [ -n "$SERVICE" ]; then
  echo "stopping $SERVICE"
  sudo systemctl stop "$SERVICE" || true
fi

# Reclaim the /home overlay. Failed runs leave these behind owned by root.
USER_HOME="$(getent passwd "$RUNNER_USER" | cut -d: -f6)"
for stale in "$USER_HOME/venv" "$USER_HOME/uv" "$USER_HOME/.cache/uv"; do
  if [ -e "$stale" ]; then
    echo "removing stale $stale"
    sudo rm -rf "$stale"
  fi
done

echo "creating $RUNNER_HOME and $UV_ROOT"
sudo mkdir -p "$RUNNER_HOME" "$UV_ROOT/cache" "$UV_ROOT/tmp"
sudo chown -R "$RUNNER_USER" "$RUNNER_HOME" "$UV_ROOT"

echo "updating $ENV_FILE"
touch "$ENV_FILE"
scratch="$(mktemp)"
grep -vE '^(HOME|TMPDIR|UV_CACHE_DIR)=' "$ENV_FILE" > "$scratch" || true
cat >> "$scratch" <<EOF
HOME=$RUNNER_HOME
TMPDIR=$UV_ROOT/tmp
UV_CACHE_DIR=$UV_ROOT/cache
EOF
cp "$scratch" "$ENV_FILE"
rm -f "$scratch"

if [ -n "$SERVICE" ]; then
  echo "starting $SERVICE"
  sudo systemctl start "$SERVICE"
else
  echo "note: no service installed, nothing to restart"
fi

echo
echo "--- $ENV_FILE ---"
cat "$ENV_FILE"
echo
df -h "$USER_HOME" /data
