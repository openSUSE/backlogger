import os
import sys
import unittest
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


class TestOutput(unittest.TestCase):
    def test_influxdb(self):
        data = {"api": "https://example.com/issues.json", "team": "Awesome Team", "output": "influxdb",
                "queries": [{"title": "Workable Backlog", "query": "query_id=123"}]}
        backlogger.data = data
        backlogger.json_rest = MagicMock(return_value={"issues":[], "total_count":2})
        self.assertEqual(backlogger.render_influxdb(data),
                         ['slo,team="Awesome Team",title="Workable Backlog" count=2'])
