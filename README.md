# TALK — Terminal Assistant via Language Knowledge

TALK, doğal dildeki istekleri tek satırlık, güvenli ve kullanıma hazır Bash komutlarına çeviren bir terminal asistanıdır. Proje temel hedefi şudur:

- kullanıcıdan doğal dil alır,
- uygun bir LLM sağlayıcısından komut üretir,
- komutu güvenlik analiziyle tarar,
- gerekli durumlarda onay ister,
- canlı çıktıyı izleyerek komutu çalıştırır,
- geçmişi SQLite üzerinden saklar.

Bu yaklaşım sayesinde kullanıcılar `ls`, `du`, `grep`, `find`, `systemctl`, `curl | bash` gibi işlemleri doğrudan kopyalayıp yazmak yerine, açıklamalarla işi istemeyi öğrenir; sistem güvenliği ve doğrulama katmanı korunur.

---

## 1) Proje genel görünümü

TALK tek bir amaç etrafında kuruludur: "Doğal dili terminal komutuna dönüştür, riskleri değerlendir, güvenli şekilde çalıştır." Bu yüzden arayüz ve iş mantığı net şekilde ayrılmıştır.

- `talk.py`: CLI arayüzü ve etkileşimli terminal akışı
- `talk_gui.py`: Tkinter tabanlı masaüstü arayüzü
- `talk_core/`: iş mantığı, yapılandırma, güvenlik, geçmiş ve API katmanı
- `tests/`: güvenlik, onay ve geçmiş testleri

Aşağıdaki akış temel çalışma biçimini anlatır:

```text
Kullanıcı istemi
    ↓
CLI / GUI arayüzü
    ↓
TalkPipeline.generate()
    ↓
CommandApiPipeline
    ↓
Gemini / Groq modeli
    ↓
parse_response() 
    ↓
security.analyze_command()
    ↓
User confirmation gate
    ↓
executor.execute_stream()
    ↓
SQLite history save
```

---

## 2) Klasör yapısı

```text
Talk/
├── README.md
├── pyproject.toml
├── talk.py
├── talk_gui.py
├── talk_core/
│   ├── __init__.py
│   ├── config.py
│   ├── confirm.py
│   ├── executor.py
│   ├── history.py
│   ├── llm.py
│   ├── models.py
│   ├── pipeline.py
│   ├── security.py
│   └── api/
│       ├── __init__.py
│       ├── credentials.py
│       ├── http.py
│       ├── pipeline.py
│       ├── prompts.py
│       ├── providers.py
│       ├── registry.py
│       └── types.py
├── assets/
│   └── talk_icon.*
├── tests/
│   ├── test_confirm.py
│   ├── test_history.py
│   └── test_security.py
├── talk.egg-info/
└── ...
```

---

## 3) Ana modüller ve sorumlulukları

### 3.1 `talk.py`
CLI arayüzüdür. Kullanıcıdan girdi alır, `TalkPipeline` üzerinden komut üretimini tetikler, güvenlik denetimini yönetir ve ardından komutun çıktısını canlı şekilde gösterir.

Öne çıkan görevleri:

- REPL etkileşimli terminal döngüsü
- `--gui` veya doğrudan CLI çağrısı
- `--test` API erişim kontrolü
- güvenlik risk badge render etme
- kullanıcıya komut düzenleme / kopyalama / iptal seçenekleri sunma
- canlı output akışı

`run_command_live()` fonksiyonu, komut çıktısını satır satır ekrana yazar; `confirm_command()` ise önce riski gösterir, sonra onay aşamasını yönetir.

### 3.2 `talk_gui.py`
Tkinter tabanlı masaüstü uygulamasıdır. CLI davranışını grafik arayüze taşıyan katmandır.

Özellikler:

- modern geçmiş paneli
- arama ile eski komutlar
- API anahtarları ayarlama ekranı
- güvenlik risk listesi ve onay penceresi
- canlı çıktı alanı
- kullanıcıya göre OS / shell bağlamı ekleme

Bu dosya, kullanıcı deneyimini iyileştirir; asıl iş mantığı yine `talk_core` içinde tutulur. Bu mimari, "UI basit ve ince, iş mantığı merkezi" yaklaşımına uygundur.

### 3.3 `talk_core/pipeline.py`
Bu katmanın merkezinde `TalkPipeline` sınıfı vardır.

`TalkPipeline` şunları yapar:

1. `cfg` üzerinden yapılandırmayı alır.
2. ilgili API anahtarını çözer.
3. `CommandApiPipeline` ile komut üretimini başlatır.
4. `analyze_command()` ile güvenlik analizi yapar.
5. `execute_stream()` ile komutun canlı çalıştırılmasını planlar.
6. `HistoryManager` ile çalıştırma sonuçlarını kaydeder.

Yani `TalkPipeline` aslında uygulamanın “iş akışı koordinatörü” gibidir.

### 3.4 `talk_core/config.py`
Yapılandırma yönetimi bu modülde yapılır.

Sorumlulukları:

- `~/.talk/config.json` dosyasını okuma/yazma
- model seçimi (ör. `auto`, `gemini-2.5-flash`, `groq/llama-3.3-70b-versatile`)
- `api_timeout` ve `exec_timeout`
- `safe_mode` / `allow_high_risk_commands`
- OS bağlamı (`linux`, `windows11`, `macos` gibi)
- API anahtarlarının tek bir yerde tutulması ve normalize edilmesi

Bu sınıf, çoklu provider desteği için anahtarları `api_credentials` listesi olarak saklar ve gerektiğinde `gemini` / `groq` ayrımını otomatik anlar.

### 3.5 `talk_core/api/`
Bu klasör, LLM çağrıları için sağlayıcı katmanını içerir.

- `registry.py`: model adlarını normalize eder, provider eşlemesini yapar ve fallback listelerini oluşturur.
- `credentials.py`: ortam değişkenleri ve config içindeki API anahtarlarını çözer.
- `pipeline.py`: `CommandApiPipeline` ile tek giriş noktasını sağlar.
- `providers.py`: Gemini ve Groq çağrılarını, hata tiplerini ve model keşfini yönetir.
- `types.py`: provider enum ve hata sınıfları.

Bu yapı sayesinde model seçimi ve provider mantığı iş akışından ayrılmıştır. Eğer istenen model yoksa otomatik fallback yapar.

### 3.6 `talk_core/llm.py`
LLM yanıtı parsing ve komut doğrulama mantığı burada bulunur.

Özellikler:

- sistem talimatı tanımlar
- ortam bağlamı üretir (`OS`, `CWD`, `shell`)
- model çıktısından JSON çıkarır
- markdown, javascript, deneme akışı ya da bozuk JSON çıktılardan komutu temizlemeye çalışır
- tek satırlık komut kontrolü yapar
- güvenli olmayan komut formatlarını reddeder

Önemli fonksiyonlar:

- `parse_response()`
- `validate_generated_command()`
- `_extract_json()`
- `_normalize_command_text()`

Böylece LLM “aşırı verbose” ya da eksik komut üretirse uygulama bunu filtreler.

### 3.7 `talk_core/security.py`
Bu dosya uygulamanın güvenlik motorudur. Bir komut string'i verildiğinde risk düzeyini belirler.

Risk seviyeleri:

- `CRITICAL`: sistem çökertici, silici, formatlayıcı, `curl | bash` gibi çok yüksek riskli davranışlar
- `DANGEROUS`: `rm`, `sudo`, `shutdown`, `find -delete`, `eval` gibi kuvvetli risk işaretleri
- `CAUTION`: dosya taşıma, chmod, paket yöneticisi kullanımı, servis yönetimi gibi dikkat gerektiren işlemler
- `SAFE`: düşük riskli veya zararsız komutlar

Özel durum:

- Masaüstü dosyalarını temizleme gibi belirli sınırlı işlemler, kullanıcı açıkça hedef alan ve güvenli uzantılarla ilgiliyse izin verilebilir.
- `rm -rf /` ya da `mkfs` gibi kritik işlemler engellenir.

### 3.8 `talk_core/executor.py`
Komutun asıl çalıştırma katmanıdır. Bu dosya `subprocess` ile bash çalıştırır ve çıktıyı “streaming” biçimde üretir.

Örnek akış:

- stdout / stderr akışlarını izler
- timeout tespit eder
- çıktıyı sınırlı karakter sayısı ile kırpar
- exitcode yakalar
- `TalkPipeline.execute()` tarafından kullanılır

Bu yaklaşım, kullanıcı komutun sonucunu anlık olarak görebilsin diye tasarlanmıştır.

### 3.9 `talk_core/history.py`
Tüm çalıştırılan/üretilen komut geçmişi SQLite üzerinde saklanır.

Özellikler:

- `history.db` oluşturur
- eski `history.jsonl` veya `.talk_history` dosyalarını otomatik taşır
- `get_recent()` ve `search()` ile arama yapar
- komut, açıklama, risk seviyesi, exit code ve zaman bilgilerini depolar

Geçmiş verisi GUI içinde “history paneli” olarak kullanılır.

---

## 4) İş akışı: kullanıcıdan çalıştırmaya kadar

### Adım 1: Yapılandırma yüklenir
Uygulama başlatıldığında `Config` sınıfı çalışır. Şu kaynaklardan bilgi okunur:

- `~/.talk/config.json`
- çevre değişkenleri (`TALK_MODEL`, `GEMINI_API_KEY`, `GROQ_API_KEY`)
- `keyring` benzeri yerel anahtar depolama

### Adım 2: Model ve sağlayıcı seçimi
`CommandApiPipeline._resolve_context()` kullanılır.

- kullanıcı `auto` seçmiş olabilir,
- uygun sağlayıcı ve model bulunur,
- model yoksa fallback listesiyle sonraki modeli dener,
- `Gemini` ve `Groq` arası seçim otomatik yapılır.

### Adım 3: LLM’den komut üretimi
`TalkPipeline.generate()` çağrılır. Bu metod `CommandApiPipeline.generate()` ile model çağrısını yapar.

Modelden beklenen çıktı:

```json
{
  "command": "df -h /",
  "explanation": "Disk kullanımını gösterir.",
  "unsupported": false
}
```

### Adım 4: Komut doğrulaması
`llm.parse_response()` veya `validate_generated_command()` komut için zayıf/bozuk biçimleri filtreler.

Örneğin şunlar reddedilir:

- çok satırlı komut
- boş komut
- yarım kalmış kabuk ifadeleri
- `UNSUPPORTED_REQUEST`
- aşırı güvenlik riski taşıyan işlem zinciri

### Adım 5: Güvenlik skoru
`security.analyze_command()` komutun içindeki riskli kalıpları tarar.

Örnek bulgular:

- `curl | bash` → CRITICAL
- `rm -rf /` → CRITICAL
- `sudo` → DANGEROUS
- `chmod` → CAUTION

### Adım 6: Onay kapısı
`prompt_edit_command()` veya `confirm_command()` ile kullanıcı komutu düzenleyebilir, kopyalayabilir veya iptal edebilir.

- `safe_mode` aktifse yüksek riskli komutlar otomatik engellenir.
- kullanıcı `allow_high_risk_commands` izni verdiyse tekrar düşünülür.

### Adım 7: Çalıştırma
Onaylandıktan sonra `TalkPipeline.execute()` çağrılır. Bu metod `execute_stream()` ile bash sürecini başlatır ve çıktıyı canlı izler.

### Adım 8: Geçmiş kaydı
Komut çalıştırıldıktan sonra `record_run()` devreye girer. `HistoryManager` SQLite’ye şunları kaydeder:

- prompt
- komut
- açıklama
- risk seviyesi
- return code
- süre

---

## 5) Güvenlik filosu

TALK uygulamaları güvenlik açısından üç katmandan oluşur:

### Katman 1: LLM çıktı doğrulama
LLM cevabı JSON olarak beklenir; komut içeriği analiz edilir ve bazı bozuk kalıplar temizlenir.

### Katman 2: Shell güvenlik analizi
`security.py` komutun içinde potansiyel tehlikeleri tarar. `rm`, `sudo`, `curl | bash`, `dd`, `mkfs`, `eval` gibi kalıplar önemli uyarı/engelleme hedefi olur.

### Katman 3: Onay kapısı
Kullanıcıya komut gösterilir; risk bildirimi sunulur. Riskli komutlar için `safe_mode` ve kullanıcı izni devreye girer.

> Bu yapı, "modelin önerdiği komut doğrudan çalıştırma" riskini azaltmak için tasarlanmıştır.

---

## 6) Yapılandırma ve anahtar yönetimi

### Anahtar dosyası
Varsayılan konum:

```bash
~/.talk/config.json
```

Örnek içerik:

```json
{
  "model": "auto",
  "safe_mode": true,
  "api_timeout": 30,
  "exec_timeout": 60,
  "max_output_chars": 200000,
  "api_credentials": [
    {"provider": "gemini", "key": "AIza..."},
    {"provider": "groq", "key": "gsk_..."}
  ],
  "os_preset": "linux"
}
```

### Ortam değişkenleri

```bash
export GEMINI_API_KEY='AIza...'
export GROQ_API_KEY='gsk_...'
export TALK_MODEL='auto'
export TALK_API_TIMEOUT='30'
export TALK_EXEC_TIMEOUT='60'
```

### Sistem / OS bağlamı
`os_preset` değerleri şunları destekler:

- `linux`
- `debian`
- `ubuntu`
- `windows11`
- `windows`
- `macos`

Bu değer, LLM’e kullanıcı ortamı hakkında bağlam verir. Böylece komut üretiminde doğru sistem diline uygun komut oluşturulur.

---

## 7) Kurulum

### Bağımlılıklar
Proje Python 3.10+ gerektirir.

```bash
cd Talk
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Linux GUI desteği için ayrıca `tkinter` gereklidir:

```bash
sudo apt install python3-tk
```

### Çalıştırma

```bash
# Etkileşimli CLI
 talk

# Tek seferlik istek
 talk "disk kullanımını göster"

# GUI
 talk-gui

# API bağlantı testi
 talk --test

# Geçmişi görüntüle
 talk --history
```

### Alternatif doğrudan çağrı

```bash
python3 talk.py
python3 talk_gui.py
```

---

## 8) Kullanım örnekleri

### Basit örnekler

```bash
talk "şu anki klasörde en büyük 10 dosyayı göster"
talk "sistemde 30 gün önce değişmiş dosyaları bul"
talk "disk kullanımını özetle"
talk "apache servisini durdur"
```

### GUI kullanımı

- `talk-gui` ile arayüzü başlatın.
- sağ üstten veya ayarlar penceresinden API anahtarlarını ekleyin,
- arayüze doğal dil ile istek yazın,
- önerilen komutu inceleyin,
- güvenlik panelini kontrol edin,
- çalıştırın veya düzenleyin.

---

## 9) Testler ve geliştirme

Projenin testlerini şu komutla çalıştırabilirsiniz:

```bash
python3 -m unittest discover -s tests -v
```

Mevcut testler şunları kapsar:

- `test_security.py`: güvenlik denetimi ve kimlik/komut ayrıştırma
- `test_confirm.py`: doğrulama kapısı ve risk izinleri
- `test_history.py`: SQLite geçmiş ve arama davranışı

---

## 10) Mimari özeti

TALK, katmanlı ama hafif bir tasarıma sahiptir:

- `CLI / GUI`: kullanıcıyla etkileşim
- `TalkPipeline`: iş akışı koordinasyonu
- `Config`: ayarların ve anahtarların merkezi
- `API layer`: provider abstraction
- `LLM parser`: JSON ve komut doğrulama
- `Security engine`: risk analizi
- `Executor`: shell çalıştırma
- `History`: SQLite geçmiş

Bu mimari, uygulamanın bir “kaçınılmaz terminal işçisi” gibi davranmasını sağlar: komutu üreten modelin hatalarını, güvenlik risklerini ve çalıştırma ağacını uygulamanın kendisi denetler.

---

## 11) Lisans

Bu proje MIT Lisansı altında sunulmuştur.

---

## 12) Kısa özet

TALK, doğal dili kabuk komutuna çevirirken sadece üretim yapmaz; o komutun ne kadar güvenli olduğunu da değerlendirir. Bu yüzden kullanıcı deneyimini kolaylaştırırken, terminal üzerinde tehlikeli davranışları engellemeyi hedefler. En yalın ifadeyle:

"Doğal dil istemi → güvenli komut üretimi → risk denetimi → kullanıcı onayı → canlı çalıştırma → geçmiş kaydı"

Bu akış, proje için ana tasarım ilkesidir.
