# Supargus

Local-first privacy watchdog.

Your data is working a second job. Supargus helps you find where it is exposed, prepare takedown requests yourself, track who responds, and inspect your own machine for hidden participation in the data economy.

Think: Incogni-style workflow, but transparent, local, user-controlled, and built for people who want receipts.

> Supargus does not promise to erase you from the internet. It gives you evidence, tools, reminders, and control.

## What It Does

Supargus has two jobs:

1. Find public exposure tied to your identity.
2. Watch your local machine for privacy risks you did not knowingly install.

It is designed as both a CLI and a local app.

```bash
supargus init
supargus scan --identity workspace/identity.example.json --output-dir workspace --watchdog
supargus brokers find --identity workspace/identity.example.json
supargus takedown prepare --identity workspace/identity.example.json --matches workspace/broker_matches.json
supargus mail preview
supargus track import --requests workspace/requests/requests.json --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json
supargus watchdog scan
supargus app --workspace workspace
```

## Quick Start

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

Create a private identity file:

```bash
supargus init workspace/identity.example.json
```

Edit that file with your real details, then run a local scan:

```bash
supargus scan --identity workspace/identity.example.json --output-dir workspace --watchdog --limit 10
```

Prepare takedown drafts:

```bash
supargus takedown prepare \
  --identity workspace/identity.example.json \
  --matches workspace/broker_matches.json \
  --output-dir workspace/requests
```

Preview the request queue:

```bash
supargus mail preview --requests workspace/requests/requests.json
```

Track follow-ups:

```bash
supargus track import --requests workspace/requests/requests.json --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json
supargus track update fastpeoplesearch submitted --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json --due
```

Open the local dashboard:

```bash
supargus app --workspace workspace
```

## Why This Exists

Data brokers, people-search sites, enrichment providers, lead databases, breach mirrors, scraper networks, and residential proxy ecosystems all profit from ordinary people being easy to find, classify, contact, route through, or sell to.

Commercial removal services can be useful, but they require trust. You often hand over the exact identifiers you want protected: legal name, aliases, emails, phone numbers, addresses, relatives, and authorization to contact brokers for you.

Supargus takes the opposite stance:

- keep your identity profile local
- show evidence before action
- generate requests you can inspect
- send from accounts you control
- track every broker response
- re-check later when data reappears
- make cloud AI optional, never required

## The Promise

Supargus is not magic. It is a privacy workbench.

Some brokers are legally required to respond to valid privacy requests. Others may delay, deny, ignore, relist, or ask for more verification. Some sites are not brokers at all, but mirrors, search results, public records, forum posts, or scraped archives.

Supargus helps you separate those cases and keep pressure on them with a paper trail.

## Core Modules

| Module | Purpose |
| --- | --- |
| Identity Vault | Stores your local search profile: names, aliases, emails, phones, addresses, usernames, and jurisdiction. |
| Broker Radar | Searches known data broker and people-search sites for likely matches. |
| Evidence Locker | Saves URLs, match fields, confidence scores, timestamps, screenshots, and page extracts. |
| Takedown Studio | Generates broker-specific opt-out, deletion, CCPA, GDPR, and objection requests. |
| Mail Runner | Sends reviewed requests through SMTP, Gmail, or another local email account you control. |
| Compliance Tracker | Tracks sent requests, confirmations, denials, silence, reminders, and reappearance. |
| Local Watchdog | Scans your machine for proxy SDKs, suspicious network settings, browser extensions, startup entries, local listeners, and risky certificates. |
| Report Builder | Produces local HTML, JSON, and evidence bundles. |

## Local Watchdog

The watchdog looks for signs that your machine may be leaking, routing, or monetizing traffic without your full awareness.

Planned checks:

- residential proxy and bandwidth-sharing app signatures
- suspicious background services
- startup entries and scheduled tasks
- browser extensions with broad host permissions
- unexpected system proxy settings
- `HTTP_PROXY`, `HTTPS_PROXY`, and similar environment variables
- unknown listening ports
- recently added root certificates
- VPN, proxy, tunnel, and packet-capture processes
- local DNS or hosts-file tampering

The goal is not to accuse every network tool. The goal is to flag surprises and explain why they matter.

## Broker Radar

Broker Radar uses a local registry of broker profiles:

```yaml
id: example_people_search
name: Example People Search
type: people_search
regions: ["US"]
search:
  method: browser
  url: "https://example.com/search?name={name}&state={state}"
opt_out:
  url: "https://example.com/opt-out"
  method: form
  requires:
    - profile_url
    - email
    - verification_link
notes:
  - "May require email verification."
  - "Re-check after 30 days."
```

Every broker entry can define:

- how to search
- what counts as a match
- where the opt-out process starts
- what information is required
- what jurisdictional language applies
- how long to wait before follow-up
- whether manual review is required

## Takedown Studio

Supargus prepares requests. You approve them.

Request modes:

- opt-out
- delete my personal information
- do not sell or share
- restrict processing
- object to processing
- access request
- correction request
- appeal or follow-up

Example generated request:

```text
Subject: Privacy request - remove my personal information

Hello,

I am requesting removal of my personal information from your service.

Profile URL:
https://example.com/profile/...

Identifiers to remove:
- Name: ...
- Email: ...
- Phone: ...
- Address: ...

Please confirm once this profile has been removed and my information is no
longer sold, shared, published, or made available through your service.
```

## Email Automation

Yes, Supargus can send emails automatically through an account you control.

Supported sender modes:

- SMTP
- Gmail app password
- Gmail OAuth
- custom mail provider
- draft-only mode

The default should be draft-first:

```bash
supargus takedown prepare --broker example_people_search
supargus mail preview
supargus mail send --review
```

For Gmail, app passwords can work when 2-Step Verification is enabled, but Google recommends Sign in with Google where possible. OAuth is the better long-term path for an app.

Supargus should never silently blast legal/privacy requests. It should show what will be sent, to whom, and why.

## Cloud AI Boundary

Supargus should not require Gemini, OpenAI, Claude, or any cloud AI provider to run.

Default mode:

- direct broker checks
- local parsing
- rules-based matching
- local report generation
- local request templates

Optional AI modes:

- summarize evidence
- classify fuzzy matches
- draft nicer request language
- explain broker responses

Why optional?

Because privacy tools should not casually send your identity profile, broker matches, addresses, emails, or takedown history to a third-party model provider. If cloud AI is enabled, Supargus should make the boundary obvious:

- show what data will be sent
- allow redaction
- support paid/API modes with stronger data terms where available
- support local models later
- let users disable all AI calls globally

```bash
supargus config set ai.enabled false
supargus config set ai.provider local
supargus scan --no-ai
```

## Local App

The CLI should come first. The app makes it humane.

The current MVP includes a small local dashboard:

```bash
supargus app --workspace workspace --host 127.0.0.1 --port 8765
```

Planned app views:

- Exposure Map
- Broker Matches
- Removal Requests
- Needs Review
- Sent Mail
- Follow-Up Queue
- Reappeared Profiles
- Local Watchdog Findings
- Evidence Bundle

All data stays on your machine unless you explicitly send a request or enable an external provider.

## Example Workflow

```bash
# 1. Create a private local identity profile
supargus init workspace/identity.example.json

# 2. Scan brokers and public sources
supargus brokers find --identity workspace/identity.example.json --output workspace/broker_matches.json

# 3. Review matches
Review workspace/broker_matches.json or the generated HTML report.

# 4. Prepare takedown requests
supargus takedown prepare --identity workspace/identity.example.json --matches workspace/broker_matches.json --output-dir workspace/requests

# 5. Send reviewed requests from your own mailbox
supargus mail preview --requests workspace/requests/requests.json
supargus mail send --requests workspace/requests/requests.json --yes

# 6. Track follow-ups
supargus track import --requests workspace/requests/requests.json --tracker workspace/tracker.json
supargus track list --tracker workspace/tracker.json --due

# 7. Re-check later by running the same scan again
supargus scan --identity workspace/identity.example.json --output-dir workspace --watchdog

# 8. Scan your own machine
supargus watchdog scan
```

## What Supargus Will Not Do

Supargus will not:

- guarantee removal
- bypass CAPTCHAs
- break broker terms or access controls
- impersonate lawyers
- submit requests without your approval
- hide what it sends
- sell, upload, or centralize your identity profile

## Roadmap

### Phase 1: CLI MVP

- [x] local identity profile
- [x] broker registry format
- [x] 10 starter broker detectors
- [x] evidence capture
- [x] HTML/JSON reports
- [x] request template generator
- [x] SMTP preview/send support
- [x] compliance tracker
- [x] Windows-first watchdog scan
- [ ] encrypted vault
- [ ] 20+ high-signal broker detectors

### Phase 2: Local App

- [x] tiny standard-library local dashboard
- [ ] FastAPI backend
- review queue
- request status tracker
- scheduled re-scans
- evidence screenshots
- Gmail OAuth integration

### Phase 3: Power Features

- local LLM support
- browser automation adapters
- broker plugin system
- jurisdiction-aware request packs
- reappearance detection
- family/household profiles
- MCP server mode

## Philosophy

The privacy industry often asks you to solve data exposure by creating another account, uploading more personal information, and trusting another intermediary.

Supargus is built around a simpler idea:

> Your data should not need a middleman to come home.

Run it locally. See the evidence. Send the requests yourself. Keep the receipts.

## Status

Supargus is an early MVP successor to Argus.

Argus shows you the footprint.

Supargus helps you push back.
