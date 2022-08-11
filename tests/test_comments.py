import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backlogger


class TestComments(unittest.TestCase):
    def test_comments(self):
        data = {'url': 'https://example.com/issues', 'web': 'https://example.com/wiki'}
        backlogger.data = data
        sys.argv[1:] = ['--reminder-comment-on-issues']
        backlogger.json_rest = MagicMock(return_value=None)
        backlogger.list_issues({'query': 'query_id=123&c%5B%5D=updated_on'},
            {'issues': [{'priority': {'name': 'High'}, 'id': 123}], 'total_count': 1})
        backlogger.list_issues({'query': 'query_id=123&'},
            {'issues': [{'priority': {'name': 'High'}, 'id': 456}], 'total_count': 1})
        backlogger.json_rest.assert_called_once_with('PUT', 'https://example.com/wiki/123.json',
            {'issue': {'notes': 'This ticket was set to **High** priority but was not updated [within the SLO period](https://example.com/issues). Please consider picking up this ticket or just set the ticket to the next lower priority.'}})
