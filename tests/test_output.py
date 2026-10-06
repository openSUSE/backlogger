import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger
import entrypoint


class TestOutput(unittest.TestCase):
    def setUp(self):
        data = {
            "api": "https://example.com/issues.json",
            "web": "https://example.com/issues",
            "team": "Awesome Team",
            "queries": [{"title": "Workable Backlog", "query": "query_id=123"}],
        }
        backlogger.data = data

    def test_influxdb(self):
        backlogger.json_rest = MagicMock(
            side_effect=[
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
        )
        backlogger._today_nanoseconds = MagicMock(side_effect=[23])
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
            backlogger.data["queries"] = [query]
            backlogger.json_rest = MagicMock(
                side_effect=[
                    {
                        "issues": [],
                        "total_count": 2,
                    },
                ]
            )
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

    @patch("entrypoint.run_command")
    @patch("entrypoint.shutil.copy")
    def test_main_tolerates_non_utf8_state_file(self, mock_copy, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with open("state.json", "wb") as f:
                    f.write(b"\xff\xfe{}")
                with self.assertRaises(SystemExit) as cm:
                    entrypoint.main()
                self.assertEqual(cm.exception.code, 0)
                with open(os.path.join("gh-pages", "index.html")) as f:
                    self.assertIn("#55cc33", f.read())
            finally:
                os.chdir(orig_cwd)

    def test_get_state(self):
        cases = [
            {
                "desc": "returns None when STATE_FOLDER is not set",
                "folder": False,
                "content": None,
                "expected": None,
                "stderr": None,
            },
            {
                "desc": "returns None when state file does not exist",
                "folder": True,
                "content": None,
                "expected": None,
                "stderr": None,
            },
            {
                "desc": "returns None when state file is empty",
                "folder": True,
                "content": "",
                "expected": None,
                "stderr": None,
            },
            {
                "desc": "returns decoded dict when state file contains valid JSON",
                "folder": True,
                "content": '{"bad_queries": {"q1": {}}}',
                "expected": {"bad_queries": {"q1": {}}},
                "stderr": None,
            },
            {
                "desc": "warns to stderr and returns None when state file contains malformed JSON",
                "folder": True,
                "content": "{invalid_json",
                "expected": None,
                "stderr": "Warning: Failed to decode",
            },
            {
                "desc": "warns to stderr and returns None when state file holds a JSON list",
                "folder": True,
                "content": "[1]",
                "expected": None,
                "stderr": "Warning: Ignoring",
            },
            {
                "desc": "warns to stderr and returns None when state lacks bad_queries",
                "folder": True,
                "content": '{"updated": "2026-01-01T00:00:00+00:00"}',
                "expected": None,
                "stderr": "Warning: Ignoring",
            },
            {
                "desc": "warns to stderr and returns None when state file is not UTF-8",
                "folder": True,
                "content": b"\xff\xfe{}",
                "expected": None,
                "stderr": "Warning: Failed to decode",
            },
            {
                "desc": "warns to stderr and returns None when bad_queries is a list",
                "folder": True,
                "content": '{"bad_queries": []}',
                "expected": None,
                "stderr": "Warning: Ignoring",
            },
            {
                "desc": "warns to stderr and returns None when bad_queries is null",
                "folder": True,
                "content": '{"bad_queries": null}',
                "expected": None,
                "stderr": "Warning: Ignoring",
            },
            {
                "desc": "warns to stderr and returns None when bad_queries is a string",
                "folder": True,
                "content": '{"bad_queries": "q1"}',
                "expected": None,
                "stderr": "Warning: Ignoring",
            },
        ]
        for case in cases:
            with (
                self.subTest(case["desc"]),
                tempfile.TemporaryDirectory() as tmpdir,
                patch.dict(os.environ),
                patch("sys.stderr") as mock_stderr,
            ):
                if case["folder"]:
                    os.environ["STATE_FOLDER"] = tmpdir
                    if case["content"] is not None:
                        mode = "wb" if isinstance(case["content"], bytes) else "w"
                        with open(os.path.join(tmpdir, "state.json"), mode) as f:
                            f.write(case["content"])
                else:
                    os.environ.pop("STATE_FOLDER", None)
                result = backlogger.get_state()
                self.assertEqual(result, case["expected"])
                if case["stderr"]:
                    stderr_output = "".join(
                        call.args[0] for call in mock_stderr.write.call_args_list
                    )
                    self.assertIn(case["stderr"], stderr_output)
                    self.assertIn("state.json", stderr_output)
                else:
                    mock_stderr.write.assert_not_called()
