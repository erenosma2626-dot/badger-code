# StructuredToolAgent — 8 görev regresyon raporu

Tarih: 2026-09-14  
Agent: `agent.agent:StructuredToolAgent`  
Model endpoint: gerçek Nebius/Qwen3 endpoint’i (repo konfigürasyonu)  
Çalıştırma: `starter/scripts/run_baseline.sh <task> --agent-import-path agent.agent:StructuredToolAgent`

| Görev | Reward | Tur | termination_reason | verification_status | Tool-calling / gözlem |
|---|---:|---:|---|---|---|
| configure-git-webserver | 0.0 | 21 | `task_complete` | yok | Function calling çalıştı. Model nginx’i 80 portuna kurdu; istenen 8080 yerine 80 kullandığını belirterek tamamladı. Verifier: HTTP 000. |
| sqlite-with-gcov | 1.0 | 28 | `task_complete` | yok | Tool formatı geçerli. İlk `configure --coverage` hatasını farklı komutla düzeltti; görev geçti. |
| regex-log | 0.0 | 4 | `task_complete` | yok | Tool formatı geçerli. İki `write_file` çağrısından sonra görünür test yok; verifier başarısız. |
| build-cython-ext | 0.0 | 100 | `max_turns` | yok | Tool formatı geçerli, fakat tekrarlayan `read_file` incelemelerinde stuck loop; 100 tur limitine ulaştı. |
| chess-best-move | 0.0 | 21 | `task_complete` | yok | Apt lock ve `numpy` import hatası görüldü; sonrasında çıktı ve `move.txt` üretildi, verifier geçmedi. |
| fix-code-vulnerability | 0.0 | 100 | `max_turns` | yok | Tool çağrıları JSON olarak geçerliydi; art arda başarısız `read_file` çağrılarıyla stuck loop. |
| log-summary-date-ranges | 0.0 | 15 | `task_complete` | yok | İlk Python `timedelta` hatası ve eksik dosya denemeleri sonrası `summary.csv` üretildi; verifier geçmedi. |
| polyglot-c-py | sonuç yok | 16 (kısmi) | Ctrl+C / `CancelledError` | yok | 10+ dakika ilerleme olmadı; Ctrl+C ile durduruldu. Trial `result.json` tamamlanmamış, verifier/reward yok. |

## Özet

- Tamamlanan ve geçen görev: **1/7 tamamlanan** (`sqlite-with-gcov`); durdurulan `polyglot-c-py` dahil toplam sette **1/8 = %12,5** gözlenen başarı.
- Önceki BaselineAgent sonucu: **2/8 = %25**. Bu koşumda StructuredToolAgent, tamamlanmış görevler açısından 1/7; toplam gözlenen skor açısından 1/8 ile bazın altında kaldı.
- Gerçek endpoint’te function-calling şeması genel olarak takip edildi; 8 görevde parse/malformed tool-call kaynaklı bir hata gözlenmedi.
- En önemli sorunlar: görev gereksinimini yanlış yorumlayarak erken `task_complete`, doğrulama yapmadan bitirme ve iki görevde 100 turluk stuck loop. `verification_status` alanı bu koşum sonuçlarında bulunmadı.

Not: `.env` okunmadı. Kod dosyalarına ve `docs/plan.md` dosyasına dokunulmadı; bu rapor dosyası dışında proje dosyası değiştirilmedi ve commit atılmadı.
