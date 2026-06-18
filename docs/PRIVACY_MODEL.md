# Privacy Model

Supargus is built around local control.

## What Stays Local

- identity profile
- broker scan outputs
- takedown drafts
- SMTP/Gmail app-password config
- compliance tracker
- manual form queue
- follow-up drafts
- evidence bundles
- watchdog results

## What Leaves Your Machine

Only actions you choose to run can transmit data:

- sending email requests through your own mailbox
- opening/submitting broker opt-out forms
- enabling any future cloud AI provider
- using optional browser automation against third-party sites

Supargus should never silently blast legal/privacy requests. It should show what will be sent, to whom, and why.

## Cloud AI Boundary

Supargus does not require Gemini, OpenAI, Claude, or any cloud AI provider to run.

Default mode:

- direct broker checks
- local parsing
- rules-based matching
- local report generation
- local request templates

Optional AI modes may eventually help summarize evidence, classify fuzzy matches, draft clearer request language, or explain broker responses. If enabled, Supargus should make the boundary obvious: show what data will be sent, allow redaction, support local models where possible, and let users disable AI calls globally.

## Residential Proxy Watchdog

Residential proxy networks are valuable because they route traffic through consumer-looking IP space. Sometimes that is explicit. Sometimes it is buried in SDKs, extensions, bundled software, or "earn from your bandwidth" apps.

The watchdog looks for signals such as:

- proxy environment variables
- Windows proxy settings and proxy auto-config URLs
- suspicious local listeners
- VPN, tunnel, packet-capture, proxy-manager, and bandwidth-sharing process names
- browser extensions with broad network permissions
- extension metadata matching known proxy/bandwidth terms
- startup registry entries and scheduled tasks
- installed app folders matching proxy/bandwidth-sharing signatures

This is not about claiming every proxy company is malicious. It is about giving people a local way to ask: "Is my computer routing, monetizing, or leaking traffic in a way I did not knowingly approve?"

Public context:

- Tesonet's portfolio lists Surfshark and Oxylabs: <https://tesonet.com/portfolio/>
- Surfshark says Incogni was created within Surfshark and is now a standalone product: <https://surfshark.com/incogni>
- Oxylabs markets residential proxy products and large-scale web data collection tooling: <https://oxylabs.io/products/residential-proxy-pool>

That overlap is why Supargus is local-first.

## What Supargus Will Not Do

Supargus will not:

- guarantee removal
- bypass CAPTCHAs
- break broker terms or access controls
- impersonate lawyers
- submit requests without review
- hide what it sends
- sell, upload, or centralize your identity profile
