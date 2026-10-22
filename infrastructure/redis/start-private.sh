#!/bin/sh
set -eu

# Avoid putting credentials in redis-server's process arguments or logs.
: "${REDIS_PASSWORD:?REDIS_PASSWORD is required}"
if [ "${#REDIS_PASSWORD}" -lt 32 ]; then
  echo 'REDIS_PASSWORD must contain at least 32 URL-safe characters' >&2
  exit 1
fi
case "$REDIS_PASSWORD" in
  *[!A-Za-z0-9_-]*)
    echo 'REDIS_PASSWORD must contain only URL-safe letters, digits, underscore or hyphen' >&2
    exit 1
    ;;
esac
umask 077
config_dir=$(mktemp -d /tmp/finsight-redis.XXXXXX)
printf 'bind 0.0.0.0\nprotected-mode yes\nrequirepass %s\n' "$REDIS_PASSWORD" > "$config_dir/redis.conf"
unset REDIS_PASSWORD REDISCLI_AUTH
exec redis-server "$config_dir/redis.conf"
