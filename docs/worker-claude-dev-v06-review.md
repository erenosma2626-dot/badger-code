# v0.6-prep bağımsız review (madde 1 + 2)

Reviewer: worker 607bc0a8 · Hedef: `main...v0.6-prep` (HEAD `3a8a49f`) · Kod değiştirilmedi.

## Karar: **MERGE**. Engelleyici bir sorun yok. Aşağıdaki 3 not v0.6 koşusunda izlenmeli ya da küçük takip işleri olarak açılmalı.

## 1. Test suite
`starter/` içinde `uv run --frozen --with pytest python -m pytest -q` sonucu: **151/151 geçti** (1.67s).

## 2. Gerçek veriyle replay
Replay script'i scratch'te duruyor, commit'lenmedi. Script `result.json` → `agent_result.metadata.messages` içinden her tool çağrısını ve receipt'ini çıkarıyor. Sonra StructuredToolAgent'ın dedektör bloğunu satır satır taklit ederek dizinin tamamını iki ayrı `tools.py` ile oynatıyor: `main` ve `v0.6-prep`.

**Sadakat kontrolü:** `main` ile yapılan replay, hMsRghV (t10), WxmtRz6 (t15), XBjZTLx (t15), jwcNriN (t19) ve v053 build-cython run2–6 trial'larının orijinal sonlanma turunu **birebir** üretiyor. Replay'e güvenilebilir.

**Sınır:** Replay, kaydedilmiş diziyi oynatıyor. Yeni kodun kesmediği yerde model gerçekte nudge görmeyeceği için sonraki aksiyonlar farklı olurdu. Bu yüzden FP tarafındaki "kesilmez" sonucu yalnızca "kaydedilmiş ufuk boyunca kesilmez" anlamına geliyor.

| Trial | Orijinal | main replay | v0.6-prep replay |
|---|---|---|---|
| v053-r3 configure-git hMsRghV (FP, verif passed) | stuck t10 | cyc nudge t8/t9 → TERM t10 | **kesilmiyor** ✅ |
| v052-r3 regex-log WxmtRz6 (FP, passed) | stuck t15 | cyc nudge t14 → TERM t15 | **kesilmiyor** ✅ |
| v051-r2 build-cython qqhAFZm (FP, passed) | stuck t19 | *kesilmiyor* | kesilmiyor |
| v053-r1 log-summary XBjZTLx (gerçek) | stuck t15 | TERM t15 (exact) | **TERM t15 (exact)** ✅ |
| v053-r6 log-summary jwcNriN (gerçek) | stuck t19 | TERM t19 (exact) | **TERM t19** ✅ |
| v053-r4 build-cython YMfCHzk (read_file döngüsü) | stuck t22 | TERM t22 (exact) | **TERM t22** ✅ |
| v053-r2/r3/r5/r6 build-cython | stuck | TERM | aynı turlarda TERM ✅ |

- **qqhAFZm:** O dönemki FP'yi v0.5.1'in `extract_target` davranışı üretmiş. Bugünkü `main` bile bu trial'ı artık kesmiyor, yani burada v0.6'ya özel bir kazanç ölçülemez.
- **Gerçek döngüler:** Hepsi zaten `exact` ya da `target` tetiğiyle kesiliyordu, sonuç değişmedi. Yeni kodda bazı cyclic nudge'lar kayboluyor (XBjZTLx t9/t10) ama sonlanma turu aynı kalıyor.
- **YMfCHzk:** t13'teki target anahtarı `pyknotid.make` yerine `/app/pyknotid` oldu. Bunun nedeni, `extract_target`'ın artık `python -c` içindeki kodu atlaması. Davranış aynı.

**Madde 2 (length tavanı), replay'e göre:**
- **SB9PLK8:** 8 turun hepsi araçsız length kesilmesi. Yeni kod **4. turda** keser, 4 tur tasarruf.
- **pLJ7jgK:** Dizi `write, write, 7×terminal_exec, 12×length`. Yeni kod length serisinin 4. adımında, yani **13. adımda** keser, 8 tur tasarruf. Trial verif=passed çünkü regex.txt daha önce yazılmıştı. Kesme sonucu bozmaz.

## 3. Doğruluk incelemesi
**(a) Timestamp/PID ile değişen çıktılar.**
- Evidence eşitliği her lap'te bozulduğu için cyclic tetik bu durumda **hiç** çalışmıyor.
- Komutlar başarısızsa (exit≠0 ya da hata anahtar kelimesi varsa) `target_attempt_counts` birikiyor ve döngü **target-stuck** ile kesiliyor. Sentetik A/B döngüsünde (exit1, çıktı her seferinde farklı) t7'de TERM, main ile aynı.
- **Açık kalan durum:** exit 0 dönen ve çıktısı değişen bir döngü (ör. `cat a.log` / `cat b.log` ve içeride PID) artık yalnızca max_turns'te bitiyor. main bunu t6'da kesiyordu.
- Bu açık, cyclic tetik için baştan kabul edilmiş bir trade-off. Canary verisinde bu tipte bir döngüye rastlamadım.

**(b) Aynı dosyaya farklı içerik yazma döngüsü.**
- write_file'ın hash'i `content_sha256` ile değiştiği için cyclic tetik bu durumu artık yakalamıyor.
- Döngünün yine de kesilip kesilmediği test adımına bağlı:
  - Test adımının çıktısı sabitse **exact** tetiği yakalıyor (sentetik: t6 nudge, t8 TERM; main t7).
  - Test adımı başarısızsa **target-stuck** tetiği yakalıyor.
- **Kaçan tek durum:** Test adımı exit 0 dönüyor ama çıktısı her seferinde değişiyor ve yanlış (ör. `grep -c` her seferinde farklı yanlış sayı). Pratikte bunun riski düşük.

**(c) Ertelemenin sonsuza gitme riski.**
- Tool aksiyonlarında pratikte **ertelemeye ulaşılamıyor**. Cyclic bir tespit için iki lap'in evidence'ının birebir aynı olması gerekiyor, bu da son hash'in cycle_len adım önce zaten görülmüş olması demek. Dolayısıyla `should_defer` false dönüyor.
- Ertelemenin tetiklenebildiği tek yol şu: hedefi olmayan bir komut (`ls`, `pwd`), önceki turdan kalan (stale) cyclic sonucunu yeniden tetikliyor ve yeni bir çıktı üretiyor.
  - Bu durumda sonsuz erteleme teorik olarak mümkün: hedefsiz komutların her biri yeni çıktı üretmeye devam ettiği sürece erteleme de sürüyor.
  - Ancak bu komutlar hedefli history'ye eklenmediği için döngü büyümüyor ve MAX_TURNS üst sınır olarak kalıyor. Zarar yok, ama ertelemenin kendisi de neredeyse ölü kod.

## Takip notları (merge'i bloklamaz)
1. **Stale cyclic sonucu (main'de de var):** `find_cyclic_multi_target_loop` hedefsiz aksiyonlarda eski history ile tekrar tetik veriyor. Hesaplamayı yalnızca `target` varken yapmak daha doğru olur.
2. **Ertelemenin anlamı:** (c) bölümündeki nedenle ertelemenin yararı çok az. Ya kaldırılmalı ya da "yeni hash" yerine "son N adımda yeni hash var mı" gibi bir koşula dayandırılmalı.
3. **Madde 2 eşikleri:** Replay'de 4 değeri 2/2 trial'da doğru çalıştı. `has_repeated_lines` nudge'ının etkisini replay ölçemez, v0.6 koşusunda izlenmeli.
4. **Uygulayıcının şüphe notları:** Raporundaki (timestamp, write-content) iki şüphe doğrulandı. Pratikte exact/target tetikleri bu açıkları kapatıyor.
