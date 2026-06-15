# RTPS setup on a new PC

Use this checklist when setting up another computer for Codex work with RTPS.

## 1. Install tools

Install:

- Git for Windows
- Codex

After installing Git, open a new PowerShell window.

## 2. Create an SSH key

Run:

```powershell
ssh-keygen -t ed25519 -C "Tal-Rash rtps new pc"
```

Press Enter for the default file path.

## 3. Add the SSH key to GitHub

Show the public key:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copy the full line that starts with:

```text
ssh-ed25519
```

Add it in GitHub:

```text
GitHub -> Settings -> SSH and GPG keys -> New SSH key
```

## 4. Check GitHub SSH access

Run:

```powershell
ssh -T git@github.com
```

Expected result:

```text
Hi Tal-Rash! You've successfully authenticated
```

## 5. Clone the repository

Run:

```powershell
cd $env:USERPROFILE\Documents
git clone git@github.com:Tal-Rash/rtps.git
cd rtps
```

Check:

```powershell
git status --short --branch
```

Expected:

```text
## main...origin/main
```

## 6. Start work

Run:

```powershell
.\start-codex.bat
```

Or double-click:

```text
Documents\rtps\start-codex.bat
```

The script will:

1. open the `rtps` repository folder;
2. run `git pull --ff-only`;
3. start Codex in this project.

## 7. Prompt for Codex

When Codex opens on the new PC, send:

```text
Работаем с репозиторием git@github.com:Tal-Rash/rtps.git.
Прочитай DEPLOYMENT.md и NEW_PC_SETUP.md.
Деплой настроен через GitHub Actions на VPS root@132.243.214.167:22.
После изменений по команде "запуш" делай git status, git add, git commit, git push и проверяй GitHub Actions deploy.
```

## Daily use

Usually you only need to run:

```powershell
.\start-codex.bat
```

Then work with Codex normally.

When changes are ready, tell Codex:

```text
запуш
```
