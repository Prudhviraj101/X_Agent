with open(r'drafter.py', 'r', encoding='utf-8') as f:
    c = f.read()

nvidia_fn = '''
def _draft_nvidia(cfg: "Config", prompts: list[str]) -> list[str]:
    from openai import OpenAI, RateLimitError, APIError
    import time
    
    # We use OpenAI client but point to Nvidia's URL
    client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=cfg.nvidia_api_key)
    results = []
    for prompt in prompts:
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=cfg.nvidia_model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=800,
                    temperature=0.85,
                )
                tweet = resp.choices[0].message.content.strip()
                results.append(tweet)
                break
            except RateLimitError:
                wait = 2 ** attempt * 5
                logger.warning("[drafter] NVIDIA rate limit; retrying in %ds", wait)
                time.sleep(wait)
            except APIError as exc:
                logger.error("[drafter] NVIDIA API error: %s", exc)
                results.append("")
                break
        else:
            results.append("")
    return results
'''

if 'def _draft_nvidia' not in c:
    c = c.replace('def _draft_openai', nvidia_fn + '\n\ndef _draft_openai')

router_old = '''    if cfg.model_provider == "gemini":
        tweets = _draft_gemini(cfg, prompts)
    elif cfg.model_provider == "hybrid":
        tweets = _draft_hybrid(cfg, items)
    else:
        tweets = _draft_openai(cfg, prompts)'''

router_new = '''    if cfg.model_provider == "gemini":
        tweets = _draft_gemini(cfg, prompts)
    elif cfg.model_provider == "nvidia":
        tweets = _draft_nvidia(cfg, prompts)
    elif cfg.model_provider == "hybrid":
        tweets = _draft_hybrid(cfg, items)
    else:
        tweets = _draft_openai(cfg, prompts)'''

c = c.replace(router_old, router_new)

with open(r'drafter.py', 'w', encoding='utf-8') as f:
    f.write(c)
