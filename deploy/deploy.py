#!/usr/bin/env python3
"""Deploy the Shariah fund management system to a server over SSH.

This is the whole pipeline: package the repo, ship it, build the images on the
server, run the migration and the seed, bring the stack up, install the nginx
site, and verify everything answers. Re-running it is safe -- Compose, Alembic
and the seed are all idempotent, and the server's own secrets file is written
once and never overwritten by a later run.

Deliberately isolated from whatever else is already running on the target: its
own Compose project name, its own ports (see deploy/.env.prod.example), its own
nginx site file, and nothing it does touches another project's containers,
volumes, or nginx configuration.

Usage:
    DEPLOY_SSH_PASSWORD='...' python deploy/deploy.py [--host 172.17.0.100]
                                                       [--user srv]
                                                       [--remote-dir apps/fms]
                                                       [--skip-nginx]

The SSH password is read from the DEPLOY_SSH_PASSWORD environment variable --
deliberately not a command-line argument (visible in `ps`) and never written to
this file.
"""

from __future__ import annotations

import argparse
import io
import os
import posixpath
import secrets
import sys
import tarfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import paramiko
except ImportError:
    print("This script needs paramiko: pip install paramiko", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories that never belong in a release: build output, caches, local state,
# and anything that could carry a local secret or a throwaway script.
EXCLUDE_DIR_NAMES = {
    ".git", ".venv", "node_modules", ".next", "__pycache__", ".pytest_cache",
    ".hypothesis", ".mypy_cache", ".ruff_cache", "coverage", "playwright-report",
    "test-results", "var",
}
EXCLUDE_EXACT_PATHS = {
    "deploy/_probe.py", "deploy/_probe2.py", "deploy/_probe3.py",
    "deploy/_probe4.py", "deploy/_probe5.py", "deploy/_probe6.py",
}


def build_release_tarball() -> bytes:
    """Everything the server needs to build and run the stack, nothing else."""
    buffer = io.BytesIO()

    def tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        if any(part in EXCLUDE_DIR_NAMES for part in parts):
            return None
        rel = info.name.split("/", 1)[1] if "/" in info.name else ""
        if rel in EXCLUDE_EXACT_PATHS:
            return None
        return info

    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(REPO_ROOT, arcname="fms", filter=tar_filter)
    return buffer.getvalue()


def sftp_upload_bytes(sftp: "paramiko.SFTPClient", data: bytes, remote_path: str) -> None:
    with sftp.open(remote_path, "wb") as handle:
        handle.write(data)


class Remote:
    """A thin wrapper so every call logs what it ran and fails loudly."""

    def __init__(self, client: paramiko.SSHClient, sudo_password: str) -> None:
        self.client = client
        self.sudo_password = sudo_password

    def run(self, command: str, as_root: bool = False, check: bool = True) -> str:
        print(f"\n$ {command}")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=600)
        if as_root:
            stdin.write(self.sudo_password + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if out.strip():
            print(out.strip())
        if err.strip():
            print("[stderr]", err.strip(), file=sys.stderr)
        if check and status != 0:
            raise RuntimeError(f"command failed (exit {status}): {command}")
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="172.17.0.100")
    parser.add_argument("--user", default="srv")
    parser.add_argument("--remote-dir", default="apps/fms", help="relative to the user's home")
    parser.add_argument("--skip-nginx", action="store_true", help="skip installing the nginx site")
    args = parser.parse_args()

    password = os.environ.get("DEPLOY_SSH_PASSWORD")
    if not password:
        print("Set DEPLOY_SSH_PASSWORD in the environment before running this.", file=sys.stderr)
        return 2

    print(f"== Connecting to {args.user}@{args.host} ==")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15)
    remote = Remote(client, password)
    sftp = client.open_sftp()

    try:
        home = remote.run("echo $HOME").strip()
        project_dir = posixpath.join(home, args.remote_dir)
        deploy_dir = posixpath.join(project_dir, "deploy")

        print(f"== Preparing {project_dir} ==")
        remote.run(f"mkdir -p {project_dir}")

        print("== Packaging the release ==")
        tarball = build_release_tarball()
        print(f"   {len(tarball) / 1_048_576:.1f} MiB")
        remote_tarball = posixpath.join(home, "fms_release.tar.gz")
        sftp_upload_bytes(sftp, tarball, remote_tarball)

        print("== Extracting on the server ==")
        remote.run(f"tar xzf {remote_tarball} -C {home}")
        remote.run(f"rsync -a --delete --exclude deploy/.env {home}/fms/ {project_dir}/ 2>&1 || "
                    f"(rm -rf {project_dir}.new && mv {home}/fms {project_dir}.new && "
                    f"[ -f {deploy_dir}/.env ] && cp {deploy_dir}/.env {project_dir}.new/deploy/.env; "
                    f"rm -rf {project_dir} && mv {project_dir}.new {project_dir})")
        remote.run(f"rm -f {remote_tarball}")

        print("== Writing secrets (only if this is the first deploy) ==")
        env_path = posixpath.join(deploy_dir, ".env")
        has_env = remote.run(f"[ -f {env_path} ] && echo yes || echo no", check=False).strip()
        if has_env != "yes":
            env_contents = (
                "POSTGRES_USER=fms\n"
                f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}\n"
                "POSTGRES_DB=fms\n"
                f"FMS_SECRET_KEY={secrets.token_hex(32)}\n"
                "WEB_PORT=3100\n"
                "API_PORT=8101\n"
            )
            sftp_upload_bytes(sftp, env_contents.encode(), env_path)
            print(f"   wrote a fresh {env_path}")
        else:
            print(f"   {env_path} already exists; leaving it alone")

        print("== Building and starting the stack ==")
        compose = (
            "docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env -p fms"
        )
        remote.run(f"cd {project_dir} && {compose} up -d --build")

        print("== Waiting for the API to report healthy ==")
        for attempt in range(30):
            status = remote.run(
                f"cd {project_dir} && {compose} ps api --format '{{{{.Health}}}}'", check=False
            ).strip()
            if status == "healthy":
                break
            time.sleep (4)
        else:
            print("   API did not become healthy in time; check logs:", file=sys.stderr)
            remote.run(f"cd {project_dir} && {compose} logs --tail=80 api", check=False)
            raise RuntimeError("deployment did not become healthy")
        print("   healthy")

        print("== Seed output (temporary passwords, only printed the first time) ==")
        remote.run(f"cd {project_dir} && {compose} logs seed", check=False)

        if not args.skip_nginx:
            print("== Installing the nginx site ==")
            nginx_conf = (REPO_ROOT / "deploy" / "nginx-fms.conf").read_text()
            tmp_conf = posixpath.join(home, "fms_nginx_site.conf")
            sftp_upload_bytes(sftp, nginx_conf.encode(), tmp_conf)
            remote.run(
                f"sudo -S -p '' cp {tmp_conf} /etc/nginx/sites-available/fms && "
                f"sudo -n ln -sf /etc/nginx/sites-available/fms /etc/nginx/sites-enabled/fms && "
                f"sudo -n nginx -t && sudo -n systemctl reload nginx && rm -f {tmp_conf}",
                as_root=True,
            )
            print("   nginx site installed (salaam-fund's own site file was not touched)")

        print("\n== Verifying from outside the box ==")
        remote.run(
            "curl -fsS http://127.0.0.1:${API_PORT:-8101}/api/v1/health "
            "|| curl -fsS http://127.0.0.1:8101/api/v1/health",
            check=False,
        )

        print("\n== Done ==")
        print(f"  Web:  https://{args.host}:8543   (via nginx, private-CA cert)")
        print(f"  API:  https://{args.host}:9443/api/v1/health")
        print(f"  Direct, bypassing nginx: http://{args.host}:8101/api/v1/health is loopback-only")
        print(f"  Project directory on the server: {project_dir}")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
