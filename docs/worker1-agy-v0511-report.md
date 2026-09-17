# Worker1-AGY: v0.5.1 Prompt Notları Uygulama Raporu

**Tarih:** 17 Eylül 2026  
**Branch:** `feature/v0.5.1-prompt-notes`  
**Kapsam:** v0.5.1 için 2 genel prompt kuralının (`prompts.py`) TDD ile eklenmesi

---

## 1. Değişen ve Eklenen Dosyalar

- `starter/tests/test_prompts_v051_notes.py` *(Yeni)*: PATH kalıcılığı, toplu işleme (batch processing) kurallarını ve görev-spesifik isimlerin bulunmadığını doğrulayan 5 unit test.
- `starter/agent/prompts.py` *(Değiştirildi)*: `SYSTEM_PROMPT` (Kural 6 genişletildi, Kural 10 toplu işleme eklendi, Kural 11 TASK_COMPLETE oldu) ve `STRUCTURED_SYSTEM_PROMPT` (shell kalıcılığı ve toplu işleme kuralları eklendi).
- `docs/worker1-agy-v0511-report.md` *(Yeni)*: Görev sonuç ve doğrulama raporu.

---

## 2. Yaklaşım Özeti

1. **PATH / Kalıcılık Farkındalığı Kuralı:** `sqlite-with-gcov` bulgusuna istinaden, her komutun ayrı bir shell süreci olduğu, `export PATH=...` ayarlarının sonraki adımlara veya harici verifier sürecine miras kalmayacağı belirtildi. Kalıcı yol olarak `/usr/local/bin` veya `/usr/bin` altına sembolik link (symlink) oluşturma ya da shell profili düzenleyip kaynak gösterme mekanizmaları önerildi.
2. **Toplu-İşleme (Batch Processing) Kuralı:** `log-summary-date-ranges` bulgusuna istinaden, çok sayıda (5+) benzer veya homojen dosya (log, veri tablosu vb.) işlenirken turn/token sınırına takılmamak için dosyaları tek tek okumak yerine Python veya bash döngü/glob içeren tek bir script yazılarak programatik toplu işleme yapılması kuralı eklendi.
3. **Genel Nitelik:** Kurallar hem `SYSTEM_PROMPT` hem de `STRUCTURED_SYSTEM_PROMPT` içine görev hardcode'u yapılmaksızın genel mühendislik yönergeleri olarak yerleştirildi.

---

## 3. Commit Eşleştirmesi

1. `f42a508` — `test: add unit tests for v0.5.1 PATH persistence and batch processing prompt rules` (TDD Red aşaması)
2. `3536573` — `feat(prompts): add PATH persistence and batch processing general rules for v0.5.1` (Green aşaması)
3. *[Bu rapor commit'i]* — `docs: add worker1-agy v0.5.1 prompt notes implementation report`

---

## 4. Test Durumu

- **Yeni TDD Testleri:** `5/5 passed` (`tests/test_prompts_v051_notes.py`)
- **Tüm Test Paketi:** `114/114 passed` (0 regresyon)

---

## 5. Şüpheli / Dikkat Edilmesi Gereken Nokta

Prompt kuralları net ve görevden bağımsız ifade edildi; ancak küçük açık kaynak modellerin shell profile düzenlemelerinde dosya kaynak göstermeyi (`source ~/.bashrc`) bazen atlayabildikleri bilindiğinden, PATH kalıcılığı için `/usr/local/bin` altına symlink oluşturma yönteminin model tarafından önceliklendirilip önceliklendirilmediği v0.5.1 canary koşumunda izlenmelidir.
