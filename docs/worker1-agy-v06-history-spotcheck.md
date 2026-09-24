# Badger Code v0.6 Öncesi Geçmiş Analiz Nokta Atışı Raporu (Spot-Check)

**Tarih:** 2026-09-24  
**Yazar:** worker1-agy  
**Hedef:** Lead, Planlama Chat'i, Supervisor  
**Kapsam:** `docs/v041-log-analysis-*`, `docs/worker1-agy-v0511-*`, `docs/worker1-agy-v052-canary-deepanalysis.md`, `docs/worker1-agy-v053-canary-deepanalysis.md`, `docs/v0.5.1-canary-consolidated-report.md`, `docs/plan.md`  
**Amaç:** v0.6 89 görevlik ilk tam koşu (Faz B) öncesinde geçmiş canary ve analiz birikiminden süzülen somut dersler, kodlanmamış adaylar, altyapı riskleri ve çelişkiler.

---

## (A) Önerilmiş Ama HİÇ Kodlanmamış GENEL İyileştirme Adayları

| # | İyileştirme Adayı | Kaynak Rapor(lar) | Kanıt Gücü (Trial Sayısı) | Hâlâ Geçerli mi? | Hardcode Riski & Değerlendirme |
|---|---|---|---|---|---|
| 1 | **Araçsız `finish_reason=length` Kesilmelerine Sert Tavan (Truncation Loop Cap)** | `worker1-agy-v052-canary-deepanalysis.md` (§4.2)<br>`worker1-agy-v053-canary-deepanalysis.md` (§7.2)<br>`v0.5.3-canary-report.html` (Bulgu 3) | **Çok Yüksek**<br>(~10 trial: `regex-log` ×6, `chess-best-move` ×4; toplam 200K+ yozlaşmış token) | **EVET (En kritik)** | **Sıfır Hardcode.** Genel scaffold guardrail'i. Model 4096 token'ı araç çağırmadan doldurup kesildiğinde (`tc=NO_TC`), receipt üretilmediği için stuck-loop kör kalıyor. 2-3 ardışık kesilmede trial erken durdurulmalı. |
| 2 | **Kaynaktan Python Derlemelerinde Ortama Kurulum Kuralı (`pip install .` Prompt Notu)** | `worker1-agy-v053-canary-deepanalysis.md` (§5.B.1, §7.3)<br>`v0.5.3-canary-report.html` (Bulgu 4)<br>`plan.md` (2026-09-24) | **Orta-Yüksek**<br>(6 trial: `build-cython-ext` v0.5.2 ×1, v0.5.3 ×5 derleme başarılı ama `find_spec` fail) | **EVET** | **Düşük (Doğru formüle edilirse).** "Kaynaktan paket derlerken, aksi istenmedikçe `pip install .` veya `pip install -e .` ile aktif ortama kur" genel kuralı mühendislik standardıdır. Görev adı/paket adı verilirse hardcode olur. |
| 3 | **Döngü Dedektöründe İlerleme / Başarılı Komut İstisnası (False-Positive Guard)** | `v0.5.3-canary-report.html` (Bulgu 5)<br>`plan.md` (Terra notu §273-277 + 2026-09-24 notu) | **Düşük-Orta**<br>(1 trial şüphesi: `configure-git-webserver` v0.5.3 run3'te `nginx -t` başarılıyken 10. turda kesildi) | **EVET** | **Sıfır Hardcode.** Dedektörün "aynı hedef/komut" kararına `exit_code == 0` ve dosya değişikliği durumunu ekleyerek meşru ilerlemeyi erken kesmesini önler. |
| 4 | **Append-Guard İçin Çalışma Dizini (CWD) Farkında Yol Çözümlemesi** | `plan.md` (2026-09-22 v0.5.3 merge notu) | **Düşük**<br>(Kod analizi / potansiyel yanlış pozitif uyarısı) | **Kısmen (Düşük Öncelik)** | **Sıfır Hardcode.** `os.path.normpath` cwd bilmediğinden `data/x` ile `/app/data/x`'i farklı sayarak gereksiz advisory uyarı üretebilir. |
| 5 | **Hedef-Bazlı Nudge Metninin Araç Hatası Durumunda Revizyonu** | `v041-log-analysis-batchD-logsummary-polyglot.md` (§4.3) | **Orta**<br>(3 trial: v0.4.1 polyglot-c-py) | **Kısmen** | **Sıfır Hardcode.** Dosya okuma çöktüğünde sistemin körlemesine "dosyayı baştan sona oku" diyerek modeli aynı çöken araca yönlendirmesini engeller. |

### ⚠️ KESİNLİKLE YAPILMAMASI GEREKEN (Yarışma Kuralı İhlali / Hardcode Sayılacak) Şeyler
- `chess-best-move` için schema seviyesinde `append=true`'yu zorlamak veya dış vision/OCR API'si eklemek (Kapalı model yasağı + tek scaffold kuralı ihlali).
- `build-cython-ext` için kütüphane içi Python 3.13 uyumsuzluğunu (`fractions.gcd` → `math.gcd`) prompt'ta veya otomatik script'le yamamak (Kategori C görev-spesifik çözümdür, diskalifiye riski).
- Görevlere özel regex, port, dosya adı veya derleme bayrağı (`--gcov`, `8080`, `pyknotid`) enjekte etmek.

---

## (B) 89 Görev Ölçeğinde Altyapı ve Ortam Riskleri

89 görevlik tam koşuda (k=1) karşılaşılması neredeyse kesin olan riskler ve önerilen koruma mekanizmaları:

| Risk Sınıfı | Gözlemlenen Somut Olay | 89 Görev Ölçeğindeki Tehdit | Önerilen Önlem / Kural |
|---|---|---|---|
| **Harici Ağ & DNS Çöküşü** | `log-summary-date-ranges` v0.5.2 run3'te agent 8 turda doğru CSV üretti, verifier container'ında `releases.astral.sh` DNS hatası (`curl: (6)`) yüzünden pytest kurulamadı → haksız 0.0 alındı.<br>`configure-git-webserver` v0.5.1 run1'de model `write_file` ile `/etc/hosts`'u ezdi. | Verifier veya container kurulumlarında paket indirirken rastgele 0.0 alma ve DNS bozulması. | 1. `/etc/hosts`, `/etc/resolv.conf` dosyalarının ezilmesini engelleyen genel prompt uyarısı / guardrail.<br>2. Verifier loglarında `curl: (6)` gibi altyapı hatalarının Harbor `result.json` üzerinden tespit edilip puanlama kirliliğinin elenmesi. |
| **Eşzamanlılık (`-n`) Kaynak Kısıtı** | v0.5 baseline denemesinde `-n 4` çalıştırıldığında Terminal-Bench 2.1 resource limits ve Docker Desktop sınırları çarpıştı, `CancelledError` patladı. | Çoklu görev paralelleştirildiğinde konteynerlerin sessizce düşmesi veya çökmesi. | **Kesin Kural:** Koşularda **`-n 1`** kullanılmalı; paralelleştirme Harbor seviyesinde değil gerekirse dış süreçlerle izole edilmeli. |
| **API Soket Kopması & Gecikme (`APIConnectionError`)** | Nebius üzerinde 12-13 dakikalık endpoint donmaları (v0.3, v0.5.3 run1/4/5). Model 4096 token'ı dolduran yozlaşmış çıktı ürettiğinde soket 600-870 saniyede kopuyor (`httpcore.RemoteProtocolError`). | Birkaç görevde API kopmasıyla tüm koşunun kesintiye uğraması veya trial'ın puansız kalması. | 1. LLM istemcisine retry / exponential backoff eklenmesi.<br>2. (A.1) maddesindeki truncation cap ile modelin dakikalarca soketi kitlemesinin önlenmesi. |
| **900s Duvar-Saati Zaman Aşımı (`AgentTimeoutError`)** | Tek bir komutun 60s timeout'a girmesi (fork-bomb/recursive wrapper) veya modelin art arda 70-80s süren boş token monologları üretmesi süreyi tüketiyor (v0.5.1, v0.5.2, v0.5.3). | Puan alınabilecek görevlerin zaman aşımı tavanına çarparak düşmesi ve yüksek token cezası. | Komut seviyesinde 60s zaman aşımı korunmalı; model seviyesinde ardışık kesilme tavanı uygulanmalı. |
| **Relative Path `.env` Hatası** | `harbor run --env-file` göreceli verildiğinde alt dizinlerde `.env` bulunamadı (`Env file not found`). | Koşunun başlamadan çökmesi. | Her zaman mutlak path: `--env-file /Users/.../badger-code/.env`. |
| **QEMU / Sanallaştırma Sınırı** | 89 görevden 2'si (`qemu-alpine-ssh`, `qemu-startup`) Mac Docker Desktop nested virtualization desteklemediği için çalışmıyor ("Unimplemented syscall number 282"). | Mac üzerinde bu 2 görev istisnasız 0.0 alacaktır. | Sağlık kontrolünde bilinmeli; final skor hedefi için x86 Linux cloud VM değerlendirilmeli. |

---

## (C) v0.5.3 Bulgularıyla Çelişen / Eskimiş Eski Öneriler

Son 6 run ve 24 trial derin analizi sonucunda geçerliliğini yitiren varsayımlar:

1. **"Token limitini artırmak (8192 / 16384) büyük dosya kesilmelerini çözer" hipotezi ÇÖKTÜ:**
   - *Eski Görüş:* Modelin dosyaları sığdıramadığı, tavan yükseltilirse tamamlayacağı düşünülüyordu.
   - *v0.5.3 Gerçeği:* 16384'te bile polyglot 54K karakter üretip kesildi. Token artışı, modelin araç çağırmadan 40-60KB "kendi kendine mırıldanma" döngülerine girmesine ve 900s timeout / soket kopmasına yol açıyor. 4096 limiti bütçe ve leaderboard cezası (`-0.01 × total_tokens/1M`) için doğru ve zorunlu bir kalkandır.
2. **"`write_file(append=True)` ve recovery prompt'u modellerin dosyayı parçalamasını sağlar" tezi ÇÖKTÜ:**
   - *Eski Görüş:* Modele "dosya kesildi, `append=true` ile parçala" denirse dosyayı böleceği varsayıldı.
   - *v0.5.3 Gerçeği:* Hedef görev olan `chess-best-move`'da model enjekte edilen uyarılara rağmen monolitik OpenCV script'ini baştan üretmekte ısrar etti (Run 5). 24 trial'da hedeflenen görevlerde `append=true` **0 kez** kullanıldı. Açık kaynak 30B sınıfı modeller bu yönlendirmeyi içselleştirememektedir; zorlamak hardcode riskine girer.
3. **"`log-summary-date-ranges` append düzeltmesiyle geçti" sanrısı YANLIŞTIR:**
   - *v0.5.3 Gerçeği:* 3/6 PASS alan bu görevde tek bir trial bile `append=true` kullanmamıştır. Başarının gerçek nedeni v0.5.1'de eklenen **Kural 10 (Toplu Script Yazma Notu)** ve v0.5.2'deki verifier DNS hatasının bu turda tekrarlanmamasıdır.
4. **"Stuck-loop dedektörleri çok agresiftir, gevşetilmelidir" argümanı ÇÖKTÜ:**
   - *Eski Görüş:* Terra'nın adım 4'teki "aynı komut tekrarı meşru retry'ları kesebilir" eleştirisi.
   - *v0.5.3 Gerçeği:* `fix-code-vulnerability` ve `regex-log`'da `CYCLIC_LOOP_WINDOW=44` ve `write_file` parmak izi koruması olmasaydı her trial 100 tur ve 5M+ token harcayarak tüm bütçeyi ($36) tek bir koşuda bitirecekti. Dedektörler bütçenin hayatta kalmasını sağlayan en kritik mekanizmadır.
5. **"`build-cython-ext` için pip setuptools/cython notu tek başına yeterlidir" varsayımı EKSİKTİR:**
   - *v0.5.3 Gerçeği:* `python3 -m pip install` ile derleme exit 0 ile geçiyor; ancak paket global kurulmadığı için (`pip install .` eksikliği) ve Python 3.13 kütüphane içi `fractions.gcd` kaldırıldığı için görev yine 0.0 kalmaktadır.

---

## 🎯 Lead ve Planlama İçin Özet Sonuç (Faz B Öncesi)

1. **v0.5.4 gerekli mi?** Faz B'ye (89 görevlik sağlık koşusu) geçmeden önce sadece 2 genel ve ucuz mühendislik kuralı değerlendirilebilir:
   - **(A.1) Truncation Loop Cap:** Araçsız gelen 2 ardışık `finish_reason=length` durumunda trial'ı kesmek (89 görevde milyonlarca token ve onlarca timeout'u önler).
   - **(A.2) `pip install .` Prompt Notu:** Kaynaktan derlenen Python paketleri için global kurulum hatırlatması.
2. `configure-git-webserver`'daki döngü dedektörü şüphesi (v0.5.3 run3) doğrulanırsa ilerleme/exit-0 kontrolü eklenebilir.
3. Bunlar dışında yeni mekanizma aranmamalı, bütçe ($36) doğrudan Faz B ve Faz C koşularına saklanmalıdır.
