import paramiko

HOST = "172.17.0.100"
USER = "srv"
PASSWORD = "Salaam@123"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
cmds = [
    "whoami && id",
    "uname -a",
    "cat /etc/os-release 2>/dev/null | head -5",
    "sudo -n true && echo HAS_PASSWORDLESS_SUDO || echo NO_PASSWORDLESS_SUDO",
    "which docker && docker --version",
    "docker compose version 2>&1",
    "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1",
    "docker network ls 2>&1",
    "ss -ltnp 2>/dev/null | head -40",
    "df -h / 2>&1",
    "free -h 2>&1",
    "ls -la /opt 2>&1",
    "ls -la /srv 2>&1",
    "ls -la /home 2>&1",
]
for c in cmds:
    print(f"\n$ {c}")
    stdin, stdout, stderr = client.exec_command(c, timeout=20)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    print(out.strip())
    if err.strip():
        print("[stderr]", err.strip())
client.close()
