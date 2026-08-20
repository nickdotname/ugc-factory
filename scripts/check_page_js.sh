#!/usr/bin/env bash
# Syntax-check the dashboard's JavaScript as the browser actually receives it.
#
# Extracting it from src/web.py by regex reads *source* text, where a backslash
# is still escaped for Python — so `\\s` there looks different from the `\s` a
# browser gets. Fetching from a running server removes the guesswork.
#
# Catches the failure mode that has no console output: a duplicate `const`
# kills the whole <script> silently, and the page renders as an empty shell.
set -euo pipefail
port="${1:-8765}"
tmp="$(mktemp -t ugcpage).js"
curl -fsS "http://127.0.0.1:${port}/" \
  | sed -n '/<script>/,/<\/script>/p' | sed '1d;$d' > "$tmp"
node --check "$tmp" && echo "dashboard JS: syntax OK ($(wc -l < "$tmp" | tr -d ' ') lines)"
rm -f "$tmp"
