# RTPS deployment notes

This repository is deployed from GitHub to a VPS by GitHub Actions.

## Workflow

1. Work locally in a clone of `git@github.com:Tal-Rash/rtps.git`.
2. Commit and push changes to GitHub.
3. After changes reach `main`, GitHub Actions runs `.github/workflows/deploy.yml`.
4. The workflow connects to the VPS over SSH.
5. The VPS updates `/opt/rtps` from `origin/main`.
6. Runtime data is restored after the code update.
7. The app services are restarted and nginx is reloaded.

## Local setup

Each PC that works with this repo needs:

- Git for Windows
- OpenSSH
- an SSH key added to GitHub
- Codex or another editor/agent
- a local clone:

```powershell
git clone git@github.com:Tal-Rash/rtps.git
```

Recommended Git config:

```powershell
git config --global user.name "Tal-Rash"
git config --global user.email "shvarchkovsergey@gmail.com"
```

## GitHub

Repository:

```text
Tal-Rash/rtps
```

Deployment workflow:

```text
.github/workflows/deploy.yml
```

Required GitHub Actions secrets:

```text
VPS_HOST
VPS_PORT
VPS_USER
VPS_SSH_KEY
```

Current VPS values:

```text
VPS_HOST=132.243.214.167
VPS_PORT=22
VPS_USER=root
```

`VPS_SSH_KEY` is the private SSH key used by GitHub Actions to connect to the VPS.
Do not commit private keys to the repository.

## VPS

SSH target:

```text
root@132.243.214.167 -p 22
```

Repository path:

```text
/opt/rtps
```

Services restarted by deploy:

```text
rtps.service
grafik-ppr.service
spravochnik.service
zamer-kp.service
```

The service list lives in:

```text
deploy/services.txt
```

Service unit files in `deploy/*.service` are copied to `/etc/systemd/system/` during deploy before the restart step.

nginx is used as the reverse proxy and is reloaded after deployment.

## Persistent data

The deployment workflow intentionally preserves runtime data before resetting the code to `origin/main`.

Preserved paths:

```text
base/common_database.db
data
web_main/data
web_spravochnik/data
```

These files and directories may appear as modified or untracked on the VPS after deployment. That is expected because they are runtime data, not code to overwrite on each deploy.

## Quick checks

Check GitHub SSH from a local PC:

```powershell
ssh -T git@github.com
```

Check VPS SSH:

```powershell
ssh rtps-vps
```

Check local repo state:

```powershell
git status --short --branch
git pull --ff-only
git push --dry-run
```

Check VPS state:

```bash
cd /opt/rtps
git status --short --branch
systemctl is-active rtps.service grafik-ppr.service spravochnik.service nginx.service
```

Check the site:

```powershell
curl.exe -i http://yrtps.ru/
```

Expected root response is a redirect to login, for example `303 See Other`.

## Context for Codex

When starting a fresh Codex session on another PC, use this short prompt:

```text
Работаем с репозиторием git@github.com:Tal-Rash/rtps.git.
Локальная работа идет через Git, деплой настроен через GitHub Actions.
VPS: root@132.243.214.167:22, репозиторий на сервере в /opt/rtps.
Runtime data сохраняется между деплоями: base/common_database.db, data, web_main/data, web_spravochnik/data.
Перед изменениями проверь DEPLOYMENT.md и .github/workflows/deploy.yml.
```
