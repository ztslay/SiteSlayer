#!/bin/bash
# Script to deploy the SiteSlayer web server to Fly.io.

set -e  # Exit on error

# Ensure we're on main branch
current_branch=$(git branch --show-current)
if [ "$current_branch" != "main" ]; then
    echo "Switching to main branch..."
    git checkout main
fi

# Stash any current work
echo "Stashing current work..."
git stash push -m "deploy_server.sh stash"

# Pull remote main
echo "Pulling remote main..."
git pull --no-edit origin main

# Reapply stashed changes
echo "Reapplying stashed changes..."
git stash pop || true  # Continue even if stash pop has conflicts

# Add, commit, and push
echo "Adding, committing, and pushing..."
git add .
git commit -am"deploy_server.sh"
git push origin main