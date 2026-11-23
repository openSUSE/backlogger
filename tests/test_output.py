import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger
import entrypoint

DEFAULT_WEBHOOK_URL = "https://example.com/hook"


def make_backlog_data(queries):
    return {
        "api": "https://example.com/issues.json",
        "web": "https://example.com/issues",
        "team": "Awesome Team",
        "queries": queries,
    }


class TestOutput(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def capsys(self, capsys):
        self.capsys = capsys

    def setUp(self):
        data = make_backlog_data(
            [{"title": "Workable Backlog", "query": "query_id=123"}]
        )
        patcher = patch.object(backlogger, "data", data)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch.object(backlogger, "_today_nanoseconds", return_value=23)
    @patch("backlogger.json_rest")
    def test_influxdb(self, mock_json_rest, mock_today):
        mock_json_rest.side_effect = [
            {
                "issue_statuses": [
                    {"name": "In Progress", "id": 2},
                    {"name": "Feedback", "id": 4},
                ]
            },
            {
                "issues": [
                    {
                        "id": 1,
                        "status": {"name": "In Progress"},
                        "created_on": "2022-12-12T07:51:24Z",
                        "updated_on": "2022-12-19T12:34:52Z",
                    },
                    {
                        "id": 2,
                        "status": {"name": "In Progress"},
                        "created_on": "2022-12-06T21:32:03Z",
                        "updated_on": "2022-12-09T13:19:29Z",
                    },
                    {
                        "id": 3,
                        "status": {"name": "Feedback"},
                        "created_on": "2022-12-06T00:00:00Z",
                        "updated_on": "2022-12-14T00:00:00Z",
                    },
                    {
                        "id": 4,
                        "status": {"name": "Resolved"},
                        "created_on": "2022-12-06T13:57:05Z",
                        "updated_on": "2022-12-22T13:12:22Z",
                    },
                    {
                        "id": 5,
                        "status": {"name": "Resolved"},
                        "created_on": "2022-12-08T10:00:00Z",
                        "updated_on": "2022-12-15T10:00:00Z",
                    },
                ],
                "total_count": 5,
            },
            {
                "issue": {
                    "journals": [
                        {
                            "details": [{"name": "status_id", "new_value": "2"}],
                            "created_on": "2022-12-10T13:57:05Z",
                        },
                        {
                            "details": [
                                {
                                    "name": "status_id",
                                    "old_value": "2",
                                    "new_value": "3",
                                }
                            ],
                            "created_on": "2022-12-12T13:57:05Z",
                        },
                    ]
                }
            },
            {
                "issue": {
                    "journals": [
                        {
                            "details": [{"name": "status_id", "new_value": "2"}],
                            "created_on": "2022-12-10T10:00:00Z",
                        },
                        {
                            "details": [
                                {
                                    "name": "status_id",
                                    "old_value": "2",
                                    "new_value": "3",
                                }
                            ],
                            "created_on": "2022-12-12T10:00:00Z",
                        },
                    ]
                }
            },
        ]
        self.assertEqual(
            backlogger.render_influxdb(backlogger.data),
            [
                'slo,team="Awesome\\ Team",status="In\\ Progress",title="Workable\\ Backlog" count=2',
                'slo,team="Awesome\\ Team",status="Feedback",title="Workable\\ Backlog" count=1',
                'leadTime,team="Awesome\\ Team",status="Resolved",title="Workable\\ Backlog" count=2,leadTime=275.6273611111111,cycleTime=48.0,leadTimeSum=551.2547222222222,cycleTimeSum=96.0 23',
            ],
        )

    def test_markdown(self):
        scenarios = [
            {
                "desc": "no limits always pass",
                "count": 2,
                "limit": "",
                "data": {},
                "icon": "&#x1F49A;",
            },
            {
                "desc": "count above max fails",
                "count": 2,
                "limit": "<2",
                "data": {"max": 1},
                "icon": "&#x1F534;",
            },
            {
                "desc": "count equal to max passes",
                "count": 1,
                "limit": "<2",
                "data": {"max": 1},
                "icon": "&#x1F49A;",
            },
            {
                "desc": "count equal to min passes",
                "count": 1,
                "limit": "<5, >0",
                "data": {"min": 1, "max": 4},
                "icon": "&#x1F49A;",
            },
            {
                "desc": "count below min fails",
                "count": 0,
                "limit": "<5, >0",
                "data": {"min": 1, "max": 4},
                "icon": "&#x1F534;",
            },
            {
                "desc": "min-only query below min fails",
                "count": 0,
                "limit": ", >0",
                "data": {"min": 1},
                "icon": "&#x1F534;",
            },
            {
                "desc": "count below min 3 fails",
                "count": 2,
                "limit": "<5, >2",
                "data": {"min": 3, "max": 4},
                "icon": "&#x1F534;",
            },
        ]
        for scenario in scenarios:
            with self.subTest(scenario["desc"]):
                query = {"title": "Workable Backlog", "query": "query_id=123"}
                query.update(scenario["data"])
                test_data = make_backlog_data([query])
                with (
                    patch.object(backlogger, "data", test_data),
                    patch(
                        "backlogger.json_rest",
                        return_value={"issues": [], "total_count": scenario["count"]},
                    ),
                ):
                    self.assertEqual(
                        backlogger.render_table(backlogger.data)[1],
                        [
                            [
                                "[Workable Backlog](https://example.com/issues?query_id=123)",
                                str(scenario["count"]),
                                scenario["limit"],
                                scenario["icon"],
                            ],
                        ],
                    )

    @patch("backlogger.fetch_github_prs")
    def test_github_backlog(self, mock_fetch):
        now = datetime.now(UTC).replace(tzinfo=None)
        stale_date = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh_date = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_fetch.return_value = [
            {
                "html_url": "https://github.com/os-autoinst/openQA/pull/1",
                "updated_at": stale_date,
                "created_at": stale_date,
            },
            {
                "html_url": "https://github.com/os-autoinst/openQA/pull/2",
                "updated_at": fresh_date,
                "created_at": fresh_date,
            },
            {
                "html_url": "https://github.com/os-autoinst/os-autoinst/pull/3",
                "updated_at": stale_date,
                "created_at": stale_date,
            },
        ]

        conf = {
            "title": "Stale PRs",
            "type": "github",
            "repos": ["os-autoinst/openQA", "os-autoinst/os-autoinst"],
            "stale_days": 7,
            "max": 1,
        }

        good, issue_count, details_md, _ = backlogger.check_github_backlog(conf)
        self.assertFalse(good)
        self.assertEqual(issue_count, 2)
        self.assertIn("Show breakdown for: Stale PRs", details_md)
        self.assertIn("os-autoinst/openQA", details_md)
        self.assertIn("os-autoinst/os-autoinst", details_md)
        self.assertIn("10 days ago", details_md)
        self.assertIn("<strong>1</strong> 🔴", details_md)
        self.assertIn("<table>", details_md)
        self.assertIn("<td>", details_md)
        self.assertNotIn("| --- |", details_md)

    def _stale_prs_conf(self, **kwargs):
        conf = {
            "title": "Stale PRs",
            "type": "github",
            "repos": ["os-autoinst/openQA"],
            "stale_days": 7,
            "max": 1,
        }
        conf.update(kwargs)
        return conf

    @patch("backlogger.fetch_github_prs")
    def test_github_fetch_failure_is_reported(self, mock_fetch):
        mock_fetch.side_effect = requests.ConnectionError("github timeout")
        conf = self._stale_prs_conf()
        good, issue_count, details_md, query_error = backlogger.check_backlog(conf)
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Error querying backlog Stale PRs: ConnectionError\n")
        self.assertFalse(good)
        self.assertIsNone(issue_count)
        self.assertIn("Error querying backlog Stale PRs", details_md)
        self.assertEqual(query_error, "ConnectionError")

    @patch("backlogger.fetch_github_prs")
    def test_github_row_parse_failure_is_reported(self, mock_fetch):
        cases = [
            {
                "desc": "missing html_url is reported",
                "item": {"updated_at": "2026-01-01T00:00:00Z"},
                "expected_key": "'html_url'",
            },
            {
                "desc": "missing updated_at is reported",
                "item": {
                    "html_url": "https://github.com/os-autoinst/openQA/pull/1",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                "expected_key": "'updated_at'",
            },
            {
                "desc": "null html_url is reported",
                "item": {"html_url": None, "updated_at": "2026-01-01T00:00:00Z"},
                "expected_key": "'NoneType' object has no attribute 'split'",
            },
        ]
        conf = self._stale_prs_conf()
        for case in cases:
            with self.subTest(case["desc"]):
                mock_fetch.return_value = [case["item"]]
                good, issue_count, details_md, query_error = backlogger.check_backlog(
                    conf
                )
                _, err = self.capsys.readouterr()
                self.assertEqual(
                    err, f"Error querying backlog Stale PRs: {case['expected_key']}\n"
                )
                self.assertFalse(good)
                self.assertIsNone(issue_count)
                self.assertIn("Error querying backlog Stale PRs", details_md)
                self.assertEqual(query_error, case["expected_key"])

    @patch("backlogger.fetch_github_prs")
    def test_github_render_table(self, mock_fetch):
        now = datetime.now(UTC).replace(tzinfo=None)
        stale_date = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_fetch.return_value = [
            {
                "html_url": "https://github.com/os-autoinst/openQA/pull/1",
                "updated_at": stale_date,
                "created_at": stale_date,
            }
        ]

        data = make_backlog_data([self._stale_prs_conf(max=0)])
        all_good, rows, _, details_md_blocks = backlogger.render_table(data)

        self.assertFalse(all_good)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "1")
        self.assertEqual(rows[0][3], "&#x1F534;")
        self.assertEqual(len(details_md_blocks), 1)
        self.assertIn("Show breakdown for: Stale PRs", details_md_blocks[0])

    @unittest.skipUnless(
        shutil.which("gs") and shutil.which("magick"),
        "Ghostscript and ImageMagick are required",
    )
    def test_render_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, "index.html")
            png_path = os.path.join(tmpdir, "preview.png")
            with open(html_path, "w") as f:
                f.write("<html><body><h1>Backlog Status</h1></body></html>")
            entrypoint.render_preview(html_path, png_path)
            width, height = (
                int(v)
                for v in subprocess.check_output(
                    ["magick", "identify", "-format", "%wx%h", png_path]
                )
                .decode()
                .split("x")
            )
            self.assertGreater(width, 100)
            self.assertGreater(height, 20)
            self.assertLess(width, 595)
            self.assertLess(height, 842)

    def _broken_queries(self):
        return {
            "Workable Backlog": {
                "url": "https://example.com/issues?query_id=123",
                "issue_count": 2,
                "limits": "<1",
            }
        }

    def _errored_broken(self):
        return {
            "Workable Backlog": {
                **self._broken_queries()["Workable Backlog"],
                "error": "redmine timeout",
            }
        }

    def _failing_query(self):
        return {
            "url": "https://example.com/issues?query_id=2",
            "issue_count": None,
            "limits": "<1",
            "error": "redmine timeout",
        }

    def test_webhook_message(self):
        broken = self._broken_queries()
        cases = [
            {
                "desc": "broken query posts red circle summary",
                "state": {"bad_queries": {}},
                "bad_queries": broken,
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":red_circle: Some queries are exceeding limits:\n• Workable Backlog (Issue count 2 exceeding limit of [<1])",
            },
            {
                "desc": "two broken queries post sorted lines with json content type",
                "state": {"bad_queries": {}},
                "bad_queries": {
                    "Zeta Query": {
                        "url": "https://example.com/issues?query_id=2",
                        "issue_count": 3,
                        "limits": "<2",
                    },
                    "Alpha Query": {
                        "url": "https://example.com/issues?query_id=1",
                        "issue_count": 2,
                        "limits": "<1",
                    },
                },
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":red_circle: Some queries are exceeding limits:\n• Alpha Query (Issue count 2 exceeding limit of [<1])\n• Zeta Query (Issue count 3 exceeding limit of [<2])",
            },
            {
                "desc": "fixed query posts green heart summary",
                "state": {"bad_queries": broken},
                "bad_queries": {},
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":green_heart: All queries within limits again!",
            },
            {
                "desc": "missing webhook URL posts nothing",
                "state": {"bad_queries": {}},
                "bad_queries": broken,
                "webhook_url": None,
                "msg": None,
            },
            {
                "desc": "healthy breach alongside a query failure posts the breach alert",
                "state": {"bad_queries": {}},
                "bad_queries": {
                    **broken,
                    "Failing Query": self._failing_query(),
                },
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":red_circle: Some queries are exceeding limits:\n• Workable Backlog (Issue count 2 exceeding limit of [<1])",
            },
            {
                "desc": "state without bad_queries alerts the first breach",
                "state": {"updated": "2026-01-01T00:00:00+00:00"},
                "bad_queries": broken,
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":red_circle: Some queries are exceeding limits:\n• Workable Backlog (Issue count 2 exceeding limit of [<1])",
            },
            {
                "desc": "recovery during another query's error is not announced",
                "state": {"bad_queries": broken},
                "bad_queries": {"Failing Query": self._failing_query()},
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": None,
            },
            {
                "desc": "healthy run after a query error posts no recovery message",
                "state": {"bad_queries": self._errored_broken()},
                "bad_queries": {},
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": None,
            },
            {
                "desc": "breach re-occurring after a query error is announced",
                "state": {"bad_queries": self._errored_broken()},
                "bad_queries": broken,
                "webhook_url": DEFAULT_WEBHOOK_URL,
                "msg": ":red_circle: Some queries are exceeding limits:\n• Workable Backlog (Issue count 2 exceeding limit of [<1])",
            },
        ]
        for case in cases:
            with self.subTest(case["desc"]):
                env = (
                    {}
                    if case["webhook_url"] is None
                    else {"WEBHOOK_URL": case["webhook_url"]}
                )
                mock_http_request = MagicMock()
                with (
                    patch.dict(os.environ, env, clear=True),
                    patch("backlogger.http_request", mock_http_request),
                ):
                    backlogger.trigger_webhook(case["state"], case["bad_queries"])
                if case["msg"] is None:
                    mock_http_request.assert_not_called()
                else:
                    self.assertEqual(mock_http_request.call_args.args[0], "POST")
                    self.assertEqual(
                        mock_http_request.call_args.args[1], case["webhook_url"]
                    )
                    self.assertEqual(
                        json.loads(mock_http_request.call_args.kwargs["body"]),
                        {"msg": case["msg"]},
                    )
                    self.assertEqual(
                        mock_http_request.call_args.kwargs["headers"],
                        backlogger.JSON_HEADERS,
                    )

    @patch("backlogger.http_request")
    def test_webhook_without_state_posts_nothing(self, mock_http_request):
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}, clear=True):
            backlogger.trigger_webhook(None, self._broken_queries())
        mock_http_request.assert_not_called()

    @patch("backlogger.http_request")
    def test_webhook_connection_failure_is_logged_without_raising(
        self, mock_http_request
    ):
        mock_http_request.side_effect = requests.ConnectionError("webhook unreachable")
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
            backlogger.trigger_webhook({"bad_queries": {}}, self._broken_queries())
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Webhook notification failed: ConnectionError\n")

    @patch("backlogger.http_request")
    def test_webhook_non_2xx_response_is_logged_without_raising(
        self, mock_http_request
    ):
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("400 Client Error")
        mock_http_request.return_value = response
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
            backlogger.trigger_webhook({"bad_queries": {}}, self._broken_queries())
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Webhook notification failed: HTTPError\n")
        mock_http_request.return_value.raise_for_status.assert_called_once()

    @patch("backlogger.http_request")
    def test_webhook_failure_does_not_leak_url_token_to_stderr(self, mock_http_request):
        secret_token = "SECRET_TOKEN_XYZ_123"
        webhook_url = f"https://mattermost.example.com/hooks/{secret_token}"
        mock_http_request.side_effect = requests.ConnectionError(
            f"HTTPSConnectionPool(host='mattermost.example.com', port=443): Max retries exceeded with url: /hooks/{secret_token}"
        )
        with patch.dict(os.environ, {"WEBHOOK_URL": webhook_url}):
            backlogger.trigger_webhook({"bad_queries": {}}, self._broken_queries())
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Webhook notification failed: ConnectionError\n")
        self.assertNotIn(secret_token, err)

    def test_missing_api_key_exits(self):
        conf = {"title": "Workable Backlog", "query": "query_id=123"}
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(SystemExit),
        ):
            backlogger.check_backlog(conf)

    def test_check_backlog_failures_are_reported(self):
        conf = {"title": "Workable Backlog", "query": "query_id=123", "max": 1}
        cases = [
            {
                "desc": "request timeout is reported as query failure",
                "side_effect": requests.ReadTimeout(
                    "https://redmine.example/issues.json?query_id=123"
                ),
                "return_value": None,
                "expected": "ReadTimeout",
            },
            {
                "desc": "http error reports status code without url",
                "side_effect": requests.HTTPError(
                    "503 Server Error: for url: https://redmine.example/issues.json",
                    response=MagicMock(status_code=503),
                ),
                "return_value": None,
                "expected": "HTTPError 503",
            },
            {
                "desc": "response without issues key is reported",
                "side_effect": None,
                "return_value": {},
                "expected": "'issues'",
            },
            {
                "desc": "response without total_count is reported",
                "side_effect": None,
                "return_value": {"issues": []},
                "expected": "'total_count'",
            },
            {
                "desc": "non-numeric total_count is reported",
                "side_effect": None,
                "return_value": {"issues": [], "total_count": "abc"},
                "expected": "invalid literal for int()",
            },
            {
                "desc": "missing total_count value is reported",
                "side_effect": None,
                "return_value": {"issues": [], "total_count": None},
                "expected": "int() argument",
            },
        ]
        for case in cases:
            with self.subTest(case["desc"]):
                mock_json_rest = MagicMock(
                    side_effect=case["side_effect"],
                    return_value=case["return_value"],
                )
                with patch("backlogger.json_rest", mock_json_rest):
                    result = backlogger.check_backlog(conf)
                    good, issue_count, details_md, query_error = result
                _, err = self.capsys.readouterr()
                self.assertIn(
                    f"Error querying backlog Workable Backlog: {case['expected']}", err
                )
                self.assertTrue(err.endswith("\n"))
                self.assertNotIn("https://", err)
                self.assertFalse(good)
                self.assertIsNone(issue_count)
                self.assertIn("Error querying backlog Workable Backlog", details_md)
                self.assertIn(case["expected"], query_error)

    @patch("backlogger.http_request")
    @patch("backlogger.json_rest")
    def test_query_failure_keeps_rows_state_and_excludes_error_from_alert(
        self, mock_json_rest, mock_http_request
    ):
        mock_json_rest.side_effect = [
            requests.ReadTimeout("redmine timeout"),
            {"issues": [], "total_count": 1},
        ]
        data = make_backlog_data(
            [
                {"title": "Failing Query", "query": "query_id=1", "max": 1},
                {"title": "Workable Backlog", "query": "query_id=123", "max": 0},
            ]
        )
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                all_good, rows, bad_queries, blocks = backlogger.render_table(data)
                backlogger.update_state(bad_queries)
                with open("state.json") as sj:
                    state = json.load(sj)
                with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
                    backlogger.trigger_webhook({"bad_queries": {}}, bad_queries)
            finally:
                os.chdir(orig_cwd)
        self.assertFalse(all_good)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "-")
        self.assertEqual(rows[0][3], "&#x1F534;")
        self.assertEqual(rows[1][1], "1")
        self.assertEqual(rows[1][3], "&#x1F534;")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(list(bad_queries), ["Failing Query", "Workable Backlog"])
        self.assertIsNone(bad_queries["Failing Query"]["issue_count"])
        self.assertEqual(bad_queries["Failing Query"]["error"], "ReadTimeout")
        self.assertNotIn("error", bad_queries["Workable Backlog"])
        self.assertEqual(state["bad_queries"], bad_queries)
        msg = json.loads(mock_http_request.call_args.kwargs["body"])["msg"]
        self.assertIn("Workable Backlog", msg)
        self.assertNotIn("Failing Query", msg)

    def test_carry_pending_recoveries_preserves_unannounced_fixed_queries(self):
        state = {
            "bad_queries": {"Workable Backlog": {"issue_count": 2, "limits": "<1"}}
        }
        bad_queries = {
            "Failing Query": {
                "error": "ReadTimeout",
                "issue_count": None,
                "limits": "<1",
            }
        }
        carried = backlogger.carry_pending_recoveries(state, bad_queries)
        self.assertIn("Workable Backlog", carried)
        self.assertIn("Failing Query", carried)

        next_state = {"bad_queries": carried}
        clean_bad_queries = {}
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
            mock_http_request = MagicMock()
            with patch("backlogger.http_request", mock_http_request):
                backlogger.trigger_webhook(next_state, clean_bad_queries)
        msg = json.loads(mock_http_request.call_args.kwargs["body"])["msg"]
        self.assertEqual(msg, ":green_heart: All queries within limits again!")

    def test_carry_pending_recoveries_passes_through_clean_runs(self):
        state = {
            "bad_queries": {"Workable Backlog": {"issue_count": 2, "limits": "<1"}}
        }
        self.assertEqual(backlogger.carry_pending_recoveries(state, {}), {})
        current = {"Workable Backlog": {"issue_count": 3, "limits": "<1"}}
        self.assertEqual(backlogger.carry_pending_recoveries(state, current), current)

    def test_carry_pending_recoveries_keeps_announced_breach_across_query_error(self):
        announced = {"Workable Backlog": {"issue_count": 2, "limits": "<1"}}
        error_run = backlogger.carry_pending_recoveries(
            {"bad_queries": announced},
            {
                "Workable Backlog": {
                    "error": "ReadTimeout",
                    "issue_count": None,
                    "limits": "<1",
                }
            },
        )
        self.assertEqual(error_run, announced)
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
            mock_http_request = MagicMock()
            with patch("backlogger.http_request", mock_http_request):
                backlogger.trigger_webhook({"bad_queries": error_run}, {})
        msg = json.loads(mock_http_request.call_args.kwargs["body"])["msg"]
        self.assertEqual(msg, ":green_heart: All queries within limits again!")

    @patch("backlogger.requests.Session")
    def test_http_request_passes_timeout(self, mock_session):
        session = mock_session.return_value
        with patch.object(backlogger, "_sessions", {}):
            backlogger.http_request(
                "GET", "https://example.com/issues.json", body=None, headers={}
            )
        self.assertEqual(
            session.request.call_args.kwargs["timeout"],
            backlogger.REQUEST_TIMEOUT_SECONDS,
        )

    @patch("backlogger.requests.Session")
    def test_http_request_reuses_one_session(self, mock_session):
        with patch.object(backlogger, "_sessions", {}):
            backlogger.http_request(
                "GET", "https://example.com/one", body=None, headers={}
            )
            backlogger.http_request(
                "GET", "https://example.com/two", body=None, headers={}
            )
        mock_session.assert_called_once()

    @patch("backlogger.requests.Session")
    def test_http_request_retries_status_errors_only_for_get(self, mock_session):
        session = mock_session.return_value
        with patch.object(backlogger, "_sessions", {}):
            backlogger.http_request(
                "PUT", "https://example.com/issues/1.json", body="{}", headers={}
            )
        mounted = session.mount.call_args_list
        self.assertEqual([c.args[0] for c in mounted], ["http://", "https://"])
        for c in mounted:
            retries = c.args[1].max_retries
            self.assertFalse(retries.is_retry("PUT", 503))
            self.assertTrue(retries.is_retry("GET", 503))

    def test_check_render(self):
        leaked = (
            "<details>\n<summary>x</summary>\n\n"
            "| Repository | Open PRs |\n| --- | --- |\n| a | 1 |\n\n</details>"
        )
        self.assertTrue(entrypoint.check_render(leaked))
        clean = (
            "<details>\n<summary>x</summary>\n"
            "<table><tr><td>Repository</td></tr></table>\n</details>"
        )
        self.assertEqual(entrypoint.check_render(clean), [])

    @patch("entrypoint.run_command")
    @patch("entrypoint.shutil.copy")
    def test_entrypoint_resolves_script_path(self, mock_copy, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.dict(
                    os.environ,
                    {"INPUT_CONFIG": "custom.yaml", "INPUT_ARGS": "--exit-code"},
                ):
                    with self.assertRaises(SystemExit) as cm:
                        entrypoint.main()
                    self.assertEqual(cm.exception.code, 0)
                backlogger_cmd = mock_run.call_args_list[1][0][0]
                self.assertIn("backlogger.py custom.yaml --exit-code", backlogger_cmd)
                self.assertTrue(os.path.isabs(backlogger_cmd.split()[1]))
            finally:
                os.chdir(orig_cwd)
