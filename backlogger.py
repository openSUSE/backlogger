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
reminder_regex = (
    r"^This ticket was set to .* priority but was not updated.* Please consider"
)


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


def retry_request(method, url, data, headers, attempts=7):
    retries = Retry(
        total=attempts, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
    )
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
    msg = reminder_text.format(priority=priority, url=data["url"])
    if "comment" in conf:
        msg = conf["comment"]
    if data["reminder-comment-on-issues"]:
        if reminder_exists(conf, poo, msg):
            print("Skipping reminder for {}: a similar reminder already exists".format(poo["id"]))
            return
        print("Writing reminder for {}".format(poo["id"]))
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
    url = "{}/{}.json?include=journals".format(data["web"], poo["id"])
    root = json_rest("GET", url)
    if root is None:
        # Redmine returns a 302 to the login page for some issues
        # https://progress.opensuse.org/issues/157867
        sys.stderr.write("API for {} returned None, skipping reminder".format(poo["id"]))
        return True
    if "journals" in root["issue"]:
        journals = root["issue"]["journals"]
        for journal in journals:
            if not "notes" in journal or len(journal["notes"]) == 0:
                continue
            if re.search(reminder_regex, journal["notes"]):
                return True
    return False


def failure_more(conf):
    print(conf["title"] + " has more than " + str(conf["max"]) + " tickets!")
    return False


def check_backlog(conf):
    root = json_rest("GET", data["api"] + "?" + conf["query"])
    issue_count = list_issues(conf, root)
    good = True
    if "max" in conf:
        good = not (
            issue_count > conf["max"] or "min" in conf and issue_count < conf["min"]
        )
    return (good, issue_count)


def render_table(data):
    all_good = True
    rows = []
    bad_queries = {}
    for conf in data["queries"]:
        good, issue_count = check_backlog(conf)
        url = data["web"] + "?" + conf["query"]
        limits = "<" + str(conf["max"] + 1) if "max" in conf else ""
        if "min" in conf:
            limits += ", >" + str(conf["min"] - 1)
        rows.append(
            [
                "[" + conf["title"] + "](" + url + ")",
                str(issue_count),
                limits,
                result_icons["pass"] if good else result_icons["fail"],
            ]
        )
        if not good:
            all_good = False
            bad_queries[conf['title']] = {"url": url, "issue_count": issue_count, "limits": limits}
    return (all_good, rows, bad_queries)

def remove_project_part_from_url(url):
    return(re.sub("projects/.*/", "", url))

def cycle_time(issue, status_ids):
    start = datetime.strptime(issue["created_on"], "%Y-%m-%dT%H:%M:%SZ")
    cycle_time = 0
    in_cycle_status = [str(status_ids["In Progress"]), str(status_ids["Feedback"])]
    url = "{}/{}.json?include=journals".format(remove_project_part_from_url(data["web"]), issue["id"])
    issue = json_rest("GET", url)["issue"]
    for journal in issue["journals"]:
        for detail in journal["details"]:
            if detail["name"] == "status_id":
                if detail["new_value"] in in_cycle_status:
                    start = datetime.strptime(
                        journal["created_on"], "%Y-%m-%dT%H:%M:%SZ"
                    )
                elif detail["old_value"] in in_cycle_status:
                    end = datetime.strptime(journal["created_on"], "%Y-%m-%dT%H:%M:%SZ")
                    cycle_time += (end - start).total_seconds()
    return cycle_time


def _today_nanoseconds():
    dt = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    epoch = datetime.utcfromtimestamp(0)
    return int((dt - epoch).total_seconds() * 1000000000)


def render_influxdb(data):
    output = []

    statuses = json_rest("GET", remove_project_part_from_url(data["api"]).replace("issues", "issue_statuses"))
    status_ids = {}
    for status in statuses["issue_statuses"]:
        status_ids[status["name"]] = status["id"]

    for conf in data["queries"]:
        root = json_rest("GET", data["api"] + "?" + conf["query"] + "&limit=100")
        issue_count = list_issues(conf, root)
        status_names = []
        result = {}
        for issue in root["issues"]:
            status = issue["status"]["name"]
            if status not in status_names:
                status_names.append(status)
                result[status] = {"leadTime": [], "cycleTime": []}

            start = datetime.strptime(issue["created_on"], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(issue["updated_on"], "%Y-%m-%dT%H:%M:%SZ")
            result[status]["leadTime"].append((end - start).total_seconds())
            if status == "Resolved":
                result[status]["cycleTime"].append(cycle_time(issue, status_ids))
        for status in status_names:
            times = result[status]
            count = len(times["leadTime"])
            if status == "Resolved":
                measure = "leadTime"
                extra = ",leadTime={leadTime},cycleTime={cycleTime},leadTimeSum={leadTimeSum},cycleTimeSum={cycleTimeSum}".format(
                    leadTime=escape_telegraf_str(mean(times["leadTime"]) / 3600, "field value"),
                    cycleTime=escape_telegraf_str(mean(times["cycleTime"]) / 3600, "field value"),
                    leadTimeSum=escape_telegraf_str(sum(times["leadTime"]) / 3600, "field value"),
                    cycleTimeSum=escape_telegraf_str(sum(times["cycleTime"]) / 3600, "field value"),
                )
            else:
                measure = "slo"
                extra = ""
            output.append(
                '{measure},team="{team}",status="{status}",title="{title}" count={count}{extra}'.format(
                    measure=escape_telegraf_str(measure, "measurement"),
                    team=escape_telegraf_str(data["team"], "tag value"),
                    status=escape_telegraf_str(status, "tag value"),
                    title=escape_telegraf_str(conf["title"], "tag value"),
                    count=escape_telegraf_str(count, "field value"),
                    extra=extra,
                )
            )
            if status == "Resolved":
                output[-1] += " " + str(_today_nanoseconds())
    return output

def escape_telegraf_str(value_to_escape, element):
    # See https://docs.influxdata.com/influxdb/cloud/reference/syntax/line-protocol/#special-characters for escaping rules and where they apply
    escaped_str = str(value_to_escape) #especially for field values it can happen that we get an int
    if (element == "field value"): #field values are the only thing where unique rules apply
        escaped_str = escaped_str.replace("\\", "\\\\")
        escaped_str = escaped_str.replace("\"", "\\\"")
        return escaped_str

    # common rules applicable to everything else
    escaped_str = escaped_str.replace(",", "\\,")
    escaped_str = escaped_str.replace(" ", "\\ ")
    if (element != "measurement"):
        escaped_str = escaped_str.replace("=", "\\=")
    return escaped_str

def get_state():
    if os.environ.get('STATE_FOLDER'):
        old_state_file = os.path.join(os.environ['STATE_FOLDER'], "state.json")
        if os.path.exists(old_state_file):
            # open state.json from last run, see if anything changed and send slack notification if needed
            with open(old_state_file, "r") as sj:
                return json.load(sj)

def update_state(bad_queries):
    with open("state.json", "w") as sj:
        state = {
            "bad_queries": bad_queries,
            "updated": datetime.now().isoformat()
        }
        json.dump(state, sj)

def trigger_webhook(state, bad_queries):
    if state:
        old_bad_queries = set(state["bad_queries"].keys())
        new_bad_queries = set(bad_queries.keys())
        fixed_queries = old_bad_queries - new_bad_queries
        broken_queries = new_bad_queries - old_bad_queries
        msg = None
        if broken_queries:
            # something new broke
            msg = f":red_circle: Some queries are exceeding limits:"
            for query in new_bad_queries:
                qd = bad_queries[query]
                msg += f"\n• {query} (Issue count {qd['issue_count']} exceeding limit of [{qd['limits']}])"
        elif fixed_queries and not new_bad_queries:
            # this is the first green run so let's let everyone know
            msg = f":green_heart: All queries within limits again!"
        if msg and os.environ.get('WEBHOOK_URL'):
            r = requests.post(os.environ['WEBHOOK_URL'], json={"msg": msg})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", default="queries.yaml", nargs="?")
    parser.add_argument(
        "--output", choices=["markdown", "influxdb"], default="markdown"
    )
    parser.add_argument("--reminder-comment-on-issues", action="store_true")
    parser.add_argument("--exit-code", action="store_true")
    switches = parser.parse_args()
    try:
        all_good = True
        with open(switches.config, "r") as config:
            data = yaml.safe_load(config)
            data["reminder-comment-on-issues"] = switches.reminder_comment_on_issues
            if switches.output == "influxdb":
                print("\n".join(line for line in render_influxdb(data)))
            else:
                initialize_md(data)
                all_good, rows, bad_queries = render_table(data)
                with open("index.md", "a") as md:
                    for row in rows:
                        md.write("|".join(row) + "\n")
                # open state.json from last run, see if anything changed and send webhook notification if needed
                state = get_state()
                trigger_webhook(state, bad_queries)
                update_state(bad_queries)
    except FileNotFoundError:
        sys.exit("Configuration file {} not found".format(switches.config))
    if switches.exit_code and not all_good:
        sys.exit(3)
