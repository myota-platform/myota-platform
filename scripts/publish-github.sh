#!/usr/bin/env bash
set -euo pipefail

# GitHub organization creation is account-level and may require an interactive
# browser step. Run this after the MyOTA organization exists and gh is logged in.
gh auth status

repos=(
  myota-contracts
  myota-identity-service
  myota-programme-service
  myota-geodata-service
  myota-activity-service
  myota-web
  myota-deploy
  myota-docs
)

for repo in "${repos[@]}"; do
  gh repo create "MyOTA/${repo}" --public --description "MyOTA Outdoor Activation Platform: ${repo}" || true
done

echo "Repositories prepared. Split paths according to docs/repository-map.md, then push each repository."

