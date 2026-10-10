# NeoTV v2 — Uygulama Notları

Bu belge, `MIMARI_DENETIM_RAPORU.md` raporunda önerilen mimarinin projeye nasıl uygulandığını, mevcut kurulumun v2'ye nasıl yükseltileceğini ve yeni özellik eklerken uyulacak kuralları anlatır.

---

## 1. Yükseltme adımları (Windows, mevcut kurulum)

Komutları proje kökünde, sanal ortam (venv) etkin olarak çalıştırın.

| # | Komut | Ne yapar |
|---|-------|----------|
| 1 | `python -m tools.devctl db-backup` | `instance/database.db` dosyasının zaman damgalı bir yedeğini alır. **Bu adımı atlamayın.** |
| 2 | `pip install -r requirements.txt -r requirements-dev.txt` | Bağımlılıkları yükler. |
| 3 | `python -m tools.devctl init-env` | `.env` yoksa oluşturur, varsa eksik anahtarları ekler. Eski `DATABASE_URL=sqlite:///../data/database.db` değerini `instance/` yoluna düzeltir. |
| 4 | `python -m tools.devctl doctor` | Ayarları, veritabanını, Redis'i, ffmpeg'i ve migration durumunu denetler. |
| 5 | `python -m tools.devctl migrate` | `b2c0de000001` → `000002` → `000003` sırasıyla çalışır: önce şema, sonra veri taşıma, en son eski tabloların silinmesi. |
| 6 | `python -m tools.devctl create-admin` | Yönetici hesabı oluşturur, ya da var olan hesabı yönetici yapar. |
| 7 | `python -m tools.cleanup_legacy` → `--apply` | Önce kuru çalıştırma (sadece listeler). `--apply` eski dosyaları `.legacy_backup/` altına taşır; işlem geri alınabilir. |
| 8 | `cd frontend && npm ci && npm run build` | Frontend'i derler. Derleme öncesinde API sözleşmesi de denetlenir. |
| 9 | `python -m tools.devctl run` | API, worker ve beat süreçlerini başlatır. Frontend geliştirme sunucusu için: `npm run dev`. |

> `migrate` adımı `000003`'ten sonra geri alınamaz; `000003` eski tabloları siler ve downgrade'i bilerek hata verir. Bu nedenle 1. adımdaki yedek zorunludur.

**Redis kurmadan yerel geliştirme:** `.env` içinde yorum satırı olarak duran `REDIS_URL=fakeredis://dev` ve `CELERY_ALWAYS_EAGER=true` satırlarını açın. Bu durumda `devctl run` worker ve beat süreçlerini başlatmaz. Üretim (prod) ortamında ayarlar doğrulanırken fakeredis, SQLite ve eager mod reddedilir.

---

## 2. Bilerek taşınmayan veriler

| Veri | Neden |
|------|-------|
| Refresh token'lar ve web oturumları | Kimlik doğrulama sistemi yeni. Yükseltmeden sonra herkes bir kez yeniden giriş yapar. |
| Cihaz parmak izleri | v2'de cihaz anahtarı `HMAC(pepper, …)` ile üretiliyor ve eski kayıtlardan yeniden hesaplanamıyor. Eski cihazlar *pasif* geçmiş kaydı olarak korunur. |
| RTMP yayın anahtarları | v2 yalnızca anahtarın HMAC özetini saklıyor. Yayın anahtarlarını yönetim panelinden (Canlı yayın → anahtar ikonu) yenileyin. Harici kaynaklı kanallar değişmeden çalışmaya devam eder. |
| DRM içerik anahtarları | Eski sürüm bu anahtarları açık metin olarak saklıyor ve sunuyordu, bu yüzden ele geçirilmiş sayılmalılar. Korumayı yeni anahtarlarla yeniden uygulayın; yeni anahtarlar zarf şifrelemeyle saklanır. DRM politikaları taşındı. |
| `access_log`, `background_job` | Operasyonel kayıtlar olduğu için taşınmadı. |
| Yetim, yinelenen ya da geçersiz satırlar | Taşıma sırasında atlanır. Atlanan satır sayısı nedenine göre (`orphan`, `duplicate`, `non_http_url` …) migration çıktısında raporlanır. |

---

## 3. Mimari özet

### Backend

```
app/kernel/      container · ModuleRegistry · manifest · capability · extension point
                 outbox/inbox · UnitOfWork · endpoint() · OpenAPI
app/modules/<m>/ manifest.py · api.py (dış sözleşme) · domain.py · services.py
                 models.py · http.py · handlers.py · tasks.py
app/shared_kernel/ modüllerin ortak kullandığı saf yardımcılar
```

- **Modüller arası iletişim** üç yoldan biriyle yapılır:
  1. Bir capability'yi zorunlu ya da isteğe bağlı olarak kullanmak: `CapabilityIndex.optional(...)`.
  2. Bir olay yayınlamak (outbox) ve başka bir modülde abone olmak (inbox).
  3. Bir extension point'e eklenti kaydetmek: `drm.license_issuers`, `admin.abuse_rules`.
- **Doğrudan import yasak.** Bu kural `import-linter` ile zorlanır (`.importlinter`, 3 sözleşme).
- **Her HTTP ucu `endpoint()` üzerinden geçer.** Kimlik doğrulama, hız sınırı, yetki, profil, idempotency, doğrulama ve yanıt sözleşmesi tek bir yerde tanımlanır ve OpenAPI'ye otomatik yazılır.
- **Modül kapatma:** `DISABLED_MODULES=recommendations,drm`. Kapatılan modüle bağımlı olan modüller açılışta `MissingDependencyError` ile durur. İsteğe bağlı bağımlılıklar sessizce devre dışı kalır.

### Frontend

```
src/core/      API istemcisi (operationId tabanlı) · auth · featureKit · i18n
src/shared/    yalnızca sunum bileşenleri (core'u bile import etmez)
src/features/  <özellik>/manifest.js + index.js (public API)
src/app/       composition root: router, shell, provider'lar, bootstrap
```

- **Katman kuralları** ESLint ile zorlanır (`eslint.config.js`). Bir özellik başka bir özelliği yalnızca `index.js` dosyası üzerinden import edebilir.
- **API çağrıları** her zaman `api.call('<operationId>', { params, query, body })` biçimindedir. `npm run check:api`, kaynak kodda kullanılan her operasyonun backend sözleşmesinde var olduğunu doğrular.
- **Açılış:** `/api/v1/health/info` hangi modüllerin açık olduğunu döner. Backend modülü kapalı olan özellik menüden ve rotalardan çıkarılır.

---

## 4. Yeni bir şey eklerken (kontrol listesi)

### Yeni backend modülü

1. `flask kernel new-module <ad>` komutunu çalıştırın. Komut `_template` modülünü kopyalar; oluşan iskelet hemen açılır.
2. `app/modules/__init__.py` içindeki `INSTALLED_MODULES` listesine bir satır ekleyin.
3. Modülün `manifest.py` dosyasında `provides` / `requires` / `subscribes` / `error_map` alanlarını doldurun.
4. `flask db revision --autogenerate` ile migration oluşturun ve gözden geçirin.
5. `python -m tools.devctl openapi` ile `openapi/openapi.json` dosyasını güncelleyin. Ardından `cd frontend && npm run gen:api` çalıştırın.
6. `pytest`, `ruff check .`, `mypy app` ve `lint-imports` komutlarının hepsi yeşil olmalı. Fitness testleri şunları kontrol eder:
   - yanıtlarda belgelenmemiş hata kodu olmaması,
   - `endpoint()` kullanmayan rota olmaması,
   - OpenAPI dosyasının güncel olması.

### Yeni frontend özelliği

1. `src/features/<ad>/manifest.js` dosyasını `defineFeature({ id, backendModule, requires, routes, nav, slots, contributes })` ile oluşturun.
2. Dışa açılacak her şeyi `index.js` dosyasında toplayın.
3. `src/features/index.js` dosyasına bir satır ekleyin.
4. Başka bir özelliğin ekranına bileşen eklemek için o özelliğin ilan ettiği slot'a katkı yapın. Kullanılabilir slot'lar:
   - `home.rows`
   - `content.actions`
   - `player.observers`
   - `account.sections`
   - `shell.user`

**Sözleşme ihlalleri adlı hatalarla durur:**

| Hata | Ne zaman fırlatılır |
|------|---------------------|
| `FeatureContractError` | Manifest geçersiz olduğunda |
| `DuplicateRouteError` | İki özellik aynı yolu sahiplendiğinde |
| `MissingFeatureError` | Gerekli bir özellik kapalı ya da yüklü olmadığında |
| `UnknownSlotError` | İlan edilmemiş bir slot'a katkı yapıldığında |

Bu hatalar ekranda boş sayfa yerine `BootError` bileşeniyle gösterilir.

### Yeni yönetim paneli sekmesi

`src/features/admin/sections/registry.js` dosyasına bir kayıt ekleyin ve yanına bir bölüm (section) dosyası yazın. `module` alanı, sekmenin hangi backend modülü kapalıyken gizleneceğini belirler.

---

### Yeni bir e-posta şablonu

1. E-postayı gönderecek modülün içinde bir `emails.py` dosyası oluştur ve `EmailTemplate(key="<modul>.<ad>", subject=..., text=..., html=...)` tanımla. Şablondaki `{alan}` yer tutucularının hepsi zorunludur; HTML gövdesine giren değerler otomatik olarak kaçırılır (escape).
2. Modülün manifest dosyasına `ExtensionSpec("notifications.templates", "app.modules.<modul>.emails:templates")` ekle.
3. E-postayı göndermek için `CapabilityIndex.optional("notifications.email")` ile mailer'ı al ve kendi `with uow:` bloğunun içinde `queue(to=..., template=..., context=...)` çağır. Böylece e-posta, modülün kendi değişiklikleriyle aynı işlemde (atomik olarak) kaydedilir.

Bilinmeyen şablon ya da eksik veya fazla bir alan, isimli bir hata verir: `EMAIL_TEMPLATE_UNKNOWN` / `EMAIL_TEMPLATE_CONTEXT`. notifications modülü kapalıysa şablon katkısı otomatik olarak düşer.

### Yeni bir e-posta sağlayıcısı (Resend, Postmark …)

1. `name` alanı ve `send(message: RenderedEmail)` metodu olan bir sınıf yaz. Kalıcı hatalarda `PermanentDeliveryError` fırlat; geçici hatalarda normal bir exception fırlat (outbox artan beklemeyle tekrar dener).
2. Sınıfı `notifications.email_senders` noktasına ekle ve `.env` içinde `EMAIL_BACKEND=<name>` yap. Var olmayan bir ad verilirse uygulama açılışta, mevcut seçenekleri listeleyen bir hatayla durur.

---

## 5. E-posta ve hesap kurtarma

| Ortam | Ayar | Ne olur |
|-------|------|---------|
| Geliştirme | `EMAIL_BACKEND=console` (varsayılan) | E-posta `var/mail/<id>.eml` dosyasına yazılır. Bağlantılar `Baslat.bat` penceresine `mail.console ... links=` satırı olarak düşer; tıklayıp test edebilirsin. |
| Prod | `EMAIL_BACKEND=smtp` + `SMTP_HOST/PORT/SECURITY/USERNAME/PASSWORD` + `EMAIL_FROM` | Prod ortamında `console` ve `memory` reddedilir. SMTP 5xx hatası kalıcı sayılır, 4xx hatası tekrar denenir. |
| Test | `memory` | Testler e-postaları bellekten okur. |

**Akışlar:**
- **Kayıt:** E-posta verilmişse doğrulama e-postası gönderilir; bağlantı 48 saat geçerlidir.
- **Şifremi unuttum:** Hesap var olsun ya da olmasın aynı yanıt döner. Bağlantı 30 dakika geçerlidir ve tek kullanımlıktır.
- **Şifre sıfırlama sonrası:** Bütün oturumlar kapatılır ve hesap sahibine bilgilendirme e-postası gider.

**Güvenlik:**
- Token'lar veritabanında yalnızca SHA-256 hash'i olarak saklanır.
- Bağlantıdaki gizli değer `#token=` kısmında durur; sunucu loglarına ve Referer başlığına düşmez.
- E-posta içeriği gönderimden sonra silinir; saatlik bir temizlik görevi 24 saatten eski kayıtların içeriğini de temizler.

---

## 6. Doğrulama komutları

```bash
pytest                                   # SQLite + fakeredis (hızlı)
TEST_DATABASE_URL=postgresql://... TEST_REDIS_URL=redis://... pytest tests/integration
python -m tools.smoke_boot               # sıfırdan kurulum → API → giriş → e-postayla şifre sıfırlama
ruff check . && ruff format --check . && mypy app && lint-imports
cd frontend && npm run lint && npm test -- --run && npm run build
```
