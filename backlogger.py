#!/usr/bin/env python3
import argparse
import os
import sys
import json
from statistics import mean
from datetime import datetime, timedelta
from inspect import getmembers, isfunction
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse
import yaml
import re


# Icons used for PASS or FAIL in the md file
result_icons = {"pass": "&#x1F49A;", "fail": "&#x1F534;"}
reminder_text = "This ticket was set to **{priority}** priority but was not updated [within the SLO period]({url}). Please consider picking up this ticket or just set the ticket to the next lower priority."
reminder_regex = r"^This ticket was set to .* priority but was not updated.* Please consider"

# Initialize a blank md file to replace the current README
def initialize_md(data):
    with open("index.md", "w") as md:
        md.write("# Backlog Status\n\n")
        md.write(
            "This is the dashboard for [{}]({}).\n".format(data["team"], data["url"])
        )
        md.write(
            "**Latest Run:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " UTC\n"
        )
        md.write("*(Please refresh to see latest results)*\n\n")
        md.write(
            "Backlog Query | Number of Issues | Limits | Status\n--- | --- | --- | ---\n"
        )


def get_link(conf):
    return data["web"] + "?" + conf["query"]


# Append individual results to md file
def results_to_md(conf, number, status):
    mdlink = "[" + conf["title"] + "](" + get_link(conf) + ")"
    lessthan = conf["max"] + 1
    limits = "<" + str(lessthan)
    if "min" in conf:
        limits += ", >" + str(conf["min"] - 1)
    with open("index.md", "a") as md:
        md.write(mdlink + " | " + str(number) + " | " + limits + " | " + status + "\n")


def retry_request(method, url, data, headers, attempts=7):
    retries = Retry(total=attempts, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    http = requests.Session()
    parsed_url = urlparse(url)
    http.mount("{}://".format(parsed_url.scheme), HTTPAdapter(max_retries=retries))
    return http.request(method, url, data=data, headers=headers)


def json_rest(method, url, rest=None):
    text = json.dumps(rest)
    try:
        key = os.environ["REDMINE_API_KEY"]
    except KeyError:
        exit("REDMINE_API_KEY is required to be set")
    headers = {
        "User-Agent": "backlogger ({})".format(data["url"]),
        "Content-Type": "application/json",
        "X-Redmine-API-Key": key,
    }
    r = retry_request(method, url, data=text, headers=headers)
    r.raise_for_status()
    return r.json() if r.text else None


def issue_reminder(conf, poo):
    priority = poo["priority"]["name"]
    msg = reminder_text.format(
        priority=priority, url=data["url"]
    )
    if "comment" in conf:
        msg = conf["comment"]
    if data["reminder-comment-on-issues"]:
        if reminder_exists(conf, poo, msg):
            return
        url = "{}/{}.json".format(data["web"], poo["id"])
        json_rest("PUT", url, {"issue": {"notes": msg}})


def list_issues(conf, root):
    try:
        for poo in root["issues"]:
            if "updated_on" in conf["query"]:
                issue_reminder(conf, poo)
    except KeyError:
        print("There was an error retrieving the issues " + conf["title"])
    else:
        return int(root["total_count"])


def reminder_exists(conf, poo, msg):
    url = "{}/{}.json".format(data["web"], poo["id"])
    root = json_rest("GET", url)
    if root is not None and 'journals' in root['issue']:
        journals = root['issue']['journals']
        for journal in journals:
            if not 'notes' in journal or len(journal['notes']) == 0:
                continue
            if re.search(reminder_regex, journal['notes']):
                return True
    return False


def failure_more(conf):
    print(conf["title"] + " has more than " + str(conf["max"]) + " tickets!")
    return False


def check_backlog(conf):
    root = json_rest("GET", data["api"] + "?" + conf["query"])
    issue_count = list_issues(conf, root)
    res = not(issue_count > conf["max"] or "min" in conf and issue_count < conf["min"])
    return (res, issue_count)


def check_query(data):
    for conf in data["queries"]:
        res = check_backlog(conf)
        results_to_md(
            conf, res[1], result_icons["pass"] if res[0] else result_icons["fail"]
        )


def cycle_time(issue, status_ids):
    start = datetime.strptime(issue["created_on"], "%Y-%m-%dT%H:%M:%SZ")
    cycle_time = 0

    url = "{}/{}.json?include=journals".format(data["web"], issue["id"])
    issue = json_rest("GET", url)["issue"]
    for journal in issue["journals"]:
        for detail in journal["details"]:
            if detail["name"] == "status_id":
                if detail["new_value"] == str(status_ids["In Progress"]):
                    start = datetime.strptime(journal["created_on"], "%Y-%m-%dT%H:%M:%SZ")
                elif detail["old_value"] == str(status_ids["In Progress"]):
                    end = datetime.strptime(journal["created_on"], "%Y-%m-%dT%H:%M:%SZ")
                    cycle_time += (end - start).total_seconds() / 3600
    return cycle_time


def render_influxdb(data):
    output = []

    statuses = json_rest("GET", data["api"].replace("issues", "issue_statuses"))
    status_ids = {}
    for status in statuses["issue_statuses"]:
        status_ids[status["name"]] = status["id"]

    for conf in data["queries"]:
        root = json_rest("GET", data["api"] + "?" + conf["query"])
        issue_count = list_issues(conf, root)
        status_names = []
        result = {}
        for issue in root["issues"]:
            status = issue["status"]["name"]
            if status not in status_names:
                status_names.append(status)
                result[status] = {"avg": 0, "leadTime": [], "cycleTime": []}

            start = datetime.strptime(issue["created_on"], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(issue["updated_on"], "%Y-%m-%dT%H:%M:%SZ")
            result[status]["leadTime"].append((end - start).total_seconds() / 3600)
            if status == "Resolved":
                result[status]["cycleTime"].append(cycle_time(issue, status_ids))
        for status in status_names:
            count = len(result[status]["leadTime"])
            if status == "Resolved":
                measure = "leadTime"
                extra = " leadTime={leadTime} cycleTime={cycleTime}".format(
                    leadTime=mean(result[status]["leadTime"]),
                    cycleTime=mean(result[status]["cycleTime"]),
                )
            else:
                measure = "slo"
                extra = ""
            output.append(
                '{measure},team="{team}",status="{status}",title="{title}" count={count}{extra}'.format(
                    measure=measure,
                    team=data["team"],
                    status=status,
                    title=conf["title"],
                    count=count,
                    extra=extra,
                )
            )
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('config', default='queries.yaml', nargs='?')
    parser.add_argument('--output', choices=['markdown', 'influxdb'], default='markdown')
    parser.add_argument("--reminder-comment-on-issues", action='store_false')
    switches = parser.parse_args()
    try:
        with open(switches.config, "r") as config:
            data = yaml.safe_load(config)
            data['output'] = switches.output
            data['reminder-comment-on-issues'] = switches.reminder_comment_on_issues
            if switches.output == 'influxdb':
                print("\n".join(line for line in render_influxdb(data)))
            else:
                initialize_md(data)
                check_query(data)
    except FileNotFoundError:
        sys.exit("Configuration file {} not found".format(switches.config))
