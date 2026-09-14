# v0.3 hazırlığı — worker-claude-dev raporu

**Branch:** `cao/5a30ca70` (worktree, main'e merge edilmedi, push edildi)
**Durum:** Madde 1-5 kodlandı ve commit'lendi, TDD ile doğrulandı (32/32 test geçti). Madde 6 (canlı 8-görev regresyon koşusu) kullanıcı talimatıyla **yapılmadı** — bkz. aşağıdaki not.

## Değişen dosyalar
- `starter/agent/prompts.py` — SYSTEM_PROMPT revizyonu + yeni STRUCTURED_SYSTEM_PROMPT/STRUCTURED_NUDGE_MESSAGE
- `starter/agent/agent.py` — BOOTSTRAP_COMMAND genişletildi + yeni `StructuredToolAgent` sınıfı eklendi
- `starter/agent/tools.py` — `CODE_BLOCK_RE` sıkılaştırıldı
- `starter/agent/llm.py` — `LLMClient.chat_tools()` eklendi (native function-calling)
- `starter/agent/structured_tools.py` — yeni dosya: `terminal_exec`/`write_file`/`read_file`/`task_complete` + `ExecutionReceipt`
- `starter/tests/test_prompts_network_policy.py`, `test_agent_bootstrap_command.py`, `test_prompts_binary_file_guidance.py`, `test_tools_parser_free_text.py`, `test_structured_tools.py`, `test_llm_chat_tools.py`, `test_structured_agent_loop.py` — yeni testler (13 test)

## Madde bazında özet

**1. Prompt fix (commit `f06a4c4`)** — "there is no network, do NOT apt-get install" mutlak yasağı kaldırıldı; yerine önce `/etc/os-release` + `command -v apt-get apk` kontrolü, uygun paket yöneticisiyle kurulum, network yoksa alternatif arama, "ortam bozuk" deyip bırakmama kuralı geldi. Test: geçti (3/3).

**2. Ortam-keşfi (commit `5f15066`)** — `BOOTSTRAP_COMMAND`'a `cat /etc/os-release | grep PRETTY_NAME` ve `command -v apt-get apk git python3` eklendi. Test: geçti (2/2).

**3. Vision/binary genel kural (commit `9214ab1`)** — SYSTEM_PROMPT'a görev-bağımsız bir STRATEGY adımı eklendi: ikili/medya dosyalarında shell aracına (identify/hexdump) güvenmeden Python stdlib/PIL/struct kullan. RULES.md §4 gereği hiçbir görev adı geçmiyor. Test: geçti (2/2, ayrıca "görev adı geçmiyor" testi de var).

**4. Parser bug fix (commit `0425e84`)** — Kök neden: `CODE_BLOCK_RE` etiketsiz (```` ``` ````) kod bloklarını da bash komutu sanıyordu. Model dosya içeriğini göstermek için etiketsiz bir blok kullanıp asıl komutu ondan sonra ```bash içine koyduğunda, PARSER YANLIŞLIKLA İLK (etiketsiz) bloğu çalıştırıyordu — regex-log/sqlite-with-gcov'daki "But: command not found" / "TASK_COMPLETE: command not found" hatalarının kök nedeni tam olarak bu. Artık sadece açıkça `bash`/`sh`/`shell` etiketli bloklar çalıştırılıyor. Regresyon testiyle önce hatayı yeniden ürettim (kırmızı test), sonra düzelttim (yeşil). Test: geçti (3/3), mevcut 20 eski test de bozulmadı.

**5. Terra'nın mimarisi (commit `3b26dce`, en büyük madde)** — `docs/plan.md`'nin ikinci mermaid diyagramındaki hedefe uygun: native tool-calling (OpenAI/Nebius `tools=` şeması) ile 4 ayrı yapısal araç — `terminal_exec`, `write_file`, `read_file`, `task_complete` — ve her çağrı için deterministik `ExecutionReceipt` (exit_code, timed_out, cwd_after, stdout_tail/stderr_tail, changed_paths, output_ref). `task_complete` artık serbest metin değil, API'nin kendisinin ayırt ettiği ayrı bir araç — bu, "TASK_COMPLETE'in kod bloğuna gömülmesi" bug sınıfını yapısal olarak imkansız kılıyor.
   - **Mimari karar:** Mevcut `BaselineAgent`'ın yerine geçmek yerine, onun **yanına** paralel yeni bir sınıf (`agent.agent:StructuredToolAgent`, isim `mlm26-structured-tools`) olarak eklendi — çünkü function-calling desteği olmayan endpoint'lerde (bazı Ollama/llama.cpp kurulumları) çalışmaz, mevcut regex-tabanlı ajan onlar için hâlâ gerekli. Nebius'un OpenAI-uyumlu endpoint'i function-calling destekliyor (llm.py docstring'i zaten bunu not ediyordu).
   - Test: gerçek bir LLM/container olmadan, sahte (fake) OpenAI client + sahte environment ile tool-calling döngüsünün uçtan uca (nudge → terminal_exec → task_complete) doğru çalıştığı doğrulandı (7+4+1 test, hepsi geçti).
   - **Şüpheli/emin olamadığım nokta:** `terminal_exec`'in `changed_paths` alanı `find . -newer <marker>` ile tek round-trip'te best-effort hesaplanıyor — çalışma dizini dışındaki değişiklikleri veya çok hızlı ardışık I/O'yu kaçırabilir (dosyada belgeledim). Ayrıca `StructuredToolAgent` **gerçek bir Nebius/Qwen3 endpoint'ine karşı hiç koşulmadı** (bkz. aşağıdaki not) — sahte LLM ile mekanik olarak doğru olduğunu biliyorum ama gerçek modelin tool-calling'i ne kadar güvenilir çağırdığını (özellikle Qwen3-30B-A3B'nin bu formatı ne kadar iyi takip ettiğini) bilmiyorum. İlk gerçek koşuda dikkatle izlenmeli.

**6. Doğrulama (regresyon koşusu) — YAPILMADI, kullanıcı talimatıyla durduruldu.** Kodlama bitince `regex-log` görevini gerçek Nebius/Qwen3 endpoint'ine karşı smoke-test olarak başlattım (madde 6'nın parçası); kullanıcı test yapmamamı ve sadece raporlamamı söyleyince koşuyu durdurdum. Koşu, durdurulana kadar (turn 2-4) hatasız ilerliyordu — özellikle parser'ın "But this is still..." gibi serbest-metin açıklamalarını artık komut olarak çalıştırmadığını (madde 4'ün doğrudan kanıtı) gördüm, ama görev tamamlanmadı/skorlanmadı. **8 görevlik tam regresyon seti (configure-git-webserver, sqlite-with-gcov, regex-log, build-cython-ext, chess-best-move, fix-code-vulnerability, log-summary-date-ranges, polyglot-c-py) hiç koşulmadı — önceki 2/8 baz skoruyla karşılaştırma yapılamadı.** Bunu koşturmak istersen `starter/scripts/run_baseline.sh <görev-adı>` veya tüm set için tek tek `-i` bayraklarıyla harbor komutu gerekir; `StructuredToolAgent`'ı denemek için `--agent agent.agent:StructuredToolAgent` kullanılmalı.

## Test durumu
`starter/` içinde `pytest tests/ -q` → **32/32 geçti** (13 yeni + 19 eski, hiçbiri bozulmadı).

## Notlar
- `.env`/`secrets.json`/`*.pem` hiçbir yerde okunmadı veya rapora yazılmadı.
- Her madde ayrı commit: `f06a4c4`(1), `5f15066`(2), `9214ab1`(3), `0425e84`(4), `3b26dce`(5).
- Branch push edildi, main'e merge edilmedi — review bekliyor.
