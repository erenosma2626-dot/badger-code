# v0.5.1 (worker1-agy) — `LLM_MAX_TOKENS` 8192→4096 Review

**Branch:** `feature/v0.5.1-max-tokens-4096` (main'e henüz merge edilmedi, eski base `abe49e8` üzerinde — main artık `feature/v0.5.1-prompt-notes` merge edilmiş halde, branch bunu içermiyor)
**Commit'ler:** `e671448` (TDD red), `160afa9` (fix), `7144896` (rapor)
**Diff kaynağı:** `git diff main...feature/v0.5.1-max-tokens-4096` üç-nokta (merge-base'e göre) okundu — bu, branch'in eski base'inden kaynaklanan gürültüyü (prompts.py/test dosyalarının "geri alınmış" görünmesi, aslında sadece main'de daha yeni olması) doğru şekilde eledi. Gerçek/izole diff sadece `starter/agent/llm.py` ve `starter/tests/test_llm_max_tokens_default.py`'de.

## 1. Diff özeti
- `llm.py`: docstring + `LLMClient.__init__`'teki fallback `os.environ.get("LLM_MAX_TOKENS", "8192")` → `"4096"`.
- Test dosyası: default-değer testi ve override testi (şimdi 8192 ile override ediliyor) buna göre güncellenmiş. Docstring'deki eski gerekçe metni ("v0.4.1 madde 2: ... finish_reason=length ... chess-best-move/2RrorEW, regex-log/FZorHju") **tamamen silinmiş**, yerine sade "cost optimization" notu konmuş.

## 2. Test doğrulaması
İzole diff (sadece `llm.py` + testi) mevcut main tepesine uygulanıp tam suite koşuldu:
```
.venv/bin/python -m pytest starter/tests -q
114 passed in 0.65s
```
**114/114 doğrulandı** (agy'nin raporundaki "109/109" iddiası da doğru ama eski/stale base'e göre — o zaman prompt-notes'un 5 yeni testi main'de yoktu; sayı farkı branch'in main'in gerisinde kalmasından, bir hatadan değil).

## 3. ASIL SORU — Parça 1 bulgusuyla çelişki var mı?

**Evet, doğrudan ve somut bir çelişki var — bu hipotetik değil, KANITLANMIŞ bir gerileme riski.**

Kanıt zinciri:
1. v0.4.1'de (`db18bbf`) `LLM_MAX_TOKENS` **zaten bir kez** 2048'den 8192'ye çıkarılmıştı, açık gerekçeyle: `chess-best-move`/`regex-log` trial'larında model çıktısı `finish_reason=length` ile ortasından kesiliyor, bu da agent'ın aynı kesilmiş içeriği tekrar tekrar üretmeye çalıştığı bir döngüye yol açıyordu.
2. Parça 1'in derin log analizinde (`docs/worker-claude-dev-v05-deeplog-regexlog-cython-polyglot.md`), v0.5 baseline'da — yani **8192 zaten aktifken** — `polyglot-c-py` run2'de AYNI hata sınıfı tekrar gözlemlendi: model tek bir `write_file` içeriğini 8192 token sınırına rağmen bitiremedi, tool-call parse edilemedi, agent 900s duvar-saatine çarpana kadar toparlanamadı.
3. Yani **8192'nin kendisi bile bu hata sınıfını tamamen kapatmamış durumda** — hâlâ en az 1/9 trialda (polyglot run2) yetersiz kaldığına dair taze, doğrudan kanıt var. `LLM_MAX_TOKENS`'ı 4096'ya (yarısına) düşürmek, bu zaten-marjinal-yetersiz sınırı DAHA DA küçültür — agy'nin kendi "şüpheli nokta" notu bunu doğru teşhis ediyor ("4096, 8192'ye göre bu truncation'a çarpma ihtimalini artırır") ama bunun karşılığında hiçbir telafi edici önlem (ör. write_file'ı parçalı yazma zorunluluğu, ya da 4096'nın yeterli olacağına dair ölçülmüş veri) diff'te yok.

**Sonuç: Bu bir "belki gelecekte sorun çıkarır" endişesi değil — v0.5 baseline'ın kendi verisinde zaten görülmüş, dokümante edilmiş bir hata modunu daha sık tetikleyecek yönde bir değişiklik.** Maliyet optimizasyonu meşru bir hedef ama gerekçe olarak sunulan diff'te ne bir $ tasarrufu tahmini, ne de "4096 neden yeterli" analizi var — sadece "cost optimization" ibaresi var.

## 4. Öneri

**(c) Şimdi merge etme — ama düz "canary'de gözle" de değil, aşağıdaki koşullu sıra önerilir:**

1. **Şu an merge EDİLMEMELİ.** Elimizde 8192'nin bile bir trial'ı kurtaramadığına dair somut kanıt varken, sınırı yarıya indirmek — ek bir telafi mekanizması olmadan — bilinen bir hata sınıfının frekansını artırma riskini kabul etmek anlamına gelir. Bu, "maliyet optimizasyonu" kazancının büyüklüğü ölçülmeden alınacak asimetrik bir bahis.
2. **(b) Ara değer (6144) de tek başına yeterli bir çözüm değil** — sorunun kökü "tek write_file çağrısının boyutu" değil, modelin bazen (polyglot gibi görevlerde) tek seferde çok büyük/karmaşık bir dosyayı tek parçada üretmeye çalışması. 4096 vs 6144 vs 8192 arasındaki fark muhtemelen bu spesifik başarısızlık modunu sadece biraz geciktirir, ortadan kaldırmaz.
3. **Önerilen gerçek sıra:** Önce Parça 1'de önerilen "tek büyük dosya için write_file'ı parçalı/incremental yazma" prompt notu (v0.5.1 aday listesindeki mevcut "çok-dosyalı toplu script" notundan FARKLI, henüz kodlanmamış bir öneri) değerlendirilsin/kodlansın. Bu telafi mekanizması varken, `LLM_MAX_TOKENS` düşürme denemesi (4096 veya 6144) ayrı bir v0.5.2 canary'de, polyglot-c-py ve build-cython-ext gibi büyük-dosya-üreten görevlere ÖZEL DİKKATLE izlenerek test edilsin. Mekanizma yokken sınırı düşürmek, maliyet kazanır ama zaten kırılgan bir hata sınıfını daha da kırılgan hale getirir.
4. Eğer Lead maliyet baskısı nedeniyle yine de düşürmek isterse: en azından **8192'yi koruyup** sadece `LLM_MAX_TOKENS` env var'ı ile ayrı bir düşük-maliyetli koşu deneyip karşılaştırmalı ölçüm alınması, kod tabanındaki DEFAULT'u sabit olarak değiştirmekten daha güvenli bir yol olur (default'u değiştirmek yeni her koşu/PR için sessizce bu riski taşır).

**Kısa cevap:** Evet, çelişiyor — ve bu, kodlanmamış bir hipotez değil, aynı v0.5 verisinde zaten gözlenmiş bir gerilemenin daha sık tetiklenmesi riski. Karar Lead'de ama teknik tavsiyem: bu haliyle merge ETME.
