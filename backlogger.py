#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime, timedelta
from inspect import getmembers, isfunction
import requests
import yaml


# Icons used for PASS or FAIL in the md file
result_icons = {"pass": "&#x1F49A;", "fail": "&#x1F534;"}

# Initialize a blank md file to replace the current README
def initialize_md(data):
    with open('index.md', 'w') as md:
        md.write("# Backlog Status\n\n")
        md.write("This is the dashboard for [{}]({}).\n".format(data['team'], data['url']))
        md.write("**Latest Run:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " UTC\n")
        md.write("*(Please refresh to see latest results)*\n\n")
        md.write("Backlog Query | Number of Issues | Limits | Status\n--- | --- | --- | ---\n")


def get_link(conf):
    return data['web'] + '?' + conf['query']


# Append individual results to md file
def results_to_md(conf, number, status):
    mdlink = '[' + conf['title'] + '](' + get_link(conf) + ')'
    lessthan = conf['max'] + 1
    limits = '<' + str(lessthan)
    if 'min' in conf:
        limits += ', >' + str(conf['min'] - 1)
    with open('index.md', 'a') as md:
        md.write(mdlink + " | " + str(number) + " | " + limits + " | " + status + "\n")


def json_rest(method, url, rest=None):
    text = json.dumps(rest)
    try:
        key = os.environ['REDMINE_API_KEY']
    except KeyError:
        exit('REDMINE_API_KEY is required to be set')
    headers = {
      'User-Agent': 'backlogger ({})'.format(data['url']),
      'Content-Type': 'application/json',
      'X-Redmine-API-Key': key,
    }
    r = requests.request(method, url, data=text, headers=headers)
    r.raise_for_status()
    return r.json() if r.text else None


def issue_reminder(poo):
    priority = poo['priority']['name']
    msg = 'This ticket was set to **{priority}** priority but was not updated [within the SLO period]({url}). Please consider picking up this ticket or just set the ticket to the next lower priority.'.format(priority=priority, url=data['url'])
    print(msg)
    if '--reminder-comment-on-issues' in sys.argv:
        url = '{}/{}.json'.format(data['web'], poo['id'])
        json_rest('PUT', url, {'issue': {'notes': msg}})


def list_issues(conf, root):
    try:
        for poo in root['issues']:
            print(data['web'] + '/' + str(poo['id']))
            if 'updated_on' in conf['query']:
                issue_reminder(poo)
    except KeyError:
        print("There was an error retrieving the issues " + conf['title'])
    else:
        issue_count = int(root["total_count"])
        if issue_count > len(root['issues']):
            print("there are more issues, check " + get_link(conf))


def failure_more(conf):
    print(conf['title'] + " has more than " + str(conf['max']) + " tickets!")
    return False


def failure_less(conf):
    print(conf['title'] + " has less than " + str(conf['min']) + " tickets!")
    return False


def check_backlog(conf):
    root = json_rest('GET', data['api'] + '?' + conf['query'])
    list_issues(conf, root)
    issue_count = int(root["total_count"])
    if issue_count > conf['max']:
        res = failure_more(conf)
    elif 'min' in conf and issue_count < conf['min']:
        res = failure_less(conf)
    else:
        res = True
        print(conf['title'] + " length is " + str(issue_count) + ", all good!")
    if not res:
        print("Please check " + get_link(conf))
    return (res, issue_count)


def check_query(name):
    for conf in data['queries']:
        res = check_backlog(conf)
        results_to_md(conf, res[1], result_icons["pass"] if res[0] else result_icons["fail"])

if __name__ == '__main__':
    filename = sys.argv[1] if len(sys.argv) > 1 else 'queries.yaml'
    try:
        with open(filename, 'r') as config:
            data = yaml.safe_load(config)
            initialize_md(data)
            check_query(data)
    except FileNotFoundError:
        sys.exit('Configuration file {} not found'.format(filename))
