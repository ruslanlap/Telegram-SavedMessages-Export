#!/usr/bin/env bash
# Recreate (re-tag) a given Git tag at the current HEAD and push it to origin.
# Usage: ./rebuildtag.sh <tag-name> [--yes]
#   --yes   Skip the confirmation prompt.

set -euo pipefail

TAG="${1:-}"
CONFIRM_FLAG="${2:-}"

if [[ -z "$TAG" ]]; then
  echo "Usage: $0 <tag-name> [--yes]" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This script must be run inside a git repository" >&2
  exit 1
fi

if [[ "$CONFIRM_FLAG" != "--yes" ]]; then
  read -r -p "Recreate tag '$TAG' on current HEAD and push to origin (this will delete the existing tag if present). Continue? [y/N] " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
fi

# Ensure we have the latest refs
git fetch --tags

# Delete local tag if it exists
if git show-ref --tags "$TAG" >/dev/null 2>&1; then
  git tag -d "$TAG"
fi

# Delete remote tag if it exists
if git ls-remote --tags origin "$TAG" | grep -q "$TAG"; then
  git push origin :refs/tags/"$TAG"
fi

# Create tag at current HEAD
git tag "$TAG"
# Push tag to origin
git push origin "$TAG"

echo "Tag '$TAG' recreated at $(git rev-parse --short HEAD) and pushed to origin."
