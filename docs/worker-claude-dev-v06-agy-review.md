# Review: v0.6-prep-agy (worker1-agy) — claude-dev

**Karar: DÜZELTME GEREKLİ** (küçük; prompt kısmı merge edilebilir, retry kısmında 3 düzeltme şart)

## 1) llm.py retry
- Sınıflandırma doğru: APIConnectionError / APITimeoutError / httpcore.RemoteProtocolError / status>=500 → retry; 4xx → anında raise (testli). `__cause__` kontrolü de makul. (Not: SDK httpx hatalarını zaten APIConnectionError'a sarıyor; httpcore dalı pratikte ölü ama zararsız. 429 retry edilmiyor — kasıtlıysa ok.)
- **ÇİFT RETRY VAR:** `AsyncOpenAI(...)` `max_retries` verilmeden kuruluyor → SDK default `max_retries=2`, `timeout read=600s`. Doğrulandı. Sonuç: 1+3 dış deneme × 3 SDK denemesi = **12 istek**, bekleme katlanıyor. → `AsyncOpenAI(..., max_retries=0)` yapılmalı (main'deki revert edilmiş madde3 commit'i bunu yapıyordu).
- **Bütçe riski:** SDK read timeout 600s. Uzun soket kopması (600-870s) sonrası aynı devasa istek yeniden gönderilirse tek retry 900s agent bütçesini tamamen yer; backoff (2+4+8≈14s) önemsiz, asıl maliyet istek süresi. Öneri: (a) SDK timeout'u env ile makul bir değere indir (ör. 180-300s), (b) retry'ı kalan süreye göre kes (deadline param / geçen süre > X ise retry etme), ya da en azından APITimeoutError'ı 1 retry ile sınırla.
- Küçük: `getattr(self, "max_retries", 3)` kalıpları gereksiz (attr'ler __init__ + class default'ta var).

## 2) prompts.py
- Göreve-özel hardcode yok (pyknotid/port/görev adı geçmiyor; test de bunu yasaklıyor). Notlar genel: `pip install .` vs `build_ext --inplace`, systemd yoksa `service`/direkt daemon, /etc/hosts overwrite etme → append.
- Çelişki yok; tekrar: aynı metin hem SYSTEM_PROMPT (madde 13-14) hem STRUCTURED'a ekli — iki ayrı prompt olduğu için kabul edilebilir. Numaralandırma kaydı doğru (TASK_COMPLETE → 15).
- Uzama: prompts.py 19408 → 20528 byte (+~1.1KB toplam, prompt başına ~550 char ≈ **~130-150 token/istek**). Her turda gönderildiği için çok turlu görevde birikir ama küçük; kabul edilebilir.

## 3) main + branch birleşik test
- Geçici branch `review-agy-merge`'de `git merge main`: çakışmasız (prompts.py auto-merge).
- `uv run --with pytest pytest -q` → **4 failed, 158 passed**. Başarısızların 4'ü de test_llm_retry.py'deki `@pytest.mark.asyncio` testleri: **pytest-asyncio bağımlılığı projede yok**. `--with pytest-asyncio` ile: **162 passed**.
- → Düzeltme: ya pytest-asyncio'yu dev-deps'e ekle ya da testleri `asyncio.run(...)` ile senkron yaz (repo'daki mevcut stil hangisiyse).

## Gerekli düzeltmeler (özet)
1. `AsyncOpenAI(..., max_retries=0)` — çift retry'ı kaldır.
2. SDK timeout / deadline-bilinçli retry — 600s+ timeout sonrası retry'ın 900s bütçeyi yemesini engelle.
3. Async testleri mevcut test komutuyla geçer hale getir.
Prompt değişikliği olduğu gibi merge edilebilir.
