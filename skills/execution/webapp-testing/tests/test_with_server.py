import sys
import os
import subprocess
import pytest
import socket
from unittest.mock import patch, MagicMock, call

# Import start_server_process from skills/execution/webapp-testing/scripts/with_server.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from with_server import start_server_process, is_server_ready, main

def test_start_server_simple_command():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        proc = start_server_process("python3 -m http.server 8000")

        mock_popen.assert_called_once_with(
            ['python3', '-m', 'http.server', '8000'],
            cwd=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        assert proc == mock_proc

def test_start_server_cd_and_cmd():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        proc = start_server_process("cd backend && python3 server.py")

        expected_cwd = os.path.abspath("backend")
        mock_popen.assert_called_once_with(
            ['python3', 'server.py'],
            cwd=expected_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        assert proc == mock_proc

def test_start_server_multiple_subcommands():
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = MagicMock(returncode=0)
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        proc = start_server_process("cd frontend && npm run build && npm run start")

        expected_cwd = os.path.abspath("frontend")
        mock_run.assert_called_once_with(['npm', 'run', 'build'], cwd=expected_cwd)
        mock_popen.assert_called_once_with(
            ['npm', 'run', 'start'],
            cwd=expected_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

def test_start_server_prerequisite_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(RuntimeError) as exc_info:
            start_server_process("npm run build && npm run start")

        assert "Command failed with return code 1" in str(exc_info.value)

def test_command_injection_prevention():
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = MagicMock(returncode=0)
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        # Malicious input attempting shell expansion/injection
        start_server_process("echo $(whoami) && python3 server.py")

        # Verify prerequisite run call was passed list of tokens safely
        mock_run.assert_called_once_with(['echo', '$(whoami)'], cwd=None)
        # Verify popen call for server was passed list of tokens safely
        mock_popen.assert_called_once_with(
            ['python3', 'server.py'],
            cwd=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

def test_is_server_ready_success_immediately():
    """Test is_server_ready returns True immediately when port is open."""
    with patch("with_server.socket.create_connection") as mock_create_connection, \
         patch("with_server.time.sleep") as mock_sleep:
        
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        result = is_server_ready(8080, timeout=30)

        assert result is True
        mock_create_connection.assert_called_once_with(('localhost', 8080), timeout=1)
        mock_sleep.assert_not_called()

def test_is_server_ready_success_after_retry():
    """Test is_server_ready retries and returns True when port becomes ready."""
    with patch("with_server.socket.create_connection") as mock_create_connection, \
         patch("with_server.time.sleep") as mock_sleep:
        
        mock_conn = MagicMock()
        mock_create_connection.side_effect = [
            ConnectionRefusedError("Connection refused"),
            socket.error("Socket error"),
            mock_conn,
        ]

        result = is_server_ready(3000, timeout=10)

        assert result is True
        assert mock_create_connection.call_count == 3
        mock_create_connection.assert_has_calls([
            call(('localhost', 3000), timeout=1),
            call(('localhost', 3000), timeout=1),
            call(('localhost', 3000), timeout=1),
        ])
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(0.05), call(0.1)])

def test_is_server_ready_timeout():
    """Test is_server_ready returns False when connection times out."""
    with patch("with_server.socket.create_connection") as mock_create_connection, \
         patch("with_server.time.time") as mock_time, \
         patch("with_server.time.sleep") as mock_sleep:
        
        mock_create_connection.side_effect = ConnectionRefusedError("Connection refused")
        # Simulate time passing: start at 100, then loop iterations 105, 115, 125, 131
        mock_time.side_effect = [100.0, 105.0, 115.0, 125.0, 131.0]

        result = is_server_ready(5173, timeout=30)

        assert result is False
        assert mock_create_connection.call_count > 1
        assert mock_sleep.called


def test_main_missing_command(capsys):
    with patch("sys.argv", ["with_server.py", "--server", "npm run dev", "--port", "3000"]), \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
        try:
            main()
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "Error: No command specified to run" in captured.out
        mock_exit.assert_called_once_with(1)

def test_main_mismatched_server_and_port(capsys):
    with patch("sys.argv", ["with_server.py", "--server", "npm run dev", "--port", "3000", "--port", "3001", "python", "test.py"]), \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
        try:
            main()
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "Error: Number of --server and --port arguments must match" in captured.out
        mock_exit.assert_called_once_with(1)

def test_main_successful_execution(capsys):
    with patch("sys.argv", ["with_server.py", "--server", "npm start", "--port", "3000", "python", "test.py"]), \
         patch("with_server.start_server_process") as mock_start, \
         patch("with_server.is_server_ready", return_value=True) as mock_ready, \
         patch("subprocess.run") as mock_run, \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:

        mock_proc = MagicMock()
        mock_start.return_value = mock_proc
        mock_run.return_value = MagicMock(returncode=0)

        try:
            main()
        except SystemExit:
            pass

        mock_start.assert_called_once_with("npm start")
        mock_ready.assert_called_once_with(3000, timeout=30)
        mock_run.assert_called_once_with(["python", "test.py"])
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)
        mock_exit.assert_called_once_with(0)

def test_main_server_timeout(capsys):
    with patch("sys.argv", ["with_server.py", "--server", "npm start", "--port", "3000", "python", "test.py"]), \
         patch("with_server.start_server_process") as mock_start, \
         patch("with_server.is_server_ready", return_value=False) as mock_ready, \
         patch("subprocess.run") as mock_run:

        mock_proc = MagicMock()
        mock_start.return_value = mock_proc

        with pytest.raises(RuntimeError) as exc_info:
            main()

        assert "Server failed to start on port 3000 within 30s" in str(exc_info.value)
        mock_start.assert_called_once_with("npm start")
        mock_ready.assert_called_once_with(3000, timeout=30)
        mock_run.assert_not_called()
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)


def test_main_server_cleanup_timeout():
    """Test that main() handles TimeoutExpired correctly during server cleanup."""
    with patch("with_server.sys.argv", ["with_server.py", "--server", "dummy", "--port", "8000", "--", "echo", "hello"]), \
         patch("with_server.start_server_process") as mock_start, \
         patch("with_server.is_server_ready") as mock_ready, \
         patch("with_server.subprocess.run") as mock_run:

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="dummy", timeout=5), None]
        mock_start.return_value = mock_proc
        mock_ready.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 0
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert mock_proc.wait.call_count == 2
        mock_proc.wait.assert_has_calls([call(timeout=5), call()])
