from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

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
        self.assertEqual(q4, "metals nickel")
        self.assertEqual(r4, "ru_to_en_token_rewrite")

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


if __name__ == "__main__":
    unittest.main()
