#!/usr/bin/env bash
# Co-locate the shared package into each hosted-agent folder so it is included
# in the azd direct-code-deploy zip. Source of truth: agents/shared.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="agents/shared"
for agent in risk_analyzer forensics workflow; do
  DEST="agents/$agent/shared"
  rm -rf "$DEST"
  cp -R "$SRC" "$DEST"
  echo "synced shared -> $DEST"
done
