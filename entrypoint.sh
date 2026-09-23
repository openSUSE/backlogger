#!/usr/bin/env bash
set -Eeuo pipefail

# Map inputs
CONFIG="${INPUT_CONFIG:-queries.yaml}"
ARGS="${INPUT_ARGS:---exit-code}"
FOLDER="${INPUT_FOLDER:-gh-pages}"
STATE="${INPUT_STATE:-state}"
REDMINE_API_KEY="${INPUT_REDMINE_API_KEY:-${REDMINE_API_KEY:-}}"
WEBHOOK_URL="${INPUT_WEBHOOK_URL:-${WEBHOOK_URL:-}}"
export REDMINE_API_KEY
export WEBHOOK_URL
export STATE_FOLDER="${STATE}"

# Setup GITHUB_TOKEN if available
if [ -n "${INPUT_GITHUB_TOKEN:-}" ]; then
	export GITHUB_TOKEN="${INPUT_GITHUB_TOKEN}"
elif [ -n "${GITHUB_TOKEN:-}" ]; then
	export GITHUB_TOKEN="${GITHUB_TOKEN}"
fi

# Fetch previous state
if [ -d .git ]; then
	echo "Fetching previous state.json from branch: ${FOLDER}"
	git fetch origin "${FOLDER}" || true
	mkdir -p "${STATE}"
	git show "origin/${FOLDER}:state.json" >"${STATE}/state.json" 2>/dev/null || echo "No previous state.json found on branch ${FOLDER}"
else
	echo "Not a git repository, or .git folder not found. Skipping fetching state."
fi

# Render Markdown from configured backlog queries
echo "Running backlogger.py..."
set +e
python3 /app/backlogger.py "${CONFIG}" ${ARGS}
backlog_status=$?
set -e

# Define variables
org="${GITHUB_REPOSITORY_OWNER:-}"
repo=""
if [ -n "${GITHUB_REPOSITORY:-}" ]; then
	repo=$(cut -f2 -d/ <<<"${GITHUB_REPOSITORY}")
fi

extra=""
if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] && [ -n "${GITHUB_EVENT_PATH:-}" ] && [ -f "${GITHUB_EVENT_PATH}" ]; then
	pr_number=$(python3 -c "import json, os; d = json.load(open(os.environ['GITHUB_EVENT_PATH'])); print(d.get('number', d.get('pull_request', {}).get('number', '')))")
	if [ -n "${pr_number}" ]; then
		extra="/pr-preview/pr-${pr_number}"
	fi
fi

preview_date="$(date +%s)"
preview="preview.png"
preview_url="https://${org}.github.io/${repo}${extra}/${preview}?v=${preview_date}"

if [ "${backlog_status}" -eq 0 ]; then
	status_color="#55cc33"
else
	status_color="#cc3333"
fi

# Render HTML
echo "Rendering HTML..."
mkdir -p "${FOLDER}"
cat /app/head.html >"${FOLDER}/index.html"
if [ -f index.md ]; then
	python3 -m markdown index.md >>"${FOLDER}/index.html"
else
	echo "index.md not found!"
fi
cat /app/foot.html >>"${FOLDER}/index.html"

sed -i \
	-e "s@STATUS_COLOR@${status_color}@g" \
	-e "s@GITHUB_REPOSITORY@${GITHUB_REPOSITORY:-}@g" \
	-e "s@PREVIEW_IMAGE_URL@${preview_url}@g" \
	-e "s@WORKFLOW_NAME@${GITHUB_WORKFLOW:-}@g" \
	"${FOLDER}/index.html"

# Render PNG preview
echo "Rendering PNG preview..."
weasyprint "${FOLDER}/index.html" - | convert - -trim "${FOLDER}/${preview}"

# Publish state json
if [ -f state.json ]; then
	echo "Publishing state.json..."
	cp state.json "${FOLDER}/"
fi

echo "Done."
exit "${backlog_status}"
