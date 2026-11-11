import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from .env

response = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain prompt caching in one sentence."}],
)

print(response.content[0].text)
print(f"\nTokens used: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
