"""Drop privileges from root to the unprivileged application user, then exec.

A persistent volume is mounted *after* the image is built, which discards any
ownership set at build time. On Railway, Fly, Docker volumes and Kubernetes
alike the mount arrives owned by root, so the application user cannot create
the SQLite file and startup dies with "unable to open database file".

The entrypoint therefore starts as root, repairs ownership, and hands over to
this module, which becomes the application user and execs the server in the same
process. Doing the drop in Python rather than via gosu or su-exec keeps the
image free of an extra package that has to exist in the base image's archive,
and it means the server keeps PID 1, so SIGTERM reaches it directly and the
container still stops promptly.
"""

from __future__ import annotations

import os
import sys

APP_UID = 10001
APP_GID = 10001


def drop_privileges() -> None:
    if os.getuid() != 0:
        return
    # Order matters: supplementary groups and the group must be set while still
    # root, and the user id last, because it is irreversible.
    os.setgroups([APP_GID])
    os.setgid(APP_GID)
    os.setuid(APP_UID)
    os.environ["HOME"] = "/home/odyssey"


def main(argv: list[str]) -> int:
    if not argv:
        print("drop-privs: nothing to execute", file=sys.stderr)
        return 1
    drop_privileges()
    if os.getuid() == 0:
        print("drop-privs: failed to drop privileges", file=sys.stderr)
        return 1
    os.execvp(argv[0], argv)
    return 0  # unreachable unless exec fails


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
