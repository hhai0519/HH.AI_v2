#!/usr/bin/env python3
"""
Start one or more servers, wait for them to be ready, run a command, then clean up.

Usage:
    # Single server
    python scripts/with_server.py --server "npm run dev" --port 5173 -- python automation.py
    python scripts/with_server.py --server "npm start" --port 3000 -- python test.py

    # Multiple servers
    python scripts/with_server.py \
      --server "cd backend && python server.py" --port 3000 \
      --server "cd frontend && npm run dev" --port 5173 \
      -- python test.py
"""

import os
import shlex
import subprocess
import socket
import time
import sys
import argparse

def is_server_ready(port, timeout=30):
    """Wait for server to be ready by polling the port."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection(('localhost', port), timeout=1):
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def start_server_process(cmd_str):
    """
    Safely start a server process without using shell=True.
    Parses chained commands (separated by && or ;) and tracks cd directory changes.
    """
    tokens = shlex.split(cmd_str)
    subcmds = []
    current = []
    for token in tokens:
        if token in ("&&", ";"):
            if current:
                subcmds.append(current)
                current = []
        else:
            current.append(token)
    if current:
        subcmds.append(current)

    if not subcmds:
        raise ValueError(f"Invalid empty server command: {cmd_str}")

    cwd = None
    for i, subcmd in enumerate(subcmds):
        if not subcmd:
            continue
        if subcmd[0] == "cd":
            if len(subcmd) > 1:
                target_dir = subcmd[1]
                cwd = os.path.abspath(os.path.join(cwd, target_dir)) if cwd else os.path.abspath(target_dir)
            continue

        # If this is the last subcommand, launch in background via Popen
        if i == len(subcmds) - 1:
            return subprocess.Popen(
                subcmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            # Synchronously run prerequisite commands before the server
            res = subprocess.run(subcmd, cwd=cwd)
            if res.returncode != 0:
                raise RuntimeError(f"Command failed with return code {res.returncode}: {' '.join(subcmd)}")

    raise ValueError(f"No executable command found in server command: {cmd_str}")


def main():
    parser = argparse.ArgumentParser(description='Run command with one or more servers')
    parser.add_argument('--server', action='append', dest='servers', required=True, help='Server command (can be repeated)')
    parser.add_argument('--port', action='append', dest='ports', type=int, required=True, help='Port for each server (must match --server count)')
    parser.add_argument('--timeout', type=int, default=30, help='Timeout in seconds per server (default: 30)')
    parser.add_argument('command', nargs=argparse.REMAINDER, help='Command to run after server(s) ready')

    args = parser.parse_args()

    # Remove the '--' separator if present
    if args.command and args.command[0] == '--':
        args.command = args.command[1:]

    if not args.command:
        print("Error: No command specified to run")
        sys.exit(1)

    # Parse server configurations
    if len(args.servers) != len(args.ports):
        print("Error: Number of --server and --port arguments must match")
        sys.exit(1)

    servers = []
    for cmd, port in zip(args.servers, args.ports):
        servers.append({'cmd': cmd, 'port': port})

    server_processes = []

    try:
        # Start all servers
        for i, server in enumerate(servers):
            print(f"Starting server {i+1}/{len(servers)}: {server['cmd']}")

            process = start_server_process(server['cmd'])
            server_processes.append(process)

            # Wait for this server to be ready
            print(f"Waiting for server on port {server['port']}...")
            if not is_server_ready(server['port'], timeout=args.timeout):
                raise RuntimeError(f"Server failed to start on port {server['port']} within {args.timeout}s")

            print(f"Server ready on port {server['port']}")

        print(f"\nAll {len(servers)} server(s) ready")

        # Run the command
        print(f"Running: {' '.join(args.command)}\n")
        result = subprocess.run(args.command)
        sys.exit(result.returncode)

    finally:
        # Clean up all servers
        print(f"\nStopping {len(server_processes)} server(s)...")
        for i, process in enumerate(server_processes):
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            print(f"Server {i+1} stopped")
        print("All servers stopped")


if __name__ == '__main__':
    main()
