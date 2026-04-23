#!/bin/bash

docker stop ix-missav-dlp-web-missav-dlp-web-1


# ▼▼▼ [Core Fix] ▼▼▼
# Force delete all local .pyc cache files before running docker build
echo "Cleaning up local __pycache__ directories..."
find . -type d -name "__pycache__" -exec rm -r {} +
find . -type f -name "*.pyc" -delete
# ▲▲▲ [Fix Complete] ▲▲▲

# Delete all unused Docker resources (images, containers, networks, volumes)
echo "Pruning Docker system..."
docker system prune -a -f

# Build a new Docker image without using cache
echo "Building new Docker image..."
docker build -t nerdnam/missav-dlp-web:0.0.1 --no-cache .

echo "Script finished."