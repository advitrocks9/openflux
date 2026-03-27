#!/bin/bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Building base image ==="
docker build -t openflux-base -f tests/acceptance/Dockerfile.base .

echo "=== Running acceptance tests ==="
if [ $# -eq 0 ]; then
    # No args: run free adapters only
    echo "(Running free adapters only. Pass service names or --profile all for everything.)"
    docker compose -f tests/acceptance/docker-compose.yml --profile free up --build --abort-on-container-exit
else
    docker compose -f tests/acceptance/docker-compose.yml up --build --abort-on-container-exit "$@"
fi
