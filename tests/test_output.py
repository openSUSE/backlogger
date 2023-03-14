import os
import sys
import unittest
from unittest.mock import MagicMock, call

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
                {"issue_statuses": [{"name": "In Progress", "id": 2}]},
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
                            "status": {"name": "Resolved"},
                            "created_on": "2022-12-06T13:57:05Z",
                            "updated_on": "2022-12-22T13:12:22Z",
                        },
                        {
                            "id": 4,
                            "status": {"name": "Resolved"},
                            "created_on": "2022-12-08T10:00:00Z",
                            "updated_on": "2022-12-15T10:00:00Z",
                        },
                    ],
                    "total_count": 4,
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
        self.assertEqual(
            backlogger.render_influxdb(backlogger.data),
            [
                'slo,team="Awesome\\ Team",status="In\\ Progress",title="Workable\\ Backlog" count=2',
                'leadTime,team="Awesome\\ Team",status="Resolved",title="Workable\\ Backlog" count=2,leadTime=275.6273611111111,cycleTime=48.0,leadTimeSum=551.2547222222222,cycleTimeSum=96.0',
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
                backlogger.render_table(backlogger.data),
                [
                    ['[Workable Backlog](https://example.com/issues?query_id=123)',
                    '2',
                    scenario["limit"],
                    scenario["icon"]],
                ],
            )
