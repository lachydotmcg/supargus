# Supargus

```text
  ____  _   _ ____   _    ____   ____ _   _ ____
 / ___|| | | |  _ \ / \  |  _ \ / ___| | | / ___|
 \___ \| | | | |_) / _ \ | |_) | |  _| | | \___ \
  ___) | |_| |  __/ ___ \|  _ <| |_| | |_| |___) |
 |____/ \___/|_| /_/   \_\_| \_\\____|\___/|____/

        LOCAL REMOVAL OPS // BROKER RADAR // PROXY WATCHDOG
```

Supargus is a free, open-source, local-first privacy removal console.

Think Incogni-style removal workflows, but run from your own machine: a native desktop app on your taskbar, a CLI for power users, local identity storage, reviewed email sending, manual opt-out form queues, recurring scans, evidence bundles, and a watchdog for proxy/bandwidth-sharing software you may not know is installed.

No account. No subscription. No uploading your identity profile to another middleman.

## Why It Exists

Your personal data is not just "out there." It is searched, enriched, sold, reused, and sometimes routed through infrastructure that ordinary users never knowingly opted into.

Commercial removal services can be useful, but they ask for the exact data you are trying to protect: legal name, aliases, emails, phone numbers, addresses, relatives, and permission to contact brokers for you.

Supargus takes the opposite stance:

- keep the identity profile local
- show evidence before action
- generate requests you can inspect
- send from accounts you control
- track every broker response
- re-check when data reappears
- scan your own machine for proxy and bandwidth-sharing signals
- make cloud AI optional, never required

## The App

`supargus app` opens a real desktop application window, not a localhost browser tab.

Current desktop views:

- Command Center
- Broker Radar
- Local Watchdog
- Monitor Changes
- Compliance Tracker
- Form Queue with open/copy/mark-submitted controls
- Run Log

From the app you can run broker scans, build takedown drafts, preview/send reviewed email requests through SMTP or Gmail app passwords, build manual opt-out form queues, import tracker records, generate follow-ups, export evidence bundles, and run the local watchdog.

## Quick Start

```bash
git clone https://github.com/lachydotmcg/supargus.git
cd supargus
python -m venv .venv
source .venv/bin/activate
pip install -e .
supargus init workspace/identity.example.json
supargus app --workspace workspace
```

Windows PowerShell:

```powershell
git clone https://github.com/lachydotmcg/supargus.git
cd supargus
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
supargus init workspace\identity.example.json
supargus app --workspace workspace
```

On Windows installs, `supargus-app` is also exposed as a GUI launcher.

## Core Capabilities

| Area | What Supargus Does |
| --- | --- |
| Identity Vault | Stores your names, aliases, emails, phones, addresses, usernames, and jurisdiction locally. |
| Broker Radar | Checks known data broker and people-search sites for likely exposure. |
| Takedown Studio | Generates opt-out, deletion, do-not-sell/share, and follow-up request drafts. |
| Mail Runner | Previews and sends reviewed requests through SMTP or Gmail app-password config. |
| Form Queue | Tracks brokers that require manual web forms, with open/copy/mark-submitted controls. |
| Custom Removals | Adds arbitrary URLs outside the broker registry and prepares local removal drafts. |
| Compliance Tracker | Tracks submitted, waiting, confirmed, denied, due, and follow-up states. |
| Monitor | Diffs recurring scans for new matches, clears, and reappearances. |
| Evidence Bundle | Exports reports, drafts, tracker state, form queue, and hashes into a portable zip. |
| Local Watchdog | Looks for proxy settings, bandwidth-sharing apps, broad browser extensions, listeners, startup entries, and suspicious installed-app signatures. |

## Residential Proxy Angle

Residential proxy networks are valuable because they route traffic through consumer-looking IP space. Sometimes that is explicit. Sometimes it is buried in SDKs, extensions, bundled software, or "earn from your bandwidth" apps.

Supargus treats that as a consent and visibility problem.

Public context:

- Tesonet's portfolio lists Surfshark and Oxylabs: <https://tesonet.com/portfolio/>
- Surfshark says Incogni was created within Surfshark and is now a standalone product: <https://surfshark.com/incogni>
- Oxylabs markets residential proxy products and large-scale web data collection tooling: <https://oxylabs.io/products/residential-proxy-pool>

That overlap is exactly why Supargus is local-first. A privacy tool should not require you to upload more private identifiers to another opaque intermediary before you can begin cleaning up exposure.

## Docs

- [Install and Setup](docs/INSTALL.md)
- [Command Reference](docs/COMMANDS.md)
- [Privacy Model](docs/PRIVACY_MODEL.md)
- [Roadmap](docs/ROADMAP.md)

## Boundaries

Supargus will not guarantee removal, bypass CAPTCHAs, break broker terms, impersonate lawyers, silently submit requests, sell your data, or centralize your identity profile.

It gives you evidence, tools, reminders, and receipts. You stay in control.

## Status

Supargus is an early MVP successor to Argus.

Argus shows you the footprint.

Supargus helps you push back.
