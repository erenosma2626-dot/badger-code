# Vision / Görsel Girdi Görevleri ve Yarışma Kuralları (RULES.md) Analiz Raporu

**Tarih:** 2026-09-14  
**Yazar:** worker1-agy  
**Branch:** `feat/vision-rules-analysis`  
**İlgili Görev:** Plan Adım #4 / Öncelik 2 (Vision/görsel girdi desteği ve mimari karar)

---

## 1. Yönetici Özeti (Executive Summary)

`chess-best-move` görevinde ajanın `chess_board.png` dosyasını okuyamaması üzerine ortaya çıkan *"Sisteme harici bir Vision modeli (GPT-4o, Claude 3.5 Sonnet, Qwen2-VL vb.) eklenmeli mi?"* sorusu, yarışma kuralları ([`RULES.md`](../RULES.md)), SSS ([`FAQ.md`](../FAQ.md)) ve görevin **orijinal referans çözümü** incelenerek araştırılmıştır.

### Üç Kritik Sonuç:
1. **Harici Vision LLM Eklemek KURAL İHLALİDİR:** Yarışma kuralları gereği kapalı modeller (GPT, Claude, Gemini) kesinlikle yasaktır (`RULES.md §4`). Çoklu model kullanımına izin verilir ancak dahil olan *her modelin* onaylı açık model listesinde olması şarttır (`FAQ.md`). Onaylı listedeki 5 modelin (Qwen3.6-27B, Qwen3-Coder-30B, Qwen2.5-Coder 32B/14B/7B) **hiçbiri multimodal/vision modeli değildir.**
2. **Görev Aslında Vision LLM İstememektedir:** `chess-best-move` görevinin resmi referans çözümü (`solution/solve.py`) incelendiğinde, **hiçbir multimodal model kullanılmadığı görülmüştür.** Container içinde `/fonts/noto.ttf` ve `pillow 11.2.1` hazır bulunmaktadır. Referans çözüm, tahtayı 8x8 karelere bölüp Unicode satranç karakterleriyle pikselleri (Mean Squared Error ile) karşılaştıran ve ardından `stockfish` ile en iyi hamleyi bulan **saf bir Python betiğidir.**
3. **Maliyet / Getiri Oranı:** 89 Terminal-Bench görevinin **88'i saf terminal/metin görevidir.** Sadece 1 görev görsel girdi içermektedir. Tek bir görev için mimariyi bozmak veya diskalifiye riskine girmek rasyonel değildir.

---

## 2. Yarışma Kuralları ve Model Kısıtlamaları İncelemesi

[`RULES.md`](../RULES.md), [`FAQ.md`](../FAQ.md) ve [`reference-starter-repo/README.md`](../reference-starter-repo/README.md) belgelerindeki bağlayıcı kurallar:

| Konu | Resmi Kural | Badger Code Açısından Sonuç |
|---|---|---|
| **Kapalı Modeller** | *"Closed-weight models (GPT, Claude, Gemini) are out of scope anywhere in your system, including 'just the planner'."* (`RULES.md §4`) | GPT-4o, Claude 3.5 Sonnet veya Gemini Vision API'si kesinlikle çağrılamaz. Çağrıldığı tespit edilirse diskalifiye edilir. |
| **Onaylı Modeller** | *"Your submitted run must use a model on the approved list."* (`RULES.md §4`) | Sadece şu modeller kullanılabilir: `Qwen3.6-27B-FP8`, `Qwen3-Coder-30B-A3B-Instruct-FP8`, `Qwen2.5-Coder-32B/14B/7B-Instruct-AWQ`. |
| **Çoklu Model Kullanımı** | *"Can I use multiple models? Yes, as long as every model involved is on the approved list."* (`FAQ.md`) | İkinci bir model kullanılabilir (ör. planner + coder), ancak ikinci model de onaylı listede olmak zorundadır. |
| **Multimodal / Vision** | Onaylı listede hiçbir vision modeli yoktur. | Mimarimize açık kaynaklı dahi olsa (ör. Qwen2-VL) onaylatılmamış ikinci bir model eklenemez. |
| **Model Onayı Talebi** | Katılımcılar Kaggle Discussion sekmesinde HF linki + quant + gerekçe ile model ekleme talebi açabilir (≤48GB VRAM). | Eğer vision modeli kullanılmak isteniyorsa yarışma organizatörlerine resmi talep açılması zorunludur. |
| **Hardcoding Yasağı** | *"One system prompt, one agent loop, no per-task branching... no hardcoded solutions."* (`RULES.md §4`) | `if task == "chess-best-move"` gibi göreve özel hardcode dallanmalar kesinlikle yasaktır. |

---

## 3. `chess-best-move` Görevinin Referans Çözüm Analizi

Harbor görev önbelleğindeki orijinal çözüm betiği (`~/.cache/harbor/tasks/Wz3X4eVncfR6vdDfRM6kXV/chess-best-move/solution/solve.py`) doğrudan okunmuştur:

### Çözümün Çalışma Mantığı:
1. **Bağımlılık Kurulumu:**
   ```bash
   apt install -y stockfish
   pip3 install numpy==2.3.2 python-chess==1.2.0 --break-system-packages
   ```
2. **Kareleri Ayrıştırma:**
   `PIL.Image.open("chess_board.png")` ile 8x8 kareler kırpılır.
3. **Piksel Benzerliği ile Taş Tespiti (Template Matching):**
   Container'da bulunan `/fonts/noto.ttf` fontu kullanılarak 12 satranç taşı (`♔, ♕, ♖, ♗, ♘, ♙, ♚, ♛, ♜, ♝, ♞, ♟`) şablon resimler olarak bellekte çizilir. Her tahta karesi ile bu şablonlar arasında Mean Squared Error (MSE) hesaplanır; minimum fark veren taş tahtaya atanır.
4. **FEN Notasyonu Üretimi:**
   Tespit edilen taş dizilimi standart FEN formatına dönüştürülür (`full_fen = f"{fen_position} w KQkq - 0 1"`).
5. **Motor ile En İyi Hamlenin Hesaplanması:**
   `python-chess` kütüphanesi üzerinden yerel `stockfish` motoru çalıştırılır (`time_limit = chess.engine.Limit(time=2.0)`).
6. **Sonucun Kaydedilmesi:**
   Hamle `/app/move.txt` dosyasına yazılır.

### Bizim Ajan Neden Başarısız Oldu?
14 Eylül koşumunda (`starter/jobs/2026-09-14__11-10-07/chess-best-move__tEmkxth`):
- Ajan görseli doğrudan incelemek için bash seviyesinde `identify chess_board.png` (ImageMagick) ve `file chess_board.png` komutlarını denedi.
- İki komut da minimal Ubuntu imajında olmadığı için `exit 127: command not found` aldı.
- Ajan ortamda `python3` ve `Pillow`'un kurulu olduğunu araştırmadı (`python3 -c "import PIL"` yapmadı).
- Görseli okuyamayınca tahtayı analiz etmeden sabit bir hamle (`e2e4`) üreterek `TASK_COMPLETE` dedi.

---

## 4. Stratejik Karar Seçenekleri

| Seçenek | Risk / Kural Durumu | Geliştirme Maliyeti | Beklenen Kazanç |
|---|---|---|---|
| **1. Harici Vision API (GPT-4o/Claude) Bağlamak** | 🔴 **DİSKALİFİYE (Kural İhlali)** | Düşük | Sıfır (Diskalifiye olunur) |
| **2. Kaggle Discussion'da Qwen2-VL Talebi Açmak** | 🟢 **Kurallara Uygun** | Yüksek (Orkestrasyona 2. model entegrasyonu, token bütçesi) | 89 görevde +1 görev (%1.1 puan) |
| **3. ReAct Promptuna "Görsel Dosyaları Python/PIL ile İncele" Rehberliği Eklemek** | 🟢 **Kurallara %100 Uygun (Tek Loop)** | Düşük (Sadece prompt stratejisine genel bir madde) | Model doğru düşünürse +1 görev |
| **4. Görsel Görevleri Kapsam Dışı Bırakmak (No-op / Pass)** | 🟢 **Sıfır Risk** | Sıfır | 88/89 görev üzerinden tam performans |

---

## 5. Önerilen Eylem Planı (Öneri)

1. **Vision modeli ekleme fikri tamamen terk edilmelidir:** Yarışma kuralları buna izin vermemektedir ve 89 görevde sadece 1 adet görsel görev için multimodal mimari kurmak erken soyutlama ve token israfıdır.
2. **Genel Prompt İyileştirmesi:** [`starter/agent/prompts.py`](starter/agent/prompts.py) altındaki `STRATEGY` bölümüne göreve özel hardcode olmadan genel bir kural eklenebilir:
   > *"If the task input involves binary, structured, or media files (.png, .dat, .bin, .parquet), do not rely on missing shell utilities (identify, hexdump). Instead write a small Python script using standard libraries (PIL, struct, io) to inspect the data."*
3. **Kaggle Discussion İzlemesi:** Eğer organizatörler topluluk talebiyle listeye hafif bir açık ağırlıklı vision modeli (ör. `Qwen2-VL-7B-Instruct`) eklerse, o zaman değerlendirilebilir; şu aşamada öncelik metin-tabanlı 88 görevin başarısını artırmak olmalıdır.
