# BaselineAgent 8 Görevlik Regresyon Seti Raporu

**Tarih:** 2026-09-14  
**Agent:** `agent.agent:BaselineAgent` (commit `ae7f312` — v0.3 prep)  
**Model:** `Qwen/Qwen3-30B-A3B-Instruct-2507` (Nebius TokenFactory)  
**Koşum Tipi:** Sıralı tekil koşum (`-n 1`), 8 görev

---

## 1. Sonuç Özeti

| Görev | Reward | Tur | Termination Reason | Verification Status | Önceki Baz Durum |
|---|:---:|:---:|---|---|:---:|
| `configure-git-webserver` | 0.0 | 100 | `max_turns` | `missing` | 1.0 (GEÇMİŞTİ) |
| `sqlite-with-gcov` | 0.0 | 81 | `stuck_loop_detected` | `not_applicable` | 1.0 (GEÇMİŞTİ) |
| `regex-log` | 0.0 | 12 | `task_complete` | `missing` | 0.0 |
| `build-cython-ext` | 0.0 | 17 | `stuck_loop_detected` | `not_applicable` | 0.0 |
| `chess-best-move` | 0.0 | 20 | `stuck/timeout` (`AgentTimeoutError` @ 900s) | `not_applicable` | 0.0 |
| `fix-code-vulnerability` | 0.0 | 33 | `stuck/timeout` (pytest askıda kaldı @ 13dk) | `not_applicable` | 0.0 |
| `log-summary-date-ranges` | 0.0 | 20 | `task_complete` | `stale` | 0.0 |
| `polyglot-c-py` | 0.0 | 15 | `task_complete` (`AddTestsDirError` verifier) | `missing` | 0.0 |

**Genel Başarı:** **0/8 (%0)**  
**Önceki Baz Skor ile Kıyas:** Önceki baz skor **2/8 (%25)** idi (`configure-git-webserver` ve `sqlite-with-gcov` geçmişti). Yeni koşuda bu iki görev de başarısız olarak **0/8 (%0)** sonucuna geriledi.

---

## 2. Görev Bazlı Detaylar ve Bulgular

1. **`configure-git-webserver` (0.0, 100 tur, max_turns):**
   - Agent chroot ve SSH yapılandırması sırasında `git-shell` bağımlılıklarını kopyalamaya çalışırken sonsuz konfigürasyon döngüsüne girdi (`ld-linux`, paylaşımlı kütüphaneler, `/etc/passwd`). 100 tur sınırına çarptı.

2. **`sqlite-with-gcov` (0.0, 81 tur, stuck_loop_detected):**
   - Agent SQLite derleme sürecinde `./jimsh0 configure` komutunu parametreleriyle defalarca tekrarladı. Stuck-loop guardrail'i turn 64'te nudge gönderdi, turn 81'de tekrar üzerine erken sonlandırdı.

3. **`regex-log` (0.0, 12 tur, task_complete):**
   - Agent regex kuralını üretti, dosyayı yazdı ve doğrulama yapmadan (missing verification) `TASK_COMPLETE` bildirdi. Çözüm verifier testlerini geçemedi.

4. **`build-cython-ext` (0.0, 17 tur, stuck_loop_detected):**
   - Turn 10'da stuck-loop tespitiyle uyarıldı; `cd pyknotid` ve `python3 setup.py build_ext --inplace` döngüsünden çıkamayarak turn 17'de durduruldu (eski 100 turluk israfı önleyen guardrail devrede).

5. **`chess-best-move` (0.0, 20 tur, stuck/timeout):**
   - Model LLM chat isteği / analiz sırasında 900 saniyelik Harbor agent timeout sınırına takıldı (`AgentTimeoutError`).

6. **`fix-code-vulnerability` (0.0, 33 tur, stuck/timeout):**
   - Turn 32'de `bottle.py` dosyasını `cat > /app/bottle.py << 'EOF'` ile tam olmayan bir şablonla güncelledi, turn 33'te `pytest -rA` çalıştırıldığında test askıda kaldı ve 13+ dakika sonra harbor sonlandı.

7. **`log-summary-date-ranges` (0.0, 20 tur, task_complete):**
   - Tarih aralıklarını hesaplamak için Python scripti yazdı (`count_logs.py`), `summary.csv` üretti. Doğrulama durumu `stale` (son düzenleme sonrası tam bağımsız test yok), çıktı verifier kriterini karşılamadı.

8. **`polyglot-c-py` (0.0, 15 tur, task_complete / AddTestsDirError):**
   - C ve Python uyumlu Fibonacci polyglot dosyası yazdı (`/app/polyglot/main.py.c`). Agent `TASK_COMPLETE` dedi; ancak verifier aşamasında container durduğu için `AddTestsDirError` alındı.

---

## 3. İlgili İş Klasörleri (starter/jobs/)

- `configure-git-webserver`: `starter/jobs/2026-09-14__19-02-02`
- `sqlite-with-gcov`: `starter/jobs/2026-09-14__19-09-18`
- `regex-log`: `starter/jobs/2026-09-14__19-17-16`
- `build-cython-ext`: `starter/jobs/2026-09-14__19-22-24`
- `chess-best-move`: `starter/jobs/2026-09-14__19-25-08`
- `fix-code-vulnerability`: `starter/jobs/2026-09-14__19-42-41`
- `log-summary-date-ranges`: `starter/jobs/2026-09-14__20-06-36`
- `polyglot-c-py`: `starter/jobs/2026-09-14__20-18-58`
