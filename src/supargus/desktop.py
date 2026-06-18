"""Native desktop application for Supargus."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

from .app import build_state, run_action
from .identity import sample_identity, save_identity

try:  # Keep imports optional so headless test environments can still import the package.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - depends on local Python GUI support.
    tk = None
    ttk = None
    filedialog = None
    messagebox = None


DESKTOP_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("workflow", "Run Full Workflow", "Scan, diff, watchdog, drafts, tracker, follow-ups, bundle."),
    ("broker_scan", "Broker Scan", "Generate broker evidence and the local report."),
    ("watchdog", "Watchdog Scan", "Inspect this machine for local privacy risks."),
    ("prepare_requests", "Prepare Requests", "Create takedown drafts from broker matches."),
    ("form_queue", "Build Form Queue", "Collect brokers that require manual opt-out forms."),
    ("mail_preview", "Preview Email Queue", "Review the email requests ready to send."),
    ("mail_send", "Send Reviewed Emails", "Send request drafts through your SMTP or Gmail app password config."),
    ("tracker_import", "Import Tracker", "Track request status and follow-up windows."),
    ("followups", "Generate Follow-Ups", "Create follow-up drafts for tracked requests."),
    ("bundle", "Export Bundle", "Zip evidence, drafts, reports, and hashes."),
    ("validate", "Validate Registry", "Check broker adapters before scanning."),
)


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


class SupargusDesktop:
    def __init__(self, root: "tk.Tk", workspace: str | Path) -> None:
        self.root = root
        self.queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.buttons: list["tk.Widget"] = []

        workspace_path = Path(workspace)
        self.workspace_var = tk.StringVar(value=str(workspace_path))
        self.identity_var = tk.StringVar(value=str(workspace_path / "identity.sgvault"))
        self.config_var = tk.StringVar(value="supargus.config.json")
        self.smtp_var = tk.StringVar(value=str(workspace_path / "smtp.gmail.json"))
        self.limit_var = tk.StringVar(value="10")
        self.status_var = tk.StringVar(value="Ready")

        self.metric_vars = {
            "brokers": tk.StringVar(value="0"),
            "matches": tk.StringVar(value="0"),
            "watchdog": tk.StringVar(value="0"),
            "changes": tk.StringVar(value="0"),
            "requests": tk.StringVar(value="0"),
            "bundle": tk.StringVar(value="0 B"),
        }

        self._configure_window()
        self._build_layout()
        self.refresh()
        self.root.after(100, self._drain_queue)

    def _configure_window(self) -> None:
        self.root.title("Supargus")
        self.root.geometry("1280x820")
        self.root.minsize(1080, 700)
        self.root.configure(bg="#f5f8fa")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background="#f5f8fa")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("Sidebar.TFrame", background="#102027")
        style.configure("Title.TLabel", background="#f5f8fa", foreground="#102027", font=("Segoe UI", 28, "bold"))
        style.configure("Subtitle.TLabel", background="#f5f8fa", foreground="#52656d", font=("Segoe UI", 11))
        style.configure("SidebarTitle.TLabel", background="#102027", foreground="#f4fbfb", font=("Segoe UI", 17, "bold"))
        style.configure("SidebarText.TLabel", background="#102027", foreground="#b8ccd2", font=("Segoe UI", 9))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#102027", font=("Segoe UI", 13, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#52656d", font=("Segoe UI", 9))
        style.configure("MetricValue.TLabel", background="#ffffff", foreground="#102027", font=("Segoe UI", 22, "bold"))
        style.configure("MetricLabel.TLabel", background="#ffffff", foreground="#52656d", font=("Segoe UI", 9))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.configure("Ghost.TButton", font=("Segoe UI", 9), padding=(10, 7))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=28, background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_layout(self) -> None:
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=252)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(24, 12))
        ttk.Label(brand, text="Supargus", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Desktop privacy operations", style="SidebarText.TLabel").pack(anchor="w", pady=(2, 0))

        nav = ttk.Frame(sidebar, style="Sidebar.TFrame")
        nav.grid(row=1, column=0, sticky="ew", padx=18, pady=18)
        for label, tab in (
            ("Command Center", "commands"),
            ("Broker Radar", "brokers"),
            ("Local Watchdog", "watchdog"),
            ("Monitor Changes", "changes"),
                ("Compliance Tracker", "tracker"),
                ("Form Queue", "forms"),
                ("Run Log", "log"),
        ):
            button = tk.Button(
                nav,
                text=label,
                anchor="w",
                command=lambda name=tab: self._select_tab(name),
                bg="#102027",
                fg="#d7e7eb",
                activebackground="#17333c",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                padx=12,
                pady=9,
                font=("Segoe UI", 10),
            )
            button.pack(fill="x", pady=2)

        note = tk.Label(
            sidebar,
            text="Runs locally as a desktop app. No browser tab required. Cloud AI remains optional.",
            bg="#102027",
            fg="#bdd3d8",
            wraplength=198,
            justify="left",
            font=("Segoe UI", 9),
        )
        note.grid(row=2, column=0, sticky="ew", padx=22, pady=(12, 0))

        main = ttk.Frame(shell)
        main.grid(row=0, column=1, sticky="nsew", padx=24, pady=22)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Command your privacy cleanup.", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Scan brokers, prepare takedowns, monitor reappearances, and keep the receipts from one native window.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(header, textvariable=self.status_var, style="Subtitle.TLabel").grid(row=0, column=1, sticky="e")

        self._build_metrics(main)
        self._build_notebook(main)

    def _build_metrics(self, parent: "ttk.Frame") -> None:
        metrics = ttk.Frame(parent)
        metrics.grid(row=1, column=0, sticky="ew", pady=(18, 16))
        for idx in range(6):
            metrics.columnconfigure(idx, weight=1, uniform="metric")
        for idx, (key, label) in enumerate(
            (
                ("brokers", "Brokers checked"),
                ("matches", "Possible matches"),
                ("watchdog", "Watchdog findings"),
                ("changes", "Scan changes"),
                ("requests", "Draft requests"),
                ("bundle", "Bundle size"),
            )
        ):
            card = ttk.Frame(metrics, style="Panel.TFrame", padding=(14, 12))
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))
            ttk.Label(card, text=label, style="MetricLabel.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=self.metric_vars[key], style="MetricValue.TLabel").pack(anchor="w", pady=(5, 0))

    def _build_notebook(self, parent: "ttk.Frame") -> None:
        self.notebook = ttk.Notebook(parent)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        self.commands_tab = ttk.Frame(self.notebook, padding=16)
        self.brokers_tab = ttk.Frame(self.notebook, padding=16)
        self.watchdog_tab = ttk.Frame(self.notebook, padding=16)
        self.changes_tab = ttk.Frame(self.notebook, padding=16)
        self.tracker_tab = ttk.Frame(self.notebook, padding=16)
        self.forms_tab = ttk.Frame(self.notebook, padding=16)
        self.log_tab = ttk.Frame(self.notebook, padding=16)

        for tab, label in (
            (self.commands_tab, "Command Center"),
            (self.brokers_tab, "Broker Radar"),
            (self.watchdog_tab, "Local Watchdog"),
            (self.changes_tab, "Monitor Changes"),
            (self.tracker_tab, "Compliance Tracker"),
            (self.forms_tab, "Form Queue"),
            (self.log_tab, "Run Log"),
        ):
            self.notebook.add(tab, text=label)

        self._build_command_tab()
        self.broker_tree = self._tree(self.brokers_tab, ("broker", "status", "confidence", "score", "url"))
        self.watchdog_text = self._text_panel(self.watchdog_tab)
        self.change_tree = self._tree(self.changes_tab, ("broker", "change", "previous", "current", "detail"))
        self.tracker_tree = self._tree(self.tracker_tab, ("broker", "status", "delivery", "updated"))
        self.forms_text = self._text_panel(self.forms_tab)
        self.log_text = self._text_panel(self.log_tab)
        self._log("Supargus desktop is ready.")

    def _build_command_tab(self) -> None:
        self.commands_tab.columnconfigure(0, weight=1)
        self.commands_tab.columnconfigure(1, weight=1)

        setup = ttk.Frame(self.commands_tab, style="Panel.TFrame", padding=16)
        setup.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Local Workspace", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self._field(setup, 1, "Workspace", self.workspace_var, self._choose_workspace)
        self._field(setup, 2, "Identity", self.identity_var, self._choose_identity)
        self._field(setup, 3, "Config", self.config_var, None)
        self._field(setup, 4, "Gmail / SMTP config", self.smtp_var, None)
        self._field(setup, 5, "Limit", self.limit_var, None)

        quick = ttk.Frame(setup, style="Panel.TFrame")
        quick.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(quick, text="Create Sample Identity", style="Ghost.TButton", command=self._create_sample_identity).pack(side="left")
        ttk.Button(quick, text="Refresh Results", style="Ghost.TButton", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(quick, text="Open Workspace Folder", style="Ghost.TButton", command=self._open_workspace).pack(side="left")

        for idx, (action, title, detail) in enumerate(DESKTOP_ACTIONS):
            card = ttk.Frame(self.commands_tab, style="Panel.TFrame", padding=16)
            card.grid(row=1 + idx // 2, column=idx % 2, sticky="nsew", padx=(0 if idx % 2 == 0 else 10, 0), pady=8)
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=title, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=detail, style="Muted.TLabel", wraplength=360).grid(row=1, column=0, sticky="w", pady=(4, 10))
            button = ttk.Button(card, text="Run", style="Primary.TButton", command=lambda value=action: self.run_action(value))
            button.grid(row=2, column=0, sticky="w")
            self.buttons.append(button)

    def _field(self, parent: "ttk.Frame", row: int, label: str, variable: "tk.StringVar", browse: Any) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=10, pady=(10, 0))
        if browse:
            ttk.Button(parent, text="Browse", style="Ghost.TButton", command=browse).grid(row=row, column=2, sticky="e", pady=(10, 0))

    def _tree(self, parent: "ttk.Frame", columns: tuple[str, ...]) -> "ttk.Treeview":
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=150, anchor="w")
        ybar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ybar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        return tree

    def _text_panel(self, parent: "ttk.Frame") -> "tk.Text":
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        text = tk.Text(
            parent,
            bg="#071316",
            fg="#d7f5ec",
            insertbackground="#d7f5ec",
            relief="flat",
            padx=14,
            pady=12,
            wrap="word",
            font=("Consolas", 10),
        )
        ybar = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=ybar.set)
        text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        return text

    def _select_tab(self, key: str) -> None:
        mapping = {
            "commands": self.commands_tab,
            "brokers": self.brokers_tab,
            "watchdog": self.watchdog_tab,
            "changes": self.changes_tab,
            "tracker": self.tracker_tab,
            "forms": self.forms_tab,
            "log": self.log_tab,
        }
        self.notebook.select(mapping[key])

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
        }

    def run_action(self, action: str) -> None:
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
        state = build_state(self.workspace_var.get())
        summary = state["summary"]
        self.metric_vars["brokers"].set(str(summary["brokers_checked"]))
        self.metric_vars["matches"].set(str(summary["possible_matches"]))
        self.metric_vars["watchdog"].set(str(summary["watchdog_findings"]))
        self.metric_vars["changes"].set(str(summary["scan_changes"]))
        self.metric_vars["requests"].set(str(summary["request_drafts"]))
        self.metric_vars["bundle"].set(_fmt_bytes(int(summary["bundle_size"])))
        self._populate_brokers(state["matches"])
        self._populate_watchdog(state["findings"])
        self._populate_changes(state["changes"])
        self._populate_tracker(state["tracker"])
        self._populate_forms(state)

    def _populate_brokers(self, items: list[dict[str, Any]]) -> None:
        self._clear_tree(self.broker_tree)
        for item in items:
            self.broker_tree.insert(
                "",
                "end",
                values=(
                    item.get("broker_name", ""),
                    item.get("status", ""),
                    item.get("confidence", ""),
                    item.get("score", ""),
                    item.get("search_url", ""),
                ),
            )

    def _populate_watchdog(self, items: list[dict[str, Any]]) -> None:
        self.watchdog_text.configure(state="normal")
        self.watchdog_text.delete("1.0", "end")
        if not items:
            self.watchdog_text.insert("end", "No watchdog data yet. Run Watchdog Scan.")
        for item in items:
            self.watchdog_text.insert(
                "end",
                f"{item.get('severity', '').upper()}  {item.get('title', '')}\n"
                f"{item.get('detail', '')}\n"
                f"Evidence: {item.get('evidence', '')}\n\n",
            )
        self.watchdog_text.configure(state="disabled")

    def _populate_changes(self, items: list[dict[str, Any]]) -> None:
        self._clear_tree(self.change_tree)
        for item in items:
            self.change_tree.insert(
                "",
                "end",
                values=(
                    item.get("broker_name", ""),
                    item.get("change_type", ""),
                    item.get("previous_status", ""),
                    item.get("current_status", ""),
                    item.get("detail", ""),
                ),
            )

    def _populate_tracker(self, items: list[dict[str, Any]]) -> None:
        self._clear_tree(self.tracker_tree)
        for item in items:
            self.tracker_tree.insert(
                "",
                "end",
                values=(
                    item.get("broker_name", ""),
                    item.get("status", ""),
                    item.get("delivery", ""),
                    item.get("updated_at", ""),
                ),
            )

    def _populate_forms(self, state: dict[str, Any]) -> None:
        forms_path = state["paths"].get("forms", "")
        tasks = []
        try:
            if forms_path:
                data = json.loads(Path(forms_path).read_text(encoding="utf-8"))
                tasks = data.get("tasks", []) if isinstance(data, dict) else []
        except Exception:
            tasks = []
        self.forms_text.configure(state="normal")
        self.forms_text.delete("1.0", "end")
        if not tasks:
            self.forms_text.insert("end", "No manual form tasks yet. Prepare requests, then build the form queue.")
        for item in tasks:
            self.forms_text.insert(
                "end",
                f"{item.get('status', '').upper()}  {item.get('broker_name', '')}\n"
                f"Opt-out form: {item.get('opt_out_url', '')}\n"
                f"Profile: {item.get('profile_url', '')}\n\n"
                f"{item.get('request_body', '').strip()}\n\n---\n\n",
            )
        self.forms_text.configure(state="disabled")

    def _clear_tree(self, tree: "ttk.Treeview") -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_running(self, running: bool, status: str) -> None:
        self.status_var.set(status)
        for button in self.buttons:
            button.configure(state="disabled" if running else "normal")

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
