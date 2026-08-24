import sys
import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock

# Import start_server_process from skills/execution/webapp-testing/scripts/with_server.py
sys.path.insert(0, os.path.abspath('skills/execution/webapp-testing/scripts'))
from with_server import start_server_process

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
