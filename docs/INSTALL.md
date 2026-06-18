# Install and Setup

## Install

```bash
git clone https://github.com/lachydotmcg/supargus.git
cd supargus
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Windows PowerShell:

```powershell
git clone https://github.com/lachydotmcg/supargus.git
cd supargus
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## Start the Desktop App

```bash
supargus app --workspace workspace
```

On Windows installs:

```powershell
supargus-app
```

## Create an Identity File

```bash
supargus init workspace/identity.example.json
```

Edit the file with your real details. Keep it private and do not commit it.

## Windows Vault

On Windows, seal your identity file with current-user DPAPI encryption:

```powershell
supargus vault status
supargus vault seal workspace\identity.example.json workspace\identity.sgvault --delete-plaintext
```

`--delete-plaintext` performs a best-effort overwrite and remove of the source file after sealing. Keep backups carefully; a DPAPI vault is tied to the Windows user account that created it.

## Gmail App Password Setup

Google recommends Sign in with Google/OAuth where possible. For the local MVP, Supargus supports Gmail app-password SMTP for accounts with 2-Step Verification enabled.

```bash
supargus mail setup-gmail \
  --email you@gmail.com \
  --app-password "xxxx xxxx xxxx xxxx" \
  --output workspace/smtp.gmail.json
```

Keep `workspace/smtp.gmail.json` private. Revoke the app password in your Google Account if it is exposed.

## Fallback Web Console

The desktop app is the primary experience. A local web console is still available for development and remote/headless environments:

```bash
supargus web --workspace workspace --host 127.0.0.1 --port 8765
```
