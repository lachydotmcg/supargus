from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from supargus.app import build_state, render_dashboard, run_action
from supargus.broker import build_search_url, score_broker_page, search_brokers
from supargus.bundle import export_bundle
from supargus.cli import build_parser
from supargus.config import WorkflowConfig, load_config, save_default_config
from supargus.custom import add_custom_target, load_custom_targets, prepare_custom_requests, update_custom_status
from supargus.desktop import DESKTOP_ACTIONS
from supargus.forms import build_form_queue, format_form_queue
from supargus.identity import identity_from_dict, sample_identity, save_identity, load_identity
from supargus.mailer import gmail_smtp_config, load_smtp_config, save_smtp_config
from supargus.monitor import diff_matches, diff_payload, save_snapshot, latest_snapshot
from supargus.models import BrokerMatch
from supargus.registry import load_default_brokers, validate_brokers
from supargus.schedule import cron_line, schedule_instructions, schtasks_create_command
from supargus.shortcut import build_shortcut_spec, shortcut_locations
from supargus.takedown import prepare_requests
from supargus.tracker import due_for_follow_up, import_requests, load_tracker, prepare_followups, record_payload, update_status
from supargus.vault import open_file, seal_file, vault_available
from supargus.watchdog import _token_hits, check_env_proxies, check_installed_app_signatures
from supargus.workflow import run_workflow


class SupargusCoreTests(unittest.TestCase):
    def test_identity_roundtrip_json(self) -> None:
        profile = sample_identity()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            save_identity(profile, path)
            loaded = load_identity(path)
        self.assertEqual(loaded.full_name, "Jane Example")
        self.assertEqual(loaded.primary_email(), "jane@example.com")

    def test_default_registry_loads(self) -> None:
        brokers = load_default_brokers()
        self.assertGreaterEqual(len(brokers), 10)
        self.assertTrue(any(broker.id == "fastpeoplesearch" for broker in brokers))

    def test_default_registry_validates(self) -> None:
        self.assertEqual(validate_brokers(load_default_brokers()), [])

    def test_build_search_url_encodes_identity(self) -> None:
        profile = sample_identity()
        url = build_search_url("https://example.com/search?name={name}&state={state}", profile)
        self.assertIn("Jane+Example", url)
        self.assertIn("TX", url)

    def test_score_broker_page(self) -> None:
        profile = sample_identity()
        score, matched, confidence = score_broker_page("Jane Example lives in Austin TX. Email jane@example.com", profile)
        self.assertGreaterEqual(score, 70)
        self.assertIn("name", matched)
        self.assertEqual(confidence, "high")

    def test_score_broker_page_checks_aliases_and_secondary_contacts(self) -> None:
        profile = identity_from_dict(
            {
                "full_name": "Jane Example",
                "aliases": ["J Example"],
                "emails": ["jane@example.com", "jane.alt@example.com"],
                "phones": ["555-1111", "555-2222"],
            }
        )
        score, matched, confidence = score_broker_page("J Example can be reached at jane.alt@example.com", profile)
        self.assertGreaterEqual(score, 55)
        self.assertIn("name", matched)
        self.assertIn("email", matched)
        self.assertEqual(confidence, "medium")

    def test_search_brokers_dry_run(self) -> None:
        profile = sample_identity()
        brokers = load_default_brokers()[:2]
        matches = search_brokers(brokers, profile, fetch=False)
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(match.status == "needs_manual_review" for match in matches))

    def test_prepare_requests_writes_manifest(self) -> None:
        profile = sample_identity()
        brokers = load_default_brokers()[:1]
        match = BrokerMatch(
            broker_id=brokers[0].id,
            broker_name=brokers[0].name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
            evidence_url="https://example.com/profile/jane",
        )
        with tempfile.TemporaryDirectory() as tmp:
            requests, manifest = prepare_requests([match], brokers, profile, tmp)
            self.assertEqual(len(requests), 1)
            self.assertTrue(manifest.exists())
            self.assertTrue(Path(requests[0].file_path).exists())

    def test_prepare_requests_includes_request_only_fetch_errors(self) -> None:
        profile = sample_identity()
        broker = load_default_brokers()[0]
        match = BrokerMatch(
            broker_id=broker.id,
            broker_name=broker.name,
            status="fetch_error",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
            evidence_url="https://example.com/search",
            error="blocked by site",
        )
        with tempfile.TemporaryDirectory() as tmp:
            requests, _ = prepare_requests([match], [broker], profile, tmp)
        self.assertEqual(len(requests), 1)

    def test_env_proxy_detection(self) -> None:
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9999"}, clear=True):
            findings = check_env_proxies()
        self.assertEqual(len(findings), 1)
        self.assertIn("HTTP_PROXY", findings[0].title)

    def test_watchdog_token_hits_include_residential_proxy_terms(self) -> None:
        hits = dict(_token_hits("Oxylabs residential proxy manager and Honeygain client"))
        self.assertIn("oxylabs", hits)
        self.assertIn("honeygain", hits)

    def test_installed_app_signature_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Honeygain").mkdir()
            with patch("supargus.watchdog._install_roots", return_value=[root]):
                findings = check_installed_app_signatures()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "installed_app")

    def test_identity_from_dict(self) -> None:
        profile = identity_from_dict({"full_name": "A B", "emails": ["a@example.com"]})
        self.assertEqual(profile.full_name, "A B")
        self.assertEqual(profile.emails, ["a@example.com"])

    def test_render_dashboard_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = render_dashboard(tmp)
        self.assertIn("Supargus", html)
        self.assertIn("Command Center", html)
        self.assertIn("Run full workflow", html)

    def test_build_state_summarizes_workspace_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broker_matches.json").write_text(
                json.dumps(
                    {
                        "summary": {"checked": 2, "possible_matches": 1, "manual_review": 1},
                        "matches": [{"broker_id": "a", "broker_name": "Broker A", "status": "possible_match"}],
                    }
                ),
                encoding="utf-8",
            )
            (root / "watchdog.json").write_text(
                json.dumps({"summary": {"findings": 1, "high": 1}, "findings": [{"title": "Proxy", "severity": "high"}]}),
                encoding="utf-8",
            )
            state = build_state(root)
        self.assertEqual(state["summary"]["brokers_checked"], 2)
        self.assertEqual(state["summary"]["possible_matches"], 1)
        self.assertEqual(state["summary"]["watchdog_findings"], 1)
        self.assertEqual(len(state["matches"]), 1)

    def test_app_validate_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_action(Path(tmp), {"action": "validate", "workspace": tmp})
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_app_broker_scan_uses_fetch_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            identity = Path(tmp) / "identity.json"
            save_identity(sample_identity(), identity)
            with patch("supargus.app.search_brokers", return_value=[]) as mocked:
                run_action(Path(tmp), {"action": "broker_scan", "workspace": tmp, "identity": str(identity), "fetch": True})
        self.assertTrue(mocked.call_args.kwargs["fetch"])

    def test_gmail_smtp_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smtp.gmail.json"
            config = gmail_smtp_config("jane@example.com", "abcd efgh ijkl mnop")
            save_smtp_config(config, path)
            loaded = load_smtp_config(path)
        self.assertEqual(loaded.host, "smtp.gmail.com")
        self.assertEqual(loaded.port, 465)
        self.assertEqual(loaded.username, "jane@example.com")
        self.assertEqual(loaded.password, "abcdefghijklmnop")

    def test_form_queue_from_manual_request(self) -> None:
        profile = sample_identity()
        broker = load_default_brokers()[0]
        broker.opt_out.contact_email = ""
        match = BrokerMatch(
            broker_id=broker.id,
            broker_name=broker.name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
            evidence_url="https://example.com/profile/jane",
        )
        with tempfile.TemporaryDirectory() as tmp:
            requests, _ = prepare_requests([match], [broker], profile, Path(tmp) / "requests")
            tasks, manifest = build_form_queue(requests, Path(tmp) / "forms" / "forms.json")
            formatted = format_form_queue(tasks)
            self.assertTrue(manifest.exists())
        self.assertEqual(len(tasks), 1)
        self.assertIn(broker.id, formatted)

    def test_custom_removal_queue_and_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "custom" / "custom.json"
            target = add_custom_target(queue_path, "example.com/profile/jane", reason="personal data exposed")
            loaded = load_custom_targets(queue_path)
            requests, manifest = prepare_custom_requests(loaded, sample_identity(), Path(tmp) / "custom" / "requests")
            update_custom_status(queue_path, target.id, "submitted", notes="manual form")
            updated = load_custom_targets(queue_path)
            self.assertTrue(manifest.exists())
        self.assertTrue(target.url.startswith("https://"))
        self.assertEqual(len(requests), 1)
        self.assertEqual(updated[0].status, "submitted")

    def test_desktop_actions_cover_core_workflow(self) -> None:
        actions = {action for action, _, _ in DESKTOP_ACTIONS}
        self.assertIn("workflow", actions)
        self.assertIn("broker_scan", actions)
        self.assertIn("watchdog", actions)
        self.assertIn("mail_preview", actions)
        self.assertIn("form_queue", actions)
        self.assertIn("bundle", actions)

    def test_cli_app_is_desktop_and_web_is_fallback(self) -> None:
        parser = build_parser()
        app_args = parser.parse_args(["app", "--workspace", "workspace"])
        web_args = parser.parse_args(["web", "--workspace", "workspace", "--port", "8765"])
        gmail_args = parser.parse_args(["mail", "setup-gmail", "--email", "a@example.com", "--app-password", "abcdefghijklmnop"])
        form_args = parser.parse_args(["forms", "build", "--requests", "workspace/requests/requests.json"])
        custom_args = parser.parse_args(["custom", "add", "https://example.com/profile/jane"])
        shortcut_args = parser.parse_args(["shortcut", "install", "--workspace", "workspace", "--no-desktop"])
        self.assertEqual(app_args.command, "app")
        self.assertEqual(app_args.workspace, "workspace")
        self.assertEqual(web_args.command, "web")
        self.assertEqual(web_args.port, 8765)
        self.assertEqual(gmail_args.mail_command, "setup-gmail")
        self.assertEqual(form_args.forms_command, "build")
        self.assertEqual(custom_args.custom_command, "add")
        self.assertEqual(shortcut_args.shortcut_command, "install")
        self.assertFalse(shortcut_args.desktop)

    def test_shortcut_spec_builds_desktop_launcher(self) -> None:
        locations = shortcut_locations("Supargus Review")
        spec = build_shortcut_spec("Supargus Review", "workspace", "desktop", working_dir="C:/repo/supargus")
        self.assertEqual(spec.path, locations["desktop"])
        self.assertIn("-m supargus.cli app", spec.arguments)
        self.assertIn("workspace", spec.arguments)
        self.assertEqual(spec.working_dir, Path("C:/repo/supargus"))

    def test_tracker_import_update_and_due(self) -> None:
        profile = sample_identity()
        brokers = load_default_brokers()[:1]
        match = BrokerMatch(
            broker_id=brokers[0].id,
            broker_name=brokers[0].name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
            evidence_url="https://example.com/profile/jane",
        )
        with tempfile.TemporaryDirectory() as tmp:
            requests, _ = prepare_requests([match], brokers, profile, Path(tmp) / "requests")
            tracker = Path(tmp) / "tracker.json"
            records = import_requests(requests, tracker, status="sent", follow_up_after_days=1)
            self.assertEqual(len(records), 1)
            payload = record_payload(records[0])
            self.assertTrue(payload["request_id"].startswith("SG-"))
            self.assertIn("timeline", payload)
            self.assertIn("next_follow_up_at", payload)
            self.assertIn("Name: Jane Example", payload["requested_data"])
            update_status(tracker, brokers[0].id, "waiting", notes="confirmation pending")
            loaded = load_tracker(tracker)
            self.assertEqual(loaded[0].status, "waiting")
            loaded[0].updated_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
            due = due_for_follow_up(loaded)
            self.assertEqual(len(due), 1)

    def test_build_state_includes_tracker_timeline_payload(self) -> None:
        profile = sample_identity()
        broker = load_default_brokers()[0]
        match = BrokerMatch(
            broker_id=broker.id,
            broker_name=broker.name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests, _ = prepare_requests([match], [broker], profile, root / "requests")
            import_requests(requests, root / "tracker.json")
            state = build_state(root)
        self.assertTrue(state["tracker"][0]["request_id"].startswith("SG-"))
        self.assertIn("status_explanation", state["tracker"][0])
        self.assertEqual(state["summary"]["tracker_records"], 1)

    def test_prepare_followups_writes_manifest(self) -> None:
        profile = sample_identity()
        brokers = load_default_brokers()[:1]
        match = BrokerMatch(
            broker_id=brokers[0].id,
            broker_name=brokers[0].name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url="https://example.com/search",
            evidence_url="https://example.com/profile/jane",
        )
        with tempfile.TemporaryDirectory() as tmp:
            requests, _ = prepare_requests([match], brokers, profile, Path(tmp) / "requests")
            tracker = Path(tmp) / "tracker.json"
            records = import_requests(requests, tracker, status="waiting", follow_up_after_days=1)
            records[0].updated_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
            followups, manifest = prepare_followups(records, Path(tmp) / "followups")
            self.assertEqual(len(followups), 1)
            self.assertTrue(manifest.exists())
            self.assertIn("Follow-up", followups[0].subject)

    @unittest.skipUnless(vault_available(), "requires Windows DPAPI")
    def test_vault_roundtrip_file(self) -> None:
        profile = sample_identity()
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "identity.json"
            vault = Path(tmp) / "identity.sgvault"
            opened = Path(tmp) / "opened.json"
            save_identity(profile, plain)
            seal_file(plain, vault)
            open_file(vault, opened)
            loaded = load_identity(opened)
        self.assertEqual(loaded.full_name, profile.full_name)

    @unittest.skipUnless(vault_available(), "requires Windows DPAPI")
    def test_load_identity_from_vault(self) -> None:
        profile = sample_identity()
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "identity.json"
            vault = Path(tmp) / "identity.sgvault"
            save_identity(profile, plain)
            seal_file(plain, vault)
            loaded = load_identity(vault)
        self.assertEqual(loaded.primary_email(), profile.primary_email())

    def test_monitor_diff_detects_reappeared_and_cleared(self) -> None:
        previous = [
            BrokerMatch("a", "Broker A", "no_obvious_match", "unknown", 0, "https://a"),
            BrokerMatch("b", "Broker B", "possible_match", "medium", 50, "https://b"),
        ]
        current = [
            BrokerMatch("a", "Broker A", "possible_match", "high", 80, "https://a"),
            BrokerMatch("b", "Broker B", "no_obvious_match", "unknown", 0, "https://b"),
            BrokerMatch("c", "Broker C", "needs_manual_review", "unknown", 0, "https://c"),
        ]
        changes = diff_matches(previous, current)
        types = {change.change_type for change in changes}
        self.assertEqual(types, {"reappeared", "cleared", "new_match"})

    def test_monitor_snapshot_and_payload(self) -> None:
        payload = {
            "matches": [
                {
                    "broker_id": "a",
                    "broker_name": "Broker A",
                    "status": "no_obvious_match",
                    "confidence": "unknown",
                    "score": 0,
                    "search_url": "https://a",
                }
            ]
        }
        current = {
            "matches": [
                {
                    "broker_id": "a",
                    "broker_name": "Broker A",
                    "status": "possible_match",
                    "confidence": "high",
                    "score": 90,
                    "search_url": "https://a",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            previous_path = Path(tmp) / "previous.json"
            current_path = Path(tmp) / "current.json"
            previous_path.write_text(json.dumps(payload), encoding="utf-8")
            current_path.write_text(json.dumps(current), encoding="utf-8")
            snapshot = save_snapshot(previous_path, Path(tmp) / "history")
            self.assertTrue(snapshot.exists())
            self.assertEqual(latest_snapshot(Path(tmp) / "history"), Path(tmp) / "history" / "latest.json")
            diff = diff_payload(previous_path, current_path)
        self.assertEqual(diff["summary"]["reappeared"], 1)

    def test_export_bundle_includes_manifest_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requests").mkdir()
            (root / "followups").mkdir()
            (root / "broker_matches.json").write_text('{"matches":[]}', encoding="utf-8")
            (root / "requests" / "demo.txt").write_text("hello", encoding="utf-8")
            (root / "followups" / "demo_followup.txt").write_text("checking in", encoding="utf-8")
            bundle_path, manifest = export_bundle(root, root / "bundle.zip")
            self.assertEqual(manifest["file_count"], 3)
            self.assertTrue(all(item["sha256"] for item in manifest["files"]))
            with zipfile.ZipFile(bundle_path) as zf:
                names = set(zf.namelist())
        self.assertIn("manifest.json", names)
        self.assertIn("broker_matches.json", names)
        self.assertIn("requests/demo.txt", names)
        self.assertIn("followups/demo_followup.txt", names)

    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "supargus.config.json"
            save_default_config(path)
            config = load_config(path)
        self.assertEqual(config.workspace, "workspace")
        self.assertTrue(config.watchdog)

    def test_schedule_commands_include_workflow(self) -> None:
        win = schtasks_create_command("supargus.config.json", time="08:30")
        cron = cron_line("supargus.config.json", hour=8, minute=30)
        instructions = schedule_instructions("supargus.config.json", time="08:30")
        self.assertIn("workflow", win)
        self.assertIn("/ST 08:30", win)
        self.assertTrue(cron.startswith("30 8 * * *"))
        self.assertIn("Windows Task Scheduler", instructions)

    def test_workflow_run_writes_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = root / "identity.json"
            save_identity(sample_identity(), identity)
            config = WorkflowConfig(
                identity=str(identity),
                workspace=str(root / "workspace"),
                history_dir=str(root / "history"),
                tracker=str(root / "workspace" / "tracker.json"),
                requests_dir=str(root / "workspace" / "requests"),
                followups_dir=str(root / "workspace" / "followups"),
                bundle_path=str(root / "workspace" / "bundle.zip"),
                limit=2,
                watchdog=False,
            )
            outputs = run_workflow(config)
            workspace = root / "workspace"
            self.assertTrue((workspace / "broker_matches.json").exists())
            self.assertTrue((workspace / "requests" / "requests.json").exists())
            self.assertTrue((workspace / "bundle.zip").exists())
            self.assertEqual(outputs["request_count"], 2)


if __name__ == "__main__":
    unittest.main()
