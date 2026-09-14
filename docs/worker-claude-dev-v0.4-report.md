# v0.4 worker raporu — spec §5 madde 1-6 uygulaması

**Worktree/branch:** `cao/9b066522`
**Kapsam:** `docs/v0.4-spec.md` §5'teki 7 adımın 1-6'sı (7. adım — 8 görevlik canary koşusu — kullanıcının kendi makinesinde koşturacağı, bu görevin dışında).
**Disiplin:** her adım TDD ile (önce başarısız test, sonra minimum kod), ayrı commit, `uv run pytest` her adımdan sonra tam yeşil.

## Commit'ler (sırayla)

| # | Commit | Spec maddesi | Özet |
|---|---|---|---|
| 1 | `4cb89d9` | §2.4 | Teşhis: tool-call parser uyuşmazlığı — gözlemlenebilirlik eklendi (fix değil) |
| 2 | `2ffadb2` | §1.1 madde 3 | `structured_tools.write_file`'ın python3/base64 fallback zinciri doğrulandı (kod değişikliği gerekmedi) |
| 3 | `738db6e` | §1.1 madde 1 | `verification_status` StructuredToolAgent'a taşındı |
| 4 | `114f316` | §1.1 madde 2 + §2.3 | Stuck-loop fingerprint StructuredToolAgent'a taşındı + "aynı hedefe N. verimsiz deneme" genişletmesi (her iki agent) |
| 5 | `978ee07` | §2.1 | Doğrulama kapısı sıkılaştırıldı — nudge sonrası kabul için yeni tool-call/receipt şart (her iki agent) |
| 6 | `40d379b` | §2.2 | Bootstrap'a tam recursive dosya listesi + cd-kalıcı-değil genel kuralı |

**Test durumu:** `uv run pytest` (starter/) — 61/61 yeşil, her commit sonrası doğrulandı.

## Değişen dosyalar

- `starter/agent/agent.py` — her iki agent'a guardrail taşımaları/genişletmeleri
- `starter/agent/llm.py` — `chat_tools()` artık `finish_reason` döndürüyor
- `starter/agent/tools.py` — `extract_target()`, `is_unproductive_attempt()` yeni yardımcılar
- `starter/agent/prompts.py` — `TARGET_STUCK_LOOP_MESSAGE`, `STRUCTURED_COMPLETION_EVIDENCE_MESSAGE`, cd-kalıcı-değil kuralı (her iki sistem promptu)
- `starter/tests/*` — 6 yeni test dosyası + 3 mevcut dosyada güncelleme (bkz. aşağıda "davranış değişikliği" notu)
- `docs/v0.4-diagnosis-toolcall.md` — yeni, §2.4 teşhis raporu
- `docs/worker-claude-dev-v0.4-report.md` — bu dosya

## Madde madde yaklaşım ve bulgular

### 1. §2.4 — tool-call parser teşhisi
Kod incelemesi (`structured_tools.TOOL_SCHEMAS`, `llm.chat_tools()`, `StructuredToolAgent`'ın tool_call ayrıştırması) hem şema formatında hem ayrıştırma mantığında hata bulmadı — ikisi de OpenAI/Nebius `tools=` sözleşmesiyle birebir uyumlu. Asıl boşluk gözlemlenebilirlikti: `tool_calls` boş geldiğinde modelin ham `text`'i hiçbir yere loglanmıyordu. Eklenen: `finish_reason` (llm.py) + StructuredToolAgent'ta ham içeriğin tam loglanması. **En olası kök neden hipotezi** (doğrulanmamış, gerçek trial verisi gerektirir): `write_file`'ın büyük `content` argümanı `LLM_MAX_TOKENS`'i (varsayılan 2048) aşıp tool-call bloğunu yarıda kesiyor, sunucu tarafı parser kapanmamış bloğu ayrıştıramayıp boş `tool_calls` + ham metne düşüyor. Detay: `docs/v0.4-diagnosis-toolcall.md`.

### 2. §1.1 madde 3 — write_file fallback
`structured_tools.write_file` zaten `tools.run_write_file` ile birebir aynı `command -v python3` / `command -v base64` probe zincirine sahipti — kod değişikliği gerekmedi. Bunu hem canned-command-string testiyle hem de GERÇEK bir minimal ortam simülasyonuyla (kısıtlı `PATH` ile gerçek `/bin/sh` çalıştırma, python3 gizli) doğruladım — ikinci test tarzı, gelecekte bu zincir sessizce bozulursa (örn. bir refactor sırasında) yakalayacak.

### 3. §1.1 madde 1 — verification_status
StructuredToolAgent'a BaselineAgent'ınkiyle aynı 4-durumlu (`not_applicable`/`missing`/`passed`/`stale`) mantık taşındı, ama sınıflandırma receipt akışından türetildi: `write_file` = tek edit tool'u, herhangi bir `exit_code=0` `terminal_exec` = doğrulama sinyali (BaselineAgent'ın shell-komut sınıflandırıcısına eşdeğer ayrım burada yok, tool'lar zaten ayrık).

### 4. §1.1 madde 2 + §2.3 — stuck-loop genişletmesi
İki ayrı tetikleyici, ikisi de mevcut "bir kez nudge, tekrarında sert sonlandır" disiplinini paylaşıyor:
- **Birebir tekrar** (mevcut mantık, artık StructuredToolAgent'ta da var — daha önce HİÇ yoktu, bu §1.1'in release-blocker maddesiydi).
- **Aynı hedef, N verimsiz deneme** (yeni, §2.3): `extract_target()` ile en-sondaki path-benzeri token çıkarılıyor, `is_unproductive_attempt()` ile exit_code≠0 veya "not found"/"no such file" gibi sinyaller sayılıyor. Komut metni her turda değişse bile (farklı grep pattern'i, hep aynı dosyaya karşı) 3. denemede tetikleniyor.

### 5. §2.1 — doğrulama kapısı sıkılaştırması
Eski davranış: nudge'dan sonraki HERHANGİ bir TASK_COMPLETE/task_complete, arada gerçek bir işlem olsun olmasın kabul ediliyordu. Yeni davranış: nudge sonrası en az bir gerçek tool-call (shell/write_file/terminal_exec/read_file, sonucu ne olursa olsun) şart; yoksa 2. reddetme SERT — üçüncü bir nudge değil, doğrudan `completion_rejected_no_new_evidence` ile sonlandırma. **Önemli:** bu, `tests/test_agent_completion_evidence_gate.py`'deki 3 mevcut testin BEKLENEN davranışını kasıtlı olarak değiştirdi (spec'in kendisi bu değişikliği istiyor) — eski "2. deneme her zaman kabul edilir" testleri "arada gerçek eylem yoksa sert reddedilir" olarak güncellendi, "arada gerçek eylem varsa kabul edilir" için yeni bir test eklendi.

### 6. §2.2 — oryantasyon
`BOOTSTRAP_COMMAND`'a `find /app -type f | head -200` eklendi (iki agent da bunu paylaşıyor). Her iki sistem promptuna genel (göreve özel olmayan) "cd kalıcı değil, zincirle ya da mutlak yol kullan" kuralı eklendi.

## Şüpheli/dikkat edilmesi gereken noktalar

- **§2.4'ün kök nedeni doğrulanmadı** — sadece hipotez. Bir sonraki canary koşusunda `finish_reason=length` loglanırsa doğrulanmış olur; o durumda gerçek fix (madde 7'nin SONRASI, bu görevin kapsamı dışında) `LLM_MAX_TOKENS` artırmak ya da büyük `write_file` içerikleri için parçalı yazma protokolü olabilir.
- **§2.1'in "sert reddetme" semantiği bir yorumdur** — spec metni ("2. reddetmede mevcut soft-block sonlandırma kuralı geçerli olsun") tam olarak "kabul et" mi yoksa "sonlandır" mı demek istediği konusunda iki okumaya açıktı. Ben "sonlandır, kabul etme" olarak yorumladım çünkü (a) "sert" kelimesi kabul değil ret anlamına geliyor, (b) "sonsuz döngü riski yok" ifadesi ancak sonlandırma ile tutarlı (kabul etmek zaten sonsuz döngü riski taşımıyordu). Lead review'inde bu yorumun onaylanması gerekir.
- **`extract_target`/`is_unproductive_attempt` best-effort heuristikler** — tam bir shell parser değil, spec de zaten "best-effort" diyor. Yanlış pozitif/negatif riski BaselineAgent'ın mevcut `classify_command` heuristiğiyle aynı sınıfta.
- `.env`/secrets dosyalarına dokunulmadı, okunmadı.

## Sonraki adım
Spec §5 madde 7 (8 görevlik canary set, n≥3, StructuredToolAgent ile) kullanıcının kendi makinesinde çalıştırılacak — bu görev kapsamında başlatılmadı.

Branch push edildi, main'e merge edilmedi — Lead review bekleniyor.
