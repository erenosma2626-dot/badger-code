# v0.4.1 canary log analizi — batch C (2026-09-16, chess-best-move ×3 + fix-code-vulnerability ×3)

Saf log analizi. Kod dosyasına dokunulmadı, değiştirilmedi, sadece okundu (`agent.py`, `tools.py` teşhis amaçlı). Kaynak: `result.json` (`agent_result.metadata.messages`, `termination_reason`), `verifier/test-stdout.txt`, `trial.log`.

Tüm 6 trial `reward=0.0`.

## Özet tablo

| Trial | Görev | Turn | Sonlanma | Kök neden | Kategori | Güven |
|---|---|---|---|---|---|---|
| run1 vxBfYMi | chess | 16 | stuck_loop_detected | Aynı PNG üzerinde tekrarlanan `python3 -c` piksel-okuma denemeleri, `move.txt` hiç yazılmadı | `same_target_stuck` (doğru çalıştı) | Yüksek |
| run2 PgNGaJM | chess | 5 | stuck_loop_detected | Aynı desen, çok daha hızlı saplandı (3 turda) | `same_target_stuck` (doğru çalıştı) | Yüksek |
| run3 9RVFNAV | chess | 17 | stuck_loop_detected | Aynı desen, `chess_board_gray.png` türetip yine aynı döngüye girdi | `same_target_stuck` (doğru çalıştı) | Yüksek |
| run1 6NKkckU | vuln | 100 | max_turns | 9-10 dosyalık `read_file`+`cat` döngüsü, `write_file` 0 kez — **cyclic detector tetiklenmedi** | `cyclic_multi_target_loop` (KAÇIRILDI) | Çok yüksek |
| run2 gfEE5FY | vuln | 45 | stuck_loop_detected | Döngü kısa sürede kırılıp aynı `bottle.py`/tek komuta saplandı — same-target/exact-repeat yakaladı | `same_target_stuck` (doğru çalıştı, ama döngü değil) | Yüksek |
| run3 8i4XRK4 | vuln | 100 | max_turns | run1 ile birebir aynı 9-10 dosyalık döngü, yine yakalanmadı | `cyclic_multi_target_loop` (KAÇIRILDI) | Çok yüksek |

## chess-best-move (3/3 trial)

Üç trial de öncekinden (v0.4 batch3'teki "hayali tahta okuma / e2e4 hardcode") **farklı bir sorun** sergiliyor. Bu sefer model `e2e4` gibi sabit bir hamle yazmıyor; bunun yerine `chess_board.png`'yi (ve run3'te türettiği `chess_board_gray.png`'yi) art arda `python3 -c "from PIL import Image..."` tek-satırlık komutlarla piksel piksel okumaya çalışıyor, format/boyut/mode/pixel-value denemelerini tekrarlıyor, hiçbirinde tutarlı bir sonuca varamıyor ve `/app/move.txt`'ye hiçbir zaman yazmıyor. `extract_target` her seferinde aynı hedefi (`/app/chess_board.png`, run1'de bir ara yanlışlıkla komut metninden `img.mode` ifadesini hedef sanmış) çıkarıp `same-target stuck-loop` mekanizmasını doğru tetikledi (3 turda run2, 8-13 turda diğerleri), nudge sonrası tekrar edince doğru şekilde sonlandırdı. **Mekanizma burada TAM OLARAK NİYETİ GİBİ ÇALIŞTI** — sorun tespit değil, agent'ın görsel/pixel-analiz yeteneğinin (PIL ile satranç tahtası okuma) hâlâ işe yaramaz olması. Kategori: yeni bir taksonomi maddesi gerektirmiyor, mevcut `visual_extraction_failure`/`unsupported_completion` ailesine giriyor ama artık hardcode değil, gerçek (başarısız) analiz denemesi. **Güven: Yüksek** (üç trial de log'da birebir aynı komut deseniyle doğrulandı).

## fix-code-vulnerability (3/3 trial) — asıl teşhis

**run1 (6NKkckU) ve run3 (8i4XRK4), önceki kampanyadaki AYNI 9-10 dosyalık döngüsel `read_file`→`terminal_exec cat` desenini birebir tekrarlıyor**: `bottle.py → test_router.py → test_wsgi.py → test_fileupload.py/test_plugins.py → test_contextlocals.py → test_importhook.py → test_stpl.py → test_multipart.py → test_securecookies.py → (baştan)`, tam 100 tur boyunca ~5 tur döngü halinde, `write_file` sıfır kez çağrılıyor. Bu, tam olarak `find_cyclic_multi_target_loop()`'un yazılma amacı olan desen.

**Kök neden bulundu — pencere boyutu (K) yetersiz, hedef çıkarma mantığı DEĞİL:**

```python
CYCLIC_LOOP_WINDOW = int(os.environ.get("AGENT_CYCLIC_LOOP_WINDOW", "8"))
...
for cycle_len in range(2, max_window // 2 + 1):   # max_window=8 → cycle_len sadece 2,3,4
    span = cycle_len * 2
    ...
```

`max_window=8` ile fonksiyon **en fazla 4 uzunluğunda bir döngüyü** tespit edebilir (`8 // 2 = 4`, span=8 gerekir iki tam lap için). Gerçek döngü ise **9-10 farklı hedef** içeriyor, ve her hedef hem `read_file` hem `terminal_exec cat` ile iki kez ziyaret ediliyor — yani `cyclic_target_history`'de bir tam lap **18-20 giriş** tutuyor, iki lap karşılaştırması için **36-40 girişlik bir pencere** gerekiyor. Mevcut pencere (8) bunun beşte biri kadar. Fonksiyon `history[-span:]` ile sadece son 8 girişe (yaklaşık son 2 dosyanın read+cat çiftine) bakıyor, bu asla bir tam lap'i bile kapsamıyor — döngü matematiksel olarak yakalanamaz durumda, extraction mantığında hata yok (dosya adları doğru ve tutarlı çıkarılıyor, run2'de görülen `bottle.py`, `test_router.py` hedefleri tam isabetli).

**run2 (gfEE5FY) neden farklı bitti:** Model 45 turda tam döngüyü sadece kısmi tamamladı (tüm 9 dosyayı gezmeden), sonra `bottle.py` üzerinde tekrar eden `grep`/`python3 -c base64...` komutlarına saplandı — bu **aynı hedefe ardışık saplanma** (`same-target` veya `exact-repeat` sinyali), döngüsel değil. Mekanizma burada doğru çalıştı çünkü tetikleyici desen zaten "dar" stuck-loop'un kapsadığı türdendi, cyclic detector'a hiç ihtiyaç kalmadı.

**Sonuç:** v0.4.1'de yazılan `find_cyclic_multi_target_loop()` mantığı doğru tasarlanmış ama parametrelendirmesi bu görevin gerçek döngü uzunluğuna göre kalibre edilmemiş — 3'te 2 trial'da (en pahalı olanlar, 100 tur × ~5M input token) hâlâ hiç devreye girmiyor.

### v0.4.2 adayı düzeltme önerisi

`AGENT_CYCLIC_LOOP_WINDOW` varsayılanını artırmak — 9-10 hedefli bir döngüyü iki lap ile yakalamak için en az `2 * 2 * 10 = 40` gerekir (her hedef read_file+cat olarak iki girişe karşılık geldiği varsayımıyla). Önerilen: **`CYCLIC_LOOP_WINDOW` varsayılanını 8'den 40-48'e çıkarmak**, tek satırlık, düşük riskli bir sabit değişikliği. Alternatif/tamamlayıcı: `cyclic_target_history`'ye eklerken aynı hedefin ardışık `read_file`+`terminal_exec cat` çiftini TEK bir girişe sıkıştırmak (dedup) — bu, gereken pencereyi yarıya (~20) indirir ve daha az agresif bir büyütme ile aynı sonucu verir, ama `agent.py`'de ek bir dedup adımı gerektirir (window'u büyütmekten daha invaziv). **Öncelik sırası: önce pencereyi büyütmek (tek satır, düşük risk), yetersiz kalırsa dedup eklemek.**

## Genel çıkarım

- chess-best-move'da mekanizma (`same-target stuck-loop`) 3/3 doğru çalıştı; kalan sorun tamamen agent'ın görsel analiz yeteneğinde, tespit/nudge katmanında değil.
- fix-code-vulnerability'de `find_cyclic_multi_target_loop()` mantıksal olarak doğru ama `CYCLIC_LOOP_WINDOW=8` sabiti, görevin gerçek döngü uzunluğuna (9-10 hedef × 2 tool-call/hedef ≈ 18-20 giriş/lap) göre 4-5 kat küçük — bu yüzden en pahalı 2/3 trial'da (100 tur, 5M+ token) hâlâ hiç tetiklenmiyor. Bu, v0.4.1'in kapatmayı hedeflediği boşluğun parametre kalibrasyonu yüzünden hâlâ açık kaldığının doğrudan kanıtı.
