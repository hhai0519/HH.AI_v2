import unittest
import os
import json
from unittest.mock import patch, mock_open, MagicMock

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

from quota_monitor import get_quota, DB_PATH

class TestQuotaMonitor(unittest.TestCase):
    @patch('os.path.exists')
    def test_get_quota_from_tmp_file(self, mock_exists):
        # Setup: current_quota.tmp exists
        def side_effect(path):
            if path == 'current_quota.tmp':
                return True
            return False
        mock_exists.side_effect = side_effect

        m_open = mock_open(read_data="85.5")
        with patch('builtins.open', m_open):
            quota, msg = get_quota()

        self.assertEqual(quota, 85.5)
        self.assertEqual(msg, "Source: current_quota.tmp (Manual Override)")

    @patch('os.path.exists')
    def test_get_quota_from_db_cockpit(self, mock_exists):
        # Setup: tmp file doesn't exist, DB does
        def side_effect(path):
            if path == 'current_quota.tmp':
                return False
            if path == DB_PATH:
                return True
            return False
        mock_exists.side_effect = side_effect

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Setup for Cockpit query to succeed
        db_data = {
            "state.model_quotas": {
                "MODEL_PLACEHOLDER_M47": {
                    "remaining_percent": 42.0
                }
            }
        }
        mock_cursor.fetchone.side_effect = [(json.dumps(db_data),), None]

        with patch('sqlite3.connect', return_value=mock_conn):
            quota, msg = get_quota()

        self.assertEqual(quota, 42.0)
        self.assertEqual(msg, "Source: Cockpit DB Cached")

    @patch('os.path.exists')
    def test_get_quota_from_db_new_model_credits(self, mock_exists):
        def side_effect(path):
            if path == 'current_quota.tmp':
                return False
            if path == DB_PATH:
                return True
            return False
        mock_exists.side_effect = side_effect

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Setup for Cockpit query to fail, new model credits query to succeed
        mock_cursor.fetchone.side_effect = [None, ("binary_data",)]

        with patch('sqlite3.connect', return_value=mock_conn):
            quota, msg = get_quota()

        self.assertIsNone(quota)
        self.assertIn("偵測到新版 modelCredits 鍵值", msg)

    @patch('os.path.exists')
    def test_get_quota_db_missing(self, mock_exists):
        def side_effect(path):
            return False # Neither file exists
        mock_exists.side_effect = side_effect

        quota, msg = get_quota()

        self.assertIsNone(quota)
        self.assertIn("找不到資料庫文件", msg)

    @patch('os.path.exists')
    def test_get_quota_from_db_cockpit_no_remaining(self, mock_exists):
        def side_effect(path):
            if path == 'current_quota.tmp':
                return False
            if path == DB_PATH:
                return True
            return False
        mock_exists.side_effect = side_effect

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Setup for Cockpit query to succeed but missing remaining_percent
        db_data = {
            "state.model_quotas": {
                "MODEL_PLACEHOLDER_M47": {
                }
            }
        }
        # First fetchone returns db_data, next one (new modelCredits) returns None
        mock_cursor.fetchone.side_effect = [(json.dumps(db_data),), None]

        with patch('sqlite3.connect', return_value=mock_conn):
            quota, msg = get_quota()

        self.assertIsNone(quota)
        self.assertIn("無法自動取得配額", msg)

    @patch('os.path.exists')
    def test_get_quota_db_exception(self, mock_exists):
        def side_effect(path):
            if path == 'current_quota.tmp':
                return False
            if path == DB_PATH:
                return True
            return False
        mock_exists.side_effect = side_effect

        with patch('sqlite3.connect', side_effect=Exception("DB Error")):
            quota, msg = get_quota()

        self.assertIsNone(quota)
        self.assertIn("讀取資料庫時發生異常: DB Error", msg)

if __name__ == '__main__':
    unittest.main()
