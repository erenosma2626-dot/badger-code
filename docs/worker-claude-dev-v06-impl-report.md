# v0.6-prep uygulama raporu (worker claude-dev)

Branch: `v0.6-prep` (main'e dokunulmadı, push/merge yok). Kapsam, Lead'in değişikliğinden sonra **yalnızca madde 1 + madde 2**.

## Test durumu
- Başlangıç: 139/139 geçiyordu (`uv run --frozen --with pytest python -m pytest -q`, `starter/` içinden).
- Son durum: **151/151 geçiyor** (+12 yeni test; beklenen davranış değişikliği yüzünden 1 mevcut test güncellendi).
- Her madde için önce testler yazıldı ve fail ettikleri görüldü, sonra kod yazıldı.

## Değişen dosyalar
- `starter/agent/tools.py`: `canonical_cycle`, `should_defer_cyclic_terminate` eklendi; `find_cyclic_multi_target_loop(..., evidence=)` eklendi; `extract_target` artık `-c "..."` içini ve IP'leri atlıyor.
- `starter/agent/agent.py`: her iki agent'ta (Baseline + Structured) kanıt geçmişi, canonical anahtar ve erteleme var; Structured'da length tavanı var; `has_repeated_lines` ve `LENGTH_TRUNCATION_TERMINATE_AT=4` eklendi.
- `starter/agent/prompts.py`: `REPETITIVE_TRUNCATION_MESSAGE` eklendi.
- Testler: `test_tools_cyclic_target_loop.py`, `test_structured_agent_cyclic_loop.py`, `test_structured_agent_truncated_response.py`.

## Madde 1: ilerlemeyi hesaba katan cyclic dedektör
- **(a)** Tetik anahtarı artık döngünün sözlük sırasında en küçük rotasyonu. Böylece nudge'dan sonra `b,c,d,a` rotasyonu yeni bir nudge almıyor, doğrudan terminate ediyor. Davranış değişikliği: 10 hedefli testte terminate turn 30 yerine **21**'de oluyor; test buna göre güncellendi.
- **(b)** Her hedef için `(tool, exit_code, output_hash)` tutuluyor; `write_file`'da hash'e content_sha giriyor. İki lap'ın kanıtı birbirinden farklıysa bu döngü sayılmıyor. Bu yüzden hMsRghV tipi edit→test ilerlemesi (yeni içerik + yeni çıktı) artık kesilmiyor.
- **(c)** Nudge'dan sonra cyclic tetik tekrar gelirse ve son aksiyon exit 0 ile daha önce hiç görülmemiş bir çıktı ürettiyse terminate erteleniyor. Exact-repeat ve target-stuck bu ertelemeden etkilenmiyor.
- Exact-repeat ve target-stuck tespitlerinin aynen çalışmaya devam ettiği ayrı testlerle kanıtlandı.
- **Yan bulgu:** `extract_target` artık `python -c "..."` içindeki kodu ve IP biçimli token'ları hedef saymıyor.

## Madde 2: araçsız ardışık length tavanı (StructuredToolAgent)
- `consecutive_length_count`, hedef ne olursa olsun araçsız `finish_reason=length` turlarını sayıyor. Bir tool çağrısı ya da length dışı bir yanıt gelince sıfırlanıyor.
- ≥2 ardışık kesilmede, ham metinde bir satır ≥3 kez tekrar ediyorsa, mevcut append önerisine ek olarak "kısa/minimal yaz, tekrar eden satır üretme" nudge'ı ekleniyor.
- ≥4 ardışık kesilmede erken terminate: `termination_reason="consecutive_length_truncation"`.

## Kapsam değişikliği / revert
- Madde 3 (llm.py retry), Lead'in mesajı gelmeden önce commit'lenmişti (`be8f885` test, `8151c9e` feat).
- Bunlar `d5ed200` ile revert edildi. Ağaç, madde 2 commit'i `3205117` ile birebir aynı.
- Madde 4 ve 5'e ve versiyon string'lerine hiç dokunulmadı.

## Commit → madde
| Commit | Madde |
|---|---|
| b01bd58 | 1 test |
| 2b65b22 | 1 feat |
| 76094da | 2 test |
| 3205117 | 2 feat |
| be8f885, 8151c9e | 3 (revert edildi) |
| d5ed200 | 3 revert |

## Emin olmadığım noktalar
- Kanıt karşılaştırması tam eşitlik arıyor. Çıktısında timestamp/PID olan komutlar her lap'ta farklı hash üretir, bu yüzden gerçek bir döngü cyclic tetikten kaçabilir. Bu durumda yakalanması exact-repeat ve target-stuck'a kalıyor.
- Structured test fake'inde `write_file` receipt'inin content_sha'sı sabit geliyor gibi görünüyor. Eski "write_file döngüsü" testi bu yüzden hâlâ geçiyor. Gerçek ortamda aynı yola farklı içerik yazılırsa bu artık döngü sayılmaz; bu bilinçli bir tercih.
- Referans verilen `docs/worker-claude-dev-v06-prep-guardrail-review.md` bu worktree'de yoktu. hMsRghV fikstürü görev tanımına göre sentetik olarak kuruldu, gerçek trial verisi kullanılmadı.
- Tavan eşikleri (2/4, satır tekrarı ≥3) sezgisel seçildi, trial verisiyle kalibre edilmedi.
