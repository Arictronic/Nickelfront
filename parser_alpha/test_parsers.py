"""Comprehensive parser testing script for all 5 sources."""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Any

# Test queries for metallurgy domain
TEST_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "high entropy alloys",
]

SOURCES = ["arXiv", "CORE", "OpenAlex", "Crossref", "EuropePMC"]


def analyze_paper_quality(paper: dict[str, Any]) -> dict[str, Any]:
    """Analyze quality of a single paper record."""
    issues = []
    warnings = []
    
    # Check required fields
    if not paper.get("title"):
        issues.append("missing_title")
    if not paper.get("authors"):
        warnings.append("no_authors")
    if not paper.get("abstract"):
        warnings.append("no_abstract")
    
    # Check URLs
    url = paper.get("url")
    pdf_url = paper.get("pdf_url")
    
    if not url:
        issues.append("missing_article_url")
    elif url and ".pdf" in url.lower():
        warnings.append("article_url_is_pdf")
    
    if not pdf_url:
        warnings.append("missing_pdf_url")
    elif pdf_url and ".pdf" not in pdf_url.lower():
        warnings.append("pdf_url_not_pdf")
    
    # Check identifiers
    if not paper.get("doi") and not paper.get("source_id"):
        warnings.append("no_identifiers")
    
    # Check dates
    if not paper.get("publication_date"):
        warnings.append("no_publication_date")
    
    # Check metadata richness
    metadata_score = 0
    if paper.get("title"): metadata_score += 1
    if paper.get("authors"): metadata_score += 1
    if paper.get("abstract"): metadata_score += 1
    if paper.get("keywords"): metadata_score += 1
    if paper.get("doi"): metadata_score += 1
    if paper.get("publication_date"): metadata_score += 1
    if paper.get("journal"): metadata_score += 1
    
    quality = "excellent" if metadata_score >= 6 else "good" if metadata_score >= 4 else "poor"
    
    return {
        "quality": quality,
        "metadata_score": metadata_score,
        "issues": issues,
        "warnings": warnings,
        "has_article_url": bool(url),
        "has_pdf_url": bool(pdf_url),
        "has_doi": bool(paper.get("doi")),
        "has_abstract": bool(paper.get("abstract")),
    }


def analyze_source_results(source: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze results from a single source."""
    if not papers:
        return {
            "source": source,
            "status": "no_results",
            "count": 0,
            "quality_summary": {},
        }
    
    quality_analyses = [analyze_paper_quality(p) for p in papers]
    
    # Aggregate statistics
    total = len(papers)
    excellent = sum(1 for q in quality_analyses if q["quality"] == "excellent")
    good = sum(1 for q in quality_analyses if q["quality"] == "good")
    poor = sum(1 for q in quality_analyses if q["quality"] == "poor")
    
    has_article_url = sum(1 for q in quality_analyses if q["has_article_url"])
    has_pdf_url = sum(1 for q in quality_analyses if q["has_pdf_url"])
    has_doi = sum(1 for q in quality_analyses if q["has_doi"])
    has_abstract = sum(1 for q in quality_analyses if q["has_abstract"])
    
    # Collect all issues and warnings
    all_issues = []
    all_warnings = []
    for q in quality_analyses:
        all_issues.extend(q["issues"])
        all_warnings.extend(q["warnings"])
    
    # Count unique issues
    issue_counts = {}
    for issue in all_issues:
        issue_counts[issue] = issue_counts.get(issue, 0) + 1
    
    warning_counts = {}
    for warning in all_warnings:
        warning_counts[warning] = warning_counts.get(warning, 0) + 1
    
    return {
        "source": source,
        "status": "success",
        "count": total,
        "quality_distribution": {
            "excellent": excellent,
            "good": good,
            "poor": poor,
        },
        "url_coverage": {
            "article_url": f"{has_article_url}/{total} ({100*has_article_url//total}%)",
            "pdf_url": f"{has_pdf_url}/{total} ({100*has_pdf_url//total}%)",
        },
        "metadata_coverage": {
            "doi": f"{has_doi}/{total} ({100*has_doi//total}%)",
            "abstract": f"{has_abstract}/{total} ({100*has_abstract//total}%)",
        },
        "common_issues": issue_counts,
        "common_warnings": warning_counts,
        "sample_papers": [
            {
                "title": p.get("title", "")[:80],
                "url": p.get("url"),
                "pdf_url": p.get("pdf_url"),
                "doi": p.get("doi"),
                "quality": analyze_paper_quality(p)["quality"],
            }
            for p in papers[:3]
        ],
    }


async def test_all_sources():
    """Test all sources with multiple queries."""
    print("=" * 80)
    print("PARSER TESTING SUITE")
    print("=" * 80)
    print(f"Testing {len(SOURCES)} sources with {len(TEST_QUERIES)} queries")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    results = {}
    
    for source in SOURCES:
        print(f"\n{'='*80}")
        print(f"Testing source: {source}")
        print(f"{'='*80}")
        
        source_results = []
        
        for query in TEST_QUERIES:
            print(f"\nQuery: '{query}'")
            print("-" * 40)
            
            # Find latest JSON file for this source
            data_dir = Path("data")
            if not data_dir.exists():
                print(f"[X] Data directory not found. Run parser first!")
                continue
            
            # Look for files matching this source
            pattern = f"{source.replace(' ', '_')}*.json"
            files = sorted(data_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
            
            if not files:
                print(f"[!] No data files found for {source}")
                print(f"   Run: python run_parser.py --source {source} --query \"{query}\" --limit 20")
                continue
            
            # Read the most recent file
            latest_file = files[0]
            print(f"[FILE] Reading: {latest_file.name}")
            
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    papers = json.load(f)
                
                print(f"[OK] Loaded {len(papers)} papers")
                
                # Analyze results
                analysis = analyze_source_results(source, papers)
                source_results.append(analysis)
                
                # Print summary
                if analysis["status"] == "success":
                    print(f"   Quality: {analysis['quality_distribution']}")
                    print(f"   URLs: {analysis['url_coverage']}")
                    if analysis["common_issues"]:
                        print(f"   [WARN] Issues: {analysis['common_issues']}")
                
            except Exception as e:
                print(f"[ERROR] Error reading file: {e}")
                continue
        
        results[source] = source_results
    
    # Generate comprehensive report
    print("\n" + "=" * 80)
    print("COMPREHENSIVE REPORT")
    print("=" * 80)
    
    report_path = Path("data/parser_test_report.json")
    report = {
        "test_date": datetime.now().isoformat(),
        "sources_tested": SOURCES,
        "queries_used": TEST_QUERIES,
        "results": results,
    }
    
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[REPORT] Full report saved to: {report_path}")
    
    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    print(f"{'Source':<15} {'Status':<12} {'Papers':<8} {'Quality':<20} {'URLs':<15}")
    print("-" * 80)
    
    for source, source_results in results.items():
        if not source_results:
            print(f"{source:<15} {'NO DATA':<12} {'-':<8} {'-':<20} {'-':<15}")
            continue
        
        for result in source_results:
            if result["status"] == "no_results":
                print(f"{source:<15} {'NO RESULTS':<12} {'0':<8} {'-':<20} {'-':<15}")
            else:
                quality = f"E:{result['quality_distribution']['excellent']} G:{result['quality_distribution']['good']} P:{result['quality_distribution']['poor']}"
                urls = result['url_coverage']['article_url'].split()[0]
                print(f"{source:<15} {'SUCCESS':<12} {result['count']:<8} {quality:<20} {urls:<15}")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    # Generate recommendations
    recommendations = []
    
    for source, source_results in results.items():
        if not source_results:
            recommendations.append(f"[X] {source}: No test data available - run parser first")
            continue
        
        for result in source_results:
            if result["status"] == "no_results":
                recommendations.append(f"[!] {source}: Returns no results - check API/query")
            elif result["count"] < 5:
                recommendations.append(f"[!] {source}: Low result count ({result['count']}) - may need tuning")
            
            if result.get("common_issues"):
                for issue, count in result["common_issues"].items():
                    if count > result["count"] * 0.5:
                        recommendations.append(f"[CRITICAL] {source}: {issue} affects {count}/{result['count']} papers")
            
            if result.get("common_warnings"):
                for warning, count in result["common_warnings"].items():
                    if count > result["count"] * 0.7:
                        recommendations.append(f"[WARNING] {source}: {warning} in {count}/{result['count']} papers")
    
    if recommendations:
        for rec in recommendations:
            print(rec)
    else:
        print("[OK] All parsers working well!")
    
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print("1. Review parser_test_report.json for detailed analysis")
    print("2. Fix critical issues (missing URLs, identifiers)")
    print("3. Test parsers that returned no data")
    print("4. Consider adding Russian sources (elibrary.ru, cyberleninka.ru)")
    print("5. Design PDF processing pipeline")
    print()


if __name__ == "__main__":
    asyncio.run(test_all_sources())