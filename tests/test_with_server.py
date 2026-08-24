import subprocess
import time
import sys
import os
import pytest

WITH_SERVER_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "skills", "execution", "webapp-testing", "scripts", "with_server.py"
)

def test_single_server_success():
    # Start a simple server using python http.server
    cmd = [
        sys.executable,
        WITH_SERVER_SCRIPT,
        "--server", "python3 -m http.server 8891",
        "--port", "8891",
        "--", "echo", "hello"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "hello" in res.stdout
    assert "Server ready on port 8891" in res.stdout

def test_multiple_servers_bench():
    # Start 3 servers, each sleeping 1 second before opening port
    # In sequential startup: 1s + 1s + 1s ≈ 3+ seconds
    # In parallel startup: max(1s, 1s, 1s) ≈ 1+ seconds
    server_cmd_fmt = "python3 -c \"import socket, time; time.sleep(1); s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(1); time.sleep(5)\""
    ports = [8892, 8893, 8894]

    args = [sys.executable, WITH_SERVER_SCRIPT]
    for port in ports:
        args.extend(["--server", server_cmd_fmt.format(port=port), "--port", str(port)])
    args.extend(["--", "echo", "ready"])

    start_time = time.time()
    res = subprocess.run(args, capture_output=True, text=True)
    duration = time.time() - start_time

    assert res.returncode == 0
    assert "ready" in res.stdout
    print(f"\n[BENCHMARK] Startup time for 3 servers: {duration:.2f}s")
