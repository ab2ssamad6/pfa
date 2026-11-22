#!/bin/sh
# The trainer runs as the host user (HOST_UID, e.g. 501 on macOS) so repo files are not root-owned.
# That uid has no /etc/passwd entry in the image; tools like DVC call getpwuid() and fail. Register it.
if ! getent passwd "$(id -u)" >/dev/null 2>&1; then
  echo "netad:x:$(id -u):$(id -g):netad:${HOME:-/tmp}:/bin/sh" >> /etc/passwd
fi
exec "$@"
