import socket
import unittest
from unittest.mock import patch, MagicMock, call

# Import is_server_ready from with_server
import sys
from pathlib import Path

# Add script directory to sys.path if not present
sys.path.insert(0, str(Path(__file__).resolve().parent))

from with_server import is_server_ready


class TestIsServerReady(unittest.TestCase):

    @patch("with_server.socket.create_connection")
    @patch("with_server.time.sleep")
    def test_is_server_ready_success_immediately(self, mock_sleep, mock_create_connection):
        """Test is_server_ready returns True immediately when port is open."""
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        result = is_server_ready(8080, timeout=30)

        self.assertTrue(result)
        mock_create_connection.assert_called_once_with(('localhost', 8080), timeout=1)
        mock_sleep.assert_not_called()

    @patch("with_server.socket.create_connection")
    @patch("with_server.time.sleep")
    def test_is_server_ready_success_after_retry(self, mock_sleep, mock_create_connection):
        """Test is_server_ready retries and returns True when port becomes ready."""
        mock_conn = MagicMock()
        mock_create_connection.side_effect = [
            ConnectionRefusedError("Connection refused"),
            socket.error("Socket error"),
            mock_conn,
        ]

        result = is_server_ready(3000, timeout=10)

        self.assertTrue(result)
        self.assertEqual(mock_create_connection.call_count, 3)
        mock_create_connection.assert_has_calls([
            call(('localhost', 3000), timeout=1),
            call(('localhost', 3000), timeout=1),
            call(('localhost', 3000), timeout=1),
        ])
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_has_calls([call(0.5), call(0.5)])

    @patch("with_server.socket.create_connection")
    @patch("with_server.time.time")
    @patch("with_server.time.sleep")
    def test_is_server_ready_timeout(self, mock_sleep, mock_time, mock_create_connection):
        """Test is_server_ready returns False when connection times out."""
        mock_create_connection.side_effect = ConnectionRefusedError("Connection refused")
        # Simulate time passing: start at 100, then loop iterations 105, 115, 125, 131
        mock_time.side_effect = [100.0, 105.0, 115.0, 125.0, 131.0]

        result = is_server_ready(5173, timeout=30)

        self.assertFalse(result)
        self.assertGreater(mock_create_connection.call_count, 1)
        self.assertTrue(mock_sleep.called)


if __name__ == "__main__":
    unittest.main()
