# Kök Neden Analizi: Harbor Task Container'larında `git` / `apk` "command not found" (Exit 127)

**Tarih:** 2026-09-14  
**Yazar:** worker1-agy  
**Branch:** `feat/git-apk-analysis`  
**Amaç:** 2026-09-13 ile 2026-09-14 koşumları arasında `configure-git-webserver` ve diğer görevlerde ortaya çıkan `command not found` (exit 127) hatalarının kök nedenini belirlemek.

---

## 1. Yönetici Özeti (Executive Summary)

Sorun **Harbor altyapısında, Docker daemon'ında veya imaj önbelleğinde (cache) meydana gelen bir bozulma DEĞİLDİR.**

İki temel yanlış varsayım tespit edilmiştir:
1. **Container'ların Alpine Linux olduğu varsayımı yanlıştır:** Terminal-Bench sample setindeki 10 görevin 10'u da Debian veya Ubuntu tabanlıdır (`configure-git-webserver` bir **Ubuntu 24.04.3 LTS** container'ıdır). Container'larda paket yöneticisi `apt`/`apt-get`'tir. `apk` hiçbir zaman var olmamıştır ve `apk add` çağrısı kaçınılmaz olarak `exit 127: apk: command not found` vermiştir.
2. **`git`'in önceden kurulu olduğu ve 14 Eylül'de kaybolduğu varsayımı yanlıştır:** `configure-git-webserver`'ın resmi Docker imajında (`ghcr.io/laude-institute/terminal-bench/configure-git-webserver:2.0`) `git` hiçbir zaman ön-kurulu değildi. 13 Eylül'deki başarılı koşumda ajan 2. turda `apt-get update && apt-get install -y git python3` çalıştırarak paketi internetten indirmiştir (container'ın outbound internet erişimi açıktır).
3. **Gerçek Kök Neden (Regresyon Kaynağı):** 13 Eylül gecesi `d2e7f1b` (v0.2.0) commit'i ile `starter/agent/prompts.py` dosyasına eklenen mutlak kurallardır:
   - *"Everything runs locally inside this container. There is no network, no remote server... Do not try to push, pull, or access the internet."*
   - *"If a required tool or package is missing, do NOT attempt to install it over the network (apt-get, pip install, curl a download)..."*
   Bu prompt kısıtlaması nedeniyle 14 Eylül'de ajan, `/usr/bin/apt-get`'i görmesine rağmen paket kurmaktan kaçınmış, kendisini hayali bir şekilde Alpine'de sanarak `apk` denemiş, o da bulunamayınca "ortam bozuk" diyerek görevi eksik terk etmiştir.

---

## 2. Somut Kanıtlar ve İnceleme

### A. Docker İmajları ve İşletim Sistemi Kanıtı
Repo ve Harbor önbelleğinde (`~/.cache/harbor/tasks/`) yer alan tüm task tanımları ve Docker imajları canlı olarak sorgulanmıştır:

| Görev Adı | Docker İmajı | Dağıtım (OS) | Paket Yöneticisi | `git` Var mı? |
|---|---|---|---|---|
| `configure-git-webserver` | `.../configure-git-webserver:2.0` | **Ubuntu 24.04.3 LTS** | `/usr/bin/apt-get` | ❌ **YOK** |
| `regex-log` | `.../regex-log:2.0` | **Ubuntu 24.04.3 LTS** | `/usr/bin/apt-get` | ❌ **YOK** |
| `sqlite-with-gcov` | `.../sqlite-with-gcov:2.0` | **Ubuntu 24.04.3 LTS** | `/usr/bin/apt-get` | ❌ **YOK** |
| `chess-best-move` | `.../chess-best-move:2.0` | **Ubuntu 24.04.3 LTS** | `/usr/bin/apt-get` | ❌ **YOK** |
| `polyglot-c-py` | `.../polyglot-c-py:2.0` | **Ubuntu 24.04.3 LTS** | `/usr/bin/apt-get` | ❌ **YOK** |
| `log-summary-date-ranges` | `.../log-summary-date-ranges:2.0` | **Debian 12 (bookworm)** | `/usr/bin/apt-get` | ❌ **YOK** |
| `build-cython-ext` | `.../build-cython-ext:2.0` | **Debian 12 (bookworm)** | `/usr/bin/apt-get` | ✅ **VAR** |
| `fix-code-vulnerability` | `.../fix-code-vulnerability:2.0` | **Debian 13 (trixie)** | `/usr/bin/apt-get` | ✅ **VAR** |
| `qemu-alpine-ssh` | `.../qemu-alpine-ssh:2.0` | **Debian 11 (bullseye)** | `/usr/bin/apt-get` | ❌ **YOK** |
| `qemu-startup` | `.../qemu-startup:2.0` | **Debian 11 (bullseye)** | `/usr/bin/apt-get` | ❌ **YOK** |

**Doğrulama Komutu Çıktısı (`configure-git-webserver:2.0`):**
```bash
docker run --rm ghcr.io/laude-institute/terminal-bench/configure-git-webserver:2.0 sh -c "cat /etc/os-release | grep PRETTY_NAME; which apk apt apt-get git 2>&1"
# Çıktı:
# PRETTY_NAME="Ubuntu 24.04.3 LTS"
# /usr/bin/apt
# /usr/bin/apt-get
# (git ve apk çıktısı BOŞ)
```

Görevin orijinal `Dockerfile`'ı (`~/.cache/harbor/tasks/XvSZ8ep75ygfvFmonK4WcK/configure-git-webserver/environment/Dockerfile`):
```dockerfile
FROM ubuntu:24.04
WORKDIR /app
RUN apt update -y && apt install -y curl
```
İmajda `git` bilerek kurulmamıştır; görevin amacı ajanın bir git sunucusu yapılandırmasıdır.

---

### B. 13 Eylül ve 14 Eylül Koşumlarının Karşılaştırmalı Transkript Kanıtı

#### 13 Eylül Koşumu (`starter/jobs/2026-09-13__18-35-50/configure-git-webserver__izbiWHm`):
- **Turn 1:** Ajan `git init --bare` çalıştırdı.
  - Sonuç: `exit code: 127, stdout: bash: line 4: git: command not found`
- **Turn 2:** Ajan hatayı doğru yorumladı ve şu komutu çalıştırdı:
  ```bash
  apt-get update
  apt-get install -y git python3
  ```
  - Sonuç: `exit code: 0`
  - Container'ın dış ağ erişimi çalıştı (`Get:1 http://security.ubuntu.com/ubuntu noble-security... [126 kB]`).
  - `git` ve `python3` başarıyla kuruldu.

#### 14 Eylül Koşumu (`starter/jobs/2026-09-14__11-09-51/configure-git-webserver__3inUy4u`):
- `d2e7f1b` commit'i ile gelen v0.2.0 prompt'u ajanın hafızasına şu kuralları kazıdı:
  1. *"Everything runs locally inside this container. There is no network, no remote server, no GitHub. Do not try to push, pull, or access the internet."*
  2. *"If a required tool or package is missing, do NOT attempt to install it over the network (apt-get, pip install, curl a download)..."*
- **Turn 1 (Msg 6):** Ajan `write_file` kullanarak `/app/Dockerfile` yazdı ve içine `FROM alpine:latest` ile `RUN apk add --no-cache git` koydu (tamamen modelin kendi kafasından uydurduğu bir senaryo).
- **Turn 8 (Msg 28-29):** Ajan `/app/git-server-config.sh` çalıştırdı:
  - Sonuç: `exit code: 127: git: command not found`
- **Turn 9 (Msg 30-31):** Kendi yazdığı hayali Dockerfile nedeniyle ortamı Alpine sanan model:
  ```bash
  apk add --no-cache git
  ```
  çalıştırdı.
  - Sonuç: `exit code: 127: apk: command not found`
- **Turn 10 (Msg 32-33):** Ajan neyin kurulu olduğunu görmek için `ls /usr/bin/` çalıştırdı.
  - Çıktıda `/usr/bin/apt` ve `/usr/bin/apt-get` **açıkça listelendi.**
- **Turn 11 (Msg 34-36):** Ajan `apt-get`'i görmesine rağmen sistem promptundaki **"do NOT attempt to install over the network (apt-get...)"** yasağı nedeniyle `apt-get` çalıştırmadı ve düşünce zincirinde (thought) şunu ifade etti:
  > *"git is not available in the system, and there's no package manager (apk) to install it... we cannot install git, and the environment is fundamentally incomplete for the task... the only way forward is to assume that git is available in the real environment... TASK_COMPLETE"*
- Görev hiç yapılandırılmadan terk edildi ve 0.0 aldı.

---

### C. Diğer Görevlerdeki "Command Not Found" (Exit 127) İncelemesi

Supervisor notlarında geçen *"14 Eylül'de 6/8 görevde git/apk command not found verdi"* tespiti ayrıntılı olarak filtrelenmiş ve incelenmiştir. Gerçekte:
- **`git` ve `apk` sadece `configure-git-webserver`'da denenmiştir.** Diğer 7 görevde `git` veya `apk` aranmamıştır.
- Diğer görevlerdeki exit 127 hatalarının nedenleri tamamen farklıdır:
  1. **`chess-best-move`:** Ajan satranç tahtası görselini (`chess_board.png`) okumak için `identify`, `file` ve `hexdump` çalıştırmıştır. Minimal Ubuntu container'ında bu araçlar kurulu olmadığından exit 127 almıştır (Problem: vision/multimodal araç eksikliği).
  2. **`sqlite-with-gcov`:** Ajan `./configure`'u yanlış çalışma dizininde aramış (`exit 127: ./configure: No such file or directory`) ve finalde `TASK_COMPLETE` kelimesini markdown code fence içine yazdığı için Harbor tarafından bash komutu gibi çalıştırılmıştır (`exit 127: TASK_COMPLETE: command not found`).
  3. **`regex-log`:** Ajan yanıtındaki serbest metin (`But this doesn't ensure... Use...`), action parser tarafından bash komutu sanılarak container'a gönderilmiştir (`exit 127: But: command not found`).
  4. **`log-summary-date-ranges`:** Heredoc sınır belirteci tırnaklanmadığı için `exit 127: EOF: command not found` ve bash değişken genişlemesi hatasından dolayı `exit 127: 2025-08-12: command not found` alınmıştır.
  5. **`polyglot-c-py`:** Container'da `gcc` vardır ancak `python3` yoktur (`exit 127: python3: command not found`). Bu durum görevin doğası gereğidir.

---

## 3. Kök Neden Hipotezleri ve Hüküm

| Hipotez | İnceleme / Test | Sonuç |
|---|---|---|
| **H1: Harbor container'ı kurarken bir cache veya Docker layer bozulması yaşandı** | Harbor'ın kullandığı imaj hash'leri ve Docker katmanları kontrol edildi. 13 ve 14 Eylül'de `ghcr.io/laude-institute/terminal-bench/*:2.0` imajları bit-düzeyinde aynıdır. | ❌ **ÇÜRÜTÜLDÜ** |
| **H2: Task container'ları Alpine Linux'tur ve Harbor'da apk bozulmuştur** | `docker run` ile imajın `/etc/os-release` dosyası okundu. İmajlar Alpine değil Ubuntu 24.04 / Debian'dır. `apk` hiç var olmamıştır. | ❌ **ÇÜRÜTÜLDÜ** |
| **H3: Container'ların internet erişimi Harbor tarafından kapatılmıştır** | Verifier çıktısında (`verifier/test-stdout.txt`) `apt-get` ve `uv`'nin internetten onlarca MB paket indirdiği görülmüştür. Container internete açıktır. | ❌ **ÇÜRÜTÜLDÜ** |
| **H4: Prompt regresyonu ajanın paket kurmasını engellemiş ve halüsinasyona yol açmıştır** | `prompts.py` diff'i (`d2e7f1b`) ve LLM'in düşünce transkriptleri kanıtlamıştır: Ajan `apt`'yi görmüş fakat prompttaki mutlak yasak nedeniyle çalıştırmaktan kaçınmıştır. |  **KESİN KÖK NEDEN** |

---

## 4. Önerilen Düzeltmeler (Uygulama Değil, Sadece Öneri)

1. **`starter/agent/prompts.py`'deki Yanıltıcı Ağ ve Paket Kurulum Yasağını Düzeltmek:**
   - Mevcut yasak:
     > *"Everything runs locally inside this container. There is no network, no remote server... If a required tool or package is missing, do NOT attempt to install it over the network (apt-get...)"*
   - Önerilen revizyon:
     > *"Some task containers have outbound internet access while others are isolated. If an essential tool for the task is missing, check your OS (`cat /etc/os-release`), use the appropriate package manager (`apt-get update && apt-get install -y <pkg>` for Debian/Ubuntu), and proceed if network is available. Do not get stuck if the network is unavailable — seek alternatives."*

2. **Otomatik Ortam Keşfi (OS Bilgisi Enjeksiyonu):**
   - Şu an `agent.py` ilk turda ajana otomatik `pwd` ve `ls` snapshot'ı vermektedir.
   - Bu başlangıç snapshot'ına tek satırlık `cat /etc/os-release | grep PRETTY_NAME` veya `command -v apt-get apk` eklenirse model asla "Alpine üzerindeyim" sanrısına kapılıp `apk` aramaz.

3. **Action Parser Güçlendirmesi (`starter/agent/tools.py`):**
   - Serbest metinlerin (`But: command not found`) veya `TASK_COMPLETE`'in bash kodu sanılıp çalıştırılmasını önlemek için markdown kod bloğu ayıklayıcısı daha sıkı kurallara bağlanmalıdır.
