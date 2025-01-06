from duckduckgo_search import DDGS
from typing import List, Dict
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urlparse


async def search_topic(topic: str, max_results: int = 10) -> List[Dict]:
    """Search DuckDuckGo for a topic and return results"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(topic, max_results=max_results))

            # Process each result to include webpage content
            enriched_results = []
            for result in results:
                try:
                    # Add delay between requests
                    await asyncio.sleep(2)

                    # Get webpage content
                    headers = {"User-Agent": "Mozilla/5.0"}
                    response = requests.get(result["href"], headers=headers, timeout=10)
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Extract and clean text content
                    text = " ".join([p.text.strip() for p in soup.find_all("p")])
                    domain = urlparse(result["href"]).netloc

                    enriched_results.append(
                        {
                            "title": result["title"],
                            "body": text,
                            "href": result["href"],
                            "domain": domain,
                        }
                    )
                except Exception as e:
                    logging.warning(f"Error processing webpage {result['href']}: {e}")
                    # Include original result if webpage processing fails
                    enriched_results.append(result)

            return enriched_results if enriched_results else []

    except ValueError as e:
        logging.warning(f"DuckDuckGo search error for topic '{topic}': {e}")
        return [
            {
                "title": "Search Unavailable",
                "body": f"Basic information about {topic}.",
                "href": "https://example.com",
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
            if "href" in result:
                sources.append(result["href"])

        return {"content": summary, "sources": sources}
    except Exception as e:
        logging.error(f"Error researching topic: {e}")
        return {
            "content": f"Error researching {topic}. Please try again later.",
            "sources": [],
        }


async def main():
    topic = "artificial intelligence"
    result = await research_topic(topic)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
