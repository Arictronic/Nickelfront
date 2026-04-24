from __future__ import annotations

import unittest

from parsers_pkg.pipelines.data_pipeline import process_papers
from parsers_pkg.sources import build_default_source_registry
from run_parser import _build_dry_run_plan
from shared.schemas.paper import Paper


class TestPipelineAndDryRunSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_with_minimal_records(self):
        papers = [
            Paper(
                title="Nickel corrosion behavior",
                authors=["A. Author"],
                source="Crossref",
                url="https://doi.org/10.1000/xyz.1",
                doi="10.1000/xyz.1",
            ),
            Paper(
                title="Nickel corrosion behavior",
                authors=["A. Author"],
                source="OpenAlex",
                url="https://openalex.org/W12345",
                source_id="W12345",
            ),
        ]

        result = await process_papers(papers, enable_enrichment=True)
        self.assertTrue(result.success)
        self.assertGreater(len(result.papers), 0)
        self.assertIn("parser", result.diagnostics)

    async def test_dry_run_all_sources_have_expected_keys(self):
        registry = build_default_source_registry()
        for source in registry.list_names():
            plan = _build_dry_run_plan(
                source=source,
                query="nickel",
                limit=5,
                disable_fragile_sources=False,
                api_only=False,
                stable_only=False,
                allow_experimental=True,
                out_dir="data",
                max_fallback_sources=3,
                strict_source=False,
            )
            self.assertIn("route_plan", plan)
            self.assertGreaterEqual(len(plan["route_plan"]), 1)
            first = plan["route_plan"][0]
            self.assertIn("maturity", first)
            self.assertIn("access_mode", first)
            self.assertIn("compliance_notes", first)

    async def test_dry_run_strict_source_disables_fallback(self):
        plan = _build_dry_run_plan(
            source="Crossref",
            query="iron",
            limit=5,
            disable_fragile_sources=False,
            api_only=False,
            stable_only=False,
            allow_experimental=True,
            out_dir="data",
            max_fallback_sources=5,
            strict_source=True,
        )
        self.assertEqual(plan["route_count"], 1)
        self.assertTrue(plan["flags"]["strict_source"])
        self.assertEqual(plan["route_plan"][0]["source"], "Crossref")


if __name__ == "__main__":
    unittest.main()
