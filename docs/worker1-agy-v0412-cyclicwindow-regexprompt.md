# v0.4.1.2 Uygulama ve Doğrulama Raporu: CYCLIC_LOOP_WINDOW Kalibrasyonu & Regex Sayma Prompt Kuralı

**Tarih:** 2026-09-16  
**Uygulayıcı:** worker1-agy  
**Branch:** `feature/v0.4.1.2-fixes`  
**İlgili Commit'ler:**
- `91b60fb` — `fix(agent): calibrate CYCLIC_LOOP_WINDOW default from 8 to 44` (Madde 1)
- `d2d4f25` — `feat(prompts): add general regex counting constraint guidance` (Madde 2)

---

## 1. Değişen ve Eklenen Dosyalar

- `starter/agent/agent.py` — `CYCLIC_LOOP_WINDOW` varsayılanı 8'den 44'e çıkarıldı.
- `starter/agent/tools.py` — `find_cyclic_multi_target_loop` varsayılan `max_window` değeri 8'den 44'e güncellendi.
- `starter/agent/prompts.py` — `SYSTEM_PROMPT` ve `STRUCTURED_SYSTEM_PROMPT` içine genel regex sayma kısıtı kuralı eklendi.
- `starter/tests/test_tools_cyclic_target_loop.py` — 10 hedefli döngü ve çift aksiyonlu (read+cat) 40 girişlik senaryolar için testler eklendi.
- `starter/tests/test_structured_agent_cyclic_loop.py` — `StructuredToolAgent` için 10 hedefli döngü entegrasyon testi eklendi.
- `starter/tests/test_prompts_general_rules.py` — Regex prompt kuralı ve genel kural doğrulaması için testler eklendi.
- `docs/worker1-agy-v0412-cyclicwindow-regexprompt.md` — Bu rapor dokümanı.

---

## 2. Yaklaşım Özeti

v0.4.1'de eklenen döngüsel çoklu-hedef tespit mekanizmasının penceresi, `fix-code-vulnerability` ve benzeri görevlerde gözlenen 9-10 dosyalık çift aksiyonlu (`read_file` + `cat`) tam turları (lap başına ~18-20, iki lap'te 36-40 giriş) yakalayabilmesi için varsayılan 8'den 44'e yükseltildi (`AGENT_CYCLIC_LOOP_WINDOW` env override korunarak). Ayrıca, `regex-log` görevinde gözlenen ve token sınırını aşarak model çıktısının kesilmesine yol açan onlarca zincirlenmiş negatif lookahead stratejisinin önüne geçmek amacıyla, sayma/kısıtlama işlemlerinin regex dışına taşınmasını öğütleyen genel bir strateji maddesi hem baseline hem de structured system prompt'larına eklendi. Her iki madde TDD disipliniyle (önce başarısız test, ardından kod değişikliği, ardından tam suite doğrulaması) ve bağımsız commit'lerle tamamlandı.

---

## 3. Madde 1: CYCLIC_LOOP_WINDOW Kalibrasyonu

### Değer Değişimi
- **Eski Değer:** `8` (`8 // 2 = 4`, en fazla 4 uzunluğunda döngüleri tespit edebiliyordu)
- **Yeni Değer:** `44` (`44 // 2 = 22`, 9-10 farklı hedefin `read_file` + `terminal_exec cat` ile ikişer kez ziyaret edildiği 36-40 girişlik 2 tam lap senaryolarını rahatlıkla tespit edebiliyor)
- **Env Var Override:** `int(os.environ.get("AGENT_CYCLIC_LOOP_WINDOW", "44"))` şeklinde çalışmaya devam ediyor.

### Test Durumu (TDD)
1. **Eklenen/Güncellenen Testler:**
   - `starter/tests/test_tools_cyclic_target_loop.py`:
     - `test_two_full_cycles_through_ten_targets_is_detected`: 10 dosya × 2 lap = 20 girişlik döngünün tespiti (default 8 iken başarısız oldu, 44 ile geçti).
     - `test_two_full_cycles_through_ten_targets_with_read_and_exec_is_detected`: Gerçek dünya senaryosu: 10 dosya × 2 aksiyon (read+cat) × 2 lap = 40 girişlik döngünün tespiti (default 8 iken başarısız oldu, 44 ile geçti).
     - `test_find_cyclic_multi_target_loop_honors_explicit_max_window`: `max_window=8` verildiğinde 20 girişin yakalanmadığı, `max_window=44` ile yakalandığı doğrulandı.
   - `starter/tests/test_structured_agent_cyclic_loop.py`:
     - `test_ten_targets_cyclic_loop_triggers_stuck_loop_with_window_44`: 10 hedefli senaryoda 20. turda nudge verilmesi, 3. turda (turn 30) `stuck_loop_detected` ile sonlanması doğrulandı (pencere 8 iken `task_complete`'e düşerek fail etmişti).
   - Mevcut tüm küçük döngü testleri (`cycle_len=2` ve `cycle_len=4`) geriye dönük uyumlu olarak firesiz geçti.

2. **Pytest Çıktısı (Cyclic Testleri):**
```
starter/tests/test_tools_cyclic_target_loop.py .........                 [ 52%]
starter/tests/test_structured_agent_cyclic_loop.py .....                 [ 82%]
starter/tests/test_agent_cyclic_loop.py ...                              [100%]
============================== 17 passed in 0.30s ==============================
```

---

## 4. Madde 2: Regex / Sayma Stratejisi Genel Prompt Notu

### Eklenen Tam Metin
`starter/agent/prompts.py` içinde hem `SYSTEM_PROMPT` (Kural 9) hem de `STRUCTURED_SYSTEM_PROMPT` metnine aşağıdaki kural eklenmiştir:

> *"If you need to express a counting constraint (such as "at most/at least N occurrences") with regex, avoid chaining dozens of negative lookaheads — this produces extremely long regexes (thousands of characters) that can exceed output token limits and truncate your response. Instead: (a) extract raw matches with a simpler regex and do the counting/filtering outside regex (e.g. in Python code), or (b) move the counting constraint outside the regex entirely."*

### Test Durumu (TDD)
1. **Eklenen Testler (`starter/tests/test_prompts_general_rules.py`):**
   - `test_baseline_system_prompt_states_regex_counting_rule`: `SYSTEM_PROMPT` içinde regex sayma ve lookahead kısıtının varlığını denetler.
   - `test_structured_system_prompt_states_regex_counting_rule`: `STRUCTURED_SYSTEM_PROMPT` içinde aynı kuralın varlığını denetler.
   - `test_prompts_rules_are_generic_not_task_specific`: Prompt kurallarının göreve özel isimler (örn. `regex-log`) barındırmadığını denetler.
2. **Sözdizimi ve Import:**
   - `python -c "import agent.agent; import agent.prompts; import agent.tools"` ile syntax ve import bütünlüğü doğrulandı.

---

## 5. Genel Test Özeti

Tam test paketi çalıştırıldı:
```
============================= 109 passed in 0.59s ==============================
```
Tüm 109 test (önceki 103 test + 6 yeni test) yeşil durumdadır.

---

## 6. Şüphe / Dikkat Notu

Pencerenin 44'e çıkması döngü arama aralığını `cycle_len=22`'ye kadar genişletse de, işlem saf bellek içi karşılaştırmalarla yapıldığından milisaniyelik ek yük dahi oluşturmamaktadır; tek beklenen davranış değişikliği, daha önce yakalanamayan uzun döngülerin 100 tura varmadan zamanında tespit edilip sonlandırılmasıdır.
