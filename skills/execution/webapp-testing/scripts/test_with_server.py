import unittest
from unittest.mock import patch, MagicMock
import sys
import subprocess
import socket

from with_server import (
    is_server_ready,
    parse_args,
    stop_servers,
    server_manager,
    main
)


class TestWithServer(unittest.TestCase):

    @patch("socket.create_connection")
    def test_is_server_ready_success(self, mock_conn):
        mock_conn.return_value = MagicMock()
        self.assertTrue(is_server_ready(8080, timeout=1))

    @patch("socket.create_connection", side_effect=socket.error("Connection refused"))
    def test_is_server_ready_timeout(self, mock_conn):
        self.assertFalse(is_server_ready(8080, timeout=0.1))

    def test_parse_args_valid(self):
        test_argv = ["--server", "npm start", "--port", "3000", "--", "python", "test.py"]
        args, servers = parse_args(test_argv)
        self.assertEqual(args.command, ["python", "test.py"])
        self.assertEqual(servers, [{"cmd": "npm start", "port": 3000}])

    def test_parse_args_multiple_servers(self):
        test_argv = [
            "--server", "cmd1", "--port", "3000",
            "--server", "cmd2", "--port", "5173",
            "echo", "done"
        ]
        args, servers = parse_args(test_argv)
        self.assertEqual(args.command, ["echo", "done"])
        self.assertEqual(servers, [
            {"cmd": "cmd1", "port": 3000},
            {"cmd": "cmd2", "port": 5173}
        ])

    @patch("sys.exit")
    def test_parse_args_no_command(self, mock_exit):
        test_argv = ["--server", "npm start", "--port", "3000"]
        parse_args(test_argv)
        mock_exit.assert_called_with(1)

    @patch("sys.exit")
    def test_parse_args_mismatched_server_port(self, mock_exit):
        test_argv = ["--server", "cmd1", "--server", "cmd2", "--port", "3000", "--", "echo", "hi"]
        parse_args(test_argv)
        mock_exit.assert_called_with(1)

    def test_stop_servers_normal(self):
        proc1 = MagicMock()
        proc2 = MagicMock()
        stop_servers([proc1, proc2])
        proc1.terminate.assert_called_once()
        proc1.wait.assert_called_once_with(timeout=5)
        proc2.terminate.assert_called_once()
        proc2.wait.assert_called_once_with(timeout=5)

    def test_stop_servers_timeout_expired(self):
        proc = MagicMock()
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="test", timeout=5), None]
        stop_servers([proc])
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    @patch("with_server.is_server_ready", return_value=True)
    @patch("subprocess.Popen")
    def test_server_manager_success(self, mock_popen, mock_ready):
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        servers = [{"cmd": "npm start", "port": 3000}]

        with server_manager(servers, timeout=5) as procs:
            self.assertEqual(procs, [mock_proc])

        mock_proc.terminate.assert_called_once()

    @patch("with_server.is_server_ready", return_value=False)
    @patch("subprocess.Popen")
    def test_server_manager_failure_cleans_up(self, mock_popen, mock_ready):
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        servers = [{"cmd": "npm start", "port": 3000}]

        with self.assertRaises(RuntimeError):
            with server_manager(servers, timeout=0.1):
                pass

        mock_proc.terminate.assert_called_once()

    @patch("subprocess.run")
    @patch("with_server.server_manager")
    @patch("with_server.parse_args")
    def test_main(self, mock_parse, mock_mgr, mock_run):
        mock_args = MagicMock()
        mock_args.command = ["echo", "test"]
        mock_args.timeout = 30
        servers = [{"cmd": "npm start", "port": 3000}]
        mock_parse.return_value = (mock_args, servers)
        mock_run.return_value = MagicMock(returncode=0)

        with patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_with(0)


if __name__ == "__main__":
    unittest.main()
