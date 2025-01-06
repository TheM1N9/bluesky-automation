from duckduckgo_search import DDGS
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urlparse


def analyze_webpage_content(query, max_results=5):
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))

        for result in results:
            url = result["href"]
            try:
                # Add delay to be respectful
                time.sleep(2)

                # Get webpage content
                headers = {"User-Agent": "Mozilla/5.0"}
                response = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(response.text, "html.parser")

                # Extract key information
                domain = urlparse(url).netloc
                title = soup.title.string if soup.title else "No title"
                text = " ".join([p.text for p in soup.find_all("p")])

                print(f"\nSource: {domain}")
                print(f"Title: {title}")
                print(f"Summary: {text[:500]}...\n")
                print("-" * 80)

            except Exception as e:
                print(f"Error processing {url}: {str(e)}")


# Usage
query = "artificial intelligence"
analyze_webpage_content(query)
