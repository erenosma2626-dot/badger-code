# v0.4.1 worker raporu (Claude Sonnet 5, worktree cao/d15a5ec0)

3 madde tamamlandı, her biri ayrı commit(ler) ile, TDD ile (önce başarısız test, sonra minimum kod, sonra test tekrar çalıştırılıp doğrulandı). Tüm değişiklikler `starter/agent/agent.py`, `starter/agent/llm.py`, `starter/agent/prompts.py`, `starter/agent/tools.py` ve yeni test dosyalarında. `.env`/`secrets.json`/`*.pem` dosyalarına hiç dokunulmadı.

## Güncelleme (rebase / worker1-agy entegrasyonu)

Branch `950be83`'ten dallanmıştı, worker1-agy'nin v0.4.1 kolay 3 düzeltmesi (main'e `fa1579b` olarak merge edilmiş) branch'te yoktu — supervisor bunu tespit edip `git fetch origin && git rebase origin/main` yapmamı istedi.

**Sonuç: `git rebase origin/main` TEK bir conflict ile temiz sonuçlandı** (`starter/agent/tools.py`, `find_cyclic_multi_target_loop` fonksiyonunun eklendiği yerde — HEAD tarafı boştu, sadece kendi fonksiyonumu geri eklemem yeterliydi; worker1-agy'nin `is_unproductive_attempt()`'e `command=` parametresi eklemesiyle çakışmadı, farklı fonksiyonlardı). `starter/agent/agent.py` ve `starter/agent/prompts.py` git tarafından OTOMATİK merge edildi — özellikle agent.py'deki `is_unproductive_attempt(...)` çağrı siteleri, worker1-agy'nin eklediği `command=` argümanı İLE benim eklediğim `cyclic_target_history.append(target)` satırı bir arada, doğru şekilde birleşti (aşağıda doğrulandı). `structured_tools.py`'ye (read_file'ın temiz hata mesajı fix'i) hiç dokunmamıştım, conflict'siz geldi.

Doğrulamalar:
- `starter/agent/agent.py:414-427` ve `:850-862` — her iki `is_unproductive_attempt(...)` çağrısı da `command=`/`cmd=` parametresini taşıyor VE hemen ardından `cyclic_target_history.append(target)` var — iki değişiklik iç içe, kaybolan yok.
- worker1-agy'nin 3 yeni test dosyası (`test_prompts_general_rules.py`, `test_structured_tools.py`, `test_tools_target_extraction.py` — toplam 31 test) rebase sonrası branch'te mevcut ve ayrı ayrı çalıştırılıp geçti.
- `git diff fa1579b HEAD -- .env '**/secrets.json' '**/*.pem'` boş — bu dosyalara dokunulmadı.
- `git log --oneline` sırası: `950be83` → worker1-agy'nin 3 commiti + rapor (`803df05`, `ca7b98f`, `356c470`, `fa1579b`) → benim 3 madde + rapor (`db18bbf`, `bfe6b64`, `653ebb3`, `a34a404`) — lineer, temiz.

**Tam test suite: `pytest starter/tests -q` → 99 test, hepsi geçti.**

## Değişen dosyalar

- `starter/agent/agent.py` — her 3 madde de burada
- `starter/agent/llm.py` — madde 2 (max_tokens default)
- `starter/agent/prompts.py` — madde 1 (CYCLIC_LOOP_MESSAGE), madde 2 (TRUNCATED_RESPONSE_MESSAGE)
- `starter/agent/tools.py` — madde 1 (`find_cyclic_multi_target_loop`)
- Yeni test dosyaları: `test_tools_cyclic_target_loop.py`, `test_structured_agent_cyclic_loop.py`, `test_agent_cyclic_loop.py`, `test_llm_max_tokens_default.py`, `test_structured_agent_truncated_response.py`, `test_structured_agent_meaningful_verification.py`
- Güncellenen mevcut test: `test_structured_agent_completion_evidence_gate.py` (bkz. "şüpheli nokta" altında, kasıtlı davranış değişikliği)

## Commit'ler

1. `56e86fb` — **madde 2**: `LLM_MAX_TOKENS` default 2048→8192 (env override hâlâ çalışıyor); `finish_reason=="length"` durumunda StructuredToolAgent artık `TRUNCATED_RESPONSE_MESSAGE` gönderiyor (STRUCTURED_NUDGE_MESSAGE yerine), diğer finish_reason'larda eski davranış korunuyor. BaselineAgent'a dokunulmadı.
2. `9965ef1` — **madde 3**: `is_meaningful_verification(command)` blocklist fonksiyonu (`cat/ls/chmod/chown/echo/pwd/head/tail` ile başlayan komutlar False, gerisi True). Hem `pending_verification` temizleme koşuluna hem de completion-evidence nudge kapısına (yeni `meaningful_action_since_nudge` bayrağı ile) uygulandı.
3. `59bab16` — **madde 1**: `find_cyclic_multi_target_loop()` (tools.py, saf fonksiyon) + `stuck_nudged` global bool → `set[str]` (hem BaselineAgent hem StructuredToolAgent'ta).

## Madde bazlı yaklaşım/tasarım kararları

**Madde 1 — cyclic_multi_target_loop + hedef-bazlı nudge:**
`find_cyclic_multi_target_loop(history, max_window=8)` son `max_window` ziyaret edilen hedefi alır, `cycle_len` 2'den `max_window//2`'ye kadar dener; son `cycle_len` hedef, ondan önceki `cycle_len` hedefe TAM eşitse (2 tam tur) ve en az 2 farklı hedef içeriyorsa (tek hedef tekrarı zaten `target_is_stuck`'ın işi) o döngüyü döndürür. Pencere K=8 seçildi (cycle_len 2-4 arası döngüleri yakalar); `AGENT_CYCLIC_LOOP_WINDOW` env var ile ayarlanabilir. Her iki agent loop'unda (BaselineAgent shell path, StructuredToolAgent tool-call path) üçüncü tetikleyici olarak mevcut ikisine OR'landı, mevcut ikisi dokunulmadan. `stuck_nudged` artık `set[str]`: exact_repeat için sabit `"__exact_repeat__"` anahtarı, target_is_stuck için hedefin kendisi, cyclic için döngünün virgülle birleştirilmiş hali (`"__cyclic__:a.py,b.py,..."`) — böylece farklı bir hedef/döngüde ilk kez takılma her zaman yeni bir nudge alır, sadece AYNI anahtar tekrar tetiklenirse sert sonlandırma olur.

**Madde 2 — finish_reason=length:**
Basit, düşük riskli değişiklik. `chat_tools()` zaten `usage["finish_reason"]`'ı expose ediyordu (önceki bir v0.4 iterasyonunda eklenmiş), sadece agent.py'deki "tool_calls yoksa" dalında bunu kontrol edip mesajı seçtim.

**Madde 3 — is_meaningful_verification:**
Blocklist yaklaşımı spec'in istediği gibi (allowlist yerine) — "hangi komut gerçek test" tahmini görev-bağımsız güvenilir değil ama "kesinlikle pasif" komutları saymak güvenli. `action_since_nudge` (mevcut, davranışı korundu) ile `meaningful_action_since_nudge` (yeni) ayrı tutuldu: `read_file` hâlâ `action_since_nudge=True` yapıyor ama `meaningful_action_since_nudge`'a katkı sağlamıyor; `terminal_exec` sadece `is_meaningful_verification(command)` True ise katkı sağlıyor; `write_file` her zaman ikisini de True yapıyor (yeni bir edit zaten "yeni durum" demek).

## Test durumu

Rebase ÖNCESİ (worker1-agy'siz): `pytest starter/tests -q` → 85 test, hepsi geçti (madde 1 öncesi 65, madde 2 sonrası 69, madde 3 sonrası 72+1 güncellenen, madde 1 sonrası 85). Rebase SONRASI (worker1-agy'nin 3 fix'i + testleri dahil): **99 test, hepsi geçti** (+14 worker1-agy testi).

Madde bazlı yeni testler:
- Madde 1: `test_tools_cyclic_target_loop.py` (6, saf fonksiyon), `test_structured_agent_cyclic_loop.py` (4), `test_agent_cyclic_loop.py` (3) — toplam 13
- Madde 2: `test_llm_max_tokens_default.py` (2), `test_structured_agent_truncated_response.py` (2) — toplam 4
- Madde 3: `test_structured_agent_meaningful_verification.py` (6) + `test_structured_agent_completion_evidence_gate.py`'e eklenen 1 yeni test — toplam 7

## Şüpheli / emin olmadığım nokta

1. **Madde 3 — `test_second_task_complete_after_a_new_tool_call_is_accepted` testini değiştirdim.** Eski test, nudge sonrası SADECE bir `read_file` çağrısının task_complete'i kabul ettirmeye yettiğini doğruluyordu — bu tam olarak spec'in kapatmamı istediği açık. Eski testi silmek yerine ikiye böldüm: `test_second_task_complete_after_a_new_meaningful_tool_call_is_accepted` (gerçek `terminal_exec` ile kabul) ve `test_second_task_complete_after_only_a_read_file_readback_is_still_rejected` (sadece read_file ile red). Bu kasıtlı bir davranış değişikliği ama supervisor'ın onaylaması gereken bir "regresyon" olarak görünebilir — lütfen gözden geçirin.
2. **Madde 1 — cyclic key tasarımı**: `exact_repeat_stuck` için hep aynı `"__exact_repeat__"` anahtarını kullandım (spec'in önerdiği gibi), yani AYNI komut metni farklı bir hedefte tekrar exact-repeat olarak tetiklenirse bu da "daha önce nudge aldı" sayılıp sert sonlandırabilir (hedef-bazlı değil, "tekrar tipi"-bazlı). Bunun kasıtlı olduğunu düşünüyorum (spec açıkça bu anahtarı öneriyor) ama pratikte "aynı komutu iki farklı, alakasız hedefte art arda tekrarlama" nadir bir senaryo olduğu için test etmedim; canary loglarında görülürse bu ayrım da hedef-bazlı yapılabilir.
3. **Madde 1 — pencere boyutu K=8**: spec "K=6-8" öneriyordu, ben 8 seçtim (cycle_len 4'e kadar döngü yakalar, örn. 4-dosyalı döngüler). Gerçek trial'lardaki döngü uzunluğu (9-10 dosya) bu pencereden daha büyük olabilir — K=8 sadece son birkaç turdaki döngüyü yakalar, tüm 9-10 dosyalık döngüyü değil. Daha büyük bir K (örn. 16-20) daha geniş döngüleri yakalar ama yanlış-pozitif riski de artar (rastgele 2 turun aynı gelmesi ihtimali). Canary'de gerçek trial uzunluklarına göre ayarlanması gerekebilir — bu bir tuning kararı, spec net bir sayı vermiyordu.
