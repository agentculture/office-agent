#!/usr/bin/env bash
# Fetch GitHub issues with full body and comments
# Usage: gh-issues.sh [RANGE|NUMBER] [--repo OWNER/REPO]
#   gh-issues.sh 191-197          # range
#   gh-issues.sh 191              # single
#   gh-issues.sh 191 192 195      # list
#   gh-issues.sh --repo foo/bar 5 # explicit repo

set -euo pipefail

REPO_FLAG=""
NUMBERS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: --repo requires a value (OWNER/REPO)" >&2
        echo "Usage: gh-issues.sh [RANGE|NUMBER...] [--repo OWNER/REPO]" >&2
        exit 1
      fi
      REPO_FLAG="--repo $2"
      shift 2 ;;
    *-*)  # range like 191-197
      IFS='-' read -r start end <<< "$1"
      for ((i=start; i<=end; i++)); do NUMBERS+=("$i"); done
      shift ;;
    *)  NUMBERS+=("$1"); shift ;;
  esac
done

if [[ ${#NUMBERS[@]} -eq 0 ]]; then
  echo "Usage: gh-issues.sh [RANGE|NUMBER...] [--repo OWNER/REPO]" >&2
  exit 1
fi

for num in "${NUMBERS[@]}"; do
  echo "========================================"
  echo "ISSUE #${num}"
  echo "========================================"
  # shellcheck disable=SC2086
  gh issue view "$num" $REPO_FLAG --json number,title,state,labels,body,comments \
    --jq '{
      number: .number,
      title: .title,
      state: .state,
      labels: [.labels[].name],
      body: .body,
      comments: [.comments[] | {author: .author.login, body: .body}]
    }' 2>/dev/null || echo "ERROR: Could not fetch issue #${num}"
  echo
done
