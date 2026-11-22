#!/usr/bin/env python3
import os
import re
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


def make_reminder_data(api=False):
    data = {
        "url": "https://example.com/issues",
        "web": "https://example.com/wiki",
        "reminder-comment-on-issues": True,
    }
    if api:
        data["api"] = "https://example.com/issues.json"
    return data


def make_reminder_conf():
    return {
        "title": "Workable Backlog",
        "query": "query_id=123&c%5B%5D=updated_on",
        "max": 5,
    }


def make_reminder_state():
    return {
        "has_repeat_reminder": False,
        "last_reminder": datetime.min.replace(tzinfo=UTC).replace(tzinfo=None),
    }


def make_reminder_journal(created_on):
    return {
        "notes": "This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.",
        "created_on": created_on,
    }


class TestComments(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def capsys(self, capsys):
        self.capsys = capsys

    def setUp(self):
        patcher = patch.object(backlogger, "data", make_reminder_data(api=True))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_comments(self):
        rest = {
            "issue": {
                "id": 1000,
                "priority": {"id": 6, "name": "Urgent"},
                "journals": [
                    {"id": 1, "notes": ""},
                ],
            },
        }
        mock_json_rest = MagicMock(return_value=rest)
        with patch("backlogger.json_rest", mock_json_rest):
            backlogger.list_issues(
                {"query": "query_id=123&c%5B%5D=updated_on"},
                {
                    "issues": [{"priority": {"name": "High"}, "id": 123}],
                    "total_count": 1,
                },
            )
            backlogger.list_issues(
                {"query": "query_id=123&"},
                {
                    "issues": [{"priority": {"name": "High"}, "id": 456}],
                    "total_count": 1,
                },
            )
            calls = [
                call(
                    "GET",
                    "https://example.com/wiki/123.json?include=journals",
                ),
                call(
                    "PUT",
                    "https://example.com/wiki/123.json",
                    {
                        "issue": {
                            "notes": "This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority."
                        }
                    },
                ),
            ]
            mock_json_rest.assert_has_calls(calls)

    def test_no_repeat(self):
        rest = {
            "issue": {
                "id": 1000,
                "priority": {"id": 6, "name": "Urgent"},
                "journals": [
                    {"id": 1, "notes": ""},
                    {"id": 2, "notes": None},
                    {
                        "id": 3,
                        "notes": "This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.",
                        "created_on": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                ],
            },
        }

        mock_json_rest = MagicMock(return_value=rest)
        with patch("backlogger.json_rest", mock_json_rest):
            backlogger.issue_reminder(
                {"query": "query_id=123&c%5B%5D=updated_on"},
                {"priority": {"name": "High"}, "id": 1000},
                {
                    "has_repeat_reminder": datetime.min.replace(tzinfo=UTC).replace(
                        tzinfo=None
                    ),
                    "last_reminder": False,
                },
            )
            mock_json_rest.assert_called_once_with(
                "GET",
                "https://example.com/wiki/1000.json?include=journals",
            )
        out, _ = self.capsys.readouterr()
        assert out == "Skipping reminder for 1000: a similar reminder already exists\n"

    def test_empty_issue(self):
        mock_json_rest = MagicMock(return_value=None)
        with patch("backlogger.json_rest", mock_json_rest):
            backlogger.issue_reminder(
                {"query": "query_id=123&c%5B%5D=updated_on"},
                {"priority": {"name": "High"}, "id": 1000},
                {
                    "has_repeat_reminder": datetime.min.replace(tzinfo=UTC).replace(
                        tzinfo=None
                    ),
                    "last_reminder": False,
                },
            )
            mock_json_rest.assert_called_once_with(
                "GET",
                "https://example.com/wiki/1000.json?include=journals",
            )
        _, err = self.capsys.readouterr()
        assert re.match("API for 1000 returned None", err)

    def test_automatic_priority_on_issue(self):
        test_params = [
            {
                "desc": "Immediate",
                "prio_from": "Immediate",
                "prio_to": "Urgent",
                "past_days": 2,
                "prio_id_to": 6,
            },
            {
                "desc": "Urgent",
                "prio_from": "Urgent",
                "prio_to": "High",
                "past_days": 25,
                "prio_id_to": 5,
            },
            {
                "desc": "High",
                "prio_from": "High",
                "prio_to": "Normal",
                "past_days": 35,
                "prio_id_to": 4,
            },
            {
                "desc": "Normal",
                "prio_from": "Normal",
                "prio_to": "Low",
                "past_days": 700,
                "prio_id_to": 3,
            },
        ]
        expected_str = "Reducing priority from {} to next lower {} for 1000"
        for params in test_params:
            prio_from = params["prio_from"]
            prio_to = params["prio_to"]
            prio_id_to = params["prio_id_to"]
            with self.subTest(params["desc"]):
                mock_json_rest = self._test_issue_reminder(
                    prio_from=prio_from, past_days=params["past_days"]
                )
                out, _ = self.capsys.readouterr()
                assert re.search(expected_str.format(prio_from, prio_to), out)
            calls = [
                call(
                    "GET",
                    "https://example.com/wiki/1000.json?include=journals",
                ),
                call(
                    "PUT",
                    "https://example.com/wiki/1000.json",
                    {
                        "issue": {
                            "priority_id": prio_id_to,
                            "notes": f"This ticket was set to **{prio_from}** priority but was not updated [within the SLO period](https://example.com/issues). The ticket will be set to the next lower priority **{prio_to}**.",
                        }
                    },
                ),
            ]
            mock_json_rest.assert_has_calls(calls)

    def test_issue_with_low_priority_never_change(self):
        test_params = [
            {"desc": "Low priority, 2 days", "prio_from": "Low", "past_days": 2},
            {"desc": "Low priority, 1000 days", "prio_from": "Low", "past_days": 1000},
        ]
        for params in test_params:
            with self.subTest(params["desc"]):
                mock_json_rest = self._test_issue_reminder(
                    prio_from=params["prio_from"], past_days=params["past_days"]
                )
                out, _ = self.capsys.readouterr()
                assert re.search("Skipping priority update for 1000", out)
            calls = [
                call(
                    "GET",
                    "https://example.com/wiki/1000.json?include=journals",
                ),
            ]
            mock_json_rest.assert_has_calls(calls)

    def _test_issue_reminder(self, prio_from, past_days):
        rest = {
            "issue": {
                "id": 1000,
                "journals": [
                    {"id": 1, "notes": ""},
                    {"id": 2, "notes": None},
                    {
                        "id": 3,
                        "notes": "This ticket was set to **Urgent** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.",
                        "created_on": (
                            datetime.now(UTC) - timedelta(days=past_days)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                ],
            },
        }

        mock_json_rest = MagicMock(return_value=rest)
        with patch("backlogger.json_rest", mock_json_rest):
            backlogger.issue_reminder(
                {"query": "query_id=123&c%5B%5D=updated_on"},
                {"priority": {"name": prio_from}, "id": 1000},
                {
                    "has_repeat_reminder": datetime.min.replace(tzinfo=UTC).replace(
                        tzinfo=None
                    ),
                    "last_reminder": False,
                },
            )
        return mock_json_rest
