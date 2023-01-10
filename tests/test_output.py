import os
import sys
import unittest
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


class TestOutput(unittest.TestCase):
    def test_influxdb(self):
        data = {
            "api": "https://example.com/issues.json",
            "team": "Awesome Team",
            "output": "influxdb",
            "queries": [{"title": "Workable Backlog", "query": "query_id=123"}],
        }
        backlogger.data = data
        backlogger.json_rest = MagicMock(
            return_value={
                "issues": [
                    {
                        "status": {"name": "In Progress"},
                        "created_on": "2022-12-12T07:51:24Z",
                        "updated_on": "2022-12-19T12:34:52Z",
                    },
                    {
                        "status": {"name": "In Progress"},
                        "created_on": "2022-12-06T21:32:03Z",
                        "updated_on": "2022-12-09T13:19:29Z",
                    },
                    {
                        "status": {"name": "Resolved"},
                        "created_on": "2022-12-06T13:57:05Z",
                        "updated_on": "2022-12-22T13:12:22Z",
                    },
                ],
                "total_count": 3,
            }
        )
        self.assertEqual(
            backlogger.render_influxdb(data),
            [
                'slo,team="Awesome Team",status="In Progress",title="Workable Backlog" count=2 avg=118.25750000000001 med=172.72444444444446 std=5933.296074228397',
                'leadTime,team="Awesome Team",status="Resolved",title="Workable Backlog" count=1 avg=383.2547222222222 med=383.2547222222222 std=0',
            ],
        )
