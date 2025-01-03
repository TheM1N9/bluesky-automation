from duckduckgo_search import DDGS
from typing import List, Dict
import asyncio
import logging


async def search_topic(topic: str, max_results: int = 10) -> List[Dict]:
    """Search DuckDuckGo for a topic and return results"""
    try:
        with DDGS() as ddgs:
            # Use a smaller max_results to improve reliability
            results = list(ddgs.text(topic, max_results=max_results))
            return results if results else []
    except ValueError as e:
        logging.warning(f"DuckDuckGo search error for topic '{topic}': {e}")
        # Return a fallback result
        return [
            {
                "title": "Search Unavailable",
                "body": f"Basic information about {topic}.",
                "link": "https://example.com",
            }
        ]
    except Exception as e:
        logging.error(f"Unexpected search error: {e}")
        return []


async def research_topic(topic: str) -> Dict[str, str | List[str]]:
    """Research a topic and return content and sources"""
    try:
        results = await search_topic(topic)

        if not results:
            return {
                "content": f"Unable to find information about {topic}. Please try again later.",
                "sources": [],
            }

        # Combine search results into a summary
        summary = f"Topic: {topic}\n\n"
        sources = []

        for result in results[:5]:  # Limit to top 5 results
            summary += f"- {result['title']}\n{result['body']}\n\n"
            if "link" in result:
                sources.append(result["link"])

        return {"content": summary, "sources": sources}
    except Exception as e:
        logging.error(f"Error researching topic: {e}")
        return {
            "content": f"Error researching {topic}. Please try again later.",
            "sources": [],
        }
