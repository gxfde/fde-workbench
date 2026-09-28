#!/usr/bin/env bash

set -u

status=0

if command -v mysqladmin >/dev/null 2>&1 && mysqladmin ping --silent >/dev/null 2>&1; then
  echo "MySQL: available"
else
  echo "MySQL: unavailable"
  echo "Start with: brew services start mysql"
  status=1
fi

if command -v redis-cli >/dev/null 2>&1 && [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
  echo "Redis: available"
else
  echo "Redis: unavailable"
  echo "Start with: brew services start redis"
  status=1
fi

exit "$status"
