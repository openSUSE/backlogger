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
            {"icon": "&#x1F49A;", "limit": "", "data": {}},
            {"icon": "&#x1F534;", "limit": "<2", "data": {"max": 1}},
            {"icon": "&#x1F49A;", "limit": "<5, >0", "data": {"min": 1, "max": 4}},
            {"icon": "&#x1F534;", "limit": "<5, >2", "data": {"min": 3, "max": 4}},
        ]
        for scenario in scenarios:
            query = {"title": "Workable Backlog", "query": "query_id=123"}
            query.update(scenario["data"])
            test_data = make_backlog_data([query])
            mock_json_rest = MagicMock(
                side_effect=[
                    {
                        "issues": [],
                        "total_count": 2,
                    },
                ]
            )
            with (
                patch.object(backlogger, "data", test_data),
                patch("backlogger.json_rest", mock_json_rest),
            ):
                self.assertEqual(
                    backlogger.render_table(backlogger.data)[1],
                    [
                        [
                            "[Workable Backlog](https://example.com/issues?query_id=123)",
                            "2",
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

        good, issue_count, details_md = backlogger.check_github_backlog(conf)
        self.assertFalse(good)  # 2 stale PRs > max 1
        self.assertEqual(issue_count, 2)
        self.assertIn("Show breakdown for: Stale PRs", details_md)
        self.assertIn("os-autoinst/openQA", details_md)
        self.assertIn("os-autoinst/os-autoinst", details_md)
        self.assertIn("10 days ago", details_md)
        self.assertIn("<strong>1</strong> 🔴", details_md)
        self.assertIn("<table>", details_md)
        self.assertIn("<td>", details_md)
        self.assertNotIn("| --- |", details_md)

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

        data = {
            "api": "https://example.com/issues.json",
            "web": "https://example.com/issues",
            "team": "Awesome Team",
            "queries": [
                {
                    "title": "Stale PRs",
                    "type": "github",
                    "repos": ["os-autoinst/openQA"],
                    "stale_days": 7,
                    "max": 0,
                }
            ],
        }
        backlogger.data = data
        all_good, rows, _, details_md_blocks = backlogger.render_table(data)

        self.assertFalse(all_good)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "1")  # 1 stale PR
        self.assertEqual(rows[0][3], "&#x1F534;")  # red/fail icon
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

    @patch("backlogger.http_request")
    def test_webhook_without_state_posts_nothing(self, mock_http_request):
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}, clear=True):
            backlogger.trigger_webhook(
                None, {"Workable Backlog": {"limits": "<5", "issue_count": 10}}
            )
        mock_http_request.assert_not_called()

    @patch("backlogger.http_request")
    def test_webhook_connection_failure_is_logged_without_raising(
        self, mock_http_request
    ):
        mock_http_request.side_effect = requests.ConnectionError("webhook unreachable")
        with patch.dict(os.environ, {"WEBHOOK_URL": DEFAULT_WEBHOOK_URL}):
            backlogger.trigger_webhook(
                {"bad_queries": {}},
                {"Workable Backlog": {"limits": "<5", "issue_count": 10}},
            )
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
            backlogger.trigger_webhook(
                {"bad_queries": {}},
                {"Workable Backlog": {"limits": "<5", "issue_count": 10}},
            )
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
            backlogger.trigger_webhook(
                {"bad_queries": {}},
                {"Workable Backlog": {"limits": "<5", "issue_count": 10}},
            )
        _, err = self.capsys.readouterr()
        self.assertEqual(err, "Webhook notification failed: ConnectionError\n")
        self.assertNotIn(secret_token, err)

    def test_webhook_json_content_type_and_sorted_lines(self):
        state = {"bad_queries": {}}
        bad_queries = {
            "Workable Backlog": {"limits": "<5", "issue_count": 10},
            "Second Query": {"limits": "<3", "issue_count": 9},
        }
        mock_http_request = MagicMock()
        with (
            patch.dict(os.environ, {"WEBHOOK_URL": "https://hook.example.com"}),
            patch("backlogger.http_request", mock_http_request),
        ):
            backlogger.trigger_webhook(state, bad_queries)
        method, url = mock_http_request.call_args.args
        kwargs = mock_http_request.call_args.kwargs
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://hook.example.com")
        self.assertEqual(kwargs["headers"], backlogger.JSON_HEADERS)
        self.assertEqual(
            json.loads(kwargs["body"])["msg"],
            ":red_circle: Some queries are exceeding limits:\n"
            "• Second Query (Issue count 9 exceeding limit of [<3])\n"
            "• Workable Backlog (Issue count 10 exceeding limit of [<5])",
        )

    def test_webhook_missing_url_no_request(self):
        state = {"bad_queries": {}}
        bad_queries = {"Workable Backlog": {"limits": "<5", "issue_count": 10}}
        mock_http_request = MagicMock()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backlogger.http_request", mock_http_request),
        ):
            backlogger.trigger_webhook(state, bad_queries)
        mock_http_request.assert_not_called()

    @patch("backlogger.requests.Session")
    def test_http_request_passes_timeout(self, mock_session):
        session = mock_session.return_value.__enter__.return_value
        backlogger.http_request(
            "GET", "https://example.com/issues.json", body=None, headers={}
        )
        self.assertEqual(
            session.request.call_args.kwargs["timeout"],
            backlogger.REQUEST_TIMEOUT_SECONDS,
        )

    @patch("backlogger.requests.Session")
    def test_http_request_retries_status_errors_only_for_get(self, mock_session):
        session = mock_session.return_value.__enter__.return_value
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
