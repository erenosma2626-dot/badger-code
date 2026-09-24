# v0.6-prep-agy retry fix — claude-dev

Branch: `v0.6-prep-agy-fix` (v0.6-prep-agy'nin 05d4ea2'sinden türedi). main'e yazma/merge/push yok.

## Commit → adım
- `0640850` — test: test_llm_retry.py'deki 4 `@pytest.mark.asyncio` test `asyncio.run(...)` ile senkron yazıldı (repo stili: test_llm_chat_tools vb. böyle). pyproject'e dokunulmadı.
- `f679276` — test (RED): SDK `max_retries==0`, varsayılan timeout 240s, `LLM_REQUEST_TIMEOUT` env ile ayar, APITimeoutError ve RemoteProtocolError en fazla 1 retry. 4 fail.
- `340f03a` — fix (GREEN): `starter/agent/llm.py`.

## Değişen dosyalar
- `starter/agent/llm.py`
  - `AsyncOpenAI(..., max_retries=0, timeout=self.request_timeout)`; `LLM_REQUEST_TIMEOUT` (varsayılan 240) — docstring config listesine eklendi.
  - `_is_slow_failure()`: APITimeoutError / httpcore.RemoteProtocolError (doğrudan ya da `__cause__`) → ayrı sayaçla en fazla `max_slow_retries=1`. APIConnectionError/5xx 3 retry'da kaldı (toplam üst sınır `max_retries`).
  - `getattr(self, ...)` fallback'leri kaldırıldı (değerler class default + `__init__`'te var).
- `starter/tests/test_llm_retry.py` (asyncio.run dönüşümü + 4 yeni test).

## Test
- Branch: `uv run --with pytest pytest -q` → **154 passed**.
- main geçici merge (çakışmasız, prompts.py auto-merge) → **166 passed**. Geçici branch silindi; branch'te merge yok.

## Şüpheli noktalar / yapılmayanlar
- Kalan-süre-bütçesine göre retry kesme **yapılmadı**: LLMClient agent'ın 900s bütçesini bilmiyor (agent.py'de deadline takibi yok, timeout Harbor tarafından dışarıdan uygulanıyor). Basit tutuldu. En kötü durum şimdi: 240s + backoff ~2s + 240s ≈ 8 dk (eskiden 600s×3×4). Hâlâ bütçenin yarısı; daha sıkı isteniyorsa LLM_REQUEST_TIMEOUT düşürülebilir ya da agent'a deadline eklenip LLMClient'a geçirilebilir (ayrı iş).
- 240s uzun reasoning completion'ları (max_tokens 8192, yavaş endpoint) keserse yanlış-pozitif timeout olabilir; env ile ayarlanabilir. .env.example'a eklenmedi.
- APITimeoutError, APIConnectionError'ın alt sınıfı; slow kontrolü is_transient'ten sonra yapıldığı için doğru ayrışıyor.
- 429 hâlâ retry edilmiyor (değiştirmedim).
