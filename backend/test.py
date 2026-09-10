"""Quick test to verify backend is working"""
import os
from dotenv import load_dotenv
from anthropic import Anthropic
from elevenlabs import ElevenLabs

load_dotenv()

# Test Anthropic API
print("Testing Anthropic API...")
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
response = client.messages.create(
    model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
    max_tokens=100,
    messages=[{"role": "user", "content": "Say 'API is working' in 5 words or less."}]
)
print(f"✓ Anthropic: {response.content[0].text}")

# Test ElevenLabs API
print("\nTesting ElevenLabs API...")
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
voice_id = os.getenv("MALE_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
audio = elevenlabs.text_to_speech.convert(
    voice_id=voice_id,
    text="Interview coach is ready",
)
audio_bytes = b""
for chunk in audio:
    audio_bytes += chunk
print(f"✓ ElevenLabs: Generated {len(audio_bytes)} bytes of audio")

print("\n✓ All APIs working!")