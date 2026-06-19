# Command Reference

## Scan

```bash
supargus scan --identity workspace/identity.example.json --output-dir workspace --watchdog --limit 10
supargus scan --identity workspace/identity.sgvault --output-dir workspace --watchdog --limit 10
```

## Broker Radar

```bash
supargus brokers find --identity workspace/identity.example.json --output workspace/broker_matches.json --html workspace/broker_matches.html
supargus brokers validate
supargus brokers list
```

## Takedown Requests

```bash
supargus takedown prepare \
  --identity workspace/identity.example.json \
  --matches workspace/broker_matches.json \
  --output-dir workspace/requests
```

## Email Preview and Send

Always preview before sending:

```bash
supargus mail preview --requests workspace/requests/requests.json
supargus mail send --requests workspace/requests/requests.json --smtp-config workspace/smtp.gmail.json --yes
```

## Manual Form Queue

```bash
supargus forms build --requests workspace/requests/requests.json --output workspace/forms/forms.json
supargus forms list --queue workspace/forms/forms.json
supargus forms update fastpeoplesearch submitted --queue workspace/forms/forms.json --notes "Submitted through website form"
```

## Custom Removals

Use this for URLs or sites outside the default broker registry.

```bash
supargus custom add https://example.com/profile/jane --queue workspace/custom/custom.json --reason "personal data exposed"
supargus custom list --queue workspace/custom/custom.json
supargus custom prepare --queue workspace/custom/custom.json --identity workspace/identity.example.json --output-dir workspace/custom/requests
supargus custom update custom_1234567890 submitted --queue workspace/custom/custom.json --notes "Submitted through contact form"
```

## Compliance Tracker

```bash
supargus track import --requests workspace/requests/requests.json --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json
supargus track update fastpeoplesearch submitted --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json --due
supargus track followup --tracker workspace/tracker.json --output-dir workspace/followups
```

Preview follow-up drafts:

```bash
supargus mail preview --requests workspace/followups/requests.json
```

## Recurring Scan Monitor

```bash
supargus monitor snapshot --matches workspace/broker_matches.json --history-dir workspace/history
supargus monitor scan --identity workspace/identity.sgvault --output-dir workspace --history-dir workspace/history --limit 10
supargus monitor diff --current workspace/broker_matches.json --history-dir workspace/history --output workspace/monitor_diff.json
```

`monitor scan` writes a fresh `broker_matches.json`, compares it with the latest snapshot when one exists, writes `monitor_diff.json`, and then saves the new snapshot.

## Local Watchdog

```bash
supargus watchdog scan --output workspace/watchdog.json --html workspace/watchdog.html
```

## Evidence Bundle

```bash
supargus export bundle --workspace workspace --output workspace/supargus_evidence_bundle.zip
```

The bundle includes `manifest.json` with file sizes and SHA-256 hashes.

## One-Command Workflow

```bash
supargus config init
supargus workflow run --config supargus.config.json
```

The workflow config controls identity path, workspace, history, tracker, request directories, broker limit, watchdog scans, follow-up generation, form queue generation, and bundle export.

## Scheduling

```bash
supargus schedule print --config supargus.config.json --time 09:00
```

This prints Windows Task Scheduler and cron examples. Supargus does not install scheduled tasks without you copying/running the command yourself.

## Desktop Shortcuts

Windows shortcut helper:

```powershell
supargus shortcut install --workspace workspace
supargus shortcut install --workspace workspace --no-desktop --start-menu
```
