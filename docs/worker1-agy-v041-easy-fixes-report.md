# Worker1-AGY: v0.4.1 İyileştirmeleri ve Düzeltmeler Raporu

**Tarih:** 16 Eylül 2026  
**Branch:** `cao/0bfb59a8`  
**Kapsam:** Badger Code v0.4.1 için 3 bağımsız, izole hata düzeltmesi (Madde 1, Madde 2, Madde 3)

---

## 1. Değişen ve Eklenen Dosyalar

- **Kaynak Kodları:**
  - `starter/agent/tools.py`: `is_unproductive_attempt()` fonksiyonuna `command` desteği ve arama/okuma komutu filtresi eklendi.
  - `starter/agent/agent.py`: `BaselineAgent` ve `StructuredToolAgent` çağrı noktalarında `command` parametresi iletildi.
  - `starter/agent/structured_tools.py`: `read_file()` içindeki varlık denetimi, platform bağımsız stdin pipe'ı ve hata yakalama güçlendirildi.
  - `starter/agent/prompts.py`: `SYSTEM_PROMPT` ve `STRUCTURED_SYSTEM_PROMPT` metinlerine sıralama (`set` yerine `list`/`sort`) ve derleme çıktısı temizliği kuralları eklendi.
- **Test Dosyaları:**
  - `starter/tests/test_tools_target_extraction.py`: Madde 1 senaryoları (a, b, c, d) için TDD testleri eklendi.
  - `starter/tests/test_structured_tools.py`: Madde 2 için var olmayan dosya, minimal shell fallback, boş dosya ve regresyon testleri eklendi.
  - `starter/tests/test_prompts_general_rules.py` *(Yeni)*: Madde 3 prompt kurallarının varlığını ve genel niteliğini doğrulayan testler eklendi.

---

## 2. Madde Bazında Yaklaşım Özetleri

### Madde 1: `is_unproductive_attempt()` Yanlış Pozitif Düzeltmesi
- **Yaklaşım:** `is_unproductive_attempt()` fonksiyonuna opsiyonel `command: str | None = None` parametresi eklendi. `exit_code == 0` durumunda `_UNPRODUCTIVE_KEYWORDS` kontrolü yalnızca komut bir inceleme/arama komutu olduğunda (`grep`, `find`, `which`, `locate`, `ls`, `cat`, `head`, `tail` vb.) veya `command is None` iken (geriye dönük uyumluluk için) çalıştırılır; `./configure`, `make`, `gcc`, `python3` gibi derleme/çalıştırma komutlarında `exit_code == 0` doğrudan üretken (`False`) kabul edilir. `agent.py` üzerindeki her iki çağrı noktası da güncellendi (`read_file` için `command=None` korunarak dosya yolu karmaşası önlendi).

### Madde 2: `read_file()` Bozuk Hata ve `Incorrect padding` Düzeltmesi
- **Yaklaşım:** Kök neden olarak shell tarafında `base64 "$__rf_path" | tr -d '\n'` boru hattının son komut (`tr`) nedeniyle her zaman exit 0 dönmesi ve Harbor'ın stderr'i stdout'a yönlendirmesi sonucu metin hata mesajının base64 decode'a girip `binascii.Error: Incorrect padding` fırlatması tespit edildi. Çözüm olarak hem python3 hem de base64 fallback dallarına dosya varlığı (`[ ! -e ]` / `p.exists()`) ve dizin kontrolü (`[ -d ]` / `p.is_dir()`) eklenerek erken `exit 1` sağlandı; ayrıca platformlar arası uyum için `base64 < "$__rf_path"` stdin yönlendirmesi kullanıldı ve Python decode bloğunda olası hata mesajları yakalanarak her zaman `exit_code != 0` ile temiz `'No such file: <path>'` döndürülmesi garanti altına alındı.

### Madde 3: Sistem Promptlarına Genel Kurallar
- **Yaklaşım:** `prompts.py` içindeki hem `SYSTEM_PROMPT` hem de `STRUCTURED_SYSTEM_PROMPT` bölümlerine iki genel kural eklendi: (a) çıktıda sıra kritikse `set` yerine `list` veya açıkça sort kullanılması, (b) görev tamamlanmadan önce derleme sırasında üretilen geçici veya ikili (.o vb.) dosyaların temizlenmesi. Eklenen kuralların görev-spesifik olmadığı ve dosyanın hatasız import edildiği bir test ile doğrulandı.

---

## 3. Commit Eşleştirmesi

1. **`803df05`** — `fix(tools): restrict exit 0 unproductive keywords check to inspection commands` (Madde 1)
2. **`ca7b98f`** — `fix(structured_tools): ensure read_file reports clear error on nonexistent paths` (Madde 2)
3. **`356c470`** — `feat(prompts): add general rules for output ordering and build artifact cleanup` (Madde 3)

---

## 4. Test Durumu ve Pytest Çıktısı

Her madde için önce başarısız testler yazıldı (TDD Red), ardından minimum kod yazılarak testlerin geçmesi sağlandı (Green). Tüm test paketi başarıyla tamamlandı:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/erenosma/Downloads/badger-code/.cao/worktrees/0bfb59a8
collected 75 items

starter/tests/test_agent_bootstrap_command.py ...                        [  4%]
starter/tests/test_agent_completion_evidence_gate.py ....                [  9%]
starter/tests/test_agent_stuck_loop.py ...                               [ 13%]
starter/tests/test_llm_chat_tools.py .....                               [ 20%]
starter/tests/test_prompts_binary_file_guidance.py ..                    [ 22%]
starter/tests/test_prompts_cwd_not_persistent.py ..                      [ 25%]
starter/tests/test_prompts_general_rules.py ....                         [ 30%]
starter/tests/test_prompts_network_policy.py ...                         [ 34%]
starter/tests/test_structured_agent_completion_evidence_gate.py ...      [ 38%]
starter/tests/test_structured_agent_loop.py ..                           [ 41%]
starter/tests/test_structured_agent_stuck_loop.py ....                   [ 46%]
starter/tests/test_structured_agent_verification_status.py .....         [ 53%]
starter/tests/test_structured_tools.py ................                  [ 74%]
starter/tests/test_tools_parser_free_text.py ...                         [ 78%]
starter/tests/test_tools_target_extraction.py ...........                [ 93%]
starter/tests/test_tools_write_file.py .....                             [100%]

============================== 75 passed in 0.47s ==============================
```

---

## 5. Şüpheli / Dikkat Edilmesi Gereken Noktalar

- `is_unproductive_attempt()` içinde `command` parametresinin birden fazla shell komutu içeren zincirlerde (`cd dir && grep ...`) doğru filtrelenmesi için zincir ayrıştırma desteği eklendi; ancak çok karmaşık subshell yapılarında (`(sh -c '...')`) ilk token analizi yerine subshell gövdesine bakılması gerekebilir (mevcut benchmark görevlerindeki kalıplar için mevcut mantık fazlasıyla yeterli ve güvenlidir).
