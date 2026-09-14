# SAF log analizi — batch 3 (2026-09-14)

İncelenen dört trial:

1. `starter/jobs/2026-09-14__19-25-08/chess-best-move__SfqXSHt` — BaselineAgent
2. `starter/jobs/2026-09-14__19-16-04/chess-best-move__BQF2HVK` — StructuredToolAgent
3. `starter/jobs/2026-09-14__19-42-41/fix-code-vulnerability__H4JHBcj` — BaselineAgent
4. `starter/jobs/2026-09-14__19-20-47/fix-code-vulnerability__sj4mcsY` — StructuredToolAgent

Not: Analiz yalnızca log/result/verifier okumaya dayanır. `.env` okunmadı, proje koduna dokunulmadı.

## 1. Chess — BaselineAgent (`SfqXSHt`)

- Kök neden: Agent geçerli bir action formatına ulaşamadı; ilk uzun `python3 -c` bloğunu eksik/yarım halde tekrar tekrar gönderdi. Runner her seferinde bunu geçersiz action sayıp aynı uyarıyı verdi; agent uyarıyı yeni bir yaklaşım üretmek için kullanamadı. Sonuçta 900 saniyelik agent timeout.
- Turn/kanıt: `agent_result.metadata.messages` idx 2, 4, 6, …, 40’ta aynı `PIL`/`numpy` tabanlı uzun bash bloğu görülüyor. Aradaki kullanıcı turn’lerinde aynı uyarı var: **“Your last response contained no valid action. Respond with exactly one bash code block or write_file block…”**
- Dış kanıt: `exception.txt`: **`harbor.trial.errors.AgentTimeoutError: Agent execution timed out after 900.0 seconds`**. Verifier `test-stdout.txt` ise `/app/move.txt` bulunamadığını bildiriyor (`FileNotFoundError`); `reward.txt` = `0`.
- Kategori: **Yeni öneri — action-format/parser uyumsuzluğu + invalid-action recovery loop**. İkincil: stuck-loop / ilerlemesiz tekrar.
- Güven: **Yüksek**.

## 2. Chess — StructuredToolAgent (`BQF2HVK`)

- Kök neden: Agent sonunda dosya yazabildi, fakat görüntüden konumu güvenilir biçimde çıkarmadan kaba bir sezgiye geçti ve yalnızca bir hamle seçti. Kendi ifadesiyle tüm taşları piyon varsayan “plausible” bir tahta çıkardı; ardından test/alternatif kazanan hamle araması yapmadan `e2e4` yazdı.
- Turn/kanıt: metadata mesaj idx 31’de `PIL is available`; idx 33’te `/app/analyze_chess.py` yazılıyor; idx 39’da çıktı **“Current board state:”** olarak kaba `p` işaretleri içeriyor; idx 40’ta agent **“assuming all pieces are pawns”** diyerek sınırlamayı açıkça kabul ediyor; idx 41’de `/app/move.txt` yalnız `e2e4` ile yazılıyor; idx 43’te kanıt **“contains the move 'e2e4'”** diyor.
- Verifier kanıtı: `test-stdout.txt` beklenen iki hamleyi açıkça veriyor: `g2g4` ve `e2e4`; assertion sonucu **`assert ['e2e4'] == ['e2e4', 'g2g4']`**. `reward.txt` = `0`.
- Kategori: Mevcut **girdiye bakmadan / girdiyi yetersiz analiz ederek cevap uydurma**; ayrıca **completion-evidence eksikliği / çözüm uzayını tamamlamadan bitirme**. Bu, salt “test etmedi” değil: görüntü analizi yöntemi baştan yetersiz olmasına rağmen sonuç kesinleştirildi.
- Güven: **Yüksek**.

## 3. Fix-code-vulnerability — BaselineAgent (`H4JHBcj`)

- Kök neden: Agent gerçek dosya içeriğini anlamlı biçimde okumadan fonksiyon adı tahminleriyle grep zincirine girdi; 1–27. turlar arasında aynı hedefi (`_parse_route`, sonra `_parse_qsl`/`urlunquote`) farklı grep süslemeleriyle aradı. Ardından kanıtı olmayan CWE listesiyle rapor yazmayı denedi, eksik/placeholder bir dosya değişikliği hazırladı ve 33. turda tüm `pytest -rA` testlerini çalıştırarak uzun süre kilitlendi.
- Turn/kanıt: `trial.log`/`job.log` turları 1–27’nin tamamı `cat ... | grep` veya `grep -r` varyasyonlarıdır; örneğin turn 1 **`cat /app/bottle.py | grep ... "def route"`**, turn 2–13 `_parse_route`, turn 14–27 `_parse_qsl`/`urlunquote`/`encoding`. Turn 28’de doğrudan **`{"file_path": "/app/bottle.py", "cwe_id": ["CWE-20", "CWE-79", "CWE-74"]}`** yazılmaya çalışılıyor. Turn 32’de içerik **`# ... (rest of the file remains`** olan placeholder düzenleme var. Turn 33: **`pytest -rA`**.
- Verifier durumu: Bu trial için istenen `result.json`, `verifier/test-stdout.txt` ve `verifier/reward.txt` trial klasöründe yok. Job-level `result.json` hâlâ `n_running_trials: 1`, `n_completed_trials: 0` gösteriyor; dolayısıyla reward/verifier başarısızlığını bu trial için uydurmak mümkün değil. Bu eksiklik, koşunun pytest aşamasında tamamlanmadan kaldığını destekliyor.
- Kategori: Mevcut **okumak yerine körlemesine grep tahmini** + **stuck-loop / ilerlemesiz arama**. İkincil yeni öneri: **kanıtsız teşhis ve placeholder edit ile erken çözüm denemesi**; ayrıca **uzun test komutunu timeout/izolasyon olmadan başlatma**.
- Güven: Kök neden için **Yüksek**; pytest’in tam olarak neden 13 dakika sürdüğü için **Orta** (log testin başladığını gösteriyor, verifier çıktısı yok).

## 4. Fix-code-vulnerability — StructuredToolAgent (`sj4mcsY`)

- Kök neden: Agent gerçek hedef fonksiyona ulaşmak yerine `read_file` çağrılarını/isimlerini tahmin ederek tekrarladı. Başarılı okumalar çoğunlukla yanlış veya test dosyalarına ait; başarısız okumalar aynı yaklaşımın varyasyonlarıyla sürdürülmüş. Sonuçta dosyadaki güvenlik açığını doğrulayacak hedef kodu izole edemedi ve düzeltme/rapor tamamlanmadı.
- Turn/kanıt: metadata’da idx 3–23 arasında art arda `read_file` sonuçları görülüyor; idx 5, 9, 11, 13, 15, 19 ve 21 başarısız (`exit_code: 1`), idx 7/17/23 gibi başarılı okumaların stdout’u test kodu veya alakasız içerik. Bu desen idx 201’e kadar sürüyor. `trial.log` dosyası da sonrasında anlamlı bir ilerleme/başarılı completion kaydetmiyor.
- Verifier kanıtı: `test-stdout.txt` 357 testte tek failure gösteriyor: **`TestResponse.test_prevent_control_characters_in_headers`**, `ValueError not raised by append`; yani header control-character doğrulaması düzelmemiş. `reward.txt` = `0`.
- Kategori: Mevcut **okumak yerine körlemesine grep/tahmin** (StructuredTool varyantında tekrarlı `read_file` tahmini) + **stuck-loop**. İkincil: **başarısız tool sonucundan sonra planı değiştirmeme**.
- Güven: **Yüksek**.

## Birleşik sonuç

Dört koşuda iki ayrı failure ailesi görülüyor:

1. **Eylem/loop kontrolü:** Baseline chess’te parser’ın reddettiği action’ın aynen tekrarı; her iki vulnerability koşusunda da bilgi kazandırmayan arama/okuma varyasyonlarının sürdürülmesi.
2. **Kanıt-temelli tamamlama eksikliği:** Structured chess, yetersiz görüntü çıkarımını kabul ettiği halde yalnız bir hamleyi kesin sonuç sayıyor; Baseline vulnerability ise hedef kodu doğrulamadan CWE ve placeholder değişiklik üretiyor.

Önerilen taksonomi ekleri:

- `invalid_action_recovery_loop`: parser reddinden sonra aynı/özde aynı action’ın yeniden üretilmesi.
- `unsupported_completion`: çözümün eksik veya yöntemin yetersiz olduğu açıkken test/kanıt olmadan tamamlandı sayılması.
- `blind_search_after_tool_failure`: başarısız/yanlış okumadan sonra hedefi yeniden çerçevelemek yerine grep/read varyasyonlarını sürdürme.

