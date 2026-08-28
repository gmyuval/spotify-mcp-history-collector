"""Validate development and production Compose configuration without applying it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")


def main() -> int:
    docker = shutil.which("docker")
    if docker is None:
        print("Docker CLI is required for Compose configuration validation.", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["COMPOSE_DISABLE_ENV_FILE"] = "1"

    failed = False
    for relative_path in COMPOSE_FILES:
        command = [docker, "compose"]
        if relative_path == "docker-compose.prod.yml":
            command.extend(["--env-file", ".env.prod.example"])
        command.extend(["-f", relative_path, "config", "--quiet"])
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode == 0:
            print(f"Compose configuration OK: {relative_path}")
            continue
        failed = True
        print(f"Compose configuration failed: {relative_path}", file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")

    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
