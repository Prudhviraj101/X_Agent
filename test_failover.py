"""Self-check for hybrid writer failover state machine (no network)."""
import sys, os
sys.path.insert(0, '.')
import types as _types

# Fake google.genai so _draft_hybrid never touches the network
class _FakeResp:
    text = "facts"

class _FakeModels:
    def generate_content(self, *a, **k):
        return _FakeResp()

class _FakeClient:
    def __init__(self, *a, **k):
        self.models = _FakeModels()

fake_genai = _types.SimpleNamespace(Client=_FakeClient)
fake_types = _types.SimpleNamespace(GenerateContentConfig=lambda **k: k)
mod = _types.ModuleType("google")
sys.modules["google"] = mod
mod2 = _types.ModuleType("google.genai")
mod2.Client = _FakeClient
sys.modules["google.genai"] = mod2
mod3 = _types.ModuleType("google.genai.types")
mod3.GenerateContentConfig = lambda **k: k
sys.modules["google.genai.types"] = mod3

import drafter

# Reset module state
drafter._WRITER_MODE = "openai"
drafter._OPENAI_BLOCKED_UNTIL = 0.0

# Scenario 1: OpenAI rate-limited -> flips to Gemini
calls = {"openai": 0, "gemini": 0}
def fake_openai(writer, cfg, facts, url, templates=None):
    calls["openai"] += 1
    return None  # simulate quota exhausted
def fake_gemini(client, cfg, facts, url, templates=None):
    calls["gemini"] += 1
    return f"gemini tweet for {url}"
drafter._write_with_openai = fake_openai
drafter._write_with_gemini = fake_gemini

from scraper import ScrapedItem
item = ScrapedItem(title="t", url="https://x/u/1", source="t", summary="", score=1)

# Fake cfg
class C:
    hybrid_researcher_model = "gemini-3.5-flash"
    gemini_model = "gemini-3.5-flash"
    gemini_api_key = "fake"
    openai_api_key = "fake"
    hybrid_writer_model = "gpt-4o-mini"
cfg = C()

t = drafter._draft_hybrid(cfg, [item, item])
assert calls["openai"] == 1 and calls["gemini"] == 2, f"scenario1: {calls}"
assert drafter._WRITER_MODE == "gemini", "should be in gemini mode"
print("S1 passed: OpenAI exhausted -> Gemini writer used, mode=gemini")

# Scenario 2: cooldown expires, OpenAI works again -> flips back
drafter._OPENAI_BLOCKED_UNTIL = -1  # already past cooldown
calls = {"openai": 0, "gemini": 0}
def fake_openai2(writer, cfg, facts, url, templates=None):
    calls["openai"] += 1
    return "openai tweet"
drafter._write_with_openai = fake_openai2
drafter._write_with_gemini = fake_gemini

t2 = drafter._draft_hybrid(cfg, [item])
assert calls["openai"] == 1, f"scenario2: {calls}"
assert drafter._WRITER_MODE == "openai", "should flip back to openai"
assert t2[0] == "openai tweet"
print("S2 passed: cooldown over + OpenAI OK -> flipped back to OpenAI, mode=openai")

print("ALL PASSED")