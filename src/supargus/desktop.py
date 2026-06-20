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
from .identity import load_identity, sample_identity, save_identity

try:  # Keep imports optional so headless test environments can still import the package.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - depends on local Python GUI support.
    tk = None
    ttk = None
    filedialog = None
    messagebox = None


GUIDE_STEPS = (
    ("1", "Set up your identity", "Use a local identity vault or sample profile so Supargus knows what to search for."),
    ("2", "Run a verified scan", "Supargus tries lightweight public searches first, then marks private brokers as request-only."),
    ("3", "Review evidence", "Check matches, blocked searches, and this-PC findings before sending anything."),
    ("4", "Take action", "Prepare removals, build form tasks, preview emails, and export receipts from your machine."),
)


DESKTOP_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("workflow", "Run privacy check", "Scan exposure, create drafts, update tracker, and export receipts."),
    ("broker_scan", "Scan data brokers", "Check the broker registry for likely exposure."),
    ("watchdog", "Scan this PC", "Look for proxy, extension, startup, and bandwidth-sharing signals."),
    ("prepare_requests", "Prepare removals", "Create readable takedown drafts from broker matches."),
    ("form_queue", "Build form queue", "Collect brokers that need manual opt-out forms."),
    ("mail_preview", "Preview emails", "Review request emails before anything is sent."),
    ("mail_send", "Send reviewed emails", "Send approved requests through your SMTP or Gmail app password config."),
    ("tracker_import", "Import tracker", "Track requests, status, and follow-up dates."),
    ("followups", "Generate follow-ups", "Create follow-up drafts for pending requests."),
    ("bundle", "Export receipts", "Zip evidence, reports, drafts, and hashes."),
    ("guide_take_action", "Guide: take action", "Prepare requests, tracker records, form tasks, and receipts from current results."),
    ("validate", "Validate registry", "Check broker adapters before scanning."),
)


COLORS = {
    "bg": "#f4f6fb",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "nav": "#ffffff",
    "line": "#e4e9f2",
    "ink": "#111827",
    "muted": "#64748b",
    "soft": "#eef3f9",
    "navy": "#101923",
    "blue": "#101923",
    "blue_dark": "#243447",
    "yellow": "#f6b40b",
    "yellow_soft": "#fff6d8",
    "green": "#16a34a",
    "green_soft": "#eaf8ef",
    "red": "#b42318",
    "red_soft": "#fff0ed",
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


class SupargusDesktop:
    def __init__(self, root: "tk.Tk", workspace: str | Path) -> None:
        self.root = root
        self.queue: "queue.Queue[tuple[str, str, Any]]" = queue.Queue()
        self.buttons: list["tk.Widget"] = []
        self.nav_buttons: dict[str, "tk.Button"] = {}
        self.pages: dict[str, "tk.Frame"] = {}
        self.form_tasks: list[FormTask] = []
        self.custom_targets: list[Any] = []
        self.state: dict[str, Any] = {}

        workspace_path = Path(workspace)
        self.workspace_var = tk.StringVar(value=str(workspace_path))
        self.identity_var = tk.StringVar(value=str(workspace_path / "identity.sgvault"))
        self.config_var = tk.StringVar(value="supargus.config.json")
        self.smtp_var = tk.StringVar(value=str(workspace_path / "smtp.gmail.json"))
        self.limit_var = tk.StringVar(value="10")
        self.custom_url_var = tk.StringVar(value="")
        self.custom_reason_var = tk.StringVar(value="personal data exposed")
        self.status_var = tk.StringVar(value="Ready")

        self.metric_vars = {
            "brokers": tk.StringVar(value="0"),
            "matches": tk.StringVar(value="0"),
            "watchdog": tk.StringVar(value="0"),
            "request_only": tk.StringVar(value="0"),
            "changes": tk.StringVar(value="0"),
            "requests": tk.StringVar(value="0"),
            "bundle": tk.StringVar(value="0 B"),
            "score": tk.StringVar(value="100"),
            "score_label": tk.StringVar(value="Protected"),
        }

        self._configure_window()
        self._load_logo()
        self._build_layout()
        self.refresh()
        self.show_page("home")
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
            ("home", "Dashboard"),
            ("guide", "Guide"),
            ("cleanup", "Cleanup"),
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
        page = tk.Frame(self.content, bg=COLORS["bg"])
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.pages[key] = page
        return page

    def show_page(self, key: str) -> None:
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            selected = name == key
            button.configure(bg=COLORS["yellow_soft"] if selected else COLORS["nav"], fg=COLORS["blue"] if selected else COLORS["muted"])

    def _card(self, parent: "tk.Widget", row: int, column: int, *, columnspan: int = 1, rowspan: int = 1, padx=(0, 14), pady=(0, 14)) -> "tk.Frame":
        frame = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
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
            padx=18,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        return button

    def _build_home_page(self) -> None:
        page = self._page("home")
        page.columnconfigure(0, weight=2)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)

        header = tk.Frame(page, bg=COLORS["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        tk.Label(header, text="Your privacy, in plain English.", bg=COLORS["bg"], fg=COLORS["ink"], font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Scan data brokers, prepare removals, and check this PC without handing your identity to another service.",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(4, 0))

        left = tk.Frame(page, bg=COLORS["bg"])
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)
        left.rowconfigure(2, weight=1)

        score_card = self._card(left, 0, 0, columnspan=2, padx=(0, 14))
        score_card.columnconfigure(0, weight=1)
        score_card.columnconfigure(1, weight=1)
        tk.Label(score_card, text="Privacy score", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 0))
        tk.Label(score_card, textvariable=self.metric_vars["score"], bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 50, "bold")).grid(row=1, column=0, sticky="w", padx=24)
        self.score_label_widget = tk.Label(score_card, textvariable=self.metric_vars["score_label"], bg=COLORS["surface"], fg=COLORS["green"], font=("Segoe UI", 16, "bold"))
        self.score_label_widget.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 20))
        self.score_canvas = tk.Canvas(score_card, width=250, height=150, bg=COLORS["surface"], highlightthickness=0)
        self.score_canvas.grid(row=0, column=1, rowspan=3, sticky="e", padx=24, pady=18)

        self._home_action(left, 1, 0, "Scan exposure", "Check data brokers and people-search sites.", "broker_scan", "Scan now", primary=True)
        self._home_action(left, 1, 1, "Prepare removals", "Create request drafts you can inspect.", "prepare_requests", "Prepare")
        self._home_action(left, 2, 0, "Scan this PC", "Find proxy and bandwidth-sharing signals.", "watchdog", "Scan PC")
        self._home_action(left, 2, 1, "Export receipts", "Bundle reports, drafts, and hashes.", "bundle", "Export")

        advisor = self._card(page, 1, 1, padx=(0, 0))
        advisor.columnconfigure(0, weight=1)
        tk.Label(advisor, text="Trusted advisor", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
        self.next_step_title = tk.Label(advisor, text="Run a privacy check", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 16, "bold"), wraplength=270, justify="left")
        self.next_step_title.pack(anchor="w", padx=22)
        self.next_step_body = tk.Label(advisor, text="", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=280, justify="left")
        self.next_step_body.pack(anchor="w", padx=22, pady=(8, 18))
        workflow_button = self._button(advisor, "Run full privacy check", lambda: self.run_action("workflow"), primary=True)
        workflow_button.pack(anchor="w", padx=22, pady=(0, 16))
        self.buttons.append(workflow_button)

        metrics = tk.Frame(advisor, bg=COLORS["surface"])
        metrics.pack(fill="x", padx=22, pady=(4, 20))
        for label, var in (
            ("Possible matches", self.metric_vars["matches"]),
            ("Request-only brokers", self.metric_vars["request_only"]),
            ("Watchdog findings", self.metric_vars["watchdog"]),
            ("Draft requests", self.metric_vars["requests"]),
            ("Evidence bundle", self.metric_vars["bundle"]),
        ):
            row = tk.Frame(metrics, bg=COLORS["surface"])
            row.pack(fill="x", pady=6)
            tk.Label(row, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, textvariable=var, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 10, "bold")).pack(side="right")

    def _build_guide_page(self) -> None:
        page = self._page("guide")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "First privacy check", "A guided pass from local setup to reviewed cleanup action.")

        checklist = self._card(page, 1, 0, rowspan=2)
        checklist.columnconfigure(0, weight=1)
        tk.Label(checklist, text="What happens first", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=20, pady=(18, 8))
        for number, title, body in GUIDE_STEPS:
            row = tk.Frame(checklist, bg=COLORS["surface"])
            row.pack(fill="x", padx=20, pady=8)
            badge = tk.Label(row, text=number, bg=COLORS["yellow_soft"], fg=COLORS["blue"], width=3, font=("Segoe UI", 10, "bold"))
            badge.pack(side="left", ipady=5)
            copy = tk.Frame(row, bg=COLORS["surface"])
            copy.pack(side="left", fill="x", expand=True, padx=(12, 0))
            tk.Label(copy, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
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
        guide_button = self._button(actions, "Run guided scan", lambda: self.run_action("workflow"), primary=True)
        guide_button.pack(anchor="w", padx=20, pady=(0, 10))
        self.buttons.append(guide_button)
        self._button(actions, "Open cleanup view", lambda: self.show_page("cleanup")).pack(anchor="w", padx=20, pady=(0, 18))

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

    def _home_action(self, parent: "tk.Widget", row: int, column: int, title: str, body: str, action: str, button_text: str, *, primary: bool = False) -> None:
        card = self._card(parent, row, column)
        tk.Label(card, text=title, bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=20, pady=(18, 3))
        tk.Label(card, text=body, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=300, justify="left").pack(anchor="w", padx=20)
        button = self._button(card, button_text, lambda: self.run_action(action), primary=primary)
        button.pack(anchor="w", padx=20, pady=18)
        self.buttons.append(button)

    def _build_cleanup_page(self) -> None:
        page = self._page("cleanup")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "Data broker cleanup", "See likely exposure, then create removal drafts you can review.")

        actions = tk.Frame(page, bg=COLORS["bg"])
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for text, action, primary in (
            ("Scan brokers", "broker_scan", True),
            ("Prepare removals", "prepare_requests", False),
            ("Build form queue", "form_queue", False),
            ("Preview emails", "mail_preview", False),
        ):
            button = self._button(actions, text, lambda value=action: self.run_action(value), primary=primary)
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)

        table_card = self._card(page, 2, 0, padx=(0, 0))
        table_card.rowconfigure(0, weight=1)
        table_card.columnconfigure(0, weight=1)
        self.broker_tree = self._tree(table_card, ("broker", "status", "confidence", "score", "url"))

    def _build_watchdog_page(self) -> None:
        page = self._page("watchdog")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "This PC", "Look for local proxy, extension, startup, and bandwidth-sharing risks.")

        top = tk.Frame(page, bg=COLORS["bg"])
        top.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        button = self._button(top, "Scan this PC", lambda: self.run_action("watchdog"), primary=True)
        button.pack(side="left")
        self.buttons.append(button)
        tk.Label(top, text="No action is taken automatically. Findings are review-only.", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=14)

        card = self._card(page, 2, 0, padx=(0, 0))
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)
        self.watchdog_text = self._text_panel(card, dark=False)

    def _build_removals_page(self) -> None:
        page = self._page("removals")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        self._section_header(page, "Removal workbench", "Review form tasks and add custom removal targets that are outside the broker registry.")

        self._build_forms_panel(page)
        self._build_custom_panel(page)

    def _build_forms_panel(self, page: "tk.Frame") -> None:
        card = self._card(page, 1, 0, rowspan=2)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        tk.Label(card, text="Manual form queue", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        controls = tk.Frame(card, bg=COLORS["surface"])
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=12)
        for text, command, primary in (
            ("Open form", self._open_selected_form, True),
            ("Copy request", self._copy_selected_form, False),
            ("Mark submitted", self._mark_selected_form_submitted, False),
        ):
            self._button(controls, text, command, primary=primary).pack(side="left", padx=(0, 8))
        body = tk.Frame(card, bg=COLORS["surface"])
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.forms_tree = self._tree(body, ("broker", "status", "url"))

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
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=150, anchor="w")
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

    def run_action(self, action: str) -> None:
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
        payload = self._payload(action)
        workspace = Path(payload["workspace"])

        def worker() -> None:
            try:
                result = run_action(workspace, payload)
                self.queue.put(("action_ok", action, result))
            except Exception as exc:
                self.queue.put(("action_error", action, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self) -> None:
        self.state = build_state(self.workspace_var.get())
        summary = self.state["summary"]
        score = _privacy_score(summary)
        label, label_color = _score_label(score)

        self.metric_vars["brokers"].set(str(summary["brokers_checked"]))
        self.metric_vars["matches"].set(str(summary["possible_matches"]))
        self.metric_vars["request_only"].set(str(summary.get("request_only", 0)))
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
        self._populate_brokers(self.state["matches"])
        self._populate_watchdog(self.state["findings"])
        self._populate_tracker(self.state["tracker"])
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
        if matches and not requests:
            title = "Prepare removal drafts"
            body = "Supargus found possible broker exposure. Create drafts first, then review before sending anything."
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

    def _populate_brokers(self, items: list[dict[str, Any]]) -> None:
        self._clear_tree(self.broker_tree)
        if not items:
            self.broker_tree.insert("", "end", values=("No broker scan yet", "Run Scan brokers", "", "", ""))
            return
        for item in items:
            self.broker_tree.insert("", "end", values=(item.get("broker_name", ""), item.get("status", ""), item.get("confidence", ""), item.get("score", ""), item.get("search_url", "")))

    def _populate_watchdog(self, items: list[dict[str, Any]]) -> None:
        self.watchdog_text.configure(state="normal")
        self.watchdog_text.delete("1.0", "end")
        if not items:
            self.watchdog_text.insert("end", "No watchdog data yet. Run Scan this PC.")
        for item in items:
            self.watchdog_text.insert("end", f"{item.get('severity', '').upper()}  {item.get('title', '')}\n{item.get('detail', '')}\nEvidence: {item.get('evidence', '')}\n\n")
        self.watchdog_text.configure(state="disabled")

    def _populate_tracker(self, items: list[dict[str, Any]]) -> None:
        if not hasattr(self, "tracker_tree"):
            return
        self._clear_tree(self.tracker_tree)
        for item in items:
            self.tracker_tree.insert("", "end", values=(item.get("broker_name", ""), item.get("status", ""), item.get("delivery", ""), item.get("updated_at", "")))

    def _populate_forms(self, state: dict[str, Any]) -> None:
        forms_path = state["paths"].get("forms", "")
        try:
            self.form_tasks = load_form_queue(forms_path) if forms_path else []
        except Exception:
            self.form_tasks = []
        self._clear_tree(self.forms_tree)
        if not self.form_tasks:
            self.forms_tree.insert("", "end", iid="form-empty", values=("No form tasks yet", "Build form queue", ""))
            return
        for idx, task in enumerate(self.form_tasks):
            self.forms_tree.insert("", "end", iid=f"form-{idx}", values=(task.broker_name, task.status, task.opt_out_url))

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
        text = f"Broker: {task.broker_name}\nOpt-out form: {task.opt_out_url}\nProfile: {task.profile_url}\n\n{task.request_body.strip()}\n"
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
            else:
                self._log(f"ERROR {action}\n{value}")
                self._set_running(False, f"{action} failed")
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
            if not self.identity_var.get():
                self.identity_var.set(str(Path(selected) / "identity.sgvault"))
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
