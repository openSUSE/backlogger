#!/usr/bin/env python3
import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest
import requests

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
        self.assertEqual(
            out, "Skipping reminder for 1000: a similar reminder already exists\n"
        )

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
        self.assertRegex(err, "^API for 1000 returned None")

    def test_configured_comment_overrides_default_reminder_text(self):
        mock_json_rest = MagicMock(return_value={"issue": {"journals": []}})
        with (
            patch.object(backlogger, "data", make_reminder_data()),
            patch("backlogger.json_rest", mock_json_rest),
        ):
            backlogger.issue_reminder(
                {**make_reminder_conf(), "comment": "Custom reminder"},
                {"priority": {"name": "High"}, "id": 1000},
                make_reminder_state(),
            )
        mock_json_rest.assert_called_with(
            "PUT",
            "https://example.com/wiki/1000.json",
            {"issue": {"notes": "Custom reminder"}},
        )

    def test_disabled_reminders_skip_journal_requests(self):
        mock_json_rest = MagicMock()
        with (
            patch.object(
                backlogger,
                "data",
                {**make_reminder_data(), "reminder-comment-on-issues": False},
            ),
            patch("backlogger.json_rest", mock_json_rest),
        ):
            backlogger.issue_reminder(
                make_reminder_conf(),
                {"priority": {"name": "High"}, "id": 1000},
                make_reminder_state(),
            )
        mock_json_rest.assert_not_called()

    def test_non_dict_issue_is_logged_with_unknown_id(self):
        with (
            patch.object(backlogger, "data", make_reminder_data()),
            patch("backlogger.json_rest", MagicMock()),
        ):
            backlogger.issue_reminder(
                make_reminder_conf(), "1000", make_reminder_state()
            )
        _, err = self.capsys.readouterr()
        self.assertTrue(err.startswith("Reminder for ? failed:"))
        self.assertTrue(err.endswith("\n"))

    def test_reminder_failure_is_logged(self):
        cases = [
            {
                "desc": "journal fetch failure is logged",
                "poo": {"priority": {"name": "High"}, "id": 1000},
                "side_effect": requests.ConnectionError("journal fetch failed"),
                "expected_contains": "ConnectionError",
                "writes": False,
            },
            {
                "desc": "journal fetch timeout omits url",
                "poo": {"priority": {"name": "High"}, "id": 1000},
                "side_effect": requests.ReadTimeout(
                    "https://example.com/wiki/1000.json"
                ),
                "expected_contains": "ReadTimeout",
                "writes": False,
            },
            {
                "desc": "issue without priority is logged",
                "poo": {"id": 1000},
                "side_effect": None,
                "expected_contains": "'priority'",
                "writes": False,
            },
            {
                "desc": "malformed journals list is logged",
                "poo": {"priority": {"name": "High"}, "id": 1000},
                "side_effect": lambda method, url: {
                    "issue": {"journals": "not-a-list"}
                },
                "expected_contains": "'str' object has no attribute 'get'",
                "writes": False,
            },
            {
                "desc": "non-iterable journals value is logged",
                "poo": {"priority": {"name": "High"}, "id": 1000},
                "side_effect": lambda method, url: {"issue": {"journals": 5}},
                "expected_contains": "'int' object is not iterable",
                "writes": False,
            },
            {
                "desc": "reminder write failure is logged",
                "poo": {"priority": {"name": "High"}, "id": 1000},
                "side_effect": [
                    {"issue": {"journals": []}},
                    requests.ConnectionError("reminder write failed"),
                ],
                "expected_contains": "ConnectionError",
                "writes": True,
            },
        ]
        for case in cases:
            with self.subTest(case["desc"]):
                mock_json_rest = MagicMock(side_effect=case["side_effect"])
                with (
                    patch.object(backlogger, "data", make_reminder_data()),
                    patch("backlogger.json_rest", mock_json_rest),
                ):
                    backlogger.issue_reminder(
                        make_reminder_conf(),
                        case["poo"],
                        make_reminder_state(),
                    )
                out, err = self.capsys.readouterr()
                self.assertEqual("Writing reminder for 1000" in out, case["writes"])
                self.assertTrue(err.startswith("Reminder for 1000 failed:"))
                self.assertIn(case["expected_contains"], err)
                self.assertNotIn("https://example.com", err)
                self.assertTrue(err.endswith("\n"))

    def test_reminder_failure_keeps_query_row(self):
        mock_json_rest = MagicMock(
            side_effect=[
                {
                    "issues": [{"priority": {"name": "High"}, "id": 1000}],
                    "total_count": 1,
                },
                {"issue": {"journals": []}},
                requests.ConnectionError("reminder write failed"),
            ]
        )
        with (
            patch.object(backlogger, "data", make_reminder_data(api=True)),
            patch("backlogger.json_rest", mock_json_rest),
        ):
            good, issue_count, details_md, query_error = backlogger.check_backlog(
                make_reminder_conf()
            )
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Reminder for 1000 failed: ConnectionError\n")
        self.assertTrue(good)
        self.assertEqual(issue_count, 1)
        self.assertIsNone(details_md)
        self.assertIsNone(query_error)

    def test_reminder_failure_stops_loop_for_subsequent_issues(self):
        root = {
            "issues": [
                {"priority": {"name": "High"}, "id": 1001},
                {"priority": {"name": "High"}, "id": 1002},
            ],
            "total_count": 2,
        }
        mock_json_rest = MagicMock(side_effect=requests.ConnectionError("network down"))
        with patch("backlogger.json_rest", mock_json_rest):
            count = backlogger.list_issues(make_reminder_conf(), root)
        self.assertEqual(count, 2)
        mock_json_rest.assert_called_once_with(
            "GET", "https://example.com/wiki/1001.json?include=journals"
        )
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Reminder for 1001 failed: ConnectionError\n")

    def test_data_error_continues_loop_for_subsequent_issues(self):
        root = {
            "issues": [
                {"id": 1001},
                {"priority": {"name": "High"}, "id": 1002},
            ],
            "total_count": 2,
        }
        mock_json_rest = MagicMock(return_value={"issue": {"journals": []}})
        with patch("backlogger.json_rest", mock_json_rest):
            count = backlogger.list_issues(make_reminder_conf(), root)
        self.assertEqual(count, 2)
        mock_json_rest.assert_called_with(
            "PUT",
            "https://example.com/wiki/1002.json",
            {
                "issue": {
                    "notes": "This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority."
                }
            },
        )
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Reminder for 1001 failed: 'priority'\n")

    def test_non_json_journal_response_continues_loop_for_subsequent_issues(self):
        root = {
            "issues": [
                {"priority": {"name": "High"}, "id": 1001},
                {"priority": {"name": "High"}, "id": 1002},
            ],
            "total_count": 2,
        }
        mock_json_rest = MagicMock(
            side_effect=[
                requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0),
                {"issue": {"journals": []}},
                None,
            ]
        )
        with patch("backlogger.json_rest", mock_json_rest):
            count = backlogger.list_issues(make_reminder_conf(), root)
        self.assertEqual(count, 2)
        self.assertEqual(mock_json_rest.call_count, 3)
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Reminder for 1001 failed: JSONDecodeError\n")

    def test_is_transport_error_classifier(self):
        cases = [
            (
                "connection error is transport",
                requests.ConnectionError("offline"),
                True,
            ),
            ("timeout is transport", requests.ReadTimeout("timed out"), True),
            (
                "retry error is transport",
                requests.exceptions.RetryError("exhausted"),
                True,
            ),
            (
                "http error is not transport",
                requests.HTTPError("404 Not Found"),
                False,
            ),
            ("key error is not transport", KeyError("missing"), False),
        ]
        for desc, err, expected in cases:
            with self.subTest(desc):
                self.assertEqual(backlogger.is_transport_error(err), expected)

    def test_malformed_journal_keeps_query_row(self):
        journal = make_reminder_journal("not-a-date")
        mock_json_rest = MagicMock(
            side_effect=[
                {
                    "issues": [{"priority": {"name": "High"}, "id": 1000}],
                    "total_count": 1,
                },
                {"issue": {"journals": [journal]}},
            ]
        )
        with (
            patch.object(backlogger, "data", make_reminder_data(api=True)),
            patch("backlogger.json_rest", mock_json_rest),
        ):
            good, issue_count, details_md, query_error = backlogger.check_backlog(
                make_reminder_conf()
            )
        _, err = self.capsys.readouterr()
        self.assertIn("Reminder for 1000 failed: Invalid isoformat string", err)
        self.assertTrue(good)
        self.assertEqual(issue_count, 1)
        self.assertIsNone(details_md)
        self.assertIsNone(query_error)

    def test_priority_update_failure_is_logged(self):
        created_on = (datetime.now(UTC) - timedelta(days=40)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_json_rest = MagicMock(
            side_effect=[
                {"issue": {"journals": [make_reminder_journal(created_on)]}},
                requests.ConnectionError("priority update failed"),
            ]
        )
        with (
            patch.object(backlogger, "data", make_reminder_data()),
            patch("backlogger.json_rest", mock_json_rest),
        ):
            backlogger.issue_reminder(
                make_reminder_conf(),
                {"priority": {"name": "High"}, "id": 1000},
                make_reminder_state(),
            )
        out, err = self.capsys.readouterr()
        self.assertIn("Reducing priority from High to next lower Normal for 1000", out)
        self.assertEqual(err, "Reminder for 1000 failed: ConnectionError\n")

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
                self.assertRegex(out, expected_str.format(prio_from, prio_to))
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
                self.assertRegex(out, "Skipping priority update for 1000")
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
