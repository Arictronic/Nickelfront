import asyncio
import json

import httpx
import pytest


async def _fetch_openalex_structure() -> dict:
    """Fetch one OpenAlex record for manual/API-contract inspection."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            "https://api.openalex.org/works",
            params={"search": "nickel-based alloys", "per-page": 1},
        )
        resp.raise_for_status()
        return resp.json()


@pytest.mark.external
async def test_openalex():
    data = await _fetch_openalex_structure()
    assert isinstance(data, dict)

    if data.get("results"):
        result = data["results"][0]
        assert "display_name" in result
        print("=== OpenAlex API Response Structure ===")
        print(f"Title: {result.get('display_name')}")
        print(f"Has abstract_inverted_index: {'abstract_inverted_index' in result}")

        if "abstract_inverted_index" in result:
            print(f"Abstract inverted index sample: {str(result['abstract_inverted_index'])[:200]}...")
        else:
            print("No abstract_inverted_index field found")

        print("\n=== Full result keys ===")
        print(json.dumps(list(result.keys()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    payload = asyncio.run(_fetch_openalex_structure())
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
