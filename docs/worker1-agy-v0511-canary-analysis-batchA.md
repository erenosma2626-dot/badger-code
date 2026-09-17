# v0.5.1 Canary Analiz Raporu — Parça A (worker1-agy)

**Tarih:** 2026-09-17  
**İncelenen Koşumlar:** v0.5.1 Canary (`jobs/v051-canary-run1/2/3`) vs v0.5 Baseline (`starter/jobs/v05-baseline-run1/2/3`)  
**Kapsam:** `configure-git-webserver`, `sqlite-with-gcov`, `chess-best-move`

---

## 1. configure-git-webserver: GERÇEK Regresyon mu, Doğal Varyans mı?

### 🔴 Net Karar
**configure-git-webserver GERÇEK BİR REGRESYON DEĞİLDİR; n=3'ün doğal stokastik varyansıdır.**

v0.5.1 ile gelen değişikliklerin (PATH kalıcılığı prompt notu, toplu-işleme prompt notu ve `LLM_MAX_TOKENS=4096` düşüşü) bu iki FAIL trial'ı üzerinde **hiçbir negatif etkisi veya nedensel bağı bulunmamaktadır**.

---

### Kanıtlar ve İki FAIL Trial'ın Derinlemesine Transcript Analizi

#### A) Token Tavanı (4096) ve Prompt Notlarının İzolasyonu
1. **Token Limiti:**
   - Run 1 (`configure-git-webserver__Y29EXy8`): 97 tur boyunca toplam 3.690 output token üretildi (tur başına ortalama ~38 token).
   - Run 3 (`configure-git-webserver__HsoyyKM`): 57 tur boyunca toplam 3.618 output token üretildi (tur başına ortalama ~63 token).
   - Hiçbir turda 4096 sınırına yaklaşılmadı, sıfır truncation (`finish_reason="length"` = 0).
2. **v0.5.1 Prompt Notları:**
   - Ne PATH kalıcılığı ne de toplu-işleme (batch script) notu bu görevde model tarafından yanlış yorumlanmadı, tetiklenmedi veya bir hataya yol açmadı.

---

#### B) Trial 1 Detayı (`jobs/v051-canary-run1/configure-git-webserver__Y29EXy8` — FAIL 0.0, 97 Tur)

1. **Paket Seçimi Hatası:**
   - **Turn 4 (Msg 8):** Model `terminal_exec: apt-get update && apt-get install -y git` çalıştırdı. `openssh-server` paketini kurmadı.
2. **Kritik Konfigürasyon Hatası (Nginx `alias` Bug'ı):**
   - **Turn 31 (Msg 62):** `/etc/nginx/sites-available/git-server` dosyasına şu konfigürasyonu yazdı:
     ```nginx
     server {
         listen 8080;
         server_name localhost;
         location / {
             alias /var/www/html;
             index index.html;
         }
     ```
   - Nginx'te `location /` bloğunda `root /var/www/html;` yerine `alias /var/www/html;` kullanılması, `/hello.html` isteklerinin 404 dönmesine yol açar.
3. **Kapsam Dışı Doğrulama Tuzağı ve `/etc/hosts` Bozulması:**
   - **Turn 41 (Msg 82):** Model `/tmp/test-git-push.sh` oluşturarak kullanıcı akışını test etmeye kalktı: `git push origin master` (`origin: user@server:/git/server`).
   - `server` çözülemediği için `ssh: Could not resolve hostname server` hatası aldı.
   - **Turn 44 (Msg 88):** Hatayı çözmek için `write_file` ile `/etc/hosts` dosyasını `127.0.0.1   server\n` içeriğiyle **tamamen üzerine yazdı**. Docker container'ın varsayılan DNS/host çözümleme yapısı bozuldu.
   - **Turn 45 (Msg 90):** Tekrar çalıştırdığında `ssh: connect to host server port 22: Connection refused` aldı (`openssh-server` kurulu olmadığı için).
   - **Turn 46 (Msg 92):** Guardrail devreye girdi: `stuck loop detected (3 unproductive attempts against target '/tmp/test-git-push.sh'), sending nudge`.
4. **50 Turluk 404 Kısırdöngüsü ve Sonlanma:**
   - **Turn 50 (Msg 101):** Model `/tmp/test-git-push.sh`'ı bırakıp web sunucusunu test etti: `curl -s http://localhost:8080/hello.html`. Nginx `alias` hatası yüzünden `404 Not Found` cevabı aldı.
   - **Turn 50 - 97:** Model sonraki ~50 tur boyunca dosyanın `/var/www/html/hello.html` altında olduğunu görüp `service nginx reload` ve `curl -s http://localhost:8080/hello.html` arasında kilitlendi. `alias` satırını düzeltmeyi akıl edemedi.
   - **Turn 97 (Msg 197):** `stuck loop repeated after nudge, terminating` ile guardrail tarafından öldürüldü.
5. **Verifier Durumu:**
   - Turn 44'te `/etc/hosts` ezildiği için Harbor verifier'ı çalışırken Astral releases sunucusuna erişemedi: `curl: (6) Could not resolve host: releases.astral.sh`. Ancak verifier çalışsaydı bile Nginx 404 döndüğü için yine 0.0 alacaktı.

---

#### C) Trial 3 Detayı (`jobs/v051-canary-run3/configure-git-webserver__HsoyyKM` — FAIL 0.0, 57 Tur)

1. **Paket Seçimi:**
   - **Turn 4 (Msg 8):** Model sadece `git` kurdu (`apt-get install -y git`), `openssh-server` kurmadı.
2. **Kapsam Dışı SSH Doğrulama Tuzağı:**
   - **Turn 29 (Msg 58):** Model `/tmp/test-push.sh` yazdı:
     ```bash
     git remote add origin user@server:/git/server
     git push origin master
     ```
   - Görev metninde açıkça *"I'll setup login with the server to work, you don't have to worry about that."* denmesine rağmen, sistem prompt'undaki "VERIFY before finishing" kuralı gereği model bu push'u doğrulamaya saplandı.
   - **Turn 31-56:** SSH portu (22) dinlemediği için `ssh: connect to host server port 22: Connection refused` hatası aldı. Model `/etc/hosts`'u düzenledi, `cd /tmp/test-repo && git push origin master` komutunu defalarca tekrarladı.
   - **Turn 51:** `stuck loop detected (3 unproductive attempts against target '/tmp/test-repo'), sending nudge`.
   - **Turn 57:** Model aynı başarısız komutu tekrarlayınca `stuck loop repeated after nudge, terminating` ile öldürüldü.
3. **Verifier Çıktısı:**
   - Verifier `verify.sh` çalıştırdı:
     ```
     AssertionError: Did not pass test
     ❌ TEST FAILED: Web server returned HTTP 404
     fatal: not a git repository (or any of the parent directories): .git
     ```
   - Modelin yazdığı post-receive hook (`git archive --format=tar HEAD | tar -x -C /var/www/html`), bare repoda doğru GIT_DIR/work-tree olmadan çalışmadığı için dosyalar `/var/www/html`'e aktarılamamıştı.

---

#### D) Run 2 ile Karşılaştırma (Neden Run 2 Geçti?)
- Run 2 (`configure-git-webserver__8BLoZNr` — PASS 1.0, 28 Tur):
  - **Turn 1 (Msg 2):** Doğrudan `apt-get update && apt-get install -y git openssh-server nginx` kurdu.
  - **Turn 5 (Msg 10):** `/etc/ssh/sshd_config` yapılandırıldı (`PermitRootLogin yes`).
  - **Turn 27 (Msg 54):** `curl -s http://localhost:8080/hello.html` test edildi (HTTP 200).
  - **Turn 28 (Msg 56):** `task_complete` çağrıldı ve PASS (1.0) alındı.

#### E) v0.5 Baseline ile Karşılaştırma
- v0.5 baseline'da da model run1-retry (`qDSWYti`) ve run2'de (`K3nFokq`) ilk adımda `openssh-server` paketini kurmuş ve SSH servislerini ayağa kaldırmıştı.
- Model stokastik olarak `openssh-server` paketini kurup kurmama kararına göre ikiye ayrılmaktadır:
  - **Patika 1 (Kazanan):** `openssh-server` kurulur -> `user@server` test push'u takılmaz veya HTTP doğrulanıp bitirilir -> PASS (v0.5 r1, r2, r3 ve v0.5.1 r2).
  - **Patika 2 (Tuzak):** Sadece `git` kurulur -> model SSH push simülasyonu dener -> `Connection refused` alır -> `/etc/hosts` bozar ve döngüye girer -> FAIL (v0.5.1 r1 ve r3).
- Dolayısıyla v0.5'teki 3/3 ile v0.5.1'deki 1/3 arasındaki fark, modelin n=3 içerisindeki yaklaşım varyansıdır; scaffold veya prompt regresyonu değildir.

---

## 2. sqlite-with-gcov Analizi: PATH Kalıcılık Notu Etkili Oldu mu?

### 🟡 Net Sonuç
**PATH kalıcılık prompt notu model tarafından OKUNDU ve DOĞRUDAN UYGULANDI (Run 1 kanıtı); ancak görevler başka model hataları nedeniyle FAIL aldı.**

### Trial İncelemeleri

1. **Run 1 (`sqlite-with-gcov__oVcrHDz` — AgentTimeoutError / 47 Tur):**
   - **Kanıt (PATH Notu Çalıştı):**
     - Model derlemeyi tamamladıktan sonra, **Turn 18 / Msg 36**'da tam olarak prompt notunda önerilen yöntemi uyguladı:
       ```json
       terminal_exec: {"command": "cd /app && ln -sf /app/sqlite/sqlite3 /usr/local/bin/sqlite3"}
       ```
     - Model geçici bir `export PATH=...` yerine doğrudan `/usr/local/bin` altına symlink oluşturdu. Prompt notunun yönlendirmesi %100 başarılı oldu.
   - **Neden Başarısız Oldu (Sonsuz Özyineleme / Fork-bomb Bug'ı):**
     - Ancak model, bu adımdan iki tur önce **Turn 16 / Msg 32**'de derlenen ikili dosyanın üzerine anlaşılmaz bir şekilde şu wrapper script'i yazdı:
       ```bash
       #!/bin/bash
       exec /app/sqlite/sqlite3 "$@"
       ```
     - Kendini çağıran bu betik, `sqlite3 --version` çalıştırıldığında sonsuz özyinelemeye girdi.
     - **Turn 19 (Msg 38) ve Turn 21 (Msg 42):** Komutlar `Command timed out after 60 seconds` ile patladı.
     - Art arda gelen 60 saniyelik komut zaman aşımları toplam çalışma süresini 900 saniye tavanına ulaştırdı ve Harbor `Verifier execution timed out after 900.0 seconds` hatasıyla `AgentTimeoutError` üretti.
2. **Run 2 (`sqlite-with-gcov__ovF7LVQ` — FAIL 0.0, 15 Tur) ve Run 3 (`sqlite-with-gcov__3Zx432z` — FAIL 0.0, 20 Tur):**
   - Her iki trial'da da model derleme aşamasına **hiç ulaşamadı**.
   - Model `./configure` betiğine SQLite autoconf'un desteklemediği bayrakları ısrarla gönderdi:
     - Run 2 Turn 10 (Msg 20): `./configure --enable-coverage` -> `Error: Unknown option --coverage`
     - Run 2 Turn 11 (Msg 22): `./configure ... --with-cc=gcc` -> `Error: Unknown option --with-cc`
     - Run 2 Turn 15 (Msg 31): `./configure --enable-gcov ... --with-cc=gcc` -> `stuck loop repeated after nudge, terminating` (Turn 15).
     - Run 3 Turn 10, 16, 20: Benzer şekilde `--enable-coverage` ve `--with-cc` argümanlarında ısrar edilerek stuck-loop ile Turn 20'de öldürüldü.
   - Bu iki trial derleme yapamadığı için PATH kalıcılık aşamasına hiç gelemedi.

---

## 3. chess-best-move Analizi: v0.5'teki "3/3 completion_rejected" Örüntüsü Hâlâ Aynı mı?

### 🟢 Net Sonuç
**HAYIR, ÖRÜNTÜ TAMAMEN DEĞİŞTİ (0/3 completion_rejected).**

v0.5 baseline'da 3/3 olan `completion_rejected_no_new_evidence` engeli, v0.5.1 canary'de **0/3'e düşmüştür**. Üç trial'ın üçünde de agent'ın doğrulama kanıtı guardrail tarafından kabul edilmiş (`acknowledged: true`), süreç verifier'a teslim edilmiştir.

### Karşılaştırma Tablosu

| Koşum | Trial ID | Tur Sayısı | Bitiş Şekli / Guardrail Yanıtı | Verifier Sonucu |
|---|---|---|---|---|
| **v0.5 Baseline Run 1** | `chess-best-move__UjbGeir` | 14 | `completion_rejected_no_new_evidence` (hard reject) | FAIL (0.0) |
| **v0.5 Baseline Run 2** | `chess-best-move__rkgqGvS` | 27 | `completion_rejected_no_new_evidence` (hard reject) | FAIL (0.0) |
| **v0.5 Baseline Run 3** | `chess-best-move__RUVhD7P` | 20 | `completion_rejected_no_new_evidence` (hard reject) | FAIL (0.0) |
| **v0.5.1 Canary Run 1** | `chess-best-move__CFzgQZ5` | 23 | **`acknowledged: true` (task_complete onaylandı)** | FAIL (0.0) - `test_move_correct` AssertionError |
| **v0.5.1 Canary Run 2** | `chess-best-move__q5LnaFZ` | 12 | **`acknowledged: true` (task_complete onaylandı)** | FAIL (0.0) - `test_move_correct` AssertionError |
| **v0.5.1 Canary Run 3** | `chess-best-move__D2nkEmn` | 12 | **`acknowledged: true` (task_complete onaylandı)** | FAIL (0.0) - `test_move_correct` AssertionError |

### Transcript Kanıtları (v0.5.1)
- **Run 1:** Turn 21'de `/app/chess_analysis.py` çalıştırıldı, Turn 22'de `read_file: /app/move.txt` okundu (`g2g7`), Turn 23'te somut kanıtla `task_complete` çağrıldı -> `acknowledged: true`.
- **Run 2:** Turn 10'da Python analiz script'i çalıştırıldı, Turn 11'de `read_file: /app/move.txt` okundu (`e2e4\nd2d4`), Turn 12'de `task_complete` çağrıldı -> `acknowledged: true`.
- **Run 3:** Turn 10'da Python analiz script'i çalıştırıldı, Turn 11'de `read_file: /app/move.txt` okundu (`e2e4`), Turn 12'de `task_complete` çağrıldı -> `acknowledged: true`.

### Kök Neden (Neden Hâlâ 0.0?)
Guardrail artık agent'ın meşru doğrulama adımlarını (script çalıştırma + dosya okuma) sahte/kanıtsız tamamlama saymamaktadır. Ancak görev `chess_board.png` görselinin piksellerini çözmeyi gerektirdiği ve model metin tabanlı (Qwen3-30B) olduğu için, Python OpenCV/PIL ile yapılan kaba şablon eşleme yanlış taş pozisyonları çıkarmakta ve verifier'ın beklediği `['e2e4', 'g2g4']` mat hamleleri yerine yanlış hamleler (`g2g7`, `e2e4 d2d4`, `e2e4`) üretilmektedir. Bu, Plan dokümanında da sabitlenen **Kategori C (model yetkinlik sınırı)** durumudur.

---

## Özet Değerlendirme (Parça A)

1. **configure-git-webserver:** Gerçek regresyon değildir; modelin `openssh-server` kurma kararı ve hatalı Nginx `alias` / `user@server` SSH push doğrulama tuzağına düşmesine bağlı stokastik varyanstır. v0.5.1 değişiklikleriyle hiçbir nedensel bağı yoktur.
2. **sqlite-with-gcov:** PATH kalıcılığı notu model tarafından tam olarak kavranmış ve Run 1'de `ln -sf ... /usr/local/bin/sqlite3` ile uygulanmıştır. Başarısızlık nedeni, modelin kendi derlediği binary'nin üzerine recursive bash script yazıp 60s timeout döngüsüne girmesi (Run 1) ve `./configure` bayraklarını yanlış vermesidir (Run 2/3).
3. **chess-best-move:** v0.5'teki `completion_rejected_no_new_evidence` örüntüsü tamamen aşılmıştır (0/3 reject). Agent her 3 trial'da da kanıtlı tamamlama üreterek guardrail onayını almıştır (`acknowledged: true`). Başarısızlık saf model vizyon kapasitesi yetersizliğidir (Kategori C).
