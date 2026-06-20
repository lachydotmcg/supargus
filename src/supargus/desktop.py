"""Native desktop application for Supargus."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import webbrowser
from importlib.resources import files
from pathlib import Path
from typing import Any

from .app import build_state, run_action
from .custom import add_custom_target, load_custom_targets, prepare_custom_requests, update_custom_status
from .forms import FormTask, load_form_queue, update_form_status
from .identity import identity_from_dict, load_identity, sample_identity, save_identity
from .mailer import gmail_smtp_config, save_smtp_config

try:  # Keep imports optional so headless test environments can still import the package.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - depends on local Python GUI support.
    tk = None
    ttk = None
    filedialog = None
    messagebox = None


GUIDE_STEPS = (
    ("identity", "1", "Set up your identity", "Enter the name, emails, usernames, phone numbers, and address Supargus should search for."),
    ("scan", "2", "Run the dashboard privacy check", "Go to Dashboard and run the full privacy check so Supargus can build the first report."),
    ("review", "3", "Read what was found", "Use the plain-English score report to see why the score changed and what needs attention."),
    ("action", "4", "Take action", "Use Data Brokers to see the sites, then open Removals to send email requests, copy text, or finish forms."),
)


DESKTOP_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("workflow", "Run privacy check", "Scan exposure, create drafts, update tracker, and export receipts."),
    ("broker_scan", "Scan data brokers", "Check the broker registry for likely exposure."),
    ("watchdog", "Scan this PC", "Look for proxy, extension, startup, and bandwidth-sharing signals."),
    ("prepare_requests", "Prepare removals", "Create readable takedown drafts from broker matches."),
    ("form_queue", "Build form queue", "Collect brokers that need manual opt-out forms."),
    ("review_queue", "Build review queue", "Create approve/skip records for generated requests."),
    ("action_plan", "Build action plan", "Turn scan, request, tracker, and form outputs into next steps."),
    ("safe_actions", "Automate safe steps", "Prepare drafts, form queue, tracker, follow-ups, action plan, and receipts without sending."),
    ("mail_preview", "Preview emails", "Review request emails before anything is sent."),
    ("mail_send", "Send reviewed emails", "Send approved requests through your SMTP or Gmail app password config."),
    ("tracker_import", "Import tracker", "Track requests, status, and follow-up dates."),
    ("followups", "Generate follow-ups", "Create follow-up drafts for pending requests."),
    ("bundle", "Export receipts", "Zip evidence, reports, drafts, and hashes."),
    ("guide_take_action", "Guide: take action", "Prepare requests, tracker records, form tasks, and receipts from current results."),
    ("validate", "Validate registry", "Check broker adapters before scanning."),
)


COLORS = {
    "bg": "#f3f6fb",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "nav": "#ffffff",
    "line": "#e4e9f2",
    "line_strong": "#ccd6e2",
    "ink": "#0b1622",
    "muted": "#64748b",
    "soft": "#edf2f8",
    "navy": "#0b1622",
    "blue": "#132235",
    "blue_dark": "#0b1622",
    "yellow": "#f6b40b",
    "yellow_dark": "#a86500",
    "yellow_soft": "#fff5cf",
    "green": "#11854d",
    "green_soft": "#e9f8ef",
    "red": "#b42318",
    "red_soft": "#fff0ed",
    "orange": "#d97706",
    "orange_soft": "#fff3df",
    "shadow": "#d8e0ea",
}


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lachydotmcg.supargus.desktop")
    except Exception:
        return


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for suffix in ("B", "KB", "MB", "GB"):
        if size < 1024 or suffix == "GB":
            return f"{size:.1f} {suffix}" if suffix != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _asset_path(name: str) -> str:
    try:
        return str(files("supargus").joinpath("assets", name))
    except Exception:
        return str(Path.cwd() / name)


def _privacy_score(summary: dict[str, Any]) -> int:
    score = 100
    score -= min(32, int(summary.get("possible_matches", 0) or 0) * 4)
    score -= min(18, int(summary.get("request_only", 0) or 0) * 2)
    score -= min(24, int(summary.get("watchdog_findings", 0) or 0) * 6)
    score -= min(18, int(summary.get("scan_changes", 0) or 0) * 5)
    score += min(10, int(summary.get("request_drafts", 0) or 0) * 2)
    return max(0, min(100, score))


def _score_label(score: int) -> tuple[str, str]:
    if score >= 85:
        return "Protected", COLORS["green"]
    if score >= 65:
        return "Needs review", COLORS["yellow"]
    return "Action needed", COLORS["red"]


def _summary_int(summary: dict[str, Any], key: str) -> int:
    return int(summary.get(key, 0) or 0)


def _score_findings(summary: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    possible = _summary_int(summary, "possible_matches")
    request_only = _summary_int(summary, "request_only")
    watchdog = _summary_int(summary, "watchdog_findings")
    changes = _summary_int(summary, "scan_changes")
    forms = _summary_int(summary, "form_tasks")
    pending = _summary_int(summary, "review_pending")
    drafts = _summary_int(summary, "request_drafts")

    if possible:
        findings.append(f"{possible} likely public broker hit{'s' if possible != 1 else ''} matched your profile.")
    if request_only:
        findings.append(f"{request_only} broker{'s' if request_only != 1 else ''} could not be searched directly and need request-only cleanup.")
    if watchdog:
        findings.append(f"{watchdog} local PC finding{'s' if watchdog != 1 else ''} need review.")
    if forms:
        findings.append(f"{forms} manual opt-out form{'s' if forms != 1 else ''} are waiting for you.")
    if pending:
        findings.append(f"{pending} email draft{'s' if pending != 1 else ''} need approval before sending.")
    if changes:
        findings.append(f"{changes} scan change{'s' if changes != 1 else ''} appeared since the last baseline.")
    if drafts and not pending and not forms:
        findings.append(f"{drafts} removal draft{'s' if drafts != 1 else ''} exist locally.")
    if not findings:
        findings.append("No actionable exposure has been found yet. Run a full privacy check to build the first report.")
    return findings


def _score_next_actions(summary: dict[str, Any], exists: dict[str, Any] | None = None) -> list[str]:
    exists = exists or {}
    actions: list[str] = []
    possible = _summary_int(summary, "possible_matches")
    request_only = _summary_int(summary, "request_only")
    drafts = _summary_int(summary, "request_drafts")
    forms = _summary_int(summary, "form_tasks")
    pending = _summary_int(summary, "review_pending")
    approved = _summary_int(summary, "review_approved")
    watchdog = _summary_int(summary, "watchdog_findings")

    if possible or request_only:
        actions.append("Open Data Brokers to see the exact sites Supargus found or could not verify.")
    if forms:
        actions.append("Use Open website/form or Copy request text for each broker that needs a manual form.")
    if pending:
        actions.append("Approve only the email drafts you trust, then send reviewed emails with your Gmail app password.")
    elif drafts and not exists.get("review_queue"):
        actions.append("Build the Review Queue so each removal draft can be approved or skipped.")
    if possible and not drafts:
        actions.append("Prepare removal drafts for the public hits Supargus found.")
    if request_only and not drafts:
        actions.append("Prepare request-only opt-outs for brokers that cannot be directly searched.")
    if watchdog:
        actions.append("Open This PC and review the local proxy or bandwidth-sharing findings.")
    if approved:
        actions.append("Send approved email requests when your SMTP/Gmail config is ready.")
    if not exists.get("action_plan"):
        actions.append("Build the Action Plan to turn findings into a prioritized queue.")
    if not actions:
        actions.append("Re-run the privacy check later to catch broker reappearances.")
    return actions


def _plain_english_report(summary: dict[str, Any], exists: dict[str, Any] | None = None) -> str:
    score = _privacy_score(summary)
    label, _color = _score_label(score)
    lines = [
        f"Privacy score: {score} ({label})",
        "",
        "Why this score changed:",
    ]
    for item in _score_findings(summary):
        lines.append(f"- {item}")
    lines.extend(["", "What to do next:"])
    for idx, item in enumerate(_score_next_actions(summary, exists), 1):
        lines.append(f"{idx}. {item}")
    lines.extend(
        [
            "",
            "What Supargus proved:",
            "Public people-search hits are only marked when reachable pages return matching identifiers. Private or blocked broker databases are treated as request-only because Supargus cannot honestly verify them from your machine.",
        ]
    )
    return "\n".join(lines)


def _task_label(status: str) -> str:
    labels = {
        "needs_form": "Open website form",
        "submitted": "Submitted",
        "confirmed": "Removed",
        "waiting": "Waiting for broker",
    }
    return labels.get(status, status.replace("_", " ").title())


def _review_status_label(status: str) -> str:
    labels = {
        "pending": "Needs your approval",
        "approved": "Approved to send",
        "skipped": "Skipped",
    }
    return labels.get(status, status.replace("_", " ").title())


def _delivery_label(item: dict[str, Any]) -> str:
    if item.get("to_email"):
        return "Email request"
    if item.get("opt_out_url"):
        return "Website form"
    return str(item.get("delivery") or "Manual review").replace("_", " ").title()


def _broker_user_row(item: dict[str, Any]) -> tuple[str, str, str, str] | None:
    status = str(item.get("status") or "")
    mode = str(item.get("action_mode") or "")
    place = str(item.get("broker_name") or item.get("broker_id") or "Unknown broker")
    open_url = str(item.get("evidence_url") or item.get("search_url") or "")
    matched_fields = [str(value).replace("_", " ") for value in item.get("matched_fields", []) if value]

    if status == "possible_match" or mode == "verified_public":
        fields = ", ".join(matched_fields) if matched_fields else str(item.get("confidence") or "profile details")
        return (
            place,
            f"Possible public profile matched: {fields}",
            "Prepare removal, then review before sending",
            open_url,
        )
    if mode == "request_only" or status in {"fetch_error", "needs_manual_review"}:
        reason = "site blocked direct checking" if item.get("error") else "private or manual database"
        return (
            place,
            f"Could not verify directly: {reason}",
            "Prepare a request-only opt-out",
            open_url,
        )
    if mode == "public_unverified":
        return (
            place,
            "Public search result needs manual review",
            "Open the result and decide whether to request removal",
            open_url,
        )
    return None


def _watchdog_meaning(item: dict[str, Any]) -> str:
    category = str(item.get("category", ""))
    if category == "network":
        return "Your traffic may be routed or exposed in a way you did not expect."
    if category == "browser":
        return "A browser extension may be able to observe or alter browsing activity."
    if category in {"process", "startup", "installed_app"}:
        return "Software on this PC may be proxy, bandwidth-sharing, or data-routing related."
    return "This local privacy signal needs review."


def _watchdog_safe_action(item: dict[str, Any]) -> str:
    category = str(item.get("category", ""))
    if category == "network":
        return "Open Windows proxy settings"
    if category == "browser":
        return "Open browser extensions"
    if category == "startup":
        return "Open Startup Apps"
    if category in {"process", "installed_app"}:
        return "Open Apps settings"
    return "Copy fix instructions"


def _friendly_mode(item: dict[str, Any]) -> str:
    mode = str(item.get("action_mode") or "")
    status = str(item.get("status") or "")
    if mode == "verified_public" or status == "possible_match":
        return "Verified public hit"
    if mode == "request_only" or status in {"needs_manual_review", "fetch_error"}:
        return "Request-only"
    if mode == "public_unverified":
        return "Public search queued"
    if mode == "no_public_match" or status == "no_obvious_match":
        return "No public hit"
    return mode.replace("_", " ").title() if mode else "Review"


def _mode_color(item: dict[str, Any]) -> tuple[str, str]:
    mode = _friendly_mode(item)
    if mode == "Verified public hit":
        return COLORS["green_soft"], COLORS["green"]
    if mode == "Request-only":
        return COLORS["yellow_soft"], COLORS["yellow_dark"]
    if mode == "No public hit":
        return COLORS["soft"], COLORS["muted"]
    return COLORS["orange_soft"], COLORS["orange"]


class SupargusDesktop:
    def __init__(self, root: "tk.Tk", workspace: str | Path) -> None:
        self.root = root
        self.queue: "queue.Queue[tuple[str, str, Any]]" = queue.Queue()
        self.buttons: list["tk.Widget"] = []
        self.nav_buttons: dict[str, "tk.Button"] = {}
        self.pages: dict[str, "tk.Frame"] = {}
        self.form_tasks: list[FormTask] = []
        self.custom_targets: list[Any] = []
        self.action_items: list[dict[str, Any]] = []
        self.review_items: list[dict[str, Any]] = []
        self.watchdog_items: list[dict[str, Any]] = []
        self.broker_items: list[dict[str, Any]] = []
        self.guide_status_labels: dict[str, "tk.Label"] = {}
        self.scan_step_labels: list["tk.Label"] = []
        self.state: dict[str, Any] = {}
        self.current_page = ""
        self.progress_token = 0
        self.progress_step_index = 0

        workspace_path = Path(workspace)
        self.workspace_var = tk.StringVar(value=str(workspace_path))
        self.identity_var = tk.StringVar(value=str(workspace_path / "identity.sgvault"))
        self.config_var = tk.StringVar(value="supargus.config.json")
        self.smtp_var = tk.StringVar(value=str(workspace_path / "smtp.gmail.json"))
        self.limit_var = tk.StringVar(value="10")
        self.custom_url_var = tk.StringVar(value="")
        self.custom_reason_var = tk.StringVar(value="personal data exposed")
        self.status_var = tk.StringVar(value="Ready")
        self.guide_cta_var = tk.StringVar(value="Run full privacy check")
        self.risk_headline_var = tk.StringVar(value="Run a privacy check")
        self.risk_body_var = tk.StringVar(value="Supargus will explain what it found here.")
        self.scan_progress_var = tk.StringVar(value="Ready when you are.")
        self.gmail_email_var = tk.StringVar(value="")
        self.gmail_password_var = tk.StringVar(value="")

        self.metric_vars = {
            "brokers": tk.StringVar(value="0"),
            "matches": tk.StringVar(value="0"),
            "watchdog": tk.StringVar(value="0"),
            "request_only": tk.StringVar(value="0"),
            "public_unverified": tk.StringVar(value="0"),
            "verified": tk.StringVar(value="0"),
            "action_items": tk.StringVar(value="0"),
            "review_pending": tk.StringVar(value="0"),
            "review_approved": tk.StringVar(value="0"),
            "form_tasks": tk.StringVar(value="0"),
            "changes": tk.StringVar(value="0"),
            "requests": tk.StringVar(value="0"),
            "bundle": tk.StringVar(value="0 B"),
            "score": tk.StringVar(value="100"),
            "score_label": tk.StringVar(value="Protected"),
        }

        self.setup_vars = {
            "full_name": tk.StringVar(),
            "aliases": tk.StringVar(),
            "emails": tk.StringVar(),
            "usernames": tk.StringVar(),
            "phones": tk.StringVar(),
            "address": tk.StringVar(),
            "city": tk.StringVar(),
            "region": tk.StringVar(),
            "postal_code": tk.StringVar(),
            "country": tk.StringVar(),
            "jurisdiction": tk.StringVar(),
        }

        self._configure_window()
        self._load_logo()
        self._build_layout()
        self.refresh()
        self._pick_start_page()
        self.root.after(100, self._drain_queue)

    def _configure_window(self) -> None:
        self.root.title("Supargus")
        self.root.geometry("1060x720")
        self.root.minsize(940, 640)
        self.root.configure(bg=COLORS["bg"])

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=30, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#f8fafc", foreground=COLORS["muted"])
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", COLORS["ink"])])

    def _load_logo(self) -> None:
        self.logo_image = None
        self.icon_image = None
        try:
            image = tk.PhotoImage(file=_asset_path("logo.png"))
            logo_factor = max(1, image.width() // 46)
            icon_factor = max(1, image.width() // 128)
            self.logo_image = image.subsample(logo_factor, logo_factor)
            self.icon_image = image.subsample(icon_factor, icon_factor)
            self.root.iconphoto(True, self.icon_image)
        except Exception:
            self.logo_image = None
            self.icon_image = None

    def _build_layout(self) -> None:
        self.shell = tk.Frame(self.root, bg=COLORS["bg"])
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(1, weight=1)

        self._build_topbar()
        self._build_sidebar()

        self.content = tk.Frame(self.shell, bg=COLORS["bg"])
        self.content.grid(row=1, column=1, sticky="nsew", padx=22, pady=18)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self._build_setup_page()
        self._build_home_page()
        self._build_guide_page()
        self._build_cleanup_page()
        self._build_watchdog_page()
        self._build_removals_page()
        self._build_advanced_page()

    def _build_topbar(self) -> None:
        top = tk.Frame(self.shell, bg=COLORS["surface"], height=72, highlightbackground=COLORS["line"], highlightthickness=1)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)
        top.rowconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        brand = tk.Frame(top, bg=COLORS["surface"])
        brand.grid(row=0, column=0, sticky="w", padx=24)
        if self.logo_image:
            tk.Label(brand, image=self.logo_image, bg=COLORS["surface"]).pack(side="left", padx=(0, 10))
        tk.Label(brand, text="Supargus", bg=COLORS["surface"], fg=COLORS["navy"], font=("Segoe UI", 18, "bold")).pack(side="left")

        status = tk.Frame(top, bg=COLORS["surface"])
        status.grid(row=0, column=2, sticky="e", padx=24)
        tk.Label(status, text="Local-first / Review before send", bg=COLORS["surface"], fg=COLORS["blue"], font=("Segoe UI", 9, "bold")).pack(anchor="e")
        tk.Label(status, text="Status", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="e")
        tk.Label(status, textvariable=self.status_var, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10)).pack(anchor="e")

    def _build_sidebar(self) -> None:
        side = tk.Frame(self.shell, bg=COLORS["nav"], width=104, highlightbackground=COLORS["line"], highlightthickness=1)
        side.grid(row=1, column=0, sticky="nsw")
        side.grid_propagate(False)

        items = (
            ("setup", "Setup"),
            ("home", "Dashboard"),
            ("guide", "Guide"),
            ("cleanup", "Data Brokers"),
            ("watchdog", "This PC"),
            ("removals", "Removals"),
            ("advanced", "Advanced"),
        )
        for key, label in items:
            button = tk.Button(
                side,
                text=label,
                command=lambda value=key: self.show_page(value),
                bg=COLORS["nav"],
                fg=COLORS["muted"],
                activebackground=COLORS["yellow_soft"],
                activeforeground=COLORS["blue"],
                relief="flat",
                bd=0,
                padx=8,
                pady=14,
                cursor="hand2",
                font=("Segoe UI", 9, "bold"),
            )
            button.pack(fill="x", padx=8, pady=(10 if key == "home" else 2, 0))
            self.nav_buttons[key] = button

    def _page(self, key: str) -> "tk.Frame":
        """Create a scrollable page container. Returns the inner scrollable frame."""
        outer = tk.Frame(self.content, bg=COLORS["bg"])
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=COLORS["bg"], highlightthickness=0, bd=0)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(canvas, bg=COLORS["bg"])
        inner.columnconfigure(0, weight=1)

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(window_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.pages[key] = outer
        return inner

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            selected = name == key
            button.configure(bg=COLORS["yellow_soft"] if selected else COLORS["nav"], fg=COLORS["blue"] if selected else COLORS["muted"])

    def _card(self, parent: "tk.Widget", row: int, column: int, *, columnspan: int = 1, rowspan: int = 1, padx=(0, 14), pady=(0, 14)) -> "tk.Frame":
        frame = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["line_strong"], highlightthickness=1)
        frame.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky="nsew", padx=padx, pady=pady)
        return frame

    def _button(self, parent: "tk.Widget", text: str, command, *, primary: bool = False, danger: bool = False) -> "tk.Button":
        if primary:
            bg, fg, active = COLORS["blue"], "#ffffff", COLORS["blue_dark"]
        elif danger:
            bg, fg, active = COLORS["red"], "#ffffff", "#8f1d14"
        else:
            bg, fg, active = COLORS["soft"], COLORS["ink"], "#e2e8f0"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=bg,
            padx=18,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        return button

    def _pill(self, parent: "tk.Widget", text: str, *, bg: str, fg: str) -> "tk.Label":
        return tk.Label(parent, text=text, bg=bg, fg=fg, padx=10, pady=4, font=("Segoe UI", 9, "bold"))

    def _metric_tile(self, parent: "tk.Widget", row: int, column: int, label: str, variable: "tk.StringVar", detail: str) -> None:
        tile = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
        tile.grid(row=row, column=column, sticky="nsew", padx=(0, 10), pady=(0, 10))
        tk.Label(tile, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        tk.Label(tile, textvariable=variable, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 21, "bold")).pack(anchor="w", padx=14)
        tk.Label(tile, text=detail, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=160, justify="left").pack(anchor="w", padx=14, pady=(0, 12))

    def _insight_card(self, parent: "tk.Widget", title: str, body: str, mode: str) -> "tk.Frame":
        bg, fg = {
            "verified": (COLORS["green_soft"], COLORS["green"]),
            "request": (COLORS["yellow_soft"], COLORS["yellow_dark"]),
            "local": (COLORS["soft"], COLORS["blue"]),
        }.get(mode, (COLORS["surface_alt"], COLORS["muted"]))
        card = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
        card.columnconfigure(1, weight=1)
        marker = tk.Frame(card, width=6, bg=fg)
        marker.grid(row=0, column=0, rowspan=2, sticky="nsw")
        self._pill(card, mode.upper(), bg=bg, fg=fg).grid(row=0, column=1, sticky="w", padx=14, pady=(12, 4))
        tk.Label(card, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 11, "bold")).grid(row=1, column=1, sticky="w", padx=14)
        tk.Label(card, text=body, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=185, justify="left").grid(row=2, column=1, sticky="w", padx=14, pady=(4, 12))
        return card

    def _identity_exists(self) -> bool:
        """Return True if a usable identity file is present."""
        p = Path(self.identity_var.get())
        if p.exists():
            return True
        # Also accept workspace/identity.json as a fallback
        alt = Path(self.workspace_var.get()) / "identity.json"
        if alt.exists():
            self.identity_var.set(str(alt))
            return True
        return False

    def _pick_start_page(self) -> None:
        if self._identity_exists():
            self.show_page("home")
        else:
            self.show_page("setup")

    def _build_setup_page(self) -> None:
        page = self._page("setup")
        page.columnconfigure(0, weight=1)

        header = tk.Frame(page, bg=COLORS["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(header, text="Create your privacy profile", bg=COLORS["bg"], fg=COLORS["ink"], font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Supargus uses this profile to search for your exposure across people-search sites and data brokers. Nothing is sent anywhere without your review.",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        card = tk.Frame(page, bg=COLORS["surface"], highlightbackground=COLORS["line_strong"], highlightthickness=1)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(1, weight=1)

        fields = [
            ("full_name", "Full name", "Your full legal name"),
            ("aliases", "Aliases", "Other names, maiden names, nicknames, comma-separated"),
            ("emails", "Email addresses", "All email addresses, comma-separated"),
            ("usernames", "Usernames", "Forum handles, social usernames, comma-separated"),
            ("phones", "Phone numbers", "Include country code e.g. +15551234567, comma-separated"),
            ("address", "Street address", "House number and street name"),
            ("city", "City", ""),
            ("region", "State / Province", ""),
            ("postal_code", "Postal code", ""),
            ("country", "Country", "2-letter code e.g. US, AU, GB"),
            ("jurisdiction", "Jurisdiction", "Privacy law that applies, e.g. US-CA, AU, EU-GDPR"),
        ]

        for idx, (key, label, hint) in enumerate(fields):
            tk.Label(card, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(
                row=idx, column=0, sticky="w", padx=22, pady=(14 if idx == 0 else 8, 0)
            )
            entry = tk.Entry(card, textvariable=self.setup_vars[key], relief="solid", bd=1, font=("Segoe UI", 10))
            entry.grid(row=idx, column=1, sticky="ew", padx=(8, 22), pady=(14 if idx == 0 else 8, 0), ipady=6)
            if hint:
                tk.Label(card, text=hint, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=210, justify="left").grid(
                    row=idx, column=2, sticky="w", padx=(0, 22), pady=(14 if idx == 0 else 8, 0)
                )

        buttons = tk.Frame(card, bg=COLORS["surface"])
        buttons.grid(row=len(fields), column=0, columnspan=3, sticky="w", padx=22, pady=18)
        save_btn = self._button(buttons, "Save profile", self._save_setup_profile, primary=True)
        save_btn.pack(side="left", padx=(0, 12))
        self._button(buttons, "Skip for now", lambda: self.show_page("home")).pack(side="left")

        self.setup_status = tk.Label(card, text="", bg=COLORS["surface"], fg=COLORS["green"], font=("Segoe UI", 10))
        self.setup_status.grid(row=len(fields) + 1, column=0, columnspan=3, sticky="w", padx=22, pady=(0, 12))

    def _save_setup_profile(self) -> None:
        def _split(val: str) -> list[str]:
            return [v.strip() for v in val.split(",") if v.strip()]

        from .models import Address

        v = self.setup_vars
        addresses = []
        if v["address"].get().strip() or v["city"].get().strip():
            addresses.append(
                Address(
                    line1=v["address"].get().strip(),
                    city=v["city"].get().strip(),
                    region=v["region"].get().strip(),
                    postal_code=v["postal_code"].get().strip(),
                    country=v["country"].get().strip(),
                )
            )

        data = {
            "full_name": v["full_name"].get().strip(),
            "aliases": _split(v["aliases"].get()),
            "emails": _split(v["emails"].get()),
            "usernames": _split(v["usernames"].get()),
            "phones": _split(v["phones"].get()),
            "addresses": [
                {
                    "line1": a.line1,
                    "city": a.city,
                    "region": a.region,
                    "postal_code": a.postal_code,
                    "country": a.country,
                }
                for a in addresses
            ],
            "jurisdiction": v["jurisdiction"].get().strip(),
        }

        if not data["full_name"]:
            if messagebox:
                messagebox.showerror("Supargus", "Full name is required.")
            return

        try:
            profile = identity_from_dict(data)
            out_path = Path(self.workspace_var.get()) / "identity.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            save_identity(profile, out_path, force=True)
            self.identity_var.set(str(out_path))
            if hasattr(self, "setup_status"):
                self.setup_status.configure(text=f"Saved to {out_path}", fg=COLORS["green"])
            self._log(f"Identity saved to {out_path}")
            self.refresh()
            self.show_page("home")
        except Exception as exc:
            if messagebox:
                messagebox.showerror("Supargus", str(exc))
            self._log(f"Could not save identity:\n{exc}")

    def _build_home_page(self) -> None:
        page = self._page("home")
        page.columnconfigure(0, weight=2)
        page.columnconfigure(1, weight=1)

        header = tk.Frame(page, bg=COLORS["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        tk.Label(header, text="Privacy protection you can actually inspect.", bg=COLORS["bg"], fg=COLORS["ink"], font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Scan public broker pages, prepare request-only removals, and check this PC without handing your identity to another service.",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # Empty state shown when no identity exists.
        self.home_empty = tk.Frame(page, bg=COLORS["bg"])
        self.home_empty.grid(row=1, column=0, columnspan=2, sticky="nsew")
        empty_card = tk.Frame(self.home_empty, bg=COLORS["surface"], highlightbackground=COLORS["line_strong"], highlightthickness=1)
        empty_card.pack(fill="x", pady=(8, 0))
        empty_card.columnconfigure(0, weight=1)
        tk.Label(empty_card, text="Get started", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(
            empty_card,
            text="Create a privacy profile so Supargus knows what to search for. Your data stays on this machine.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=24, pady=(0, 16))
        self._button(empty_card, "Create your privacy profile", lambda: self.show_page("setup"), primary=True).pack(anchor="w", padx=24, pady=(0, 22))

        # Main content hidden until identity exists.
        self.home_main = tk.Frame(page, bg=COLORS["bg"])
        self.home_main.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.home_main.columnconfigure(0, weight=2)
        self.home_main.columnconfigure(1, weight=1)
        self.home_main.rowconfigure(1, weight=1)

        scan_card = self._card(self.home_main, 0, 0, columnspan=2, padx=(0, 0), pady=(0, 14))
        scan_card.columnconfigure(0, weight=1)
        tk.Label(scan_card, text="Start here", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="n", pady=(18, 2))
        tk.Label(scan_card, text="Run a full privacy check", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 18, "bold")).grid(row=1, column=0, sticky="n")
        self.full_check_button = tk.Button(
            scan_card,
            text="Run full privacy check",
            command=lambda: self.run_action("workflow"),
            bg=COLORS["blue"],
            fg="#ffffff",
            activebackground=COLORS["blue_dark"],
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=42,
            pady=18,
            cursor="hand2",
            font=("Segoe UI", 16, "bold"),
        )
        self.full_check_button.grid(row=2, column=0, pady=(12, 10))
        self.buttons.append(self.full_check_button)
        tk.Label(scan_card, textvariable=self.scan_progress_var, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=720, justify="center").grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 12))
        steps = tk.Frame(scan_card, bg=COLORS["surface"])
        steps.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 18))
        for idx, title in enumerate(("Check broker sites", "Prepare removal options", "Scan this PC", "Build report")):
            steps.columnconfigure(idx, weight=1)
            label = tk.Label(steps, text=f"{idx + 1}. {title}", bg=COLORS["soft"], fg=COLORS["muted"], padx=10, pady=7, font=("Segoe UI", 9, "bold"))
            label.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 8, 0))
            self.scan_step_labels.append(label)

        left = tk.Frame(self.home_main, bg=COLORS["bg"])
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        score_card = self._card(left, 0, 0, columnspan=2, padx=(0, 14))
        score_card.columnconfigure(0, weight=1)
        score_card.columnconfigure(1, weight=1)
        tk.Label(score_card, text="Protection overview", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=24, pady=(16, 0))
        tk.Label(score_card, textvariable=self.metric_vars["score"], bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 44, "bold")).grid(row=1, column=0, sticky="w", padx=24)
        self.score_label_widget = tk.Label(score_card, textvariable=self.metric_vars["score_label"], bg=COLORS["surface"], fg=COLORS["green"], font=("Segoe UI", 14, "bold"))
        self.score_label_widget.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 16))
        self.score_canvas = tk.Canvas(score_card, width=220, height=130, bg=COLORS["surface"], highlightthickness=0)
        self.score_canvas.grid(row=0, column=1, rowspan=3, sticky="e", padx=20, pady=14)

        proof = tk.Frame(score_card, bg=COLORS["surface"])
        proof.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        for idx in range(3):
            proof.columnconfigure(idx, weight=1)
        for idx, (title, body, mode) in enumerate(
            (
                ("Public hits", "Checks reachable pages and shows evidence.", "verified"),
                ("Private brokers", "Creates request-only opt-out paths.", "request"),
                ("This PC", "Flags local proxy and bandwidth signals.", "local"),
            )
        ):
            self._insight_card(proof, title, body, mode).grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))

        self.action_badges: dict[str, tk.Label] = {}
        self._home_action(left, 1, 0, "Scan exposure", "Check data brokers and people-search sites.", "broker_scan", "Scan now", primary=True)
        self._home_action(left, 1, 1, "Prepare removals", "Create request drafts you can inspect.", "prepare_requests", "Prepare")
        self._home_action(left, 2, 0, "Scan this PC", "Find proxy and bandwidth-sharing signals.", "watchdog", "Scan PC")
        self._home_action(left, 2, 1, "Export receipts", "Bundle reports, drafts, and hashes.", "bundle", "Export")

        advisor = self._card(self.home_main, 0, 1, padx=(0, 0))
        advisor.grid(row=1, column=1, sticky="nsew", padx=(0, 0), pady=(0, 14))
        advisor.columnconfigure(0, weight=1)
        tk.Label(advisor, text="Trusted advisor", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=22, pady=(16, 4))
        self.next_step_title = tk.Label(advisor, text="Run a privacy check", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 15, "bold"), wraplength=250, justify="left")
        self.next_step_title.pack(anchor="w", padx=22)
        self.next_step_body = tk.Label(advisor, text="", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=260, justify="left")
        self.next_step_body.pack(anchor="w", padx=22, pady=(6, 14))
        self.risk_panel = tk.Frame(advisor, bg=COLORS["red_soft"], highlightbackground=COLORS["red"], highlightthickness=1)
        self.risk_panel.pack(fill="x", padx=22, pady=(0, 14))
        risk_top = tk.Frame(self.risk_panel, bg=COLORS["red_soft"])
        risk_top.pack(fill="x", padx=12, pady=(10, 2))
        self.risk_badge = tk.Label(risk_top, text="!", bg=COLORS["red"], fg="#ffffff", width=2, font=("Segoe UI", 10, "bold"))
        self.risk_badge.pack(side="left", padx=(0, 8))
        tk.Label(risk_top, textvariable=self.risk_headline_var, bg=COLORS["red_soft"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold"), wraplength=220, justify="left").pack(side="left", fill="x", expand=True)
        tk.Label(self.risk_panel, textvariable=self.risk_body_var, bg=COLORS["red_soft"], fg=COLORS["ink"], font=("Segoe UI", 9), wraplength=250, justify="left").pack(anchor="w", padx=12, pady=(4, 10))
        report_button = self._button(self.risk_panel, "View plain-English report", self._show_plain_english_report)
        report_button.pack(anchor="w", padx=12, pady=(0, 12))
        action_button = self._button(self.risk_panel, "Go to required action", self._open_required_action, primary=True)
        action_button.pack(anchor="w", padx=12, pady=(0, 12))

        metrics = tk.Frame(advisor, bg=COLORS["surface"])
        metrics.pack(fill="x", padx=22, pady=(4, 16))
        for label, var in (
            ("Verified public hits", self.metric_vars["verified"]),
            ("Request-only brokers", self.metric_vars["request_only"]),
            ("Public searches to review", self.metric_vars["public_unverified"]),
            ("Pending approvals", self.metric_vars["review_pending"]),
            ("Approved sends", self.metric_vars["review_approved"]),
            ("Manual form tasks", self.metric_vars["form_tasks"]),
            ("Action plan", self.metric_vars["action_items"]),
            ("Watchdog findings", self.metric_vars["watchdog"]),
            ("Draft requests", self.metric_vars["requests"]),
            ("Evidence bundle", self.metric_vars["bundle"]),
        ):
            row = tk.Frame(metrics, bg=COLORS["surface"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, textvariable=var, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).pack(side="right")

    def _build_guide_page(self) -> None:
        page = self._page("guide")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        page.rowconfigure(3, weight=1)
        self._section_header(page, "First privacy check", "A guided pass from local setup to reviewed cleanup action.")

        checklist = self._card(page, 1, 0, rowspan=2)
        checklist.columnconfigure(0, weight=1)
        tk.Label(checklist, text="What happens first", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(18, 8))
        for key, number, title, body in GUIDE_STEPS:
            row = tk.Frame(checklist, bg=COLORS["surface"])
            row.pack(fill="x", padx=20, pady=8)
            badge = tk.Label(row, text=number, bg=COLORS["yellow_soft"], fg=COLORS["blue"], width=3, font=("Segoe UI", 10, "bold"))
            badge.pack(side="left", ipady=5)
            copy = tk.Frame(row, bg=COLORS["surface"])
            copy.pack(side="left", fill="x", expand=True, padx=(12, 0))
            title_row = tk.Frame(copy, bg=COLORS["surface"])
            title_row.pack(fill="x")
            tk.Label(title_row, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 11, "bold")).pack(side="left")
            status = self._pill(title_row, "Waiting", bg=COLORS["soft"], fg=COLORS["muted"])
            status.pack(side="right")
            self.guide_status_labels[key] = status
            tk.Label(copy, text=body, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=410, justify="left").pack(anchor="w", pady=(2, 0))

        actions = self._card(page, 1, 1, padx=(0, 0))
        actions.columnconfigure(0, weight=1)
        tk.Label(actions, text="Do the useful bit", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(18, 6))
        tk.Label(
            actions,
            text="This uses public search checks where possible, prepares local takedown drafts, builds manual form tasks, imports tracker records, and exports receipts. Emails still require review before sending.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 16))
        self.guide_next_title = tk.Label(actions, text="Recommended next", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold"))
        self.guide_next_title.pack(anchor="w", padx=20, pady=(0, 2))
        self.guide_next_body = tk.Label(actions, text="", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold"), wraplength=360, justify="left")
        self.guide_next_body.pack(anchor="w", padx=20, pady=(0, 12))
        guide_button = self._button(actions, "", self._run_tutorial_next, primary=True)
        guide_button.configure(textvariable=self.guide_cta_var)
        guide_button.pack(anchor="w", padx=20, pady=(0, 10))
        self.buttons.append(guide_button)
        plan_button = self._button(actions, "Build action plan", lambda: self.run_action("action_plan"))
        plan_button.pack(anchor="w", padx=20, pady=(0, 10))
        self.buttons.append(plan_button)
        safe_button = self._button(actions, "Automate safe steps", lambda: self.run_action("safe_actions"))
        safe_button.pack(anchor="w", padx=20, pady=(0, 10))
        self.buttons.append(safe_button)
        self._button(actions, "Open Data Brokers", lambda: self.show_page("cleanup")).pack(anchor="w", padx=20, pady=(0, 18))

        privacy = self._card(page, 2, 1, padx=(0, 0), pady=(0, 14))
        tk.Label(privacy, text="Privacy guardrail", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(
            privacy,
            text="A verified scan sends your search identifiers to public broker search pages. Private broker databases cannot always be searched, so Supargus prepares request-only actions instead.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
            wraplength=370,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 18))
        tk.Label(privacy, text="Removal progress", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=20, pady=(4, 8))
        progress_body = tk.Frame(privacy, bg=COLORS["surface"])
        progress_body.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        progress_body.columnconfigure(0, weight=1)
        progress_body.rowconfigure(0, weight=1)
        self.progress_tree = self._tree(progress_body, ("request_id", "broker", "status", "next_follow_up"))

        plan_card = self._card(page, 3, 0, columnspan=2, padx=(0, 0), pady=(0, 0))
        plan_card.rowconfigure(1, weight=1)
        plan_card.columnconfigure(0, weight=1)
        tk.Label(plan_card, text="Next actions", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        plan_controls = tk.Frame(plan_card, bg=COLORS["surface"])
        plan_controls.grid(row=0, column=0, sticky="e", padx=18, pady=(12, 6))
        self._button(plan_controls, "Open", self._open_selected_action).pack(side="left", padx=(0, 8))
        self._button(plan_controls, "Copy step", self._copy_selected_action).pack(side="left")
        plan_body = tk.Frame(plan_card, bg=COLORS["surface"])
        plan_body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        plan_body.columnconfigure(0, weight=1)
        plan_body.rowconfigure(0, weight=1)
        self.action_tree = self._tree(plan_body, ("priority", "category", "title", "next_step"))

    def _home_action(self, parent: "tk.Widget", row: int, column: int, title: str, body: str, action: str, button_text: str, *, primary: bool = False) -> None:
        card = self._card(parent, row, column)
        title_row = tk.Frame(card, bg=COLORS["surface"])
        title_row.pack(fill="x", padx=20, pady=(18, 3))
        tk.Label(title_row, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).pack(side="left")
        badge = tk.Label(title_row, text="!", bg=COLORS["red"], fg="#ffffff", width=2, font=("Segoe UI", 9, "bold"))
        badge.pack(side="right")
        badge.pack_forget()
        self.action_badges[action] = badge
        tk.Label(card, text=body, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=300, justify="left").pack(anchor="w", padx=20)
        button = self._button(card, button_text, lambda: self.run_action(action), primary=primary)
        button.pack(anchor="w", padx=20, pady=18)
        self.buttons.append(button)

    def _build_cleanup_page(self) -> None:
        page = self._page("cleanup")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        self._section_header(page, "Data Brokers", "Places where Supargus found or prepared a privacy-removal action for your data.")

        actions = tk.Frame(page, bg=COLORS["bg"])
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for text, action, primary in (
            ("Run full privacy check", "workflow", True),
            ("Prepare removal options", "safe_actions", False),
            ("Build approval queue", "review_queue", False),
            ("Preview emails", "mail_preview", False),
        ):
            button = self._button(actions, text, lambda value=action: self.run_action(value), primary=primary)
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)
        for text, command, primary in (
            ("Open website/form", self._open_selected_broker_action, True),
            ("Copy request text", self._copy_selected_broker_request, False),
        ):
            button = self._button(actions, text, command, primary=primary)
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)

        gmail = tk.Frame(page, bg=COLORS["surface_alt"], highlightbackground=COLORS["line"], highlightthickness=1)
        gmail.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        gmail.columnconfigure(1, weight=1)
        gmail.columnconfigure(3, weight=1)
        tk.Label(gmail, text="Send approved requests with Gmail", bg=COLORS["surface_alt"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=6, sticky="w", padx=12, pady=(10, 0))
        tk.Label(gmail, text="Email", bg=COLORS["surface_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", padx=12, pady=10)
        tk.Entry(gmail, textvariable=self.gmail_email_var, relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=10, ipady=5)
        tk.Label(gmail, text="App password", bg=COLORS["surface_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=10)
        tk.Entry(gmail, textvariable=self.gmail_password_var, show="*", relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=1, column=3, sticky="ew", padx=(0, 10), pady=10, ipady=5)
        save_button = self._button(gmail, "Save Gmail", self._save_gmail_smtp)
        save_button.grid(row=1, column=4, padx=(0, 8), pady=10)
        send_button = self._button(gmail, "Send approved", lambda: self.run_action("mail_send"), primary=True)
        send_button.grid(row=1, column=5, padx=(0, 12), pady=10)
        self.buttons.extend([save_button, send_button])

        explain = tk.Frame(page, bg=COLORS["bg"])
        explain.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        for idx in range(3):
            explain.columnconfigure(idx, weight=1)
        for idx, (title, body, mode) in enumerate(
            (
                ("Verified public hit", "The page returned identifiers that match your profile.", "verified"),
                ("Request-only", "The broker is private, blocked, or manual. Prepare an opt-out request.", "request"),
                ("No public hit", "No obvious result came back from the reachable page.", "local"),
            )
        ):
            self._insight_card(explain, title, body, mode).grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 10, 0))

        table_card = self._card(page, 4, 0, padx=(0, 0))
        table_card.rowconfigure(0, weight=1)
        table_card.columnconfigure(0, weight=1)
        self.broker_tree = self._tree(table_card, ("place", "what_was_found", "best_next_step", "open"))

    def _build_watchdog_page(self) -> None:
        page = self._page("watchdog")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "This PC", "See exactly what local privacy signals were found and the safest next step.")

        top = tk.Frame(page, bg=COLORS["bg"])
        top.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        button = self._button(top, "Scan this PC", lambda: self.run_action("watchdog"), primary=True)
        button.pack(side="left")
        self.buttons.append(button)
        tk.Label(top, text="Safe fixes open the relevant Windows or browser setting for you to review.", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=14)

        card = self._card(page, 2, 0, padx=(0, 0))
        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)
        tk.Label(card, text="PC findings", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))
        controls = tk.Frame(card, bg=COLORS["surface"])
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 12))
        self._button(controls, "Protect me", self._protect_selected_watchdog, primary=True).pack(side="left", padx=(0, 8))
        self._button(controls, "Copy fix", self._copy_selected_watchdog_fix).pack(side="left")
        body = tk.Frame(card, bg=COLORS["surface"])
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.watchdog_tree = self._tree(body, ("finding", "what_it_means", "how_to_fix", "safe_action"))

    def _build_removals_page(self) -> None:
        page = self._page("removals")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "Removals", "Send approved emails, copy request text, or open website forms from one place.")

        self._build_forms_panel(page)
        self._build_review_panel(page)
        self._build_custom_panel(page)

    def _build_forms_panel(self, page: "tk.Frame") -> None:
        card = self._card(page, 1, 0)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(3, weight=1)
        tk.Label(card, text="Website form tasks", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        tk.Label(
            card,
            text="These sites need their opt-out form opened. Copy the prepared request text, paste it into the form, then mark it submitted.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
            wraplength=430,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(4, 0))
        controls = tk.Frame(card, bg=COLORS["surface"])
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=12)
        for text, command, primary in (
            ("Open website form", self._open_selected_form, True),
            ("Copy request text", self._copy_selected_form, False),
            ("Mark submitted", self._mark_selected_form_submitted, False),
        ):
            self._button(controls, text, command, primary=primary).pack(side="left", padx=(0, 8))
        body = tk.Frame(card, bg=COLORS["surface"])
        body.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.forms_tree = self._tree(body, ("place", "what_to_do", "website"))

    def _build_custom_panel(self, page: "tk.Frame") -> None:
        card = self._card(page, 1, 1, rowspan=2, padx=(0, 0))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(4, weight=1)
        tk.Label(card, text="Custom removals", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        form = tk.Frame(card, bg=COLORS["surface"])
        form.grid(row=1, column=0, sticky="ew", padx=18)
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="URL", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        tk.Entry(form, textvariable=self.custom_url_var, relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=0, column=1, sticky="ew", padx=(8, 0), ipady=6)
        tk.Label(form, text="Reason", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(form, textvariable=self.custom_reason_var, relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=1, column=1, sticky="ew", padx=(8, 0), ipady=6)

        controls = tk.Frame(card, bg=COLORS["surface"])
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=12)
        self._button(controls, "Add URL", self._add_custom_target, primary=True).pack(side="left", padx=(0, 8))
        self._button(controls, "Prepare drafts", self._prepare_custom_drafts).pack(side="left", padx=(0, 8))
        self._button(controls, "Mark submitted", self._mark_custom_submitted).pack(side="left")

        body = tk.Frame(card, bg=COLORS["surface"])
        body.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.custom_tree = self._tree(body, ("status", "domain", "url"))

    def _build_review_panel(self, page: "tk.Frame") -> None:
        card = self._card(page, 2, 0)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(4, weight=1)
        tk.Label(card, text="Email requests", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        summary = tk.Frame(card, bg=COLORS["surface"])
        summary.grid(row=1, column=0, sticky="ew", padx=18, pady=(10, 0))
        self._pill(summary, "Pending", bg=COLORS["yellow_soft"], fg=COLORS["yellow_dark"]).pack(side="left")
        tk.Label(summary, textvariable=self.metric_vars["review_pending"], bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 14))
        self._pill(summary, "Approved", bg=COLORS["green_soft"], fg=COLORS["green"]).pack(side="left")
        tk.Label(summary, textvariable=self.metric_vars["review_approved"], bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 0))
        controls = tk.Frame(card, bg=COLORS["surface"])
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=12)
        for text, command, primary in (
            ("Approve", self._approve_selected_review, True),
            ("Skip", self._skip_selected_review, False),
            ("Copy email", self._copy_selected_review, False),
        ):
            self._button(controls, text, command, primary=primary).pack(side="left", padx=(0, 8))
        gmail = tk.Frame(card, bg=COLORS["surface_alt"], highlightbackground=COLORS["line"], highlightthickness=1)
        gmail.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        gmail.columnconfigure(1, weight=1)
        gmail.columnconfigure(3, weight=1)
        tk.Label(gmail, text="Gmail app password", bg=COLORS["surface_alt"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 2))
        tk.Label(gmail, text="Email", bg=COLORS["surface_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", padx=12, pady=(6, 10))
        tk.Entry(gmail, textvariable=self.gmail_email_var, relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(6, 10), ipady=5)
        tk.Label(gmail, text="App password", bg=COLORS["surface_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(6, 10))
        tk.Entry(gmail, textvariable=self.gmail_password_var, show="*", relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=1, column=3, sticky="ew", padx=(0, 10), pady=(6, 10), ipady=5)
        save_button = self._button(gmail, "Save Gmail", self._save_gmail_smtp)
        save_button.grid(row=1, column=4, padx=(0, 8), pady=(6, 10))
        send_button = self._button(gmail, "Send approved", lambda: self.run_action("mail_send"), primary=True)
        send_button.grid(row=1, column=5, padx=(0, 12), pady=(6, 10))
        self.buttons.extend([save_button, send_button])
        body = tk.Frame(card, bg=COLORS["surface"])
        body.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.review_tree = self._tree(body, ("state", "place", "how_to_send", "destination"))

    def _build_advanced_page(self) -> None:
        page = self._page("advanced")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "Advanced tools", "Power-user controls are here when you need them.")

        setup = self._card(page, 1, 0)
        setup.columnconfigure(1, weight=1)
        tk.Label(setup, text="Local setup", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 0))
        self._field(setup, 1, "Workspace", self.workspace_var, self._choose_workspace)
        self._field(setup, 2, "Identity", self.identity_var, self._choose_identity)
        self._field(setup, 3, "Config", self.config_var, None)
        self._field(setup, 4, "Gmail / SMTP", self.smtp_var, None)
        self._field(setup, 5, "Limit", self.limit_var, None)
        self._button(setup, "Create sample identity", self._create_sample_identity).grid(row=6, column=0, padx=18, pady=16, sticky="w")
        self._button(setup, "Open workspace folder", self._open_workspace).grid(row=6, column=1, padx=8, pady=16, sticky="w")

        tools = self._card(page, 1, 1, padx=(0, 0))
        tools.columnconfigure(0, weight=1)
        tk.Label(tools, text="Command actions", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 8))
        for action, title, detail in DESKTOP_ACTIONS:
            row = tk.Frame(tools, bg=COLORS["surface"])
            row.pack(fill="x", padx=18, pady=5)
            tk.Label(row, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).pack(side="left")
            button = self._button(row, "Run", lambda value=action: self.run_action(value))
            button.pack(side="right")
            self.buttons.append(button)

        log_card = self._card(page, 2, 0, columnspan=2, padx=(0, 0), pady=(0, 0))
        log_card.rowconfigure(0, weight=1)
        log_card.columnconfigure(0, weight=1)
        self.log_text = self._text_panel(log_card, dark=True)

    def _section_header(self, parent: "tk.Frame", title: str, body: str) -> None:
        header = tk.Frame(parent, bg=COLORS["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        tk.Label(header, text=title, bg=COLORS["bg"], fg=COLORS["ink"], font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(header, text=body, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 11)).pack(anchor="w", pady=(4, 0))

    def _field(self, parent: "tk.Widget", row: int, label: str, variable: "tk.StringVar", browse: Any) -> None:
        tk.Label(parent, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", padx=18, pady=(12, 0))
        tk.Entry(parent, textvariable=variable, relief="solid", bd=1, font=("Segoe UI", 10)).grid(row=row, column=1, sticky="ew", padx=10, pady=(12, 0), ipady=5)
        if browse:
            self._button(parent, "Browse", browse).grid(row=row, column=2, sticky="e", padx=(0, 18), pady=(12, 0))

    def _tree(self, parent: "tk.Widget", columns: tuple[str, ...]) -> "ttk.Treeview":
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        widths = {
            "broker": 190,
            "place": 190,
            "action": 165,
            "status": 120,
            "state": 150,
            "confidence": 110,
            "score": 70,
            "url": 280,
            "open": 260,
            "website": 260,
            "destination": 260,
            "next_step": 360,
            "title": 260,
            "what_was_found": 300,
            "what_to_do": 240,
            "what_it_means": 340,
            "how_to_fix": 340,
            "finding": 230,
            "safe_action": 220,
            "how_to_send": 140,
            "request_id": 155,
            "next_follow_up": 180,
        }
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=widths.get(column, 150), anchor="w", stretch=True)
        ybar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ybar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        if columns and columns[0] in {"broker", "status"}:
            tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_records())
        return tree

    def _text_panel(self, parent: "tk.Widget", *, dark: bool) -> "tk.Text":
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        bg = COLORS["navy"] if dark else COLORS["surface_alt"]
        fg = "#d7f5ec" if dark else COLORS["ink"]
        text = tk.Text(parent, bg=bg, fg=fg, insertbackground=fg, relief="flat", padx=14, pady=12, wrap="word", font=("Consolas", 10))
        ybar = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=ybar.set)
        text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        return text

    def _payload(self, action: str) -> dict[str, Any]:
        try:
            limit = int(self.limit_var.get() or "10")
        except ValueError:
            limit = 10
            self.limit_var.set("10")
        return {
            "action": action,
            "identity": self.identity_var.get(),
            "workspace": self.workspace_var.get(),
            "config": self.config_var.get(),
            "smtp_config": self.smtp_var.get(),
            "limit": limit,
            "fetch": True,
        }

    def run_action(self, action: str, extra: dict[str, Any] | None = None) -> None:
        if action == "guide_take_action":
            action = "workflow"
        if action == "mail_send" and messagebox:
            approved = messagebox.askyesno(
                "Send reviewed emails?",
                "Supargus will send email requests through the configured SMTP account. Preview the queue first and continue only if the drafts are ready.",
            )
            if not approved:
                return
        self._set_running(True, f"Running {action}...")
        self._start_progress_steps(action)
        payload = self._payload(action)
        if extra:
            payload.update(extra)
        workspace = Path(payload["workspace"])

        def worker() -> None:
            try:
                result = run_action(workspace, payload)
                self.queue.put(("action_ok", action, result))
            except Exception as exc:
                self.queue.put(("action_error", action, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _action_progress_text(self, action: str) -> str:
        labels = {
            "workflow": "Checking broker sites, preparing removal drafts, scanning this PC, and bundling receipts...",
            "broker_scan": "Checking public broker pages and marking private brokers as request-only...",
            "watchdog": "Checking this PC for proxy, extension, startup, and bandwidth-sharing signals...",
            "prepare_requests": "Writing removal requests you can review before anything is sent...",
            "safe_actions": "Preparing drafts, forms, tracker records, follow-ups, and receipts without sending email...",
            "mail_send": "Sending only approved email requests through your configured account...",
            "bundle": "Packaging reports, drafts, tracker state, and receipts...",
        }
        return labels.get(action, f"Running {action.replace('_', ' ')}...")

    def _progress_sequence(self, action: str) -> tuple[str, ...]:
        if action == "workflow":
            return (
                "Checking data broker and people-search pages for your profile...",
                "Marking private or blocked brokers as request-only, without pretending they were verified...",
                "Preparing removal emails and website form tasks for your review...",
                "Scanning this PC for proxy, startup, and browser-extension privacy signals...",
                "Building the plain-English report and local evidence receipts...",
            )
        if action == "watchdog":
            return (
                "Checking network proxy and listener settings...",
                "Checking browser extensions with broad permissions...",
                "Checking startup and installed-app privacy signals...",
            )
        if action in {"prepare_requests", "safe_actions"}:
            return (
                "Reading the broker findings...",
                "Preparing removal emails and website form tasks...",
                "Building approval and tracking records...",
            )
        return (self._action_progress_text(action),)

    def _update_scan_step_labels(self, index: int, *, done_all: bool = False, failed: bool = False) -> None:
        for idx, label in enumerate(getattr(self, "scan_step_labels", [])):
            if failed and idx == index:
                bg, fg = COLORS["red_soft"], COLORS["red"]
            elif done_all or idx < index:
                bg, fg = COLORS["green_soft"], COLORS["green"]
            elif idx == index:
                bg, fg = COLORS["yellow_soft"], COLORS["yellow_dark"]
            else:
                bg, fg = COLORS["soft"], COLORS["muted"]
            label.configure(bg=bg, fg=fg)

    def _start_progress_steps(self, action: str) -> None:
        self.progress_token += 1
        token = self.progress_token
        self.progress_step_index = 0
        steps = self._progress_sequence(action)
        self.scan_progress_var.set(steps[0])
        self._update_scan_step_labels(0)
        self.root.after(1200, lambda: self._advance_progress_steps(token, steps))

    def _advance_progress_steps(self, token: int, steps: tuple[str, ...]) -> None:
        if token != self.progress_token:
            return
        self.progress_step_index = min(self.progress_step_index + 1, len(steps) - 1)
        self.scan_progress_var.set(steps[self.progress_step_index])
        self._update_scan_step_labels(min(self.progress_step_index, len(getattr(self, "scan_step_labels", [])) - 1))
        if self.progress_step_index < len(steps) - 1:
            self.root.after(1400, lambda: self._advance_progress_steps(token, steps))

    def _finish_progress_steps(self, text: str, *, failed: bool = False) -> None:
        self.progress_token += 1
        self.scan_progress_var.set(text)
        if failed:
            self._update_scan_step_labels(max(0, self.progress_step_index), failed=True)
        else:
            self._update_scan_step_labels(0, done_all=True)

    def refresh(self) -> None:
        self.state = build_state(self.workspace_var.get())
        summary = self.state["summary"]
        score = _privacy_score(summary)
        label, label_color = _score_label(score)

        # Toggle empty / main home state
        if hasattr(self, "home_empty") and hasattr(self, "home_main"):
            if self._identity_exists():
                self.home_empty.grid_remove()
                self.home_main.grid()
            else:
                self.home_main.grid_remove()
                self.home_empty.grid()

        self.metric_vars["brokers"].set(str(summary["brokers_checked"]))
        self.metric_vars["matches"].set(str(summary["possible_matches"]))
        self.metric_vars["request_only"].set(str(summary.get("request_only", 0)))
        self.metric_vars["public_unverified"].set(str(summary.get("public_unverified", 0)))
        self.metric_vars["verified"].set(str(summary.get("verified_or_likely", 0)))
        self.metric_vars["action_items"].set(str(summary.get("action_items", 0)))
        self.metric_vars["review_pending"].set(str(summary.get("review_pending", 0)))
        self.metric_vars["review_approved"].set(str(summary.get("review_approved", 0)))
        self.metric_vars["form_tasks"].set(str(summary.get("form_tasks", 0)))
        self.metric_vars["watchdog"].set(str(summary["watchdog_findings"]))
        self.metric_vars["changes"].set(str(summary["scan_changes"]))
        self.metric_vars["requests"].set(str(summary["request_drafts"]))
        self.metric_vars["bundle"].set(_fmt_bytes(int(summary["bundle_size"])))
        self.metric_vars["score"].set(str(score))
        self.metric_vars["score_label"].set(label)
        self.status_var.set(label)
        self.score_label_widget.configure(fg=label_color)

        self._draw_score(score, label_color)
        self._set_next_step(summary)
        self._update_risk_panel(summary, score)
        self._update_action_badges(summary)
        self._update_guide(summary)
        self._populate_brokers(self.state["matches"])
        self._populate_watchdog(self.state["findings"])
        self._populate_tracker(self.state["tracker"])
        self._populate_progress(self.state["tracker"])
        self._populate_action_plan(self.state["action_plan"])
        self._populate_review_queue(self.state["review_queue"])
        self._populate_forms(self.state)
        self._populate_custom()

    def _draw_score(self, score: int, color: str) -> None:
        if not hasattr(self, "score_canvas"):
            return
        canvas = self.score_canvas
        canvas.delete("all")
        canvas.create_arc(28, 24, 222, 218, start=180, extent=-180, outline="#e5e7eb", width=18, style="arc")
        canvas.create_arc(28, 24, 222, 218, start=180, extent=-max(4, int(180 * score / 100)), outline=color, width=18, style="arc")
        canvas.create_text(125, 86, text=f"{score}", fill=COLORS["ink"], font=("Segoe UI", 33, "bold"))
        canvas.create_text(125, 122, text="privacy score", fill=COLORS["muted"], font=("Segoe UI", 10, "bold"))

    def _set_next_step(self, summary: dict[str, Any]) -> None:
        matches = int(summary.get("possible_matches", 0) or 0)
        requests = int(summary.get("request_drafts", 0) or 0)
        findings = int(summary.get("watchdog_findings", 0) or 0)
        pending = int(summary.get("review_pending", 0) or 0)
        forms = int(summary.get("form_tasks", 0) or 0)
        request_only = int(summary.get("request_only", 0) or 0)
        if pending:
            title = "Approve or skip drafts"
            body = "Removal drafts are ready. Open Removals, inspect each destination, then approve only the requests you want sent."
        elif forms:
            title = "Finish manual forms"
            body = "Some brokers require browser forms. Open each form, paste the prepared request, and mark it submitted."
        elif matches and not requests:
            title = "Prepare removal drafts"
            body = "Supargus found possible broker exposure. Create drafts first, then review before sending anything."
        elif request_only:
            title = "Send request-only opt-outs"
            body = "Some brokers cannot be searched directly. Supargus can still prepare removal requests you control."
        elif findings:
            title = "Review this PC"
            body = "The watchdog found local signals worth checking. These are review-only findings, not automatic accusations."
        elif not summary.get("brokers_checked"):
            title = "Run your first scan"
            body = "Start with a local broker scan. Supargus will create evidence you can inspect before taking action."
        else:
            title = "Keep monitoring"
            body = "You have a baseline. Re-scan later to catch reappearances and export receipts when you need them."
        self.next_step_title.configure(text=title)
        self.next_step_body.configure(text=body)

    def _set_risk_widget_color(self, widget: "tk.Widget", bg: str) -> None:
        try:
            current = widget.cget("bg")
            if current in {COLORS["red_soft"], COLORS["yellow_soft"], COLORS["green_soft"]}:
                widget.configure(bg=bg)
        except tk.TclError:
            return
        for child in widget.winfo_children():
            self._set_risk_widget_color(child, bg)

    def _update_risk_panel(self, summary: dict[str, Any], score: int) -> None:
        findings = _score_findings(summary)
        next_actions = _score_next_actions(summary, self.state.get("exists", {}))
        headline = "Action needed" if score < 65 else "Needs review" if score < 85 else "Protected"
        body = f"{findings[0]} Next: {next_actions[0]}"
        bg = COLORS["red_soft"] if score < 65 else COLORS["yellow_soft"] if score < 85 else COLORS["green_soft"]
        fg = COLORS["red"] if score < 65 else COLORS["yellow_dark"] if score < 85 else COLORS["green"]
        self.risk_headline_var.set(headline)
        self.risk_body_var.set(body)
        self.risk_panel.configure(bg=bg, highlightbackground=fg)
        self.risk_badge.configure(bg=fg)
        self._set_risk_widget_color(self.risk_panel, bg)

    def _set_action_badge(self, action: str, active: bool) -> None:
        badge = getattr(self, "action_badges", {}).get(action)
        if not badge:
            return
        if active:
            badge.pack(side="right")
        else:
            badge.pack_forget()

    def _update_action_badges(self, summary: dict[str, Any]) -> None:
        checked = _summary_int(summary, "brokers_checked")
        matches = _summary_int(summary, "possible_matches")
        request_only = _summary_int(summary, "request_only")
        drafts = _summary_int(summary, "request_drafts")
        watchdog = _summary_int(summary, "watchdog_findings")
        bundle = _summary_int(summary, "bundle_size")
        self._set_action_badge("broker_scan", checked == 0)
        self._set_action_badge("prepare_requests", (matches or request_only) and drafts == 0)
        self._set_action_badge("watchdog", watchdog > 0)
        self._set_action_badge("bundle", drafts > 0 and bundle == 0)

    def _report_relevant_details(self) -> str:
        public_hits = []
        request_only = []
        for item in self.state.get("matches", []):
            row = _broker_user_row(item)
            if not row:
                continue
            place, what, _next_step, open_url = row
            line = f"- {place}: {what}"
            if open_url:
                line += f" ({open_url})"
            if str(item.get("status") or "") == "possible_match" or str(item.get("action_mode") or "") == "verified_public":
                public_hits.append(line)
            elif str(item.get("action_mode") or "") == "request_only" or str(item.get("status") or "") in {"fetch_error", "needs_manual_review"}:
                request_only.append(line)

        pc_findings = [
            f"- {item.get('title', 'PC finding')}: {_watchdog_meaning(item)} Next: {item.get('remediation') or _watchdog_safe_action(item)}"
            for item in self.state.get("findings", [])
        ]

        lines: list[str] = []
        if public_hits:
            lines.append("Sites where your data may be visible:")
            lines.extend(public_hits[:8])
        if request_only:
            if lines:
                lines.append("")
            lines.append("Brokers Supargus could not verify directly:")
            lines.extend(request_only[:8])
        if pc_findings:
            if lines:
                lines.append("")
            lines.append("This PC findings:")
            lines.extend(pc_findings[:8])
        return "\n".join(lines)

    def _show_plain_english_report(self) -> None:
        report = _plain_english_report(self.state.get("summary", {}), self.state.get("exists", {}))
        relevant = self._report_relevant_details()
        if relevant:
            report = f"{report}\n\nRelevant findings:\n{relevant}"
        if tk is None:
            return
        popup = tk.Toplevel(self.root)
        popup.title("Supargus report")
        popup.geometry("620x520")
        popup.configure(bg=COLORS["surface"])
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(1, weight=1)
        tk.Label(popup, text="Plain-English privacy report", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 17, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        text = tk.Text(popup, bg=COLORS["surface_alt"], fg=COLORS["ink"], relief="flat", wrap="word", padx=14, pady=12, font=("Segoe UI", 10))
        text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        text.insert("1.0", report)
        text.configure(state="disabled")
        controls = tk.Frame(popup, bg=COLORS["surface"])
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        controls.columnconfigure(0, weight=1)
        self._button(controls, self._required_action_label(), lambda: self._continue_from_report(popup), primary=True).grid(row=0, column=0, sticky="w")
        self._button(controls, "Close", popup.destroy).grid(row=0, column=1, sticky="e")

    def _required_action_label(self) -> str:
        summary = self.state.get("summary", {})
        if _summary_int(summary, "possible_matches") or _summary_int(summary, "request_only"):
            return "View Data Brokers"
        if _summary_int(summary, "watchdog_findings"):
            return "Review This PC"
        if _summary_int(summary, "form_tasks") or _summary_int(summary, "review_pending"):
            return "Open Removals"
        return "Continue guided setup"

    def _continue_from_report(self, popup: "tk.Toplevel") -> None:
        popup.destroy()
        self._open_required_action()

    def _open_required_action(self) -> None:
        summary = self.state.get("summary", {})
        if _summary_int(summary, "possible_matches") or _summary_int(summary, "request_only"):
            self.show_page("cleanup")
        elif _summary_int(summary, "watchdog_findings"):
            self.show_page("watchdog")
        elif _summary_int(summary, "form_tasks") or _summary_int(summary, "review_pending"):
            self.show_page("removals")
        elif not _summary_int(summary, "brokers_checked"):
            self.run_action("workflow")
        else:
            self.show_page("guide")

    def _guide_step_state(self, summary: dict[str, Any]) -> dict[str, str]:
        identity_exists = self._identity_exists()
        scan_done = int(summary.get("brokers_checked", 0) or 0) > 0
        review_started = bool(
            int(summary.get("action_items", 0) or 0)
            or int(summary.get("review_pending", 0) or 0)
            or int(summary.get("review_approved", 0) or 0)
            or int(summary.get("form_tasks", 0) or 0)
        )
        action_started = bool(
            int(summary.get("tracker_records", 0) or 0)
            or int(summary.get("request_drafts", 0) or 0)
            or int(summary.get("bundle_size", 0) or 0)
        )
        return {
            "identity": "Done" if identity_exists else "Next",
            "scan": "Done" if scan_done else ("Next" if identity_exists else "Waiting"),
            "review": "Done" if review_started else ("Next" if scan_done else "Waiting"),
            "action": "Done" if action_started else ("Next" if review_started else "Waiting"),
        }

    def _set_guide_status(self, key: str, status: str) -> None:
        label = self.guide_status_labels.get(key)
        if not label:
            return
        bg, fg = {
            "Done": (COLORS["green_soft"], COLORS["green"]),
            "Next": (COLORS["yellow_soft"], COLORS["yellow_dark"]),
            "Waiting": (COLORS["soft"], COLORS["muted"]),
        }.get(status, (COLORS["soft"], COLORS["muted"]))
        label.configure(text=status, bg=bg, fg=fg)

    def _update_guide(self, summary: dict[str, Any]) -> None:
        states = self._guide_step_state(summary)
        for key, status in states.items():
            self._set_guide_status(key, status)
        if states["identity"] != "Done":
            self.guide_cta_var.set("Start setup")
            body = "Create a privacy profile so Supargus knows what to search for."
        elif states["scan"] != "Done":
            self.guide_cta_var.set("Run full privacy check")
            body = "Start with a broker scan and local PC check, then let Supargus prepare safe local artifacts."
        elif states["review"] != "Done":
            self.guide_cta_var.set("Open Data Brokers")
            body = "Review the sites Supargus found or could not verify, then move into Removals for forms and emails."
        elif int(summary.get("review_pending", 0) or 0) or int(summary.get("form_tasks", 0) or 0):
            self.guide_cta_var.set("Open Removals")
            body = "Finish manual forms, approve email drafts, and mark submitted work from the Removals workbench."
        else:
            self.guide_cta_var.set("Automate safe steps")
            body = "Prepare drafts, tracker records, follow-ups, action plan, and receipts without sending email."
        if hasattr(self, "guide_next_body"):
            self.guide_next_body.configure(text=body)

    def _run_tutorial_next(self) -> None:
        summary = self.state.get("summary", {})
        states = self._guide_step_state(summary)
        if states["identity"] != "Done":
            self.show_page("setup")
        elif states["scan"] != "Done":
            self.run_action("workflow")
        elif states["review"] != "Done":
            self.show_page("cleanup")
        elif int(summary.get("review_pending", 0) or 0) or int(summary.get("form_tasks", 0) or 0):
            self.show_page("removals")
        else:
            self.run_action("safe_actions")

    def _populate_brokers(self, items: list[dict[str, Any]]) -> None:
        self.broker_items = []
        self._clear_tree(self.broker_tree)
        if not items:
            self.broker_tree.insert("", "end", values=("No scan yet", "Run full privacy check", "Start from Dashboard", ""))
            return
        for item in items:
            row = _broker_user_row(item)
            if not row:
                continue
            self.broker_items.append(item)
            self.broker_tree.insert(
                "",
                "end",
                iid=f"broker-{len(self.broker_items) - 1}",
                values=row,
            )
        if not self.broker_items:
            self.broker_tree.insert("", "end", values=("No relevant broker hits", "No public matches or request-only tasks found", "Re-run later to monitor changes", ""))

    def _selected_broker_item(self) -> dict[str, Any] | None:
        if not hasattr(self, "broker_tree"):
            return None
        selected = self.broker_tree.selection()
        if not selected and len(self.broker_items) == 1:
            return self.broker_items[0]
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.broker_items[index]
        except Exception:
            return None

    def _matching_form_task(self, item: dict[str, Any]) -> FormTask | None:
        broker_id = str(item.get("broker_id", ""))
        broker_name = str(item.get("broker_name", ""))
        urls = {str(item.get("evidence_url", "")), str(item.get("search_url", ""))}
        matches = [
            task
            for task in self.form_tasks
            if (broker_id and task.broker_id == broker_id) or (broker_name and task.broker_name == broker_name)
        ]
        for task in matches:
            if task.profile_url and task.profile_url in urls:
                return task
        return sorted(matches, key=lambda task: task.updated_at or task.created_at)[-1] if matches else None

    def _matching_review_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        broker_id = str(item.get("broker_id", ""))
        broker_name = str(item.get("broker_name", ""))
        urls = {str(item.get("evidence_url", "")), str(item.get("search_url", ""))}
        matches = [
            review
            for review in self.review_items
            if (broker_id and review.get("broker_id") == broker_id) or (broker_name and review.get("broker_name") == broker_name)
        ]
        for review in matches:
            if review.get("profile_url") in urls:
                return review
        return sorted(matches, key=lambda review: str(review.get("updated_at", "")))[-1] if matches else None

    def _open_selected_broker_action(self) -> None:
        item = self._selected_broker_item()
        if not item:
            self._log("Select a broker finding first.")
            return
        task = self._matching_form_task(item)
        url = task.opt_out_url if task else str(item.get("evidence_url") or item.get("search_url") or "")
        if not url:
            self._log("Selected broker has no website URL to open.")
            return
        webbrowser.open(url)
        self.status_var.set("Opened broker action")
        self._log(f"Opened broker action for {item.get('broker_name', 'broker')}:\n{url}")

    def _copy_selected_broker_request(self) -> None:
        item = self._selected_broker_item()
        if not item:
            self._log("Select a broker finding first.")
            return
        task = self._matching_form_task(item)
        if task:
            self._copy_form_task_to_clipboard(task)
            return
        review = self._matching_review_item(item)
        if review:
            self._copy_review_item_to_clipboard(review)
            return
        self.status_var.set("Prepare removal options first")
        self._log("No prepared request exists for that broker yet. Run Prepare removal options, then copy again.")

    def _populate_watchdog(self, items: list[dict[str, Any]]) -> None:
        self.watchdog_items = list(items)
        self._clear_tree(self.watchdog_tree)
        if not items:
            self.watchdog_tree.insert("", "end", values=("No PC scan yet", "Run Scan this PC", ""))
            return
        for item in items:
            self.watchdog_tree.insert(
                "",
                "end",
                iid=f"watchdog-{len(self.watchdog_tree.get_children())}",
                values=(
                    item.get("title", "PC finding"),
                    _watchdog_meaning(item),
                    item.get("remediation") or _watchdog_safe_action(item),
                    _watchdog_safe_action(item),
                ),
            )

    def _populate_tracker(self, items: list[dict[str, Any]]) -> None:
        if not hasattr(self, "tracker_tree"):
            return
        self._clear_tree(self.tracker_tree)
        for item in items:
            self.tracker_tree.insert("", "end", values=(item.get("broker_name", ""), item.get("status", ""), item.get("delivery", ""), item.get("updated_at", "")))

    def _populate_progress(self, items: list[dict[str, Any]]) -> None:
        if not hasattr(self, "progress_tree"):
            return
        self._clear_tree(self.progress_tree)
        if not items:
            self.progress_tree.insert("", "end", values=("No requests yet", "Run full privacy check", "", ""))
            return
        for item in items[:8]:
            self.progress_tree.insert(
                "",
                "end",
                values=(
                    item.get("request_id", ""),
                    item.get("broker_name", ""),
                    item.get("status", ""),
                    item.get("next_follow_up_at", ""),
                ),
            )

    def _populate_action_plan(self, items: list[dict[str, Any]]) -> None:
        if not hasattr(self, "action_tree"):
            return
        self.action_items = list(items)
        self._clear_tree(self.action_tree)
        if not items:
            self.action_tree.insert("", "end", values=("none", "start", "No action plan yet", "Run full privacy check"))
            return
        for idx, item in enumerate(items[:8]):
            self.action_tree.insert(
                "",
                "end",
                iid=f"action-{idx}",
                values=(
                    item.get("priority", ""),
                    item.get("category", ""),
                    item.get("title", ""),
                    item.get("next_step", ""),
                ),
            )

    def _populate_forms(self, state: dict[str, Any]) -> None:
        forms_path = state["paths"].get("forms", "")
        try:
            self.form_tasks = load_form_queue(forms_path) if forms_path else []
        except Exception:
            self.form_tasks = []
        self._clear_tree(self.forms_tree)
        if not self.form_tasks:
            self.forms_tree.insert("", "end", iid="form-empty", values=("No website forms yet", "Run full privacy check", ""))
            return
        for idx, task in enumerate(self.form_tasks):
            self.forms_tree.insert("", "end", iid=f"form-{idx}", values=(task.broker_name, _task_label(task.status), task.opt_out_url))

    def _populate_review_queue(self, items: list[dict[str, Any]]) -> None:
        if not hasattr(self, "review_tree"):
            return
        self.review_items = list(items)
        self._clear_tree(self.review_tree)
        if not items:
            self.review_tree.insert("", "end", iid="review-empty", values=("No emails yet", "Run full privacy check", "", ""))
            return
        for idx, item in enumerate(items):
            destination = item.get("to_email") or item.get("opt_out_url") or item.get("profile_url") or ""
            self.review_tree.insert(
                "",
                "end",
                iid=f"review-{idx}",
                values=(_review_status_label(str(item.get("status", ""))), item.get("broker_name", ""), _delivery_label(item), destination),
            )

    def _selected_review_item(self) -> dict[str, Any] | None:
        if not hasattr(self, "review_tree"):
            return None
        selected = self.review_tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.review_items[index]
        except Exception:
            return None

    def _approve_selected_review(self) -> None:
        item = self._selected_review_item()
        if not item:
            self._log("Select a review item first.")
            return
        self.run_action("review_approve", {"request_id": item.get("request_id", "")})

    def _skip_selected_review(self) -> None:
        item = self._selected_review_item()
        if not item:
            self._log("Select a review item first.")
            return
        self.run_action("review_skip", {"request_id": item.get("request_id", "")})

    def _copy_review_item_to_clipboard(self, item: dict[str, Any]) -> None:
        path = Path(str(item.get("file_path", "")))
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        destination = item.get("to_email") or item.get("opt_out_url") or ""
        subject = item.get("subject") or f"Privacy removal request for {item.get('broker_name', 'data broker')}"
        text = (
            f"{item.get('broker_name', '')}\n"
            f"To: {destination}\n"
            f"Subject: {subject}\n"
            f"Description: Request removal of my personal information from this service.\n"
            f"State: {_review_status_label(str(item.get('status', '')))}\n\n"
            f"{body}"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied review draft")
        self._log(f"Copied review draft for {item.get('broker_name', '')}.")

    def _copy_selected_review(self) -> None:
        item = self._selected_review_item()
        if not item:
            self._log("Select a review item first.")
            return
        self._copy_review_item_to_clipboard(item)

    def _save_gmail_smtp(self) -> None:
        try:
            config = gmail_smtp_config(self.gmail_email_var.get(), self.gmail_password_var.get())
            path = Path(self.smtp_var.get() or Path(self.workspace_var.get()) / "smtp.gmail.json")
            out = save_smtp_config(config, path, force=True)
            self.smtp_var.set(str(out))
            self.gmail_password_var.set("")
            self.status_var.set("Gmail sending saved locally")
            self._log(f"Saved Gmail SMTP config locally:\n{out}\nOnly approved review items will be sent.")
        except Exception as exc:
            self.status_var.set("Gmail setup needs attention")
            self._log(f"Could not save Gmail setup:\n{exc}")
            if messagebox:
                messagebox.showerror("Supargus", str(exc))

    def _selected_watchdog_item(self) -> dict[str, Any] | None:
        if not hasattr(self, "watchdog_tree"):
            return None
        selected = self.watchdog_tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.watchdog_items[index]
        except Exception:
            return None

    def _protect_selected_watchdog(self) -> None:
        item = self._selected_watchdog_item()
        if not item:
            self._log("Select a PC finding first.")
            return
        category = str(item.get("category", ""))
        target = ""
        try:
            if category == "network":
                target = "Windows proxy settings"
                if sys.platform == "win32":
                    os.startfile("ms-settings:network-proxy")  # type: ignore[attr-defined]
                else:
                    webbrowser.open("about:preferences#general")
            elif category == "browser":
                target = "browser extensions"
                evidence = str(item.get("evidence", "")).lower()
                webbrowser.open("edge://extensions" if "edge" in evidence else "chrome://extensions")
            elif category == "startup":
                target = "Startup Apps"
                if sys.platform == "win32":
                    os.startfile("ms-settings:startupapps")  # type: ignore[attr-defined]
                else:
                    self._copy_selected_watchdog_fix()
                    return
            elif category in {"process", "installed_app"}:
                target = "Apps settings"
                if sys.platform == "win32":
                    os.startfile("ms-settings:appsfeatures")  # type: ignore[attr-defined]
                else:
                    self._copy_selected_watchdog_fix()
                    return
            else:
                self._copy_selected_watchdog_fix()
                return
            self.status_var.set(f"Opened {target}")
            self._log(f"Opened {target} for: {item.get('title', 'PC finding')}")
        except Exception as exc:
            self._log(f"Could not open settings automatically:\n{exc}")
            self._copy_selected_watchdog_fix()

    def _copy_selected_watchdog_fix(self) -> None:
        item = self._selected_watchdog_item()
        if not item:
            self._log("Select a PC finding first.")
            return
        text = (
            f"{item.get('title', 'PC finding')}\n"
            f"What it could mean: {_watchdog_meaning(item)}\n"
            f"Suggested fix: {item.get('remediation') or _watchdog_safe_action(item)}\n"
            f"Evidence:\n{item.get('evidence', '')}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied PC fix")
        self._log(f"Copied PC fix:\n{text}")

    def _selected_action_item(self) -> dict[str, Any] | None:
        if not hasattr(self, "action_tree"):
            return None
        selected = self.action_tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.action_items[index]
        except Exception:
            return None

    def _open_selected_action(self) -> None:
        item = self._selected_action_item()
        if not item:
            self._log("Select an action first.")
            return
        url = str(item.get("url", ""))
        if not url:
            self._log("Selected action does not have a URL.")
            return
        webbrowser.open(url)
        self._log(f"Opened action URL:\n{url}")

    def _copy_selected_action(self) -> None:
        item = self._selected_action_item()
        if not item:
            self._log("Select an action first.")
            return
        text = (
            f"{item.get('title', '')}\n"
            f"Priority: {item.get('priority', '')}\n"
            f"Category: {item.get('category', '')}\n"
            f"Next step: {item.get('next_step', '')}\n"
            f"Detail: {item.get('detail', '')}\n"
            f"URL: {item.get('url', '')}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied action step")
        self._log(f"Copied action step:\n{text}")

    def _populate_custom(self) -> None:
        try:
            self.custom_targets = load_custom_targets(self._custom_queue_path())
        except Exception:
            self.custom_targets = []
        self._clear_tree(self.custom_tree)
        if not self.custom_targets:
            self.custom_tree.insert("", "end", iid="custom-empty", values=("not started", "Add a URL", ""))
            return
        for idx, target in enumerate(self.custom_targets):
            self.custom_tree.insert("", "end", iid=f"custom-{idx}", values=(target.status, target.domain, target.url))

    def _show_selected_records(self) -> None:
        return

    def _selected_form_task(self) -> FormTask | None:
        selected = self.forms_tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.form_tasks[index]
        except Exception:
            return None

    def _open_selected_form(self) -> None:
        task = self._selected_form_task()
        if not task:
            self._log("Select a form task first.")
            return
        webbrowser.open(task.opt_out_url)
        self._log(f"Opened opt-out form:\n{task.opt_out_url}")

    def _copy_selected_form(self) -> None:
        task = self._selected_form_task()
        if not task:
            self._log("Select a form task first.")
            return
        self._copy_form_task_to_clipboard(task)

    def _copy_form_task_to_clipboard(self, task: FormTask) -> None:
        text = (
            f"Broker: {task.broker_name}\n"
            f"Opt-out form: {task.opt_out_url}\n"
            f"Subject: Privacy removal request for {task.broker_name}\n"
            f"Description: Request removal of my personal information from this service.\n"
            f"Profile: {task.profile_url}\n\n"
            f"{task.request_body.strip()}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied request to clipboard")
        self._log(f"Copied request payload for {task.broker_name}.")

    def _mark_selected_form_submitted(self) -> None:
        task = self._selected_form_task()
        if not task:
            self._log("Select a form task first.")
            return
        forms_path = Path(self.workspace_var.get()) / "forms" / "forms.json"
        try:
            update_form_status(forms_path, task.broker_id, "submitted", notes="Submitted through desktop form queue")
            self._log(f"Marked form submitted: {task.broker_name}")
            self.refresh()
        except Exception as exc:
            self._log(f"Could not update form task:\n{exc}")

    def _custom_queue_path(self) -> Path:
        return Path(self.workspace_var.get()) / "custom" / "custom.json"

    def _selected_custom_target(self):
        selected = self.custom_tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].split("-", 1)[1])
            return self.custom_targets[index]
        except Exception:
            return None

    def _add_custom_target(self) -> None:
        try:
            target = add_custom_target(self._custom_queue_path(), self.custom_url_var.get(), reason=self.custom_reason_var.get() or "custom_removal")
            self.custom_url_var.set("")
            self._log(f"Added custom removal target:\n{target.id} {target.url}")
            self.refresh()
        except Exception as exc:
            self._log(f"Could not add custom target:\n{exc}")
            if messagebox:
                messagebox.showerror("Supargus", str(exc))

    def _prepare_custom_drafts(self) -> None:
        try:
            identity = load_identity(self.identity_var.get())
            targets = load_custom_targets(self._custom_queue_path())
            requests, manifest = prepare_custom_requests(targets, identity, Path(self.workspace_var.get()) / "custom" / "requests")
            self._log(f"Prepared {len(requests)} custom removal draft(s):\n{manifest}")
            self.status_var.set("Custom drafts prepared")
        except Exception as exc:
            self._log(f"Could not prepare custom drafts:\n{exc}")
            if messagebox:
                messagebox.showerror("Supargus", str(exc))

    def _mark_custom_submitted(self) -> None:
        target = self._selected_custom_target()
        if not target:
            self._log("Select a custom target first.")
            return
        try:
            update_custom_status(self._custom_queue_path(), target.id, "submitted", notes="Submitted through desktop custom removals")
            self._log(f"Marked custom target submitted: {target.domain}")
            self.refresh()
        except Exception as exc:
            self._log(f"Could not update custom target:\n{exc}")

    def _clear_tree(self, tree: "ttk.Treeview") -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_running(self, running: bool, status: str) -> None:
        self.status_var.set(status)
        state = "disabled" if running else "normal"
        for button in self.buttons:
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def _drain_queue(self) -> None:
        while True:
            try:
                event = self.queue.get_nowait()
            except queue.Empty:
                break
            kind, action, value = event
            if kind == "action_ok":
                self._log(f"{action} complete\n{json.dumps(value, indent=2)}")
                self.refresh()
                self._set_running(False, f"{action} complete")
                self._finish_progress_steps("Privacy check complete. Review only the relevant findings below.")
                if action == "workflow":
                    self._show_plain_english_report()
            else:
                self._log(f"ERROR {action}\n{value}")
                self._set_running(False, f"{action} failed")
                self._finish_progress_steps(f"{action.replace('_', ' ')} failed. Check Advanced logs.", failed=True)
                if messagebox:
                    messagebox.showerror("Supargus", str(value))
        self.root.after(100, self._drain_queue)

    def _log(self, text: str) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _choose_workspace(self) -> None:
        if not filedialog:
            return
        selected = filedialog.askdirectory(initialdir=self.workspace_var.get() or ".")
        if selected:
            self.workspace_var.set(selected)
            identity_json = Path(selected) / "identity.json"
            identity_vault = Path(selected) / "identity.sgvault"
            if identity_json.exists():
                self.identity_var.set(str(identity_json))
            elif identity_vault.exists():
                self.identity_var.set(str(identity_vault))
            elif not Path(self.identity_var.get()).exists():
                self.identity_var.set(str(identity_json))
            self.refresh()

    def _choose_identity(self) -> None:
        if not filedialog:
            return
        selected = filedialog.askopenfilename(
            initialdir=str(Path(self.identity_var.get() or self.workspace_var.get()).parent),
            filetypes=(("Supargus identity", "*.sgvault *.json"), ("All files", "*.*")),
        )
        if selected:
            self.identity_var.set(selected)

    def _create_sample_identity(self) -> None:
        path = Path(self.identity_var.get())
        if path.suffix == ".sgvault":
            path = path.with_suffix(".example.json")
            self.identity_var.set(str(path))
        try:
            out = save_identity(sample_identity(), path, force=False)
        except FileExistsError:
            if not messagebox or not messagebox.askyesno("Supargus", f"{path} exists. Replace it?"):
                return
            out = save_identity(sample_identity(), path, force=True)
        self._log(f"Created sample identity template:\n{out}\nEdit it with your real details before scanning.")
        self.status_var.set("Sample identity created")

    def _open_workspace(self) -> None:
        path = Path(self.workspace_var.get())
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(path)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self._log(f"Could not open workspace folder:\n{exc}")


def run_desktop_app(workspace: str | Path = "workspace") -> int:
    if tk is None or ttk is None:
        raise RuntimeError("Python Tk support is not available. Install a Python build with tkinter to run the desktop app.")
    _set_windows_app_id()
    root = tk.Tk()
    SupargusDesktop(root, workspace)
    root.mainloop()
    return 0
