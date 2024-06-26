import os
import sys
import unittest
import pytest
import re
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


class TestComments(unittest.TestCase):

    @pytest.fixture(autouse=True)
    def capsys(self, capsys):
        self.capsys = capsys


    def test_comments(self):
        data = {"url": "https://example.com/issues", "web": "https://example.com/wiki",
                "reminder-comment-on-issues": True}
        backlogger.data = data
        rest = {
            "issue": {
                "id": 1000,
                "priority": { "id": 6, "name": "Urgent" },
                "journals": [
                    { "id": 1, "notes": "" },
                ],
            },
        }
        backlogger.json_rest = MagicMock(return_value=rest)
        backlogger.list_issues(
            {"query": "query_id=123&c%5B%5D=updated_on"},
            {"issues": [{"priority": {"name": "High"}, "id": 123}], "total_count": 1},
        )
        backlogger.list_issues(
            {"query": "query_id=123&"},
            {"issues": [{"priority": {"name": "High"}, "id": 456}], "total_count": 1},
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
        backlogger.json_rest.assert_has_calls(calls)


    def test_no_repeat(self):
        data = {"url": "https://example.com/issues", "web": "https://example.com/wiki",
                "api": "https://example.com/issues.json",
                "reminder-comment-on-issues": True}
        backlogger.data = data
        rest = {
            "issue": {
                "id": 1000,
                "priority": { "id": 6, "name": "Urgent" },
                "journals": [
                    { "id": 1, "notes": "" },
                    { "id": 2, "notes": None },
                    {
                        "id": 3,
                        "notes": "This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.",
                        "created_on": datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
                    },
                ],
            },
        }

        backlogger.json_rest = MagicMock(return_value=rest)
        backlogger.issue_reminder(
            {"query": "query_id=123&c%5B%5D=updated_on"},
            {"priority": {"name": "High"}, "id": 1000},
            {'has_repeat_reminder': datetime.min, 'last_reminder': False}
        )
        backlogger.json_rest.assert_called_once_with(
            "GET",
            "https://example.com/wiki/1000.json?include=journals",
        )
        out, err = self.capsys.readouterr()
        assert re.match("Skipping reminder for 1000", out)


    def test_empty_issue(self):
        backlogger.json_rest = MagicMock(return_value=None)
        backlogger.issue_reminder(
            {"query": "query_id=123&c%5B%5D=updated_on"},
            {"priority": {"name": "High"}, "id": 1000},
            {'has_repeat_reminder': datetime.min, 'last_reminder': False}
        )
        backlogger.json_rest.assert_called_once_with(
            "GET",
            "https://example.com/wiki/1000.json?include=journals",
        )
        out, err = self.capsys.readouterr()
        assert re.match("API for 1000 returned None", err)


    def test_automatic_priority_on_issue(self):
        test_params = [
            # prio_from, prio_to, past_days, prio_id_to
            ["Immediate", "Urgent", 2, 6],
            ["Urgent", "High", 25, 5],
            ["High", "Normal", 35, 4],
            ["Normal", "Low", 700, 3]]
        expected_str = "Reducing priority from {} to next lower {} for 1000"
        for params in test_params:
            prio_from = params[0]
            prio_to = params[1]
            prio_id_to = params[3]
            with self.subTest(params):
                self._test_issue_reminder(prio_from=params[0], past_days=params[2])
                out, err = self.capsys.readouterr()
                assert re.search(expected_str.format(prio_from,
                                                     prio_to), out)
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
                            "notes": "This ticket was set to **{}** priority but was not updated [within the SLO period](https://example.com/issues). The ticket will be set to the next lower priority **{}**.".format(prio_from, prio_to)
                        }
                    },
                ),
            ]
            backlogger.json_rest.assert_has_calls(calls)


    def test_issue_with_low_priority_never_change(self):
        test_params = [
            # prio_from, past_days
            ["Low", 2],
            ["Low", 1000]]
        for params in test_params:
            with self.subTest(params):
                self._test_issue_reminder(prio_from=params[0], past_days=params[1])
                out, err = self.capsys.readouterr()
                assert re.search("Skipping priority update for 1000", out)
            calls = [
                call(
                    "GET",
                    "https://example.com/wiki/1000.json?include=journals",
                ),
            ]
            backlogger.json_rest.assert_has_calls(calls)


    def _test_issue_reminder(self, prio_from, past_days):
        data = {"url": "https://example.com/issues", "web": "https://example.com/wiki",
                "api": "https://example.com/issues.json",
                "reminder-comment-on-issues": True}
        backlogger.data = data
        rest = {
            "issue": {
                "id": 1000,
                "journals": [
                    { "id": 1, "notes": "" },
                    { "id": 2, "notes": None },
                    {
                        "id": 3,
                        "notes": "This ticket was set to **Urgent** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.",
                        "created_on": (datetime.now() - timedelta(days=past_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
                    },
                ],
            },
        }

        backlogger.json_rest = MagicMock(return_value=rest)
        backlogger.issue_reminder(
            {"query": "query_id=123&c%5B%5D=updated_on"},
            {"priority": {"name": prio_from}, "id": 1000},
            {'has_repeat_reminder': datetime.min, 'last_reminder': False}
        )
