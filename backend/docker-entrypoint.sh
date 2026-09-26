#!/bin/sh
# Container entrypoint.
#
# Volumes are mounted after the image is built, so any ownership set at build
# time is gone and the mount arrives owned by root. The application runs as an
# unprivileged user, so something has to bridge that gap before the server can
# create its database. This script starts as root, makes the writable paths
# usable, and hands over to drop_privs.py, which becomes the application user
# and execs the server.
#
# When the mount already has the right ownership -- a plain `docker run` with
# no volume, or a host that mounts volumes as the application user -- the chown
# is a no-op and the drop is skipped, so this is safe to run repeatedly.

set -e

DATA_DIR="${DATA_DIR:-/srv/app/data}"
UPLOAD_DIR="${UPLOAD_DIR:-/srv/app/data/uploads}"
APP_USER="${APP_USER:-odyssey}"

mkdir -p "$DATA_DIR" "$UPLOAD_DIR"

if [ "$(id -u)" = "0" ]; then
    chown -R "$APP_USER:$APP_USER" "$DATA_DIR" "$UPLOAD_DIR"
    chmod -R u+rwX "$DATA_DIR" "$UPLOAD_DIR"
    exec python /usr/local/bin/drop_privs.py "$@"
fi

exec "$@"
