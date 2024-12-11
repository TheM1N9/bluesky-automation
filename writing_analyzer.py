from typing import List, Tuple
import google.generativeai as genai
import os
from datetime import datetime


async def analyze_writing_style(
    samples: List[dict], db, user_email: str
) -> Tuple[str, str]:
    """Analyze writing samples and store the result permanently"""

    # Check if analysis already exists
    user = await db.get_user(user_email)
    if user.get("writing_style"):
        return (
            user["writing_style"]["thinking_style"],
            user["writing_style"]["narrative_style"],
        )

    # Perform analysis only if it doesn't exist
    essays = "\n\n".join([s["content"] for s in samples if s["type"] == "ESSAY"])
    tweets = "\n\n".join([s["content"] for s in samples if s["type"] == "TWEET"])

    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""
    Analyze these writing samples to determine the author's thinking and narrative styles.

    Essays:
    {essays}

    Tweets:
    {tweets}

    Based on these samples, provide:
    1. A detailed analysis of their thinking style (analytical patterns, reasoning approach, perspective)
    2. A detailed analysis of their narrative style (tone, voice, pacing, language use)

    Format the response as JSON:
    ```json
    {{
        "thinking_style": "detailed description of thinking style",
        "narrative_style": "detailed description of narrative style"
    }}
    ```
    """

    try:
        response = model.generate_content(prompt)
        result = response.text

        import json
        import re

        json_match = re.search(r"```json(.*)```", result, re.DOTALL)
        if json_match:
            analysis = json.loads(json_match.group(1))
            thinking_style = analysis["thinking_style"]
            narrative_style = analysis["narrative_style"]

            # Store in database
            await db.update_writing_style(user_email, thinking_style, narrative_style)

            return thinking_style, narrative_style
    except Exception as e:
        print(f"Error analyzing writing style: {e}")

    return "Could not analyze style", "Could not analyze style"
