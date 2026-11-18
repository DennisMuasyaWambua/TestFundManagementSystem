import paramiko

HOST = "172.17.0.100"
USER = "srv"
PASSWORD = "Salaam@123"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
cmds = [
    "ls -la ~/srv 2>&1",
    "find ~/srv -maxdepth 3 -iname '*compose*' -o -iname '*docker*' 2>/dev/null",
    "find ~/srv -maxdepth 2 -type d 2>/dev/null",
    "which nginx caddy traefik 2>&1",
    "systemctl list-units --type=service --state=running 2>&1 | grep -iE 'nginx|caddy|traefik|docker' ",
    "ls -la /etc/nginx 2>&1 | head -20",
    "ls -la /etc/nginx/sites-enabled 2>&1",
    "cat /etc/nginx/sites-enabled/* 2>&1 | head -150",
    "curl -s -o /dev/null -w 'host80 http_code=%{http_code}\\n' http://localhost:80/ 2>&1",
    "curl -s -o /dev/null -w 'host8080 http_code=%{http_code}\\n' http://localhost:8080/ 2>&1",
    "docker inspect backend-app-1 --format '{{json .NetworkSettings.Networks}}' 2>&1",
    "docker inspect frontend-app-1 --format '{{json .NetworkSettings.Networks}}' 2>&1",
    "docker inspect backend-app-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' 2>&1",
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
