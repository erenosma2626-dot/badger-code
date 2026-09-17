# v0.5.1 (worker1-agy) — Bağımsız Review

**Branch:** `feature/v0.5.1-prompt-notes` (main'e henüz merge edilmedi)
**Commit'ler:** `f42a508` (TDD red), `3536573` (TDD green), `212575a` (rapor)
**Diff kaynağı:** `git diff main...feature/v0.5.1-prompt-notes` doğrudan okundu (agy'nin özetine güvenilmedi).

## 1. Değişen dosyalar
- `starter/agent/prompts.py`: `SYSTEM_PROMPT` ve `STRUCTURED_SYSTEM_PROMPT`'a 2 yeni genel kural eklendi (PATH/env-var kalıcılık farkındalığı; ≥5 benzer dosya varsa tek-tek okuma yerine toplu-işleme script'i).
- `starter/tests/test_prompts_v051_notes.py` (yeni, 53 satır, 5 test).

## 2. Göreve-özel hardcode kontrolü
Sorun yok. İki kural da genel/yeniden kullanılabilir ifadelerle yazılmış — "export PATH", "environment variables", "external verification process", "multiple (e.g. 5+) similar or homogenous files" gibi soyut terimler kullanılıyor, hiçbir görev adı/ID'si veya spesifik dosya yolu geçmiyor. Ayrıca eklenen `test_prompts_remain_generic_and_avoid_task_names` testi, prompt metninde 4 bilinen görev adının (`sqlite-with-gcov`, `log-summary-date-ranges`, `chess-best-move`, `fix-code-vulnerability`) GEÇMEDİĞİNİ doğruluyor — iyi bir ek güvence. Yarışma kuralı ("tek system prompt, göreve özel dallanma/hardcoding yasak") ihlali yok.

## 3. SYSTEM_PROMPT / STRUCTURED_SYSTEM_PROMPT tutarlılığı
İki kural da her iki prompt'a da eklenmiş, ifadeler neredeyse birebir aynı (STRUCTURED_SYSTEM_PROMPT'ta numaralandırma yok, düz paragraf — buna uygun şekilde metne gömülmüş). `SYSTEM_PROMPT`'ta madde numaraları 7'den itibaren doğru şekilde kaydırılmış (yeni PATH notu mevcut 6. maddenin sonuna eklenmiş, yeni batch-processing notu eski 9. maddeden sonra 10 olarak eklenmiş, eski 10 (TASK_COMPLETE) 11'e kaymış) — numaralandırma bütünlüğü bozulmamış, kontrol ettim. Mevcut diğer kurallarla (cwd kalıcılığı, set-sıralama, regex-token-limiti, TASK_COMPLETE formatı) çakışma yok; PATH notu zaten var olan "her komut ayrı shell invocation" notunun doğal bir uzantısı olarak eklenmiş, tekrar/çelişki yaratmıyor.

## 4. Testlerin gerçekliği
5 testin 3'ü (`path_persistence` ×2, `batch_processing` ×2) yalnızca **string containment** kontrolü yapıyor (`"export" in lowered`, `"persist" in lowered`, `"script" in lowered` vb.) — davranışı değil, metnin varlığını doğruluyor. Bu, bir prompt-metni değişikliği için makul bir test stratejisi (prompt'un kendisi "davranış" değil, LLM'e giden statik metin — gerçek davranış testi ancak canary koşusuyla mümkün) ama **yüzeysel** olduğu açık: örneğin `"export" in lowered` gibi gevşek bir OR-koşulu, metnin TAM olarak istenen anlamı taşıyıp taşımadığını garanti etmez, sadece kelimenin bir yerde geçtiğini garanti eder. 5. test (`test_prompts_remain_generic_and_avoid_task_names`) daha değerli — gerçek bir regresyon sınıfını (hardcode sızması) yakalayabilir. Sonuç: testler TDD disiplinini doğru uyguluyor (red→green commit'leri ayrı) ama "yeni davranışı test etme" iddiası abartılı olmasın — bunlar prompt-metni varlık testleri, davranış testi değil. Bu, statik prompt değişiklikleri için beklenen/kabul edilebilir bir sınır.

## 5. Tam test suite doğrulaması
```
.venv/bin/python -m pytest starter/tests -q
114 passed in 0.69s
```
**114/114 iddiası DOĞRULANDI**, bağımsız olarak çalıştırıldı (worker1-agy'nin iddiasına güvenilmedi).

## 6. agy'nin flagledigi şüpheli nokta: "küçük modeller shell profile source etmeyi atlayabilir"
Bu endişe gerçek ve haklı. Prompt, PATH kalıcılığı için "sourcing a shell profile" seçeneğini bir alternatif olarak sunuyor, ama küçük/orta ölçekli modellerin (Qwen3-30B-A3B gibi) çok adımlı bir zinciri (profil dosyasını düzenle → `source` et → AYNI komutta veya sonraki komutlarda gerçekten kullan) güvenilir şekilde uygulaması şüpheli — özellikle her `terminal_exec` çağrısının ayrı bir shell invocation olduğu (zaten prompttaki 6. kuralın konusu) düşünülürse, `source ~/.bashrc` her yeni invocation'da TEKRAR çalıştırılmadıkça hiçbir işe yaramaz, ve model bunu unutabilir. **Ancak** prompt metni bunu tek seçenek olarak sunmuyor — "symlinking into /usr/local/bin or /usr/bin" seçeneğini de (ve muhtemelen daha güvenilir olanı, çünkü symlink kalıcı dosya-sistemi durumu, shell-oturumu durumu değil) ilk sırada veriyor. Yani riski azaltan bir tasarım tercihi zaten mevcut. Ek olarak sqlite-with-gcov/run2'deki gerçek vakada (plan.md'de belgelenen) modelin `export PATH=...` denemesi zaten "gerçek ama kapsam-dışı" bir doğrulamaydı — symlink çözümü bu spesifik vakayı da kapatırdı. **Değerlendirme:** flagleme doğru ama pratik risk düşük çünkü prompt zaten symlink'i öne çıkarıyor; ek bir aksiyon gerekmiyor, sadece izlenmesi gereken bir gözlem — bir sonraki canary koşusunda PATH-ile-ilgili trial'larda modelin hangi seçeneği (symlink vs. shell profile) seçtiği ayrıca not edilebilir.

## Sonuç
**Sorun yok — merge edilebilir.** Diff genel/yeniden-kullanılabilir, iki prompt'a tutarlı şekilde eklenmiş, mevcut kurallarla çakışmıyor, 114/114 test bağımsız doğrulandı. Testler yüzeysel (string-containment) ama bu bir prompt-metni değişikliği için makul bir sınır; hardcode-sızıntısı testi (`test_prompts_remain_generic_and_avoid_task_names`) ayrıca değerli bir ek güvence. agy'nin flagledigi "shell profile" riski gerçek ama prompt'un symlink alternatifini öne sürmesiyle zaten hafifletilmiş — merge'i engelleyecek bir bulgu değil.
