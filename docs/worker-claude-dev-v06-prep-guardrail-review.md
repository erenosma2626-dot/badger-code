# v0.6 öncesi guardrail incelemesi (salt-okuma)

Tarih: 2026-09-24 · Worker: claude-dev · Kod değişikliği / commit yok (bu dosya hariç).
Kaynak: `starter/agent/agent.py` (cyclic dedektör ~L920-990, truncation handling ~L690), `starter/agent/tools.py::find_cyclic_multi_target_loop` (L571), `jobs/v05*-canary-run*/`.

## Görev 1 — hMsRghV: hipotez DOĞRU (yanlış-pozitif kesme)

Transkript (10 tur): apt install → sshd_config → git user → bare repo → nginx site yaz → `ln && nginx -t && systemctl restart` (exit 1: config syntax hatası) → config'i düzelt (yeni sha) → aynı komut (exit 1, ama **`nginx -t` artık başarılı**; tek hata "System has not been booted with systemd") → **tur 8 nudge** → config'i yeniden yaz (aynı sha, gereksiz) → **tur 9 nudge** → `ln && nginx -t` **exit 0, test successful** → **tur 10 terminate**.

Kesinleştiren mekanizma kusurları:
1. **Rotasyon = farklı key.** Döngü key'i `"__cyclic__:" + ",".join(cycle)`; `[A,B]` ve `[B,A]` aynı döngü ama farklı key. Tur 8'de `[sites-available, sites-enabled/]`, tur 9'da `[sites-enabled/, sites-available]` → aynı döngü için 2 nudge; tur 10'da history yine `..A,B,A,B` → ilk key zaten nudge'lanmış → **terminate**.
2. **Verimlilik bakılmıyor.** `find_cyclic_multi_target_loop` sadece target dizisine bakıyor; exit code / output hash / content_sha256 değişimi hiç hesaba katılmıyor. Edit→test iterasyonu (A=dosya yaz, B=test et) tanım gereği 2-döngü → 2 lap (4 aksiyon) sonra nudge.
3. **Başarılı aksiyonda da terminate.** Tur 10 exit 0 idi; terminate kararı son aksiyonun sonucundan bağımsız.
4. Yardımcı: `extract_target` `ln -sf X Y/` için hedefi `Y/` dizinine indiriyor → aynı mantıksal iş iki "target" gibi görünüyor.

Modelin gerçek hatası `systemctl` (container'da yok) idi — dedektör onu değil, ilerleyen config işini kesti.

### Diğer stuck_loop_detected trial'ları (v0.5.1–v0.5.3, 33 trial, hepsi reward 0)
Son turlarda ilerleme/başarılı exit görülen, cyclic key ile kesilenler:
- **v051-run2/build-cython-ext__qqhAFZm** — net FP: `[setup.py, test_pyknotid.py]` 2-döngü; her test farklı hata (eksik modül → eksik `vispy`), son aksiyon `pip install vispy` exit 0 → tur 19 kesildi.
- **v052-run3/regex-log__WxmtRz6** — net FP: `[regex.txt, test_log.txt]` edit→test; son 4 aksiyonun 3'ü exit 0, tur 15 kesildi.
- **v053-run6/chess-best-move__C8N6ABn** — olası FP: eksik sistem kütüphanelerini sırayla çözüyor (libGL kuruldu → yeni hata libgthread); tur 17 kesildi. (Model de dağılıyordu, sınırda.)
- v053-run2/regex-log__JzTsDY6 ve v053-run1/log-summary__XBjZTLx: rotasyon-çift-nudge var (`[regex.txt,'10.0.0.1']`→`['10.0.0.1',regex.txt]`) ama sonrasında **gerçek** exact-repeat var → kesme makul. Not: `'10.0.0.1'` target olarak çıkarılmış — `extract_target` python -c string içindeki IP'yi target sanıyor.
- build-cython-ext / fix-code-vulnerability'deki uzun (5+ dosya) read döngüleri ve read_file exact-repeat kesmeleri: gerçek stuck, FP değil.

Özet: 3 net/olası FP; üçü de **kısa (2-3) döngü + edit/test deseni**.

## Görev 2 — AwD7YWz timeout nedeni

İlk `apt-get install` 900 s'lik bütçeden büyük bir dilimi yedi (ilk komut timed_out, sonra dpkg lock, kill, `timeout 30` ile exit 124 — paket kurulumu 3 kez tekrarlandı). Tur 24'e kadar model makul ilerliyordu (sshd çalışıyor, bare repo hazır, nginx kurulu). Tur 25–31'in **yedisi de** `finish_reason=length`: model nginx site dosyasını yazarken `fastcgi_param ...` satırlarını dejeneratif şekilde tekrar ederek 4096 token'lık `LLM_MAX_TOKENS`'ı dolduruyor; her tur ~4K token üretip hiçbir aksiyon yapmıyor. Agent'ın truncation nudge'ı "append ile parçala" diyor — bu dejeneratif tekrar için yanlış çare (dosya ~20 satırlık olmalı); truncation serisini kesecek/strateji değiştirecek bir üst sınır yok, bu yüzden 900 s duvarına çarptı.

## Öneriler (genel, göreve-özel değil)

1. **Cyclic key'i rotasyon-bağımsız yap** (canonical rotation, ör. döngünün sözlük sırasına göre en küçük rotasyonu ya da `frozenset`).
   Kanıt: hMsRghV, JzTsDY6, XBjZTLx, v051-run3 cython'da aynı döngü için ardışık 2 nudge. Risk: düşük (tek nudge'a iniyor, terminate bir tur daha geç). Etki: hMsRghV'de terminate en az 1-2 tur ertelenirdi; tek başına kurtarmaz ama #2 ile birlikte kurtarır.
2. **Cyclic dedektörü "ilerleme" varsa susturmak**: iki lap'ta (aksiyon, exit_code, output_hash / content_sha256) tuple dizisi aynı değilse döngü sayma — ya da en az bir exit_code 0→değişim/yeni output hash varsa. Mevcut exact-repeat fingerprint'i zaten var, yeniden kullanılabilir.
   Kanıt: 3 FP (hMsRghV, qqhAFZm, WxmtRz6) hepsinde lap'lar arası output farklı. Risk: orta — gerçek döngüde output zaman damgası vb. yüzünden değişirse kaçırır; ama exact-repeat ve target_is_stuck hâlâ yakalar. Etki: 6 canary'de ~3 trial'ı kesilmekten kurtarır (kazanç garanti değil; çoğu zaten zor görevler).
3. **Son aksiyon başarılıyken terminate etme** (nudge'a izin ver, ama `exit_code==0` ve yeni output ise terminate'i bir sonraki tetiklemeye ertele). Kanıt: hMsRghV tur 10 exit 0 ile kesildi, qqhAFZm son aksiyon exit 0. Risk: düşük; max_turns/wall-clock zaten üst sınır. Etki: FP'lerin kalan kısmını kapatır.
4. **Truncation serisi için dejenerasyon savunması**: `finish_reason=length` art arda ≥2 ve raw content'te aynı satır N kez tekrar ediyorsa "append ile parçala" yerine "çıktın tekrar döngüsüne girdi; dosyayı minimal yaz" nudge'ı + ≥4 ardışık length'te stuck_loop gibi terminate (wall-clock'u yakmadan). Ayrıca 2. truncation'da o tur için daha düşük temperature / repetition penalty (backend destekliyorsa) düşünülebilir.
   Kanıt: AwD7YWz tur 25-31, 7 ardışık length. Risk: düşük-orta (gerçekten büyük dosya yazan görevlerde append yolu korunmalı → tekrar-oranı koşulu şart). Etki: timeout yerine erken, bilgilendirici sonuç; 89 görevde uzun config/kod üreten görevlerde wall-clock kazancı.
5. **Uzun süren paket kurulumunu arka plana/timeout'a yönlendir + `systemctl` yok ipucu**: ortam snapshot'ına "init sistemi: systemd yok → `service`/doğrudan binary kullan" satırı ekle (snapshot'ta `command -v systemctl` sonucu — genel, göreve özel değil).
   Kanıt: hMsRghV ve AwD7YWz ikisinde de systemctl hatası; AwD7YWz'de apt timeout + dpkg lock zinciri ~birkaç yüz saniye. Risk: çok düşük (sadece bilgi). Etki: servis-kuran görevlerde birkaç tur tasarruf.

Önerilen öncelik: 1+2+3 birlikte (tek küçük PR, mevcut `test_*cyclic*` testlerine FP regresyon testi: edit→test 2-döngüsü farklı çıktılarla nudge'lanmamalı), sonra 4.
