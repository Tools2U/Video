# shortGPT/api_utils/openai_api.py

import openai
import os

class OpenAIAPI:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        openai.api_key = self.api_key

    def get_chapters(self, script, model="gpt-4", max_tokens=4096):
        prompt = (
            f"Identify key chapters or sections in the following YouTube script. "
            f"Highlight prominent words or phrases that indicate the beginning of a new section:\n\n{script}\n\n"
            f"Provide the output in a structured format with timestamps."
        )
        response = openai.Completion.create(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.5,
        )
        return response.choices[0].text.strip()
