import asyncio
import httpx
import json

async def test_openalex():
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://api.openalex.org/works?search=nickel-based+alloys&per-page=1')
        data = resp.json()
        
        # Print the first result to see structure
        if data.get('results'):
            result = data['results'][0]
            print("=== OpenAlex API Response Structure ===")
            print(f"Title: {result.get('display_name')}")
            print(f"Has abstract_inverted_index: {'abstract_inverted_index' in result}")
            
            if 'abstract_inverted_index' in result:
                print(f"Abstract inverted index sample: {str(result['abstract_inverted_index'])[:200]}...")
            else:
                print("No abstract_inverted_index field found")
            
            print("\n=== Full result keys ===")
            print(json.dumps(list(result.keys()), indent=2))

asyncio.run(test_openalex())