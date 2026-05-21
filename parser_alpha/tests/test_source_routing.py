from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from parsers_pkg.source_routing import SourceHealthStore, SourceRunTelemetry, adapt_query_for_source, resolve_route
from parsers_pkg.sources import build_default_source_registry


class TestSourceRouting(unittest.TestCase):
    def test_query_adaptation(self):
        q1, r1 = adapt_query_for_source("Crossref", "nickel catalyst")
        self.assertEqual(q1, "nickel catalyst")
        self.assertEqual(r1, "identity")

        q2, r2 = adapt_query_for_source("OpenAlex", "nickel AND superalloy OR oxidation")
        self.assertEqual(q2, "nickel AND superalloy OR oxidation")
        self.assertEqual(r2, "identity")

        q3, r3 = adapt_query_for_source("arXiv", "никель суперсплавы")
        self.assertEqual(q3, "nickel superalloys")
        self.assertEqual(r3, "ru_to_en_token_rewrite")

        q4, r4 = adapt_query_for_source("CyberLeninka", "металлы никель")
        self.assertEqual(q4, "металлы никель")
        self.assertEqual(r4, "identity")

    def test_query_translation_can_be_disabled_for_dry_run(self):
        with patch("parsers_pkg.source_routing.get_shared_query_translator") as mocked_translator:
            mocked_translator.side_effect = AssertionError("translator must not be called in dry-run routing")
            query, reason = adapt_query_for_source(
                "Crossref",
                "никелевые жаропрочные сплавы",
                allow_translation=False,
            )

        self.assertEqual(query, "никелевые жаропрочные сплавы")
        self.assertIn("translation_skipped", reason)

    def test_health_penalty_affects_route(self):
        registry = build_default_source_registry()
        with tempfile.TemporaryDirectory() as td:
            store = SourceHealthStore(Path(td) / "source_health.json")
            for _ in range(5):
                store.record(
                    SourceRunTelemetry(
                        source="OpenAlex",
                        success=False,
                        parsed_count=0,
                        raw_count=0,
                        degraded=True,
                        error="rate_limit",
                    )
                )
            store.save()

            route = resolve_route(
                requested_source="auto",
                registry=registry,
                query="nickel",
                health_store=store,
                disable_fragile_sources=False,
                api_only=False,
                max_sources=5,
            )
            names = [item.source for item in route]
            # Low-health OpenAlex should not be among top priorities in auto mode.
            self.assertIn("arXiv", names)
            self.assertNotEqual(names[0], "OpenAlex")

    def test_stable_only_and_no_experimental_filters(self):
        registry = build_default_source_registry()
        with tempfile.TemporaryDirectory() as td:
            store = SourceHealthStore(Path(td) / "source_health.json")

            stable_route = resolve_route(
                requested_source="auto",
                registry=registry,
                query="nickel",
                health_store=store,
                disable_fragile_sources=False,
                api_only=False,
                stable_only=True,
                allow_experimental=True,
                max_sources=10,
            )
            self.assertTrue(all(registry.get(item.source).maturity == "stable" for item in stable_route))

            no_experimental_route = resolve_route(
                requested_source="OpenAlex,Crossref,EuropePMC",
                registry=registry,
                query="nickel",
                health_store=store,
                disable_fragile_sources=False,
                api_only=False,
                stable_only=False,
                allow_experimental=False,
                max_sources=10,
            )
            self.assertTrue(all(registry.get(item.source).maturity != "experimental" for item in no_experimental_route))

    def test_explicit_route_preserves_user_order(self):
        registry = build_default_source_registry()
        with tempfile.TemporaryDirectory() as td:
            store = SourceHealthStore(Path(td) / "source_health.json")
            route = resolve_route(
                requested_source="OpenAlex,Crossref,EuropePMC",
                registry=registry,
                query="iron",
                health_store=store,
                disable_fragile_sources=False,
                api_only=False,
                stable_only=False,
                allow_experimental=True,
                max_sources=3,
            )
            self.assertEqual([item.source for item in route], ["OpenAlex", "Crossref", "EuropePMC"])

    def test_rospatent_metadata_matches_pdf_extraction_capability(self):
        registry = build_default_source_registry()
        self.assertTrue(registry.get("Rospatent").capabilities.pdf_url)

    def test_source_health_save_merges_sequential_writers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source_health.json"
            first = SourceHealthStore(path)
            second = SourceHealthStore(path)

            first.record(SourceRunTelemetry(source="CORE", success=True, parsed_count=1, raw_count=1, degraded=False))
            second.record(SourceRunTelemetry(source="CORE", success=False, parsed_count=0, raw_count=0, degraded=True, error="rate_limit"))

            first.save()
            second.save()

            merged = SourceHealthStore(path).get("CORE")
            self.assertEqual(merged.get("runs"), 2)
            self.assertEqual(merged.get("successes"), 1)
            self.assertEqual(merged.get("failures"), 1)
            self.assertEqual(merged.get("degraded_runs"), 1)


if __name__ == "__main__":
    unittest.main()

class TestSourceHealthStoreRobustness(unittest.TestCase):
    def test_source_health_save_failure_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            store = SourceHealthStore(Path(td) / "source_health.json")
            store.record(SourceRunTelemetry(source="CORE", success=True, parsed_count=1, raw_count=1, degraded=False))

            def fail_lock(*args, **kwargs):
                raise TimeoutError("locked")

            store._acquire_save_lock = fail_lock  # type: ignore[method-assign]
            store.save()  # must not raise; source health is telemetry only

class TestSourceRegistryCanonicalNames(unittest.TestCase):
    def test_registry_accepts_case_insensitive_source_names(self):
        registry = build_default_source_registry()
        self.assertTrue(registry.is_supported("arxiv"))
        self.assertEqual(registry.get("crossREF").name, "Crossref")

    def test_resolve_route_canonicalizes_lowercase_explicit_sources(self):
        registry = build_default_source_registry()
        with tempfile.TemporaryDirectory() as td:
            store = SourceHealthStore(Path(td) / "source_health.json")
            route = resolve_route(
                requested_source="openalex, crossref",
                registry=registry,
                query="nickel",
                health_store=store,
                disable_fragile_sources=False,
                api_only=False,
                max_sources=2,
            )
        self.assertEqual([item.source for item in route], ["OpenAlex", "Crossref"])

class TestSourceHealthCorruptStateRound19(unittest.TestCase):
    def test_record_tolerates_corrupt_counter_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source_health.json"
            path.write_text(
                '{"sources":{"CORE":{"runs":"bad","successes":"2","failures":null,"degraded_runs":"1"}}}',
                encoding="utf-8",
            )
            store = SourceHealthStore(path)
            store.record(SourceRunTelemetry(source="CORE", success=True, parsed_count=3, raw_count=4, degraded=False))
            store.save()

            merged = SourceHealthStore(path).get("CORE")
            self.assertEqual(merged.get("runs"), 1)
            self.assertEqual(merged.get("successes"), 3)
            self.assertEqual(merged.get("failures"), 0)
            self.assertEqual(merged.get("degraded_runs"), 1)
            self.assertEqual(merged.get("last_parsed_count"), 3)

    def test_record_replaces_non_dict_source_entry(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source_health.json"
            path.write_text('{"sources":{"CORE":"broken"}}', encoding="utf-8")
            store = SourceHealthStore(path)
            store.record(SourceRunTelemetry(source="CORE", success=False, parsed_count=0, raw_count=0, degraded=True, error="boom"))
            store.save()

            merged = SourceHealthStore(path).get("CORE")
            self.assertEqual(merged.get("runs"), 1)
            self.assertEqual(merged.get("failures"), 1)
            self.assertEqual(merged.get("degraded_runs"), 1)
            self.assertEqual(merged.get("last_error"), "boom")
