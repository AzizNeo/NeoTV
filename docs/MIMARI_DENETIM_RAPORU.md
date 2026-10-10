# NeoTV IPTV — Expert Mimari Denetim Raporu ve Dönüşüm Planı

> **Kapsam:** `IPTV_Project` deposunun tamamı — backend (`app/`, 128 Python dosyası), migration zinciri, Celery/Redis altyapısı, transcoder alt sistemi, betikler (`Scripts/`), CI (`.github/`), `docker-compose.yml` ve frontend (`frontend/src`, React 19 + Vite 7).
> **Yöntem:** Her kaynak dosya satır satır okundu; import grafiği, çağrı zinciri, transaction sınırları, process/thread modeli ve HTTP sözleşmeleri (frontend ↔ backend) çapraz doğrulandı. Her bulgu **dosya + satır düzeyinde kanıt**, **gerçek etki senaryosu** ve **üretim kalitesinde fix kodu** içerir.
> **Tarih:** 09.10.2026

---

## İçindekiler

0. [Yönetici Özeti](#0-yönetici-özeti)
1. [Önem Derecesi Sözlüğü](#1-önem-derecesi-sözlüğü)
2. [Mevcut Mimari Haritası (As-Is)](#2-mevcut-mimari-haritası-as-is)
3. [Bulgular ve Expert Fix'ler](#3-bulgular-ve-expert-fixler)
   - [3.A Güvenlik](#3a-güvenlik)
   - [3.B Çalışma Zamanı Kırılmaları (Runtime Breakers)](#3b-çalışma-zamanı-kırılmaları-runtime-breakers)
   - [3.C Veri Tutarlılığı, Transaction ve Eşzamanlılık](#3c-veri-tutarlılığı-transaction-ve-eşzamanlılık)
   - [3.D Asenkron Altyapı: Celery, Outbox, EventBus](#3d-asenkron-altyapı-celery-outbox-eventbus)
   - [3.E Streaming ve Transcoder](#3e-streaming-ve-transcoder)
   - [3.F Performans ve Ölçeklenebilirlik](#3f-performans-ve-ölçeklenebilirlik)
   - [3.G Konfigürasyon, Ortam ve DevOps](#3g-konfigürasyon-ortam-ve-devops)
   - [3.H Frontend](#3h-frontend)
   - [3.I Kod Hijyeni ve Teknik Borç](#3i-kod-hijyeni-ve-teknik-borç)
   - [3.J Test ve CI](#3j-test-ve-ci)
4. [Hedef Mimari: "Puzzle" Modular Monolith (To-Be)](#4-hedef-mimari-puzzle-modular-monolith-to-be)
5. [Geçiş Yol Haritası (Strangler Fig, Kırılmasız)](#5-geçiş-yol-haritası-strangler-fig-kırılmasız)
6. [Yeni Özellik Ekleme / Çıkarma / Değiştirme Reçetesi](#6-yeni-özellik-ekleme--çıkarma--değiştirme-reçetesi)
7. [Ek: Bulgu Endeksi ve Kontrol Listesi](#7-ek-bulgu-endeksi-ve-kontrol-listesi)

---

## 0. Yönetici Özeti

Proje iki mimarinin **ara geçiş durumunda donmuş** hâlde: bir yanda klasik katmanlı Flask yapısı (`app/routes`, `app/services`, `app/models`), diğer yanda Strangler Fig ile başlatılmış modüler monolit (`app/modules`, `app/core`, `app/shared_kernel`). Sorun şu ki ileri seviye yapı taşlarının (outbox, circuit breaker, GCRA rate limiter, cache stampede guard, stream concurrency guard, profile context, chaos, L1 cache, search, transcoder orkestratörü) **önemli bir kısmı ya hiç bağlanmamış ya da yanlış bağlanmış**. Ortaya çıkan tablo "parçalar expert, montaj kırık" şeklinde özetlenebilir.

### 0.1 Sağlık Karnesi

| Boyut | Not | Gerekçe (özet) |
|---|---|---|
| Güvenlik | **F** | Kimliksiz SSRF proxy, path traversal ile dosya okuma, ödemesiz plan yükseltme, imzasız webhook, RTMP stream key'inin herkese açık sızması, token tipi karışıklığı |
| Çalışma zamanı doğruluğu | **D** | Favoriler, geçmiş, playlist listesi, trending, canlı ABR ve VOD yetkilendirme uçları deterministik olarak 4xx/5xx döndürüyor; ikinci kullanıcı aynı tarayıcıdan giriş yapamıyor |
| Veri tutarlılığı | **D** | Outbox başarısız handler'ı "processed" işaretliyor; plan limitleri 3 farklı yerde; eşzamanlı stream limiti yarış koşuluna açık |
| Asenkron altyapı | **F** | İki ayrı Celery uygulaması; outbox dispatcher hiçbir worker tarafından çalıştırılmıyor; transcoder task'ı kayıtsız |
| Modülerlik | **C−** | Doğru yön (ports/adapters, shared_kernel, import-linter) ama sessiz hata yutan loader'lar, yarım göç ve çift implementasyonlar modülerliği fiilen anlamsızlaştırıyor |
| Performans | **D** | 6 thread'li Waitress üzerinde 10–30 sn bloklayan istekler, segment proxy'sinin tamamen RAM'e alınması, senkron toplu import |
| Test/CI | **F** | Fiilen sıfır çalışan test; CI yolları Linux'ta kırık; katman sözleşmesi kendi kodunu ihlal ediyor |
| Frontend | **C** | Feature-sliced yön doğru; ancak çift `AuthProvider`, VOD'un yetkilendirmeyi tamamen bypass etmesi, 5 olmayan admin endpoint'i |

### 0.2 En Kritik 12 Bulgu (önce bunlar)

| # | ID | Bulgu | Etki |
|---|---|---|---|
| 1 | SEC-01 | `/api/live/<id>/<path:filename>` path traversal | Sunucudaki her okunabilir dosyanın (`.env`, `instance/database.db`) indirilmesi |
| 2 | SEC-02 | `/api/live/proxy/hls?url=` kimliksiz, allowlist'siz, `verify=False` proxy | Tam SSRF: iç ağ, cloud metadata, Redis/Flower yönetim uçları |
| 3 | SEC-04 | `/api/billing/upgrade` ödeme almadan planı yükseltiyor; `/webhook` imzasız | Gelir kaybı, herkes Family plan |
| 4 | SEC-03 | `LiveChannel.to_dict()` → `stream_key` kimliksiz `/api/live/channels`'ta | Yayın kaçırma (RTMP publish hijack) |
| 5 | SEC-05 | Access/profile token tipi doğrulanmıyor; askıya alınan kullanıcı JWT ile erişmeye devam ediyor | Yetki yükseltme, oturum ömrü uzatma |
| 6 | RT-06 | `Device.device_id` global unique + boş fingerprint | Aynı tarayıcıdan 2. kullanıcı **giriş yapamıyor** (IntegrityError → 500) |
| 7 | RT-05 | `@require_profile_context` her yerde zorunlu, ama profil token'ı üreten endpoint ve `profiles` tablosu yok | Favoriler, geçmiş, öneriler, VOD yetkilendirme %100 başarısız |
| 8 | ASY-01 | İki Celery app; outbox task'ları kayıtlı olduğu app hiçbir worker'da yok | `subscription.changed` hiç işlenmiyor → ödeme yapan kullanıcı 1 stream'e kilitli |
| 9 | ASY-02 | `EventBus.publish` handler hatasını yutuyor → outbox `processed` | Retry/dead-letter mekanizması fiilen ölü; sessiz veri kaybı |
| 10 | FE-02 | VOD oynatma `channel.url`'i doğrudan player'a veriyor | Eşzamanlı limit, DRM, oturum takibi, abonelik kontrolü tamamen bypass |
| 11 | RT-07 | Migration zinciri bozuk (`zzzz_*` revision id'siz, `billing_subscriptions`/outbox tabloları yok) | `flask db upgrade` çalışmıyor; billing ve outbox 500 |
| 12 | CFG-01 | `load_dotenv()` `Config` sınıfı değerlendirildikten **sonra** çağrılıyor | `.env`'deki `SECRET_KEY` hiç uygulanmıyor → hardcoded `'dev-secret-key'` ile JWT imzalanıyor |

### 0.3 Mimari Teşhis — Tek Cümle

> **Sistemin temel kusuru, modüllerin birbirine "sözleşme" ile değil "konvansiyon + sessiz try/except" ile bağlanması.** Bir modül eksik olduğunda, yanlış isimlendirildiğinde ya da bağımlılığı çözülemediğinde sistem bunu **açık, isimlendirilmiş bir hata** ile bildirmek yerine sessizce devam ediyor. Bölüm 4'teki hedef mimari tam olarak bunu tersine çevirir: her parça bir **manifest** ile kendini ilan eder, çekirdek bu manifest'leri **boot anında doğrular** ve uyumsuzlukta `ModuleContractError`, `MissingCapabilityError`, `DuplicateRouteError` gibi isimlendirilmiş hatalarla **başlatmayı reddeder**.

---

## 1. Önem Derecesi Sözlüğü

| Seviye | Anlam | Hedef süre |
|---|---|---|
| **P0 — Kritik** | Güvenlik açığı, veri kaybı ya da çekirdek akışın deterministik kırılması | Hemen (Faz 0) |
| **P1 — Yüksek** | Belirli koşullarda kırılma, iş kuralı ihlali, ölçekte çöküş | Faz 1 |
| **P2 — Orta** | Bakım maliyeti, performans, tutarsız davranış | Faz 2 |
| **P3 — Düşük** | Hijyen, okunabilirlik, gelecekteki risk | Faz 3 |

Her bulgu formatı: **Konum → Kanıt → Etki → Kök Neden → Expert Fix → Doğrulama**.

---

## 2. Mevcut Mimari Haritası (As-Is)

```mermaid
flowchart TB
    subgraph FE["frontend (React 19)"]
        FE_core["core/ (axios, AuthContext, router)"]
        FE_feat["features/ (auth, playlist, epg, billing, admin, player)"]
        FE_legacy["legacy: components/SecurePlayer, pages/*, context/AuthContext (re-export)"]
    end

    subgraph BE["Flask app (Waitress, 6 thread)"]
        INIT["app/__init__.py create_app()"]
        subgraph LEG["Legacy katman"]
            R["routes/* (15 blueprint, elle kayıt)"]
            S["services/* (statik metotlar, db.session doğrudan)"]
            M["models/* (bir kısmı shim)"]
        end
        subgraph NEW["Strangler modülleri"]
            MOD_AUTH["modules/auth (routes+services+ports+adapters+listeners)"]
            MOD_BILL["modules/billing (routes+services)"]
            MOD_OTHER["modules/drm, stream, profile, search (yalnızca models/services; routes yok)"]
        end
        CORE["core/ (container, event_bus, outbox_dispatcher, middleware, resilience, cache, celery_app #1)"]
        SK["shared_kernel/ (events, outbox modeli, registry)"]
        TASKS["tasks/ (celery_app #2, m3u, epg, transcoder)"]
    end

    subgraph INFRA["Altyapı"]
        SQLITE[("SQLite instance/database.db")]
        REDIS[("Redis — start.py başlatmıyor")]
        W1["celery worker (compose) → celery_app #2"]
        FFMPEG["FFmpeg /dev/shm (Linux-only)"]
    end

    FE_feat -->|"/api/* (Vite proxy)"| R
    FE_feat --> MOD_AUTH
    INIT --> R
    INIT -->|"module_loader: hata yutarak"| NEW
    R --> S --> M --> SQLITE
    MOD_AUTH -->|"adapters → legacy models"| M
    CORE --> REDIS
    MOD_BILL -->|"OutboxEvent INSERT"| SK
    CORE -. "dispatch_outbox: celery_app #1 — HİÇBİR WORKER YOK" .-> SK
    TASKS --> W1
    R -->|"master.m3u8"| TASKS
    TASKS -. "transcode.* task'ı kayıtsız" .-> FFMPEG
```

**Gözlemler:**

1. **Çift kaynak gerçekliği (dual source of truth):** `services/auth_service.py` ↔ `modules/auth/services.py`, `services/billing_service.py` ↔ `modules/billing/services.py`, `routes/auth.py` ↔ `modules/auth/routes.py`, `context/AuthContext.jsx` ↔ `core/context/AuthContext.jsx`, `components/ErrorBoundary.jsx` ↔ `shared/ErrorBoundary/ErrorBoundary.jsx`, `components/SecurePlayer.jsx` ↔ `features/player/CustomPlayer.jsx`, `PremiumTab` ↔ `PremiumPage`. Canlıda hangisinin çalıştığı yalnızca `create_app` ve `module_loader` sırası okunarak anlaşılabiliyor.
2. **"Bağlanmamış uzmanlık":** `LoginAttemptGuard` (yalnızca kayıtsız legacy `routes/auth.py`'de), `StreamConcurrencyGuard` (yalnızca 403 gövdesinde sayaç için), `l1_l2_cache_response`, `invalidate_cache`, `chaos.*`, `search_channels`, `ProfileContextService`, `LiveStreamService`, `EPGService`, `BackgroundJob` — **hiçbiri bir istek yolunda gerçek iş yapmıyor.**
3. **Import-time yan etkiler:** `core/container.py` modül yüklenirken Redis client'ları, guard'ları, script kayıtlarını; `core/observability/tracing.py` global tracer provider'ı ve OTLP exporter'ı; `transcoder/stream_manager.py` Redis bağlantısını; `extensions.py` Redis URL'sini **import anında** oluşturuyor. Test edilebilirlik ve konfigürasyon sırası bu yüzden kırık (bkz. CFG-01).

---

## 3. Bulgular ve Expert Fix'ler

### 3.A Güvenlik

#### SEC-01 · P0 · HLS segment endpoint'inde path traversal (keyfi dosya okuma)

**Konum:** `app/routes/live.py` → `serve_hls_segments()`

```python
@live_bp.route('/<int:channel_id>/<path:filename>', methods=['GET'])
def serve_hls_segments(channel_id, filename):
    file_path = Path(f"/dev/shm/streams/{channel_id}/{filename}")
    ...
    return send_file(file_path, mimetype=mimetype)
```

**Etki:** Werkzeug'un `path` converter'ı `/` ve `..` içeren değerleri kabul eder. `curl --path-as-is "http://host/api/live/1/../../../../home/app/.env"` ya da `%2e%2e%2f` kodlamasıyla `Path` birleşimi kök dizinden çıkar. Endpoint **kimlik doğrulaması da istemiyor**. Windows geliştirme makinesinde `/dev/shm/...` sürücü köküne çözülür (`C:\dev\shm\...`) ve aynı traversal `C:\Users\...` altını okuyabilir. Sonuç: `.env`, `instance/database.db` (tüm parola hash'leri, DRM content key'leri düz metin) indirilebilir.

**Kök neden:** Kullanıcı girdisinin dosya sistemi yoluna doğrudan birleştirilmesi; whitelist yok; `send_from_directory`/`safe_join` kullanılmamış.

**Expert Fix:** Üç katmanlı savunma — (1) dosya adı **whitelist regex**, (2) `send_from_directory` (içeride `werkzeug.security.safe_join` kullanır, kök dışına çıkışta `NotFound` fırlatır), (3) segment erişimini imzalı **playback grant**'e bağlama (SEC-02'deki `UrlSigner`). Üretimde dosyayı Python'dan değil Nginx'ten servis edin (`X-Accel-Redirect`).

```python
# app/modules/live/http/hls_assets.py
import re
from pathlib import Path
from flask import Blueprint, abort, current_app, send_from_directory, make_response
from app.modules.live.http.grants import require_playback_grant

hls_assets_bp = Blueprint("hls_assets", __name__)

# Yalnızca transcoder'ın ürettiği dosya adları kabul edilir.
_ALLOWED_ASSET = re.compile(
    r"^(?:master|stream_[0-9])\.m3u8$"
    r"|^stream_[0-9]/data\d{6}\.ts$"
)

_M3U8 = "application/vnd.apple.mpegurl"
_TS = "video/mp2t"


@hls_assets_bp.get("/<int:channel_id>/<path:filename>")
@require_playback_grant(scope="live")          # imzalı, kullanıcıya bağlı, süreli erişim
def serve_hls_asset(channel_id: int, filename: str):
    if not _ALLOWED_ASSET.fullmatch(filename):
        abort(404)

    root = Path(current_app.config["HLS_OUTPUT_ROOT"]) / str(channel_id)
    is_playlist = filename.endswith(".m3u8")

    if current_app.config["HLS_SERVE_VIA_NGINX"]:
        # Nginx: location /_protected_hls/ { internal; alias /dev/shm/streams/; }
        resp = make_response("", 200)
        resp.headers["X-Accel-Redirect"] = f"/_protected_hls/{channel_id}/{filename}"
        resp.headers["Content-Type"] = _M3U8 if is_playlist else _TS
        return resp

    # send_from_directory → safe_join; kök dışına çıkış = 404 (NotFound)
    return send_from_directory(
        root,
        filename,
        mimetype=_M3U8 if is_playlist else _TS,
        conditional=True,
        max_age=1 if is_playlist else 30,   # playlist sık değişir, segment immutable
    )
```

```nginx
# deploy/nginx/hls.conf
location /_protected_hls/ {
    internal;                       # dışarıdan doğrudan erişilemez
    alias /dev/shm/streams/;
    types { application/vnd.apple.mpegurl m3u8; video/mp2t ts; }
    add_header Cache-Control "no-cache" always;
}
```

**Doğrulama (regresyon testi):**

```python
@pytest.mark.parametrize("evil", ["../../etc/passwd", "..%2f..%2fetc%2fpasswd", "stream_0/../../x.ts", "master.m3u8/../../a"])
def test_hls_asset_rejects_traversal(client, grant_qs, evil):
    r = client.get(f"/api/v1/live/1/{evil}?{grant_qs}")
    assert r.status_code == 404
```

---

#### SEC-02 · P0 · Kimliksiz, allowlist'siz, TLS doğrulamasız HLS proxy → tam SSRF

**Konum:** `app/routes/live.py::proxy_hls`, `app/services/stream_proxy.py::fetch_and_proxy`, `app/services/m3u_parser.py::fetch_and_parse`, `app/services/stream_validator.py`

```python
@live_bp.route('/proxy/hls', methods=['GET'])
def proxy_hls():
    url = request.args.get('url')
    result = VideoService().get_proxy_stream(url)        # requests.get(url, verify=False, allow_redirects=True)
```

**Etki:**
- Herhangi bir anonim istemci sunucuyu **açık proxy** olarak kullanabilir: `?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/` (cloud credential sızıntısı), `?url=http://localhost:5555/api/workers` (Flower), `?url=http://10.0.0.5:8080/...` (iç ağ tarama).
- `allow_redirects=True` → allowlist eklense bile 302 ile iç adrese yönlendirme.
- `verify=False` → MITM ile manipüle edilmiş playlist; playlist içindeki her URL tekrar proxy'den geçtiği için zincirleme SSRF.
- `resp.content` tüm yanıtı belleğe alır → büyük dosya ile bellek tükenmesi (DoS).
- Aynı desen `m3u_parser.fetch_and_parse` (herhangi bir login'li kullanıcı playlist ekleyerek tetikleyebilir — SEC-09) ve `StreamValidator.validate_url` içinde de var.

**Expert Fix:** Merkezî bir **Egress Gateway** (tek giriş noktası) + **imzalı proxy URL**. Proxy artık rastgele `url` parametresi kabul etmez; yalnızca backend'in `authorize` adımında **ürettiği ve imzaladığı** hedefleri açar. Rewriter da alt playlist/segment URL'lerini aynı imza ile yeniden imzalar.

```python
# app/core/security/signed_url.py
from __future__ import annotations
import base64, hashlib, hmac, time
from dataclasses import dataclass


class SignatureInvalidError(Exception):
    """İmza bozuk ya da başka bir subject için üretilmiş."""


class SignatureExpiredError(Exception):
    """İmza süresi dolmuş."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass(frozen=True, slots=True)
class UrlSigner:
    """HMAC-SHA256 ile hedef URL'yi bir subject'e (kullanıcıya) ve süreye bağlar."""
    secret: bytes
    default_ttl: int = 300

    def sign(self, target: str, subject: str, ttl: int | None = None) -> dict[str, str]:
        exp = int(time.time()) + (ttl or self.default_ttl)
        u = _b64e(target.encode())
        return {"u": u, "exp": str(exp), "sig": self._mac(u, subject, exp)}

    def verify(self, *, u: str, exp: str, sig: str, subject: str) -> str:
        try:
            exp_i = int(exp)
        except (TypeError, ValueError) as e:
            raise SignatureInvalidError("exp") from e
        if exp_i < int(time.time()):
            raise SignatureExpiredError()
        if not hmac.compare_digest(self._mac(u, subject, exp_i), sig or ""):
            raise SignatureInvalidError("sig")
        return _b64d(u).decode()

    def _mac(self, u: str, subject: str, exp: int) -> str:
        msg = f"{u}.{subject}.{exp}".encode()
        return _b64e(hmac.new(self.secret, msg, hashlib.sha256).digest())
```

```python
# app/core/security/egress.py
from __future__ import annotations
import ipaddress, socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import requests


class EgressDeniedError(Exception):
    def __init__(self, reason: str, url: str):
        super().__init__(f"egress denied ({reason}): {url}")
        self.reason, self.url = reason, url


@dataclass(frozen=True)
class EgressPolicy:
    allowed_schemes: frozenset[str] = frozenset({"http", "https"})
    allowed_ports: frozenset[int] = frozenset({80, 443, 8080, 8000, 8443})
    host_allowlist: frozenset[str] | None = None        # None = yalnızca IP kontrolü (admin import'larında)
    insecure_tls_hosts: frozenset[str] = frozenset()     # bilinçli istisna listesi, varsayılan boş
    max_redirects: int = 3
    connect_timeout: float = 3.05
    read_timeout: float = 10.0


@dataclass
class EgressGateway:
    """Uygulamanın dış dünyaya açılan TEK kapısı. requests'i doğrudan kullanmak yasaktır
    (import-linter sözleşmesi ile zorlanır — bkz. 4.13)."""
    policy: EgressPolicy
    session: requests.Session = field(default_factory=requests.Session)

    def check(self, url: str) -> None:
        p = urlsplit(url)
        if p.scheme not in self.policy.allowed_schemes:
            raise EgressDeniedError("scheme", url)
        host = (p.hostname or "").lower().rstrip(".")
        if not host:
            raise EgressDeniedError("no_host", url)
        port = p.port or (443 if p.scheme == "https" else 80)
        if port not in self.policy.allowed_ports:
            raise EgressDeniedError("port", url)
        if self.policy.host_allowlist is not None and not self._host_allowed(host):
            raise EgressDeniedError("host_not_allowlisted", url)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise EgressDeniedError("dns", url) from e
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:                       # private, loopback, link-local, metadata, CGNAT...
                raise EgressDeniedError(f"non_public_ip:{ip}", url)

    def get(self, url: str, *, stream: bool = True, headers: dict | None = None) -> requests.Response:
        """Redirect'leri ELLE takip eder; her hop tekrar doğrulanır."""
        current = url
        for _ in range(self.policy.max_redirects + 1):
            self.check(current)
            host = urlsplit(current).hostname or ""
            resp = self.session.get(
                current,
                headers=headers,
                stream=stream,
                allow_redirects=False,
                timeout=(self.policy.connect_timeout, self.policy.read_timeout),
                verify=host not in self.policy.insecure_tls_hosts,
            )
            if not resp.is_redirect:
                return resp
            location = resp.headers.get("Location", "")
            resp.close()
            current = urljoin(current, location)
        raise EgressDeniedError("too_many_redirects", url)

    def _host_allowed(self, host: str) -> bool:
        return any(host == h or host.endswith("." + h) for h in self.policy.host_allowlist or ())
```

> **DNS rebinding notu:** `check()` ile gerçek bağlantı arasında DNS cevabı değişebilir. Tam koruma için egress'i bir **forward proxy** (Smokescreen/Squid + ACL) üzerinden geçirin ya da `urllib3` için çözümlenen IP'yi sabitleyen özel bir `HTTPAdapter` kullanın. Uygulama katmanındaki bu kontrol, savunmanın ilk halkasıdır.

```python
# app/modules/live/services/hls_proxy.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import urlencode, urljoin

from app.core.security.egress import EgressGateway
from app.core.security.signed_url import UrlSigner

M3U8 = "application/vnd.apple.mpegurl"
MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status: int
    mimetype: str
    body: bytes | Iterator[bytes]


class PlaylistTooLargeError(Exception): ...


class HlsProxyService:
    def __init__(self, egress: EgressGateway, signer: UrlSigner, proxy_path: str):
        self._egress, self._signer, self._proxy_path = egress, signer, proxy_path

    def proxied_url(self, target: str, subject: str) -> str:
        return f"{self._proxy_path}?{urlencode(self._signer.sign(target, subject))}"

    def fetch(self, target: str, subject: str) -> ProxyResponse:
        resp = self._egress.get(target, stream=True)
        if resp.status_code != 200:
            resp.close()
            return ProxyResponse(502, "text/plain", b"upstream error")

        ctype = resp.headers.get("Content-Type", "")
        if self._is_playlist(target, ctype):
            raw = self._read_capped(resp)
            text = raw.decode("utf-8", errors="replace")
            return ProxyResponse(200, M3U8, self._rewrite(text, target, subject).encode())

        # Segment: belleğe ALMADAN akıt (streaming pass-through)
        def _iter() -> Iterator[bytes]:
            try:
                yield from resp.iter_content(CHUNK)
            finally:
                resp.close()
        return ProxyResponse(200, ctype or "video/mp2t", _iter())

    # ── yardımcılar ────────────────────────────────────────────────
    @staticmethod
    def _is_playlist(url: str, ctype: str) -> bool:
        return ".m3u8" in url.lower() or "mpegurl" in ctype.lower()

    @staticmethod
    def _read_capped(resp) -> bytes:
        buf = bytearray()
        for chunk in resp.iter_content(CHUNK):
            buf += chunk
            if len(buf) > MAX_PLAYLIST_BYTES:
                resp.close()
                raise PlaylistTooLargeError()
        return bytes(buf)

    def _rewrite(self, text: str, base: str, subject: str) -> str:
        out: list[str] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#EXT-X-KEY") or s.startswith("#EXT-X-MAP") or s.startswith("#EXT-X-MEDIA"):
                out.append(self._rewrite_uri_attr(s, base, subject))   # URI="..." attribute'larını da proxy'le
            elif s and not s.startswith("#"):
                out.append(self.proxied_url(urljoin(base, s), subject))
            else:
                out.append(s)
        return "\n".join(out)

    def _rewrite_uri_attr(self, line: str, base: str, subject: str) -> str:
        import re
        return re.sub(
            r'URI="([^"]+)"',
            lambda m: f'URI="{self.proxied_url(urljoin(base, m.group(1)), subject)}"',
            line,
        )
```

```python
# app/modules/live/http/proxy_routes.py
from flask import Blueprint, Response, request, stream_with_context
from flask_login import login_required, current_user
from app.core.security.signed_url import SignatureExpiredError, SignatureInvalidError
from app.core.security.egress import EgressDeniedError
from app.core.http.errors import ApiError
from app.kernel.container import resolve
from app.modules.live.services.hls_proxy import HlsProxyService

proxy_bp = Blueprint("live_proxy", __name__)


@proxy_bp.get("/proxy/hls")
@login_required
def proxy_hls():
    signer = resolve("url_signer")
    try:
        target = signer.verify(
            u=request.args.get("u", ""), exp=request.args.get("exp", ""),
            sig=request.args.get("sig", ""), subject=str(current_user.id),
        )
    except SignatureExpiredError:
        raise ApiError("PLAYBACK_GRANT_EXPIRED", 403)
    except SignatureInvalidError:
        raise ApiError("PLAYBACK_GRANT_INVALID", 403)

    try:
        result = resolve(HlsProxyService).fetch(target, subject=str(current_user.id))
    except EgressDeniedError as e:
        raise ApiError("EGRESS_DENIED", 403, details={"reason": e.reason})

    body = result.body if isinstance(result.body, bytes) else stream_with_context(result.body)
    resp = Response(body, status=result.status, mimetype=result.mimetype, direct_passthrough=True)
    resp.headers["Cache-Control"] = "no-store"
    return resp
```

`authorize` adımı artık ham `?url=` değil, `HlsProxyService.proxied_url(channel.hls_url, subject=user_id)` döndürür. Host allowlist'i, `LiveChannel.hls_url` ve `Channel.url` host'larından türetilen ve admin tarafından yönetilen `egress_allowed_hosts` tablosundan (Redis'te 60 sn cache) beslenir.

---

#### SEC-03 · P0 · RTMP `stream_key` kimliksiz uçta sızıyor

**Konum:** `app/models/live.py::LiveChannel.to_dict()` → `'stream_key': self.stream_key, # Only show to admin!`; `app/routes/live.py::get_live_channels()` kimlik doğrulaması olmadan `to_dict()` döndürüyor. Ayrıca `authorize_stream` iç yayın için `stream_url=/static/hls/{stream_key}.m3u8` döndürüyor ve endpoint de kimliksiz.

**Etki:** Yorumda "Only show to admin!" yazmasına rağmen herkes stream key'i alır → OBS ile `rtmp://server/live/<key>`'e publish edip yayını ele geçirebilir. Statik HLS yolu key ile aynı olduğu için playback URL'si de credential sızdırıyor.

**Kök neden:** Tek bir `to_dict()` ile hem admin hem public yanıt üretmek (serialization concern'ünün modele gömülmesi). Playback kimliği ile ingest kimliğinin aynı değer olması.

**Expert Fix:** (1) Model serialization'dan arındırılır; **audience'a özel DTO**'lar (`LiveChannelPublicDTO`, `LiveChannelAdminDTO`). (2) Ingest key ile playback id ayrıştırılır (`playback_id` = rastgele, public; `stream_key` = gizli, rotate edilebilir). (3) Key DB'de hash'lenmiş saklanır; RTMP sunucusunun `on_publish` callback'i hash karşılaştırır.

```python
# app/modules/live/schemas.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class LiveChannelPublicDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: int
    name: str
    description: str | None
    logo: str | None
    is_live: bool
    started_at: datetime | None
    # NOT: stream_key, hls_url, ingest_server ASLA burada yok.


class LiveChannelAdminDTO(LiveChannelPublicDTO):
    ingest_server: str | None
    stream_key_last4: str           # tam key yalnızca oluşturma/rotate anında bir kez gösterilir
    hls_url: str | None
```

```python
# app/modules/live/services/ingest_keys.py
import hashlib, hmac, secrets

class IngestKeyService:
    def __init__(self, pepper: bytes):
        self._pepper = pepper

    def issue(self) -> tuple[str, str]:
        """(plain_key, key_hash) döner. plain_key yalnızca bir kez admin'e gösterilir."""
        plain = secrets.token_urlsafe(24)
        return plain, self._hash(plain)

    def verify(self, presented: str, stored_hash: str) -> bool:
        return hmac.compare_digest(self._hash(presented), stored_hash)

    def _hash(self, key: str) -> str:
        return hmac.new(self._pepper, key.encode(), hashlib.sha256).hexdigest()
```

```python
# nginx-rtmp: on_publish http://backend/api/v1/live/ingest/on-publish;
@ingest_bp.post("/ingest/on-publish")
@require_internal_network            # yalnızca RTMP sunucusunun IP'si
def on_publish():
    key = request.form.get("name", "")
    channel = resolve(LiveChannelRepository).find_by_ingest_key(key, verifier=resolve(IngestKeyService))
    if channel is None:
        return "", 403                    # nginx-rtmp 4xx → publish reddedilir
    resolve(LiveChannelService).mark_live(channel.id)
    return "", 204
```

---

#### SEC-04 · P0 · Ödemesiz plan yükseltme ve imzasız webhook

**Konum:** `app/modules/billing/routes.py::upgrade_plan`, `::payment_webhook`; `app/modules/billing/services.py::upgrade_plan`, `::handle_webhook`

```python
def upgrade_plan(self, user_id, plan_id):
    ...
    sub.plan = plan_id; sub.status = 'active'; sub.expires_at = now + timedelta(days=30)
    sub.last_payment_at = now          # ← ödeme alınmadan "ödendi" yazılıyor
```

```python
@billing_bp.route('/webhook', methods=['POST'])
def payment_webhook():                 # ← kimlik/imza yok
    data = request.get_json()
    billing_service.handle_webhook(data.get('type'), data)
```

**Etki:** Login'li her kullanıcı `POST /api/billing/upgrade {"plan":"family"}` ile ücretsiz Family plan alır. Anonim herkes `POST /api/billing/webhook {"type":"payment.success","user_id":X}` ile herhangi bir aboneliği aktive edebilir ya da `subscription.expired` ile başkasının aboneliğini düşürebilir. `data` `None` ise `AttributeError` → 500.

**Kök neden:** "Ödeme sağlayıcısı" kavramının bir port olarak modellenmemesi; plan değişikliğinin **komut** (kullanıcı niyeti) ile **olay** (ödeme sağlayıcının onayı) olarak ayrıştırılmaması.

**Expert Fix:** Plan değişikliği iki aşamalı **saga**: `RequestPlanChange` → sağlayıcıda checkout oturumu → imzalı webhook `payment.succeeded` → `ActivatePlan` (idempotent) → outbox `subscription.changed`.

```python
# app/modules/billing/ports.py
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckoutSession:
    provider_session_id: str
    redirect_url: str


@dataclass(frozen=True)
class VerifiedWebhookEvent:
    provider_event_id: str
    type: str
    user_id: int
    plan_id: str | None
    occurred_at: int


class PaymentProvider(Protocol):
    name: str
    def create_checkout(self, *, user_id: int, plan_id: str, idempotency_key: str) -> CheckoutSession: ...
    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> VerifiedWebhookEvent: ...
```

```python
# app/modules/billing/adapters/hmac_webhook.py  — Stripe/iyzico tarzı imza doğrulama şablonu
import hashlib, hmac, json, time
from app.modules.billing.ports import VerifiedWebhookEvent


class WebhookSignatureError(Exception): ...
class WebhookReplayError(Exception): ...


def verify_hmac_webhook(raw_body: bytes, signature_header: str, secret: bytes,
                        tolerance_s: int = 300) -> VerifiedWebhookEvent:
    """Header formatı: 't=<unix>,v1=<hex>' . İmza = HMAC_SHA256(secret, f'{t}.' + body)."""
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        ts, sig = int(parts["t"]), parts["v1"]
    except (KeyError, ValueError) as e:
        raise WebhookSignatureError("malformed_header") from e

    if abs(time.time() - ts) > tolerance_s:
        raise WebhookReplayError("timestamp_outside_tolerance")

    expected = hmac.new(secret, f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise WebhookSignatureError("bad_signature")

    payload = json.loads(raw_body)
    return VerifiedWebhookEvent(
        provider_event_id=payload["id"], type=payload["type"],
        user_id=int(payload["data"]["user_id"]), plan_id=payload["data"].get("plan_id"),
        occurred_at=ts,
    )
```

```python
# app/modules/billing/http/routes.py
@billing_bp.post("/checkout")
@login_required
@idempotent(scope="billing.checkout")
def checkout():
    cmd = PlanChangeRequest.model_validate(request.get_json(silent=True) or {})
    session = resolve(BillingService).request_plan_change(current_user.id, cmd.plan_id,
                                                          idempotency_key=g.idempotency_key)
    return ok({"redirect_url": session.redirect_url}, status=201)


@billing_bp.post("/webhooks/<provider>")
def provider_webhook(provider: str):
    gateway = resolve_named(PaymentProvider, provider)          # bilinmeyen provider → UnknownProviderError (404)
    event = gateway.verify_webhook(raw_body=request.get_data(cache=False), headers=dict(request.headers))
    resolve(BillingService).apply_provider_event(event)          # ProcessedWebhook(provider, event_id) UNIQUE → idempotent
    return ok({"received": True})
```

```python
# app/modules/billing/services.py (ilgili kısım)
def apply_provider_event(self, event: VerifiedWebhookEvent) -> None:
    with self._uow:                                               # tek transaction
        if self._uow.webhooks.seen(event.provider_event_id):      # UNIQUE(provider, event_id)
            return
        self._uow.webhooks.mark_seen(event.provider_event_id)
        sub = self._uow.subscriptions.get_for_update(event.user_id)
        handler = self._EVENT_HANDLERS.get(event.type)
        if handler is None:
            raise UnhandledWebhookEventError(event.type)          # isimlendirilmiş hata; sessiz geçiş yok
        handler(self, sub, event)
        self._uow.outbox.add(SubscriptionChangedEvent.from_subscription(sub, self._catalog))
```

---

#### SEC-05 · P0 · Token tipi karışıklığı, askıya alınmış kullanıcının erişimi, request loader'da oturum açma

**Konum:** `app/__init__.py::load_user_from_request`, `app/services/auth_service.py::verify_token`, `app/core/middleware/profile_context.py`, `app/modules/profile/services.py`

**Kanıt ve etki:**
1. Access token ve profile token **aynı `SECRET_KEY` ve aynı algoritmayla** imzalanıyor; `verify_token` `typ` claim'ini kontrol etmiyor. 12 saatlik **profile token, Bearer access token olarak kabul ediliyor** → 1 saatlik oturum ömrü fiilen 12 saate uzuyor. Tersine, access token `X-Profile-Token` olarak verilirse decode başarılı, sonra `payload["profile_id"]` → `KeyError` → 500.
2. `request_loader` kullanıcının `is_active` alanını kontrol etmiyor; Flask-Login `request_loader` yolunda da `is_active` denetimi yapılmaz. Admin'in `suspend` ettiği kullanıcı mevcut JWT'si ile token süresi dolana kadar her şeye erişir; `modules/auth` login'i de `is_active` kontrolü yapmadığından yeni token da alabilir.
3. `request_loader` içinde `login_user(user)` çağrısı → stateless JWT isteğine **session cookie** yazılıyor. Sonuç: hibrit kimlik (cookie + bearer), `withCredentials: true` ile birleşince CSRF yüzeyi ve logout semantiği bozuk (token silinse de cookie yaşar).
4. Token iptali (revocation) yok: parola değişimi/şüpheli giriş sonrası verilen token'lar geçerli kalır.
5. `sub` integer — PyJWT ≥ 2.10'da `sub` string olmak zorunda; kütüphane yükseltildiğinde tüm doğrulamalar `InvalidSubjectError` ile düşer (zaman ayarlı bomba).

**Expert Fix:** Tek bir `TokenService`; her token'da `typ`, `aud`, `iss`, `jti`, `ver` (token version) ve string `sub`; doğrulamada **zorunlu claim listesi**; request loader stateless ve `is_active` + `token_version` kontrolü yapar.

```python
# app/modules/identity/services/tokens.py
from __future__ import annotations
import time, uuid
from dataclasses import dataclass
from enum import StrEnum

import jwt


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    PROFILE = "profile_ctx"
    PLAYBACK = "playback"


class TokenInvalidError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TokenClaims:
    sub: str
    typ: TokenType
    ver: int
    jti: str
    exp: int
    extra: dict


@dataclass(frozen=True)
class TokenService:
    signing_key: str
    issuer: str = "neotv"
    audience: str = "neotv-api"
    ttl: dict[TokenType, int] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.ttl is None:
            object.__setattr__(self, "ttl", {
                TokenType.ACCESS: 15 * 60,
                TokenType.REFRESH: 30 * 24 * 3600,
                TokenType.PROFILE: 12 * 3600,
                TokenType.PLAYBACK: 5 * 60,
            })

    def issue(self, *, sub: int | str, typ: TokenType, ver: int, **extra) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer, "aud": self.audience, "sub": str(sub), "typ": typ.value,
            "ver": ver, "jti": uuid.uuid4().hex, "iat": now, "nbf": now, "exp": now + self.ttl[typ],
            **extra,
        }
        return jwt.encode(payload, self.signing_key, algorithm="HS256")

    def verify(self, token: str, *, expected: TokenType) -> TokenClaims:
        try:
            p = jwt.decode(
                token, self.signing_key, algorithms=["HS256"],
                audience=self.audience, issuer=self.issuer, leeway=10,
                options={"require": ["exp", "iat", "sub", "typ", "ver", "jti", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenInvalidError("TOKEN_EXPIRED") from e
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError("TOKEN_INVALID") from e
        if p["typ"] != expected.value:
            raise TokenInvalidError("TOKEN_TYPE_MISMATCH")
        base = {"iss", "aud", "sub", "typ", "ver", "jti", "iat", "nbf", "exp"}
        return TokenClaims(sub=p["sub"], typ=TokenType(p["typ"]), ver=int(p["ver"]), jti=p["jti"],
                           exp=int(p["exp"]), extra={k: v for k, v in p.items() if k not in base})
```

```python
# app/modules/identity/http/request_loader.py
from flask_login import LoginManager
from app.modules.identity.services.tokens import TokenService, TokenType, TokenInvalidError


def install_request_loader(login_manager: LoginManager, tokens: TokenService, users) -> None:
    @login_manager.request_loader
    def _load(req):
        header = req.headers.get("Authorization", "")
        scheme, _, raw = header.partition(" ")
        if scheme.lower() != "bearer" or not raw:
            return None
        try:
            claims = tokens.verify(raw, expected=TokenType.ACCESS)
        except TokenInvalidError:
            return None
        user = users.get(int(claims.sub))
        if user is None or not user.is_active:          # askıya alınan kullanıcı ANINDA düşer
            return None
        if user.token_version != claims.ver:            # parola değişimi / "tüm cihazlardan çık" = ver += 1
            return None
        return user                                     # login_user() YOK — tamamen stateless
```

Ek olarak `SESSION_PROTECTION=None` ve `app.session_interface` için cookie yazmayan bir arayüz (veya Flask-Login yerine saf `g.current_user` + decorator) kullanılmalı; refresh token ise **httpOnly + Secure + SameSite=Strict** cookie'de, rotation + reuse detection ile (bkz. FE-04).

---

#### SEC-06 · P1 · Login akışında brute-force korumasının fiilen devre dışı olması ve kullanıcı numaralandırma

**Konum:** Canlıda kayıtlı olan `app/modules/auth/routes.py::login` rate limit ve `LoginAttemptGuard` içermiyor. Korumalı sürüm `app/routes/auth.py` **hiç register edilmiyor** (ölü kod). `check_username` herhangi bir limit olmadan kullanıcı adı varlığını döndürüyor ve RegisterPage onu her tuş vuruşunda (debounce ile) çağırıyor. `authenticate_user` kullanıcı yoksa hash karşılaştırması yapmadan döndüğü için **zamanlama farkı** ile de numaralandırma mümkün.

**Expert Fix:**

```python
# app/modules/identity/services/auth.py  (ilgili kısım)
from werkzeug.security import check_password_hash, generate_password_hash

_DUMMY_HASH = generate_password_hash("timing-equalizer")   # modül yüklenirken bir kez


class AuthenticationError(Exception):
    def __init__(self, code: str, retry_after: int | None = None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


def authenticate(self, username: str, password: str, *, captcha_token: str | None) -> User:
    key = username.strip().lower()
    delay = self._guard.get_required_delay_seconds(key)
    if delay:
        raise AuthenticationError("LOGIN_THROTTLED", retry_after=delay)
    if self._guard.requires_captcha(key) and not self._captcha.verify(captcha_token):
        raise AuthenticationError("CAPTCHA_REQUIRED")

    user = self._users.find_by_username(key)
    ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)  # sabit zaman
    if not (user and ok):
        self._guard.record_failure(key)
        raise AuthenticationError("INVALID_CREDENTIALS")
    if not user.is_active:
        raise AuthenticationError("ACCOUNT_SUSPENDED")
    self._guard.record_success(key)
    return user
```

`check_username` → `rate_limit_ip(rps=2, burst=5)` + yanıtı yalnızca kayıt formunda gösterin; giriş formunda asla.

---

#### SEC-07 · P0 · DRM: content key'in düz JSON ile teslimi, düz metin saklanması, lisans yenilemede IDOR

**Konum:** `app/services/drm_license_server.py::request_license` (`'content_key': drm_content.content_key` yanıtta), `app/modules/drm/models.py::DRMContent.content_key` (düz metin), `app/routes/drm.py::renew_license` → `DRMLicenseServer.renew_license(license_id, ip)` sahiplik kontrolü **yok**.

**Etki:** "Widevine/PlayReady/FairPlay" etiketleri kozmetik; gerçekte istemciye çıplak AES anahtarı veriliyor (ClearKey bile değil). Herhangi bir login'li kullanıcı başkasının `license_id`'sini yenileyebilir (lisans ömrünü sınırsız uzatma). DB sızıntısında (bkz. SEC-01) tüm içerik anahtarları açığa çıkar.

**Expert Fix:**
1. **Anahtarlar şifreli saklanır** (envelope encryption): `KeyVault` portu; geliştirmede Fernet, üretimde KMS/Vault Transit.
2. Gerçek DRM'de anahtar asla JSON'da dönmez; CDM'in `challenge`'ı alınır, lisans sunucusu (Widevine proxy / PallyCon / EZDRM / Axinom) imzalı lisans blob'u döner. AES-128 HLS için ise kısa ömürlü playback token'ı ile korunan **key delivery endpoint**'i kullanılır.
3. Tüm lisans operasyonları `user_id` ile scope'lanır.

```python
# app/modules/drm/ports.py
from typing import Protocol

class KeyVault(Protocol):
    def wrap(self, plaintext_key: bytes) -> str: ...
    def unwrap(self, wrapped: str) -> bytes: ...


# app/modules/drm/adapters/fernet_vault.py
from cryptography.fernet import Fernet, MultiFernet

class FernetKeyVault:
    """MultiFernet → anahtar rotasyonu: ilk anahtar ile şifreler, hepsiyle çözer."""
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("KeyVault requires at least one key (DRM_KEK_KEYS)")
        self._f = MultiFernet([Fernet(k) for k in keys])

    def wrap(self, plaintext_key: bytes) -> str:
        return self._f.encrypt(plaintext_key).decode()

    def unwrap(self, wrapped: str) -> bytes:
        return self._f.decrypt(wrapped.encode())
```

```python
# app/modules/drm/http/routes.py  — AES-128 HLS key delivery
@drm_bp.get("/keys/<key_id>")
@require_playback_grant(scope="vod")              # 5 dk'lık, user+content'e bağlı playback token
def deliver_key(key_id: str):
    grant = g.playback_grant
    content = resolve(DrmContentRepository).get_by_key_id(key_id)
    if content is None or content.content_id != grant.content_id:
        raise ApiError("KEY_NOT_FOUND", 404)
    key = resolve(KeyVault).unwrap(content.wrapped_key)
    resp = Response(key, mimetype="application/octet-stream")
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


@drm_bp.post("/license/renew")
@login_required
def renew_license():
    body = RenewLicenseRequest.model_validate(request.get_json(silent=True) or {})
    result = resolve(DrmLicenseService).renew(license_id=body.license_id, user_id=current_user.id,
                                              ip=request.remote_addr)          # user_id ile scope → IDOR yok
    return ok(result)
```

---

#### SEC-08 · P1 · Stream heartbeat IDOR ve `/play/<token>` ile origin sızıntısı

**Konum:** `app/services/stream_service.py::heartbeat(token)` — `StreamSession.query.filter_by(token=token)` kullanıcıya göre filtrelemiyor. `routes/stream.py::play_stream` kimliksiz ve `redirect(channel.url)` ile **upstream origin URL'sini** açığa çıkarıyor (token'ı ele geçiren herkes kalıcı origin URL'yi öğrenir).

**Fix:** `filter_by(token=token, user_id=current_user.id)`; `play` uç noktası redirect yerine SEC-02'deki imzalı proxy URL'sini döndürmeli, origin URL hiçbir istemci yanıtında yer almamalı (bkz. FE-02, `/api/channels` yanıtındaki `url` alanı da kaldırılmalı).

---

#### SEC-09 · P1 · Global playlist'leri her kullanıcı ekleyip silebiliyor; senkron SSRF tetikleyici

**Konum:** `app/routes/playlist.py` — tüm uçlar yalnızca `@login_required`. `Playlist` modelinde `owner_id` yok; yani sıradan bir kullanıcı tüm sistemin playlist'ini silebilir (`DELETE /api/playlists/<id>` cascade ile kanalları da siler) ve `POST` ile sunucuya keyfi URL fetch ettirebilir (SEC-02). Fetch istek thread'inde 30 sn bloklar (PERF-01).

**Fix:** Playlist'ler ya admin kapsamına (`@require_permission("catalog:write")`) alınmalı ya da `owner_id` ile kullanıcıya özel hâle getirilmeli; fetch işlemi `EgressGateway` üzerinden ve Celery task'ı olarak (`202 Accepted` + task id) yürütülmeli. Bkz. ASY-05.

---

#### SEC-10 · P1 · Hardcoded anti-leech secret ve MD5

**Konum:** `app/routes/live.py::generate_stream_token` → `secret = "super_secret_vod_key_123"`, `hashlib.md5(...)`, `==` ile karşılaştırma; ayrıca doğrulama satırları **yorum satırı** hâlinde (koruma tamamen kapalı).

**Fix:** Kaldırın; SEC-02'deki `UrlSigner` (HMAC-SHA256, `compare_digest`, secret config'ten) tek imzalama mekanizması olsun. İmza `subject=user_id` ile bağlandığı için IP bağlamaya gerek kalmaz (mobil ağlarda IP sık değişir; IP bağlama false-positive üretir).

---

#### SEC-11 · P1 · Altyapı yüzeyi: Redis/Flower açık, varsayılan parolalar, repoda secret

**Konum ve kanıt:**
- `docker-compose.yml`: Redis `6379:6379` ile host'a açık, parola/ACL yok; Flower `admin:secretflowerpass` varsayılan; `mher/flower` 5555 dışarı açık.
- `.env` repoda; `Scripts/database/init_admin.py` her çalıştırmada admin parolasını `admin123`'e **sıfırlıyor**; `Scripts/utils/debug_jwt.py` içinde gerçek bir JWT ve aday secret'lar hardcoded.
- Proje bir git deposu değil ve `.gitignore` yok; `instance/database.db`, `logs/`, `backend_debug.log` (820 KB) proje kökünde.

**Fix:**
```yaml
# docker-compose.yml (ilgili kısım)
redis:
  image: redis:7.4-alpine
  command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?REDIS_PASSWORD zorunlu}",
            "--maxmemory", "512mb", "--maxmemory-policy", "volatile-lru"]
  expose: ["6379"]            # ports: YOK — yalnızca iç ağ
flower:
  environment:
    FLOWER_BASIC_AUTH: "${FLOWER_USER:?}:${FLOWER_PASSWORD:?}"
  profiles: ["ops"]           # varsayılan up'ta başlamaz
```
> `maxmemory-policy allkeys-lru` **broker ile aynı Redis'te tehlikelidir**: bellek dolduğunda Celery kuyruk anahtarlarını da tahliye eder → task kaybı. Broker ve cache için ayrı Redis (ya da ayrı DB + `volatile-lru` ve tüm cache anahtarlarına TTL) kullanın.

`init_admin.py` → parolayı ortamdan ya da `getpass` ile alan, var olan admin'i **asla** sıfırlamayan bir `flask identity create-admin` CLI komutuyla değiştirilmeli. Tüm secret'lar rotate edilmeli.

#### SEC-12 · P0 · Profil PIN doğrulaması her zaman `True`

**Konum:** `app/modules/profile/services.py::_verify_pin`

```python
def _verify_pin(self, profile, pin):
    if pin is None: return False
    # return verify_hash(pin, profile.pin_hash)
    return True                                   # ← her PIN geçerli
```

**Etki:** Çocuk profili kilidi / ebeveyn kontrolü tamamen göstermelik; deneme sayacı da hiçbir zaman artmıyor. Fix RT-05 içinde (`check_password_hash` + atomik sayaç).

---

### 3.B Çalışma Zamanı Kırılmaları (Runtime Breakers)

#### RT-01 · P0 · Transcoder paketi import anında çöküyor

**Konum:** `app/services/transcoder/stream_manager.py` → `from app.core.config import settings` — **`app/core/config.py` mevcut değil.** `app/services/transcoder/__init__.py` bu modülü re-export ettiği için paketin herhangi bir yerinden import `ModuleNotFoundError` verir. Ek olarak `app/tasks/transcoder_tasks.py` `psutil` import ediyor; `requirements.txt`'te yok.

**Etki:** `GET /api/live/<id>/master.m3u8` → `stream_orchestrator` lazy import'u → **500**. Celery worker transcoder task modülünü import edemez.

**Fix:** `settings` tek bir tipli konfigürasyon nesnesinden gelmeli (CFG-01'deki `Settings`), Redis client'ı import anında değil **container**'dan çözülmeli:

```python
# app/modules/live/services/orchestrator.py
class StreamOrchestrator:
    STREAM_KEY_PREFIX = "abr_stream:"

    def __init__(self, redis, dispatcher: "TranscodeDispatcher", settings: "Settings"):
        self._redis, self._dispatch, self._settings = redis, dispatcher, settings
    ...
# Kayıt: container.register(StreamOrchestrator, factory=lambda c: StreamOrchestrator(
#     c.resolve("redis_state"), c.resolve(TranscodeDispatcher), c.resolve(Settings)))
```

`requirements` → `psutil` eklenir (ya da Grim Reaper process tablosu yerine Redis'te tutulan PGID listesi + `os.killpg` ile yazılır; bkz. STR-03).

---

#### RT-02 · P0 · `/api/favorites` ve `/api/history` `AttributeError` ile düşüyor

**Konum:** `app/routes/main.py::get_favorites` → `fav.channel.id`; `::get_history` → `item.channel.name`. `Favorite` ve `WatchHistory` modellerinde `channel` relationship'i **yok** ("Rule 2 — Soft References" gereği kaldırılmış, ama tüketici kod güncellenmemiş). Ayrıca iki uç da `@require_profile_context` gerektiriyor (RT-05).

**Fix:** Soft-reference politikası korunarak **toplu (batch) okuma** ile N+1 olmadan çözülür; kanal okuma, katalog modülünün public port'u üzerinden yapılır (modül sınırı ihlal edilmez):

```python
# app/modules/library/services.py
class LibraryService:
    def __init__(self, favorites: FavoriteRepository, catalog: CatalogReadPort):
        self._favorites, self._catalog = favorites, catalog

    def list_favorites(self, profile_id: int) -> list[ChannelCardDTO]:
        fav_ids = self._favorites.channel_ids_for(profile_id)            # tek sorgu
        cards = self._catalog.get_cards(fav_ids)                         # tek sorgu: WHERE id IN (...)
        by_id = {c.id: c for c in cards}
        return [by_id[i] for i in fav_ids if i in by_id]                 # silinmiş kanallar sessizce düşer, sıra korunur
```

```python
# app/modules/catalog/ports.py  — diğer modüllerin katalogu okuyabileceği TEK kapı
from typing import Protocol, Sequence

class CatalogReadPort(Protocol):
    def get_cards(self, channel_ids: Sequence[int]) -> list["ChannelCardDTO"]: ...
    def exists(self, channel_id: int) -> bool: ...
```

---

#### RT-03 · P0 · `GET /api/playlists/` `TypeError` ile düşüyor

**Konum:** `app/routes/playlist.py::get_playlists` → `len(p.channels)`; `Playlist.channels` `lazy='dynamic'` (bir `AppenderQuery`; `__len__` yok). Ayrıca her playlist için ayrı sorgu (N+1).

**Fix:**

```python
from sqlalchemy import func, select

def list_playlists_with_counts(session) -> list[dict]:
    stmt = (
        select(Playlist.id, Playlist.name, func.count(Channel.id).label("channel_count"))
        .outerjoin(Channel, Channel.playlist_id == Playlist.id)
        .group_by(Playlist.id, Playlist.name)
        .order_by(Playlist.id)
    )
    return [dict(r._mapping) for r in session.execute(stmt)]
```

> Not: `url` alanı (çoğu IPTV sağlayıcısında `username/password` içerir) liste yanıtından çıkarılmalı.

---

#### RT-04 · P0 · `/api/recommendations/trending` her istekte 500

**Konum:** `app/routes/recommendations.py::get_trending` → `trending_guard.get_or_compute(compute_fn=lambda: RecommendationService.get_trending(...))`. `get_trending` **ORM `Channel` nesneleri** döndürüyor; `CacheStampedeGuard` `json.dumps(fresh)` yapıyor → `TypeError: Object of type Channel is not JSON serializable`. Cache hiçbir zaman dolmadığı için her istek yeniden hesaplar ve düşer. Ek olarak cache anahtarı `"trending:global"` sabit; `limit` ve `hours` parametreleri anahtar dışı (farklı parametreler aynı cache'i paylaşır).

**Kök neden:** Cache katmanının **serileştirilebilir DTO** sözleşmesi yok; servis katmanı ORM nesnesi sızdırıyor.

**Fix:** Servisler yalnızca DTO döndürür; cache guard bir `Codec` ile tiplenir; anahtar parametreleri içerir.

```python
# app/core/cache/stampede.py  (imza değişikliği — geriye uyumlu default codec ile)
from typing import Callable, Generic, TypeVar
T = TypeVar("T")

class JsonCodec(Generic[T]):
    def __init__(self, encode: Callable[[T], object], decode: Callable[[object], T]):
        self.encode, self.decode = encode, decode

# app/modules/recommendations/services.py
@dataclass(frozen=True, slots=True)
class TrendingItem:
    channel: ChannelCardDTO
    play_count: int

def get_trending(self, limit: int, hours: int) -> list[TrendingItem]:
    since = utcnow() - timedelta(hours=hours)
    rows = self._events.top_played_since(since, limit)               # [(channel_id, count)]
    cards = {c.id: c for c in self._catalog.get_cards([cid for cid, _ in rows])}   # N+1 yok
    return [TrendingItem(cards[cid], cnt) for cid, cnt in rows if cid in cards]

# route
limit = min(request.args.get("limit", 10, type=int), 50)
hours = min(request.args.get("hours", 24, type=int), 168)
items = trending_guard.get_or_compute(
    key=f"trending:v2:{hours}:{limit}",
    compute_fn=lambda: [asdict(i) for i in svc.get_trending(limit, hours)],
)
```

---

#### RT-05 · P0 · Profil bağlamı zorunlu, ama profil sistemi yok

**Konum:** `@require_profile_context` şu uçlarda zorunlu: `/api/stream/authorize`, `/api/toggle_favorite/*`, `/api/favorites`, `/api/history`, `/api/recommendations/for-you|continue|recently-watched`. `X-Profile-Token` üreten **hiçbir endpoint yok**; `profiles` tablosu/modeli yok (`zzzz_*` migration'ı var olmayan tabloya index ekliyor); frontend bu header'ı hiç göndermiyor.

**Etki:** Bu uçların tamamı deterministik olarak `400 MISSING_PROFILE_TOKEN`. Ana sayfadaki 4 öneri satırından 3'ü boş; VOD yetkilendirme (`SecurePlayer`) imkânsız — bu yüzden frontend yetkilendirmeyi tamamen atlamaya başlamış (FE-02).

**Expert Fix:** `profile` modülünü tamamlamak + **geriye uyumlu geçiş modu**. `PROFILE_CONTEXT_MODE`:
- `default_profile` (geçiş): header yoksa kullanıcının varsayılan profili otomatik çözülür/yaratılır → mevcut frontend kırılmaz.
- `strict` (hedef): header zorunlu.

```python
# app/modules/profile/models.py
from sqlalchemy import text
from app.kernel.db import db, utcnow_column


class Profile(db.Model):
    __tablename__ = "profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)          # soft FK (modül sınırı)
    name = db.Column(db.String(40), nullable=False)
    is_kids = db.Column(db.Boolean, nullable=False, default=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    pin_hash = db.Column(db.String(255))
    avatar = db.Column(db.String(64))
    created_at = utcnow_column()

    __table_args__ = (
        db.Index("ux_profiles_user_default", "user_id", unique=True,
                 postgresql_where=text("is_default"), sqlite_where=text("is_default = 1")),
        db.UniqueConstraint("user_id", "name", name="uq_profiles_user_name"),
    )
```

```python
# app/modules/profile/services.py
from werkzeug.security import check_password_hash


class ProfileNotOwnedError(Exception): ...
class PinRequiredError(Exception): ...
class PinInvalidError(Exception): ...
class PinLockedError(Exception):
    def __init__(self, retry_after: int):
        super().__init__("PIN_LOCKED"); self.retry_after = retry_after


_INCR_WITH_TTL = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


class ProfileContextService:
    MAX_ATTEMPTS, LOCK_SECONDS = 5, 900

    def __init__(self, repo, tokens: "TokenService", redis):
        self._repo, self._tokens, self._redis = repo, tokens, redis
        self._incr = redis.register_script(_INCR_WITH_TTL)

    def select(self, *, user_id: int, profile_id: int, pin: str | None, token_version: int) -> str:
        profile = self._repo.get(profile_id)
        if profile is None or profile.user_id != user_id:
            raise ProfileNotOwnedError()
        if profile.pin_hash:
            key = f"pin_attempts:{profile_id}"
            if int(self._redis.get(key) or 0) >= self.MAX_ATTEMPTS:
                raise PinLockedError(retry_after=int(self._redis.ttl(key) or self.LOCK_SECONDS))
            if pin is None:
                raise PinRequiredError()
            if not check_password_hash(profile.pin_hash, pin):
                self._incr(keys=[key], args=[self.LOCK_SECONDS])      # INCR+EXPIRE atomik
                raise PinInvalidError()
            self._redis.delete(key)
        return self._tokens.issue(sub=user_id, typ=TokenType.PROFILE, ver=token_version,
                                  profile_id=profile.id, is_kids=profile.is_kids)

    def default_for(self, user_id: int) -> "Profile":
        return self._repo.get_or_create_default(user_id)              # ON CONFLICT DO NOTHING + SELECT
```

```python
# app/core/http/profile_context.py
import functools
from flask import current_app, g, request
from flask_login import current_user
from app.core.http.errors import ApiError
from app.kernel.container import resolve
from app.modules.identity.services.tokens import TokenInvalidError, TokenService, TokenType


@dataclass(frozen=True, slots=True)
class ProfileContext:
    profile_id: int
    user_id: int
    is_kids: bool


def require_profile_context(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        raw = request.headers.get("X-Profile-Token")
        if raw:
            try:
                c = resolve(TokenService).verify(raw, expected=TokenType.PROFILE)
            except TokenInvalidError as e:
                raise ApiError(f"PROFILE_{e.code}", 401)
            if c.sub != str(current_user.id):
                raise ApiError("PROFILE_MISMATCH", 403)
            g.current_profile = ProfileContext(int(c.extra["profile_id"]), current_user.id,
                                               bool(c.extra.get("is_kids", False)))
        elif current_app.config["PROFILE_CONTEXT_MODE"] == "default_profile":
            p = resolve("profile_service").default_for(current_user.id)
            g.current_profile = ProfileContext(p.id, current_user.id, p.is_kids)
        else:
            raise ApiError("MISSING_PROFILE_TOKEN", 400)
        return fn(*args, **kwargs)
    return wrapper
```

Endpoint'ler: `GET /api/v1/profiles`, `POST /api/v1/profiles`, `POST /api/v1/profiles/<id>/select` → `{profile_token}`. Frontend axios interceptor'ı `X-Profile-Token`'ı ekler (FE-04).

---

#### RT-06 · P0 · Aynı tarayıcıdan ikinci kullanıcı giriş yapamıyor

**Konum:** `app/models/device.py` → `device_id = db.Column(db.String(128), unique=True)` (**global unique**) ve

```python
def generate_device_id(user_agent, ip_address, extra_fingerprint=None):
    raw = f"{user_agent}:{extra_fingerprint or ''}"        # user_id YOK, ip kullanılmıyor
```

Frontend login'de `device_fingerprint` göndermiyor → `raw = "<UA>:"`. Aynı Chrome sürümündeki iki farklı kullanıcı **aynı device_id**'yi üretir. Adapter `filter_by(user_id=..., device_id=...)` ile arar → bulamaz → `INSERT` → **`IntegrityError` (UNIQUE device.device_id) → 500**. Aynı ofisteki/evdeki tüm aynı-tarayıcı kullanıcıları için login kırık.

**Fix:** (1) Benzersizlik `(user_id, device_id)`; (2) cihaz kimliği istemcide **rastgele ve kalıcı** üretilir (`crypto.randomUUID()` → `localStorage`), her istekte `X-Device-ID` ile gelir; (3) sunucu bunu kullanıcıya bağlı HMAC ile saklar (ham değeri saklamaz); (4) upsert atomik.

```python
# app/modules/devices/services.py
import hashlib, hmac
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


class DeviceRegistry:
    def __init__(self, session, pepper: bytes, ua_parser):
        self._s, self._pepper, self._ua = session, pepper, ua_parser

    def device_key(self, user_id: int, client_device_id: str | None, user_agent: str) -> str:
        basis = f"id:{client_device_id}" if client_device_id else f"ua:{user_agent}"
        return hmac.new(self._pepper, f"{user_id}|{basis}".encode(), hashlib.sha256).hexdigest()[:40]

    def touch(self, *, user_id: int, client_device_id: str | None, user_agent: str, ip: str) -> int:
        key = self.device_key(user_id, client_device_id, user_agent)
        info = self._ua.parse(user_agent)
        insert = pg_insert if self._s.bind.dialect.name == "postgresql" else sqlite_insert
        stmt = insert(Device).values(
            user_id=user_id, device_id=key, device_name=info.name, device_type=info.type,
            browser=info.browser, os=info.os, last_ip=ip, last_seen=utcnow(), login_count=1, is_active=True,
        ).on_conflict_do_update(
            index_elements=["user_id", "device_id"],
            set_={"last_seen": utcnow(), "last_ip": ip, "is_active": True,
                  "login_count": Device.login_count + 1},
        ).returning(Device.id)
        return self._s.execute(stmt).scalar_one()
```

Migration RT-07'de.

---

#### RT-07 · P0 · Migration zinciri modellerle uyumsuz ve kırık

**Kanıt:**
1. `migrations/versions/zzzz_add_unique_default_profile_constraint.py`: `revision` ve `down_revision` değişkenleri **tanımlı değil** → Alembic script dizinini yüklerken hata verir; **hiçbir** `flask db upgrade/downgrade/history` komutu çalışmaz. Ayrıca var olmayan `profiles` tablosuna index ekliyor.
2. Model `billing_subscriptions` tablosunu kullanıyor; migration `subscription` tablosu yaratıyor → billing uçları `no such table: billing_subscriptions`.
3. `shared_outbox_events`, `shared_processed_event_log` için migration yok → kayıt (register) ve plan değişikliği `INSERT` sırasında düşer.
4. "Soft FK" kuralıyla modellerden FK'ler kaldırılmış ama DB'de FK'ler duruyor → `flask db migrate` autogenerate her seferinde FK drop önerir (şema sürüklenmesi / drift).
5. `Scripts/batch/fix_db.bat` **migrations klasörünü ve veritabanını siler** ve sıfırdan `db init` yapar — üretimde veri kaybı tetikleyicisi.

**Fix — tek, deterministik, veri koruyan revision:**

```python
# migrations/versions/b7f1c2a9e001_modular_tables_and_device_scope.py
"""billing rename, outbox/inbox, profiles, device scope, token_version

Revision ID: b7f1c2a9e001
Revises: d88aab850aa0
"""
from alembic import op
import sqlalchemy as sa

revision = "b7f1c2a9e001"
down_revision = "d88aab850aa0"
branch_labels = None
depends_on = None

_SQLITE_NC = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"

    # 1) subscription → billing_subscriptions (VERİ KORUNUR)
    op.rename_table("subscription", "billing_subscriptions")

    # 2) Outbox / Inbox
    op.create_table(
        "shared_outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_outbox_status_available", "shared_outbox_events", ["status", "available_at"])
    op.create_table(
        "shared_processed_event_log",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("consumer_name", sa.String(100), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 3) Profiles (+ kısmi unique index: kullanıcı başına tek default)
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("is_kids", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("pin_hash", sa.String(255)),
        sa.Column("avatar", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_profiles_user_name"),
    )
    op.create_index("ux_profiles_user_default", "profiles", ["user_id"], unique=True,
                    postgresql_where=sa.text("is_default"), sqlite_where=sa.text("is_default = 1"))

    # 4) Device: global unique → (user_id, device_id)
    if sqlite:
        with op.batch_alter_table("device", recreate="always", naming_convention=_SQLITE_NC) as b:
            b.drop_constraint("uq_device_device_id", type_="unique")
            b.create_unique_constraint("uq_device_user_device", ["user_id", "device_id"])
    else:
        op.drop_constraint("device_device_id_key", "device", type_="unique")
        op.create_unique_constraint("uq_device_user_device", "device", ["user_id", "device_id"])

    # 5) Token revocation
    with op.batch_alter_table("user") as b:
        b.add_column(sa.Column("token_version", sa.Integer, nullable=False, server_default="1"))


def downgrade():
    with op.batch_alter_table("user") as b:
        b.drop_column("token_version")
    # device kısıtı geri alınmaz: global unique'e dönüş veri kaybı riski taşır → bilinçli tek yön
    op.drop_index("ux_profiles_user_default", table_name="profiles")
    op.drop_table("profiles")
    op.drop_table("shared_processed_event_log")
    op.drop_index("ix_outbox_status_available", table_name="shared_outbox_events")
    op.drop_table("shared_outbox_events")
    op.rename_table("billing_subscriptions", "subscription")
```

**Ek kurallar:**
- `zzzz_*.py` silinir.
- `db.Model.metadata` için **naming convention** zorunlu hâle getirilir (bundan sonraki tüm constraint'ler isimli olur, SQLite batch işlemleri deterministikleşir):
  ```python
  # app/kernel/db.py
  from flask_sqlalchemy import SQLAlchemy
  from sqlalchemy import MetaData
  NAMING = {"ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}
  db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING))
  ```
- Soft FK kararı **açıkça** verilir: modül sınırını geçen referanslarda FK **yok** (migration ile kaldırılır), modül içinde FK **var**. `include_object` hook'u ile autogenerate'in modül-dışı FK'leri önermesi engellenir.
- `fix_db.bat` silinir; yerine `flask db upgrade` + `flask identity create-admin`.

---

#### RT-08 · P1 · Başlatıcılar kırık ve sistem genelinde process öldürüyor

**Konum:** `start.py`
- `subprocess.run([python_exe, "seed_live.py"])` ve `start_process([python_exe, "ingest.py"])` — bu dosyalar `Scripts/database/` ve `Scripts/streaming/` altına taşınmış; çıktı `DEVNULL`'a gittiği için hata **görünmez**.
- `cleanup()` → `taskkill /F /IM node.exe /T` ve `wmic ... where name='python.exe' and processid!=<pid> delete`: kullanıcının makinesindeki **tüm** Node ve Python süreçlerini (VS Code Pylance, başka projeler, Jupyter) öldürür. `wmic` Windows 11 24H2'de kaldırıldı.
- Redis ve Celery worker başlatılmıyor → Redis'e bağımlı tüm uçlar 500 (RT-09).
- `launch.py` önce `.venv/bin/python.exe` arıyor (Windows'ta yol `.venv/Scripts/python.exe`); `.vscode/tasks.json` da `.venv/bin/python.exe` kullanıyor.

**Fix:** Başlatıcı yalnızca **kendi başlattığı** process ağacını yönetmeli. Tek, cross-platform bir `devctl` (veya `honcho`/`Procfile.dev`) yaklaşımı:

```python
# tools/devctl.py
from __future__ import annotations
import os, signal, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable                                  # venv'den çağrılması beklenir; aramaz
IS_WIN = os.name == "nt"


@dataclass(frozen=True)
class Proc:
    name: str
    argv: list[str]
    cwd: Path = ROOT
    health_port: int | None = None


PROCS = [
    Proc("api", [PY, "-m", "flask", "--app", "app.wsgi:app", "run", "--port", "5000"], health_port=5000),
    Proc("worker", [PY, "-m", "celery", "-A", "app.wsgi:celery", "worker", "-Q", "default,playlist,epg",
                    "-P", "solo" if IS_WIN else "prefork", "-l", "info"]),
    Proc("beat", [PY, "-m", "celery", "-A", "app.wsgi:celery", "beat", "-l", "info"]),
    Proc("web", ["npm.cmd" if IS_WIN else "npm", "run", "dev"], cwd=ROOT / "frontend", health_port=5173),
]


def spawn(p: Proc, logdir: Path) -> subprocess.Popen:
    logdir.mkdir(exist_ok=True)
    kw: dict = {"cwd": p.cwd, "stdout": open(logdir / f"{p.name}.log", "ab"), "stderr": subprocess.STDOUT}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True               # kendi process group'u → yalnızca onu öldürürüz
    return subprocess.Popen(p.argv, **kw)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)  # YALNIZCA kendi ağacımız
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    procs = {p.name: spawn(p, ROOT / "logs") for p in PROCS}
    try:
        while all(pr.poll() is None for pr in procs.values()):
            time.sleep(1)
        dead = [n for n, pr in procs.items() if pr.poll() is not None]
        print(f"[devctl] süreç sonlandı: {dead} — logs/<ad>.log dosyasına bakın", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for pr in procs.values():
            stop(pr)


if __name__ == "__main__":
    raise SystemExit(main())
```

Redis Windows'ta Docker Desktop/WSL ile (`docker compose up redis`) başlatılır; `devctl` başlangıçta Redis'e `PING` atıp yoksa **isimlendirilmiş bir hata** ile durur (`RedisUnavailableError: REDIS_URL=... erişilemiyor`).

---

#### RT-09 · P1 · Redis kesintisi katalog listesini düşürüyor (failure domain karışması)

**Konum:** `app/routes/main.py::get_channels` → `channels_breaker.call(fn=_fetch_base_catalog, fallback=_fallback_to_base_catalog)`.
- `_fetch_base_catalog` DB'den okuduktan sonra **Redis'e snapshot yazıyor**. Redis kapalıysa `ConnectionError` → breaker bunu **DB hatası** sayar → 5 istekte devre açılır → sağlıklı DB'ye rağmen kullanıcılar "degraded" görür.
- Fallback da Redis'ten okuyor → Redis kapalıyken fallback da patlar → **500**.
- `CircuitBreaker.call` fallback `None` ise `None` döndürür; çağıran `result.get(...)` → `AttributeError`.

**Fix:** Her dış bağımlılığa **ayrı breaker**; snapshot yazımı **best-effort** ve breaker dışı; fallback zinciri kendi içinde hata toleranslı. Geliştirilmiş breaker RES-01'de.

```python
def get_channels():
    q = CatalogQuery.from_request(request.args)
    try:
        page = db_breaker.call(lambda: catalog.page(q))
    except (CircuitOpenError, SQLAlchemyError):
        snap = best_effort(lambda: snapshots.read("catalog:page1"), default=None, log="catalog.snapshot.read")
        return ok(snap.with_degraded("CATALOG_DEGRADED") if snap else CatalogPage.empty_degraded())
    if q.is_first_page_unfiltered:
        best_effort(lambda: snapshots.write("catalog:page1", page, ttl=86400), log="catalog.snapshot.write")
    return ok(personalize(page, g.current_profile))
```

```python
# app/core/resilience/best_effort.py
import logging
from typing import Callable, TypeVar
T = TypeVar("T")
_log = logging.getLogger("resilience.best_effort")

def best_effort(fn: Callable[[], T], *, default: T | None = None, log: str) -> T | None:
    """Yan etki/optimizasyon niteliğindeki işlemler için: hata ana akışı ASLA kesmez ama ASLA sessiz de değildir."""
    try:
        return fn()
    except Exception:
        _log.warning("best_effort.failed op=%s", log, exc_info=True)
        return default
```

---

### 3.C Veri Tutarlılığı, Transaction ve Eşzamanlılık

#### DATA-01 · P0 · Eşzamanlı stream limiti yarış koşuluna açık; oturumlar hiç serbest bırakılmıyor

**Konum:** `app/services/stream_service.py::authorize_stream` — `COUNT(*)` → karşılaştırma → `INSERT`, kilit yok. Rate limit 3 rps/burst 5 olduğu için aynı kullanıcı paralel 5 istekle limiti aşabilir. Redis Lua ile atomik çalışan `StreamConcurrencyGuard` **yazılmış ama yalnızca hata gövdesindeki sayaç için kullanılıyor**. Oturum **release** endpoint'i yok; ilk token 30 dk geçerli. Limit=1 olan kullanıcı player'ı kapatıp başka cihazda açtığında 30 dakika boyunca `STREAM_LIMIT_EXCEEDED` alır.

**Fix:** Kaynak gerçeklik Redis ZSET (atomik, heartbeat ile kayan pencere); DB oturumu yalnızca **audit** kaydı. Release açık uç + `navigator.sendBeacon`.

```python
# app/modules/playback/services/sessions.py
class StreamLimitExceededError(Exception):
    def __init__(self, active: int, limit: int):
        super().__init__("STREAM_LIMIT_EXCEEDED"); self.active, self.limit = active, limit


class PlaybackSessionService:
    HEARTBEAT_WINDOW = 30            # sn — istemci 10 sn'de bir heartbeat atar

    def __init__(self, guard: "StreamConcurrencyGuard", audit: "SessionAuditRepository",
                 entitlements: "EntitlementService"):
        self._guard, self._audit, self._ent = guard, audit, entitlements

    def open(self, *, user_id: int, profile_id: int, content_ref: str, device_key: str, ip: str) -> str:
        limit = self._ent.for_user(user_id).max_streams
        granted, token = self._guard.acquire_slot(user_id, limit, device_key)
        if not granted:
            raise StreamLimitExceededError(self._guard.get_active_count(user_id), limit)
        self._audit.record_open(token=token, user_id=user_id, profile_id=profile_id,
                                content_ref=content_ref, ip=ip)
        return token

    def heartbeat(self, *, user_id: int, token: str) -> None:
        if not self._guard.heartbeat(user_id, token):        # user_id ile scope → IDOR yok (SEC-08)
            raise SessionExpiredError()

    def close(self, *, user_id: int, token: str) -> None:
        self._guard.release_slot(user_id, token)
        self._audit.record_close(token=token)
```

```js
// frontend: player kapatılırken / sekme kapanırken slotu serbest bırak
const release = () => navigator.sendBeacon('/api/v1/playback/sessions/release',
  new Blob([JSON.stringify({ token })], { type: 'application/json' }));
window.addEventListener('pagehide', release);
```

> `sendBeacon` Authorization header gönderemez; release ucu `token`'ın kendisini (Redis'te user'a bağlı, tahmin edilemez) yetki olarak kabul eder ve `user_id`'yi ZSET üyeliğinden çözer. Bu nedenle release, kimliksiz ama **token-scoped** bir uçtur.

---

#### DATA-02 · P1 · DRM eşzamanlılık kontrolü PostgreSQL'de hata, SQLite'ta etkisiz

**Konum:** `app/services/drm_guard.py::_check_concurrent_limit` → `.with_for_update(skip_locked=True).count()`.
- PostgreSQL: `SELECT count(*) ... FOR UPDATE` → **"FOR UPDATE is not allowed with aggregate functions"** hatası.
- `skip_locked=True` kilitli satırları **sayımdan çıkarır** → paralel isteklerde sayım eksik → limit aşılır (korumanın tam tersi).
- SQLite: `FOR UPDATE` yok sayılır; koruma sıfır.
- Ayrıca DRM limiti `DRMPolicy.max_concurrent_streams`'den, stream limiti `User.max_connections`'tan geliyor (DATA-03).

**Fix:** DRM lisansı ayrı bir slot havuzu değil, **aynı playback oturumunun** bir parçası olmalı: lisans yalnızca geçerli bir `PlaybackSession` token'ı ile verilir. DB tarafında sıralama gerekiyorsa kullanıcı başına **transaction-scoped advisory lock**:

```python
from sqlalchemy import text

def lock_user_scope(session, user_id: int) -> None:
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:ns, :uid)"), {"ns": 42, "uid": user_id})
    # SQLite: tek yazıcı modeli zaten serileştirir (BEGIN IMMEDIATE ile) — bkz. DATA-08
```

---

#### DATA-03 · P1 · Plan limitleri üç farklı yerde tanımlı (single source of truth ihlali)

**Kanıt:**
- `modules/billing/services.py::PLANS[*].max_connections` (free=1, personal=2, duo=3, family=5)
- `modules/billing/models.py::Subscription.get_connection_limit()` (aynı + `enterprise: 10`)
- `services/billing_service.py::PLANS` (legacy kopya)
- `DRMPolicy.max_concurrent_streams` + `drm_policy_resolver.create_default_policy` (`user.max_connections`)
- `User.max_connections` / `User.subscription_plan` (outbox ile eventual-consistent kopya — ve outbox çalışmadığı için **hiç güncellenmiyor**, ASY-01)

**Fix — Entitlement Catalog:** Planlar **veri** olarak tek yerde; diğer her şey ondan türetilir. `User` üzerindeki kopyalar kaldırılır (ya da yalnızca read-model cache olarak tutulur).

```python
# app/modules/billing/catalog.py
from dataclasses import dataclass
from enum import StrEnum


class PlanId(StrEnum):
    FREE = "free"; PERSONAL = "personal"; DUO = "duo"; FAMILY = "family"


@dataclass(frozen=True, slots=True)
class Entitlements:
    max_streams: int
    max_profiles: int
    max_resolution: str            # "480p" | "1080p" | "2160p"
    offline_downloads: bool
    ads: bool


@dataclass(frozen=True, slots=True)
class Plan:
    id: PlanId
    display_name: str
    price_minor: int               # kuruş — float para birimi YOK
    currency: str
    cycle: str
    entitlements: Entitlements


class UnknownPlanError(LookupError): ...


class PlanCatalog:
    def __init__(self, plans: list[Plan]):
        ids = [p.id for p in plans]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate plan id in catalog")
        self._by_id = {p.id: p for p in plans}

    def get(self, plan_id: str) -> Plan:
        try:
            return self._by_id[PlanId(plan_id)]
        except (ValueError, KeyError) as e:
            raise UnknownPlanError(plan_id) from e

    def public(self) -> list[Plan]:
        return list(self._by_id.values())


DEFAULT_CATALOG = PlanCatalog([
    Plan(PlanId.FREE, "Free", 0, "TRY", "forever", Entitlements(1, 1, "480p", False, True)),
    Plan(PlanId.PERSONAL, "Personal", 2999, "TRY", "monthly", Entitlements(2, 2, "1080p", False, False)),
    Plan(PlanId.DUO, "Duo", 4499, "TRY", "monthly", Entitlements(3, 3, "1080p", True, False)),
    Plan(PlanId.FAMILY, "Family", 6999, "TRY", "monthly", Entitlements(5, 5, "2160p", True, False)),
])
```

```python
# app/modules/billing/entitlements.py  — diğer modüllerin çağırdığı PUBLIC port
class EntitlementService:
    def __init__(self, subs: "SubscriptionRepository", catalog: PlanCatalog, clock):
        self._subs, self._catalog, self._clock = subs, catalog, clock

    def for_user(self, user_id: int) -> Entitlements:
        sub = self._subs.find(user_id)
        if sub is None or not sub.grants_access(self._clock()):   # expired/suspended → FREE
            return self._catalog.get(PlanId.FREE).entitlements
        return self._catalog.get(sub.plan).entitlements
```

`playback` ve `drm` modülleri `EntitlementService`'i port olarak alır; `User.max_connections` artık **okunmaz**.

---

#### DATA-04 · P1 · Abonelik yaşam döngüsü uygulanmıyor

**Kanıt:** Trial bitişi/grace bitişi/expire'ı tetikleyen periyodik iş yok; `check_subscription` hiçbir yerde çağrılmıyor; stream yetkilendirmesi abonelik durumuna bakmıyor; `cancel()` sonrası `expires_at` geçse bile plan aynı kalıyor. `start_trial`'ın "bir kez" kuralı yalnızca `trial_ends_at` kolonuna bakıyor; planı free'ye düşürülen kullanıcıda kayıt kalmaya devam ettiği için doğru çalışıyor, ancak `upgrade_plan` `trial_ends_at`'i temizlemediğinden durum makinesi tutarsız.

**Fix:** Açık bir **durum makinesi** + zaman tabanlı geçişler için beat task'ı.

```python
# app/modules/billing/domain/subscription_state.py
from enum import StrEnum

class SubStatus(StrEnum):
    TRIAL = "trial"; ACTIVE = "active"; GRACE = "grace"; CANCELLED = "cancelled"
    EXPIRED = "expired"; SUSPENDED = "suspended"

_ALLOWED: dict[SubStatus, frozenset[SubStatus]] = {
    SubStatus.TRIAL:     frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED, SubStatus.CANCELLED}),
    SubStatus.ACTIVE:    frozenset({SubStatus.GRACE, SubStatus.CANCELLED, SubStatus.SUSPENDED}),
    SubStatus.GRACE:     frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED, SubStatus.SUSPENDED}),
    SubStatus.CANCELLED: frozenset({SubStatus.EXPIRED, SubStatus.ACTIVE}),
    SubStatus.SUSPENDED: frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED}),
    SubStatus.EXPIRED:   frozenset({SubStatus.ACTIVE, SubStatus.TRIAL}),
}

class IllegalTransitionError(Exception):
    def __init__(self, src: SubStatus, dst: SubStatus):
        super().__init__(f"{src} → {dst} geçişi tanımsız"); self.src, self.dst = src, dst

def transition(current: SubStatus, target: SubStatus) -> SubStatus:
    if target not in _ALLOWED[current]:
        raise IllegalTransitionError(current, target)
    return target
```

```python
# app/modules/billing/tasks.py
@celery.task(name="billing.expire_due_subscriptions")
def expire_due_subscriptions() -> int:
    svc = resolve(BillingService)
    return svc.expire_due(now=utcnow(), batch=500)     # her değişen kayıt için outbox: subscription.changed
# manifest.beat_schedule = {"billing.expire-due": {"task": "billing.expire_due_subscriptions", "schedule": 300}}
```

---

#### DATA-05 · P1 · Idempotency anahtarı istek gövdesine bağlı değil; bekleme thread'i bloklar

**Konum:** `app/core/middleware/idempotency.py`
1. Aynı `Idempotency-Key` ile **farklı gövde** gönderilirse önceki yanıt döner (ör. `channel_id=5` için alınan stream token'ı `channel_id=9` isteğine dönebilir).
2. Kilit alınamazsa `time.sleep(0.5)` döngüsüyle **10 sn'ye kadar** Waitress thread'i bloklanır (6 thread'lik havuzda 6 eşzamanlı retry tüm sunucuyu kilitler).
3. Yanıt yalnızca JSON gövde + status olarak saklanıyor; header'lar (ör. `Location`, `Retry-After`) kayboluyor.
4. Kilit TTL'i işlemden kısa sürerse `finally` başkasının kilidini silebilir (token'sız `DEL`).

**Fix:**

```python
# app/core/http/idempotency.py
import functools, hashlib, json, uuid
from flask import g, request, jsonify, make_response
from flask_login import current_user
from app.core.http.errors import ApiError

_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


def _fingerprint() -> str:
    h = hashlib.sha256()
    h.update(request.method.encode()); h.update(b"\0")
    h.update(request.path.encode());   h.update(b"\0")
    h.update(request.get_data(cache=True) or b"")
    return h.hexdigest()


def idempotent(*, scope: str, ttl: int = 86400, lock_ttl: int = 30, redis_name: str = "redis_state"):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            key = request.headers.get("Idempotency-Key")
            if not key:
                return fn(*a, **kw)
            if len(key) > 128:
                raise ApiError("IDEMPOTENCY_KEY_INVALID", 400)
            from app.kernel.container import resolve
            r = resolve(redis_name)
            principal = str(current_user.id) if current_user.is_authenticated else f"anon:{request.remote_addr}"
            base = f"idem:{scope}:{principal}:{key}"
            fp = _fingerprint()

            cached = r.get(base)
            if cached:
                env = json.loads(cached)
                if env["fp"] != fp:
                    raise ApiError("IDEMPOTENCY_KEY_REUSED", 422)
                resp = make_response(jsonify(env["body"]), env["status"])
                resp.headers["Idempotent-Replayed"] = "true"
                return resp

            lock_token = uuid.uuid4().hex
            if not r.set(f"{base}:lock", lock_token, nx=True, ex=lock_ttl):
                resp = make_response(jsonify({"success": False, "error": {"code": "REQUEST_IN_PROGRESS"}}), 409)
                resp.headers["Retry-After"] = "1"               # BEKLEME YOK — istemci tekrar dener
                return resp
            try:
                g.idempotency_key = key
                rv = make_response(fn(*a, **kw))
                if 200 <= rv.status_code < 300 and rv.is_json:
                    r.set(base, json.dumps({"fp": fp, "status": rv.status_code, "body": rv.get_json()}), ex=ttl)
                return rv
            finally:
                r.eval(_RELEASE, 1, f"{base}:lock", lock_token)   # yalnızca KENDİ kilidimizi sil
        return wrapper
    return deco
```

---

#### DATA-06 · P1 · Playlist yenileme kanal kimliklerini yok ediyor → favoriler, ilerleme, olaylar yetim kalıyor

**Konum:** `app/routes/playlist.py::refresh_playlist` tüm kanalları siler, yeniden ekler. Yeni satırlar **yeni PK** alır. `Favorite`, `WatchProgress`, `PlaybackEvent`, `PlaybackMetrics`, `DRMContent.channel_id` eski ID'lere işaret eder. PostgreSQL'de FK ihlali (silme reddedilir), SQLite'ta (FK enforcement varsayılan kapalı) **sessiz yetim kayıtlar**.

**Fix:** Doğal anahtar ile **upsert** (`playlist_id + source_key`; `source_key` = `tvg-id` varsa o, yoksa normalize edilmiş URL'in SHA-1'i), artık listede olmayanları **soft-delete** (`is_active=false`), tek transaction, Celery'de.

```python
# app/modules/catalog/services/playlist_sync.py
import hashlib
from sqlalchemy import update


def source_key(entry: "ParsedEntry") -> str:
    if entry.tvg_id:
        return f"tvg:{entry.tvg_id}"
    return "url:" + hashlib.sha1(entry.url.strip().encode()).hexdigest()


class PlaylistSyncService:
    BATCH = 1000

    def __init__(self, uow_factory, upserter: "ChannelUpserter"):
        self._uow_factory, self._upsert = uow_factory, upserter

    def sync(self, playlist_id: int, entries: list["ParsedEntry"]) -> "SyncReport":
        seen: set[str] = set()
        with self._uow_factory() as uow:
            for i in range(0, len(entries), self.BATCH):
                chunk = entries[i:i + self.BATCH]
                rows = [{"playlist_id": playlist_id, "source_key": source_key(e), "name": e.name,
                         "url": e.url, "logo": e.logo, "group": e.group or "Uncategorized",
                         "is_active": True} for e in chunk]
                seen.update(r["source_key"] for r in rows)
                self._upsert(uow.session, rows)       # ON CONFLICT (playlist_id, source_key) DO UPDATE
            deactivated = uow.session.execute(
                update(Channel)
                .where(Channel.playlist_id == playlist_id, Channel.source_key.not_in(seen), Channel.is_active)
                .values(is_active=False)
            ).rowcount
            uow.outbox.add(CatalogChangedEvent(playlist_id=playlist_id))
        return SyncReport(upserted=len(seen), deactivated=deactivated)
```

> `NOT IN` büyük kümelerde verimsizdir; >10k kanal için `seen` kümesi geçici tabloya (`CREATE TEMP TABLE`) yazılıp anti-join yapılmalı.

---

#### DATA-07 · P1 · Toplu import: yanlış canlı/VOD sınıflandırması, atomik olmayan yazım, saatlerce süren HTTP isteği

**Konum:** `app/services/video_service.py::_process_links`, `stream_validator.py`
- `is_live = '#EXT-X-ENDLIST' not in content` yalnızca ilk 4 KB'a bakıyor; **master playlist'ler** asla `ENDLIST` içermez → tüm HLS VOD'lar "live" olarak `LiveChannel` tablosuna yazılıyor.
- `is_binary = any(b in first_chunk[:10] for b in [b'\x47', b'\x00'])` → ilk 10 bayt içinde herhangi bir `'G'` karakteri (ör. `#EXTM3U\nG...`) binary sanılır.
- Her link için sıralı, 30 sn timeout'lu doğrulama, hata durumunda **3 kez** tekrar istek (SSL → verify=False → ConnectionError → verify=False) → 1000 linklik import HTTP isteği içinde saatler sürer.
- `create_live_channel` adı Türkçe karakterli kanallarda stream_key'i boş string'e indirger (`re.sub(r'[^a-z0-9_]', '', ...)`), sonra `'x'` ekleyerek döngüye girer.

**Fix:** Import → `202 Accepted` + Celery task; doğrulama `asyncio`/`httpx` ile **sınırlı eşzamanlılık** (ör. 20) ve toplam bütçe; sınıflandırma master playlist'te alt varyant playlist'in ilk 64 KB'ı okunarak yapılır (`#EXT-X-PLAYLIST-TYPE:VOD` / `#EXT-X-ENDLIST`); stream key SEC-03'teki `IngestKeyService` ile rastgele üretilir.

```python
# app/modules/catalog/services/stream_probe.py
import asyncio
import httpx

class StreamKind(StrEnum):
    LIVE = "live"; VOD = "vod"; UNKNOWN = "unknown"; DEAD = "dead"

async def probe(client: httpx.AsyncClient, url: str, egress: "EgressGateway") -> StreamKind:
    egress.check(url)
    try:
        async with client.stream("GET", url, timeout=8.0) as r:
            if r.status_code != 200:
                return StreamKind.DEAD
            head = b""
            async for chunk in r.aiter_bytes():
                head += chunk
                if len(head) >= 65536:
                    break
    except httpx.HTTPError:
        return StreamKind.DEAD
    if head[:1] == b"\x47" and len(head) > 188 and head[188:189] == b"\x47":   # TS sync byte, 188-bayt paket
        return StreamKind.LIVE
    text = head.decode("utf-8", "ignore")
    if "#EXT-X-STREAM-INF" in text:                                            # master → ilk varyantı incele
        variant = next((l for l in text.splitlines() if l and not l.startswith("#")), None)
        return await probe(client, str(httpx.URL(url).join(variant)), egress) if variant else StreamKind.UNKNOWN
    if "#EXT-X-ENDLIST" in text or "#EXT-X-PLAYLIST-TYPE:VOD" in text:
        return StreamKind.VOD
    return StreamKind.LIVE if "#EXTINF" in text else StreamKind.UNKNOWN

async def probe_many(urls: list[str], egress, concurrency: int = 20) -> dict[str, StreamKind]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(follow_redirects=False, http2=True) as client:
        async def one(u):
            async with sem:
                return u, await probe(client, u, egress)
        return dict(await asyncio.gather(*(one(u) for u in urls)))
```

> Redirect takibi `EgressGateway` mantığıyla elle yapılmalıdır; örnekte kısaltma amacıyla `follow_redirects=False` ile 3xx "DEAD" sayılır.

---

#### DATA-08 · P1 · SQLite + çok thread'li sunucu + "FOR UPDATE" varsayımları

**Kanıt:** Waitress 6 thread; her istekte `AccessLog` yazımı, heartbeat'ler, metrikler → SQLite tek yazıcı kilidi → `database is locked`. `with_for_update` çağrıları (outbox dispatcher, DRM guard) SQLite'ta etkisiz; kod PostgreSQL semantiği varsayıyor, CI de PostgreSQL ile test ediyor ama geliştirme SQLite ile koşuyor (ortam paritesi yok).

**Fix:** Geliştirme dahil **PostgreSQL** (docker compose). SQLite yalnızca birim testlerinde kalacaksa:

```python
# app/kernel/db.py
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")        # FK enforcement — DATA-06'daki sessiz yetimleri engeller
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
```

---

#### DATA-09 · P2 · Naive `datetime.utcnow()` ve zaman damgaları

**Kanıt:** Tüm modeller `default=datetime.utcnow` (naive). Python 3.12+'da `datetime.utcnow()` **deprecated**; `__pycache__` 3.12 ve 3.14 derlemeleri içeriyor, yani proje bu sürümlerle çalıştırılıyor. Naive/aware karışımı `TypeError: can't compare offset-naive and offset-aware datetimes` üretir (ör. JWT `exp` aware, DB naive).

**Fix:**
```python
# app/kernel/time.py
from datetime import datetime, timezone
def utcnow() -> datetime:
    return datetime.now(timezone.utc)

# app/kernel/db.py
def utcnow_column(**kw):
    return db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, **kw)
```
Testlerde `Clock` portu enjekte edilir (`FrozenClock`) — zaman bağımlı tüm kurallar (trial, grace, lisans) deterministik test edilir.

---

#### DATA-10 · P2 · `Favorite` için benzersizlik yok; toggle yarış koşulu

**Konum:** `favorite` tablosunda `(user_id, channel_id)` unique değil. `toggle_favorite` "oku → sil/ekle" yapıyor; çift tıklamada iki satır oluşabilir, sonraki toggle yalnızca birini siler → UI "favori değil" derken DB'de favori kalır. Ayrıca toggle **idempotent değildir** (aynı isteği tekrarlamak durumu tersine çevirir) — idempotency middleware'i ile birlikte kullanılması semantik çelişkidir.

**Fix:** REST semantiği: `PUT /api/v1/profiles/me/favorites/{channel_id}` (ekle, idempotent) ve `DELETE ...` (kaldır, idempotent); `UNIQUE(profile_id, channel_id)` + `INSERT ... ON CONFLICT DO NOTHING`.

---

#### RES-01 · P1 · Circuit breaker: yarı-açık durum hatalı, fallback sözleşmesi belirsiz, bağımlılıklar karışık

**Konum:** `app/core/resilience/circuit_breaker.py`
- `HALF_OPEN`'da `_half_open_calls` hiç azaltılmıyor; probe sayısı dolunca bir sonraki başarılı çağrıya kadar **tüm istekler fallback'e** düşer, ama başarılı çağrı yapılamadığı için devre yarı-açıkta **takılı kalabilir**.
- `HALF_OPEN`'da tek bir başarısızlık devreyi hemen açmıyor; `_failures` sayacı eşiğe yeniden ulaşana kadar yük gönderilmeye devam ediliyor.
- Her `Exception` başarısızlık sayılıyor (ör. `ValueError` gibi istemci hataları da devreyi açar).
- `fallback=None` ise sessizce `None` döner (RT-09).
- Durum process-local; 4 Gunicorn worker = 4 bağımsız devre (kabul edilebilir, ama bilinçli olmalı).

**Fix:**

```python
# app/core/resilience/circuit_breaker.py
from __future__ import annotations
import threading, time
from enum import Enum
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"; OPEN = "open"; HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str, retry_in: float):
        super().__init__(f"circuit '{name}' open; retry in {retry_in:.1f}s")
        self.name, self.retry_in = name, retry_in


class CircuitBreaker:
    def __init__(self, name: str, *, failure_threshold: int = 5, recovery_timeout: float = 30.0,
                 half_open_max_calls: int = 1, counted: tuple[type[BaseException], ...] = (Exception,),
                 clock: Callable[[], float] = time.monotonic):
        self.name = name
        self._threshold, self._recovery, self._probe_cap = failure_threshold, recovery_timeout, half_open_max_calls
        self._counted, self._clock = counted, clock
        self._state, self._failures, self._opened_at, self._in_flight_probes = CircuitState.CLOSED, 0, 0.0, 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def call(self, fn: Callable[[], T]) -> T:
        probe = self._acquire()                       # açık devrede CircuitOpenError fırlatır
        try:
            result = fn()
        except self._counted:
            self._record_failure(probe)
            raise
        except BaseException:
            self._release_probe(probe)                # sayılmayan hata: devre durumunu etkilemez
            raise
        self._record_success(probe)
        return result

    # ── iç durum makinesi ───────────────────────────────────────────
    def _acquire(self) -> bool:
        with self._lock:
            if self._state is CircuitState.OPEN:
                elapsed = self._clock() - self._opened_at
                if elapsed < self._recovery:
                    raise CircuitOpenError(self.name, self._recovery - elapsed)
                self._state, self._in_flight_probes = CircuitState.HALF_OPEN, 0
            if self._state is CircuitState.HALF_OPEN:
                if self._in_flight_probes >= self._probe_cap:
                    raise CircuitOpenError(self.name, 0.0)
                self._in_flight_probes += 1
                return True
            return False

    def _release_probe(self, probe: bool) -> None:
        if probe:
            with self._lock:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)

    def _record_success(self, probe: bool) -> None:
        with self._lock:
            if probe:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)
            self._state, self._failures = CircuitState.CLOSED, 0

    def _record_failure(self, probe: bool) -> None:
        with self._lock:
            if probe:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)
            self._failures += 1
            if probe or self._failures >= self._threshold:     # yarı-açıkta TEK hata yeterli
                self._state, self._opened_at = CircuitState.OPEN, self._clock()
```

Fallback breaker'ın değil **çağıranın** sorumluluğudur (`try/except CircuitOpenError`), böylece fallback yolu tiplenir ve `None` sızmaz. Breaker'lar `name` ile container'da kayıtlı olur (`db`, `elasticsearch`, `upstream_hls`) ve `/metrics`'e durumlarını yayınlar.
### 3.D Asenkron Altyapı: Celery, Outbox, EventBus

#### ASY-01 · P0 · İki ayrı Celery uygulaması; outbox hiçbir zaman dispatch edilmiyor

**Kanıt:**

| | `app/core/celery_app.py` | `app/tasks/celery_app.py` |
|---|---|---|
| Instance | `celery_app = Celery("iptv_project", broker=REDIS_URL)` | `celery = Celery(__name__)` |
| Env değişkeni | `REDIS_URL` | `CELERY_BROKER_URL` |
| Kayıtlı task'lar | `core.dispatch_outbox`, `core.retry_*`, `core.reap_*`, `core.purge_*` | `m3u_tasks.*`, `epg_tasks.*` |
| Flask app context | **Yok** (`db.session` kullanan task'lar `RuntimeError: Working outside of application context`) | Var (`ContextTask`) |
| `include` | `app.modules.{auth,billing,drm,profile,search,stream}.tasks` — **hiçbiri mevcut değil** → worker başlarken `ModuleNotFoundError` | — |
| Beat | RedBeat + 4 periyodik görev | `refresh-epg-every-6-hours` |
| Worker | **Hiçbir yerde çalıştırılmıyor** | `docker-compose` → `celery_worker.celery` |

Ek olarak `app/tasks/celery_config.py` (Grim Reaper beat'i) **hiçbir yerden yüklenmiyor**; `transcoder_tasks.py` `@shared_task` kullanıyor ama worker bu modülü import etmediği için `transcode.start_abr_stream` **"Received unregistered task"** hatası alır; ayrıca task'ın gideceği `celery` kuyruğunu dinleyen worker yok (compose'daki worker'lar yalnızca `playlist` ve `epg`).

**Etki:** `user.registered` ve `subscription.changed` olayları `shared_outbox_events`'te sonsuza dek `pending` kalır → `User.max_connections` hiçbir zaman güncellenmez → ödeme yapan kullanıcı 1 stream'e kilitli (DATA-03 ile birleşince en görünür iş hatası). Canlı ABR akışı her zaman 504.

**Expert Fix — tek Celery, manifest güdümlü kayıt, isimlendirilmiş hatalar:**

```python
# app/kernel/celery_factory.py
from __future__ import annotations
import importlib.util
from celery import Celery
from flask import Flask
from app.kernel.errors import ModuleContractError, DuplicateScheduleError
from app.kernel.manifest import ModuleManifest


def create_celery(app: Flask, manifests: list[ModuleManifest]) -> Celery:
    celery = Celery(app.import_name)
    celery.conf.update(app.config["CELERY"])              # Settings → dict (CFG-01)

    class FlaskTask(celery.Task):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = FlaskTask

    includes: list[str] = ["app.kernel.outbox.tasks"]
    beat: dict[str, dict] = {}
    routes: dict[str, dict] = {}
    for m in manifests:
        for mod in m.task_modules:
            if importlib.util.find_spec(mod) is None:
                raise ModuleContractError(m.name, f"task modülü bulunamadı: {mod}")
            includes.append(mod)
        for name, entry in m.beat_schedule.items():
            if name in beat:
                raise DuplicateScheduleError(name, owner=m.name)
            beat[name] = entry
        for pattern, route in m.task_routes.items():
            routes[pattern] = route

    celery.conf.update(
        include=includes,
        beat_schedule=beat,
        task_routes=routes,
        task_default_queue="default",
        task_acks_late=True,                    # worker ölürse mesaj tekrar kuyruğa
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_serializer="json", accept_content=["json"], result_serializer="json",
        broker_connection_retry_on_startup=True,
        result_expires=3600,
    )
    celery.set_default()                         # @shared_task'lar bu app'e bağlanır
    app.extensions["celery"] = celery
    return celery
```

```python
# app/wsgi.py — TEK giriş noktası (web, worker, beat aynı factory'yi kullanır)
from app import create_app
app = create_app()
celery = app.extensions["celery"]
```

```bash
celery -A app.wsgi:celery worker -Q default,playlist,epg,outbox -l info
celery -A app.wsgi:celery worker -Q transcode -c 2 -l info     # ayrı havuz, CPU/GPU ağır
celery -A app.wsgi:celery beat -S redbeat.RedBeatScheduler -l info
```

`app/core/celery_app.py`, `app/tasks/celery_app.py`, `app/tasks/celery_config.py`, `celery_worker.py` silinir.

---

#### ASY-02 · P0 · EventBus hataları yutuyor → başarısız olay "processed" işaretleniyor

**Konum:** `app/core/event_bus.py::publish` her handler'ı `try/except` içinde çağırıp yalnızca log'luyor; `outbox_dispatcher` `EventBus.publish(...)` dönerse `final_status = "processed"` yazıyor.

**Etki:** Handler'ın DB hatası, bug'ı, timeout'u → olay **kalıcı olarak işlendi** sayılır. `retry_failed_outbox_events` ve dead-letter mantığı fiilen **ölü kod**. Hiç subscriber yoksa da (ör. modül yüklenemedi, ASY-07) olay "processed" olur — sessiz veri kaybı.

Ek tasarım sorunları: `_subscribers` **class-level mutable global** (testler arası sızıntı; conftest bunu elle temizlemek zorunda kalmış); handler kimliği yok (aynı handler iki modülden farklı amaçla bağlanamaz); tüm handler'lar aynı transaction/process'te seri çalışıyor (bir yavaş consumer diğerlerini bekletir).

**Expert Fix — tüketici bazlı teslimat (per-consumer delivery) + Inbox:**

```python
# app/kernel/events/bus.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Protocol


class EventHandler(Protocol):
    def __call__(self, event: object, *, uow: "UnitOfWork") -> None: ...


class DuplicateConsumerError(Exception): ...
class UnknownConsumerError(LookupError): ...
class UnknownEventTypeError(LookupError): ...


@dataclass(frozen=True, slots=True)
class Subscription:
    event_name: str
    consumer: str                 # "billing.on_user_registered" — global benzersiz
    handler: EventHandler
    queue: str = "outbox"


@dataclass
class EventBus:
    """Instance tabanlı; container'da singleton. Global state YOK."""
    _subs: dict[str, dict[str, Subscription]] = field(default_factory=dict)

    def subscribe(self, sub: Subscription) -> None:
        bucket = self._subs.setdefault(sub.event_name, {})
        if sub.consumer in bucket:
            raise DuplicateConsumerError(f"{sub.consumer} zaten {sub.event_name} için kayıtlı")
        bucket[sub.consumer] = sub

    def consumers(self, event_name: str) -> list[Subscription]:
        return list(self._subs.get(event_name, {}).values())

    def handler(self, event_name: str, consumer: str) -> Subscription:
        try:
            return self._subs[event_name][consumer]
        except KeyError as e:
            raise UnknownConsumerError(f"{event_name}/{consumer}") from e
```

```python
# app/kernel/outbox/tasks.py
from sqlalchemy import text
from app.kernel.container import resolve
from app.kernel.events.bus import EventBus
from app.kernel.events.registry import EventRegistry

_CLAIM_PG = text("""
UPDATE shared_outbox_events SET status = 'dispatching', processing_started_at = now()
WHERE id IN (
    SELECT id FROM shared_outbox_events
    WHERE status = 'pending' AND available_at <= now()
    ORDER BY created_at
    LIMIT :n
    FOR UPDATE SKIP LOCKED
)
RETURNING id, event_name
""")


@celery.task(name="kernel.outbox.dispatch", queue="outbox")
def dispatch_outbox(batch: int = 200) -> int:
    """Olayı ÇALIŞTIRMAZ — her (olay, tüketici) çifti için ayrı teslim task'ı planlar."""
    bus, session = resolve(EventBus), resolve("db_session")
    with session.begin():
        rows = session.execute(_CLAIM_PG, {"n": batch}).all()
    fanned = 0
    for event_id, event_name in rows:
        consumers = bus.consumers(event_name)
        if not consumers:
            _mark(session, event_id, "no_consumer")      # görünür durum; "processed" DEĞİL → alarm üretir
            continue
        for sub in consumers:
            deliver_event.apply_async((event_id, sub.consumer), queue=sub.queue)
            fanned += 1
        _mark(session, event_id, "dispatched")
    return fanned


@celery.task(
    bind=True, name="kernel.outbox.deliver", acks_late=True,
    autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=8,
)
def deliver_event(self, event_id: str, consumer: str) -> str:
    bus, registry, uow_factory = resolve(EventBus), resolve(EventRegistry), resolve("uow_factory")
    with uow_factory() as uow:
        record = uow.outbox.get(event_id)
        sub = bus.handler(record.event_name, consumer)                 # UnknownConsumerError → retry → DLQ
        if not uow.inbox.try_claim(event_id, consumer):                # INSERT .. ON CONFLICT DO NOTHING
            return "duplicate"
        event = registry.decode(record.event_name, record.payload_json)   # UnknownEventTypeError
        sub.handler(event, uow=uow)                                    # yan etki + inbox AYNI transaction'da
    return "delivered"                                                 # __exit__ → commit (exactly-once etki)
```

```python
# app/kernel/outbox/dead_letter.py — max_retries aşıldığında görünür kayıt
from celery.signals import task_failure

@task_failure.connect(sender="kernel.outbox.deliver")
def _to_dead_letter(sender=None, task_id=None, exception=None, args=None, **_):
    event_id, consumer = args
    resolve("dead_letter_repo").record(event_id=event_id, consumer=consumer, error=repr(exception))
```

Bu modelde bir tüketicinin hatası diğerlerini etkilemez, her tüketici kendi backoff'u ile yeniden denenir, inbox tablosu (mevcut `shared_processed_event_log`) **aynı transaction'da** yazıldığı için "en az bir kez teslim + idempotent tüketici = etkide tam olarak bir kez" garantisi sağlanır.

---

#### ASY-03 · P1 · Outbox dispatcher'da transaction ve context hataları

**Konum:** `app/core/outbox_dispatcher.py`
- Flask app context olmadan `db.session` → `RuntimeError` (ASY-01).
- Adım 2'de listener `ProcessedEventLog.query...first()` ile okuyup erken dönerse oturum **autobegin** ile transaction açık kalır; Adım 3'teki `with db.session.begin()` → `InvalidRequestError: A transaction is already begun on this Session` → olay sonsuza dek `processing` (reaper 5 dk sonra kurtarır, sonra aynı döngü).
- `with_for_update(skip_locked=True)` SQLite'ta etkisiz; iki worker aynı olayı işleyebilir.
- Listener (`auth/listeners.py`) idempotency kontrolünü **ayrı sorgu** ile yapıp sonra `commit` ediyor; kontrol ile insert arası yarış.

**Fix:** ASY-02'deki claim (`UPDATE ... RETURNING` + `SKIP LOCKED`) ve `try_claim` (`ON CONFLICT DO NOTHING`):

```python
# app/kernel/outbox/inbox.py
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

class InboxRepository:
    def __init__(self, session):
        self._s = session

    def try_claim(self, event_id: str, consumer: str) -> bool:
        ins = pg_insert if self._s.bind.dialect.name == "postgresql" else sqlite_insert
        stmt = ins(ProcessedEventLog).values(event_id=event_id, consumer_name=consumer) \
                                     .on_conflict_do_nothing(index_elements=["event_id", "consumer_name"])
        return self._s.execute(stmt).rowcount == 1
```

---

#### ASY-04 · P1 · `sync_playlist_task` sahte; uç noktalar task'ı hiç kullanmıyor

**Konum:** `app/tasks/m3u_tasks.py` → `channels_added = len(parsed_data)` (`parsed_data` bir **dict**: `{'success':..., 'links':...}` → her zaman 2), DB'ye hiçbir şey yazılmıyor ("Normally we would db.session.commit() here"). Ayrıca `fetch_and_parse` hata döndürdüğünde de "completed" raporlanıyor. Route'lar (`/api/playlists`, `/api/admin/import-links`) task'ı çağırmıyor, senkron çalışıyor.

**Fix:** DATA-06'daki `PlaylistSyncService` + task; HTTP ucu `202`:

```python
# app/modules/catalog/tasks.py
@celery.task(bind=True, name="catalog.sync_playlist", queue="playlist",
             autoretry_for=(TransientFetchError,), retry_backoff=True, max_retries=3)
def sync_playlist(self, playlist_id: int) -> dict:
    lock = resolve("lock_factory")(f"lock:sync_playlist:{playlist_id}", ttl=600)
    if not lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running"}
    try:
        self.update_state(state="PROGRESS", meta={"progress": 10, "message": "indiriliyor"})
        source = resolve(PlaylistSourceRepository).get(playlist_id)       # URL kuyrukta taşınmaz
        entries = resolve(M3UFetcher).fetch(source.url)                    # EgressGateway + boyut limiti
        self.update_state(state="PROGRESS", meta={"progress": 60, "message": "yazılıyor"})
        report = resolve(PlaylistSyncService).sync(playlist_id, entries)
        return {"status": "completed", **report.as_dict()}
    finally:
        lock.release()                                                     # token'lı release (redis-py Lock)


# http
@catalog_bp.post("/playlists/<int:playlist_id>/sync")
@require_permission("catalog:write")
def trigger_sync(playlist_id: int):
    res = sync_playlist.delay(playlist_id)
    return ok({"task_id": res.id}, status=202, headers={"Location": f"/api/v1/tasks/{res.id}"})
```

> Mevcut implementasyondaki `finally` + `sys.exc_info()` ile Retry tespiti, `raise self.retry(...)` sonrası `Retry` istisnası propagate ederken çalışır; ancak `redis-py`'nin `Lock` nesnesi (token'lı, `extend`/`reacquire` destekli) bu el yapımı mekanizmanın yerine geçmelidir.

---

#### ASY-05 · P1 · Modül/listener yükleyicileri hataları yutuyor

**Konum:**
- `app/core/module_loader.py`: `except Exception as e: logger.error(...)` → routes import'u patlayan modül sessizce atlanır; uygulama "sağlıklı" başlar, uçlar 404 döner. `drm`, `profile`, `search`, `stream` modüllerinde `routes.py` olmadığı için her açılışta **4 adet `[FAIL]` log'u** üretilir (gürültü, gerçek hatayı gizler).
- `app/core/listener_registry.py`: `except ModuleNotFoundError: continue` — `listeners.py` **var ama içindeki bir import eksikse** de (`ModuleNotFoundError` alt sınıfı) sessizce atlanır → subscription.changed tüketicisi hiç kaydolmaz → ASY-02 ile birleşince olay "processed".
- `get_celery_includes`: disk taraması ile var olmayan `tasks` modüllerini ekler (ASY-01).

**Kök neden:** "Konvansiyon ile keşif" (`pkgutil.iter_modules` + `getattr(..., f"{name}_bp")`) **opsiyonel** ile **zorunlu**'yu ayırt edemiyor.

**Fix:** Bölüm 4.3'teki **ModuleManifest + ModuleRegistry**. Özet: her modül ne sağladığını açıkça ilan eder; registry, ilan edilen her parçanın gerçekten var olduğunu doğrular; eksikse isimlendirilmiş hata ile boot'u durdurur. Yokluğun "bilinçli" olduğu durumlar manifest'te `None`/boş liste ile ifade edilir — tahmin yok.

---

#### ASY-06 · P2 · `BackgroundJob` modeli Celery ile çakışan ikinci bir iş kuyruğu

`app/models/background_job.py` kendi `status/retry/progress` makinesi olan bir tablo; hiçbir yerde kullanılmıyor ve Celery'nin result backend'i ile aynı sorumluluğu üstleniyor. Kaldırılmalı; uzun süreli iş takibi gerekiyorsa `task_id` + domain'e özgü durum (ör. `PlaylistSyncRun`) tutulmalı.

---

### 3.E Streaming ve Transcoder

#### STR-01 · P0 · `FFmpeg` stderr `PIPE` ama hiç okunmuyor → transcoder kilitleniyor

**Konum:** `app/services/transcoder/ffmpeg_engine.py::start_transcoding` → `stderr=subprocess.PIPE`; ardından `transcoder_tasks.py` `engine.process.wait()`. FFmpeg sürekli stderr'e yazar (`-nostats` olsa bile uyarılar/segment bilgileri); OS pipe buffer'ı (~64 KB) dolunca FFmpeg **yazma çağrısında bloklanır**, encode durur, `wait()` sonsuza dek bekler. Belgelenmiş klasik deadlock (Python `subprocess` dokümantasyonu: "use communicate() ... to avoid deadlocks").

**Fix:** stderr'i ayrı bir thread ile **sürekli tüketip** sınırlı ring buffer'a almak (crash teşhisi için son N satır), `-progress pipe:1` ile yapılandırılmış ilerleme okumak:

```python
# app/modules/live/adapters/ffmpeg_process.py
import collections, subprocess, threading

class FfmpegProcess:
    def __init__(self, argv: list[str], *, new_group: bool):
        kw = {"start_new_session": True} if new_group else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, bufsize=0, **kw)
        self.tail: collections.deque[str] = collections.deque(maxlen=200)
        self._t = threading.Thread(target=self._drain, name=f"ffmpeg-stderr-{self.proc.pid}", daemon=True)
        self._t.start()

    def _drain(self) -> None:
        assert self.proc.stderr is not None
        for raw in iter(self.proc.stderr.readline, b""):
            self.tail.append(raw.decode("utf-8", "replace").rstrip())
        self.proc.stderr.close()

    def wait(self, timeout: float | None = None) -> int:
        rc = self.proc.wait(timeout)
        self._t.join(timeout=2)
        return rc
```

---

#### STR-02 · P1 · Orkestratör: izleyici sayısı yalnızca artıyor, boşta kalan transcoder hiç durmuyor

**Konum:** `transcoder/stream_manager.py::request_stream` → her `master.m3u8` isteğinde `viewers += 1`; azaltan kod yok. Durdurma yalnızca FFmpeg kendiliğinden çıkınca. Ayrıca `hgetall` → kontrol → `hset` atomik değil (iki eşzamanlı istek iki task dispatch edebilir); `STARTING` durumundaki anahtarın 300 sn TTL'i dolduğunda FFmpeg çalışmaya devam etse bile ikinci bir FFmpeg başlatılır.

**Fix:** İzleyici varlığı = playback session heartbeat'i (DATA-01) ile **lease** modeli; transcoder kendi lease'ini yeniler; "son izleyici heartbeat'i X sn önce" ise reaper durdurur. Başlatma kararı tek Lua script ile atomik:

```lua
-- KEYS[1]=abr_stream:<id>  ARGV[1]=now ARGV[2]=source ARGV[3]=start_ttl
local st = redis.call('HGET', KEYS[1], 'status')
if st == 'STARTING' or st == 'RUNNING' then
  redis.call('HSET', KEYS[1], 'last_viewer_at', ARGV[1])
  return 0                                   -- zaten çalışıyor; dispatch etme
end
redis.call('HSET', KEYS[1], 'status', 'STARTING', 'source', ARGV[2], 'last_viewer_at', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1                                     -- çağıran task'ı dispatch eder
```

Reaper: `last_viewer_at < now - IDLE_GRACE (ör. 60 sn)` olan `RUNNING` akışları `transcode.stop` task'ı ile durdurur (FFmpeg'i başlatan worker'ın PGID'sini bilen tek yer orasıdır; farklı makinedeki worker'ın `os.killpg` çağrısı işe yaramaz → stop komutu worker'a **kontrol kanalı** ile iletilir: Redis pub/sub `transcode:control:<worker_hostname>`).

---

#### STR-03 · P1 · Platform bağımlılığı: `/dev/shm`, `os.setsid`, `os.killpg`, NVENC

**Kanıt:** Geliştirme ortamı Windows; `preexec_fn=os.setsid`, `os.getpgid`, `os.killpg` **Windows'ta yok** → task `AttributeError`. `/dev/shm` Windows'ta yok. Profiller sabit `h264_nvenc` → NVIDIA GPU yoksa FFmpeg başlangıçta çıkar; `-tune hq` libx264'te geçersiz bir değer (fallback de çalışmaz). `-map a:0` kaynakta ses yoksa FFmpeg hata verir. Grim Reaper `psutil` ile **tüm** `ffmpeg` süreçlerini tarar → aynı makinedeki `Scripts/streaming/ingest.py` FFmpeg'ini de "zombie" sayıp öldürür.

**Fix:** Transcoder bir **port**; platform/encoder seçimi adapter'da; kapasite tespiti açılışta yapılır ve eksikse isimlendirilmiş hata:

```python
# app/modules/live/ports.py
class TranscoderPort(Protocol):
    def start(self, stream_id: str, source_url: str, output_dir: Path, ladder: "AbrLadder") -> "TranscodeHandle": ...
    def stop(self, handle: "TranscodeHandle") -> None: ...

class EncoderUnavailableError(RuntimeError): ...

# app/modules/live/adapters/encoder_probe.py
def detect_video_encoder(preferred: list[str]) -> str:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
    for enc in preferred:                                   # ["h264_nvenc", "h264_qsv", "h264_videotoolbox", "libx264"]
        if f" {enc} " in out:
            return enc
    raise EncoderUnavailableError(f"Hiçbiri yok: {preferred}")
```

`AbrLadder`, encoder'a göre `preset/tune` eşlemesini (`nvenc: p4/hq`, `libx264: veryfast/zerolatency`) içerir; çıktı dizini `Settings.hls_output_root` (Linux: `/dev/shm/streams`, Windows: `%LOCALAPPDATA%\neotv\hls`). Ses yoksa `-map 0:a:0?` (soru işareti = opsiyonel). Reaper yalnızca **kendi etiketlediği** süreçleri hedefler (komut satırına `-metadata neotv_stream=<id>` eklenir ve eşleşme bununla yapılır).

---

#### STR-04 · P1 · `master.m3u8` cold-start'ı 10 sn senkron long-polling ile bekliyor

**Konum:** `routes/live.py::get_abr_master_playlist` → `while not exists: time.sleep(0.5)` 20 kez. 6 thread'lik Waitress'te 6 eşzamanlı izleyici sunucuyu 10 sn kilitler.

**Fix:** `202 Accepted` + `Retry-After: 1` döndür; hls.js `manifestLoadingRetryDelay`/`manifestLoadingMaxRetry` ile bekler. Ya da master playlist'i **statik olarak hemen üret** (ladder bilinir) ve varyant playlist'ler hazır olana kadar `#EXT-X-START` ile kısa bekletme yap. Thread bloklanmaz.

---

### 3.F Performans ve Ölçeklenebilirlik

#### PERF-01 · P1 · 6 thread'lik Waitress üzerinde bloklayan işlemler envanteri

| Uç / Bileşen | Bloklama süresi (en kötü) | Kaynak |
|---|---|---|
| `master.m3u8` cold start | 10 sn | STR-04 |
| Idempotency kilidi bekleme | 10 sn | DATA-05 |
| CacheStampedeGuard kilit bekleme | 10 sn | `core/cache.py` |
| `POST /api/playlists` (M3U fetch) | 30 sn | SEC-09 |
| `POST /api/admin/import-links` | N × 30–90 sn | DATA-07 |
| `GET /api/live/proxy/hls` (segment) | 15 sn + tüm segment RAM'de | SEC-02 |

**Etki:** 6 eşzamanlı yavaş istek = tüm API yanıt vermez (thread starvation). Video segment trafiği (bir izleyici ≈ her 2–6 sn'de bir istek) API ile aynı havuzu paylaşıyor.

**Fix (topoloji):**
- **Gunicorn** (`gthread` worker, `workers = 2×CPU+1`, `threads=8`) ya da I/O ağırlıklı proxy için **ayrı** bir servis.
- Video/segment trafiği **asla** uygulama sunucusundan geçmemeli: Nginx (`X-Accel-Redirect`, `proxy_cache` ile upstream HLS önbelleği) veya CDN + imzalı URL (CloudFront/Bunny token auth). Uygulama yalnızca **yetkilendirir ve imzalar**.
- Uzun işler → Celery (ASY-04).
- Tüm bekleme döngüleri → `409/202 + Retry-After`.

---

#### PERF-02 · P2 · Her istekte senkron `AccessLog` INSERT + commit

**Konum:** `app/utils/decorators.py::log_access` — yanıt üretildikten sonra ayrı `commit`; hata `print` ile yutuluyor. Ayrıca handler'ın commit etmediği bir değişikliği varsa (ör. hata sonrası kirli oturum) `log_access` onu da commit eder.

**Fix:** Erişim günlüğü yapılandırılmış log (JSON stdout → Loki/ELK) olarak yazılır; veritabanına değil. Denetim (audit) gerekiyorsa outbox ile asenkron. `print` → `logging`.

---

#### PERF-03 · P2 · N+1 sorgular

- `RecommendationService.get_trending` → her kanal için `Channel.query.get` (RT-04 fix'i ile çözülür).
- `get_continue_watching`, `get_recently_watched`, `ProgressService.get_continue_list` → `p.channel` (lazy) her kayıt için ayrı sorgu.
- `get_personalized` → `WatchProgress.query.filter_by(user_id).all()` tüm geçmişi belleğe alır; `NOT IN (büyük liste)`.
- `admin.get_stats` 4 ayrı `COUNT` (kabul edilebilir; ama `active_24h` etiketi yanlış: aslında `is_active` sayısı).

**Fix:** Kanal kartları her zaman `CatalogReadPort.get_cards(ids)` ile toplu; "izlenmemiş" filtresi `NOT EXISTS` alt sorgusu ile:

```python
from sqlalchemy import exists, select

stmt = (select(Channel)
        .where(Channel.group.in_(top_groups), Channel.is_active,
               ~exists().where(WatchProgress.channel_id == Channel.id, WatchProgress.profile_id == profile_id))
        .limit(limit))
```

---

#### PERF-04 · P2 · Import-time ağır yan etkiler ve gereksiz thread'ler

- `core/observability/tracing.py` import edildiği anda `TracerProvider` + `OTLPSpanExporter("http://otel-collector:4317")` kuruluyor; geliştirmede bu host yok → arka planda sürekli bağlantı denemesi + log gürültüsü; test izolasyonu yok.
- `CacheStampedeGuard.get_or_compute` her cache miss'te bir **renewal thread** başlatıyor (lock_timeout 10 sn, compute çoğunlukla < 100 ms) — gereksiz thread churn.
- `l1_l2_cache_response`: anahtar `f"{fn.__name__}:{kwargs}"` → **positional argümanlar ve kullanıcı kimliği anahtarda yok**; bir uçta kullanılırsa kullanıcılar arası veri sızıntısı. Şu an hiçbir yerde kullanılmıyor — kullanılmadan kaldırılmalı ya da anahtar fonksiyonu zorunlu parametre yapılmalı.

**Fix:** Telemetri `Settings.otel_endpoint` varsa `create_app` içinde kurulur, yoksa no-op provider. Renewal thread yalnızca `compute` beklenen süreyi aşarsa (`threading.Timer` ile gecikmeli) başlar.

---

### 3.G Konfigürasyon, Ortam ve DevOps

#### CFG-01 · P0 · `.env` uygulanmıyor; `SECRET_KEY` hardcoded fallback ile çalışıyor

**Konum:** `run.py`

```python
from app import create_app          # ← app/__init__ → app.config import → Config sınıf gövdesi DEĞERLENDİRİLİR
from dotenv import load_dotenv
load_dotenv()                       # ← çok geç: Config.SECRET_KEY zaten 'dev-secret-key'
```

Ayrıca: `Config.SQLALCHEMY_DATABASE_URI` `DATABASE_URL`'i **hiç okumuyor** (`.env`'deki değer ve `conftest.py`'deki PostgreSQL ayarı yok sayılıyor; `create_app()` SQLite ile kurulup sonra `app.config.update` ile URI değiştiriliyor — Flask-SQLAlchemy engine'i `init_app` anında oluşturduğu için bu değişiklik **etkisiz**). `extensions.py` Redis URL'ini import anında okuyor; `celery_worker.py` hiç `load_dotenv` çağırmıyor; `ALLOWED_ORIGINS` iki yerde tanımlı; `SESSION_COOKIE_SECURE=False` sabit; `health/info` `'environment': 'development'` sabit.

**Expert Fix — tipli, doğrulanan, fail-fast Settings:**

```python
# app/kernel/settings.py
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      env_nested_delimiter="__", extra="forbid")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    secret_key: SecretStr = Field(min_length=32)
    database_url: str = "postgresql+psycopg://neotv:neotv@localhost:5432/neotv"
    redis_state_url: RedisDsn = "redis://localhost:6379/1"
    celery_broker_url: RedisDsn = "redis://localhost:6379/0"
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    profile_context_mode: Literal["strict", "default_profile"] = "default_profile"
    hls_output_root: Path = Path("/dev/shm/streams")
    hls_serve_via_nginx: bool = False
    otel_endpoint: str | None = None
    drm_kek_keys: list[SecretStr] = []
    payment_webhook_secret: SecretStr | None = None
    disabled_modules: frozenset[str] = frozenset()

    @field_validator("secret_key")
    @classmethod
    def _no_placeholder(cls, v: SecretStr) -> SecretStr:
        bad = {"dev-secret-key", "dev-secret-key-change-in-production", "changeme"}
        if v.get_secret_value() in bad:
            raise ValueError("SECRET_KEY placeholder değerde bırakılmış")
        return v

    @model_validator(mode="after")
    def _prod_invariants(self) -> "Settings":
        if self.env == "prod":
            if self.database_url.startswith("sqlite"):
                raise ValueError("prod ortamında SQLite kullanılamaz")
            if not self.drm_kek_keys:
                raise ValueError("prod ortamında DRM_KEK_KEYS zorunlu")
            if self.profile_context_mode != "strict":
                raise ValueError("prod ortamında PROFILE_CONTEXT_MODE=strict olmalı")
        return self

    def flask_config(self) -> dict:
        return {
            "SECRET_KEY": self.secret_key.get_secret_value(),
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
            "SESSION_COOKIE_SECURE": self.env in {"staging", "prod"},
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "PROFILE_CONTEXT_MODE": self.profile_context_mode,
            "HLS_OUTPUT_ROOT": str(self.hls_output_root),
            "HLS_SERVE_VIA_NGINX": self.hls_serve_via_nginx,
            "CELERY": {"broker_url": str(self.celery_broker_url),
                       "result_backend": str(self.celery_broker_url)},
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()                     # eksik/yanlış değer → ValidationError ile BOOT DURUR
```

```python
# app/__init__.py
def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()          # testler kendi Settings'ini enjekte eder
    app = Flask(__name__)
    app.config.from_mapping(settings.flask_config())
    ...
```

`.env` repodan çıkar, yerine `.env.example` (placeholder'lar, açıklamalar) gelir.

---

#### CFG-02 · P1 · Proje kökü aynı zamanda bir sanal ortam; depo hijyeni yok

**Kanıt:** Kökte `Lib/site-packages`, `Include/greenlet`, `Scripts/*.exe` (pip, flask, alembic, waitress) → kök dizin yanlışlıkla `python -m venv .` ile venv yapılmış; ayrıca `.venv/` de var. Proje betikleri venv'in `Scripts/` klasörüne konmuş (Windows'ta venv bin dizini). `__pycache__` 3.11/3.12/3.13/3.14 derlemeleri, `logs/`, `backend_debug.log`, `instance/database.db`, `frontend/dist`, `frontend/node_modules` aynı ağaçta. Git deposu yok, `.gitignore` yok.

**Etki:** Python sürümü belirsiz (4 farklı yorumlayıcı izi), import çözümlemesi belirsiz (`Lib/site-packages` `sys.path`'te olabilir), betik yolları (`Scripts` vs `scripts`) Linux CI'da kırık (TEST-02), secret ve veri sızıntısı.

**Fix:**
```text
1. git init; aşağıdaki .gitignore ile ilk commit
2. Kökteki Lib/, Include/, Scripts/*.exe, pyvenv.cfg silinir; proje betikleri tools/ altına taşınır
3. Python sürümü sabitlenir: .python-version = 3.12 ; pyproject.toml (requires-python = ">=3.12,<3.13")
4. Bağımlılık yönetimi: uv / pip-tools ile kilit dosyası (requirements.lock)
```

```gitignore
# .gitignore
.venv/
__pycache__/
*.py[cod]
instance/
logs/
*.log
.env
!.env.example
frontend/node_modules/
frontend/dist/
.importlinter.generated
/var/
```

---

#### CFG-03 · P1 · `docker-compose.yml` çalışmıyor

**Kanıt:** `build: .` ama **Dockerfile yok**; backend/API servisi yok; PostgreSQL yok; transcode kuyruğu için worker yok; `version: '3.8'` obsolete; `celery_beat` `REDBEAT_REDIS_URL` ile ayrı DB kullanırken core celery_app `redbeat_redis_url = REDIS_URL` diyor.

**Fix — çalışan referans topoloji:**

```dockerfile
# Dockerfile
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY app ./app
COPY migrations ./migrations
RUN useradd -r -u 10001 app && chown -R app /srv
USER app
EXPOSE 8000
HEALTHCHECK CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1
CMD ["gunicorn", "app.wsgi:app", "-k", "gthread", "-w", "4", "--threads", "8", "-b", "0.0.0.0:8000", "--access-logfile", "-"]
```

```yaml
# docker-compose.yml
x-app: &app
  build: .
  env_file: .env
  depends_on:
    postgres: { condition: service_healthy }
    redis:    { condition: service_healthy }

services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: neotv, POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?}", POSTGRES_DB: neotv }
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U neotv"], interval: 5s, retries: 10 }

  redis:
    image: redis:7.4-alpine
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?}", "--appendonly", "yes"]
    healthcheck: { test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"], interval: 5s, retries: 10 }

  migrate:
    <<: *app
    command: ["flask", "--app", "app.wsgi:app", "db", "upgrade"]
    restart: "no"

  api:
    <<: *app
    depends_on: { migrate: { condition: service_completed_successfully } }
    ports: ["8000:8000"]

  worker:
    <<: *app
    command: ["celery", "-A", "app.wsgi:celery", "worker", "-Q", "default,playlist,epg,outbox", "-c", "8", "-l", "info"]

  worker-transcode:
    <<: *app
    command: ["celery", "-A", "app.wsgi:celery", "worker", "-Q", "transcode", "-c", "2", "-l", "info"]
    shm_size: "2gb"            # /dev/shm HLS segmentleri için

  beat:
    <<: *app
    command: ["celery", "-A", "app.wsgi:celery", "beat", "-S", "redbeat.RedBeatScheduler", "-l", "info"]

volumes: { pgdata: {} }
```

### 3.H Frontend

#### FE-01 · P1 · Çift `AuthProvider` → iki bağımsız kimlik durumu

**Konum:** `src/main.jsx` `<AuthProvider><App/></AuthProvider>` ve `src/App.jsx` içinde tekrar `<AuthProvider>`. (`src/context/AuthContext.jsx` yalnızca re-export olduğu için ikisi **aynı bileşen**, iki ayrı instance.)

**Etki:** Açılışta iki kez `/auth/check`; iki `auth:unauthorized` listener'ı; dış provider'ın state'i hiçbir tüketiciye ulaşmıyor ama `logoutLocal` ile `localStorage`'ı temizliyor; ileride dış katmanda `useAuth` kullanan bir bileşen (ör. ErrorBoundary'ye eklenen bir "çıkış" butonu) **farklı** kullanıcı durumunu görür.

**Fix:** Tüm provider'lar tek bir kompozisyon noktasında:

```jsx
// src/app/AppProviders.jsx
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/core/api/queryClient';
import { AuthProvider } from '@/core/auth/AuthProvider';
import { ProfileProvider } from '@/core/profile/ProfileProvider';

export function AppProviders({ children }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ProfileProvider>{children}</ProfileProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

// src/main.jsx
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <AppProviders>
        <RouterProvider router={router} />   {/* router feature registry'den üretilir — 4.10 */}
      </AppProviders>
    </ErrorBoundary>
  </StrictMode>
);
```

---

#### FE-02 · P0 · VOD oynatma yetkilendirmeyi tamamen bypass ediyor; origin URL'ler istemcide

**Konum:** `features/playlist/pages/HomePage.jsx::handleChannelClick`

```js
} else {
    setStreamUrl(channel.url);           // ← /stream/authorize YOK, heartbeat YOK, limit YOK
```

`/api/channels` yanıtı her kanal için ham `url` alanını içeriyor (`_serialize_channel_base`). `SecurePlayer.jsx` (authorize + heartbeat yapan bileşen) hiçbir yerde kullanılmıyor.

**Etki:** Eşzamanlı stream limiti, abonelik durumu, DRM, kids filtresi, oturum takibi ve QoE ölçümü — hepsi devre dışı. Tüm katalog URL'leri (çoğu IPTV sağlayıcısında `username/password` içerir) tek bir istekle dışarı alınabilir.

**Fix:** Tek bir **Playback Gateway** — hem canlı hem VOD için aynı akış; katalog yanıtında `url` yok:

```js
// src/features/playback/api/playbackApi.js
import { api } from '@/core/api/client';

export const openSession = (contentRef) =>
  api.post('/v1/playback/sessions', { content_ref: contentRef });          // {session_token, manifest_url, heartbeat_interval_s, drm?}
export const heartbeat   = (token) => api.post('/v1/playback/sessions/heartbeat', { token });
export const releaseUrl  = '/api/v1/playback/sessions/release';
```

```js
// src/features/playback/hooks/usePlaybackSession.js
import { useEffect, useRef, useState } from 'react';
import { openSession, heartbeat, releaseUrl } from '../api/playbackApi';

export function usePlaybackSession(contentRef) {
  const [state, setState] = useState({ status: 'idle', session: null, error: null });
  const tokenRef = useRef(null);

  useEffect(() => {
    if (!contentRef) return undefined;
    let cancelled = false;
    let timer = null;

    const release = () => {
      const token = tokenRef.current;
      if (!token) return;
      tokenRef.current = null;
      navigator.sendBeacon(releaseUrl, new Blob([JSON.stringify({ token })], { type: 'application/json' }));
    };

    setState({ status: 'opening', session: null, error: null });
    openSession(contentRef)
      .then((session) => {
        if (cancelled) { tokenRef.current = session.session_token; release(); return; }
        tokenRef.current = session.session_token;
        setState({ status: 'ready', session, error: null });
        timer = setInterval(() => {
          heartbeat(session.session_token).catch((err) => {
            clearInterval(timer);
            setState((s) => ({ ...s, status: 'expired', error: err }));
          });
        }, session.heartbeat_interval_s * 1000);
      })
      .catch((error) => !cancelled && setState({ status: 'denied', session: null, error }));

    window.addEventListener('pagehide', release);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener('pagehide', release);
      release();
    };
  }, [contentRef]);

  return state;   // { status: idle|opening|ready|denied|expired, session, error }
}
```

`HomePage` ve `LiveStreamsPage` yalnızca `<PlayerContainer contentRef="vod:123" />` render eder; player kaynak URL'sini **sadece** `session.manifest_url`'den alır.

---

#### FE-03 · P0 · hls.js her playlist/segment isteğine sahte `Authorization` header'ı ekliyor

**Konum:** `features/player/components/CustomPlayer.jsx` → `xhrSetup: xhr.setRequestHeader('Authorization', 'Bearer dummy_token_abc123')`

**Etki:** Üçüncü taraf CDN'lere (ör. `cdn.example.com`) giden **cross-origin** isteklerde `Authorization` header'ı CORS preflight (`OPTIONS`) tetikler; CDN `Access-Control-Allow-Headers: Authorization` döndürmüyorsa **istek tarayıcıda engellenir → oynatma başarısız**. Ayrıca sahte bir güvenlik hissi yaratıyor.

**Fix:** Header kaldırılır. Yetki URL imzası ile taşınır (SEC-02); başka bir origin'e kimlik bilgisi asla gönderilmez:

```js
xhrSetup(xhr, url) {
  // Kasıtlı olarak boş: yetki, backend'in imzaladığı manifest_url / segment URL'lerinde.
}
```

---

#### FE-04 · P1 · Token yönetimi: `localStorage`, refresh yok, her 401'de global logout

**Konum:** `core/api/axios.js`, `core/context/AuthContext.jsx`
- Access token `localStorage`'da → herhangi bir XSS'te kalıcı token hırsızlığı.
- Refresh mekanizması yok; 1 saatlik token dolunca kullanıcı oynatma ortasında çıkış yapar.
- **Herhangi bir** 401 (ör. `PROFILE_TOKEN_EXPIRED`, `SESSION_EXPIRED` heartbeat yanıtı) `auth:unauthorized` → tüm oturum kapanıyor.
- `withCredentials: true` + backend'in `login_user` ile cookie yazması → hibrit kimlik (SEC-05).
- `X-Device-ID` ve `X-Profile-Token` hiç gönderilmiyor (RT-05, RT-06).

**Fix — bellek içi access token, httpOnly refresh cookie, single-flight refresh, hata koduna göre davranış:**

```js
// src/core/api/client.js
import axios from 'axios';
import { env } from '@/core/config/env';
import { tokenStore } from '@/core/auth/tokenStore';     // bellek içi; sayfa yenilenince refresh ile geri gelir
import { deviceId } from '@/core/device/deviceId';
import { ApiError } from './ApiError';

export const api = axios.create({ baseURL: env.VITE_API_BASE_URL, withCredentials: true });

api.interceptors.request.use((config) => {
  const access = tokenStore.getAccess();
  if (access) config.headers.Authorization = `Bearer ${access}`;
  const profile = tokenStore.getProfile();
  if (profile) config.headers['X-Profile-Token'] = profile;
  config.headers['X-Device-ID'] = deviceId();
  return config;
});

let refreshing = null;                                     // single-flight: aynı anda tek refresh
const refreshOnce = () =>
  (refreshing ??= axios
    .post(`${env.VITE_API_BASE_URL}/v1/auth/refresh`, null, { withCredentials: true })   // httpOnly cookie
    .then((r) => tokenStore.setAccess(r.data.data.access_token))
    .finally(() => { refreshing = null; }));

api.interceptors.response.use(
  (res) => {
    const body = res.data;
    return body && typeof body === 'object' && 'success' in body ? body.data : body;    // ZARFI AÇ, MUTASYON YOK
  },
  async (error) => {
    const res = error.response;
    const code = res?.data?.error?.code;
    const original = error.config;

    if (res?.status === 401 && code === 'TOKEN_EXPIRED' && !original._retried) {
      original._retried = true;
      try { await refreshOnce(); return api(original); }
      catch { window.dispatchEvent(new CustomEvent('auth:logout', { detail: { reason: 'REFRESH_FAILED' } })); }
    }
    if (res?.status === 401 && code?.startsWith('PROFILE_')) {
      window.dispatchEvent(new CustomEvent('profile:reselect'));   // yalnızca profil seçimine dön
    }
    throw ApiError.from(error);
  }
);
```

```js
// src/core/device/deviceId.js
const KEY = 'neotv.device_id';
export function deviceId() {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) { id = crypto.randomUUID(); localStorage.setItem(KEY, id); }
    return id;
  } catch { return 'ephemeral'; }
}
```

```js
// src/core/api/ApiError.js
export class ApiError extends Error {
  constructor({ status, code, message, details }) {
    super(message ?? code ?? 'UNKNOWN');
    Object.assign(this, { status, code: code ?? 'UNKNOWN', details });
  }
  static from(axiosError) {
    const r = axiosError.response;
    const e = r?.data?.error ?? {};
    return new ApiError({ status: r?.status ?? 0, code: e.code ?? (r ? 'HTTP_' + r.status : 'NETWORK'),
                          message: e.message, details: e.details });
  }
}
```

UI metinleri `code` → i18n anahtarı eşlemesiyle üretilir (backend'in TR/EN karışık mesajları kullanıcıya gösterilmez).

---

#### FE-05 · P1 · API sözleşme kayması: frontend'in çağırdığı 5 uç backend'de yok

| Frontend çağrısı | Backend |
|---|---|
| `GET /admin/sessions` | yok (`/admin/sessions/live` var) |
| `POST /admin/refresh-m3u` | yok |
| `POST /admin/channels/delete-all` | yok |
| `POST /admin/channels/import-m3u` (multipart) | yok (`/admin/import-links` JSON) |
| `POST /admin/sessions/clear-all` | yok |
| `POST /admin/sessions/<id>/terminate` | var ama `501 NOT_IMPLEMENTED` |

**Kök neden:** Sözleşme kodda değil, iki ayrı kod tabanında elle tekrarlanıyor.

**Fix — schema-first sözleşme ve codegen:**
1. Backend uçları Pydantic request/response modelleri ile tanımlanır; `spectree` / `flask-openapi3` ile `/api/v1/openapi.json` üretilir.
2. Frontend: `openapi-typescript` ile tipler + `openapi-fetch` ile tipli istemci üretilir (`npm run gen:api`).
3. CI: backend'den üretilen spec ile commit'lenmiş spec arasında `oasdiff breaking` çalışır; kırıcı değişiklik → PR başarısız. Frontend `tsc --noEmit` (JS projesi için `// @ts-check` + JSDoc ya da kademeli TS geçişi) var olmayan uç çağrısını derleme anında yakalar.

```jsonc
// frontend/package.json (scripts)
"gen:api": "openapi-typescript ../openapi/openapi.json -o src/core/api/schema.d.ts",
"check:api": "npm run gen:api && git diff --exit-code src/core/api/schema.d.ts"
```

---

#### FE-06 · P2 · Kayıt formu backend'in kabul etmediği veriyi topluyor

`RegisterPage` e-posta, ad, soyad, ülke kodlu telefon topluyor; `register(username, password, fullPhone)` → `AuthContext.register` yalnızca `username, password` gönderiyor; backend `phone` parametresini yok sayıyor. Kullanıcıya veri toplandığı izlenimi verilip veri atılıyor (KVKK açısından da "amaçla sınırlılık" ihlali). Şifre kuralı yalnızca frontend'de (≥ 8), backend'de yok.

**Fix:** Kayıt şeması backend'de tek kaynak (`RegisterRequest` Pydantic: `username`, `email`, `password` min 10 + zxcvbn skoru), frontend şeması OpenAPI'den türetilir; toplanmayacak alan formdan çıkarılır.

---

#### FE-07 · P2 · `CustomPlayer` yaşam döngüsü sızıntıları

**Konum:** `features/player/components/CustomPlayer.jsx`
- Native HLS (Safari) ve progresif yolda `video.addEventListener('loadedmetadata', ...)` **kaldırılmıyor** → `streamUrl` her değiştiğinde handler birikir.
- `resumePosition` effect bağımlılığında → ilerleme kaydı sonrası prop değişirse **player sıfırdan kurulur**.
- `hlsRef.current` destroy sonrası `null`'lanmıyor; `video.src` temizlenmiyor (unmount sonrası arka planda indirme sürebilir).
- `hls._retried` monkey-patch.

**Fix — motor soyutlaması (4.10'daki `PlayerEngine`) ve deterministik temizlik:**

```js
// src/features/player/engines/hlsJsEngine.js
import Hls from 'hls.js';

export function createHlsJsEngine(video, { isLive, onFatal }) {
  const hls = new Hls({ enableWorker: true, lowLatencyMode: isLive, maxBufferLength: 30 });
  let networkRetries = 0;
  hls.on(Hls.Events.ERROR, (_e, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRetries++ < 3) return hls.startLoad();
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR) return hls.recoverMediaError();
    onFatal(data);
  });
  hls.attachMedia(video);
  return {
    load: (url) => hls.loadSource(url),
    destroy: () => { hls.destroy(); video.removeAttribute('src'); video.load(); },
  };
}

// CustomPlayer içinde:
useEffect(() => {
  const video = videoRef.current;
  if (!video || !manifestUrl) return undefined;
  const engine = pickEngine(video, { isLive, onFatal: setFatal });   // hls.js | native | shaka(DRM)
  engine.load(manifestUrl);
  return () => engine.destroy();
}, [manifestUrl, isLive]);                                           // resumePosition BURADA DEĞİL

useEffect(() => {
  const video = videoRef.current;
  if (!video || !resumeAt) return undefined;
  const seek = () => { video.currentTime = resumeAt; };
  video.addEventListener('loadedmetadata', seek, { once: true });
  return () => video.removeEventListener('loadedmetadata', seek);
}, [resumeAt]);
```

---

#### FE-08 · P2 · Katmanlar karışık; feature'lar arası doğrudan import; sabit route/nav

- Legacy `components/`, `pages/`, `context/` ile `features/`, `core/`, `shared/` bir arada; `Settings`, `Profile`, `Devices` legacy, `favorites/history/playlists` route'ları **placeholder `<div>`**.
- `features/playlist/pages/HomePage.jsx` → `@/features/epg/hooks/useLiveStreams` ve `@/features/billing/components/PremiumTab` (feature → feature iç import'u; `eslint-plugin-boundaries` bağımlılık olarak kurulu ama kural ihlali derleniyor).
- `AppRouter` ve `Sidebar` her yeni özellikte elle düzenlenmek zorunda (yeni özellik = merkezi dosyalarda değişiklik = birleştirme çatışması).
- `PremiumTab` (11.7 KB) ve `PremiumPage` (9.2 KB) aynı işin iki kopyası.

**Fix:** 4.10'daki **Feature Manifest + Registry**; feature'lar yalnızca birbirinin `index.js` public API'sini import eder; `eslint-plugin-boundaries` kuralı CI'da `error`.

---

### 3.I Kod Hijyeni ve Teknik Borç

#### HYG-01 · P2 · Çift implementasyonlar (silinecekler listesi)

| Silinecek | Canlıdaki karşılığı | Not |
|---|---|---|
| `app/routes/auth.py` | `app/modules/auth/routes.py` | Önce korumalar (rate limit, login guard) modüle taşınır (SEC-06) |
| `app/routes/billing.py`, `app/services/billing_service.py` | `app/modules/billing/*` | |
| `app/services/auth_service.py` | `app/modules/auth/services.py` | `load_user_from_request` legacy'yi kullanıyor → önce o taşınır |
| `app/core/celery_app.py`, `app/tasks/celery_app.py`, `app/tasks/celery_config.py`, `celery_worker.py` | `app/kernel/celery_factory.py` | ASY-01 |
| `app/services/stream_manager.py` | — | `transcoder/stream_manager.py` ile isim çakışması, kullanılmıyor |
| `app/services/transcoder/interfaces.py::IStorageAdapter` | `storage_adapter.py::IStorageAdapter` | **Aynı isimde iki farklı arayüz**, farklı metotlar |
| `app/models/background_job.py` | Celery | ASY-06 |
| `app/templates/*`, `app/static/{css,js}`, `routes/profile.py` (Jinja) | React SPA | İkinci, ölü UI |
| `frontend/src/components/SecurePlayer.jsx` | `features/playback` | FE-02 |
| `frontend/src/context/AuthContext.jsx`, `components/ErrorBoundary.jsx` | `core/`, `shared/` | |
| `features/billing/components/PremiumTab.jsx` | `PremiumPage` | |
| `Scripts/utils/debug_jwt.py`, `Scripts/batch/fix_db.bat`, `Scripts/maintenance/fix_*.py` | — | Tek seferlik onarım betikleri; secret içeriyor |

#### HYG-02 · P2 · "Bağlanmamış uzmanlık" envanteri

Aşağıdaki bileşenler kodda var ama **hiçbir istek yolunda gerçek iş yapmıyor**: `l1_l2_cache_response`, `invalidate_cache`, `chaos.maybe_inject_*` (`MockSettings` ile), `modules/search/*` (`es_client = None`, fallback `[]`), `zero_downtime_reindex` (alias `remove` aksiyonu wildcard ile tüm indeksleri hedefler), `ProfileContextService`, `LiveStreamService`, `EPGService`, `StreamConcurrencyGuard.acquire_slot/heartbeat/release_slot`, `LoginAttemptGuard` (canlı login'de), `UserId` value object, `Scripts/backfill_profile_id.py` (`db = None` ile ilk satırda döner), `BackgroundJob`.

**İlke:** Bir bileşen ya (a) bir manifest'e kayıtlı, testli ve bir uç tarafından kullanılıyor, ya da (b) silinir. "İleride lazım olur" kodu, okuyanı sistemin gerçekte yaptığı şey hakkında yanıltır — bu projedeki en pahalı borç budur.

#### HYG-03 · P3 · Diğer

- `print(...)` ile hata raporlama (`log_access`, `ChannelManager`) → `logging` + yapılandırılmış alanlar.
- Çıplak `except:` (`start.py`, `stream_manager.check_stream_status`, `stream_validator`) → `KeyboardInterrupt`/`SystemExit` yutulur.
- `User.query.get(...)` (SQLAlchemy 2.0'da legacy) → `db.session.get(User, id)`.
- Hata mesajları TR/EN karışık ve kullanıcıya doğrudan gösteriliyor → kod + i18n.
- `docs/schema.txt` gerçek yapıyı yansıtmıyor (`player.py`, `api.py`, `hls_handler.py` yok).
- `models/live.py::to_dict` → `playback_url` `http://localhost:8080` hardcoded.
- `routes/stream.py` içinde `bitdash-a.akamaihd.net → /hls-proxy` gibi **ortama özel hack** domain koduna gömülü.
- `DECORATOR_ORDER.md` kuralları doküman ile değil, **yapı** ile zorlanmalı (4.6'daki `endpoint()` kompozitörü).

---

### 3.J Test ve CI

#### TEST-01 · P0 · Fiilen sıfır çalışan test

**Kanıt:**
- `pytest.ini` → `testpaths = app/modules app/core app/shared_kernel`; `tests/test_validation_fix.py` bu yollarda değil → **hiç çalışmaz**.
- Toplanan tek test `app/core/tests/test_bootstrap_integration.py`; **assert satırı yorumda** → her koşulda geçer.
- `app/conftest.py` modül seviyesinde `from app import create_app` → import anında Redis client, tracing exporter, container guard'ları kurulur; `DATABASE_URL`'i ayarlasa da `Config` okumadığı için (CFG-01) testler SQLite dosyasına (`instance/database.db` — **geliştirici veritabanı**) karşı `db.drop_all()` çalıştırabilir.
- Frontend'de 3 adet bileşen testi var (`Button/Modal/Spinner`), `vitest` yapılandırması ve CI'da çalıştırma yok.

**Fix — test piramidi ve izole fixture'lar:**

```python
# tests/conftest.py
import pytest
from app import create_app
from app.kernel.settings import Settings
from app.kernel.db import db


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    return Settings(
        env="test",
        secret_key="t" * 48,
        database_url="postgresql+psycopg://postgres:test@localhost:5432/iptv_test",
        redis_state_url="redis://localhost:6379/15",
        celery_broker_url="memory://",
        profile_context_mode="strict",
        hls_output_root=tmp_path_factory.mktemp("hls"),
    )


@pytest.fixture(scope="session")
def app(settings):
    app = create_app(settings)
    app.config.update(TESTING=True, CELERY={**app.config["CELERY"], "task_always_eager": True})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture(autouse=True)
def _tx_rollback(app):
    """Her test kendi SAVEPOINT'inde; test sonunda geri alınır → testler arası sızıntı yok."""
    conn = db.engine.connect()
    trans = conn.begin()
    db.session.configure(bind=conn, join_transaction_mode="create_savepoint")
    yield
    db.session.remove()
    trans.rollback()
    conn.close()
```

```python
# tests/contract/test_payment_provider_contract.py — PORT sözleşme testi: her adapter AYNI testi geçer
import pytest
from app.modules.billing.adapters.fake import FakePaymentProvider
from app.modules.billing.adapters.hmac_webhook import WebhookSignatureError

@pytest.fixture(params=[FakePaymentProvider])           # yeni adapter = listeye 1 ekleme
def provider(request):
    return request.param.for_tests()

def test_rejects_tampered_webhook(provider):
    body, headers = provider.sign_sample_event("payment.succeeded", user_id=1, plan_id="duo")
    with pytest.raises(WebhookSignatureError):
        provider.verify_webhook(raw_body=body + b" ", headers=headers)
```

```python
# tests/architecture/test_manifests.py — mimari fitness function
from app.modules import INSTALLED_MODULES
from app.kernel.registry import ModuleRegistry, load_manifests
import pkgutil, app.modules as mods

def test_every_module_directory_is_installed_or_explicitly_ignored():
    on_disk = {m.name for m in pkgutil.iter_modules(mods.__path__) if m.ispkg}
    installed = {p.rsplit(".", 1)[-1] for p in INSTALLED_MODULES}
    assert on_disk - installed - {"_template"} == set(), "Kurulmamış (yetim) modül dizini var"

def test_registry_boots_cleanly():
    ModuleRegistry(load_manifests(INSTALLED_MODULES), disabled=frozenset()).resolve_order()
```

#### TEST-02 · P0 · CI iş akışı ilk adımda kırılıyor ve mimari sözleşme kendi kodunu ihlal ediyor

**Kanıt:** `.github/workflows/architecture-guard.yml`
- `python scripts/dev/...` — dizin adı `Scripts` (büyük S); Linux'ta dosya sistemi büyük/küçük harf duyarlı → **"No such file"**.
- `.importlinter` dosyası repoda yok; `git diff --exit-code .importlinter` **izlenmeyen** dosyada her zaman 0 döner → "drift" kontrolü hiçbir şeyi yakalamaz.
- Üretilen `layers` sözleşmesi `app.modules > app.shared_kernel > app.core` sırasında; bu sözleşmede alt katman üst katmanı import edemez. `app/core/outbox_dispatcher.py` ve `app/core/tasks.py` `app.shared_kernel`'i import ediyor → **sözleşme ihlali**, CI kırmızı.
- Sözleşmeler yalnızca `app.modules`'ü kapsıyor; kodun büyük kısmı (`app/routes`, `app/services`, `app/models`) hiçbir kurala tabi değil; modüller legacy'ye (`app.modules.auth.adapters → app.models.device`) serbestçe bağlanabiliyor.
- `actions/setup-python@v4`, Python 3.10 — geliştirme 3.12+.
- Frontend için hiçbir CI adımı yok.

**Fix — çalışan sözleşmeler:**

```ini
# .importlinter (elle yönetilir, generate edilmez — sözleşme koddur)
[importlinter]
root_package = app
include_external_packages = True

[importlinter:contract:layers]
name = Katmanlar: modules -> kernel -> shared_kernel
type = layers
layers =
    app.modules
    app.kernel
    app.shared_kernel

[importlinter:contract:module-independence]
name = Modüller birbirinin içine bakamaz (yalnızca *.api public yüzeyi)
type = independence
modules =
    app.modules.identity
    app.modules.catalog
    app.modules.playback
    app.modules.billing
    app.modules.drm
    app.modules.live
    app.modules.library
    app.modules.recommendations
    app.modules.devices
    app.modules.profile
ignore_imports =
    app.modules.*.** -> app.modules.*.api

[importlinter:contract:no-legacy]
name = Yeni modüller legacy katmana bağlanamaz
type = forbidden
source_modules = app.modules
forbidden_modules =
    app.routes
    app.services
    app.models

[importlinter:contract:egress]
name = Dış HTTP yalnızca EgressGateway üzerinden
type = forbidden
source_modules = app.modules
forbidden_modules =
    requests
    urllib.request
ignore_imports =
    app.modules.*.adapters.** -> requests

[importlinter:contract:shared-kernel-purity]
name = shared_kernel saf kalır (ORM/Flask/Celery yok)
type = forbidden
source_modules = app.shared_kernel
forbidden_modules =
    flask
    flask_sqlalchemy
    sqlalchemy
    celery
    redis
```

> `independence` sözleşmesindeki `ignore_imports` jokerleri import-linter sürümüne göre farklı yorumlanabilir; kesin kural için her modül çifti yerine **`app.modules.X.api` dışındaki her alt paketi `forbidden`** olarak tanımlayan küçük bir üretici betik (`tools/gen_contracts.py`) ve onun çıktısının commit'lenmesi önerilir. Üretilen dosya izlenir ve CI `--exit-code` ile kayma kontrolü yapar.

> `shared_outbox` modeli ORM içerdiği için `shared_kernel`'den `app.kernel.outbox`'a taşınır; `shared_kernel` yalnızca saf event dataclass'ları ve value object'leri barındırır.

```yaml
# .github/workflows/ci.yml
name: CI
on: [pull_request, push]
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_PASSWORD: test, POSTGRES_DB: iptv_test }, ports: ["5432:5432"],
                  options: "--health-cmd pg_isready --health-interval 5s --health-retries 10" }
      redis:    { image: redis:7, ports: ["6379:6379"] }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements.lock -r requirements-dev.lock
      - run: ruff check . && ruff format --check .
      - run: mypy app
      - run: lint-imports
      - run: pytest -q --cov=app --cov-fail-under=70
      - run: flask --app app.wsgi:app openapi dump > /tmp/openapi.json && oasdiff breaking openapi/openapi.json /tmp/openapi.json --fail-on ERR
        env: { SECRET_KEY: "${{ secrets.CI_SECRET_KEY }}", DATABASE_URL: "postgresql+psycopg://postgres:test@localhost:5432/iptv_test" }
  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci
      - run: npm run check:api
      - run: npm run lint -- --max-warnings=0
      - run: npx vitest run --coverage
      - run: npm run build
```

---

## 4. Hedef Mimari: "Puzzle" Modular Monolith (To-Be)

> **Amaç:** Bir özelliği eklemek, çıkarmak ya da değiştirmek **tek bir parçaya dokunmak** anlamına gelsin; parçalar birbirine yanlış oturursa sistem bunu **çalışma zamanında değil boot anında, isimlendirilmiş bir hata ile** söylesin. Mikroservis maliyetine girmeden mikroservis sınırları: tek deploy, tek veritabanı, ama sözleşme ile ayrılmış bounded context'ler. İhtiyaç olursa herhangi bir modül, sözleşmesi değişmeden ayrı bir servise çıkarılabilir.

### 4.1 Tasarım İlkeleri (Mimari Anayasa)

| # | İlke | Somut kural | Nasıl zorlanır |
|---|---|---|---|
| 1 | **Modül = puzzle parçası = bounded context** | Bir modül kendi tablolarının, route'larının, task'larının, event tüketicilerinin, izinlerinin, hata kodlarının ve ayarlarının **tek sahibidir** | Manifest + tablo prefix'i (`billing_*`) + import-linter |
| 2 | **Açık ilan, örtük keşif yok** | Modül ne sağladığını (`provides`) ve neye ihtiyaç duyduğunu (`requires`) manifest'te ilan eder | `ModuleRegistry` boot doğrulaması |
| 3 | **Sessiz hata yok** | Eksik parça → `MissingCapabilityError`, çakışan parça → `DuplicateCapabilityError`/`DuplicateRouteError`, devre dışı bağımlılık → `DisabledDependencyError`; boot durur | Kernel hata hiyerarşisi |
| 4 | **Public yüzey = `api.py`** | Başka modül yalnızca `app.modules.X.api`'yi import edebilir (port'lar, DTO'lar, event tipleri) | import-linter `independence` + `forbidden` |
| 5 | **Senkron okuma port ile, yan etki event ile** | "Bana X'i söyle" → port çağrısı; "X oldu, ilgilenen tepki versin" → outbox event | Kod incelemesi + kural: modüller arası **yazma** çağrısı yok |
| 6 | **Composition root tek** | Modüller global singleton import etmez; bağımlılıklar `Container`'dan çözülür | `core/container.py`'deki import-time nesneler kaldırılır |
| 7 | **Domain framework-bağımsız** | `domain/` Flask, SQLAlchemy, Redis, Celery import etmez | import-linter `forbidden` |
| 8 | **Sözleşme koddur** | HTTP: Pydantic → OpenAPI → TS tipleri; Port: Protocol + contract test; Event: versiyonlu dataclass + upcaster | CI: `oasdiff`, contract test suite |
| 9 | **Her parça kapatılabilir** | `DISABLED_MODULES=recommendations` → modül yüklenmez; ona `requires` ile bağlı modül varsa boot **isimlendirerek** reddeder; `optional_requires` ile bağlı olan graceful degrade eder | Registry |
| 10 | **Frontend aynı aynada** | Her backend modülünün karşılığı bir frontend feature manifest'i; route/nav/izin merkezî dosyada değil feature'da | `buildRegistry()` + `eslint-plugin-boundaries` |

### 4.2 Hedef Dizin Yapısı

```text
IPTV_Project/
├── app/
│   ├── __init__.py                  # create_app(settings) — composition root (20 satır)
│   ├── wsgi.py                      # app + celery (web, worker, beat için tek giriş)
│   ├── kernel/                      # Çekirdek: iş kuralı İÇERMEZ
│   │   ├── settings.py              # Pydantic Settings (CFG-01)
│   │   ├── container.py             # DI container (isimlendirilmiş hatalar)
│   │   ├── manifest.py              # ModuleManifest, RouteSpec, SubscriptionSpec
│   │   ├── registry.py              # ModuleRegistry: doğrulama + topolojik boot
│   │   ├── errors.py                # KernelError hiyerarşisi
│   │   ├── db.py                    # db (naming convention), utcnow_column, UnitOfWork
│   │   ├── time.py                  # Clock portu, utcnow()
│   │   ├── celery_factory.py        # TEK Celery (ASY-01)
│   │   ├── events/                  # EventBus, EventRegistry (versiyon + upcaster)
│   │   ├── outbox/                  # OutboxEvent, Inbox, dispatch/deliver task'ları
│   │   ├── http/                    # endpoint() kompozitörü, ApiError, ErrorMap, envelope, request-id
│   │   ├── security/                # TokenService, UrlSigner, EgressGateway, permissions
│   │   ├── resilience/              # CircuitBreaker, best_effort, rate limiter, idempotency
│   │   ├── cache/                   # StampedeGuard (codec'li)
│   │   └── observability/           # logging (JSON), tracing (opsiyonel), metrics
│   ├── shared_kernel/               # SAF: event dataclass'ları, value object'ler, enum'lar
│   └── modules/
│       ├── __init__.py              # INSTALLED_MODULES = (...)  ← modül ekle/çıkar = 1 satır
│       ├── _template/               # `flask kernel new-module <ad>` iskeleti
│       ├── identity/                # kullanıcı, kimlik doğrulama, token, rol/izin
│       ├── profile/                 # profiller, PIN, profil bağlamı
│       ├── devices/                 # cihaz kaydı/yönetimi
│       ├── catalog/                 # kanal/VOD kataloğu, playlist kaynakları, import/sync
│       ├── playback/                # PlaybackGate, oturumlar, kaynak çözümleyiciler, QoE
│       ├── live/                    # canlı kanallar, ingest, transcoder orkestrasyonu, HLS asset
│       ├── drm/                     # içerik anahtarları (KeyVault), lisanslar
│       ├── billing/                 # plan kataloğu, abonelik durum makinesi, ödeme sağlayıcıları
│       ├── library/                 # favoriler, izleme geçmişi, devam et
│       ├── recommendations/         # trending, kişisel öneriler (read model)
│       └── admin/                   # yönetim uçları (diğer modüllerin api.py'lerini orkestre eder)
├── migrations/
├── tests/                           # entegrasyon + mimari (fitness function) testleri
├── tools/                           # devctl.py, gen_contracts.py, betikler
├── deploy/                          # nginx, docker, k8s
├── openapi/openapi.json             # commit'lenen sözleşme (CI diff)
└── frontend/
    └── src/
        ├── app/                     # AppProviders, AppShell, router factory, featureKit
        ├── core/                    # api client (generated), auth, profile, device, config
        ├── shared/                  # UI kit, hooks, utils — feature bilmez
        └── features/
            ├── index.js             # FEATURES = [...]  ← feature ekle/çıkar = 1 satır
            ├── auth/  catalog/  live/  playback/  billing/  devices/  profile/  library/  admin/
            └── <feature>/manifest.js, index.js (public API), api/, hooks/, components/, pages/
```

**Modül içi standart yerleşim (her modülde aynı — kas hafızası):**

```text
app/modules/billing/
├── manifest.py        # TEK giriş noktası: kernel yalnızca bunu okur
├── api.py             # PUBLIC yüzey: port'lar, DTO'lar, event tipleri (başka modüller YALNIZCA bunu import eder)
├── domain/            # saf iş kuralları: durum makinesi, value object, domain hataları
├── services.py        # use-case'ler (application layer) — UoW ile transaction sınırı
├── ports.py           # bu modülün DIŞARIDAN ihtiyaç duyduğu arayüzler (PaymentProvider...)
├── adapters/          # port implementasyonları: sql_repo.py, stripe.py, fake.py
├── http/              # routes.py (blueprint), schemas.py (Pydantic request/response)
├── handlers.py        # event tüketicileri
├── tasks.py           # Celery task'ları
├── models.py          # ORM — yalnızca billing_* tabloları
└── tests/             # unit + contract (co-located)
```

### 4.3 Modül Sözleşmesi: `ModuleManifest` ve `ModuleRegistry`

```python
# app/kernel/errors.py
class KernelError(RuntimeError):
    """Boot'u durduran, isimlendirilmiş mimari hata. Mesaj her zaman sahibi modülü içerir."""


class ModuleContractError(KernelError):
    def __init__(self, module: str, detail: str):
        super().__init__(f"[module:{module}] sözleşme ihlali: {detail}")
        self.module, self.detail = module, detail


class DuplicateModuleError(KernelError): ...
class UnknownModuleError(KernelError): ...          # DISABLED_MODULES'ta yazım hatası sessiz geçmez


class DuplicateCapabilityError(KernelError):
    def __init__(self, capability: str, first: str, second: str):
        super().__init__(f"'{capability}' hem '{first}' hem '{second}' tarafından sağlanıyor")


class MissingCapabilityError(KernelError):
    def __init__(self, module: str, capability: str):
        super().__init__(f"[module:{module}] '{capability}' gerektiriyor ama hiçbir kurulu modül sağlamıyor")


class DisabledDependencyError(KernelError):
    def __init__(self, module: str, capability: str, provider: str):
        super().__init__(f"[module:{module}] '{capability}' gerektiriyor; sağlayıcı '{provider}' DEVRE DIŞI")


class CircularModuleDependencyError(KernelError): ...
class DuplicateRouteError(KernelError): ...
class DuplicateScheduleError(KernelError):
    def __init__(self, schedule: str, owner: str):
        super().__init__(f"[module:{owner}] beat görevi '{schedule}' zaten tanımlı")


class HandlerImportError(KernelError):
    def __init__(self, module: str, path: str, cause: BaseException):
        super().__init__(f"[module:{module}] '{path}' import edilemedi: {cause!r}")
        self.__cause__ = cause
```

```python
# app/kernel/manifest.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

ServiceKey = type | str


@dataclass(frozen=True, slots=True)
class RouteSpec:
    blueprint: str                       # "app.modules.billing.http.routes:billing_bp" (lazy, dotted)
    url_prefix: str                      # "/api/v1/billing"


@dataclass(frozen=True, slots=True)
class SubscriptionSpec:
    event: str                           # "user.registered"
    consumer: str                        # "billing.create_free_subscription" (global benzersiz)
    handler: str                         # "app.modules.billing.handlers:on_user_registered"
    queue: str = "outbox"


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    version: str
    provides: Mapping[str, ServiceKey] = field(default_factory=dict)    # capability → container anahtarı
    requires: frozenset[str] = frozenset()
    optional_requires: frozenset[str] = frozenset()
    services: Callable[["Container"], None] | None = None
    routes: tuple[RouteSpec, ...] = ()
    subscriptions: tuple[SubscriptionSpec, ...] = ()
    task_modules: tuple[str, ...] = ()
    beat_schedule: Mapping[str, dict[str, Any]] = field(default_factory=dict)
    task_routes: Mapping[str, dict[str, str]] = field(default_factory=dict)
    error_map: Mapping[type[Exception], tuple[int, str]] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()
    playback_policies: tuple[str, ...] = ()      # 4.7 — çoklu sağlayıcılı extension point
    source_resolvers: tuple[str, ...] = ()       # 4.7

    def __post_init__(self):
        if not self.name.isidentifier():
            raise ValueError(f"Geçersiz modül adı: {self.name!r}")
        overlap = self.requires & self.optional_requires
        if overlap:
            raise ValueError(f"[{self.name}] aynı capability hem zorunlu hem opsiyonel: {overlap}")
```

```python
# app/kernel/registry.py
from __future__ import annotations
import importlib
from collections import deque
from typing import Sequence

from flask import Flask
from app.kernel.errors import (
    CircularModuleDependencyError, DisabledDependencyError, DuplicateCapabilityError, DuplicateModuleError,
    DuplicateRouteError, HandlerImportError, MissingCapabilityError, ModuleContractError, UnknownModuleError,
)
from app.kernel.manifest import ModuleManifest


def import_attr(path: str, *, owner: str):
    mod_path, sep, attr = path.partition(":")
    if not sep:
        raise ModuleContractError(owner, f"'{path}' 'paket.modul:nesne' formatında değil")
    try:
        mod = importlib.import_module(mod_path)
    except Exception as e:                                  # import zincirindeki HER hata sahibine atfedilir
        raise HandlerImportError(owner, path, e) from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise ModuleContractError(owner, f"'{path}' içinde '{attr}' yok") from e


def load_manifests(installed: Sequence[str]) -> list[ModuleManifest]:
    out = []
    for pkg in installed:
        m = import_attr(f"{pkg}.manifest:manifest", owner=pkg.rsplit(".", 1)[-1])
        if not isinstance(m, ModuleManifest):
            raise ModuleContractError(pkg, "manifest bir ModuleManifest örneği değil")
        out.append(m)
    return out


class ModuleRegistry:
    def __init__(self, manifests: Sequence[ModuleManifest], *, disabled: frozenset[str]):
        names = [m.name for m in manifests]
        dups = {n for n in names if names.count(n) > 1}
        if dups:
            raise DuplicateModuleError(f"Aynı ada sahip modüller: {sorted(dups)}")
        unknown = disabled - set(names)
        if unknown:
            raise UnknownModuleError(f"DISABLED_MODULES içinde bilinmeyen modül(ler): {sorted(unknown)}")
        self._active = [m for m in manifests if m.name not in disabled]
        self._disabled = [m for m in manifests if m.name in disabled]
        self._order: list[ModuleManifest] | None = None

    # ── 1) Statik doğrulama + topolojik sıralama ────────────────────────
    def resolve_order(self) -> list[ModuleManifest]:
        providers: dict[str, str] = {}
        for m in self._active:
            for cap in m.provides:
                if cap in providers:
                    raise DuplicateCapabilityError(cap, providers[cap], m.name)
                providers[cap] = m.name
        disabled_caps = {cap: m.name for m in self._disabled for cap in m.provides}

        deps: dict[str, set[str]] = {m.name: set() for m in self._active}
        for m in self._active:
            for cap in sorted(m.requires):
                if cap in providers:
                    deps[m.name].add(providers[cap])
                elif cap in disabled_caps:
                    raise DisabledDependencyError(m.name, cap, disabled_caps[cap])
                else:
                    raise MissingCapabilityError(m.name, cap)
            for cap in m.optional_requires:
                if cap in providers:
                    deps[m.name].add(providers[cap])
            deps[m.name].discard(m.name)

        # Kahn — deterministik (alfabetik) sıra; aynı girdi = aynı boot sırası
        by_name = {m.name: m for m in self._active}
        indeg = {n: len(d) for n, d in deps.items()}
        dependents: dict[str, set[str]] = {n: set() for n in deps}
        for n, ds in deps.items():
            for d in ds:
                dependents[d].add(n)
        queue = deque(sorted(n for n, k in indeg.items() if k == 0))
        order: list[ModuleManifest] = []
        while queue:
            n = queue.popleft()
            order.append(by_name[n])
            for nxt in sorted(dependents[n]):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(self._active):
            cyclic = sorted(n for n, k in indeg.items() if k > 0)
            raise CircularModuleDependencyError(f"Döngüsel modül bağımlılığı: {cyclic}")
        self._order = order
        return order

    # ── 2) Boot: servis → route → abonelik → hata eşlemesi → doğrulama ───
    def boot(self, app: Flask, container, bus, error_map) -> None:
        from app.kernel.events.bus import Subscription
        order = self._order or self.resolve_order()
        for m in order:
            if m.services:
                with container.owned_by(m.name):
                    m.services(container)
            for cap, key in m.provides.items():
                if not container.has(key):
                    raise ModuleContractError(m.name, f"'{cap}' sağladığını ilan etti ama '{key}' kaydetmedi")
            for spec in m.routes:
                bp = import_attr(spec.blueprint, owner=m.name)
                if bp.name in app.blueprints:
                    raise DuplicateRouteError(f"[module:{m.name}] blueprint adı '{bp.name}' zaten kayıtlı")
                app.register_blueprint(bp, url_prefix=spec.url_prefix)
            for s in m.subscriptions:
                bus.subscribe(Subscription(s.event, s.consumer, import_attr(s.handler, owner=m.name), s.queue))
            for exc, (status, code) in m.error_map.items():
                error_map.register(exc, status=status, code=code, owner=m.name)
        self._assert_no_url_collisions(app)
        app.extensions["modules"] = {m.name: m.version for m in order}

    @staticmethod
    def _assert_no_url_collisions(app: Flask) -> None:
        seen: dict[tuple[str, frozenset[str]], str] = {}
        for rule in app.url_map.iter_rules():
            key = (rule.rule, frozenset(rule.methods - {"HEAD", "OPTIONS"}))
            if key in seen and seen[key] != rule.endpoint:
                raise DuplicateRouteError(f"{rule.rule} {sorted(key[1])}: '{seen[key]}' ve '{rule.endpoint}'")
            seen[key] = rule.endpoint
```

```python
# app/modules/__init__.py
"""Kurulu modüller. Sıra önemsizdir — registry bağımlılıklardan sırayı türetir.
Modül eklemek/çıkarmak = bu tuple'a 1 satır. Geçici kapatmak = DISABLED_MODULES ortam değişkeni."""
INSTALLED_MODULES: tuple[str, ...] = (
    "app.modules.identity",
    "app.modules.profile",
    "app.modules.devices",
    "app.modules.catalog",
    "app.modules.billing",
    "app.modules.playback",
    "app.modules.live",
    "app.modules.drm",
    "app.modules.library",
    "app.modules.recommendations",
    "app.modules.admin",
)
```

**Örnek manifest (billing):**

```python
# app/modules/billing/manifest.py
from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.modules.billing.api import EntitlementService, PlanCatalog
from app.modules.billing.domain.errors import UnknownPlanError
from app.modules.billing.domain.subscription_state import IllegalTransitionError


def _services(c) -> None:
    from app.modules.billing.adapters.sql_repo import SqlSubscriptionRepository
    from app.modules.billing.catalog import DEFAULT_CATALOG
    from app.modules.billing.services import BillingService
    from app.kernel.time import Clock

    c.register(PlanCatalog, lambda c: DEFAULT_CATALOG)
    c.register("billing.subscriptions", lambda c: SqlSubscriptionRepository(c.resolve("db_session")), lifetime="request")
    c.register(EntitlementService, lambda c: EntitlementService(
        c.resolve("billing.subscriptions"), c.resolve(PlanCatalog), c.resolve(Clock)), lifetime="request")
    c.register(BillingService, lambda c: BillingService(
        c.resolve("uow_factory"), c.resolve(PlanCatalog), c.resolve("billing.payment_providers")), lifetime="request")


manifest = ModuleManifest(
    name="billing",
    version="2.0.0",
    provides={"billing.entitlements": EntitlementService, "billing.plans": PlanCatalog},
    requires=frozenset({"identity.users"}),
    services=_services,
    routes=(RouteSpec("app.modules.billing.http.routes:billing_bp", "/api/v1/billing"),),
    subscriptions=(
        SubscriptionSpec("user.registered", "billing.create_free_subscription",
                         "app.modules.billing.handlers:on_user_registered"),
    ),
    task_modules=("app.modules.billing.tasks",),
    beat_schedule={"billing.expire-due": {"task": "billing.expire_due_subscriptions", "schedule": 300.0}},
    error_map={UnknownPlanError: (400, "INVALID_PLAN"),
               IllegalTransitionError: (409, "ILLEGAL_SUBSCRIPTION_TRANSITION")},
    permissions=("billing:admin",),
)
```

**Boot-time hata örnekleri** (hepsi uygulama ayağa kalkmadan, log'un ilk satırında):

```text
MissingCapabilityError: [module:playback] 'billing.entitlements' gerektiriyor ama hiçbir kurulu modül sağlamıyor
DisabledDependencyError: [module:playback] 'billing.entitlements' gerektiriyor; sağlayıcı 'billing' DEVRE DIŞI
DuplicateCapabilityError: 'catalog.read' hem 'catalog' hem 'catalog_v2' tarafından sağlanıyor
HandlerImportError: [module:billing] 'app.modules.billing.handlers:on_user_registered' import edilemedi: ModuleNotFoundError("No module named 'stripe'")
ModuleContractError: [module:drm] 'drm.keys' sağladığını ilan etti ama 'KeyVault' kaydetmedi
UnknownModuleError: DISABLED_MODULES içinde bilinmeyen modül(ler): ['recomendations']
```

### 4.4 Dependency Injection Container

```python
# app/kernel/container.py
from __future__ import annotations
import threading
from contextlib import contextmanager
from typing import Any, Callable, Literal

from flask import g, has_app_context

Key = type | str
Lifetime = Literal["singleton", "request", "transient"]


class ServiceNotRegisteredError(LookupError):
    def __init__(self, key: Key):
        super().__init__(f"'{_name(key)}' kayıtlı değil — bu servisi sağlaması gereken modülün "
                         f"manifest.provides/services tanımını ve INSTALLED_MODULES'u kontrol edin")


class DuplicateServiceError(RuntimeError): ...
class CircularServiceDependencyError(RuntimeError): ...


def _name(key: Key) -> str:
    return key if isinstance(key, str) else f"{key.__module__}.{key.__qualname__}"


class Container:
    def __init__(self) -> None:
        self._factories: dict[Key, tuple[Callable[["Container"], Any], Lifetime, str]] = {}
        self._singletons: dict[Key, Any] = {}
        self._lock = threading.RLock()
        self._local = threading.local()
        self._owner = "kernel"

    @contextmanager
    def owned_by(self, owner: str):
        prev, self._owner = self._owner, owner
        try:
            yield self
        finally:
            self._owner = prev

    def register(self, key: Key, factory: Callable[["Container"], Any], *,
                 lifetime: Lifetime = "singleton", replace: bool = False) -> None:
        with self._lock:
            if key in self._factories and not replace:
                raise DuplicateServiceError(
                    f"'{_name(key)}' zaten '{self._factories[key][2]}' tarafından kayıtlı; '{self._owner}' tekrar deniyor")
            self._factories[key] = (factory, lifetime, self._owner)
            self._singletons.pop(key, None)

    def override(self, key: Key, instance: Any) -> None:
        """Testler için: kayıtlı servisi hazır bir örnekle değiştirir."""
        self.register(key, lambda _c: instance, replace=True)

    def has(self, key: Key) -> bool:
        return key in self._factories

    def resolve(self, key: Key) -> Any:
        try:
            factory, lifetime, _owner = self._factories[key]
        except KeyError:
            raise ServiceNotRegisteredError(key) from None

        if lifetime == "singleton":
            with self._lock:
                if key not in self._singletons:
                    self._singletons[key] = self._build(key, factory)
                return self._singletons[key]
        if lifetime == "request":
            if not has_app_context():
                raise RuntimeError(f"'{_name(key)}' request-scoped; app context dışında çözülemez")
            scope = g.setdefault("_di_scope", {})
            if key not in scope:
                scope[key] = self._build(key, factory)
            return scope[key]
        return self._build(key, factory)

    def _build(self, key: Key, factory):
        stack: list[Key] = getattr(self._local, "stack", [])
        if key in stack:
            chain = " → ".join(_name(k) for k in [*stack, key])
            raise CircularServiceDependencyError(chain)
        self._local.stack = [*stack, key]
        try:
            return factory(self)
        finally:
            self._local.stack = stack


def resolve(key: Key) -> Any:
    from flask import current_app
    return current_app.extensions["container"].resolve(key)
```

### 4.5 Composition Root (`create_app`)

```python
# app/__init__.py
from flask import Flask
from app.kernel.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    app = Flask(__name__)
    app.config.from_mapping(settings.flask_config())

    from app.kernel.db import db, migrate
    from app.kernel.container import Container
    from app.kernel.bootstrap import register_kernel_services, install_http, install_observability
    from app.kernel.registry import ModuleRegistry, load_manifests
    from app.kernel.celery_factory import create_celery
    from app.kernel.events.bus import EventBus
    from app.kernel.http.errors import ErrorMap
    from app.modules import INSTALLED_MODULES

    db.init_app(app)
    migrate.init_app(app, db)

    container = Container()
    app.extensions["container"] = container
    register_kernel_services(container, settings)        # Settings, redis, egress, signer, tokens, bus, uow, clock...

    install_http(app, settings)                           # CORS, request-id, JSON hata zarfı, ErrorMap handler
    install_observability(app, settings)                  # JSON log; OTel yalnızca endpoint varsa

    registry = ModuleRegistry(load_manifests(INSTALLED_MODULES), disabled=settings.disabled_modules)
    order = registry.resolve_order()
    registry.boot(app, container, container.resolve(EventBus), container.resolve(ErrorMap))
    create_celery(app, order)

    app.extensions["module_registry"] = registry
    return app
```

### 4.6 HTTP Katmanı: Kompozit `endpoint()`, hata taksonomisi, versiyonlama

Decorator sırası **dokümantasyonla değil, yapıyla** garanti edilir (`DECORATOR_ORDER.md` → kod):

```python
# app/kernel/http/endpoint.py
from dataclasses import dataclass
from typing import Literal
from flask_login import login_required
from app.kernel.observability.tracing import traced
from app.kernel.resilience.rate_limit import rate_limit_ip, rate_limit_user
from app.kernel.resilience.idempotency import idempotent
from app.kernel.security.permissions import require_permission
from app.kernel.http.profile_context import require_profile_context


@dataclass(frozen=True)
class Rate:
    scope: str
    rps: int
    burst: int = 5


def endpoint(*, auth: Literal["public", "user"] = "user", rate: Rate | None = None,
             permission: str | None = None, profile: bool = False, idempotency_scope: str | None = None):
    """Çalışma zamanı sırası: traced → auth → rate → permission → profile → idempotency → handler."""
    if auth == "public" and (permission or profile):
        raise ValueError("public endpoint'te permission/profile kullanılamaz")

    def deco(fn):
        wrapped = fn
        if idempotency_scope:
            wrapped = idempotent(scope=idempotency_scope)(wrapped)
        if profile:
            wrapped = require_profile_context(wrapped)
        if permission:
            wrapped = require_permission(permission)(wrapped)
        if rate:
            limiter = rate_limit_user if auth == "user" else rate_limit_ip
            wrapped = limiter(scope=rate.scope, rps=rate.rps, burst=rate.burst)(wrapped)
        if auth == "user":
            wrapped = login_required(wrapped)
        return traced(f"{fn.__module__}.{fn.__qualname__}")(wrapped)
    return deco


# kullanım
@playback_bp.post("/sessions")
@endpoint(rate=Rate("playback.open", rps=3, burst=5), profile=True, idempotency_scope="playback.open")
def open_session():
    ...
```

```python
# app/kernel/http/errors.py
from __future__ import annotations
import logging, uuid
from flask import Flask, g, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

_log = logging.getLogger("http.errors")


class ApiError(Exception):
    def __init__(self, code: str, status: int = 400, message: str | None = None, details: dict | None = None):
        super().__init__(message or code)
        self.code, self.status, self.message, self.details = code, status, message, details


class DuplicateErrorMappingError(RuntimeError): ...


class ErrorMap:
    """Domain hataları HTTP'den habersizdir; modüller manifest.error_map ile eşleme katkısı yapar."""
    def __init__(self):
        self._map: dict[type[Exception], tuple[int, str, str]] = {}

    def register(self, exc: type[Exception], *, status: int, code: str, owner: str) -> None:
        if exc in self._map:
            raise DuplicateErrorMappingError(f"{exc.__name__}: '{self._map[exc][2]}' ve '{owner}'")
        self._map[exc] = (status, code, owner)

    def lookup(self, err: Exception) -> tuple[int, str] | None:
        for klass in type(err).__mro__:
            if klass in self._map:
                status, code, _ = self._map[klass]
                return status, code
        return None


def _envelope(code: str, status: int, message: str | None = None, details=None):
    body = {"success": False, "error": {"code": code, "message": message or code,
                                        "request_id": g.get("request_id")}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def install_error_handlers(app: Flask, error_map: ErrorMap) -> None:
    @app.errorhandler(ApiError)
    def _api(e: ApiError):
        return _envelope(e.code, e.status, e.message, e.details)

    @app.errorhandler(ValidationError)
    def _validation(e: ValidationError):
        return _envelope("VALIDATION_FAILED", 422, details=e.errors(include_url=False))

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        return _envelope(f"HTTP_{e.code}", e.code or 500, e.description)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        mapped = error_map.lookup(e)
        if mapped:
            return _envelope(mapped[1], mapped[0])
        incident = uuid.uuid4().hex[:12]
        _log.exception("unhandled incident=%s", incident)
        return _envelope("INTERNAL_ERROR", 500, details={"incident": incident})
```

- Tüm yeni uçlar `/api/v1/...`; legacy uçlar geçiş boyunca `/api/...` altında **dokunulmadan** yaşar (kırılmasız geçiş), `Deprecation` + `Sunset` header'ları ile işaretlenir.
- Request/response gövdeleri Pydantic modelleri; `spectree`/`flask-openapi3` ile `openapi.json` otomatik.

### 4.7 Playback Pipeline: Genişletilebilir Politika Zinciri ve Kaynak Çözümleyiciler

Oynatma, sistemin kalbi ve en çok değişecek yeri (yeni içerik türü, yeni DRM, coğrafi kısıt, reklam, ebeveyn kontrolü...). Bugün bu kurallar `routes/stream.py` içinde `if` blokları olarak duruyor (kids filtresi, bitdash hack'i). Hedef: **her kural ayrı bir parça**, herhangi bir modül manifest'iyle katkı yapabilir; yeni kural = yeni sınıf + manifest'te bir satır.

```python
# app/modules/playback/api.py
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ContentKind(StrEnum):
    VOD_EXTERNAL = "vod_external"       # dış URL (M3U kaynaklı)
    LIVE_EXTERNAL = "live_external"     # dış HLS kaynağı
    LIVE_INGEST = "live_ingest"         # kendi RTMP ingest + transcoder
    VOD_DRM = "vod_drm"                 # şifreli VOD


@dataclass(frozen=True, slots=True)
class ContentRef:
    kind: ContentKind
    id: int

    @classmethod
    def parse(cls, raw: str) -> "ContentRef":        # "vod_external:123"
        kind, _, ident = raw.partition(":")
        return cls(ContentKind(kind), int(ident))


@dataclass(frozen=True, slots=True)
class PlaybackContext:
    user_id: int
    profile_id: int
    is_kids: bool
    device_key: str
    ip: str
    user_agent: str
    content: ContentRef


@dataclass(frozen=True, slots=True)
class Deny:
    code: str
    message: str


class PlaybackPolicy(Protocol):
    name: str
    order: int                                      # düşük önce; maliyetli/yan etkili kurallar sona
    def evaluate(self, ctx: PlaybackContext) -> Deny | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    manifest_url: str                               # imzalı; origin URL ASLA
    drm: dict | None = None                         # {"type": "widevine", "license_url": "..."}
    is_live: bool = False


class SourceResolver(Protocol):
    kind: ContentKind
    def resolve(self, ctx: PlaybackContext) -> ResolvedSource: ...
```

```python
# app/modules/playback/services/gate.py
class PlaybackDeniedError(Exception):
    def __init__(self, deny: "Deny", policy: str):
        super().__init__(deny.code); self.deny, self.policy = deny, policy


class DuplicatePolicyError(RuntimeError): ...
class NoSourceResolverError(LookupError): ...


class PlaybackGate:
    def __init__(self, policies: list[PlaybackPolicy], resolvers: list[SourceResolver]):
        names = [p.name for p in policies]
        if len(names) != len(set(names)):
            raise DuplicatePolicyError(f"Aynı isimli politikalar: {names}")
        self._policies = sorted(policies, key=lambda p: (p.order, p.name))
        self._resolvers: dict[ContentKind, SourceResolver] = {}
        for r in resolvers:
            if r.kind in self._resolvers:
                raise DuplicatePolicyError(f"{r.kind} için iki resolver: {type(self._resolvers[r.kind]).__name__}, {type(r).__name__}")
            self._resolvers[r.kind] = r

    def authorize(self, ctx: PlaybackContext) -> ResolvedSource:
        for p in self._policies:
            deny = p.evaluate(ctx)
            if deny:
                raise PlaybackDeniedError(deny, p.name)
        try:
            resolver = self._resolvers[ctx.content.kind]
        except KeyError:
            raise NoSourceResolverError(f"{ctx.content.kind} için kayıtlı SourceResolver yok "
                                        f"(ilgili modül kurulu/etkin mi?)") from None
        return resolver.resolve(ctx)
```

```python
# Örnek politikalar — her biri farklı modülden gelebilir
class EntitlementPolicy:                       # billing.entitlements kullanır
    name, order = "entitlement", 10
    def __init__(self, ent, catalog): self._ent, self._catalog = ent, catalog
    def evaluate(self, ctx):
        tier = self._catalog.required_tier(ctx.content)
        if not self._ent.for_user(ctx.user_id).allows(tier):
            return Deny("UPGRADE_REQUIRED", "Bu içerik planınıza dahil değil")


class KidsRatingPolicy:                        # catalog.ratings kullanır; "adult" string araması YOK
    name, order = "kids_rating", 20
    def __init__(self, ratings): self._ratings = ratings
    def evaluate(self, ctx):
        if ctx.is_kids and not self._ratings.is_kids_safe(ctx.content):
            return Deny("CONTENT_NOT_ALLOWED_FOR_KIDS", "Bu içerik çocuk profili için uygun değil")


class ConcurrencyPolicy:                       # EN SONDA: yan etkili (slot alır) — DATA-01
    name, order = "concurrency", 1000
    ...
```

Manifest katkısı: `playback_policies=("app.modules.billing.playback:EntitlementPolicy",)`. `playback` modülü boot sonrası tüm manifest'lerden bu yolları toplar, container'dan bağımlılıklarıyla kurar ve `PlaybackGate`'e verir. **Yeni kural eklemek playback modülünü değiştirmeyi gerektirmez.** Yeni içerik türü (ör. `podcast`) = yeni `ContentKind` + yeni `SourceResolver`; resolver yoksa `NoSourceResolverError` isimlendirerek söyler.

### 4.8 Olaylar: Versiyonlu, Tipli, Evrimleşebilir

```python
# app/shared_kernel/events.py — SAF (framework yok)
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class UserRegistered:
    NAME = "user.registered"; VERSION = 2
    user_id: str
    email: str | None
    registered_at: str


@dataclass(frozen=True, slots=True)
class SubscriptionChanged:
    NAME = "subscription.changed"; VERSION = 1
    user_id: str
    plan: str
    status: str
    effective_at: str
```

```python
# app/kernel/events/registry.py
import json
from typing import Callable

from app.kernel.events.bus import UnknownEventTypeError

Upcaster = Callable[[dict], dict]

class EventRegistry:
    def __init__(self):
        self._types: dict[str, type] = {}
        self._upcasters: dict[tuple[str, int], Upcaster] = {}

    def register(self, cls: type) -> None:
        if cls.NAME in self._types:
            raise ValueError(f"Event '{cls.NAME}' iki kez kaydedildi")
        self._types[cls.NAME] = cls

    def upcaster(self, name: str, from_version: int):
        def deco(fn: Upcaster) -> Upcaster:
            self._upcasters[(name, from_version)] = fn
            return fn
        return deco

    def encode(self, event) -> tuple[str, str]:
        payload = {"_v": event.VERSION, **{f: getattr(event, f) for f in event.__dataclass_fields__}}
        return event.NAME, json.dumps(payload, separators=(",", ":"))

    def decode(self, name: str, raw: str):
        try:
            cls = self._types[name]
        except KeyError:
            raise UnknownEventTypeError(name) from None
        data = json.loads(raw)
        v = data.pop("_v", 1)
        while v < cls.VERSION:                         # v1 → v2 → ... zinciri
            data = self._upcasters[(name, v)](data); v += 1
        return cls(**data)


# Örnek: v1'de email zorunluydu, v2'de opsiyonel
@registry.upcaster("user.registered", from_version=1)
def _ur_v1_to_v2(d: dict) -> dict:
    d.setdefault("email", None)
    return d
```

Kuyruktaki eski olaylar yeni kodla güvenle işlenir; event şeması değişikliği **deploy sırası bağımsız** hâle gelir.

### 4.9 Veri Sahipliği

| Modül | Sahip olduğu tablolar | Diğer modüllere referans |
|---|---|---|
| identity | `identity_users`, `identity_refresh_tokens` | — |
| profile | `profiles` | `user_id` (soft) |
| devices | `devices` | `user_id` (soft) |
| catalog | `catalog_channels`, `catalog_playlists`, `catalog_ratings` | — |
| playback | `playback_sessions` (audit), `playback_events`, `playback_qoe` | `user_id`, `profile_id`, `content_ref` (soft) |
| live | `live_channels`, `live_epg` | — |
| drm | `drm_contents`, `drm_policies`, `drm_licenses`, `drm_events` | `content_ref` (soft) |
| billing | `billing_subscriptions`, `billing_webhooks_seen` | `user_id` (soft) |
| library | `library_favorites`, `library_progress`, `library_history` | `profile_id`, `channel_id` (soft) |
| recommendations | `reco_trending_mv` (read model, event ile beslenir) | — |
| kernel | `kernel_outbox`, `kernel_inbox`, `kernel_dead_letters` | — |

**Kurallar:** (1) Bir modül başka modülün tablosuna **asla** SQL ile dokunmaz; (2) modül sınırını geçen referanslar FK'siz (soft) + silmeler event ile yayılır (`catalog.channel_removed` → library temizler); (3) tablo adları migration'da yeniden adlandırılırken eski adlar için geçici **view** bırakılabilir (kırılmasız geçiş).

### 4.10 Frontend: Feature Manifest + Registry ("Puzzle UI")

```js
// src/app/featureKit.js
export class FeatureContractError extends Error {
  constructor(feature, detail) { super(`[feature:${feature}] ${detail}`); this.name = 'FeatureContractError'; }
}
export class DuplicateRouteError extends FeatureContractError { name = 'DuplicateRouteError'; }
export class MissingFeatureError extends FeatureContractError { name = 'MissingFeatureError'; }

/** @typedef {{ path: string, lazy: () => Promise<{default: any}>, guard?: 'public'|'auth'|'admin' }} RouteDef */
/** @typedef {{ to: string, labelKey: string, icon: string, order?: number, guard?: 'auth'|'admin' }} NavDef */
/** @typedef {{ id: string, requires?: string[], backendModule?: string, routes?: RouteDef[], nav?: NavDef[],
 *              providers?: Array<React.ComponentType<{children: React.ReactNode}>> }} FeatureManifest */

export const defineFeature = (/** @type {FeatureManifest} */ m) => Object.freeze(m);

export function buildRegistry(features, { disabled = [], backendModules = null } = {}) {
  const seen = new Set();
  for (const f of features) {
    if (!f.id) throw new FeatureContractError('?', 'id zorunlu');
    if (seen.has(f.id)) throw new FeatureContractError(f.id, 'aynı id iki kez tanımlı');
    seen.add(f.id);
  }
  const unknown = disabled.filter((id) => !seen.has(id));
  if (unknown.length) throw new FeatureContractError(unknown.join(','), 'VITE_DISABLED_FEATURES içinde bilinmeyen feature');

  // Backend modülü kapalıysa ilgili feature otomatik düşer (iki uç tutarlı kalır)
  const active = features.filter((f) => !disabled.includes(f.id)
    && (!f.backendModule || !backendModules || backendModules.includes(f.backendModule)));
  const activeIds = new Set(active.map((f) => f.id));
  for (const f of active) {
    for (const dep of f.requires ?? []) {
      if (!activeIds.has(dep)) throw new MissingFeatureError(f.id, `'${dep}' gerekli ama kurulu/etkin değil`);
    }
  }

  const owners = new Map();
  const routes = [];
  const nav = [];
  const providers = [];
  for (const f of active) {
    for (const r of f.routes ?? []) {
      if (owners.has(r.path)) throw new DuplicateRouteError(f.id, `${r.path} zaten '${owners.get(r.path)}' tarafından tanımlı`);
      owners.set(r.path, f.id);
      routes.push({ guard: 'auth', ...r, feature: f.id });
    }
    for (const n of f.nav ?? []) nav.push({ order: 100, guard: 'auth', ...n, feature: f.id });
    providers.push(...(f.providers ?? []));
  }
  nav.sort((a, b) => a.order - b.order);
  return Object.freeze({ features: active, routes, nav, providers });
}
```

```jsx
// src/app/createAppRouter.jsx
import { createBrowserRouter } from 'react-router-dom';
import { PrivateRoute, RoleRoute } from '@/core/auth/guards';
import { AppShell } from './AppShell';

const toRoute = (r) => ({ path: r.path, lazy: async () => ({ Component: (await r.lazy()).default }) });

export function createAppRouter(registry) {
  const pick = (g) => registry.routes.filter((r) => r.guard === g).map(toRoute);
  return createBrowserRouter([
    ...pick('public'),
    {
      element: <PrivateRoute />,
      children: [{
        element: <AppShell nav={registry.nav} />,        // Sidebar artık nav'ı registry'den çizer
        children: [
          ...pick('auth'),
          { element: <RoleRoute requiredRole="admin" />, children: pick('admin') },
        ],
      }],
    },
    { path: '*', lazy: async () => ({ Component: (await import('@/shared/pages/NotFound')).default }) },
  ]);
}
```

```js
// src/features/billing/manifest.js
import { defineFeature } from '@/app/featureKit';

export default defineFeature({
  id: 'billing',
  backendModule: 'billing',
  requires: ['auth'],
  routes: [{ path: '/billing', lazy: () => import('./pages/PremiumPage') }],
  nav: [{ to: '/billing', labelKey: 'nav.billing', icon: 'Crown', order: 60 }],
});

// src/features/index.js — feature ekle/çıkar = 1 satır
import auth from './auth/manifest';
import catalog from './catalog/manifest';
import live from './live/manifest';
import playback from './playback/manifest';
import library from './library/manifest';
import billing from './billing/manifest';
import devices from './devices/manifest';
import profile from './profile/manifest';
import admin from './admin/manifest';
export const FEATURES = [auth, catalog, live, playback, library, billing, devices, profile, admin];
```

**Player motoru soyutlaması** (DRM eklemek = yeni motor, mevcut UI'a dokunmadan):

```js
// src/features/player/engines/index.js
import { createHlsJsEngine } from './hlsJsEngine';
import { createNativeEngine } from './nativeEngine';

export class UnsupportedPlaybackError extends Error { name = 'UnsupportedPlaybackError'; }

const ENGINES = [
  { id: 'shaka',  canPlay: (src) => Boolean(src.drm),                                 load: () => import('./shakaEngine') },
  { id: 'hlsjs',  canPlay: (src) => src.isHls && window.MediaSource !== undefined,    create: createHlsJsEngine },
  { id: 'native', canPlay: (src, v) => v.canPlayType(src.isHls ? 'application/vnd.apple.mpegurl' : 'video/mp4') !== '', create: createNativeEngine },
];

export async function pickEngine(video, source, opts) {
  const e = ENGINES.find((x) => x.canPlay(source, video));
  if (!e) throw new UnsupportedPlaybackError(`Uygun oynatma motoru yok (drm=${!!source.drm}, hls=${source.isHls})`);
  const create = e.create ?? (await e.load()).createShakaEngine;
  return create(video, opts);
}
```

**Frontend kuralları (ESLint `boundaries`):** `features/A` → yalnızca `features/B/index.js`; `shared` → hiçbir `features`'ı bilmez; `core` → `features`'ı bilmez; `app` → her şeyi bilir (composition root).

### 4.11 Gözlemlenebilirlik

- **Yapılandırılmış log:** JSON, her satırda `request_id`, `user_id`, `module`, `route`; `print` yasak (ruff `T201`).
- **Metrikler:** `prometheus-flask-exporter` + domain metrikleri: `playback_open_total{result}`, `playback_ttff_seconds` (QoE'den), `outbox_lag_seconds`, `outbox_dead_letters_total`, `circuit_state{name}`, `transcoder_active`.
- **İzleme:** OTel yalnızca `OTEL_EXPORTER_OTLP_ENDPOINT` varsa; Flask/SQLAlchemy/Celery/requests auto-instrumentation; outbox event'ine `traceparent` yazılır → üretici ile tüketici aynı trace'te.
- **SLO örnekleri:** Playback açma başarı oranı ≥ %99.5 (5 dk pencere), p95 TTFF < 2.5 sn, outbox gecikmesi p99 < 30 sn.
- **Sağlık uçları:** `/health/live` (process), `/health/ready` (DB + Redis + broker + migration head eşleşmesi); `/health/info` sürüm ve **etkin modül listesi** (`app.extensions["modules"]`) döner — frontend registry'si bunu kullanır.

### 4.12 Mimari Fitness Function'lar (mimari kendini savunur)

| Kural | Araç | Kırılırsa |
|---|---|---|
| Modüller birbirinin iç paketlerine bakamaz | import-linter | PR kırmızı |
| Domain framework import etmez | import-linter | PR kırmızı |
| Dış HTTP yalnız EgressGateway | import-linter | PR kırmızı |
| Her modül dizini INSTALLED_MODULES'ta | pytest (`test_manifests.py`) | PR kırmızı |
| Registry boot'u temiz | pytest | PR kırmızı |
| Her port'un tüm adapter'ları contract test'i geçer | pytest parametrize | PR kırmızı |
| OpenAPI kırıcı değişiklik yok | oasdiff | PR kırmızı (ya da bilinçli `v2`) |
| Frontend tipleri sözleşmeyle senkron | `npm run check:api` | PR kırmızı |
| Feature'lar arası iç import yok | eslint-plugin-boundaries | PR kırmızı |
| Migration'lar tek head, downgrade test edilir | `alembic heads` + `upgrade/downgrade/upgrade` | PR kırmızı |

### 4.13 Çalışma Zamanı Topolojisi

```mermaid
flowchart LR
    U[Tarayıcı / TV / Mobil] -->|HTTPS| CDN[CDN / Nginx edge]
    CDN -->|"/api/*"| API["API (Gunicorn gthread × N)"]
    CDN -->|"/hls/* imzalı, X-Accel / token auth"| HLS[("Segment deposu: /dev/shm ya da object storage")]
    API --> PG[("PostgreSQL")]
    API --> RS[("Redis — state/cache/rate-limit")]
    API --> RB[("Redis/RabbitMQ — broker")]
    RB --> WD["Worker: default/outbox/playlist/epg"]
    RB --> WT["Worker: transcode (GPU düğümleri)"]
    BEAT["Beat (RedBeat, tek aktif kilit)"] --> RB
    WT --> HLS
    RTMP["nginx-rtmp ingest"] -->|on_publish callback| API
    RTMP --> WT
    WD --> PG
    API -. OTLP .-> OBS["Prometheus / Loki / Tempo"]
    WD -. OTLP .-> OBS
```

### 4.14 Değişiklik Maliyeti: Önce / Sonra

| Senaryo | Bugün dokunulan yerler | Hedefte dokunulan yerler |
|---|---|---|
| Yeni ödeme sağlayıcısı (iyzico) | `billing/services.py` iç mantığı, route, test yok | `billing/adapters/iyzico.py` + container kaydı (1 satır) + contract test listesine 1 ekleme |
| Yeni oynatma kuralı (coğrafi kısıt) | `routes/stream.py` içine `if` | Yeni `GeoPolicy` sınıfı + sahibi modülün manifest'ine 1 satır |
| Önerileri kapatmak | Blueprint kaydını sil, frontend'de 4 `useRecommendations` çağrısını temizle, ölü cache anahtarları | `DISABLED_MODULES=recommendations`; frontend feature `backendModule` ile otomatik düşer; `optional_requires` ile bağlı modüller graceful degrade |
| Elasticsearch araması | `modules/search` bağlanmamış durumda; `main.py`'de `ilike` | `search` modülü `catalog.search` capability'si sağlar; catalog onu `optional_requires` ile kullanır (yoksa SQL fallback) |
| Yeni sayfa (EPG grid) | `AppRouter.jsx` + `Sidebar.jsx` + import'lar | `features/epg/manifest.js` + `features/index.js`'e 1 satır |
| Transcoder'ı GPU kümesine taşımak | `ffmpeg_engine.py` + task + orkestratör iç içe | `TranscoderPort`'un yeni adapter'ı (ör. `RemoteGpuTranscoder`) + container override |

---

## 5. Geçiş Yol Haritası (Strangler Fig, Kırılmasız)

> Her faz kendi başına deploy edilebilir; hiçbir faz mevcut frontend'i kırmaz (legacy `/api/*` uçları, yerlerine `/api/v1/*` karşılıkları gelene ve frontend geçene kadar yaşar). Her fazın **çıkış kriteri** ölçülebilirdir.

### Faz 0 — Kanamayı Durdur (güvenlik + veri)

| Adım | Bulgu | Not |
|---|---|---|
| HLS asset uç noktasını whitelist + `send_from_directory`'ye çevir | SEC-01 | Tek dosya değişikliği |
| `/proxy/hls`'i `@login_required` + geçici host allowlist ile kısıtla (imzalı URL Faz 2'de) | SEC-02 | Allowlist: mevcut `LiveChannel.hls_url` host'ları |
| `/api/live/channels` yanıtından `stream_key`'i çıkar; tüm stream key'leri rotate et | SEC-03 | |
| `/billing/upgrade` → `403 PAYMENT_REQUIRED` (geçici), webhook'u secret header ile koru | SEC-04 | Ödeme entegrasyonu Faz 3 |
| Request loader'da `is_active` ve `typ` kontrolü; `login_user` çağrısını kaldır | SEC-05 | |
| `_verify_pin` → `check_password_hash` | SEC-12 | |
| `run.py`'de `load_dotenv()`'yi import'lardan önceye al; gerçek `SECRET_KEY` üret; `.env` repodan çık | CFG-01 | Tüm kullanıcılar yeniden login olur (beklenen) |
| `git init` + `.gitignore`; `debug_jwt.py`, `fix_db.bat`, `init_admin.py` parola sıfırlama kaldır | CFG-02, SEC-11 | |
| `start.py` `cleanup()` → yalnızca kendi PID ağacı | RT-08 | |

**Çıkış kriteri:** OWASP ZAP baseline + manuel traversal/SSRF testleri temiz; `grep -R "super_secret\|admin123\|dev-secret-key" app Scripts` boş.

### Faz 1 — Çalışır Hâle Getir (runtime breakers)

| Adım | Bulgu |
|---|---|
| Migration `b7f1c2a9e001` + `zzzz_*` silme + naming convention | RT-07 |
| Device benzersizliği `(user_id, device_id)` + `X-Device-ID` | RT-06 |
| Profil modülü + `PROFILE_CONTEXT_MODE=default_profile` | RT-05 |
| `/favorites`, `/history`, `/playlists`, `/trending` fix'leri | RT-02/03/04 |
| Tek Celery app + `app/wsgi.py` + compose'da worker/beat | ASY-01 |
| EventBus hata yayılımı + per-consumer delivery + inbox | ASY-02/03 |
| Transcoder import fix + stderr drain + platform tespiti | RT-01, STR-01, STR-03 |
| Frontend: tek `AuthProvider`; sahte Authorization header kaldır; admin API çağrılarını gerçek uçlara eşle | FE-01, FE-03, FE-05 |
| `tests/` gerçek testlerle + CI düzeltmesi (yollar, sözleşmeler, frontend job) | TEST-01/02 |

**Çıkış kriteri:** Uçtan uca smoke testi (login → kanal listesi → favori ekle → VOD oynat → canlı oynat → plan yükseltme webhook simülasyonu → `User` entitlements güncel) CI'da yeşil; outbox `pending` yaşı < 30 sn.

### Faz 2 — Çekirdek (kernel) ve Sözleşmeler

| Adım | Bölüm |
|---|---|
| `app/kernel/` iskeleti: Settings, Container, Manifest, Registry, Errors, ErrorMap, endpoint() | 4.3–4.6 |
| `UrlSigner` + `EgressGateway` + `HlsProxyService` (imzalı proxy) | SEC-02 |
| `TokenService` (access/refresh/profile/playback), refresh cookie | SEC-05, FE-04 |
| Mevcut `modules/auth` ve `modules/billing`'e `manifest.py` + `api.py` ekle; `module_loader`/`listener_registry`'yi registry ile değiştir | 4.3 |
| Pydantic şemaları + OpenAPI üretimi + `openapi/openapi.json` commit | 4.6, FE-05 |
| import-linter sözleşmeleri (elle yönetilen) + fitness testleri | 4.12, TEST-02 |

**Çıkış kriteri:** `create_app()` yalnızca registry üzerinden modül yüklüyor; bilerek bozulmuş bir manifest ile boot denemesi isimlendirilmiş hata ile duruyor (CI'da negatif test).

### Faz 3 — Modül Göçü (sırayla, her biri bağımsız PR)

Sıra bağımlılık grafiğinin yapraklarından köke doğrudur; her adımda legacy kod **silinir** (aynı PR'da):

1. **identity** ← `routes/auth.py`, `services/auth_service.py`, `models/user.py` shim, `load_user_from_request`
2. **devices** ← `routes/devices.py`, `services/device_service.py`, `models/device.py`
3. **profile** (Faz 1'de başlatıldı) → `PROFILE_CONTEXT_MODE=strict`'e hazırlık
4. **catalog** ← `routes/main.py` (kanal listesi), `routes/playlist.py`, `services/{m3u_parser,video_service,channel_manager,stream_validator}.py`, `tasks/m3u_tasks.py`
5. **billing** → `PlanCatalog`, `EntitlementService`, durum makinesi, `PaymentProvider` portu + gerçek sağlayıcı
6. **playback** ← `routes/stream.py`, `routes/progress.py` (kısmen), `routes/metrics.py`, `services/stream_service.py`; `PlaybackGate` + politikalar
7. **library** ← favoriler, geçmiş, ilerleme
8. **live** ← `routes/live.py`, `models/live.py`, `services/live_service.py`, `services/transcoder/*`, `tasks/transcoder_tasks.py`
9. **drm** ← `routes/drm*.py`, `services/drm_*.py`; `KeyVault`
10. **recommendations** ← `routes/recommendations.py`, `services/recommendation_service.py` (event-fed read model)
11. **admin** ← `routes/admin.py` (diğer modüllerin `api.py`'lerini kullanır)

**Çıkış kriteri:** `app/routes`, `app/services`, `app/models`, `app/utils`, `app/core`, `app/tasks`, `app/templates`, `app/static` dizinleri **yok**; import-linter `no-legacy` sözleşmesi gereksizleşip kaldırılır.

### Faz 4 — Frontend Registry ve Sözleşme

1. `src/app/` (AppProviders, featureKit, createAppRouter, AppShell)
2. Her feature'a `manifest.js`; `AppRouter.jsx`/`Sidebar.jsx` statik listeleri silinir
3. `openapi-typescript` + tipli istemci; `features/*/api` dosyaları üretilen istemciyi kullanır
4. `features/playback` (FE-02) + `PlayerEngine` (FE-07); `SecurePlayer`, `PremiumTab`, legacy `pages/` göçü
5. `eslint-plugin-boundaries` kuralları `error`; vitest + MSW handler'ları OpenAPI örneklerinden

**Çıkış kriteri:** Yeni bir sayfa eklemek için `src/app/` ve `src/core/` altında **sıfır** dosya değişikliği gerekiyor (PR diff'i ile doğrulanır).

### Faz 5 — Ölçek ve İşletim

- Segment trafiği tamamen Nginx/CDN'e; API yalnızca yetkilendirme
- Transcoder için ayrı GPU worker havuzu + lease tabanlı yaşam döngüsü (STR-02)
- PostgreSQL read replica (katalog/öneri okumaları), PgBouncer
- Outbox → (ihtiyaç olursa) Kafka/Redpanda'ya köprü; event sözleşmeleri değişmez
- SLO dashboard'ları + alarm (dead-letter > 0, outbox lag, circuit open)

---

## 6. Yeni Özellik Ekleme / Çıkarma / Değiştirme Reçetesi

### 6.1 Örnek: "Program Hatırlatıcı" (Reminders) modülünü eklemek

**Hedef:** Kullanıcı EPG'de bir program için hatırlatma kurar; program başlamadan 5 dk önce bildirim alır.

**Adım 1 — İskelet:**

```bash
flask kernel new-module reminders     # app/modules/_template kopyalanır, isimler değiştirilir
```

**Adım 2 — Manifest (tek giriş noktası):**

```python
# app/modules/reminders/manifest.py
from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.modules.reminders.api import ReminderService

def _services(c):
    from app.modules.reminders.adapters.sql_repo import SqlReminderRepository
    from app.modules.live.api import EpgReadPort                         # yalnızca PUBLIC api
    c.register("reminders.repo", lambda c: SqlReminderRepository(c.resolve("db_session")), lifetime="request")
    c.register(ReminderService, lambda c: ReminderService(c.resolve("reminders.repo"), c.resolve(EpgReadPort)),
               lifetime="request")

manifest = ModuleManifest(
    name="reminders",
    version="1.0.0",
    provides={"reminders.service": ReminderService},
    requires=frozenset({"identity.users", "live.epg"}),                  # live kapalıysa boot isimlendirerek durur
    optional_requires=frozenset({"notifications.push"}),                 # yoksa in-app bildirime düşer
    services=_services,
    routes=(RouteSpec("app.modules.reminders.http.routes:reminders_bp", "/api/v1/reminders"),),
    subscriptions=(SubscriptionSpec("live.epg_program_rescheduled", "reminders.reschedule",
                                    "app.modules.reminders.handlers:on_program_rescheduled"),),
    task_modules=("app.modules.reminders.tasks",),
    beat_schedule={"reminders.fire-due": {"task": "reminders.fire_due", "schedule": 60.0}},
    task_routes={"reminders.*": {"queue": "default"}},
)
```

**Adım 3 — Kurulum (1 satır):**

```python
# app/modules/__init__.py
INSTALLED_MODULES = (..., "app.modules.reminders")
```

**Adım 4 — Migration (yalnızca bu modülün tabloları):** `flask db revision -m "reminders: initial" --autogenerate` → `reminders_*` tabloları.

**Adım 5 — Frontend (1 dosya + 1 satır):**

```js
// src/features/reminders/manifest.js
export default defineFeature({
  id: 'reminders', backendModule: 'reminders', requires: ['auth', 'live'],
  routes: [{ path: '/reminders', lazy: () => import('./pages/RemindersPage') }],
  nav: [{ to: '/reminders', labelKey: 'nav.reminders', icon: 'Bell', order: 45 }],
});
// src/features/index.js → FEATURES = [..., reminders]
```

**Dokunulmayanlar:** `create_app`, `kernel/*`, diğer tüm modüller, `AppRouter`, `Sidebar`, Celery yapılandırması, beat yapılandırması, hata eşlemeleri.

**Olası hatalar ve sistemin cevabı:**

| Hata | Ne zaman | Mesaj |
|---|---|---|
| `live` modülü devre dışı | Boot | `DisabledDependencyError: [module:reminders] 'live.epg' gerektiriyor; sağlayıcı 'live' DEVRE DIŞI` |
| `handlers.py`'de yazım hatası | Boot | `HandlerImportError: [module:reminders] 'app.modules.reminders.handlers:on_program_rescheduled' import edilemedi: ...` |
| `tasks.py` unutuldu | Boot (web ve worker) | `ModuleContractError: [module:reminders] task modülü bulunamadı: app.modules.reminders.tasks` |
| Başka modül de `/api/v1/reminders` kullanıyor | Boot | `DuplicateRouteError: /api/v1/reminders/ ['POST']: '...' ve '...'` |
| `live`'ın iç paketinden import | CI | import-linter: `app.modules.reminders.services -> app.modules.live.services` yasak |
| Frontend'de `/reminders` iki kez | Uygulama açılışı | `DuplicateRouteError: [feature:reminders] /reminders zaten 'epg' tarafından tanımlı` |

### 6.2 Bir özelliği çıkarmak

1. **Geçici:** `DISABLED_MODULES=reminders` (backend) → `/health/info` modül listesinden düşer → frontend `backendModule` eşleşmesiyle feature'ı otomatik gizler. Ona zorunlu bağımlı modül varsa boot **reddeder** ve kimin bağımlı olduğunu söyler.
2. **Kalıcı:** `INSTALLED_MODULES`'tan satırı sil → `test_every_module_directory_is_installed...` fitness testi dizinin hâlâ durduğunu söyler → dizini sil → `drop` migration'ı (tablolar yalnızca bu modüle ait olduğu için güvenli) → `features/index.js`'ten satırı sil.

### 6.3 Bir özelliği değiştirmek (davranışı korumak kaydıyla)

- **Implementasyon değişimi** (ör. SQL → Elasticsearch): yeni adapter + `container.register(..., replace=True)` ya da manifest'te seçici; port **contract test**'i her iki adapter için aynı testleri koşar → davranış eşitliği kanıtlanır.
- **Sözleşme değişimi** (ör. HTTP yanıt şekli): `/api/v2/...` yeni blueprint, eskisi `Deprecation/Sunset` header'ı ile korunur; oasdiff kırıcı değişikliği v1'de engeller.
- **Event değişimi:** `VERSION` artır + upcaster; eski kuyruk mesajları otomatik dönüşür.

---

## 7. Ek: Bulgu Endeksi ve Kontrol Listesi

| ID | Öncelik | Başlık | Faz | Durum |
|---|---|---|---|---|
| SEC-01 | P0 | HLS asset path traversal | 0 | ☐ |
| SEC-02 | P0 | Kimliksiz SSRF proxy / egress | 0→2 | ☐ |
| SEC-03 | P0 | Stream key sızıntısı | 0 | ☐ |
| SEC-04 | P0 | Ödemesiz upgrade, imzasız webhook | 0→3 | ☐ |
| SEC-05 | P0 | Token tipi, suspend, stateful request loader | 0→2 | ☐ |
| SEC-06 | P1 | Brute-force koruması devre dışı, kullanıcı numaralandırma | 2 | ☐ |
| SEC-07 | P0 | DRM anahtar teslimi/saklama, renew IDOR | 3 | ☐ |
| SEC-08 | P1 | Heartbeat IDOR, origin sızıntısı | 1 | ☐ |
| SEC-09 | P1 | Playlist uçları yetkisiz + senkron fetch | 1 | ☐ |
| SEC-10 | P1 | Hardcoded anti-leech secret, MD5 | 2 | ☐ |
| SEC-11 | P1 | Redis/Flower açık, varsayılan parolalar, secret'lar | 0 | ☐ |
| SEC-12 | P0 | PIN doğrulaması her zaman True | 0 | ☐ |
| RT-01 | P0 | Transcoder import hatası, psutil eksik | 1 | ☐ |
| RT-02 | P0 | favorites/history AttributeError | 1 | ☐ |
| RT-03 | P0 | playlists TypeError | 1 | ☐ |
| RT-04 | P0 | trending JSON serialization | 1 | ☐ |
| RT-05 | P0 | Profil sistemi yok | 1 | ☐ |
| RT-06 | P0 | Device unique çakışması → login 500 | 1 | ☐ |
| RT-07 | P0 | Migration zinciri kırık | 1 | ☐ |
| RT-08 | P1 | Başlatıcılar kırık, sistem geneli process kill | 0→1 | ☐ |
| RT-09 | P1 | Redis kesintisi katalogu düşürüyor | 1 | ☐ |
| RES-01 | P1 | Circuit breaker durum makinesi | 2 | ☐ |
| DATA-01 | P0 | Stream limiti yarışı, release yok | 1 | ☐ |
| DATA-02 | P1 | DRM FOR UPDATE + COUNT | 3 | ☐ |
| DATA-03 | P1 | Plan limitleri 3 yerde | 3 | ☐ |
| DATA-04 | P1 | Abonelik yaşam döngüsü | 3 | ☐ |
| DATA-05 | P1 | Idempotency gövde bağlamı, bloklama | 2 | ☐ |
| DATA-06 | P1 | Playlist yenileme ID'leri yok ediyor | 3 | ☐ |
| DATA-07 | P1 | Import sınıflandırma/atomiklik/süre | 3 | ☐ |
| DATA-08 | P1 | SQLite eşzamanlılık | 1 | ☐ |
| DATA-09 | P2 | Naive datetime | 2 | ☐ |
| DATA-10 | P2 | Favorite unique, toggle semantiği | 3 | ☐ |
| ASY-01 | P0 | İki Celery app, outbox çalışmıyor | 1 | ☐ |
| ASY-02 | P0 | EventBus hata yutma | 1 | ☐ |
| ASY-03 | P1 | Dispatcher transaction/context | 1 | ☐ |
| ASY-04 | P1 | Sahte sync task | 3 | ☐ |
| ASY-05 | P1 | Sessiz modül/listener yükleme | 2 | ☐ |
| ASY-06 | P2 | BackgroundJob tekrarı | 3 | ☐ |
| STR-01 | P0 | FFmpeg stderr deadlock | 1 | ☐ |
| STR-02 | P1 | Orkestratör yaşam döngüsü | 5 | ☐ |
| STR-03 | P1 | Platform/encoder bağımlılığı | 1 | ☐ |
| STR-04 | P1 | Cold-start long-polling | 3 | ☐ |
| PERF-01 | P1 | Thread starvation envanteri | 2→5 | ☐ |
| PERF-02 | P2 | Senkron access log | 2 | ☐ |
| PERF-03 | P2 | N+1 sorgular | 3 | ☐ |
| PERF-04 | P2 | Import-time yan etkiler | 2 | ☐ |
| CFG-01 | P0 | .env uygulanmıyor, Settings | 0→2 | ☐ |
| CFG-02 | P1 | Kök dizin venv, hijyen | 0 | ☐ |
| CFG-03 | P1 | docker-compose çalışmıyor | 1 | ☐ |
| FE-01 | P1 | Çift AuthProvider | 1 | ☐ |
| FE-02 | P0 | VOD yetkilendirme bypass | 1→4 | ☐ |
| FE-03 | P0 | Sahte Authorization header | 1 | ☐ |
| FE-04 | P1 | Token yönetimi | 2 | ☐ |
| FE-05 | P1 | API sözleşme kayması | 1→4 | ☐ |
| FE-06 | P2 | Kayıt formu veri tutarsızlığı | 4 | ☐ |
| FE-07 | P2 | Player yaşam döngüsü | 4 | ☐ |
| FE-08 | P2 | Katman karışıklığı, sabit route/nav | 4 | ☐ |
| HYG-01 | P2 | Çift implementasyonlar | 3 | ☐ |
| HYG-02 | P2 | Bağlanmamış bileşenler | 3 | ☐ |
| HYG-03 | P3 | Diğer hijyen | 3 | ☐ |
| TEST-01 | P0 | Sıfır çalışan test | 1 | ☐ |
| TEST-02 | P0 | CI kırık, sözleşme ihlali | 1 | ☐ |

**Toplam:** 62 bulgu — 23 × P0, 27 × P1, 11 × P2, 1 × P3.

---

> **Son not — bu raporun kendisi hakkında:** Buradaki kod örnekleri hedef mimarinin referans implementasyonlarıdır; projeye aktarılırken her biri kendi modülünde, kendi testleriyle birlikte, Faz sırasıyla eklenmelidir. Önce Faz 0, çünkü SEC-01 ve SEC-02 tek başına sunucudaki tüm verinin dışarı alınmasına yetiyor.
