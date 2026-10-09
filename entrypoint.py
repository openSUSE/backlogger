#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import time

import markdown


def run_command(cmd, check=True):
    return subprocess.run(cmd, shell=True, check=check, text=True)


def check_render(html_text):
    pipe = re.compile(r"^\s*\|.*\|\s*$")
    sep = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
    leaks, group = [], []
    for i, line in enumerate(html_text.splitlines() + [""], 1):
        if pipe.match(line):
            group.append((i, line.strip()))
        elif group:
            if len(group) >= 2 or any(sep.match(t) for _, t in group):
                leaks.append((group[0][0], group[-1][0], group[0][1]))
            group = []
    return leaks


def main():
    config = os.environ.get("INPUT_CONFIG", "queries.yaml")
    args = os.environ.get("INPUT_ARGS", "--exit-code")
    folder = os.environ.get("INPUT_FOLDER", "gh-pages")
    state_folder = os.environ.get("INPUT_STATE", "state")

    if "INPUT_REDMINE_API_KEY" in os.environ:
        os.environ["REDMINE_API_KEY"] = os.environ["INPUT_REDMINE_API_KEY"]
    if "INPUT_WEBHOOK_URL" in os.environ:
        os.environ["WEBHOOK_URL"] = os.environ["INPUT_WEBHOOK_URL"]

    os.environ["STATE_FOLDER"] = state_folder

    if "INPUT_GITHUB_TOKEN" in os.environ:
        os.environ["GITHUB_TOKEN"] = os.environ["INPUT_GITHUB_TOKEN"]

    # Configure git to trust the workspace directory to avoid dubious ownership errors in container
    run_command(
        "git config --global --add safe.directory /github/workspace", check=False
    )

    if os.path.isdir(".git"):
        print(f"Fetching previous state.json from branch: {folder}")
        run_command(f"git fetch origin {folder}", check=False)
        os.makedirs(state_folder, exist_ok=True)
        res = run_command(
            f"git show origin/{folder}:state.json > {state_folder}/state.json",
            check=False,
        )
        if res.returncode != 0:
            print(f"No previous state.json found on branch {folder}")
            state_file_path = os.path.join(state_folder, "state.json")
            if os.path.exists(state_file_path):
                os.remove(state_file_path)
    else:
        print(
            "Not a git repository, or .git folder not found. Skipping fetching state."
        )

    print("Running backlogger.py...")
    res = run_command(f"python3 backlogger.py {config} {args}", check=False)
    backlog_status = res.returncode

    org = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    repo = github_repository.split("/")[1] if github_repository else ""

    extra = ""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_name == "pull_request" and event_path and os.path.isfile(event_path):
        with open(event_path) as f:
            d = json.load(f)
            pr_number = d.get("number", d.get("pull_request", {}).get("number", ""))
            if pr_number:
                extra = f"/pr-preview/pr-{pr_number}"

    preview_date = int(time.time())
    preview = "preview.png"
    preview_url = f"https://{org}.github.io/{repo}{extra}/{preview}?v={preview_date}"

    status_color = "#55cc33" if backlog_status == 0 else "#cc3333"

    print("Rendering HTML...")
    os.makedirs(folder, exist_ok=True)

    with open("head.html", "r") as f:
        html_content = f.read()

    body_html = ""
    if os.path.isfile("index.md"):
        with open("index.md", "r") as f:
            md_text = f.read()
            body_html = markdown.markdown(md_text, extensions=["tables"])
        html_content += body_html
    else:
        print("index.md not found!")

    with open("foot.html", "r") as f:
        html_content += f.read()

    html_content = html_content.replace("STATUS_COLOR", status_color)
    html_content = html_content.replace("GITHUB_REPOSITORY", github_repository)
    html_content = html_content.replace("PREVIEW_IMAGE_URL", preview_url)
    html_content = html_content.replace(
        "WORKFLOW_NAME", os.environ.get("GITHUB_WORKFLOW", "")
    )

    index_html_path = os.path.join(folder, "index.html")
    with open(index_html_path, "w") as f:
        f.write(html_content)

    leaks = check_render(body_html)
    if leaks:
        print(
            "Render check FAILED: markdown tables leaked as raw text "
            "(markdown is not parsed inside <details>):"
        )
        for first, last, header in leaks:
            print(f"  body lines {first}-{last}: {header}")
        sys.exit(2)

    print("Rendering PNG preview...")
    run_command(
        f"weasyprint {index_html_path} - | convert - -trim {os.path.join(folder, preview)}"
    )

    if os.path.isfile("state.json"):
        print("Publishing state.json...")
        shutil.copy("state.json", folder)

    print("Done.")
    sys.exit(backlog_status)


if __name__ == "__main__":
    main()
