# Worker1-agy v0.5.2 Fixes Uygulama Raporu

**Tarih:** 2026-09-17  
**Branch:** `feature/v0.5.2-fixes` (temel: `main` @ `4d60e56`)  
**Durum:** Tamamlandı, 122/122 test geçti, review'a hazır.

---

## 1. Commit — Fix Eşleştirmesi ve Değişen Dosyalar

| Commit | Kapsam / Fix | Değişen Dosyalar |
|---|---|---|
| `9b76e0b` | **Fix 1 (KRİTİK):** `write_file` blind-spot düzeltmesi (stuck-loop / cyclic-loop) | `starter/agent/agent.py`<br>`starter/tests/test_structured_agent_stuck_loop.py`<br>`starter/tests/test_structured_agent_cyclic_loop.py` |
| `39f3922` | **Fix 2:** Parçalı-yazma / patolojik regex prompt kuralı | `starter/agent/prompts.py`<br>`starter/tests/test_prompts_v052_notes.py` |
| `4242899` | **Fix 3:** Aktif `python3` path vs `apt-get` sistem paket yöneticisi rehberliği | `starter/agent/prompts.py`<br>`starter/tests/test_prompts_v052_notes.py` |

---

## 2. Her Fix İçin Yaklaşım Özeti (2-3 Cümle)

### Fix 1 — `write_file` Blind-Spot (`agent.py:831`)
- **Yaklaşım:** `starter/agent/agent.py` içindeki `if name in ("terminal_exec", "read_file"):` bloğu `write_file`'ı kapsayacak şekilde genişletildi (`("terminal_exec", "read_file", "write_file")`).
- **Fingerprint & Target Tasarımı:** `write_file` için `combined_output`, `(receipt.content_sha256 or "") + receipt.stderr_tail` olarak tanımlandı; böylece aynı dosyaya farklı içerik yazıldığında parmak izi farklı çıkarak yanlış `exact_repeat` tetiklenmesi önlendi, birebir aynı yazma tekrarlarında ise parmak izi eşleşti. Hedef (`target`) olarak doğrudan dosya yolu (`command_or_path`) kullanılarak `target_attempt_counts` ve `cyclic_target_history`'ye entegre edildi; başarılı yazmada (`exit_code == 0`) `is_unproductive_attempt` `False` dönüp attempt sayacını sıfırlarken hedef geçmişi döngüsel çoklu-hedef (`cyclic_multi_target_loop`) tespiti için kaydedilmektedir.

### Fix 2 — Parçalı-Yazma / Patolojik Regex Prompt Notu
- **Yaklaşım:** `starter/agent/prompts.py` içinde hem `SYSTEM_PROMPT` (Kural 9) hem de `STRUCTURED_SYSTEM_PROMPT` güncellendi.
- **Detay:** Çok sayıda negatif lookahead içeren patolojik regex'lerin token limitini zorlayıp `finish_reason=length` kesilmesine yol açtığı açıkça belirtildi; karmaşık eşleştirme, filtreleme ve sayma mantığının tek bir devasa regex yerine satır satır işleme, basit string ayırma veya tarih/saat parsing gibi düz Python kodunda yapılması genel bir prensip olarak eklendi (hiçbir görev adı kullanılmadı).

### Fix 3 — Aktif Python3 Path vs Sistem Paket Yöneticisi Rehberliği
- **Yaklaşım:** `starter/agent/prompts.py` içinde `SYSTEM_PROMPT` (Kural 11, `TASK_COMPLETE` Kural 12'ye kaydırıldı) ve `STRUCTURED_SYSTEM_PROMPT`'a yeni genel rehberlik eklendi.
- **Detay:** `apt-get install python3-...` gibi sistem paket yöneticisi kurulumlarının işletim sisteminin varsayılan Python dizinlerine kurulduğu, ancak aktif yorumlayıcının (`which python3` ile kontrol edilebilen, örn. `/usr/local/bin/python3` veya venv) arama yoluna girmeyebileceği vurgulandı; bu nedenle aktif ortama doğrudan kurulum için `python3 -m pip install <paket>` kullanılmasının daha güvenilir olduğu genel kural olarak yazıldı (hiçbir görev adı kullanılmadı).

---

## 3. Test ve Doğrulama Sonuçları

- **TDD Disiplini:** Her fix için önce başarısız testler yazıldı (`test_identical_write_file_repeated_triggers_stuck_loop`, `test_two_full_cycles_through_four_targets_with_write_file_triggers_cyclic_loop`, `test_prompts_v052_notes.py`), hata alındığı teyit edildi, ardından minimum kod yazılarak testler yeşile döndürüldü.
- **Test Sonucu:** **122 / 122 passed in 1.00s** (0 failure, 0 error).
- **Regresyon Durumu:** Tüm mevcut testler (114 eski + 8 yeni eklenen) eksiksiz geçti, sıfır regresyon.

---

## 4. Şüpheli / Dikkat Çeken / Emin Olunmayan Noktalar

1. **`write_file` için `target_is_stuck` davranışı:**
   - Aynı dosyaya art arda farklı içerikler yazıldığında `exit_code == 0` olduğu için bu adımlar "üretken" sayılır ve `target_attempt_counts[target]` sıfırlanır (bu sayede ardışık kod geliştirmeleri sahte stuck-loop ile öldürülmez; doğrulamama riski zaten `verification_status` ve kanıt kapısı tarafından korunur).
   - regex-log run2'deki gibi birebir aynı dosya yolu ve aynı içerik 3 kez tekrarlandığında `exact_repeat_stuck` devreye girer, nudge atar ve 4. turda `stuck_loop_detected` ile sonlandırır (95 turluk kısırdöngü tam olarak kapanmıştır).
2. **`STRUCTURED_SYSTEM_PROMPT` token uzunluğu:**
   - Eklenen 2 kural prompt'a yaklaşık 60-70 kelime eklemiştir. Genel token bütçesi için ihmal edilebilir düzeydedir ve genel yapıyı bozmamıştır.
