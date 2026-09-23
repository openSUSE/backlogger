#!/usr/bin/env python3
import os
import subprocess
import json
import time
import shutil
import sys
import markdown

def run_command(cmd, check=True):
    return subprocess.run(cmd, shell=True, check=check, text=True)

def main():
    # Map inputs
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

    # Fetch previous state
    if os.path.isdir(".git"):
        print(f"Fetching previous state.json from branch: {folder}")
        run_command(f"git fetch origin {folder}", check=False)
        os.makedirs(state_folder, exist_ok=True)
        res = run_command(f"git show origin/{folder}:state.json > {state_folder}/state.json", check=False)
        if res.returncode != 0:
            print(f"No previous state.json found on branch {folder}")
    else:
        print("Not a git repository, or .git folder not found. Skipping fetching state.")

    # Run backlogger
    print("Running backlogger.py...")
    res = run_command(f"python3 backlogger.py {config} {args}", check=False)
    backlog_status = res.returncode

    # Define variables
    org = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    repo = github_repository.split("/")[1] if github_repository else ""
    
    extra = ""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_name == "pull_request" and event_path and os.path.isfile(event_path):
        with open(event_path) as f:
            d = json.load(f)
            pr_number = d.get('number', d.get('pull_request', {}).get('number', ''))
            if pr_number:
                extra = f"/pr-preview/pr-{pr_number}"

    preview_date = int(time.time())
    preview = "preview.png"
    preview_url = f"https://{org}.github.io/{repo}{extra}/{preview}?v={preview_date}"

    status_color = "#55cc33" if backlog_status == 0 else "#cc3333"

    # Render HTML
    print("Rendering HTML...")
    os.makedirs(folder, exist_ok=True)
    
    with open("head.html", "r") as f:
        html_content = f.read()
        
    if os.path.isfile("index.md"):
        with open("index.md", "r") as f:
            md_text = f.read()
            html_content += markdown.markdown(md_text, extensions=['tables'])
    else:
        print("index.md not found!")
        
    with open("foot.html", "r") as f:
        html_content += f.read()

    # Replace variables
    html_content = html_content.replace("STATUS_COLOR", status_color)
    html_content = html_content.replace("GITHUB_REPOSITORY", github_repository)
    html_content = html_content.replace("PREVIEW_IMAGE_URL", preview_url)
    html_content = html_content.replace("WORKFLOW_NAME", os.environ.get("GITHUB_WORKFLOW", ""))

    index_html_path = os.path.join(folder, "index.html")
    with open(index_html_path, "w") as f:
        f.write(html_content)

    # Render PNG preview
    print("Rendering PNG preview...")
    run_command(f"weasyprint {index_html_path} - | convert - -trim {os.path.join(folder, preview)}")

    # Publish state json
    if os.path.isfile("state.json"):
        print("Publishing state.json...")
        shutil.copy("state.json", folder)

    print("Done.")
    sys.exit(backlog_status)

if __name__ == "__main__":
    main()
