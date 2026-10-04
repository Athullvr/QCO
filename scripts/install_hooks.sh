#!/usr/bin/env bash
set -e
root=$(git rev-parse --show-toplevel)
install -m 755 "$root/.githooks/pre-commit" "$(git rev-parse --git-path hooks)/pre-commit"
echo "installed pre-commit hook"
