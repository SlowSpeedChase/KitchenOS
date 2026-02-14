#!/usr/bin/env bash
# scripts/analyze_failures.sh
# Analyzes batch extract failures using Claude Code CLI.
# Called by batch_extract.py when failures occur.
#
# Usage: ./scripts/analyze_failures.sh <failure_log_path>

set -euo pipefail

FAILURE_LOG="$1"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$FAILURE_LOG" ]; then
    echo "Error: Failure log not found: $FAILURE_LOG"
    exit 1
fi

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "Error: claude CLI not found. Install Claude Code to enable failure analysis."
    exit 1
fi

# Read the failure log
FAILURE_DATA=$(cat "$FAILURE_LOG")

# Build the prompt
PROMPT="You are analyzing batch recipe extraction failures for KitchenOS.

## Failure Log
\`\`\`json
${FAILURE_DATA}
\`\`\`

## Instructions

1. Read the failure log above carefully.
2. Skip any failures with error_category 'network' — these are transient.
3. For each non-transient failure:
   a. Read the relevant source code to understand the error.
   b. Try to reproduce with: .venv/bin/python extract_recipe.py --dry-run \"<url>\"
   c. Identify the root cause.
4. If you can fix the issue:
   a. Create a branch: git checkout -b fix/batch-failure-\$(date +%Y-%m-%d)
   b. Write the fix with tests.
   c. Commit and push.
   d. Create a PR with: gh pr create --title \"fix: <description>\" --body \"<details>\"
5. If the failure is unfixable (video deleted, private, etc.), note it in your output.

IMPORTANT: Read CLAUDE.md first for project conventions. Run tests before committing."

echo "=== Failure Analysis Agent ==="
echo "Analyzing: $FAILURE_LOG"
echo "Started: $(date)"
echo ""

cd "$PROJECT_ROOT"
claude -p "$PROMPT" --allowedTools "Edit,Bash,Read,Grep,Glob,Write"

echo ""
echo "Analysis complete: $(date)"
