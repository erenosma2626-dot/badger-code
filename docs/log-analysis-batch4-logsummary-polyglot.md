# Log analizi — batch 4 (log-summary-date-ranges × 2, polyglot-c-py × 2)

Saf okuma/analiz görevi, 2026-09-14. Kod değişikliği yok, commit yok.

## Özet tablo

| Trial | Agent | Görev | Reward | Kök neden (kısa) | Kategori | Güven |
|---|---|---|---|---|---|---|
| ZPx3ivw | Baseline | log-summary | 0.0 | last_7_days ERROR sayısı yanlış (3322 vs beklenen 2969) — periyot sınır/örtüşme mantığında hata, kendi kendine doğrulama yüzeysel | **Yanlış sonuçla bitirme + yüzeysel öz-doğrulama** (yeni alt-kategori, "test etmeden bitirme" ailesinden) | Orta |
| hhJdMv5 | StructuredTool | log-summary | 0.0 | Sadece 3 log dosyasını (08-10/11/12) okudu, `/app/logs` dizinini hiç listelemedi/glob'lamadı — Temmuz'dan itibaren tüm veriyi atladı | **Girdiye bakmadan cevap** (kısmi veri kullanımı) | Yüksek |
| R2K5SX2 | Baseline | polyglot-c-py | (yok, AddTestsDirError) | Doğrulama aşamasında Docker container ("main" servisi) ayakta değildi — test dizini yüklenemedi | **API/altyapı donması** (container/ortam çökmesi, agent davranışıyla ilgisiz) | Yüksek |
| yP5txW5 | StructuredTool | polyglot-c-py | (yok, CancelledError) | Aynı `write_file` tool-call'unu 16 kez art arda gönderdi ama harness her seferinde "tool çağırmadın" dedi — tool-call formatı hiç tanınmadı, sonunda dış zaman aşımı/iptal | **Parser bug (stuck-loop'a dönüşen)** | Yüksek |

---

## 1. ZPx3ivw — log-summary-date-ranges, BaselineAgent, reward 0.0

**Kök neden:** Ajan periyot mantığını üç kez revize etti (mesaj 8→14→20→29→33), son haliyle bir log dosyasının birden fazla periyoda ("last_7_days" + "last_30_days" + "month_to_date" + "total") aynı anda katkı vermesine izin verdi. Bu düzeltme `month_to_date`'i sıfırdan kurtardı ama `last_7_days` için gerçek testin beklediği 2969 yerine 3322 ERROR üretti (fark ~353, yaklaşık bir günlük ERROR hacmi — sınır günü ya fazladan dahil edildi ya da çift sayıldı).

**Kanıt (mesaj 37-38, final CSV ve ajan yorumu):**
> `last_7_days,ERROR,3322` ... "The output now shows correct counts for all periods... The fix — allowing a log file to contribute to multiple periods — has resolved the issue."

Gerçek test (`verifier/test-stdout.txt`):
> `AssertionError: Expected row ['last_7_days', 'ERROR', '2969'], got ['last_7_days', 'ERROR', '3322']`

**Mesaj 39-40 — "verification stale" burada geçerli:** Harness ajana "bitirdiğini iddia ediyorsun ama doğrulama kanıtı yok" diye sordu, ajan CSV'yi tekrar okumadı/yeniden hesaplamadı, sadece önceki debug çıktılarını (period atama mantığının "doğru" olduğunu) tekrar anlattı — gerçek bir re-check yapmadı, sadece anlatısal bir "evet doğru" cevabı verdi.

**Kategori:** Mevcut "test etmeden bitirme" kategorisine yakın ama tam örtüşmüyor — ajan test/doğrulama *yaptı* (CSV'yi okudu), sorun onun **sınır-koşulu mantık hatası** ve doğrulama isteğine **yüzeysel/performatif** yanıt vermesiydi (ground-truth'u tekrar kontrol etmek yerine önceki adımları özetledi). Öneri: yeni alt-kategori — **"yüzeysel öz-doğrulama"** (nudge'a gerçek bir kontrolle değil anlatıyla cevap verme).

**Olasılık/güven:** Orta. Alternatif açıklama: ajanın erişemediği ground-truth zaten farklı bir referans-tarih varsayımına dayanıyor olabilir (ör. "today" tanımı test fixture'ında farklı olabilir) — ajanın mantığı iç-tutarlı ama testin referans tarihiyle uyuşmuyor olabilir. Bunu doğrulamak için testin `EXPECTED_ROWS`'unun nasıl üretildiğini görmek gerekir (bu görev kapsamı dışında, koda dokunmadım).

---

## 2. hhJdMv5 — log-summary-date-ranges, StructuredToolAgent, reward 0.0

**Kök neden:** Ajan dizini hiç `ls`/glob ile listelemedi; sadece 3 dosyayı (`read_file` ile 08-10, 08-11, 08-12) manuel okudu ve script'i sadece bu 3 günü kapsayacak şekilde yazdı (mesaj 2-16). Gerçekte `/app/logs` içinde Temmuz başından itibaren onlarca dosya var (bkz. Baseline trial'ının aynı görevdeki `ls` çıktısı: 2025-07-03'ten başlıyor).

**Kanıt (mesaj 29, final CSV):**
> `last_7_days,ERROR,294` / `last_30_days,ERROR,294` / `month_to_date,ERROR,294` / `total,ERROR,294`

Dört farklı periyodun (7 gün, 30 gün, ay-başından-bugüne, toplam) **tamamen aynı sayıyı** vermesi, script'in yalnızca 3 günlük veri üzerinde çalıştığının doğrudan kanıtı — gerçek veri setinde bu dört değerin özdeş olması istatistiksel olarak imkansız (30 günlük ve toplam veri çok daha büyük olmalı).

**Ek gözlem (mesaj 17, 21):** İki kez "son cevabın hiçbir tool çağırmadı" uyarısı aldı ve toparlandı — bu trial'da fatal değildi ama yP5txW5'teki daha ciddi versiyonuyla aynı altyapısal zayıflığa işaret ediyor (bkz. trial 4).

**Kategori:** **Girdiye bakmadan cevap** — ama daha kesin ifadeyle "kısmi/eksik girdi keşfi": ajan girdiye baktı ama tamamına değil, ilk gördüğü birkaç dosyayla sınırlı kaldı ve bunun yeterli olup olmadığını hiç sorgulamadı.

**Olasılık/güven:** Yüksek. Alternatif açıklama yok — dört periyodun birebir eşit olması başka bir yorumla açıklanamaz.

---

## 3. R2K5SX2 — polyglot-c-py, BaselineAgent, reward yok (AddTestsDirError)

**Kök neden:** Bu bir agent-mantığı hatası değil, **doğrulama aşamasında altyapı hatası**. `verifier/verifier.py` test dizinini container'a yüklemeye çalışırken Docker Compose "main" servisinin artık ayakta olmadığını (`no container found for service "main"`, sonra `service "main" is not running`) tespit etti ve `AddTestsDirError` fırlattı. `test-stdout.txt` ve `reward.txt` boş — testler hiç çalışamadı.

**Kanıt (`exception.txt`):**
> `RuntimeError: Docker compose command failed for environment polyglot-c-py ... cp ... Stdout: no container found for service "main"` → sonra tar fallback'te de `service "main" is not running` → `AddTestsDirError: Failed to add tests directory to environment.`

**Not:** `agent_result.metadata.messages` bu trial için mevcut değildi (muhtemelen ajan fazına ulaşamadan/agent fazı sırasında container çöktüğü için log kaydedilmemiş — kontrol ettim, `messages` alanı boş/None döndü).

**Kategori:** **API/altyapı donması** — spesifik olarak "container/ortam çökmesi" (mevcut taksonomideki "API/altyapı donması" başlığı altına giriyor ama sebep bir LLM API'si değil, Docker environment'ın kendisi). Öneri: bu alt-türü ayırmak isterseniz **"ortam (container) erken sonlanması"** diye ayrı bir alt-kategori açılabilir.

**Olasılık/güven:** Yüksek — traceback net ve tekil bir açıklamaya işaret ediyor (container servis olarak ayakta değil). Alternatif açıklama: ajanın kendisi container'ı bir komutla durdurmuş/crash ettirmiş olabilir (ör. `apt-get`, `shutdown`, kaynak tükenmesi) ama mesaj geçmişi olmadığı için bunu doğrulayamadım — bu nedenle "yüksek" ama kesin değil.

---

## 4. yP5txW5 — polyglot-c-py, StructuredToolAgent, CancelledError

**Kök neden:** Ajan ilk turda (mesaj 2) `write_file` tool-call'unu gönderdi ama format harness tarafından tanınmadı ("Your last response didn't call any of the four tools"). Ajan **aynı içerikle aynı tool-call'u 16 kez üst üste tekrar gönderdi** (mesaj 2, 4, 6, 8, ..., 32 — hepsi aynı `write_file`/`main.py.c` içeriği), her seferinde aynı ret mesajını aldı, hiç format değiştirmedi/farklı bir yaklaşım denemedi. Trial, 34. mesajda (yine "tool çağırmadın" uyarısıyla) dış bir `CancelledError`/timeout ile kesildi — muhtemelen tur/süre limitine çarpıldığı için harness tarafından iptal edildi.

**Kanıt (mesaj 2 ve 33, birebir aynı):**
> mesaj 3: "Your last response didn't call any of the four tools (terminal_exec, write_file, read_file, task_complete). Call exactly one of them now."
> mesaj 33: (34 mesaj sonra) aynı uyarı, ajan hâlâ ilerleme kaydetmemiş.

`exception.txt`: `asyncio.exceptions.CancelledError` — `llm.chat_tools()` içinde bekleyen bir HTTP isteği iptal edildi (muhtemelen trial'ın dış zaman aşımı/iptal sinyali, StructuredToolAgent'ın 16 turluk döngüsünün süresi doldurduğu için).

**Kategori:** **Parser bug → stuck-loop'a dönüşüyor.** Bu, mevcut "stuck-loop" kategorisinden farklı çünkü ajan farklı turlarda *aynı eylemi tekrar tekrar* göndermiyor bir mantık döngüsünde değil — sorun, StructuredToolAgent'ın tool-call'unu ayrıştıran/kabul eden tarafın (agent.py / harness) bu formatı bir nedenle reddetmesi. Mesaj içeriğine bakıldığında `tool_call` JSON'u normal görünüyor; format uyuşmazlığının kesin sebebini (örn. beklenen şema farkı, prompt'taki tool-call sözdizimi talimatı ile üretilenin uyuşmaması) bu analiz kapsamında (kod dosyasına dokunmadan) tam teşhis edemedim.

**Kategori önerisi:** Yeni kategori — **"tool-call parser uyuşmazlığı"** (StructuredToolAgent'a özgü, format kabul edilmiyor → turlar tükeniyor → dış iptal). Bu, "stuck-loop" ile "API/altyapı donması" arasında farklı bir sınıf: kök neden ajan tarafında değil, agent-harness arayüzünde.

**Olasılık/güven:** Yüksek (mesaj deseni çok net — 16 kez birebir aynı istek/ret döngüsü) ama kesin format uyuşmazlığının nedeni (agent.py/StructuredToolAgent kodunda) bu analizin kapsamı dışında — implementasyon tarafı incelenmeli. Alternatif açıklama: ajan `tool_call` JSON'unu doğru gönderdi ama harness'ın parser'ı belirli bir alanı (örn. `id` veya `type`) bekliyor olabilir; bu koda bakmadan doğrulanamaz.

---

## Genel gözlem

- İki log-summary trial'ı da **tarih/periyot mantığında farklı hatalar** yaptı (biri sınır hatası, diğeri eksik veri keşfi) — ikisi de aynı kök nedenden değil, ayrı ayrı ele alınmalı.
- İki polyglot trial'ı da **agent mantığıyla ilgisiz altyapı sorunları** yaşadı (container çökmesi / tool-call parser uyuşmazlığı) — bu ikisi muhtemelen mevcut smoke-test bulgularına yeni, agent-davranışı-dışı bir hata sınıfı ekliyor ve `docs/plan.md`'deki "API/altyapı donması" kategorisinin genişletilmesini gerektirebilir.
