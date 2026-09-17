# v0.5 Derin Log Analizi — regex-log, build-cython-ext, polyglot-c-py

**Kapsam:** v0.5 baseline koşusu (Terminal-Bench 2.1, n=3). Bu 3 görevin geçerli (infra-crash olmayan) her trial'ı `result.json` (`agent_result.metadata.messages`) ve `trial.log` üzerinden tur-tur incelendi. Infra-kaynaklı crash'ler (Docker compose başlatma timeout'u — `run1`'in ilk regex-log/build-cython-ext/polyglot denemeleri) ayrı sayıldı, agent'ın davranışı hiç başlamadığı için pass/fail analizine dahil edilmedi; onların yerine geçen retry trial'ları (`run1-retry`, `run3-polyglot-retry`) "geçerli" trial olarak sayıldı.

**Geçerli trial haritası (3 görev × 3 trial = 9):**
| Görev | Trial 1 | Trial 2 | Trial 3 |
|---|---|---|---|
| regex-log | run1-retry (`dgKdWmH`) | run2 (`4mGQrMH`) | run3 (`TRpQu85`) |
| build-cython-ext | run1-retry (`DcAoAey`) | run2 (`YvkKuew`) | run3 (`UtdLXD8`) |
| polyglot-c-py | run1 (`3iZ24bm`) | run2 (`UYCnpA6`) | run3-polyglot-retry (`H6TrHpC`) |

Üçü de 0/3 reward, yani 9 trial'ın 9'u da başarısız.

---

## 1. regex-log (0/3)

| Trial | termination_reason | turn | not |
|---|---|---|---|
| run1-retry | `stuck_loop_detected` | 37 | turn 34 nudge (aynı `terminal_exec` 3 kez), turn 37 nudge sonrası tekrar → terminate |
| run2 | `AgentTimeoutError` (duvar-saati 900s) | 19 (tur limiti değil, süre) | stuck-loop hiç tetiklenmedi, model regex'i sürekli değiştirmeye devam ediyordu |
| run3 | `completion_rejected_no_new_evidence` | 5 | model 2. task_complete denemesinde de yeni tool-call getirmedi → sert red |

**Kanıt — run3, turn 3-5:** Model `write_file` ile regex'i yazdı, ardından **kendi yazdığını `read_file` ile geri okuyup** (pasif doğrulama) task_complete dedi. Guardrail reddetti: `"insufficient evidence"`. Nudge sonrası model `terminal_exec` ile regex'i `cat`'ledi (yine sadece dosyayı ekrana basıyor, log verisine karşı test etmiyor) → tekrar `{"acknowledged": false, "reason": "insufficient evidence"}`, turn 5'te `"task_complete re-declared with no new tool call since the completion-evidence nudge; rejecting hard"`.
→ **Kategori B**: guardrail tam istendiği gibi çalışıyor (pasif doğrulamayı reddediyor), ama model gerçek bir düzeltme yapmak yerine aynı pasif doğrulamayı tekrarlıyor — asıl regex'i hiç örnek log satırlarına karşı `grep -P` ile TEST ETMEDİ, sadece dosya içeriğini gösterdi.

**Kanıt — run1-retry, turn 34 (`trial.log`):** `"stuck loop detected (same terminal_exec, exit code, and output 3 times), sending nudge"` — model regex'i art arda küçük varyasyonlarla değiştirip her seferinde `grep -P` ile test ediyordu (bu iyi bir davranış), ama **son date'i izole eden lookahead'i asla doğru kuramadı** — 37 turda IPv4+tarih regex'inin "sadece satırdaki SON tarihi eşleştir" kısmını çözemedi (bkz. turn 12 raw content: kendi hatasını doğru teşhis ediyor ama düzeltmesi de yanlış çıkıyor). → **Kategori C**: gerçek regex-mühendisliği yetkinlik sınırı, guardrail zaten en pahalı sürüme (100 tur) gitmesini engelledi.

**Kanıt — run2 (900s timeout, turn 19'da kesildi):** Son asistan mesajı hâlâ regex'i "basitleştiriyorum" diyerek revize ediyordu, son `terminal_exec` çıktısı yanlış eşleşme veriyordu (`2024-01-01 ... 2024-02-30 2024-03-31` — 30 Şubat gibi geçersiz bir tarihi bile eşleştirmiş). Stuck-loop hiç tetiklenmedi çünkü model her turda regex'i FARKLI şekilde değiştiriyordu (aynı komut/çıktı tekrarı yok) — ama 900 saniyelik duvar-saati sınırına çarptı. → **Kategori C** (regex yetkinlik sınırı) + hafif **A** notu: stuck-loop dedektörü "aynı komut" bazlı, "amaçsızca varyasyon üretme" (regex'i hiç yakınsamadan sürekli değiştirme) paternini yakalamıyor — 900s'lik duvar saati bunu yakalayan tek mekanizma, turn-bazlı guardrail'ler devrede değildi.

---

## 2. build-cython-ext (0/3)

| Trial | termination_reason | turn | not |
|---|---|---|---|
| run1-retry | `stuck_loop_detected` | 50 | turn 6 ilk nudge, ardından defalarca farklı dosya-okuma nudge'ları, turn 50 terminate |
| run2 | `stuck_loop_detected` | 57 | turn 6 + turn 22 ("4 unproductive attempts against target 'setup.py'") + turn 57 terminate |
| run3 | `stuck_loop_detected` | 23 | turn 8 nudge, turn 23 terminate |

**3 trial'da TAMAMEN AYNI kök neden (kanıt — her 3 trialda birebir aynı traceback):**
```
Traceback (most recent call last):
  File "/app/pyknotid/setup.py", line 1, in <module>
    from setuptools import setup, find_packages
ModuleNotFoundError: No module named 'setuptools'
```
Model bu hatayı **3 kez ard arda aynı komutla tekrar aldı** (run3'te turn 4/8/16 civarı — `apt-get`/`pip` denemeleri arasına serpiştirilmiş ama `setuptools`'u asla `pip install setuptools` veya `apt install python3-setuptools` ile doğrudan kurmadı). Nudge (`"You just ran the same command..."`) geldikten sonra model **gerçek bir düzeltme denemek yerine**, projenin tamamen alakasız kaynak dosyalarını (`geometry.py`, `knot.py`, `__init__.py`, `spacecurve.py`) döngüsel olarak `read_file` ile tekrar tekrar okumaya başladı (run3, turn 20-48: aynı 4-5 dosya defalarca okunuyor, aralarında hiç `terminal_exec` yok) — bu, "farklı bir strateji dene" nudge'ının **yanlış yorumlanması**: model literal olarak "farklı bir tool-call" yapıyor (okuma hedefini değiştiriyor) ama sorunu çözecek bir aksiyon (setuptools kurulumu) hiç denemiyor. Stuck-loop dedektörü bunu da yakaladı (`"4 unproductive attempts against target 'setup.py'"`, run2 turn 22) ve sonunda terminate etti.

→ **Kategori C (baskın), hafif B notu:** `setuptools` eksikliğini teşhis edip kurmak temel bir Python paketleme bilgisi — model bunu 3 trial'da da yapamadı; bunun yerine nudge'a "teknik olarak farklı ama anlamsız" bir tepki (rastgele dosya okuma) verdi. Guardrail (stuck-loop + "farklı hedef" nudge'ı) tasarım gereği doğru çalıştı — modelin döngüsünü kırdı ve pahalı 100-tur senaryosuna gitmesini engelledi (en pahalı trial 57 turda durdu). **Repeat pattern:** nudge sonrası "confused re-reading" — modelin nudge'a gerçek bir strateji değişikliğiyle değil, yüzeysel bir tool-hedef değişikliğiyle cevap vermesi — build-cython-ext'in 3 trial'ının hepsinde görüldü.

---

## 3. polyglot-c-py (0/3)

| Trial | termination_reason | turn | not |
|---|---|---|---|
| run1 | `stuck_loop_detected` | 31 | turn 21 "3 unproductive attempts against target '/app/polyglot/main.py.c'", turn 24 ikinci nudge, turn 31 terminate |
| run2 | `AgentTimeoutError` (900s duvar saati) | 5 (turn sayısı düşük ama süre doldu) | kök neden: `write_file` içeriği max_tokens limitine takılıp KESİLDİ |
| run3-polyglot-retry | `stuck_loop_detected` | 18 | turn 12 + turn 15 nudge, turn 18 terminate |

**Kanıt — run1 & run3-retry (tekrarlayan, aynı dosya):** Model `/app/polyglot/main.py.c` dosyasını hem geçerli C hem geçerli Python yapmaya çalışıyor; C-yorum bloğu (`/* ... */`) içine Python string/syntax'ı sıkıştırma girişimi tutarlı şekilde başarısız:
```
File "/app/polyglot/main.py.c", line 16
    * because it's inside a C comment block.
                ^
SyntaxError: unterminated string literal (detected at line 16)
```
run3-retry'de nudge sonrası model `read_file` ile dosyayı okudu, sonra **content_sha256 BİREBİR AYNI** (`f5b2d4ca48f9...`) içerikle tekrar `write_file` yaptı — yani nudge'a rağmen dosyayı hiç değiştirmeden yeniden yazdı, aynı hatayı tekrar aldı. Bu, modelin polyglot C/Python sözdizimi çakışmasını (yorum/string sınırlarının iki dilde farklı anlamı) çözemediğinin doğrudan kanıtı.

**Kanıt — run2 (asıl kök neden farklı, timeout ama nedeni max_tokens):** Son asistan mesajı `<tool_call>` etiketiyle başlayan ama bitmeyen dev bir `write_file` içeriği — sistem mesajı: `"Your last response was cut off because it was too long (it hit the max-token limit before finishing) — it did not contain a usable tool call."` Model polyglot dosyasını TEK bir dev yorum-bloğu + kod olarak yazmaya çalışıyor, çıktı token limitini aşıyor, tool-call hiç parse edilemiyor, agent daha sonraki turlarda toparlanamadan 900s'e çarpıyor.

→ **Kategori C (baskın):** C/Python polyglot sözdizimi entegrasyonu gerçek bir model yetkinlik sınırı — plan.md'nin mevcut taksonomisiyle birebir örtüşüyor ("modelin gerçek yetkinlik sınırı… düzeltmeye çalışmak göreve-özel hardcode riski taşır"). **Kategori A notu (run2'ye özgü, yeni):** modelin tek seferde çok büyük bir dosya içeriği üretme eğilimi `max_tokens=2048` ile çarpışıp tool-call'u tamamen kaybettiriyor — bu, v0.4'te `chess-best-move`/`regex-log`'da görülen `token_truncation_induced_repeat`'in bir başka örneği; write_file boyutu için parça-parça yazma zorunluluğu (zaten v0.5.1 aday listesinde "çok dosyalıysa script yaz" notu var ama bu "tek dosya çok büyük" durumunu kapsamıyor, farklı bir vaka).

---

## 4. 3 görev arasında tekrarlayan örüntüler

1. **"Nudge sonrası yüzeysel tepki" örüntüsü** (build-cython-ext'in 3/3'ünde, polyglot'un 2/3'ünde): Model nudge'a ("farklı bir şey dene") **literal olarak farklı bir tool-call** ile cevap veriyor ama alttaki sorunu çözecek bir aksiyon üretmiyor — build-cython-ext'te alakasız dosyaları okuyor, polyglot'ta aynı içeriği tekrar yazıyor. Guardrail'in "aynı komut/hedef" tespiti bunu doğru yakalıyor ama modelin nudge'ı GERÇEKTEN anlayıp anlamadığını doğrulayan bir mekanizma yok.
2. **Pasif doğrulama örüntüsü** (regex-log run3): `read_file`/`cat` ile kendi ürettiğini geri okuyup "doğruladım" demek — v0.4.1'de zaten bilinen bir vaka, doğrulama-kapısı burada da doğru çalıştı.
3. **max_tokens kesilmesi → tool-call kaybı** (regex-log run2'de değil ama polyglot run2'de) — v0.4'ün `token_truncation_induced_repeat` ailesinin devamı, hâlâ kapatılmamış.
4. Üç görevde de **gerçek `stuck_loop_detected` sayısı 6/9**, `AgentTimeoutError` (900s duvar saati) 2/9, `completion_rejected_no_new_evidence` 1/9. **`max_turns`/100-tur senaryosu SIFIR** — v0.4.1.2'nin cyclic-loop kalibrasyonu ve mevcut guardrail'ler bu 3 görevde de en pahalı hata sınıfını (100 tur) tamamen önledi; en uzun trial 57 turda durdu.

## 5. Özet tablo

| Görev | Kategori | 1 cümle |
|---|---|---|
| regex-log | **C** (baskın) + B notu | Model "satırdaki son tarihi izole et" regex mantığını kuramıyor (run1-retry, run2); guardrail pasif doğrulamayı doğru reddediyor ama model gerçek testi hiç yapmıyor (run3). |
| build-cython-ext | **C** (baskın) + B notu | Model temel `ModuleNotFoundError: setuptools` hatasını kurulumla çözemiyor, nudge sonrası alakasız dosyaları döngüsel okumaya kaçıyor; guardrail döngüyü doğru şekilde erken kesiyor. |
| polyglot-c-py | **C** (baskın) + A notu (run2) | C/Python polyglot sözdizimini birleştirme gerçek bir model yetkinlik sınırı; run2'de ayrıca tek dosyanın max_tokens limitini aşıp tool-call'un tamamen kaybolması ayrı, kodlanabilir bir bug. |

**Öneri (karar Lead'de):** (1) polyglot run2 tipi "tek write_file içeriği max_tokens'ı aşıyor" durumu için write_file'ın parçalı/append modunu teşvik eden bir prompt notu düşünülebilir — mevcut "çok-dosyalı görevlerde toplu script" notundan FARKLI bir vaka (tek büyük dosya). (2) Nudge sonrası "yüzeysel tepki" örüntüsü genel bir prompt notuyla ("nudge sonrası tool HEDEFİNİ değil, YÖNTEMİNİ değiştir") hafifletilebilir ama bunun göreve-özel hardcode'a kaymaması için dikkatli formüle edilmeli. (3) regex-log/build-cython-ext'teki kök nedenler saf model yetkinlik sınırı (C) — scaffold tarafında ek bir aksiyon önerilmiyor.
