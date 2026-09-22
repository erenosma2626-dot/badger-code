# v0.5.3 write_file append guardrail — takip incelemesi (worker-claude-dev)

Branch: `feature/v0.5.3-write-file-append` (main'e merge edilmemiş)
İncelenen commit'ler: `7a4acd0` (testler) + `054e23a` (guard implementasyonu), önceki review'a (`docs/worker-claude-dev-v053-review.md`, orta-risk bulgu #1) yanıt olarak eklendi.

Yöntem: `git show 7a4acd0` / `git show 054e23a` satır satır okundu, tüm test suite kök dizindeki `.venv` (harbor + pytest kurulu) ile gerçekten çalıştırıldı. `.env` okunmadı/raporlanmadı.

## 1. Guard sadece bilgilendirme mi, engelleme var mı?

`agent.py:798-834`. Akış: `write_file` her zaman `structured_write_file`'a gönderiliyor (append flag'i ne olursa olsun) — **hiçbir yerde çağrı engellenmiyor veya append=false'a düşürülmüyor.** `receipt.warning` sadece `append_flag and not is_initialized and receipt.exit_code == 0` olduğunda set ediliyor, yazma zaten `structured_write_file` çağrısının içinde (guard kontrolünden önce, satır 809-815) gerçekleşmiş durumda. Yani sıra: yaz → başarılıysa initialized set'ini güncelle → hâlâ uninitialized ise uyarı ekle. Önerdiğim "bilgilendirme, engelleme yok" şekliyle birebir örtüşüyor. ✅

## 2. TDD testleri senaryonun 3 halini kapsıyor mu?

`7a4acd0`'daki 4 test + `054e23a`'nın eklediği 1 entegrasyon testi (toplam 5, mockup + gerçek dosya sistemi):

- **(a) hiç yazılmamış path, append=false → sete eklenir, sonraki append=true'da uyarı yok:** `test_initialized_path_append_false_then_append_true_receives_no_warning` + `test_initialized_path_omitted_append_param_then_append_true_receives_no_warning` (default param varyantı da ayrıca test edilmiş — iyi bir ek). ✅
- **(b) sahipsiz path'e direkt append=true → uyarı var:** `test_uninitialized_path_append_true_receives_warning` — uyarı metninin tam eşleştiğini de kontrol ediyor. ✅
- **(c) aynı sahipsiz path'e 2. append=true → uyarı yok (warn-once):** `test_uninitialized_path_warns_only_once_on_repeated_append_true`. ✅
- **Ekstra (gerçek dosya sistemi, mock değil):** `test_real_environment_uninitialized_append_true_actually_writes_and_warns` — `subprocess` ile gerçek `/bin/sh` çalıştırıyor, disk üzerinde dosya içeriğinin gerçekten `existing + added1 + added2` olduğunu, 1. çağrıda uyarı olduğunu, 2. çağrıda olmadığını doğruluyor. Bu, önceki review'da eksik olduğunu belirttiğim "dosya zaten varsa ve bu path'e hiç overwrite yapılmamışken append=true gelirse" senaryosunu tam olarak kapatıyor. ✅

Testler yüzeysel değil; hem "engelleme yok, yazma gerçekleşiyor" hem "uyarı doğru tetikleniyor/tetiklenmiyor" ikisini birden doğruluyor.

## 3. `warning`/`note` alanı mevcut tool-result formatını bozuyor mu?

`structured_tools.py`: `ExecutionReceipt.to_dict()` artık `warning is not None` olduğunda dict'e ek bir `"warning"` key'i ekliyor — mevcut key'lerin hiçbiri değişmedi, sırası da korunmuş (yeni dict `d = {...}` inşa edilip sonra opsiyonel key ekleniyor). `warning=None` olduğu (yani eski davranışa denk düşen) tüm çağrılarda `to_dict()` çıktısı **byte-byte eskisiyle aynı** — geriye dönük uyumluluk sağlanmış, JSON parse'ı ya da mevcut kod yollarını bozmuyor. ✅

`note` property/setter'ı `warning`'in bir alias'ı — `to_dict()`'e dahil değil, sadece `self.warning`'i okuyup yazıyor. Kod içinde `note` hiçbir yerde kullanılmıyor (grep ile doğrulandı) — muhtemelen ileride farklı bir isimlendirme ihtiyacına karşı bırakılmış, şu an ölü kod ama zararsız; dict çıktısını etkilemiyor.

## 4. agy'nin "relative vs absolute path karışıklığında gereksiz tekrar tetikleme" notu — gerçek bir sorun mu?

**Evet, gerçek ama düşük etkili bir sorun.** Kod:

```python
is_initialized = (
    target_path in write_file_initialized_paths
    or (bool(target_path) and os.path.normpath(target_path) in write_file_initialized_paths)
)
...
write_file_initialized_paths.add(target_path)
write_file_initialized_paths.add(os.path.normpath(target_path))
```

`os.path.normpath` sadece `.`/`..`/tekrarlanan `/` gibi sözdizimsel temizlik yapıyor — **relative→absolute çözümlemesi yapmıyor** (cwd'yi hesaba katmıyor, `os.path.abspath` değil). Yani model önce `data/file.txt` ile (append=false) yazıp, sonra aynı dosyaya `/app/data/file.txt` (append=true, aynı fiziksel dosya, environment cwd `/app` ise) ile giderse, `write_file_initialized_paths`'te `"data/file.txt"` var ama `"/app/data/file.txt"` string olarak farklı olduğu için `is_initialized=False` → **gereksiz yere uyarı tekrar tetiklenir.**

Etki değerlendirmesi: bu sadece bir **advisory warning**'in yanlış pozitif üretmesi — yazma davranışını etkilemiyor, akışı bloklamıyor, sadece modele gereksiz bir "dikkat et" notu gidiyor (agy'nin kendi flagi de bunu "kritik değil, not edilsin" diye işaretlemişti). String-eşitliği + normpath kombinasyonu path normalizasyonu için yetersiz ama zarar potansiyeli sınırlı: en kötü ihtimalle model gereksiz yere ekstra bir write_file(append=false) çağrısı yapabilir (fazladan bir turn), engelleme/veri kaybı riski yok.

**Merge'ü bloklayan bir durum değil**, ama takip için not edilmeli: gerçek düzeltme `os.path.normpath(os.path.join(cwd, target_path))` gibi cwd-farkında bir çözümleme gerektirir; environment'ın cwd'sini agent.py'nin bu noktada bilip bilmediğini kontrol etmek gerekir (mevcut kodda `write_file` dispatch'inde cwd erişimi yok, `terminal_exec` tarafında `__AGENT_CWD_AFTER__` parse ediliyor — o state buraya taşınmamış).

## 5. Test suite doğrulaması

Kök `.venv` (harbor + pytest kurulu; `starter/.venv` boş, `starter/pyproject.toml`'daki `harbor>=0.13` bağımlılığı orada yok) ile çalıştırıldı:

```
cd starter && ../.venv/bin/python -m pytest -q
........................................................................ [ 51%]
...................................................................      [100%]
139 passed in 1.21s
```

139/139 iddiası **doğrulandı**, gerçek çalıştırma ile.

## 6. Merge'ü bloklayan bir şey var mı?

Yok. Önceki review'da flaglediğim orta-risk bulgu (append=true ile sahipsiz path'e sessiz yazma) düzeltildi — kod, engellemeden bilgilendirme yaklaşımını doğru uyguluyor, testler senaryonun üç halini de (dahil gerçek dosya sistemiyle) kapsıyor, `ExecutionReceipt` formatı geriye dönük uyumlu, tüm suite yeşil. Relative/absolute path normalizasyon eksikliği gerçek ama düşük-etkili bir cilalama notu — ayrı bir takip item'ı olarak `docs/plan.md`'ye eklenebilir, merge'ü geciktirmemeli.

**MERGE EDİLEBİLİR.**
