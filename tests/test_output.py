import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


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
        now = datetime.now(timezone.utc).replace(tzinfo=None)
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
        self.assertIn("**1** 🔴", details_md)  # Each repo has 1 stale PR

    @patch("backlogger.fetch_github_prs")
    def test_github_render_table(self, mock_fetch):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
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
