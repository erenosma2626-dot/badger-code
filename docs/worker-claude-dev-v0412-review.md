# v0.4.1.2 Kod İncelemesi (worker1-agy implementasyonu)

İnceleyen: Claude (dev/review worker), 2026-09-16
Worktree: `.cao/worktrees/9f523ff4`, branch `feature/v0.4.1.2-fixes`
Commit'ler: `91b60fb` (CYCLIC_LOOP_WINDOW 8→44), `d2d4f25` (prompts.py regex-sayma kuralı), `ddf0800` (docs)

## Sonuç: MERGE'E UYGUN

## Nesnel bulgular

1. **CYCLIC_LOOP_WINDOW 8→44**: `starter/agent/agent.py` doğrulandı,
   default artık 44. `AGENT_CYCLIC_LOOP_WINDOW` env-var override'ı hâlâ
   çalışıyor — `AGENT_CYCLIC_LOOP_WINDOW=8` ile test edildi, doğru şekilde
   8'i alıyor.
2. **`find_cyclic_multi_target_loop`** (`tools.py`): `max_window` parametresi
   default 44'e güncellenmiş, docstring ve mantık (cycle_len 2..max_window//2)
   tutarlı.
3. **Testler yüzeysel değil**: `test_ten_targets_cyclic_loop_triggers_stuck_loop_with_window_44`
   gerçekten 10 farklı hedef × 3 lap = 30 turn'lük bir senaryo simüle ediyor,
   `max_turns=35` ile çalıştırılıp turn 30'da `stuck_loop_detected` bekliyor.
   `test_find_cyclic_multi_target_loop_honors_explicit_max_window` da hem
   window=8 (None döner, tespit edilemez) hem window=44 (tespit edilir)
   durumlarını ayrı ayrı doğruluyor — bu iyi bir regresyon-karşıtı kontrol.
4. **prompts.py regex-sayma kuralı**: Diff'te iki ayrı hunk var — biri
   `SYSTEM_PROMPT` (satır ~44, BaselineAgent), diğeri
   `STRUCTURED_SYSTEM_PROMPT` (satır ~184, StructuredToolAgent) içinde.
   İkisine de eklenmiş, metin birebir aynı ve göreve özel değil (genel
   "regex ile sayma kısıtı ifade etmek istersen..." talimatı) — yarışma
   kuralına (hardcode yasak) uyumlu.
5. **`pytest starter/tests/ -q`**: `.venv/bin/pytest` ile çalıştırıldı
   (sistem python3'te pytest yoktu, doğru venv bulundu) → **109 passed**,
   worker'ın iddiası doğrulandı.

## Öznel değerlendirme

- **Performans yükü iddiası**: `cyclic_target_history` listesi
  `agent.py`'de trim edilmiyor (append-only), bu yüzden teorik olarak
  MAX_TURNS (=100) kadar büyüyebilir — ama pratikte önemsiz: liste en
  fazla ~100 kısa string tutar, `find_cyclic_multi_target_loop` zaten
  sadece son `CYCLIC_LOOP_WINDOW` (44) elemanına bakıyor
  (`history[-max_window:]` tarzı bir pencereleme mantığı var). Yani
  algoritmik maliyet O(window²) sabit kalıyor, window 8→44 olması O(44²)
  vs O(8²) — turn başına birkaç mikrosaniyelik fark, ölçülebilir bir
  performans yükü değil. Worker'ın iddiası doğru.
- Bellek şişirme riski yok — 100 elemanlık string listesi ihmal edilebilir.
- Kod kalitesi: docstring güncellemeleri tutarlı, değişiklik minimal ve
  odaklı (scope creep yok).

## Şüpheli / dikkat edilmesi gereken nokta

- Yok. Diff küçük, testler gerçek senaryoyu simüle ediyor, env-var
  override korunmuş, prompt metni göreve özel değil. Merge önerilir.
