# Worker1-AGY Badger Code v0.6 Implementasyon Raporu

**Tarih:** 2026-09-24  
**Branch:** `v0.6-prep-agy`  
**Görev Kapsamı:** Badger Code v0.6 hazırlığı kapsamındaki 3 madde (Madde 3, 4, 5).

---

## 1. Değişen ve Eklenen Dosyalar
- `starter/agent/llm.py` (değiştirildi — transient error tespiti, exponential backoff + jitter retry döngüsü)
- `starter/tests/test_llm_retry.py` (eklendi — transient/non-transient ayrımı, backoff süreleri ve mock API testleri)
- `starter/agent/prompts.py` (değiştirildi — kaynak derleme ve servis/hosts ortam kuralları)
- `starter/tests/test_prompts_v06_notes.py` (eklendi — sistem istemlerindeki yeni kuralların ve genel kalışlarının testleri)
- `docs/worker1-agy-v06-impl-report.md` (eklendi — implementasyon ve doğrulama raporu)

---

## 2. Madde Bazında Yaklaşım Özeti

- **Madde 3 (`starter/agent/llm.py` transient retry + exponential backoff):**  
  `is_transient_error` yardımcı fonksiyonu tanımlanarak `openai.APIConnectionError`, `openai.APITimeoutError`, `httpcore.RemoteProtocolError` ve 5xx `openai.APIStatusError` hataları transient kabul edildi; 4xx istemci hataları (400, 401, 404, 422) retry dışı bırakıldı. `_create_completion` sarmalayıcısı ile maksimum 3 deneme boyunca exponential backoff (2s, 4s, 8s + rastgele küçük jitter, toplam süre <30s) uygulandı; hem `chat()` hem de `chat_tools()` bu mekanizmaya bağlandı.

- **Madde 4 (`starter/agent/prompts.py` kaynaktan derlenen paket kurulumu):**  
  Görev aksi belirtilmediği sürece kaynaktan derlenen Python paketlerinin aktif ortamda çözülebilmesi için `pip install .` (veya `pip install -e .`) ile kurulması ve `build_ext --inplace` aşamasında bırakılmaması kuralı `SYSTEM_PROMPT` ve `STRUCTURED_SYSTEM_PROMPT` içine eklendi. Göreve özel hardcoding yapılmadan genel ve mevcut İngilizce istem diliyle uyumlu yazıldı.

- **Madde 5 (`starter/agent/prompts.py` ortam ipuçları: systemd & /etc/hosts):**  
  Minimal konteyner yapılarında systemd/systemctl bulunmadığında servislerin `service <name> start` veya doğrudan daemon çalıştırılarak yönetilmesi gerektiği; konteyner ağ yapısını bozmamak için `/etc/hosts` dosyasının asla üzerine yazılmayıp sadece satır eklenmesi (append) gerektiği kuralı hem `SYSTEM_PROMPT` hem de `STRUCTURED_SYSTEM_PROMPT` içine entegre edildi.

---

## 3. Test Durumu
- **TDD Akışı:** Her 3 madde için önce başarısız testler yazıldı (RED fazı doğrulandı), ardından minimum implementasyon ile testler yeşile döndürüldü (GREEN fazı doğrulandı).
- **Test Suite Sonucu:** `starter/tests/` altındaki tüm testler eksiksiz çalıştırıldı.
  - **Geçen Test Sayısı:** 150
  - **Toplam Test Sayısı:** 150
  - **Sonuç:** %100 BAŞARILI (150 passed in 0.77s)

---

## 4. Şüphelenilen / Dikkat Edilmesi Gereken Nokta
- Bazı minimal imajlarda `service` komutu dahi bulunmayabileceğinden doğrudan arka plan daemon çalıştırma alternatifi isteme eklendi; ancak PID 1 sinyal yakalaması gerektiren uç durumlarda container çıkış davranışlarına dikkat edilmelidir.

---

## 5. Commit → Madde Eşleşmesi
1. `0e86b41` — **Madde 3:** `feat(llm): retry transient endpoint errors with exponential backoff`
2. `3baf82f` — **Madde 4:** `feat(prompts): guide source-compiled Python packages to pip install into active env`
3. `18ea97c` — **Madde 5:** `feat(prompts): add environment hints for service management and /etc/hosts safety`
