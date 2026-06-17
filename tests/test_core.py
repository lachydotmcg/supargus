from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from supargus.app import render_dashboard
from supargus.broker import build_search_url, score_broker_page, search_brokers
from supargus.identity import identity_from_dict, sample_identity, save_identity, load_identity
from supargus.monitor import diff_matches, diff_payload, save_snapshot, latest_snapshot
from supargus.models import BrokerMatch
from supargus.registry import load_default_brokers, validate_brokers
from supargus.takedown import prepare_requests
from supargus.tracker import due_for_follow_up, import_requests, load_tracker, update_status
from supargus.vault import open_file, seal_file, vault_available
from supargus.watchdog import check_env_proxies


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

    def test_env_proxy_detection(self) -> None:
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9999"}, clear=True):
            findings = check_env_proxies()
        self.assertEqual(len(findings), 1)
        self.assertIn("HTTP_PROXY", findings[0].title)

    def test_identity_from_dict(self) -> None:
        profile = identity_from_dict({"full_name": "A B", "emails": ["a@example.com"]})
        self.assertEqual(profile.full_name, "A B")
        self.assertEqual(profile.emails, ["a@example.com"])

    def test_render_dashboard_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = render_dashboard(tmp)
        self.assertIn("Supargus", html)
        self.assertIn("Run supargus brokers find", html)

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
            update_status(tracker, brokers[0].id, "waiting", notes="confirmation pending")
            loaded = load_tracker(tracker)
            self.assertEqual(loaded[0].status, "waiting")
            loaded[0].updated_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
            due = due_for_follow_up(loaded)
            self.assertEqual(len(due), 1)

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


if __name__ == "__main__":
    unittest.main()
