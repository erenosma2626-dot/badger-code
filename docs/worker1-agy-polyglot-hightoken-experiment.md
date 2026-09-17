# Worker1-AGY: Polyglot-C-Py Yüksek Token (LLM_MAX_TOKENS=16384) İzolasyon Deneyi Raporu

**Tarih:** 17 Eylül 2026  
**Görev:** `terminal-bench/polyglot-c-py`  
**Dataset:** `terminal-bench/terminal-bench-2-1`  
**Koşum Parametreleri:** `-a agent.agent:StructuredToolAgent -n 1 -k 3 --env-file /tmp/env-polyglot-hightoken -y --job-name polyglot-hightoken-test`  
**Konfigürasyon:** `LLM_MAX_TOKENS=16384`  
**İş Çıktı Dizini:** `starter/jobs/polyglot-hightoken-test/`  
**Toplam Süre:** 20m 42s  

---

## 1. Deney Özeti ve Amaç

`main` branch'inde `LLM_MAX_TOKENS` varsayılanı 4096'ya çekilmişti. `polyglot-c-py` görevinde modelin tek seferde büyük `write_file` içeriği yazarken token sınırını aşıp `finish_reason="length"` alması ve tool-call'un kaybolması riski göz önüne alınarak, `LLM_MAX_TOKENS=16384` ile izole bir 3 trial'lık (`-k 3`) test gerçekleştirilmiştir.

---

## 2. Trial Sonuçları

| Trial ID | Reward | Sonuç | Turns | Termination Reason | `finish_reason=="length"` |
| :--- | :---: | :---: | :---: | :--- | :--- |
| `polyglot-c-py__yk8zUMq` | 0.0 | **FAIL** | 19 | `stuck_loop_detected` | **Yok (0 kez)** |
| `polyglot-c-py__TugiD37` | 0.0 | **FAIL** | 21 | `stuck_loop_detected` | **Var (1 kez, Turn 19)** |
| `polyglot-c-py__g6pJ3xi` | 0.0 | **FAIL** | 20 | `stuck_loop_detected` | **Yok (0 kez)** |

---

## 3. Detaylı Bulgular

1. **Trial 1 (`yk8zUMq`):**
   - 19 tur sürdü.
   - C ve Python sözdizimini birleştirmeye çalışırken syntax hatalarını tekrarladı; Turn 12'de stuck loop uyarısı aldı, Turn 19'da `stuck_loop_detected` ile sonlandırıldı.
   - Hiçbir `finish_reason="length"` görülmedi.

2. **Trial 2 (`TugiD37`):**
   - 21 tur sürdü.
   - Turn 14'te stuck loop uyarısı, Turn 18'de hedef-bazlı verimsiz deneme uyarısı aldı.
   - **Turn 19'da:** Model, yanıtında sözel akıl yürütme döngüsüne girip arka arkaya aynı cümleleri ("Let’s write it. But the `#if 0` is valid in C. And in Python, it's a comment... Let’s write it...") tekrarlayarak 54.336 karakter üretti. 16.384 token tavanını aşarak `finish_reason=length` aldı ve tool çağrısı oluşmadı.
   - Ajan `TRUNCATED_RESPONSE_MESSAGE` uyarısıyla toparlanmaya çalıştı, ancak syntax hatasını çözemeyerek Turn 21'de `stuck_loop_detected` ile sonlandırıldı.

3. **Trial 3 (`g6pJ3xi`):**
   - 20 tur sürdü.
   - Benzer syntax hatalarını tekrarlayarak Turn 17'de stuck loop uyarısı aldı, Turn 20'de `stuck_loop_detected` ile sonlandırıldı.
   - Hiçbir `finish_reason="length"` görülmedi.

---

## 4. Net Sonuç Cümleleri

- **16384 ile length sorunu ORTADAN KALKMADI.** (Modelin polyglot sözdizimini çözemediğinde düşünce/açıklama aşamasında tekrarlayan bir sözel döngüye girerek 16.384 token tavanını dahi doldurabildiği ve Turn 19'da `finish_reason=length` ürettiği görülmüştür).
- **Görev BAŞARISIZ oldu.** (0/3 passed, ortalama reward: 0.0; tüm trial'lar `stuck_loop_detected` ile sonlandı).

---

## 5. Güvenlik Notu

Geçici oluşturulan `/tmp/env-polyglot-hightoken` dosyası deney bitiminde güvenli şekilde silinmiş ve var olmadığı doğrulanmıştır. Orijinal `.env` dosyasına dokunulmamıştır.
