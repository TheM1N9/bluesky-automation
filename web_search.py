from duckduckgo_search import DDGS
from typing import List, Dict
import asyncio


async def search_topic(topic: str, max_results: int = 25) -> List[Dict]:
    """Search DuckDuckGo for a topic and return results"""
    try:
        # Run DDG search in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: DDGS().text(topic, max_results=max_results)
        )

        return results if results else []
    except Exception as e:
        print(f"Search error: {e}")
        raise e
        return []


async def research_topic(topic: str) -> str:
    """Research a topic and return a summary"""
    results = await search_topic(topic)

    if not results:
        return "No information found for this topic."

    # Combine search results into a summary
    summary = f"Topic: {topic}\n\n"
    for result in results:
        summary += f"- {result['title']}\n{result['body']}\n\n"

    return summary
