# Milestone 5.0E — Authentication & Authorization Design

| Alan | Değer |
|---|---|
| Doküman durumu | TASARIM — İmplementasyon için ayrıca kullanıcı onayı gerekir |
| Milestone | 5.0E — Authentication & Authorization |
| Tasarım sürümü | 1.0.0 |
| Ana referans | `FINOS_ARCHITECTURE_BOOK.md` v1.4.0 |
| Önceki değişmez sözleşmeler | Milestone 5.0A, 5.0B, 5.0C, 5.0D |
| Çalışma modeli | Senkron HTTP resource server; fail-closed |
| Event sourcing | Kullanılmaz |
| Marka politikası | FINOS yalnız dahili geliştirme kod adıdır |

---

## 1. Amaç

Milestone 5.0E'nin amacı, Milestone 5.0D'nin yalnız trusted bir dış adapter'dan kabul ettiği `AuthenticationContext` nesnesini gerçek, provider-neutral bir OAuth 2.0/OIDC JWT resource-server sınırından üretmek ve doğrulanmış subject'in tenant/resource/action erişim kararını authoritative yerel policy state üzerinden vermektir.

Bu milestone:

1. bearer access token'ı güvenli biçimde alır ve doğrular;
2. dış identity provider ile yerel tenant/membership/role sahipliğini kesin biçimde ayırır;
3. doğrulanmış identity'yi değişmemiş 5.0D `AuthenticationContext` sözleşmesine map eder;
4. değişmemiş 5.0C `AuthorizationPort` için production authorization karar kaynağı sağlar;
5. legacy router'ların tamamını ortak authentication/authorization boundary'sine alır;
6. cross-tenant/IDOR erişimini query seviyesinde fail-closed engeller;
7. JWKS rotation, local revocation, outage, audit ve readiness davranışını executable sözleşmelerle tanımlar.

5.0E finansal hesaplama, orchestration, persistence payload sahipliği veya application use-case semantiğini değiştirmez.

---

## 2. Mevcut Durum

### 2.1 Milestone 5.0A

`app/engines/analysis_orchestrator/**` saf koordinasyon katmanıdır. Authentication, authorization, tenant membership, JWT, HTTP veya SQLAlchemy bilmez. Bu sınır değişmeyecektir.

### 2.2 Milestone 5.0B

`app/orchestration_persistence/**` terminal run, engine execution, artifact, financial owner ve recovery bütünlüğünü sahiplenir. Authentication/policy state'in sahibi değildir. Storage Ownership Matrix değişmeyecektir.

### 2.3 Milestone 5.0C

Application Layer şu public sınırları zaten sağlar ve 5.0E bunları değiştirmeden implemente eder:

- `AuthorizationPort`;
- `AuthorizationDecision`;
- `SecurityAuditPort`;
- pre-execution authorization;
- resume-source authorization;
- pre-persistence authorization revalidation;
- authorization provider unavailable/revoked/denied error taxonomy;
- required security audit ve best-effort observability ayrımı.

### 2.4 Milestone 5.0D

API & Integration Layer şu public sınırları sağlar:

- immutable `AuthenticationContext`;
- `TrustedAuthenticationContextProviderPort.current_context()`;
- `ApiRuntimeProfile`;
- raw `X-User-Id` / `X-Tenant-Id` / `X-Subject-Id` yasağı;
- issuer, age, expiry, future-skew ve correlation doğrulaması;
- production fake/allow-all/no-op adapter yasağı;
- sekiz analysis-run endpoint'inde subject/scope-aware fail-closed davranış.

Mevcut production composition gerçek token doğrulayıcı sağlamaz. `ExternalAuthorizationAdapter`, dış `policy_client` bekler. User, tenant, membership, role veya permission modeli yoktur. Analysis-run dışındaki legacy router'lar ortak security dependency'sine bağlı değildir.

---

## 3. Değişmez Public Contract'lar

5.0E aşağıdakileri değiştiremez:

1. 5.0A `run_orchestration()` imzası, engine dataclass'ları, registry'ler ve deterministik hesaplama davranışı.
2. 5.0B persistence command/port/snapshot/artifact sözleşmeleri ve Storage Ownership Matrix.
3. 5.0C command/query/DTO/enum/`ApplicationOutcome[T]`, `AuthorizationPort`, `SecurityAuditPort` ve transaction davranışı.
4. 5.0D `AuthenticationContext`, `AuthenticationStrength`, `TrustedAuthenticationContextProviderPort`, API v1 request/response şemaları, endpoint yolları ve error envelope.

5.0E yeni internal security-core contract'ları ve adapter'ları ekleyebilir; bunlar yukarıdaki public sözleşmelerin replacement'ı değil implementasyonudur.

---

## 4. Kapsam

- OAuth 2.0 bearer JWT resource-server boundary.
- Provider-neutral OIDC issuer/audience/JWKS configuration.
- Asymmetric JWT signature ve claims doğrulaması.
- JWKS cache, forced refresh, key rotation ve outage politikası.
- Request-scoped trusted `AuthenticationContext` üretimi.
- Authoritative local tenant/principal/membership/role/permission modeli.
- Company, bulk-upload batch ve analysis-run tenant ownership enforcement.
- Değişmemiş 5.0C `AuthorizationPort` production adapter'ı.
- Legacy route authentication/authorization matrisi.
- Local principal/membership revocation ve bounded token lifetime.
- Authentication/security audit olayları.
- Production composition, configuration, readiness ve safe error mapping.
- PostgreSQL constraint/index ve migration tasarımı.
- Unit/property/API/PostgreSQL/security/Docker test stratejisi.

---

## 5. Kapsam Dışı

- Token issuance veya refresh-token issuance.
- Authorization Code/PKCE login UI, redirect/callback endpoint'i.
- Password saklama, local credential database'i veya password reset.
- MFA challenge üretimi; 5.0E yalnız IdP'nin doğruladığı `acr`/`amr` sonucunu tüketir.
- IdP kullanıcı yaşam döngüsü, SCIM veya otomatik group sync.
- Self-service tenant/user/role yönetim API'si veya UI.
- Queue, worker, scheduler, batch runner veya background refresh worker.
- Distributed lock veya distributed session registry.
- Engine, Orchestrator veya finansal hesaplama değişikliği.
- Event sourcing, CQRS veya authentication event'lerinden state rebuild.
- API v2 veya 5.0D response contract değişikliği.

---

## 6. Temel Mimari Karar

5.0E bir **resource server**'dır. Dış OIDC provider credential'ı doğrular ve access token üretir; backend token'ı doğrular fakat login/token endpoint'i işletmez.

```text
Caller
  │ Authorization: Bearer <JWT>
  ▼
BearerAuthenticationDependency
  ├─ strict header parsing
  ├─ ProviderNeutralJwtVerifier
  │    ├─ IssuerRegistry
  │    └─ JwksProvider/Cache
  ├─ SecurityPrincipalRepository
  ├─ TenantMembershipRepository
  └─ RequestBoundAuthenticationContextProvider
           │ unchanged AuthenticationContext
           ▼
5.0D HTTP boundary
           │
           ▼
5.0C AuthorizationPort
           │
           ▼
LocalAuthorizationPolicyClient
```

Router token parse etmez, claim yorumlamaz ve authorization kararı üretmez. Authentication dependency, request başlamadan önce doğrulanmış context'i request-scoped provider'a bağlar. Global mutable principal/context kullanılmaz.

---

## 7. Authentication ve Authorization Ayrımı

### Authentication

Şu soruyu cevaplar: “Bu request'i yapan subject kimdir ve token gerçekten trusted issuer tarafından mı verilmiştir?”

Authentication çıktısı yalnız değişmemiş `AuthenticationContext`'tir. Token doğrulanmış olması hiçbir permission grant etmez.

### Authorization

Şu soruyu cevaplar: “Bu authenticated principal, bu tenant içindeki bu resource üzerinde bu action'ı yapabilir mi?”

Authorization'ın authoritative girdileri yerel PostgreSQL tenant/membership/role/policy state'idir. Token'daki group/role/permission claim'leri grant kaynağı değildir ve yok sayılır.

Authentication success + authorization deny normal ve zorunlu bir sonuçtur.

---

## 8. Authoritative Ownership Model

### 8.1 Tek sahiplik matrisi

| Veri | Authoritative sahip | Yerel kullanım |
|---|---|---|
| Credential, MFA, password, external subject yaşam döngüsü | Dış OIDC Identity Provider | Backend saklamaz |
| Token signature key'leri | Issuer JWKS endpoint'i | Süreli doğrulama cache'i |
| `(issuer, subject)` identity referansı | Yerel `security_subject_bindings` | Credential içermez; principal'a FK |
| Tenant kimliği ve durumu | Yerel `security_tenants` | Internal UUID + canonical tenant_key |
| Principal ↔ tenant membership ve durumu | Yerel `security_memberships` | Erişim için authoritative |
| Role ve permission ataması | Yerel security policy tabloları | Authorization grant kaynağı |
| Company tenant ownership | `companies.tenant_id` | Period/document/result buradan türetilir |
| Bulk-upload ownership | `bulk_upload_batches.tenant_id` | Item ownership batch'ten türetilir |
| Analysis-run ownership | Mevcut `analysis_run_scope_claims.tenant_id` + `initiating_subject_id` | Değişmez 5.0D semantiği |
| Security audit history | Durable external audit sink | Domain state rebuild kaynağı değildir |

### 8.2 “User” modeli

5.0E local password/user-profile sahibi bir `users` tablosu oluşturmaz. `SecurityPrincipal` internal identity aggregate'ıdır; dış identity ayrı `SecuritySubjectBinding` ile bağlanır:

- `principal_kind` (`HUMAN` veya `SERVICE`);
- status;
- `tokens_valid_after`;
- version/audit timestamps.

`SecuritySubjectBinding`, immutable `(issuer,subject) → principal_id` referansını sahiplenir; SERVICE binding ayrıca issuer-namespaced immutable `service_client_id` taşır. Subject rotation eski binding'i revoke edip yenisini aynı principal'a bağlar; subject başka principal'a taşınamaz.

Email, display name veya IdP group'ları authorization identity değildir. Gerekirse display metadata ayrı, non-authoritative projection olarak tutulabilir; v1'de tutulmaz.

### 8.3 Tenant seçimi

Tenant-scoped endpoint'lerde token'ın doğrulanmış `tenant_id` claim'i zorunludur. Bu claim yalnız selector'dır; grant değildir. Backend:

1. claim'i canonical tenant_key olarak parse eder;
2. tenant'ın ACTIVE olduğunu doğrular;
3. `(principal_id, internal tenant UUID)` membership'ini yükler;
4. membership ACTIVE değilse context üretmez;
5. context'e yalnız canonical tenant_key'i yazar.

Birden fazla membership arasından varsayım/default seçimi yapılmaz. Raw tenant header/body override yasaktır. `AuthenticationContext.tenant_id=None` public contract uyumluluğu için korunur fakat production tenant-scoped API'lerde reddedilir.

### 8.4 Resource ownership

Yeni production company ve bulk-upload batch kayıtları non-null tenant sahibi olmadan oluşturulamaz. Historical unbound kayıtlar otomatik bir tenant'a backfill edilmez; explicit, audited ownership migration/provisioning işlemi yapılana kadar API'den fail-closed görünmez.

Period, document ve financial result tenant'ı company zincirinden türetilir. Bulk-upload item tenant'ı batch'ten türetilir. Generic polymorphic resource-owner tablosu kullanılmaz; gerçek FK zinciri tercih edilir.

---

## 9. Executable Durable Security Modeli

### 9.1 Canonical tenant identity — bağlayıcı v1 kararı

- `security_tenants.id`: yalnız PostgreSQL security adapter'larında kullanılan internal UUID'dir.
- `security_tenants.tenant_key`: dış identity ile application scope arasındaki immutable, globally unique canonical identifier'dır.
- JWT tenant claim'inin değeri **tenant_key**'dir.
- Değişmemiş `AuthenticationContext.tenant_id`, canonical tenant_key string'ini taşır.
- PostgreSQL membership/authorization sorgusu tenant_key'i `security_tenants.id` UUID'sine çözer.
- Internal tenant UUID hiçbir 5.0A–5.0D public contract'a, API DTO'suna veya engine option'ına sızmaz.

`tenant_key` exact politikası:

- minimum 3, maksimum 63 ASCII byte;
- regex: `^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$`;
- yalnız ASCII lowercase kabul edilir;
- leading/trailing whitespace ve iç whitespace reddedilir;
- Unicode kabul edilmez; Unicode normalization uygulanmaz;
- case-folding/lowercasing yapılmaz; non-canonical token claim fail-closed reddedilir;
- karşılaştırma exact byte/string equality'dir.

### 9.2 Tablo sözleşmeleri

| Tablo | PK/FK/unique | Check ve isolation | Mutable/immutable, index ve delete policy |
|---|---|---|---|
| `security_tenants` | PK `id UUID`; unique `tenant_key` | canonical tenant_key CHECK; status `ACTIVE/SUSPENDED/DISABLED`; `policy_version>=1` | tenant_key immutable; status/version mutable; index status; hard DELETE RESTRICT |
| `security_principals` | PK `id UUID` | kind `HUMAN/SERVICE`; status `ACTIVE/SUSPENDED/DISABLED` | kind immutable; status, `tokens_valid_after`, version mutable; version>=1; hard DELETE RESTRICT |
| `security_subject_bindings` | PK `id UUID`; FK principal RESTRICT; unique `(issuer, subject)`; partial unique `(issuer, service_client_id)` when non-null; at most one ACTIVE binding/principal/issuer | canonical issuer/sub checks; `service_client_id` iff bound principal SERVICE; status `ACTIVE/REVOKED`; revoked fields co-occur | issuer/sub/service_client_id immutable; soft revoke only; indexes principal/status, issuer/sub and issuer/service_client_id; hard DELETE forbidden |
| `security_memberships` | PK `id UUID`; FK tenant/principal RESTRICT; unique `(tenant_id, principal_id)` | status `ACTIVE/SUSPENDED/REVOKED`; validity interval; principal/tenant isolation | status/validity/version mutable; version>=1; indexes tenant+status, principal+status; hard DELETE forbidden |
| `security_permissions` | PK `permission_code` | row must match PermissionRegistry v1.0.0 exactly | immutable seed/reference rows; UPDATE/DELETE forbidden |
| `security_roles` | PK `id UUID`; FK tenant RESTRICT; unique `(tenant_id, role_code)` | closed built-in/custom code syntax; status `ACTIVE/DISABLED`; version>=1 | tenant/code immutable; status/version mutable; hard DELETE forbidden |
| `security_role_permissions` | composite PK/FK role+permission | permission must exist; role tenant is authoritative | assignment removed only via audited provisioning; index permission; hard delete yalnız provisioning transaction'ında |
| `security_membership_roles` | composite PK/FK membership+role | membership.tenant_id == role.tenant_id trigger/check | audited assign/revoke; indexes membership/role; cross-tenant insert rejected |
| `security_provisioning_operations` | PK `id UUID`; unique `(authority_id,idempotency_key)` | operation kind, canonical payload digest, terminal status | immutable completed operation; response projection metadata; UPDATE/DELETE forbidden after terminal |
| `security_resource_binding_quarantine` | PK `id UUID`; unique resource_type/resource_id | historical invalid/unbound only; reason closed enum | remediation metadata mutable until resolved; no authorization grant |

`security_membership_roles` + role permission'larının kapalı `service_allowed` flag'ları birlikte service-grant eşdeğeridir; `SERVICE_OPERATOR` yalnız built-in varsayılan service-safe roldür. Ayrı `security_service_grants` veya direct-grant source of truth oluşturulmaz. Direct permission grant yasaktır.

Tüm mutable security tablolarında timezone-aware `created_at`, `updated_at`, `version`; revoke edilen varlıklarda `revoked_at/effective_at`, `revoked_by_principal_id`, closed `revocation_reason` bulunur. Audit timestamps caller tarafından değil injected clock tarafından üretilir. Security policy state domain state'tir; security audit event sourcing değildir.

### 9.3 Resource ownership

- `companies.tenant_id UUID` → `security_tenants.id`;
- `bulk_upload_batches.tenant_id UUID` → `security_tenants.id`;
- `analysis_run_scope_claims.tenant_id VARCHAR(63)` → `security_tenants.tenant_key` validated FK;
- period/document/financial-result ownership company FK zincirinden;
- bulk item ownership batch FK zincirinden türetilir.

Generic polymorphic owner tablosu veya dual-write owner alanı yoktur. Context tenant_key bir kez internal tenant UUID'ye resolve edilir; SQL query resource FK zinciri ve internal UUID ile scope edilir.

### 9.4 Staged migration ve historical binding

5.0E iki additive revision ile uygulanır:

1. **E1 — schema introduction:** security tabloları, nullable `companies.tenant_id`/`bulk_upload_batches.tenant_id`, quarantine tablosu ve index'ler eklenir; mevcut davranış henüz enforcement kazanmaz.
2. **Trusted provisioning/binding gate:** tenant'lar yalnız Bölüm 16'daki provisioning contract ile oluşturulur. Historical resource binding aynı trusted channel'da explicit resource listesi + tenant_key + idempotency key ile yapılır; automatic tenant inference yoktur.
3. **E2 — validation/enforcement:** her non-null historical `analysis_run_scope_claims.tenant_id` canonical regex'e uymalı ve mevcut `security_tenants.tenant_key` ile eşleşmelidir. Invalid/non-matching satır varsa E2 migration fail eder; satır sessizce normalize edilmez. Null/unbound historical company/batch/run quarantine edilir ve API'den görünmez.
4. E2, `analysis_run_scope_claims.tenant_id → security_tenants.tenant_key` FK'sini ve yeni INSERT için non-null/known tenant trigger'ını etkinleştirir. Company/batch yeni INSERT'leri için non-null tenant FK zorunludur. Historical null satırlar yalnız explicit remediation için korunur.

Dual-write yasaktır. Backfill yalnız authoritative column'a explicit trusted provisioning transaction'ıyla yapılır. `tenant_key` üzerinde case conversion veya invalid değeri yeni tenant olarak yaratma yoktur.

Downgrade:

- E2→E1 yalnız enforcement trigger/FK'lerini kaldırır; veri/kolon silmez.
- E1→pre-5.0E, herhangi bir security principal/membership/provisioning row'u veya non-null resource tenant binding'i varsa fail-closed reddedilir.
- Boş state'te E1 downgrade security tablolarını dependency-safe ters sırada kaldırabilir.
- Gerçek PostgreSQL `upgrade E1 → provision fixtures → upgrade E2 → downgrade E1 → upgrade E2` ve boş-state tam downgrade testleri zorunludur.

---

## 10. OAuth/OIDC/JWT ve Claims Trust Profile

### 10.1 Vetted library — bağlayıcı v1 kararı

Python v1 doğrulayıcısı yalnız `PyJWT[crypto]>=2.10,<3` kullanır. Dependency maintained olmalı, upstream security fixes alan destekli major family'de kalmalı ve lock/build vulnerability taramasından geçmelidir. Major upgrade ayrı security review gerektirir. Uygulama kendi signature primitive'ini yazmaz.

PyJWT default'ları güvenlik politikası değildir. Token önce bounded strict pre-parser'dan geçer; sonra PyJWT yalnız explicit issuer/audience/algorithm/key/required-claims seçenekleriyle çağrılır; ardından application-level claims validation uygulanır.

### 10.2 Credential transport

- Yalnız tek `Authorization: Bearer <token>` kabul edilir.
- Birden fazla Authorization header, virgüllü credential, farklı scheme, obs-fold veya boş token reddedilir.
- Query, cookie, form, WebSocket subprotocol veya custom identity header'dan token alınmaz.
- Maksimum encoded token 16 KiB ve tam olarak üç compact segmenttir.
- Refresh token, ID token, opaque token, JWE ve nested JWT reddedilir.

### 10.3 Strict JWS parser/crypto profili

- Header ve payload UTF-8 JSON object olmak zorundadır; top-level array/scalar reddedilir.
- `object_pairs_hook` ile duplicate header key ve duplicate claim key parse aşamasında reddedilir.
- Segmentler padding'siz canonical Base64URL'dir; `=`, whitespace, invalid alphabet, malformed padding veya decode→re-encode eşitsizliği reddedilir.
- `alg`, `kid`, `typ` zorunludur.
- `typ` issuer profile'ındaki exact `at+jwt` veya `JWT` closed set'ine uyar.
- `crit` yoksa kabul; varsa boş olsa dahi reddedilir. `b64` alanı ve özellikle `b64=false` reddedilir.
- `none`, tüm `HS*` ve issuer allowlist'i dışındaki algorithm reddedilir.
- İzinli algoritmalar yalnız `RS256`, `PS256`, `ES256`'dır ve issuer bazında ayrıca daraltılır.
- RSA modulus en az 2048 bit; exponent odd ve `>=65537` olmalıdır.
- ES256 yalnız P-256/secp256r1 key kabul eder; başka curve reddedilir.
- JWK `kty` algorithm ile exact uyumlu olmalıdır; `use` zorunlu `sig`, `key_ops` varsa `verify` içermelidir.
- JWKS içindeki `x5c`, `x5t`, `x5t#S256` key material source olarak kullanılmaz ve içeren key reddedilir.
- Token header'ındaki `jwk`, `jku`, `x5u`, `x5c`, `x5t`, `x5t#S256` reddedilir; remote URL header'ından key yüklenmez.
- Audience exact string equality'dir. String audience tek elemanlı set, array audience duplicate içermeyen string set olarak parse edilir; wildcard/substring/case folding yoktur.
- NumericDate yalnız finite signed 64-bit integer seconds'tır; bool/float/string, overflow ve `exp<=iat` reddedilir.
- Raw token, decoded header/claim set ve key material log/audit/error'a girmez.

### 10.4 Exact claim normalization

| Claim | Exact v1 sözleşmesi |
|---|---|
| `iss` | 1–512 ASCII; configured issuer ile byte-for-byte exact; trim/case/URL normalization yok |
| `sub` | 1–255 ASCII; regex `^[A-Za-z0-9._:@/|+\-]{1,255}$`; case-sensitive; whitespace/Unicode yok; authoritative namespace `(iss,sub)` |
| `tenant_id` | Bölüm 9 canonical tenant_key; 3–63 lowercase ASCII; exact, normalization yok |
| `jti` | zorunlu; 16–128 ASCII; regex `^[A-Za-z0-9._~:\-]{16,128}$`; audit correlation/revocation diagnosis ID'si, one-time nonce değildir |
| `claims_version` | exact string `auth-claims/1`; trim/case/version coercion yok |
| `aud` | issuer profile'ın HUMAN veya SERVICE exact audience'ını içerir |
| `iat`,`exp` | zorunlu NumericDate integer |
| `nbf` | opsiyonel NumericDate integer; varsa doğrulanır |

Aynı semantiği taşıyan alternatif claim'ler (`tenant`, `tid`, namespaced tenant vb.) profile'da tanımlı canonical claim ile birlikte bulunursa ambiguous-source olarak reddedilir. Duplicate JSON keys her durumda reddedilir.

Accepted claims-version listesi v1'de yalnız `{"auth-claims/1"}`'dir. Unknown/deprecated version backward-compatibility window olmadan fail-closed `401 INVALID_TOKEN`, internal reason `UNSUPPORTED_CLAIMS_VERSION` ve required `CLAIMS_VERSION_REJECTED` audit event'i üretir. Version normalization yasaktır. Yeni version ayrı tasarım/schema compatibility kararıdır.

`jti` benzersizliğini issuer garanti eder; backend v1'de her görülmeyi replay saymaz çünkü bearer token doğal olarak token ömrü içinde tekrar kullanılabilir. Aynı JTI grant/idempotency kaynağı değildir. Per-JTI replay detection future hardening'dir.

### 10.5 HUMAN token profile

Zorunlu: `iss`, `sub`, HUMAN audience, `tenant_id`, `exp`, `iat`, `jti`, `claims_version` ve `acr` veya non-empty `amr` array. Local `security_principals.kind=HUMAN` authoritative'dir. Opsiyonel token `principal_kind` bulunursa exact `HUMAN` olmalı; mismatch reddedilir.

Strength mapping issuer profile'ında closed rule set'tir:

- `PHISHING_RESISTANT`: configured high-assurance `acr` veya `amr` içinde `webauthn`/`hwk`;
- `STRONG`: configured MFA `acr` veya `amr` içinde `mfa`/`otp`;
- `BASIC`: yalnız configured password/basic `acr` veya `amr` içinde `pwd`;
- unknown/empty/contradictory evidence: token reddi; BASIC'e sessiz downgrade yok.

Active tenant membership zorunludur.

### 10.6 SERVICE token profile

Client-credentials service token'ında zorunlu: `iss`, `sub`, SERVICE-specific audience, `client_id`, `tenant_id`, `exp`, `iat`, `jti`, `claims_version`. `client_id` 1–255 ASCII ve matched active `security_subject_bindings.service_client_id` ile exact eşleşir. Binding'in bağlı olduğu local `security_principals.kind=SERVICE` authoritative'dir; token hint varsa exact SERVICE olmalı. HUMAN binding'e SERVICE token ve tersi reddedilir.

SERVICE için `acr/amr` zorunlu değildir. Strength, asymmetric signature + service audience + exact `(iss,sub,client_id)` binding ile **STRONG** olur; hiçbir service token `PHISHING_RESISTANT` sayılmaz. Service principal için active tenant membership ve en az bir active service-safe role assignment zorunludur. `SERVICE_OPERATOR` yalnız built-in varsayılan service rolüdür, zorunlu değildir; tüm permission'ları `service_allowed=true` olan custom role da geçerlidir. Tek bir `service_allowed=false` permission içeren rolün SERVICE principal'a atanması ve resolution sırasında kabulü kesin reddedilir. Interactive/MFA-only ve security provisioning action'ları SERVICE için grant olamaz. Service principal local status/`tokens_valid_after` ile revoke edilir.

### 10.7 Zaman politikası

- `exp-iat` 1 saniye ile 15 dakika arasındadır.
- Allowed clock skew exact 60 saniyedir.
- `iat > now+60s`, `exp <= now-60s`, `nbf > now+60s` reddedilir.
- Context `expires_at` zorunludur.
- Principal `tokens_valid_after` timezone-aware UTC `TIMESTAMPTZ` olarak PostgreSQL mikrosaniye hassasiyetiyle saklanır; saniyeye truncation/rounding yapılmaz. JWT NumericDate `iat` UTC-aware whole-second `datetime`'a parse edilir (`microsecond=0`). Token `iat < tokens_valid_after` ise revoked; exact timestamp eşitliği ve daha yeni token kabul edilir.
- 5.0D 15 dakikalık context age ve 60 saniyelik future-skew sınırları korunur.

---

## 11. Static Issuer Registry — OIDC Discovery Yok

5.0E v1 **OIDC Discovery kullanmaz**. `/.well-known/openid-configuration` çağrılmaz. Issuer, HUMAN/SERVICE audiences ve JWKS URI yalnız trusted static production config'ten gelir. Token claim/header'dan URL türetilmez. OIDC Discovery future integration/hardening kapsamıdır.

`OidcIssuerProfile` immutable config sözleşmesi:

```python
@dataclass(frozen=True)
class OidcIssuerProfile:
    issuer: str
    human_audiences: frozenset[str]
    service_audiences: frozenset[str]
    jwks_uri: str
    jwks_allowed_hosts: frozenset[str]
    allowed_algorithms: frozenset[JwtAlgorithm]
    allowed_types: frozenset[str]
    tenant_claim: str
    claims_version_claim: str
    strength_mapping: tuple[AuthenticationStrengthRule, ...]
    jwks_fresh_ttl_seconds: int
    http_timeout_seconds: float
```

Kurallar:

- issuer ve JWKS URI HTTPS ve fragment/query/userinfo içermeyen absolute URL olmalıdır;
- redirects varsayılan kapalıdır;
- JWKS host'u config'te sabittir; token header'ı endpoint seçemez;
- JWKS host'u issuer profile'ındaki explicit host allowlist'te olmalıdır;
- duplicate issuer/audience profile startup'ta reddedilir;
- HUMAN ve SERVICE audience setleri non-empty ve disjoint olmalıdır;
- en az bir asymmetric algorithm zorunludur;
- production issuer allowlist boşsa readiness false'dur.

---

## 12. JWKS ve Key Rotation

### 12.1 Kapalı cache limitleri

| Parametre | v1 default | İzinli sınır |
|---|---:|---:|
| Normal fresh TTL | 300 s | 30–900 s |
| Stale-while-error | 120 s | 0–300 s |
| Hard stale age | fresh TTL + stale window; default 420 s | en fazla 1200 s |
| Minimum forced-refresh interval/issuer | 30 s | 10–120 s |
| Unknown-kid negative TTL | 60 s | 10–120 s |
| Negative cache size/issuer | 256 | 32–1024 |
| Refresh timeout | 2 s | 0.25–3 s |
| JWKS response body | 256 KiB | hard max 256 KiB |
| Parsed key count | 32 | hard max 32 |

Cache issuer bazlıdır; yalnız validated public verification key metadata'sı taşır. Negative cache `(issuer,kid)` LRU'dur; TTL-expired önce, sonra least-recently-used entry evict edilir. Kid maksimum 128 ASCII'dir; invalid kid cache'e eklenmeden reddedilir. `Cache-Control` yalnız local fresh TTL'yi kısaltabilir. ETag/If-None-Match desteklenir.

### 12.2 Network güvenliği

- Yalnız static configured HTTPS JWKS URI.
- Redirect sayısı **0**; 3xx reddedilir.
- Exact configured host allowlist; token etkileyemez.
- Response content type JSON allowlist, body limit stream sırasında uygulanır.
- Duplicate JWK kid, duplicate JSON key, key-count/body limit aşımı tüm response'u invalid yapar.
- DNS/network error raw ayrıntısı public cevaba çıkmaz.

### 12.3 Refresh ve unknown-kid decision table

1. Fresh cache + known kid: network yok, key kullanılır.
2. Fresh cache + negative-cache hit: network yok, `401 INVALID_TOKEN`.
3. Unknown kid + issuer forced-refresh interval açık: issuer single-flight refresh'e katılır; request başına en fazla bir refresh.
4. Refresh başarılı + kid bulundu: key profile doğrulanır ve token verify edilir.
5. Refresh başarılı + kid yok: negative cache'e eklenir, `401 INVALID_TOKEN`.
6. Unknown kid + minimum refresh interval henüz dolmadı: refresh suppressed, bounded negative cache'e eklenir, `401 INVALID_TOKEN`; her random kid network çağrısı üretemez.
7. Refresh timeout/outage ve cache hard-stale değilse unknown kid doğrulanamaz: `503 AUTHENTICATION_PROVIDER_UNAVAILABLE`; unknown key için stale fallback yok.
8. Hard-stale sonrası tüm key doğrulaması fail-closed `503`.

Concurrent refresh process-local single-flight'tır; dağıtık lock değildir. Her process aynı bounded kurallara uyar. Refresh iş kuyruğu bounded 1/issuer'dır; kapasite doluysa yeni refresh başlamaz ve yukarıdaki suppressed/outage sonucu uygulanır.

### 12.4 Stale-while-error

Fresh TTL dolduğunda refresh denenir. Refresh yalnız provider outage nedeniyle başarısız ve requested kid daha önce doğrulanmış stale cache'te mevcutsa, hard-stale age aşılmadan bu known key kullanılabilir. Bu kullanım metric/audit üretir. Signature veya key-profile validation failure asla stale fallback tetiklemez. Hard stale sonrası kesin ret vardır.

### 12.5 Rotation

Yeni key refresh ile kabul edilir. Eski key JWKS response'ta kaldığı sürece kullanılabilir. Provider key'i kaldırırsa başarılı refresh sonrasında local cache'ten de kaldırılır; unexpired eski token artık reddedilir. Uygulama issuer'ın kaldırdığı key'i kendi kararıyla süresiz tutmaz.

### 12.6 Zorunlu metric ve audit

- `unknown_kid`;
- `refresh_attempt`;
- `refresh_suppressed`;
- `negative_cache_hit`;
- `refresh_failure`;
- `stale_key_used`;
- `hard_stale_rejection`.

Metrics backend'inde bu canonical adlara sabit `security.jwks.` namespace prefix'i eklenebilir; semantic metric adı ve label contract'ı değişmez. Metric tag'leri yalnız issuer profile ID ve outcome taşır; raw kid/token yoktur. Refresh failure, stale-key use ve hard-stale rejection security audit'e safe category ile yazılır.

---

## 13. Revocation Modeli

### 13.1 Yerel immediate revocation

Her authenticated request'te principal ve membership authoritative DB'den okunur; positive authorization cache v1'de kullanılmaz.

- principal `SUSPENDED/DISABLED` → authentication/authorization reddi;
- membership `SUSPENDED/REVOKED` veya süresi geçmiş → authorization reddi;
- tenant `SUSPENDED/DISABLED` → tenant-scoped erişim reddi;
- token `iat < principal.tokens_valid_after` → token revoked kabul edilir; exact eşitlik Bölüm 10.7 uyarınca kabul edilir.

`tokens_valid_after` yükseltmek subject'in mevcut tüm token'larını anında geçersiz kılar. Tek token/JTI denylist v1'de yoktur; compromised token için all-token revocation uygulanır.

### 13.2 Provider-side revocation

JWT self-contained olduğu için provider'daki logout/revocation, backend tarafından introspection yapılmadan mevcut token'ı anında iptal edemez. Risk şu iki zorunlu kontrolle sınırlandırılır:

- maksimum kabul edilen token lifetime 15 dakika;
- local principal/membership/tokens-valid-after kontrolü her request'te yapılır.

OIDC introspection ve per-JTI revocation store future hardening'dir; mevcut v1 için doğruluk iddiası değildir.

### 13.3 Authorization revalidation

5.0C pre-persistence revalidation değişmez. Authorization adapter DB state'i yeniden okur; request başında grant verilmiş olsa bile membership/tenant/principal revoke edilmişse persistence yapılmaz ve `AUTHORIZATION_REVOKED` sonucu üretilir.

### 13.4 Adım 9 exact revocation ve zaman semantiği

Adım 9 authoritative identity resolution için positive cache kullanmaz. Her çözümleme tek bir kısa, read-only PostgreSQL snapshot'ından yapılır; revoke transaction'ı commit edilir edilmez sonraki çözümleme yeni committed state'i görür. Repository içinde stale identity fallback, background refresh veya sınırsız retry yoktur.

Zaman kuralları bağlayıcıdır:

- `token_issued_at`, `tokens_valid_after`, `membership_valid_from`, `membership_valid_until` ve `resolved_at` timezone-aware olmalıdır. Naive input `NONCANONICAL_IDENTITY_INPUT`, naive/null/bozuk persisted değer `DATA_INTEGRITY_VIOLATION` üretir. UTC dışı aware input önce aynı instant korunarak açıkça UTC'ye çevrilir; timezone bilgisini sessiz silmek yasaktır. DTO yalnız normalize edilmiş UTC değer taşır.
- PostgreSQL tarafında `TIMESTAMPTZ`, Python tarafında UTC-aware `datetime` kullanılır. Karşılaştırma gerçek instant üzerinde mikrosaniye hassasiyetindedir; sessiz saniye/mikrosaniye truncation veya rounding yapılmaz. JWT NumericDate UTC whole-second instant'a parse edilir ve `microsecond=0` olur; database boundary mikrosaniyeli kalabilir ve hiçbir zaman token hassasiyetine düşürülmez.
- `token_issued_at < principal.tokens_valid_after` kesin `TOKEN_REVOKED_BY_PRINCIPAL`; eşitlik kabul edilir.
- Başarılı resolution için `membership_valid_from <= now` ve `membership_valid_until is None or now <= membership_valid_until` zorunludur; iki sınırda eşitlik kabul edilir.
- Token'ın effective kabul sınırı `max(principal.tokens_valid_after, membership_valid_from)` değeridir; E1/E2'de ayrı membership `tokens_valid_after` alanı yoktur. İleride authoritative non-null membership issuance/revocation boundary eklenirse aynı maximum kümesine katılır; Adım 9 mevcut olmayan alanı varsaymaz. Token bu effective boundary'den eskiyse principal boundary maximum ise `TOKEN_REVOKED_BY_PRINCIPAL`, membership `valid_from` maximum ise `TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY` üretilir; exact eşitlik ve daha yeni değer kabul edilir.
- Membership `REVOKED` veya `SUSPENDED` ise `MEMBERSHIP_INACTIVE` üretilir. E1/E2 modelinde membership-level `tokens_valid_after` alanı bulunmadığı için ayrı `TOKEN_REVOKED_BY_MEMBERSHIP` kodu üretilmez; membership revocation'ın kapalı eşdeğeri `MEMBERSHIP_INACTIVE`'dır. SERVICE için aynı membership sınırı geçerlidir; service-safe role seti eksik/invalid ise ilgili SERVICE rol kodu kullanılır.
- `tokens_valid_after` null olamaz; principal creation sırasında creation instant'ına yazılır ve “revocation boundary yok” için sentinel kullanılmaz. Null değer schema ihlali kabul edilerek `DATA_INTEGRITY_VIOLATION` üretir; epoch/default varsayımı yapılmaz.

---

## 14. AuthenticationContext Mapping

Verified token + authoritative local state aşağıdaki değişmemiş 5.0D contract'a map edilir:

| Alan | HUMAN | SERVICE |
|---|---|---|
| `subject_id` | exact verified `sub` bound to HUMAN principal | exact verified `sub`; `client_id` ayrıca aynı active subject binding'in service_client_id değeriyle doğrulanır |
| `tenant_id` | active membership sonrası canonical tenant_key | active service membership sonrası canonical tenant_key |
| `authentication_method` | sabit `oidc_bearer_jwt` | sabit `oauth2_client_credentials_jwt` |
| `authentication_strength` | closed `acr/amr` mapping sonucu BASIC/STRONG/PHISHING_RESISTANT | exact service binding sonucu STRONG; PHISHING_RESISTANT olamaz |
| `issued_at` | verified `iat` | verified `iat` |
| `expires_at` | verified `exp` | verified `exp` |
| `correlation_id` | validated request correlation; token claim'i değil | aynı |
| `claims_version` | exact `auth-claims/1` | exact `auth-claims/1` |
| `trusted_issuer` | matched static issuer profile | matched static issuer profile |
| `authorization_context_reference` | `authz:v1:H:<membership-id>:<membership-version>:<policy-version>` | `authz:v1:S:<membership-id>:<membership-version>:<policy-version>` |

`authorization_context_reference` authorization grant değildir; audit/cache coherence referansıdır. Authorization her karar noktasında güncel state'i doğrular.

Request-scoped provider immutable context'i döndürür. ContextVar veya process-global current user kullanılmaz.

---

## 15. Closed Authorization Policy

### 15.1 PermissionRegistry sözleşmesi

`PERMISSION_REGISTRY_VERSION = "1.0.0"`. Registry import/startup anında duplicate code, duplicate `(resource_type,action,scope_type)`, bilinmeyen enum, boş alan ve rolün bilinmeyen permission referansını reddeder; sonra immutable kabul edilir.

Her `PermissionDefinition` exact alanları taşır:

- `permission_code`;
- `resource_type`;
- `action`;
- `scope_type`;
- `minimum_authentication_strength`;
- `human_allowed`;
- `service_allowed`;
- `existence_hiding_policy`;
- `audit_requirement`;
- `permission_registry_version`.

`existence_hiding_policy`: `NOT_APPLICABLE`, `DENY_403`, `HIDE_404`, `RUN_CONFLICT_409` kapalı enum'udur.

### 15.2 PermissionRegistry v1.0.0 — exhaustive kayıtlar

| Permission code | Resource/action/scope | Min strength | H/S | Existence policy |
|---|---|---|---|---|
| `system.metadata.read` | SYSTEM/READ/GLOBAL | BASIC | Y/Y | DENY_403 |
| `company.create` | COMPANY/CREATE/TENANT | STRONG | Y/N | DENY_403 |
| `company.list` | COMPANY/LIST/TENANT | BASIC | Y/Y | DENY_403 |
| `company.read` | COMPANY/READ/COMPANY | BASIC | Y/Y | HIDE_404 |
| `period.create` | PERIOD/CREATE/COMPANY | STRONG | Y/N | HIDE_404 |
| `period.list` | PERIOD/LIST/COMPANY | BASIC | Y/Y | HIDE_404 |
| `period.read` | PERIOD/READ/PERIOD | BASIC | Y/Y | HIDE_404 |
| `document.list` | DOCUMENT/LIST/PERIOD | BASIC | Y/Y | HIDE_404 |
| `document.read` | DOCUMENT/READ/DOCUMENT | BASIC | Y/Y | HIDE_404 |
| `analysis_result.list` | ANALYSIS_RESULT/LIST/DOCUMENT | BASIC | Y/Y | HIDE_404 |
| `analysis_result.read` | ANALYSIS_RESULT/READ/ANALYSIS_RESULT | BASIC | Y/Y | HIDE_404 |
| `trial_balance.validate` | TRIAL_BALANCE/VALIDATE/TENANT | STRONG | Y/Y | DENY_403 |
| `trial_balance.upload` | TRIAL_BALANCE/UPLOAD/PERIOD | STRONG | Y/Y | HIDE_404 |
| `bulk_upload.create` | BULK_UPLOAD/CREATE/TENANT | STRONG | Y/N | DENY_403 |
| `bulk_upload.read` | BULK_UPLOAD/READ/BULK_BATCH | BASIC | Y/N | HIDE_404 |
| `bulk_upload.update` | BULK_UPLOAD/UPDATE/BULK_BATCH | STRONG | Y/N | HIDE_404 |
| `bulk_upload.confirm` | BULK_UPLOAD/CONFIRM/BULK_BATCH | STRONG | Y/N | HIDE_404 |
| `analysis.start` | ANALYSIS_RUN/START/COMPANY_PERIOD | STRONG | Y/Y | DENY_403 |
| `analysis.resume` | ANALYSIS_RUN/RESUME/COMPANY_PERIOD | STRONG | Y/Y | RUN_CONFLICT_409 |
| `analysis.resume_source` | ANALYSIS_RUN/RESUME_SOURCE/ANALYSIS_RUN | STRONG | Y/Y | HIDE_404 |
| `analysis.retry` | ANALYSIS_RUN/RETRY/COMPANY_PERIOD | STRONG | Y/Y | RUN_CONFLICT_409 |
| `analysis.cancel.own` | ANALYSIS_RUN/CANCEL_OWN/ANALYSIS_RUN | STRONG | Y/Y | HIDE_404 |
| `analysis.cancel.any` | ANALYSIS_RUN/CANCEL_ANY/ANALYSIS_RUN | STRONG | Y/N | HIDE_404 |
| `analysis.read` | ANALYSIS_RUN/APPLICATION_READ_GUARD/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.payload.read` | ANALYSIS_RUN/APPLICATION_PAYLOAD_GUARD/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.status.read` | ANALYSIS_RUN/STATUS_READ/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.result.read` | ANALYSIS_RUN/RESULT_METADATA_READ/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.result.payload.read` | ANALYSIS_RUN/RESULT_PAYLOAD_READ/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.history.read` | ANALYSIS_RUN/HISTORY_READ/COMPANY_PERIOD | BASIC | Y/Y | DENY_403 |
| `analysis.execution.read` | ANALYSIS_RUN/EXECUTION_METADATA_READ/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `analysis.execution.payload.read` | ANALYSIS_RUN/EXECUTION_PAYLOAD_READ/ANALYSIS_RUN | BASIC | Y/Y | HIDE_404 |
| `security.membership.manage` | SECURITY_MEMBERSHIP/MANAGE/TENANT | PHISHING_RESISTANT | Y/N | HIDE_404 |
| `security.role.assign` | SECURITY_ROLE/ASSIGN/TENANT | PHISHING_RESISTANT | Y/N | HIDE_404 |

### 15.3 Built-in role → permission matrisi

Bu liste exhaustive'dir; “tüm permission'lar” şeklinde implicit expansion yoktur.

| Role | Exact permission codes |
|---|---|
| `TENANT_ADMIN` | `system.metadata.read`, `company.create`, `company.list`, `company.read`, `period.create`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `trial_balance.validate`, `trial_balance.upload`, `bulk_upload.create`, `bulk_upload.read`, `bulk_upload.update`, `bulk_upload.confirm`, `analysis.start`, `analysis.resume`, `analysis.resume_source`, `analysis.retry`, `analysis.cancel.own`, `analysis.cancel.any`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read`, `security.membership.manage`, `security.role.assign` |
| `FINANCE_ADMIN` | `system.metadata.read`, `company.create`, `company.list`, `company.read`, `period.create`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `trial_balance.validate`, `trial_balance.upload`, `bulk_upload.create`, `bulk_upload.read`, `bulk_upload.update`, `bulk_upload.confirm`, `analysis.start`, `analysis.resume`, `analysis.resume_source`, `analysis.retry`, `analysis.cancel.own`, `analysis.cancel.any`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |
| `FINANCE_ANALYST` | `system.metadata.read`, `company.list`, `company.read`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `trial_balance.validate`, `trial_balance.upload`, `bulk_upload.create`, `bulk_upload.read`, `bulk_upload.update`, `analysis.start`, `analysis.resume`, `analysis.resume_source`, `analysis.retry`, `analysis.cancel.own`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |
| `REPORT_VIEWER` | `system.metadata.read`, `company.list`, `company.read`, `period.list`, `period.read`, `analysis_result.list`, `analysis_result.read`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |
| `AUDITOR` | `system.metadata.read`, `company.list`, `company.read`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `bulk_upload.read`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |
| `SERVICE_OPERATOR` | `system.metadata.read`, `company.list`, `company.read`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `trial_balance.validate`, `trial_balance.upload`, `analysis.start`, `analysis.resume`, `analysis.resume_source`, `analysis.retry`, `analysis.cancel.own`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |

SERVICE principal yalnız bütün permission'ları `service_allowed=true` olan bir veya daha fazla active role alabilir; `SERVICE_OPERATOR` bu kurala uyan built-in varsayılandır ve zorunlu değildir. HUMAN principal'a SERVICE-only role/permission, SERVICE principal'a tek bir human-only (`service_allowed=false`) permission dahi içeren role atanması provisioning ve resolution sırasında fail-closed reddedilir.

### 15.4 Kapalı decision algoritması

Adım 10 exact 18 basamaklı fail-fast algoritması Bölüm 15.15'tir. Normatif production akışı yalnız `ResourceSecurityReference → AuthorizationPolicyEngine → engine-selected resolver → authoritative ResourceSecurityScope` biçimindedir. Engine, trusted `VerifiedLocalIdentity`, authoritative `EffectivePermissionSet`, registered `SecurityAction` ve yalnız unresolved `ResourceSecurityReference` taşıyan immutable `PolicyEvaluationRequest` ile başlar; `ResourceSecurityScope` caller girdisi değildir ve yalnız seçilen resolver'ın internal output'u olarak değerlendirmede kullanılır. Engine audit sink çağırmadan immutable `PolicyEvaluationResult` üretir. Unknown action/permission/role/version grant değildir. DB/provider timeout veya integrity failure yalnız fail-closed `INDETERMINATE` internal sonuçtur; Adım 11 bunu değişmemiş 5.0C `AuthorizationDecision` içindeki grant'e çeviremez.

### 15.5 Değişmemiş 5.0C AuthorizationPort decision table

Gerçek public imzalar değiştirilmez:

```python
def authorize_start(scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
def authorize_resume(scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
def authorize_resume_source(source_run_id: str, target_scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
def authorize_read(scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO, *, include_payload: bool) -> AuthorizationDecision: ...
def authorize_cancel(scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
def authorize_retry(scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
```

Her satırda tenant/principal/membership ACTIVE, validity geçerli ve `iat >= tokens_valid_after` zorunludur. Bu ortak precondition'lardan biri sağlanmazsa grant yoktur; revoked identity için typed `UNAUTHORIZED/AUTHORIZATION_REVOKED`, provider/DB outage için retryable `AUTHORIZATION_PROVIDER_UNAVAILABLE` döner ve HTTP adapter 503 üretir.

| Method/checkpoint | Principal | Min strength | Permission | Resource/scope ve subject | Deny/HTTP | Required audit |
|---|---|---|---|---|---|---|
| `authorize_start(scope,actor)` | H/S | STRONG | `analysis.start` | tenant + company + period exact; target run unclaimed veya same subject replay | permission 403; wrong scope/subject existing run 409 | `AUTHZ_ANALYSIS_START` |
| `authorize_resume(scope,actor)` | H/S | STRONG | `analysis.resume` | target tenant/company/period; target replay subject exact | permission 403; wrong target scope/subject 409 | `AUTHZ_ANALYSIS_RESUME` |
| `authorize_resume_source(source_run_id,target_scope,actor)` | H/S | STRONG | `analysis.resume_source` | source tenant/company/period == target; source may be another subject within same tenant only with permission | missing/denied/cross-tenant source 404 | `AUTHZ_RESUME_SOURCE` |
| `authorize_retry(scope,actor)` | H/S | STRONG | `analysis.retry` | target scope exact; original RESUME also source check above | permission 403; target conflict 409; missing/denied source 404 | `AUTHZ_ANALYSIS_RETRY` |
| `authorize_cancel(scope,actor)` | H/S owner; HUMAN non-owner | STRONG | owner `analysis.cancel.own`; non-owner HUMAN `analysis.cancel.any` | claim tenant exact; `cancel.own` yalnız resolver'ın authoritative `owner_subject` alanını, `cancel.any` yalnız same-tenant scope + permission'ı kullanır | missing/cross-tenant 404; same-tenant permission deny 403 | `AUTHZ_ANALYSIS_CANCEL` |
| `authorize_read(scope,actor,include_payload=False)` | H/S | BASIC | application guard `analysis.read` | tenant/company/period/run exact; endpoint adapter ayrıca exact status/result/history/execution permission'ını zorunlu kılar | missing/cross-tenant ID 404; same-tenant permission deny 403 | `AUTHZ_ANALYSIS_READ_METADATA` |
| `authorize_read(scope,actor,include_payload=True)` | H/S | BASIC | application guards `analysis.read` + `analysis.payload.read` | tenant/company/period/run exact; endpoint adapter ayrıca exact result/execution payload permission'ını zorunlu kılar | missing/cross-tenant ID 404; same-tenant permission deny 403 | `AUTHZ_ANALYSIS_READ_PAYLOAD` |
| pre-persistence revalidation | original çağrının H/S türü | original permission minimumu | original `analysis.start`/`analysis.resume`/`analysis.retry` ve gerekiyorsa `analysis.resume_source` | current tenant/principal/membership/version + target scope + subject; resume source tekrar doğrulanır | deny/revoke/outage → persistence yok; typed outcome; HTTP 403/404/409 veya 503 yukarıdaki exact nedenle | `AUTHZ_PRE_PERSIST_REVALIDATED` |

`authorize_read` public imzası query kind taşımadığı için method generic application guard'ı uygular. Exact endpoint permission'ı 5.0D/5.0E boundary'de aynı `AuthorizationPolicyEnginePort` ile ayrıca değerlendirilir; iki kontrolden biri deny ise materialization yoktur. Böylece public 5.0C imzası değişmeden endpoint ayrımı kapalı kalır.

### 15.6 Adım 10 internal policy contract'ları

Adım 10 yeni bir public/application authorization contract'ı yaratmaz ve 5.0C `AuthorizationPort`/`AuthorizationDecision` imzalarını değiştirmez. Aşağıdaki tipler yalnız framework-bağımsız security core içindedir; FastAPI, Pydantic, SQLAlchemy, HTTP status veya response envelope içermez.

```python
class PolicyOperationKind(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    CANCEL = "CANCEL"
    RETRY = "RETRY"
    ADMINISTER = "ADMINISTER"

class SubjectPredicateKind(str, Enum):
    NONE = "NONE"
    SELF = "SELF"
    INITIATOR = "INITIATOR"
    SAME_TENANT = "SAME_TENANT"
    EXPLICIT_SUBJECT_MATCH = "EXPLICIT_SUBJECT_MATCH"

class OwnershipRequirement(str, Enum):
    NONE = "NONE"
    RESOURCE_OWNER_REQUIRED = "RESOURCE_OWNER_REQUIRED"
    TENANT_OWNERSHIP_REQUIRED = "TENANT_OWNERSHIP_REQUIRED"

class PolicyScopeType(str, Enum):
    ANALYSIS_RUN = "ANALYSIS_RUN"
    ANALYSIS_RESULT = "ANALYSIS_RESULT"
    EXECUTION = "EXECUTION"
    COMPANY = "COMPANY"
    FINANCIAL_PERIOD = "FINANCIAL_PERIOD"
    DOCUMENT = "DOCUMENT"
    BULK_UPLOAD_BATCH = "BULK_UPLOAD_BATCH"
    TRIAL_BALANCE = "TRIAL_BALANCE"
    SYSTEM = "SYSTEM"
    TENANT = "TENANT"
    COMPANY_PERIOD = "COMPANY_PERIOD"

class PolicyExistenceHiding(str, Enum):
    NONE = "NONE"
    HIDE_ON_TENANT_MISMATCH = "HIDE_ON_TENANT_MISMATCH"
    HIDE_ON_OWNERSHIP_MISMATCH = "HIDE_ON_OWNERSHIP_MISMATCH"
    ALWAYS_HIDE_DENIAL = "ALWAYS_HIDE_DENIAL"

class PolicyAuditRequirement(str, Enum):
    NONE = "NONE"
    DENY_ONLY = "DENY_ONLY"
    ALLOW_AND_DENY = "ALLOW_AND_DENY"
    SECURITY_CRITICAL = "SECURITY_CRITICAL"

@dataclass(frozen=True)
class SecurityAction:
    action_code: str
    required_permission: str
    resource_type: PolicyScopeType
    operation_kind: PolicyOperationKind
    minimum_authentication_strength: PolicyAuthenticationStrength
    allowed_principal_kinds: frozenset[IdentityKind]
    ownership_requirement: OwnershipRequirement
    subject_predicate_kind: SubjectPredicateKind
    existence_hiding_policy: PolicyExistenceHiding
    audit_requirement: PolicyAuditRequirement
    registry_version: str
```

`PolicyScopeType` v1 exact serialized member listesi aşağıdaki 11 satırdır; enum name ve `.value` aynı literal'dir, alias yoktur:

| # | Member / serialized value | Resolver family |
|---:|---|---|
| 1 | `ANALYSIS_RUN` | durable |
| 2 | `ANALYSIS_RESULT` | durable |
| 3 | `EXECUTION` | durable |
| 4 | `COMPANY` | durable |
| 5 | `FINANCIAL_PERIOD` | durable |
| 6 | `DOCUMENT` | durable |
| 7 | `BULK_UPLOAD_BATCH` | durable |
| 8 | `TRIAL_BALANCE` | durable |
| 9 | `SYSTEM` | synthetic |
| 10 | `TENANT` | synthetic |
| 11 | `COMPANY_PERIOD` | synthetic |

Legacy `TRIAL_BALANCE_RESOURCE` veya lowercase/compatibility alias kabul edilmez; closed-enum constructor/import fixture fail-closed reddeder. Manifest, resolver routing ve golden-vector scope seti bu tabloyla birebirdir.

`SecurityAction` invariant'ları bağlayıcıdır:

- `action_code` global unique ve `^[a-z][a-z0-9_.-]{2,95}$` canonical formundadır; duplicate veya unknown action fail-closed `UNKNOWN_ACTION` olur.
- `required_permission` exact 33 kayıtlı immutable PermissionRegistry'de bulunur; unknown değer `UNKNOWN_PERMISSION` olur.
- `resource_type`, permission'ın authorization `scope_type` değerinden aşağıdaki kapalı mapping ile türetilen `PolicyScopeType` üyesidir; domain target `PermissionDefinition.resource_type` alanıyla karıştırılmaz. Unknown/string scope kesin reddedilir. `allowed_principal_kinds` boş olamaz ve yalnız kapalı `IdentityKind` üyeleridir.
- Minimum strength, operation, ownership requirement, predicate, hiding ve audit alanları string-coerce edilmeden kendi kapalı enum tiplerini taşır.
- Owner kontrolünün tek sahibi `ownership_requirement` alanıdır. `RESOURCE_OWNER_REQUIRED` ile predicate `NONE` olmak zorundadır; v1 `SubjectPredicateKind` içinde `OWNER` yoktur. Böylece owner iki kez değerlendirilmez. `TENANT_OWNERSHIP_REQUIRED`, identity ve resolver'ın authoritative scope tenant'ını exact eşleştirir. `NONE`, `SYSTEM`, ayrı subject predicate ile tamamen tanımlanmış action veya Model A same-tenant resolution + exact permission ile tamamen tanımlanmış tenant-wide action için kullanılabilir; caller metadata'sı bu kararı genişletemez.
- Action registry version exact `PERMISSION_REGISTRY_VERSION` ile eşleşir. DTO HTTP status üretmez ve 5.0C `AuthorizationPort` metodunun yerine geçmez.

Mevcut 5.0E `PermissionDefinition.existence_hiding_policy` mapping'i internal action oluşturulurken exact yapılır: `NOT_APPLICABLE` ve `DENY_403 → NONE`, `HIDE_404 → ALWAYS_HIDE_DENIAL`, `RUN_CONFLICT_409 → HIDE_ON_TENANT_MISMATCH`. Bu internal mapping 5.0A–5.0D public contract'larını değiştirmez; HTTP 403/404/409 seçimi yine sonraki boundary'nin sorumluluğudur.

V1 action registry, 33 PermissionRegistry satırından birebir ve deterministik derlenir: `action_code == required_permission == permission_code`. Compiler **yalnız** aşağıdaki immutable lookup tablolarını kullanır; prefix/substring/wildcard, `else` fallback veya unknown değeri en yakın enum'a coercion yasaktır. Unknown source strength `UNKNOWN_PERMISSION`, unknown source action `UNKNOWN_ACTION` olarak fail-closed reddedilir ve action registry kurulmaz.

Permission metadata strength → internal HUMAN strength mapping'i exhaustive'dir:

| `PermissionDefinition.minimum_authentication_strength` | `SecurityAction.minimum_authentication_strength` |
|---|---|
| `BASIC` | `PASSWORD` |
| `STRONG` | `MFA` |
| `PHISHING_RESISTANT` | `PHISHING_RESISTANT` |

`SERVICE_CREDENTIAL` bu tablodan **asla** üretilmez. HUMAN evaluation yukarıdaki ordered eksende minimum kontrolü yapar. SERVICE evaluation yalnız action `allowed_principal_kinds` içinde SERVICE ise ve trusted context exact `SERVICE_CREDENTIAL` ise geçebilir; permission'ın HUMAN minimum değeri SERVICE credential ile sıralanmaz. HUMAN principal `SERVICE_CREDENTIAL` ile, SERVICE principal `PASSWORD/MFA/PHISHING_RESISTANT` ile geçemez. Bu cross-axis durumlar `INSUFFICIENT_AUTHENTICATION_STRENGTH`, kind allowlist ihlali ise daha erken `PRINCIPAL_KIND_NOT_ALLOWED` üretir.

Source permission action → `PolicyOperationKind` mapping'i de exhaustive'dir:

| Exact source action | Operation | Exact source action | Operation |
|---|---|---|---|
| `CREATE` | `CREATE` | `LIST` | `READ` |
| `READ` | `READ` | `VALIDATE` | `EXECUTE` |
| `UPLOAD` | `EXECUTE` | `UPDATE` | `UPDATE` |
| `CONFIRM` | `EXECUTE` | `START` | `EXECUTE` |
| `RESUME` | `EXECUTE` | `RESUME_SOURCE` | `EXECUTE` |
| `RETRY` | `RETRY` | `CANCEL_OWN` | `CANCEL` |
| `CANCEL_ANY` | `CANCEL` | `APPLICATION_READ_GUARD` | `READ` |
| `APPLICATION_PAYLOAD_GUARD` | `READ` | `STATUS_READ` | `READ` |
| `RESULT_METADATA_READ` | `READ` | `RESULT_PAYLOAD_READ` | `READ` |
| `HISTORY_READ` | `READ` | `EXECUTION_METADATA_READ` | `READ` |
| `EXECUTION_PAYLOAD_READ` | `READ` | `MANAGE` | `ADMINISTER` |
| `ASSIGN` | `ADMINISTER` |  |  |

Evaluation `resource_type` mapping'i exact `GLOBAL→SYSTEM`, `TENANT→TENANT`, `COMPANY→COMPANY`, `PERIOD→FINANCIAL_PERIOD`, `DOCUMENT→DOCUMENT`, `ANALYSIS_RESULT→ANALYSIS_RESULT`, `BULK_BATCH→BULK_UPLOAD_BATCH`, `COMPANY_PERIOD→COMPANY_PERIOD`, `ANALYSIS_RUN→ANALYSIS_RUN` biçimindedir. Existence mapping'i yukarıdaki kapılı tabloya göredir. `system.metadata.read`, `analysis.cancel.own` ve `analysis.cancel.any` predicate'i `NONE`, diğer v1 action'lar `SAME_TENANT` kullanır. `analysis.cancel.own` exact `RESOURCE_OWNER_REQUIRED`; `analysis.cancel.any` exact `NONE` ownership requirement'ına sahiptir. Collection/create action'ları var olmayan target row'u değil permission scope'una ait authoritative parent resource'u değerlendirir.

`INITIATOR` yalnız gelecekte ayrıca kaydedilmiş action metadata'sı gerçekten initiator eşleşmesi isterse kullanılabilir; v1 registry'de böyle bir action yoktur.

#### 15.6.1 SecurityAction v1 literal golden manifesti

Aşağıdaki 33 satır compiler'ın literal golden sonucudur. `K` sütununda `H=HUMAN`, `S=SERVICE`; `Own` sütununda `N=NONE`, `T=TENANT_OWNERSHIP_REQUIRED`, `O=RESOURCE_OWNER_REQUIRED`; `Hiding` sütununda `N=NONE`, `A=ALWAYS_HIDE_DENIAL`, `T=HIDE_ON_TENANT_MISMATCH`; `Audit` sütununda `D=DENY_ONLY`, `B=ALLOW_AND_DENY`, `C=SECURITY_CRITICAL` anlamına gelir. Her satırda `action_code=required_permission=Code` ve `registry_version="1.0.0"` zorunludur.

| Code | Operation | Evaluation scope | Min | K | Own | Predicate | Hiding | Audit |
|---|---|---|---|---|---|---|---|---|
| `system.metadata.read` | READ | SYSTEM | PASSWORD | H/S | N | NONE | N | D |
| `company.create` | CREATE | TENANT | MFA | H | T | SAME_TENANT | N | B |
| `company.list` | READ | TENANT | PASSWORD | H/S | T | SAME_TENANT | N | D |
| `company.read` | READ | COMPANY | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `period.create` | CREATE | COMPANY | MFA | H | T | SAME_TENANT | A | B |
| `period.list` | READ | COMPANY | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `period.read` | READ | FINANCIAL_PERIOD | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `document.list` | READ | FINANCIAL_PERIOD | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `document.read` | READ | DOCUMENT | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis_result.list` | READ | DOCUMENT | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis_result.read` | READ | ANALYSIS_RESULT | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `trial_balance.validate` | EXECUTE | TENANT | MFA | H/S | T | SAME_TENANT | N | B |
| `trial_balance.upload` | EXECUTE | FINANCIAL_PERIOD | MFA | H/S | T | SAME_TENANT | A | B |
| `bulk_upload.create` | CREATE | TENANT | MFA | H | T | SAME_TENANT | N | B |
| `bulk_upload.read` | READ | BULK_UPLOAD_BATCH | PASSWORD | H | T | SAME_TENANT | A | D |
| `bulk_upload.update` | UPDATE | BULK_UPLOAD_BATCH | MFA | H | T | SAME_TENANT | A | B |
| `bulk_upload.confirm` | EXECUTE | BULK_UPLOAD_BATCH | MFA | H | T | SAME_TENANT | A | B |
| `analysis.start` | EXECUTE | COMPANY_PERIOD | MFA | H/S | T | SAME_TENANT | N | B |
| `analysis.resume` | EXECUTE | COMPANY_PERIOD | MFA | H/S | T | SAME_TENANT | T | B |
| `analysis.resume_source` | EXECUTE | ANALYSIS_RUN | MFA | H/S | T | SAME_TENANT | A | B |
| `analysis.retry` | RETRY | COMPANY_PERIOD | MFA | H/S | T | SAME_TENANT | T | B |
| `analysis.cancel.own` | CANCEL | ANALYSIS_RUN | MFA | H/S | O | NONE | A | B |
| `analysis.cancel.any` | CANCEL | ANALYSIS_RUN | MFA | H | N | NONE | A | B |
| `analysis.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.payload.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.status.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.result.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.result.payload.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.history.read` | READ | COMPANY_PERIOD | PASSWORD | H/S | T | SAME_TENANT | N | D |
| `analysis.execution.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `analysis.execution.payload.read` | READ | ANALYSIS_RUN | PASSWORD | H/S | T | SAME_TENANT | A | D |
| `security.membership.manage` | ADMINISTER | TENANT | PHISHING_RESISTANT | H | T | SAME_TENANT | A | C |
| `security.role.assign` | ADMINISTER | TENANT | PHISHING_RESISTANT | H | T | SAME_TENANT | A | C |

Compiler testleri bu 33 satırın **bütün alanlarını** literal fixture ile karşılaştırır. Registry'de eksik/fazla action, mapping tablosunda eksik/fazla source action veya strength, ya da tek alan farkı startup invariant breach'tir.

### 15.7 `ResourceSecurityScope`

```python
class ResourceOwnershipState(str, Enum):
    TENANT_OWNED = "TENANT_OWNED"
    SUBJECT_OWNED = "SUBJECT_OWNED"
    SHARED_WITHIN_TENANT = "SHARED_WITHIN_TENANT"
    SYSTEM_OWNED = "SYSTEM_OWNED"

@dataclass(frozen=True, repr=False)
class ResourceSecurityScope:
    resource_type: PolicyScopeType
    resource_id: UUID | str
    tenant_key: str | None
    company_id: UUID | None
    period_id: UUID | None
    owner_subject: str | None
    initiator_subject: str | None
    resource_version: str
    existence_hiding_policy: PolicyExistenceHiding
    ownership_state: ResourceOwnershipState
    resolved_at: datetime
```

UUID resource'lar gerçek `UUID` instance'ı, analysis-run resource'ı canonical run ID ve SYSTEM resource'ı exact `"system"` taşır; string→UUID coercion yoktur. `tenant_key` mevcutsa canonical external key'dir. `resource_version`, aşağıdaki tek `ResourceSecurityVersionCodec v1` ile üretilen `rsv1:<64-lowercase-sha256>` token'ıdır. JSON, `repr`, ORM serialization veya storage codec kullanılmaz. Tüm zamanlar UTC'ye normalize edilir; kaynak mikrosaniyesi korunur. DTO frozen ve collection-free'dir; ORM/SQLAlchemy entity, HTTP alanı veya mutable mapping/list taşımaz.

#### 15.7.1 `ResourceSecurityVersionCodec v1`

Codec girdisi bir policy-scope manifest adı ve o manifestin exact typed alanlarıdır. Çıktı `"rsv1:" + sha256(canonical_bytes).hexdigest()` olur. Canonical bytes UTF-8'dır ve exact header `b"rsv1\n"` ile başlar. Her alan manifestteki sabit sırada, tam olarak `name + b"|" + type_tag + b"|" + ascii_byte_length + b"|" + payload + b"\n"` kaydıdır. Alan adı ASCII lowercase `^[a-z][a-z0-9_]*$`; separator byte'ları exact `0x7c` (`|`) ve kayıt sonu exact `0x0a`'dır. Uzunluk payload'ın **byte** sayısıdır, leading zero yoktur.

| Type | Tag | Exact payload |
|---|---|---|
| null | `n` | exact ASCII `null`; length `4` |
| `str` | `s` | değiştirilmemiş UTF-8; normalization/case-fold yok |
| `UUID` | `u` | lowercase canonical 36-character hyphenated form |
| closed enum | `e` | exact `.value`; string coercion yok |
| `int` | `i` | base-10, sign yalnız negatifte, leading zero yok; `bool` int değildir |
| `bool` | `b` | exact ASCII `true` veya `false` |
| `datetime` | `t` | UTC RFC3339, exact 6-digit microsecond ve `Z`: `YYYY-MM-DDTHH:MM:SS.ffffffZ` |
| `date` | `d` | exact `YYYY-MM-DD`; datetime date olarak kabul edilmez |
| `Decimal` | `m` | finite plain decimal, exponent yok; trailing fractional zero'lar silinir, decimal point gerekmezse silinir, `-0` → `0` |
| `bytes` | `x` | lowercase hexadecimal, prefix/separator yok |
| immutable tuple | `q` | `count|` ardından her eleman için `tag:length:payload|`; eleman encoded bytes'a göre ascending sorted ve duplicate-free |

Tuple yalnız manifestin açıkça tuple ilan ettiği alanda kullanılabilir; nested tuple, list, set, frozenset, map veya mutable collection v1'de yasaktır. Non-finite Decimal/float ve tüm float girdiler reddedilir. Aware datetime aynı instant korunarak UTC'ye çevrilir; naive datetime reddedilir. Adapter input sırası etkisizdir: codec yalnız manifest sırasını kullanır.

Her manifestte optional alan **vardır**. Adapter satırda bulunmayan optional değeri typed `None` olarak materialize eder ve codec explicit null kaydı yazar; “missing optional” ile “explicit null” aynı canonical değerdir. Required alan eksik/null ise, forbidden alan inputta bulunursa (null olsa dahi), unknown/fazla alan veya yanlış typed değer varsa constructor/codec `RESOURCE_STATE_INVALID` üretir; silent discard yoktur.

#### 15.7.2 Exact policy-scope manifests

Bu tablo **11 policy evaluation scope type** için fixed alan sırasıdır. Parantez içindeki `?` optional/null kabulünü gösterir; tabloda olmayan alan forbidden'dır.

| Policy evaluation scope | Exact ordered codec fields |
|---|---|
| `SYSTEM` | `resource_type(e)`, `resource_id(s)` |
| `TENANT` | `resource_type(e)`, `tenant_id(u)`, `tenant_key(s)`, `tenant_policy_version(i)` |
| `COMPANY` | `resource_type(e)`, `id(u)`, `tenant_id(u)`, `updated_at(t)` |
| `FINANCIAL_PERIOD` | `resource_type(e)`, `id(u)`, `company_id(u)`, `status(e)`, `updated_at(t)` |
| `COMPANY_PERIOD` | `resource_type(e)`, `resource_id(s)`, `company_id(u)`, `period_id(u)`, `company_updated_at(t)`, `period_updated_at(t)` |
| `DOCUMENT` | `resource_type(e)`, `id(u)`, `company_id(u)`, `period_id(u)`, `checksum(x)`, `processing_status(e)`, `processed_at(t?)` |
| `ANALYSIS_RESULT` | `resource_type(e)`, `id(u)`, `company_id(u)`, `period_id(u)`, `status(e)`, `canonical_result_digest(x)`, `completed_at(t?)` |
| `ANALYSIS_RUN` | `resource_type(e)`, `claim_id(u)`, `run_id(s)`, `company_id(u)`, `financial_period_id(u)`, `tenant_key(s)`, `initiating_subject_reference(s)`, `claim_version(i)`, `claim_status(e)`, `terminal_content_digest(x?)` |
| `EXECUTION` | `resource_type(e)`, `execution_id(u)`, `orchestration_run_id(u)`, `engine_code(e)`, `status(e)`, `input_fingerprint(x)`, `owner_content_digest(x?)`, `claim_version(i)` |
| `BULK_UPLOAD_BATCH` | `resource_type(e)`, `id(u)`, `tenant_id(u)`, `status(e)`, `total_file_count(i)`, `classified_file_count(i)`, `unclassified_file_count(i)`, `duplicate_file_count(i)`, `completed_at(t?)`, `confirmed_at(t?)` |
| `TRIAL_BALANCE` | `resource_type(e)`, `id(u)`, `company_id(u)`, `period_id(u)`, `analysis_type(e)`, `source_mode(e)`, `status(e)`, `canonical_result_digest(x)`, `completed_at(t?)` |

Raw owner/initiator subject codec'e girmez; repository Bölüm 15.13.1'deki versioned `srh1:k<version>:<digest>` değerini `initiating_subject_reference` string alanı olarak verir. Execution `orchestration_run_id`, mevcut `orchestration_engine_executions.run_id` UUID FK alanıdır ve `orchestration_runs.id`'ye bağlanır; external `orchestration_runs.run_id` string'i bu manifestte kullanılmaz. Tenant/company/period/owner claim zincirinden doğrulanır. Digest/UUID/datetime/string field'larının exact type kontrolü manifestten gelir. Her security-relevant kolon değişikliği ilgili manifest girdisini değiştirir; manifest dışı presentation/audit alanı resource version'a girmez.

#### 15.7.3 Primitive codec unit vectors

Bu **11 primitive vector** yalnız low-level typed field encoder'ın unit testidir; hiçbiri tek başına production `ResourceSecurityScope` veya 11-scope manifest acceptance testi değildir. `\n` exact LF byte'ıdır.

| ID / type | Exact canonical bytes (escaped) | Expected SHA-256 |
|---|---|---|
| P1 string | `rsv1\nvalue\|s\|5\|alpha\n` | `4112e5785dbe0fb93c2aa13bcfca060b62a74b7aad7aa51c1b0dbe92fec37584` |
| P2 UUID | `rsv1\nvalue\|u\|36\|00000000-0000-0000-0000-000000000001\n` | `6aacdb03605c07fbad2a9141e65f78553daf6f40273725893b4197d024126050` |
| P3 enum | `rsv1\nvalue\|e\|6\|ACTIVE\n` | `a31f9050ec3ede7944db6850c3ef40b3d6967b71552bf83f8b05e7170361b6da` |
| P4 null | `rsv1\nvalue\|n\|4\|null\n` | `89a4f338911c932fe4db4b6b3dd5be4222660acba371199da5421b4269c3f514` |
| P5 datetime | `rsv1\nvalue\|t\|27\|2026-08-02T10:11:12.123456Z\n` | `00611490784b6f1a6aadca6a59d53525267b0bf0965b5e10999d258fe2f6404f` |
| P6 date | `rsv1\nvalue\|d\|10\|2026-08-02\n` | `36ee68bf8569cbd8ce25f03d2d5d8f9ac3d0429569baa2757ff08c3ac7044985` |
| P7 Decimal | `rsv1\nvalue\|m\|6\|123.45\n` | `55a23f0ec3ae4ad34c622941b57cbe0308698a54c8505b6e77fd6d8a34adf339` |
| P8 bytes | `rsv1\nvalue\|x\|6\|00abff\n` | `94a99ce187077f29745582368b84542a9def95b872fc012c127c40196b74b9bd` |
| P9 sorted tuple | `rsv1\nvalue\|q\|23\|2\|s:5:ADMIN\|s:6:VIEWER\|\n` | `38402b2c976a7107fc08c71fbac293c01e11ad3097102d986955465c4ae3498c` |
| P10 bool | `rsv1\nvalue\|b\|4\|true\n` | `51df15f75b55418adbce836d66ef79ce8e4d52cefaee2dbd7b07299414225164` |
| P11 int | `rsv1\nvalue\|i\|2\|42\n` | `c6b2ad830110aab4798843c26848952187d4b0f5ade4d02c0e7074fe570d6f80` |

#### 15.7.4 Production scope golden vectors

Aşağıdaki **11 production vector**, Bölüm 15.7.2 manifestlerinin her biri için tam ve constructor tarafından kabul edilmesi zorunlu literal girdidir. Canonical bytes içindeki kayıt sırası manifest sırasıdır; escaped `\n` LF'dir. Tablodaki digest'in API token'ı exact `rsv1:<digest>`'tir.

| Scope | Exact canonical bytes (escaped) | Expected digest |
|---|---|---|
| `SYSTEM` | `rsv1\nresource_type\|e\|6\|SYSTEM\nresource_id\|s\|6\|system\n` | `a3ecb7d79f55b74d888fcadd6d76ee9305e58db47a8e76f10e2d5d6ebece04a6` |
| `TENANT` | `rsv1\nresource_type\|e\|6\|TENANT\ntenant_id\|u\|36\|00000000-0000-0000-0000-000000000001\ntenant_key\|s\|9\|acme-prod\ntenant_policy_version\|i\|1\|7\n` | `93f4b52312fac4ad00c1bd053015b1b6a962e882721d8db0042926a4ad8cb0ef` |
| `COMPANY` | `rsv1\nresource_type\|e\|7\|COMPANY\nid\|u\|36\|00000000-0000-0000-0000-000000000002\ntenant_id\|u\|36\|00000000-0000-0000-0000-000000000001\nupdated_at\|t\|27\|2026-08-02T10:11:12.123456Z\n` | `a3db9c1b7cf50a6e6eeef3b40b6e776bf20c5fd26ce999c52882025186fbf619` |
| `FINANCIAL_PERIOD` | `rsv1\nresource_type\|e\|16\|FINANCIAL_PERIOD\nid\|u\|36\|00000000-0000-0000-0000-000000000003\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nstatus\|e\|6\|active\nupdated_at\|t\|27\|2026-08-02T10:11:13.123456Z\n` | `f54c69b689d9e5964259a6c35c1a20bf2c93808ad30c643df8324605d0ad070c` |
| `COMPANY_PERIOD` | `rsv1\nresource_type\|e\|14\|COMPANY_PERIOD\nresource_id\|s\|77\|cp1:00000000-0000-0000-0000-000000000002:00000000-0000-0000-0000-000000000003\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nperiod_id\|u\|36\|00000000-0000-0000-0000-000000000003\ncompany_updated_at\|t\|27\|2026-08-02T10:11:12.123456Z\nperiod_updated_at\|t\|27\|2026-08-02T10:11:13.123456Z\n` | `8f30f3ec03813156b2c34178d943c72e98f04d19ce6255ed97f379be593764eb` |
| `DOCUMENT` | `rsv1\nresource_type\|e\|8\|DOCUMENT\nid\|u\|36\|00000000-0000-0000-0000-000000000004\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nperiod_id\|u\|36\|00000000-0000-0000-0000-000000000003\nchecksum\|x\|64\|abababababababababababababababababababababababababababababababab\nprocessing_status\|e\|9\|completed\nprocessed_at\|n\|4\|null\n` | `0801567e7b6f0cc8dc3852559c43017ee0065ecd25b661a8684e418d61f7ae93` |
| `ANALYSIS_RESULT` | `rsv1\nresource_type\|e\|15\|ANALYSIS_RESULT\nid\|u\|36\|00000000-0000-0000-0000-000000000005\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nperiod_id\|u\|36\|00000000-0000-0000-0000-000000000003\nstatus\|e\|9\|completed\ncanonical_result_digest\|x\|64\|cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd\ncompleted_at\|t\|27\|2026-08-02T10:11:13.123456Z\n` | `342807b7d80b397780c4899d629626b5e0248646ff8c0c220bbc3b29b3ca4f50` |
| `ANALYSIS_RUN` | `rsv1\nresource_type\|e\|12\|ANALYSIS_RUN\nclaim_id\|u\|36\|00000000-0000-0000-0000-000000000006\nrun_id\|s\|8\|run-0001\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nfinancial_period_id\|u\|36\|00000000-0000-0000-0000-000000000003\ntenant_key\|s\|9\|acme-prod\ninitiating_subject_reference\|s\|72\|srh1:k1:1111111111111111111111111111111111111111111111111111111111111111\nclaim_version\|i\|1\|3\nclaim_status\|e\|9\|FINALIZED\nterminal_content_digest\|x\|64\|dededededededededededededededededededededededededededededededede\n` | `e3fd9fd4c37680fbc0a0c55fd8933d87361c7f9e0a794d0867790b3508165309` |
| `EXECUTION` | `rsv1\nresource_type\|e\|9\|EXECUTION\nexecution_id\|u\|36\|00000000-0000-0000-0000-000000000007\norchestration_run_id\|u\|36\|00000000-0000-0000-0000-000000000005\nengine_code\|e\|5\|ratio\nstatus\|e\|9\|completed\ninput_fingerprint\|x\|64\|efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef\nowner_content_digest\|x\|64\|1212121212121212121212121212121212121212121212121212121212121212\nclaim_version\|i\|1\|3\n` | `614d4475e93d666f29c98126f11bde8e0e14433ba3897e9e4ecac7b2c3faa54a` |
| `BULK_UPLOAD_BATCH` | `rsv1\nresource_type\|e\|17\|BULK_UPLOAD_BATCH\nid\|u\|36\|00000000-0000-0000-0000-000000000008\ntenant_id\|u\|36\|00000000-0000-0000-0000-000000000001\nstatus\|e\|9\|confirmed\ntotal_file_count\|i\|1\|4\nclassified_file_count\|i\|1\|3\nunclassified_file_count\|i\|1\|1\nduplicate_file_count\|i\|1\|0\ncompleted_at\|t\|27\|2026-08-02T10:11:12.123456Z\nconfirmed_at\|t\|27\|2026-08-02T10:11:13.123456Z\n` | `5b8a92f2af244f261c8c92def8278a45a52eab2cadd315398cc0390c294b1ff1` |
| `TRIAL_BALANCE` | `rsv1\nresource_type\|e\|13\|TRIAL_BALANCE\nid\|u\|36\|00000000-0000-0000-0000-000000000009\ncompany_id\|u\|36\|00000000-0000-0000-0000-000000000002\nperiod_id\|u\|36\|00000000-0000-0000-0000-000000000003\nanalysis_type\|e\|13\|trial_balance\nsource_mode\|e\|15\|direct_document\nstatus\|e\|9\|completed\ncanonical_result_digest\|x\|64\|3434343434343434343434343434343434343434343434343434343434343434\ncompleted_at\|t\|27\|2026-08-02T10:11:13.123456Z\n` | `baaf857709f5db9910435b5163e78a5beee7557efcc0f66c9f7fc3f9971d3614` |

Her production row için expected constructor sonucu acceptance'tır. Adapter input mapping sırası değişse canonical bytes değişmez. `2026-08-02T13:11:12.123456+03:00`, UTC vector ile aynı bytes/digest'i üretir; bir mikrosaniye veya tek field değişikliği farklı digest üretir. Missing optional ile explicit null aynıdır.

Production negatif matris her 11 scope için applicable olduğu yerde missing required, forbidden field (null olsa da), unknown field, invalid enum, malformed UUID, invalid `cp1` compound ID, naive datetime, inconsistent company/period relation, invalid tenant key ve wrong synthetic-scope field'larını reddeder. Partial manifest production acceptance değildir.

Custom `repr/str` yalnız resource type, redacted resource reference ve ownership state taşır; `owner_subject`, `initiator_subject`, tenant/company/period değerleri veya raw DB alanı göstermez.

| Resource type | `resource_id` | tenant | company | period | owner / initiator | ownership state |
|---|---|---|---|---|---|---|
| `SYSTEM` | exact `system` | yasak | yasak | yasak | ikisi de yasak | `SYSTEM_OWNED` |
| `TENANT` | canonical external `tenant_key` | zorunlu ve `resource_id` ile exact eş | yasak | yasak | ikisi de yasak | `TENANT_OWNED` |
| `COMPANY` | company UUID | zorunlu | `company_id == resource_id` | yasak | ikisi de yasak | `TENANT_OWNED` |
| `FINANCIAL_PERIOD` | period UUID | zorunlu | zorunlu | `period_id == resource_id` | ikisi de yasak | `TENANT_OWNED` |
| `COMPANY_PERIOD` | exact `cp1:<company-uuid>:<period-uuid>` | zorunlu | compound ID içindeki company UUID ile exact eş | compound ID içindeki period UUID ile exact eş; authoritative relation doğrulanır | ikisi de yasak | `TENANT_OWNED` |
| `DOCUMENT` | document UUID | zorunlu | zorunlu | zorunlu | ikisi de yasak | `TENANT_OWNED` |
| `ANALYSIS_RESULT` | result UUID | zorunlu | zorunlu | zorunlu | ikisi de yasak | `TENANT_OWNED` |
| `ANALYSIS_RUN` | canonical run ID | zorunlu | zorunlu | zorunlu | owner authoritative immutable claim ownership binding'inden; initiator yalnız ayrı authoritative alan varsa | `SUBJECT_OWNED` |
| `EXECUTION` | execution UUID | zorunlu | zorunlu | zorunlu | owner bağlı run'ın owner binding'inden; initiator yalnız ayrı authoritative alan varsa | `SUBJECT_OWNED` |
| `BULK_UPLOAD_BATCH` | batch UUID | zorunlu | yasak | yasak | ikisi de yasak | `TENANT_OWNED` |
| `TRIAL_BALANCE` | analysis-result UUID | zorunlu | zorunlu | zorunlu | ikisi de yasak | `TENANT_OWNED` |

`owner_subject` yalnız `SUBJECT_OWNED` için zorunludur. Analysis-run v1 adapter'ı mevcut immutable claim ownership binding'ini yalnız `owner_subject` alanına projekte eder; persistence kolon adının tarihsel olarak `initiating_subject_id` olması aynı değerin `initiator_subject` alanına da kopyalanmasına izin vermez. `initiator_subject` yalnız ayrı authoritative kaynak varsa ve registered action predicate'i `INITIATOR` olduğunda tüketilir; owner ile initiator'ın eşitliği invariant değildir ve biri diğerinin fallback'i olamaz. Scope'ta initiator bulunması tek başına grant değildir. Required alan eksikliği, forbidden alan doluluğu, cross-tenant/company/period ambiguity veya invalid digest `RESOURCE_STATE_INVALID` üretir.

`ResourceOwnershipState` yalnız authoritative metadata sınıflandırmasıdır; tek başına grant veya deny üretmez. Erişim zorunluluğunun tek sahibi registered `SecurityAction.ownership_requirement` alanıdır:

| Ownership requirement | Exact karar |
|---|---|
| `NONE` | owner veya tenant-owner karşılaştırması yapmaz; action'ın predicate/permission/kind kuralları yine zorunludur |
| `TENANT_OWNERSHIP_REQUIRED` | scope tenant metadata'sı zorunludur; Model A scope-qualified resolver zaten durable cross-tenant kaynağı `RESOURCE_NOT_FOUND` yapar, trusted/synthetic scope'ta identity tenant farkı `TENANT_MISMATCH` olur; subject owner aranmaz |
| `RESOURCE_OWNER_REQUIRED` | scope `SUBJECT_OWNED`, `owner_subject` mevcut ve identity `provider_subject` ile exact/case-sensitive eş olmak zorundadır; missing owner `RESOURCE_STATE_INVALID`, fark `RESOURCE_OWNERSHIP_MISMATCH` olur |

`SUBJECT_OWNED` kaynağın gerçek owner metadata'sını taşıdığını söyler; `analysis.cancel.any`, same-tenant resume-source ve cross-subject read gibi tenant-wide action'ları otomatik reddetmez. Owner-only davranış `RESOURCE_OWNER_REQUIRED` ile tek kez uygulanır. V1'de `OWNER` predicate kaldırılmıştır; `RESOURCE_OWNER_REQUIRED + predicate=NONE` compiler invariant'ıdır.

| Action ailesi | V1 action / availability | Ownership | Predicate | Non-owner same-tenant davranışı |
|---|---|---|---|---|
| self read | v1 registry'de ayrı action yok; ileride additive permission gerekir | `NONE` | `SELF` | target subject farkı `SUBJECT_PREDICATE_FAILED` |
| any read | `analysis.read`, payload/status/result/execution read guard'ları | `TENANT_OWNERSHIP_REQUIRED` | `SAME_TENANT` | exact permission varsa ownership nedeniyle reddedilmez |
| self cancel | `analysis.cancel.own` | `RESOURCE_OWNER_REQUIRED` | `NONE` | `RESOURCE_OWNERSHIP_MISMATCH` |
| any cancel | `analysis.cancel.any` | `NONE` | `NONE` | Model A same-tenant scope ve HUMAN exact permission ile ownership/predicate nedeniyle reddedilmez |
| self retry | v1 registry'de ayrı subject-target action yok; `analysis.retry` target COMPANY_PERIOD'dur | `TENANT_OWNERSHIP_REQUIRED` | `SAME_TENANT` | source RESUME ise ayrı resume-source kontrolü uygulanır |
| any retry | v1'de ayrı `retry.any` yok | — | — | implicit expansion yasak; yeni permission olmadan yok |
| resume source self | `analysis.resume_source`, owner caller | `TENANT_OWNERSHIP_REQUIRED` | `SAME_TENANT` | allow için permission + source/target scope invariant'ları gerekir |
| resume source cross-subject | aynı action, owner caller değil | `TENANT_OWNERSHIP_REQUIRED` | `SAME_TENANT` | aynı tenant ve exact permission ile ownership nedeniyle reddedilmez; cross-tenant `RESOURCE_NOT_FOUND` |
| tenant/admin access | `analysis.cancel.any` için `NONE/NONE`; tenant-wide read action'ları için registered `TENANT_OWNERSHIP_REQUIRED/SAME_TENANT` | action manifesti | action manifesti | Model A tenant scope, rol matrisi ve exact permission ayrıca zorunludur |

`ownership_result` ownership requirement kontrolünün, `subject_predicate_result` sonraki predicate kontrolünün bağımsız sonucudur. `ownership_requirement=NONE` için ownership sonucu true'dur; değerlendirilmemiş sonraki kontrol `None` olur. ALLOW için iki alan da true'dur.

Failure result'ta değerlendirilmemiş sonraki kontrol false gibi uydurulmaz: ilgili result alanı `bool | None` olmalı, `None` exact “not evaluated” anlamına gelmelidir.

### 15.8 Policy sonucu ve kapalı reason taxonomy

```python
class PolicyOutcome(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    INDETERMINATE = "INDETERMINATE"

class PolicyReasonCode(str, Enum):
    ALLOWED = "ALLOWED"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    REGISTRY_VERSION_MISMATCH = "REGISTRY_VERSION_MISMATCH"
    TENANT_POLICY_VERSION_MISMATCH = "TENANT_POLICY_VERSION_MISMATCH"
    PRINCIPAL_KIND_NOT_ALLOWED = "PRINCIPAL_KIND_NOT_ALLOWED"
    PERMISSION_NOT_GRANTED = "PERMISSION_NOT_GRANTED"
    INSUFFICIENT_AUTHENTICATION_STRENGTH = "INSUFFICIENT_AUTHENTICATION_STRENGTH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    RESOURCE_OWNERSHIP_MISMATCH = "RESOURCE_OWNERSHIP_MISMATCH"
    SUBJECT_PREDICATE_FAILED = "SUBJECT_PREDICATE_FAILED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_STATE_INVALID = "RESOURCE_STATE_INVALID"
    POLICY_STORE_UNAVAILABLE = "POLICY_STORE_UNAVAILABLE"
    POLICY_STORE_TIMEOUT = "POLICY_STORE_TIMEOUT"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"

class SecuritySeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

@dataclass(frozen=True, repr=False)
class AuditIntent:
    required: bool
    requirement: PolicyAuditRequirement
    event_name: str
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode
    action_code: str
    resource_type: PolicyScopeType
    correlation_id: str
    subject_reference_hash: str
    tenant_key: str
    security_severity: SecuritySeverity

@dataclass(frozen=True)
class PolicyEvaluationResult:
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode
    evaluated_action: str
    principal_id: UUID
    tenant_key: str
    resource_type: PolicyScopeType
    resource_id: UUID | str
    matched_permission: str | None
    authentication_strength: PolicyAuthenticationStrength
    principal_kind: IdentityKind
    subject_predicate_result: bool | None
    ownership_result: bool | None
    existence_hiding_required: bool
    audit_intent: AuditIntent
    policy_registry_version: str
    tenant_policy_version: int
    evaluated_at: datetime
    correlation_id: str
```

Success invariant'ı `ALLOW ↔ reason=ALLOWED ↔ matched_permission=required_permission ↔ predicate/ownership=True` biçimindedir. `INDETERMINATE` yalnız store outage/timeout veya integrity failure için üretilebilir; Adım 11 bunu hiçbir zaman allow'a çeviremez. Raw subject, token, SQL/ORM veya HTTP bilgisi sonuçta yoktur.

Reason metadata registry `outcome`, retryable, hiding, security severity, metric ve safe message'ın tek sahibidir; caller bunları override edemez. DENY/INDETERMINATE sonuçta `matched_permission=None`; ALLOW'da exact required permission zorunludur. UUID, canonical tenant/action/resource, positive versions, UTC `evaluated_at` ve safe correlation constructor invariant'larıdır. Normal evaluation bir reason seçtikten sonra result constructor invariant failure verirse aynı constructor ile ikinci bir result üretilmez; aşağıdaki terminal internal error kullanılır. `repr/str` yalnız enum/code ve safe correlation gösterir.

```python
class PolicyEvaluationConstructionError(Exception):
    __slots__ = (
        "_code", "_safe_message", "_metric_name", "_audit_event",
        "_correlation_id", "_internal_cause", "_frozen",
    )

    def __init__(
        self, *, correlation_id: str | None,
        internal_cause: BaseException | None = None,
    ) -> None:
        # correlation_id None veya safe canonical application correlation ID
        # internal_cause yalnız process-internal chaining içindir
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", "POLICY_EVALUATION_CONSTRUCTION_FAILED")
        object.__setattr__(self, "_safe_message", "Policy evaluation result could not be constructed.")
        object.__setattr__(self, "_metric_name", "security.policy.result_construction_failure")
        object.__setattr__(self, "_audit_event", "security.authorization.indeterminate.data_integrity_violation")
        object.__setattr__(self, "_correlation_id", correlation_id)
        object.__setattr__(self, "_internal_cause", internal_cause)
        Exception.__init__(self, self._safe_message, self._code)
        object.__setattr__(self, "_frozen", True)

    @property
    def code(self) -> str: return self._code
    @property
    def safe_message(self) -> str: return self._safe_message
    @property
    def metric_name(self) -> str: return self._metric_name
    @property
    def audit_event(self) -> str: return self._audit_event
    @property
    def correlation_id(self) -> str | None: return self._correlation_id

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("immutable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("PolicyEvaluationConstructionError is final")

    def __str__(self) -> str: return self._safe_message
    def __repr__(self) -> str:
        return "PolicyEvaluationConstructionError(code='POLICY_EVALUATION_CONSTRUCTION_FAILED')"
```

`PolicyEvaluationConstructionError` final/immutable internal exception'dır; subclassing yasaktır. Normal business deny/reason taxonomy'sine dahil değildir. Constructor yalnız keyword-only safe correlation ve optional internal cause kabul eder; code/message/metric/audit caller tarafından override edilemez. `_internal_cause` property veya serialization yüzeyinde değildir. `args` exact `(safe_message, code)`; `str/repr/args` raw input, correlation value, resource ID, subject, token, SQL veya original exception taşımaz. Freeze sonrası mevcut alan, `args`, yeni attribute veya delete girişimi `AttributeError("immutable")` üretir. Internal `raise error from cause` kullanılabilir fakat boundary `__cause__`, `__context__`, traceback ve `_internal_cause` alanını serialize etmez.

Adım 10 ikinci `PolicyEvaluationResult` constructor çağrısı yapmadan bu terminal error'u yükseltir ve exact metriği üretir. Minimal audit intent event'i exact `audit_event`, severity CRITICAL ve yalnız mevcut safe HMAC subject reference ile best-effort olarak oluşturulur; audit-intent constructor da geçersizse yalnız metric + terminal error kalır. Adım 11 bu internal error'u fail-closed, grant=false `AuthorizationDecision`/provider integrity failure'a map eder; recursive normalization yoktur. Contract testleri constructor signature, code/metadata constants, field/args/new-attribute/delete immutability, subclass rejection, safe `str/repr/args`, raw-cause suppression ve ikinci result-constructor çağrısı olmadığını doğrular.

| Reason | Outcome | Retryable | Hiding | Severity | Exact metric | Safe internal message |
|---|---|---:|---|---|---|---|
| `ALLOWED` | ALLOW | Hayır | Hayır | LOW | `security.policy.allow` | `Policy evaluation allowed.` |
| `UNKNOWN_ACTION` | DENY | Hayır | Evet | HIGH | `security.policy.unknown_action` | `Policy action is invalid.` |
| `UNKNOWN_PERMISSION` | DENY | Hayır | Evet | CRITICAL | `security.policy.unknown_permission` | `Policy permission is invalid.` |
| `UNKNOWN_ROLE` | DENY | Hayır | exact `action.existence_hiding_policy` | HIGH | `security.policy.unknown_role` | `Policy role is invalid.` |
| `REGISTRY_VERSION_MISMATCH` | DENY | Hayır | exact `action.existence_hiding_policy` | HIGH | `security.policy.registry_version` | `Policy version is invalid.` |
| `TENANT_POLICY_VERSION_MISMATCH` | DENY | Hayır | exact `action.existence_hiding_policy` | HIGH | `security.policy.tenant_version` | `Policy version is invalid.` |
| `PRINCIPAL_KIND_NOT_ALLOWED` | DENY | Hayır | exact `action.existence_hiding_policy` | MEDIUM | `security.policy.principal_kind` | `Principal kind is not permitted.` |
| `PERMISSION_NOT_GRANTED` | DENY | Hayır | exact `action.existence_hiding_policy` | MEDIUM | `security.policy.permission_denied` | `Permission is not granted.` |
| `INSUFFICIENT_AUTHENTICATION_STRENGTH` | DENY | Hayır | exact `action.existence_hiding_policy` | MEDIUM | `security.policy.strength` | `Authentication strength is insufficient.` |
| `TENANT_MISMATCH` | DENY | Hayır | Evet | HIGH | `security.policy.tenant_mismatch` | `Resource scope is not accessible.` |
| `RESOURCE_OWNERSHIP_MISMATCH` | DENY | Hayır | exact `action.existence_hiding_policy` | HIGH | `security.policy.ownership` | `Resource scope is not accessible.` |
| `SUBJECT_PREDICATE_FAILED` | DENY | Hayır | exact `action.existence_hiding_policy` | MEDIUM | `security.policy.subject` | `Subject predicate is not satisfied.` |
| `RESOURCE_NOT_FOUND` | DENY | Hayır | Evet | MEDIUM | `security.policy.resource_not_found` | `Resource is not accessible.` |
| `RESOURCE_STATE_INVALID` | DENY | Hayır | Evet | CRITICAL | `security.policy.resource_invalid` | `Resource security state is invalid.` |
| `POLICY_STORE_UNAVAILABLE` | INDETERMINATE | Evet | Evet | HIGH | `security.policy.store_unavailable` | `Policy service is unavailable.` |
| `POLICY_STORE_TIMEOUT` | INDETERMINATE | Evet | Evet | HIGH | `security.policy.store_timeout` | `Policy service is unavailable.` |
| `DATA_INTEGRITY_VIOLATION` | INDETERMINATE | Hayır | Evet | CRITICAL | `security.policy.integrity_failure` | `Policy state is invalid.` |

Exact event registry caller girdisi olmadan şu 17 literal'i üretir:

| Reason | Exact `AuditIntent.event_name` |
|---|---|
| `ALLOWED` | `security.authorization.allow.allowed` |
| `UNKNOWN_ACTION` | `security.authorization.deny.unknown_action` |
| `UNKNOWN_PERMISSION` | `security.authorization.deny.unknown_permission` |
| `UNKNOWN_ROLE` | `security.authorization.deny.unknown_role` |
| `REGISTRY_VERSION_MISMATCH` | `security.authorization.deny.registry_version_mismatch` |
| `TENANT_POLICY_VERSION_MISMATCH` | `security.authorization.deny.tenant_policy_version_mismatch` |
| `PRINCIPAL_KIND_NOT_ALLOWED` | `security.authorization.deny.principal_kind_not_allowed` |
| `PERMISSION_NOT_GRANTED` | `security.authorization.deny.permission_not_granted` |
| `INSUFFICIENT_AUTHENTICATION_STRENGTH` | `security.authorization.deny.insufficient_authentication_strength` |
| `TENANT_MISMATCH` | `security.authorization.deny.tenant_mismatch` |
| `RESOURCE_OWNERSHIP_MISMATCH` | `security.authorization.deny.resource_ownership_mismatch` |
| `SUBJECT_PREDICATE_FAILED` | `security.authorization.deny.subject_predicate_failed` |
| `RESOURCE_NOT_FOUND` | `security.authorization.deny.resource_not_found` |
| `RESOURCE_STATE_INVALID` | `security.authorization.deny.resource_state_invalid` |
| `POLICY_STORE_UNAVAILABLE` | `security.authorization.indeterminate.policy_store_unavailable` |
| `POLICY_STORE_TIMEOUT` | `security.authorization.indeterminate.policy_store_timeout` |
| `DATA_INTEGRITY_VIOLATION` | `security.authorization.indeterminate.data_integrity_violation` |

**Adım 10 PolicyReasonCode kategori sayısı: 17.** Bu 17 kodun tamamı Bölüm 15.15'te en az bir failure/success yolundan erişilebilir. Metadata registry enum ile birebir ve immutable'dır; eksik/fazla mapping import/test invariant breach'tir.

`AuditIntent.event_name` caller girdisi değildir ve exact `"security.authorization." + outcome.value.lower() + "." + reason_code.value.lower()` formülüyle üretilir. Böylece 17 reason için event adları sırasıyla `security.authorization.allow.allowed`, `security.authorization.deny.unknown_action`, ... ve `security.authorization.indeterminate.data_integrity_violation`'dır; alias yoktur. `required`, ALLOW için requirement `ALLOW_AND_DENY|SECURITY_CRITICAL`; DENY için `DENY_ONLY|ALLOW_AND_DENY|SECURITY_CRITICAL`; INDETERMINATE için her zaman true kuralından türetilir. `subject_reference_hash` exact Bölüm 15.13.1 `srh1` output'udur; raw subject yoktur. `AuditIntent` sink'e yazmaz, immutable'dır ve `repr/str` raw tenant/subject taşımaz.

`AuditIntent.requirement` normalde exact `SecurityAction.audit_requirement` değeridir. Ancak action/permission metadata'sının güvenilir olmadığı `UNKNOWN_ACTION`, `UNKNOWN_PERMISSION` ve `DATA_INTEGRITY_VIOLATION` sonuçlarında exact fail-closed requirement `SECURITY_CRITICAL`'dır; caller veya bozuk action alanı kullanılmaz. Diğer 14 reason valid registered action'a sahip olduğundan action requirement'ını kullanır. Bu kural ile tüm 17 reason için `required` tek anlamlıdır.

Audit delivery failure Adım 10 engine reason taxonomy'sinin parçası değildir. Adım 11 adapter'ı ayrı closed `AuthorizationAdapterDecisionCode.AUDIT_REQUIRED_BUT_UNAVAILABLE` kodunu üretir; retryable=true, metric `security.authorization.audit_unavailable`, safe message `Authorization audit is unavailable.` ve event `security.authorization.deny.audit_required_but_unavailable` sabittir. Bu kod Adım 10 reachability sayısına dahil edilmez.

### 15.9 Authoritative permission ve resource portları

```python
@dataclass(frozen=True)
class PolicyMaterializationRequest:
    principal_id: UUID
    membership_id: UUID
    principal_kind: IdentityKind
    tenant_id: UUID
    tenant_key: str
    roles: tuple[str, ...]
    permission_registry_version: str
    tenant_policy_version: int
    role_set_digest: str
    permission_resolution_reference: str
    current_time: datetime
    correlation_id: str

@dataclass(frozen=True)
class EffectivePermissionSet:
    permission_codes: tuple[str, ...]
    role_codes: tuple[str, ...]
    principal_kind: IdentityKind
    membership_id: UUID
    permission_registry_version: str
    tenant_policy_version: int
    role_assignment_version: int
    role_set_digest: str
    materialized_at: datetime

@dataclass(frozen=True)
class ResolvedPolicyRole:
    role_id: UUID
    role_code: str
    role_version: int
    assignment_version: int
    permission_codes: tuple[str, ...]

@dataclass(frozen=True, repr=False)
class ResourceSecurityReference:
    scope_type: PolicyScopeType
    resource_id: UUID | str
    request_tenant_key: str | None
    company_id: UUID | None
    period_id: UUID | None
    expected_resource_version: str | None
    correlation_id: str
    referenced_at: datetime

@dataclass(frozen=True, repr=False)
class PolicyEvaluationRequest:
    identity: VerifiedLocalIdentity
    authentication_strength: PolicyAuthenticationStrength
    action: SecurityAction
    resource_reference: ResourceSecurityReference
    explicit_subject: str | None
    target_subject: str | None
    correlation_id: str
    evaluated_at: datetime
    expected_registry_version: str
    expected_tenant_policy_version: int

class ResourceSecurityRepositoryPort(Protocol):
    def resolve_durable_scope(
        self, *, resource_type: PolicyScopeType, resource_id: UUID | str,
        expected_tenant_key: str, current_time: datetime, correlation_id: str,
    ) -> ResourceSecurityScope: ...

class SyntheticSecurityScopeResolverPort(Protocol):
    def resolve_system_scope(
        self, *, current_time: datetime, correlation_id: str,
    ) -> ResourceSecurityScope: ...

    def resolve_tenant_scope(
        self, *, tenant_key: str, identity_tenant_key: str,
        expected_tenant_policy_version: int, current_time: datetime,
        correlation_id: str,
    ) -> ResourceSecurityScope: ...

    def resolve_company_period_scope(
        self, *, company_id: UUID, financial_period_id: UUID,
        expected_tenant_key: str, current_time: datetime,
        correlation_id: str,
    ) -> ResourceSecurityScope: ...

class AuthorizationPolicyRepositoryPort(Protocol):
    def resolve_role_assignments(self, request: PolicyMaterializationRequest) -> tuple[ResolvedPolicyRole, ...]: ...
    def resolve_effective_permissions(self, request: PolicyMaterializationRequest) -> EffectivePermissionSet: ...
    def validate_registry_versions(self, request: PolicyMaterializationRequest) -> None: ...
    def resolve_tenant_policy_version(self, tenant_id: UUID, *, correlation_id: str) -> int: ...

class AuthorizationPolicyEnginePort(Protocol):
    def evaluate(
        self, *, request: PolicyEvaluationRequest,
        effective_permissions: EffectivePermissionSet,
    ) -> PolicyEvaluationResult: ...
```

`PolicyEvaluationRequest` engine'in tek request girdisidir ve resolved `ResourceSecurityScope` kabul etmez. Identity subject authoritative exact `identity.provider_subject` alanıdır; `authentication_context_subject` Adım 9 invariant'ıyla buna zaten eşittir ve alternatif kaynak olarak seçilemez. Subject değerleri case-sensitive karşılaştırılır; normalize/coerce edilmez. `SELF` için yalnız `target_subject`, `EXPLICIT_SUBJECT_MATCH` için yalnız `explicit_subject`, `INITIATOR` için yalnız resolver çıktısındaki resource initiator, `SAME_TENANT` için yalnız identity ile resolver çıktısındaki tenant key zorunludur; tabloda kullanılmayan request subject alanı null olmak zorundadır. `NONE` için iki request subject alanı da null'dır. Owner-only action subject predicate kullanmaz; `ownership_requirement=RESOURCE_OWNER_REQUIRED` tarafından önce ve tek kez kontrol edilir. Gerekli subject yoksa veya forbidden subject verilirse `RESOURCE_STATE_INVALID`; canonical fakat farklıysa `SUBJECT_PREDICATE_FAILED` olur. Raw subject hiçbir result/audit/metric'e girmez.

`ResourceSecurityReference` yalnız authoritative resolution için gerekli identifier'ları taşır; owner, initiator, resolved tenant, status, digest, relationship, ORM row veya başka caller-supplied security metadata taşıyamaz. `target_subject` ve `explicit_subject` yalnız `PolicyEvaluationRequest` alanlarıdır; reference içine kopyalanamaz. Reference invariant'ları:

- `scope_type` exact closed `PolicyScopeType` instance'ıdır; string/legacy alias coercion yoktur. Invalid internal enum state Step 10.2 `DATA_INTEGRITY_VIOLATION` üretir.
- `resource_id` scope'a göre typed canonical UUID/string'dir. Malformed ID veya compound ID Step 10.1 `RESOURCE_STATE_INVALID` üretir ve hiçbir store çağrısı yapılmaz.
- `request_tenant_key`, SYSTEM için `None`, diğer on scope için identity'nin canonical tenant key'iyle exact eş zorunludur. Bu alan authoritative resource tenant'ı değildir; yalnız tenant-qualified lookup parametresidir.
- `company_id` ve `period_id` yalnız COMPANY_PERIOD için gerçek UUID ve zorunludur; diğer on scope'ta ikisi de forbidden'dır. COMPANY_PERIOD `resource_id` içindeki UUID'lerle exact eşleşir.
- `expected_resource_version` yalnız opsiyonel optimistic assertion'dır; authoritative resource-version metadata'sı veya caller-supplied security fact değildir. Varsa exact `rsv1:<64-lowercase-hex>` biçimindedir. Resolver authoritative state'ten version üretme ve doğrulama işlemini her durumda yapar; assertion bu işlemi bypass edemez ve owner/tenant/version spoofing yolu oluşturamaz. Resolver çıktısıyla farklıysa Step 10.8 exact `RESOURCE_STATE_INVALID` olur.
- `correlation_id`, enclosing request ile exact eş; `referenced_at` UTC-aware ve `referenced_at <= evaluated_at` olmak zorundadır. DTO frozen'dır; safe `repr` yalnız scope type, redacted reference ve correlation taşır.

Identifier manifesti kapalıdır:

| Scope | `resource_id` | request tenant | company/period |
|---|---|---|---|
| `SYSTEM` | exact string `system` | forbidden | forbidden |
| `TENANT` | canonical external tenant key | required ve `resource_id` ile exact eş | forbidden |
| `COMPANY_PERIOD` | exact `cp1:<company-uuid>:<period-uuid>` | required | iki UUID required ve compound ID ile exact eş |
| `ANALYSIS_RUN` | canonical external run identifier string | required | forbidden |
| `ANALYSIS_RESULT`, `EXECUTION`, `COMPANY`, `FINANCIAL_PERIOD`, `DOCUMENT`, `BULK_UPLOAD_BATCH`, `TRIAL_BALANCE` | exact UUID | required | forbidden |

Production engine construction'ı `AuthorizationPolicyRepositoryPort`, `ResourceSecurityRepositoryPort`, `SyntheticSecurityScopeResolverPort`, `ResourceSecurityVersionCodec v1` ve `SubjectReferenceHashCodec v1` binding'lerini zorunlu alır. Step 10 resolver seçimini engine yapar: sekiz durable scope yalnız `resolve_durable_scope`, üç sentetik scope yalnız exact synthetic metot üzerinden çözülür. Resolver'ın immutable `ResourceSecurityScope` çıktısı tek authoritative scope'tur. Caller resolver çağırmaz; pre-resolved scope, scope injection, caller owner/tenant/version/relationship metadata'sı ve double-resolution production composition'da yasaktır. Test fake'i reference'a karşı resolver davranışını taklit edebilir fakat doğrudan scope bypass'ı production DI doğrulamasında reddedilir.

`ResolvedPolicyRole` alanları exact yukarıdaki gibidir; `assignment_version` mevcut authoritative `security_memberships.version` değeridir. Her permission evaluation çağrısı built-in/custom ayrımı yapmadan authoritative PostgreSQL membership-role-role-permission state'ini kısa `READ ONLY, REPEATABLE READ` snapshot'ta yeniden okur. Static registry yalnız permission metadata'sını ve built-in beklenen matrisi doğrular; custom-role permission kaynağı değildir. Adım 9 proof alanları DB state üzerinden aynı canonical digest algoritmasıyla tekrar doğrulanır. Role/permission, registry, tenant policy, assignment version, digest veya reference mismatch fail-closed'dur. Raw cause/row/SQL dışarı çıkmaz.

#### 15.9.1 Immutable `PolicyRepositoryError`

```python
class PolicyRepositoryErrorCode(str, Enum):
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    STORE_TIMEOUT = "STORE_TIMEOUT"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    REGISTRY_VERSION_MISMATCH = "REGISTRY_VERSION_MISMATCH"
    TENANT_POLICY_VERSION_MISMATCH = "TENANT_POLICY_VERSION_MISMATCH"
    PROOF_MISMATCH = "PROOF_MISMATCH"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

class PolicyRepositoryError(Exception):
    __slots__ = (
        "_code", "_correlation_id", "_safe_message", "_retryable",
        "_metric_name", "_audit_event", "_internal_cause", "_frozen",
    )

    def __init__(
        self, *, code: PolicyRepositoryErrorCode, correlation_id: str,
        internal_cause: BaseException | None = None,
    ) -> None:
        if not isinstance(code, PolicyRepositoryErrorCode):
            raise TypeError("invalid PolicyRepositoryErrorCode")
        if not isinstance(correlation_id, str) or correlation_id == "":
            raise ValueError("invalid correlation_id")
        if internal_cause is not None and not isinstance(internal_cause, BaseException):
            raise TypeError("invalid internal_cause")
        metadata = POLICY_REPOSITORY_ERROR_METADATA[code]
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_correlation_id", correlation_id)
        object.__setattr__(self, "_safe_message", metadata.safe_message)
        object.__setattr__(self, "_retryable", metadata.retryable)
        object.__setattr__(self, "_metric_name", metadata.metric_name)
        object.__setattr__(self, "_audit_event", metadata.audit_event)
        object.__setattr__(self, "_internal_cause", internal_cause)
        Exception.__init__(self, self._safe_message)
        object.__setattr__(self, "_frozen", True)

    @property
    def code(self) -> PolicyRepositoryErrorCode: ...
    @property
    def correlation_id(self) -> str: ...
    @property
    def safe_message(self) -> str: ...
    @property
    def retryable(self) -> bool: ...
    @property
    def metric_name(self) -> str: ...
    @property
    def audit_event(self) -> str: ...

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("immutable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("PolicyRepositoryError is final")

    def __str__(self) -> str:
        return self.safe_message

    def __repr__(self) -> str:
        return f"PolicyRepositoryError(code={self.code.value!r}, correlation_id='<redacted>')"
```

`PolicyRepositoryError` final/internal exception'dır; exact `__init_subclass__` mekanizması her subclass girişimini reddeder. Constructor keyword-only exact `PolicyRepositoryErrorCode`, safe canonical `correlation_id` ve optional `BaseException` internal cause kabul eder; string/unknown code, invalid correlation veya non-exception cause metadata lookup'tan önce kesin reddedilir. `safe_message`, `retryable`, `metric_name` ve `audit_event` aşağıdaki immutable metadata registry'sinden türetilir; override parametresi yoktur. `_internal_cause` property veya serialization yüzeyinde değildir. `_frozen=True` sonrasında mevcut field, `args` veya yeni attribute yazımı ve bütün delete girişimleri `AttributeError("immutable")` üretir. `Exception.args` exact `(safe_message,)`; `str` yalnız safe message, `repr` yalnız code ile literal redacted correlation marker taşır ve gerçek correlation değerini göstermez.

Adapter `raise PolicyRepositoryError(code=code, correlation_id=correlation_id, internal_cause=cause) from cause` kullanabilir; ancak boundary serializer traceback, `__cause__`, `__context__` veya `_internal_cause` zincirini hiçbir public/application/audit DTO'ya almaz. Raw SQLAlchemy/PostgreSQL message, SQL, DSN, bind parameter, subject, resource ID, token, claim veya PII `args/str/repr` içinde bulunamaz. HTTP status yoktur.

| Repository code | Retryable | Exact metric | Exact audit event | Safe message | Engine reason |
|---|---:|---|---|---|---|
| `STORE_UNAVAILABLE` | Evet | `security.policy.repository.unavailable` | `security.policy.repository.store_unavailable` | `Policy store is unavailable.` | `POLICY_STORE_UNAVAILABLE` |
| `STORE_TIMEOUT` | Evet | `security.policy.repository.timeout` | `security.policy.repository.store_timeout` | `Policy store timed out.` | `POLICY_STORE_TIMEOUT` |
| `UNKNOWN_ROLE` | Hayır | `security.policy.repository.unknown_role` | `security.policy.repository.unknown_role` | `Policy role is invalid.` | `UNKNOWN_ROLE` |
| `UNKNOWN_PERMISSION` | Hayır | `security.policy.repository.unknown_permission` | `security.policy.repository.unknown_permission` | `Policy permission is invalid.` | `UNKNOWN_PERMISSION` |
| `REGISTRY_VERSION_MISMATCH` | Hayır | `security.policy.repository.registry_version` | `security.policy.repository.registry_version_mismatch` | `Policy registry version is invalid.` | `REGISTRY_VERSION_MISMATCH` |
| `TENANT_POLICY_VERSION_MISMATCH` | Hayır | `security.policy.repository.tenant_version` | `security.policy.repository.tenant_policy_version_mismatch` | `Tenant policy version is invalid.` | `TENANT_POLICY_VERSION_MISMATCH` |
| `PROOF_MISMATCH` | Hayır | `security.policy.repository.proof_mismatch` | `security.policy.repository.proof_mismatch` | `Policy proof is invalid.` | `DATA_INTEGRITY_VIOLATION` |
| `DATA_INTEGRITY_VIOLATION` | Hayır | `security.policy.repository.integrity` | `security.policy.repository.data_integrity_violation` | `Policy state is invalid.` | `DATA_INTEGRITY_VIOLATION` |
| `RESOURCE_NOT_FOUND` | Hayır | `security.policy.repository.resource_not_found` | `security.policy.repository.resource_not_found` | `Resource is not accessible.` | `RESOURCE_NOT_FOUND` |

Mapping exact lookup'tır. Constructor string veya closed enum dışındaki unknown code'u metadata lookup'tan önce reddeder; unknown code taşıyan bir `PolicyRepositoryError` oluşturulamaz. Repository adapter'ında enum üretiminden önce saptanan imkânsız/unmapped internal state ayrı invariant breach olarak engine'e `DATA_INTEGRITY_VIOLATION` semantiğiyle aktarılır; bu yol unknown code'u kabul etmez veya coerce etmez. Repository authorization/HTTP kararı üretmez.

`EffectivePermissionSet.permission_codes` ve `role_codes` non-empty, canonical, sorted, unique tuple; kind closed enum; membership gerçek UUID; registry version supported; tenant/assignment version pozitif; digest lowercase SHA-256 ve `materialized_at` normalized UTC olmalıdır. `PolicyMaterializationRequest` içindeki roles/digest/reference ile output proof'u exact eşleşir; silent sort/deduplicate/coercion yoktur.

Production engine `resolve_effective_permissions` aggregate metodunu çağırır; bu metot role assignment, registry version, tenant policy version ve proof kontrollerinin tamamını **tek** snapshot'ta yapar. Diğer metotlar aynı adapter'ın açık contract/test yüzeyidir ve aggregate sonucu farklı transaction'lardan birleştirmek için kullanılamaz. Permission ve resource okumaları ayrı kısa snapshot'lardır; uzun request transaction'ı kurulmaz. Adım 11 pre-persistence revalidation, arada commit edilen revoke/policy değişikliğini yeniden değerlendirir.

SERVICE effective setindeki her permission `service_allowed=true`, HUMAN setindeki her permission `human_allowed=true` olmalıdır. Unknown role/permission grant değildir. Positive authorization cache, stale fallback ve adapter içi retry yoktur; committed role/permission değişikliği sonraki evaluation'da görülür. Policy engine identity resolution'ı tekrarlamaz; yalnız doğrulanmış identity, materialized permission seti, action ve resource scope üzerinde karar verir.

### 15.10 Resource ownership kaynakları

`ResourceSecurityRepositoryPort` sekiz durable domain kaynağı için tek repository portudur. PostgreSQL authoritative adapter her çağrıda request tenant ile scope-qualified kısa `READ ONLY, REPEATABLE READ` snapshot açar; statement/pool timeout config'i pozitif, production varsayılanı 2 saniye ve üst sınırı 3 saniyedir. Retry/stale fallback/partial scope ve secondary unscoped existence lookup yoktur. Pool exhaustion timeout sayılır. **Model A — repository hiding** bağlayıcıdır: unknown durable resource ve başka tenant'a ait durable resource aynı `RESOURCE_NOT_FOUND` sonucunu üretir; repository cross-tenant scope veya gerçek tenant metadata'sı döndürmez. Timeout/unavailable `INDETERMINATE`, mevcut fakat relational olarak bozuk row `DATA_INTEGRITY_VIOLATION` üretir; raw DB exception dışarı çıkmaz.

Terminoloji bağlayıcıdır: aşağıdaki tablo **8 authoritative domain resource** yolunu listeler: analysis run, analysis result, execution, company, financial period, document, bulk upload batch ve trial-balance resource. Bölüm 15.7.2'deki **11 policy evaluation scope type**, bu sekiz kaynağa ek olarak sentetik parent/evaluation scope'ları `SYSTEM`, `TENANT` ve `COMPANY_PERIOD`'u kapsar. Dokümanda “sekiz resource” yalnız authoritative domain kaynaklarını, “11 scope” yalnız policy evaluation projection'larını ifade eder.

| Resource | Authoritative tablo/yol | Tenant kaynağı | Owner/initiator | Version manifest girdisi | Not-found / hiding |
|---|---|---|---|---|---|
| Analysis run | `analysis_run_scope_claims` + `orchestration_runs` | claim `tenant_id` canonical key | immutable claim ownership binding → yalnız `owner_subject`; ayrı authoritative initiator yoksa `initiator_subject=None` | claim version/status + persisted run terminal digest | `RESOURCE_NOT_FOUND`; tenant mismatch hidden |
| Analysis result | `financial_analysis_results → companies` | company `tenant_id → security_tenants.tenant_key` | yok | id/company/period/status/canonical digest/completed_at | not-found veya mismatch hidden |
| Execution | `orchestration_engine_executions → orchestration_runs → analysis_run_scope_claims` | claim tenant key | bağlı run owner binding'i → yalnız `owner_subject`; initiator fallback yok | execution id/status/input fingerprint/owner digest + claim version | not-found veya mismatch hidden |
| Company | `companies → security_tenants` | company tenant UUID → key | yok | id/tenant_id/updated_at | not-found veya mismatch hidden |
| Financial period | `financial_periods → companies → security_tenants` | company tenant | yok | id/company_id/status/updated_at | not-found veya mismatch hidden |
| Document | `financial_documents → companies → security_tenants` | company tenant | yok | id/company/period/checksum/status/processed_at | not-found veya mismatch hidden |
| Bulk upload batch | `bulk_upload_batches → security_tenants` | batch tenant UUID → key | yok | id/tenant/status/counts/completed_at/confirmed_at | not-found veya mismatch hidden |
| Trial-balance resource | `financial_analysis_results` exact `analysis_type=trial_balance` → company | company tenant | yok | analysis-result manifest + analysis type/source mode/digest | wrong type `RESOURCE_STATE_INVALID`; not-found/mismatch hidden |

#### 15.10.1 Sentetik scope resolver'ı

`SyntheticSecurityScopeResolverPort` durable resource repository'sinden ayrıdır. Sentetik scope'u durable tablo satırı gibi göstermez; SYSTEM lookup açmaz, TENANT ve COMPANY_PERIOD için aşağıdaki authoritative relation'ları kısa `READ ONLY, REPEATABLE READ` snapshot'ta doğrular.

| Scope | Identifier ve required/forbidden alanlar | Authoritative source / transaction | Not-found ve tenant davranışı | Version ve ownership |
|---|---|---|---|---|
| `SYSTEM` | `resource_id="system"`; tenant/company/period/owner/initiator forbidden | PostgreSQL lookup yok; pure deterministic factory | Yalnız `PolicyScopeType.SYSTEM` action'ları; başka alan varsa `RESOURCE_STATE_INVALID` | `SYSTEM_OWNED`; exact sabit manifestten `rsv1` version |
| `TENANT` | `resource_id=tenant_key`; canonical external tenant key ve `tenant_key` required; company/period/owner/initiator forbidden | `security_tenants` ACTIVE row + exact `policy_version`; tek short snapshot | request `tenant_key != identity_tenant_key` ise DB lookup yapmadan `TENANT_MISMATCH`; eş tenant unknown/inactive ise `RESOURCE_NOT_FOUND`; timeout/unavailable store reason | `TENANT_OWNED`; tenant UUID, key ve policy version manifesti |
| `COMPANY_PERIOD` | `resource_id="cp1:<lowercase-company-uuid>:<lowercase-period-uuid>"`; iki UUID, tenant required; owner/initiator forbidden | `financial_periods JOIN companies JOIN security_tenants`; period.company_id, company tenant ve ACTIVE tenant tek short snapshot'ta exact | scope-qualified query row bulmazsa; başka company/tenant relation veya cross-tenant ise `RESOURCE_NOT_FOUND`; bulunan row'da FK/relation corruption `DATA_INTEGRITY_VIOLATION`; timeout/unavailable store reason | `TENANT_OWNED`; company/period ID ve iki `updated_at` manifesti |

SYSTEM resolver her adapter'da byte-identical scope üretir. TENANT ve COMPANY_PERIOD resolver input'ları string/UUID coercion yapmaz. `TENANT_MISMATCH` yalnız authoritative sentetik resolver çıktısındaki tenant ile identity tenant'ı farklı olduğunda kullanılır; pre-resolved scope girişi yoktur ve durable resource için daima Model A `RESOURCE_NOT_FOUND` uygulanır. Metric/audit yalnız safe reason/action ve HMAC reference taşır; raw target tenant/resource ID yoktur.

### 15.11 Internal authentication strength

```python
class PolicyAuthenticationStrength(str, Enum):
    ANONYMOUS = "ANONYMOUS"
    PASSWORD = "PASSWORD"
    MFA = "MFA"
    PHISHING_RESISTANT = "PHISHING_RESISTANT"
    SERVICE_CREDENTIAL = "SERVICE_CREDENTIAL"
```

HUMAN ordering exact `ANONYMOUS < PASSWORD < MFA < PHISHING_RESISTANT`'tır. Permission metadata compiler mapping'i exact `BASIC→PASSWORD`, `STRONG→MFA`, `PHISHING_RESISTANT→PHISHING_RESISTANT`'tır. `SERVICE_CREDENTIAL` ayrı eksendir, bu compiler mapping'inden üretilmez ve HUMAN sırasıyla karşılaştırılmaz. HUMAN action yalnız HUMAN strength, SERVICE action yalnız verified `SERVICE_CREDENTIAL` kabul eder; SERVICE principal MFA isteyen HUMAN-only permission alamaz. Unknown/string-coerced source veya internal strength fail-closed'dur. Permission metadata minimumu authoritative'dir.

Değişmez 5.0D `AuthenticationContext.authentication_strength` mapping'i principal kind ile birlikte yapılır: HUMAN `BASIC→PASSWORD`, `STRONG→MFA`, `PHISHING_RESISTANT→PHISHING_RESISTANT`; doğrulanmış SERVICE context'i yalnız `SERVICE_CREDENTIAL` olur. `ANONYMOUS` trusted context üretmez. Token claim'i bu internal değerin authoritative kaynağı değildir; trusted AuthenticationContext mapping sonucudur.

### 15.12 Subject predicate engine

| Predicate | Exact input | Karar |
|---|---|---|
| `NONE` | request `explicit_subject=None`, `target_subject=None` | her zaman true; subject alanı verilirse invalid request |
| `SELF` | `identity.provider_subject` + request `target_subject`; `explicit_subject=None` | target zorunlu; exact eşitse true; explicit verilirse invalid request |
| `INITIATOR` | `identity.provider_subject` + `resource_scope.initiator_subject`; iki request subject alanı null | initiator zorunlu; exact eşitse true |
| `SAME_TENANT` | `identity.tenant_key` + `resource_scope.tenant_key`; iki request subject alanı null | iki tenant zorunlu; exact eşitse true |
| `EXPLICIT_SUBJECT_MATCH` | `identity.provider_subject` + request `explicit_subject`; `target_subject=None` | explicit subject zorunlu; exact eşitse true |

Gerekli subject alanının yokluğu `RESOURCE_STATE_INVALID`, canonical fakat farklı değer `SUBJECT_PREDICATE_FAILED` üretir. Karşılaştırma normalize/coerce edilmeden case-sensitive exact yapılır. Raw subject result/audit/log/metric'e yazılmaz; gerekli korelasyon yalnız deployment secret'lı HMAC-SHA256 redacted reference ile taşınır. Predicate failure permission absence ve ownership failure'dan ayrı reason'dır; action hiding policy'si uygulanır.

### 15.13 Audit intent sınırı

Policy engine audit sink çağırmaz; her evaluation için Bölüm 15.8'deki exact `AuditIntent` DTO'sunu üretir. `required` false olsa bile deterministic event/severity/metric korelasyonu kaybolmaz; sink'e teslim zorunluluğu yoktur. `NONE` allow/deny için required=false; `DENY_ONLY` yalnız deny'da, `ALLOW_AND_DENY` ve `SECURITY_CRITICAL` allow/deny'da required=true; tüm INDETERMINATE sonuçlar required=true'dur. Adım 11 mevcut `SecurityAuditPort` üzerinden delivery sahibidir:

| Requirement | ALLOW `required` | DENY `required` | INDETERMINATE `required` |
|---|---:|---:|---:|
| `NONE` | false | false | true |
| `DENY_ONLY` | false | true | true |
| `ALLOW_AND_DENY` | true | true | true |
| `SECURITY_CRITICAL` | true | true | true |

- `SECURITY_CRITICAL` veya `ALLOW_AND_DENY` allow intent'i yazılamazsa final authorization fail-closed DENY ve `AUDIT_REQUIRED_BUT_UNAVAILABLE` olur.
- `DENY_ONLY` deny audit'i yazılamazsa karar DENY kalır ve ayrı audit-unavailable güvenlik metriği zorunludur.
- Audit başarısızlığı allow'u sessiz geçiremez.

Adım 10 yalnız intent'i test eder; audit sink outage, 5.0C `AuthorizationDecision` mapping'i ve required delivery Adım 11 testidir.

#### 15.13.1 `SubjectReferenceHashCodec v1`

`subject_reference_hash` adapter-independent, write-only pseudonymous audit reference'ıdır; authorization kararı, identity lookup veya sonradan verification için kullanılmaz. HMAC-SHA256 key'i versioned production secret manager'dan gelir; raw key config/log/audit'e girmez. Unknown/inactive key version yeni event üretiminde fail-closed `DATA_INTEGRITY_VIOLATION` intent-construction failure'dır. Eski audit kaydı kendi key version'ını taşır ve rotation sonrası yeniden hesaplanmaz.

Canonical message exact `b"srh1\n"` ile başlar. Ardından fixed sırada `name|tag|UTF8-byte-length|value\n` kayıtları gelir:

1. `key_version|s|...` — exact `k<positive-base10>`;
2. `domain|s|35|finos-security-subject-reference-v1`;
3. `issuer|s|...` — already-canonical trusted issuer;
4. `tenant_key|s|...` — canonical external tenant key;
5. `principal_kind|e|...` — exact `HUMAN` veya `SERVICE`;
6. `provider_subject|s|...` — Adım 9 canonical ASCII subject.

Null, empty, Unicode/noncanonical subject, normalization ve case-folding yasaktır. Output exact `srh1:<key_version>:<64-lowercase-hmac-hex>`; örnek `srh1:k1:...`. Audit intent yalnız bu output'u taşır; raw issuer/subject/key veya unredacted resource ID taşımaz. Aynı subject farklı issuer, tenant, principal kind veya key version ile farklı reference üretir.

Golden test key'leri production secret **değildir**: `k1=000102...1f` ve `k2=202122...3f` toplam 32'ser byte hexadecimal sequence'tır.

| Vector | Exact fields | Expected output |
|---|---|---|
| HUMAN | `k1`, `https://issuer.example`, `acme-prod`, `HUMAN`, `user-123` | `srh1:k1:b19854288ee4a03e964ef11d415fde4686984af36061d35ca3771409d85da075` |
| SERVICE | `k1`, `https://issuer.example`, `acme-prod`, `SERVICE`, `svc-001` | `srh1:k1:60ebe899eda7444cddd848bab133e634f9641221e87c372c4dc94d11aef73706` |
| different issuer | `k1`, `https://issuer-2.example`, `acme-prod`, `HUMAN`, `user-123` | `srh1:k1:89228d9dedf55708c92d12a4f4a4ea6458b0ea9ee7c1d6424b6bfbeef7dab0f8` |
| different tenant | `k1`, `https://issuer.example`, `beta-prod`, `HUMAN`, `user-123` | `srh1:k1:89d5323c398fc4240dc9919404dd1bf835d519b6435374a24e94094ccbadcdd1` |
| different key/version | `k2`, `https://issuer.example`, `acme-prod`, `HUMAN`, `user-123` | `srh1:k2:d32d5f23f8da4e1c0fd5ba4772afe0cd520740ae88b4fe26520fd110790892b7` |

HUMAN vector canonical bytes'i literal `srh1\nkey_version|s|2|k1\ndomain|s|35|finos-security-subject-reference-v1\nissuer|s|22|https://issuer.example\ntenant_key|s|9|acme-prod\nprincipal_kind|e|5|HUMAN\nprovider_subject|s|8|user-123\n`'dır. Diğer vektörler aynı frame'de tabloda belirtilen alanları değiştirir. Negatif testler missing issuer/tenant/subject, malformed key version, unknown key, Unicode subject, empty field ve noncanonical issuer/tenant'ı reddeder.

### 15.14 Permission/audit manifesti ve built-in 6 × 33 matrisi

Mevcut Bölüm 15.2 tablosunun her satırı `registry_version=1.0.0` taşır. Exact audit requirement ek manifesti şöyledir:

| Audit requirement | Exact permission codes |
|---|---|
| `DENY_ONLY` | `system.metadata.read`, `company.list`, `company.read`, `period.list`, `period.read`, `document.list`, `document.read`, `analysis_result.list`, `analysis_result.read`, `bulk_upload.read`, `analysis.read`, `analysis.payload.read`, `analysis.status.read`, `analysis.result.read`, `analysis.result.payload.read`, `analysis.history.read`, `analysis.execution.read`, `analysis.execution.payload.read` |
| `ALLOW_AND_DENY` | `company.create`, `period.create`, `trial_balance.validate`, `trial_balance.upload`, `bulk_upload.create`, `bulk_upload.update`, `bulk_upload.confirm`, `analysis.start`, `analysis.resume`, `analysis.resume_source`, `analysis.retry`, `analysis.cancel.own`, `analysis.cancel.any` |
| `SECURITY_CRITICAL` | `security.membership.manage`, `security.role.assign` |
| `NONE` | boş; v1 registry'de audit-intentsiz permission yoktur |

Altı built-in rol için aşağıdaki 198 hücre exhaustive'dir; implicit “all business permissions” expansion yoktur:

| Permission | TENANT_ADMIN | FINANCE_ADMIN | FINANCE_ANALYST | REPORT_VIEWER | AUDITOR | SERVICE_OPERATOR |
|---|---|---|---|---|---|---|
| system.metadata.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| company.create | ALLOW | ALLOW | DENY | DENY | DENY | DENY |
| company.list | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| company.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| period.create | ALLOW | ALLOW | DENY | DENY | DENY | DENY |
| period.list | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| period.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| document.list | ALLOW | ALLOW | ALLOW | DENY | ALLOW | ALLOW |
| document.read | ALLOW | ALLOW | ALLOW | DENY | ALLOW | ALLOW |
| analysis_result.list | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis_result.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| trial_balance.validate | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| trial_balance.upload | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| bulk_upload.create | ALLOW | ALLOW | ALLOW | DENY | DENY | DENY |
| bulk_upload.read | ALLOW | ALLOW | ALLOW | DENY | ALLOW | DENY |
| bulk_upload.update | ALLOW | ALLOW | ALLOW | DENY | DENY | DENY |
| bulk_upload.confirm | ALLOW | ALLOW | DENY | DENY | DENY | DENY |
| analysis.start | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| analysis.resume | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| analysis.resume_source | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| analysis.retry | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| analysis.cancel.own | ALLOW | ALLOW | ALLOW | DENY | DENY | ALLOW |
| analysis.cancel.any | ALLOW | ALLOW | DENY | DENY | DENY | DENY |
| analysis.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.payload.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.status.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.result.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.result.payload.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.history.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.execution.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| analysis.execution.payload.read | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| security.membership.manage | ALLOW | DENY | DENY | DENY | DENY | DENY |
| security.role.assign | ALLOW | DENY | DENY | DENY | DENY | DENY |

Unknown permission/role implicit DENY'dır. Custom role built-in matrisi değiştirmez. Permission code silinemez veya farklı semantikle yeniden kullanılamaz; yeni permission yalnız registry version artışıyla additive eklenir, deprecated kod ilgili major version boyunca rezerv kalır. Permission manifesti sorted record JSON (`sort_keys=True`, separators `(',', ':')`, UTF-8) SHA-256 ile; role matrix sorted role + sorted 33 `(permission,ALLOW|DENY)` hücresiyle digest edilir. `PERMISSION_REGISTRY_MANIFEST_DIGEST` ve `BUILT_IN_ROLE_MATRIX_DIGEST` literal golden constant'ları implementasyonda kaydedilir; startup/test computed digest farklıysa fail-closed invariant breach olur. Böylece kod ve bu exact manifest deterministik olarak karşılaştırılabilir.

### 15.15 Exact policy evaluation precedence

Tenant/resource scope permission possession'dan önce doğrulanır; aksi sıra caller'a cross-tenant kaynağın varlığına ilişkin permission oracle sağlayabilir. Fail-fast sıra değişmezdir:

| Step | Validation | Success next step | Failure reason | Outcome | Retryable | Existence hiding | Audit intent | Metric |
|---:|---|---:|---|---|---:|---|---|---|
| 1 | `PolicyEvaluationRequest` container (reference-specific alanlar hariç), identity, permission set ve diğer typed DTO-local invariant'lar | 2 | `DATA_INTEGRITY_VIOLATION` | INDETERMINATE | Hayır | Evet | required/CRITICAL | `security.policy.integrity_failure` |
| 2 | Exact `SecurityAction` lookup; unknown source action/fallback yok | 3 | `UNKNOWN_ACTION` | DENY | Hayır | Evet | action-deny | `security.policy.unknown_action` |
| 3 | Required permission lookup + request/action/permission registry version exact | 4 | `UNKNOWN_PERMISSION` veya `REGISTRY_VERSION_MISMATCH` | DENY | Hayır | action policy | action-deny | ilgili reason metric'i |
| 4 | Identity kind action allowlist'te | 5 | `PRINCIPAL_KIND_NOT_ALLOWED` | DENY | Hayır | action policy | action-deny | `security.policy.principal_kind` |
| 5 | Identity, request ve authoritative tenant-policy version exact | 6 | `TENANT_POLICY_VERSION_MISMATCH` | DENY | Hayır | action policy | action-deny | `security.policy.tenant_version` |
| 6 | Effective permission aggregate tek authoritative snapshot'ta çağrılır; value veya tek typed `PolicyRepositoryError` capture edilir | 7 | bu basamak reason seçmez; normalization yalnız Step 7 alt-sırasındadır | — | — | — | sink yok | invocation timing metric |
| 7 | Bölüm 15.15.1 exact permission-materialization alt-precedence | 8 | alt-tablodaki tek reason | alt-tabloda exact | alt-tabloda exact | reason registry | exact reason intent | exact reason metric |
| 8 | Effective permission'lar principal-kind flag'leriyle uyumlu | 9 | `PRINCIPAL_KIND_NOT_ALLOWED` | DENY | Hayır | action policy | action-deny | `security.policy.principal_kind` |
| 9 | Permission-strength compiler ve HUMAN/SERVICE axis kontrolü | 10 | `INSUFFICIENT_AUTHENTICATION_STRENGTH` | DENY | Hayır | action policy | action-deny | `security.policy.strength` |
| 10 | Bölüm 15.15.2 exact durable/synthetic resource-resolution alt-precedence | 11 | alt-tablodaki tek reason | alt-tabloda exact | alt-tabloda exact | reason registry | exact reason intent | exact reason metric |
| 11 | Step 10 authoritative resolver çıktısındaki sentetik scope tenant ile identity tenant exact; durable scope Model A'da zaten qualified | 12 | `TENANT_MISMATCH` | DENY | Hayır | Evet | `security.authorization.deny.tenant_mismatch` / HIGH | `security.policy.tenant_mismatch` |
| 12 | `SecurityAction.ownership_requirement` exact kontrolü; classification tek başına deny değil | 13 | owner-required missing metadata → `RESOURCE_STATE_INVALID`; owner farkı → `RESOURCE_OWNERSHIP_MISMATCH` | DENY | Hayır | exact action policy | exact reason event / HIGH | `security.policy.resource_invalid` veya `security.policy.ownership` |
| 13 | Predicate-required request/resource subject girdileri mevcut, forbidden girdiler yok | 14 | `RESOURCE_STATE_INVALID` | DENY | Hayır | Evet | action-deny/CRITICAL | `security.policy.resource_invalid` |
| 14 | Action-level subject predicate exact/case-sensitive | 15 | `SUBJECT_PREDICATE_FAILED` | DENY | Hayır | action policy | action-deny/MEDIUM | `security.policy.subject` |
| 15 | Exact required permission effective set içinde | 16 | `PERMISSION_NOT_GRANTED` | DENY | Hayır | action policy | action-deny/MEDIUM | `security.policy.permission_denied` |
| 16 | Reason + action policy'den deterministic existence hiding | 17 | constructor/invariant failure → `DATA_INTEGRITY_VIOLATION` | INDETERMINATE | Hayır | Evet | required/CRITICAL | `security.policy.integrity_failure` |
| 17 | Exact `AuditIntent` event/required/severity/hash üretimi; sink çağrısı yok | 18 | constructor/invariant failure → `DATA_INTEGRITY_VIOLATION` | INDETERMINATE | Hayır | Evet | required/CRITICAL | `security.policy.integrity_failure` |
| 18 | Immutable `PolicyEvaluationResult` construction | terminal ALLOW (`ALLOWED`) veya seçilmiş terminal deny/indeterminate | constructor failure → result değil `PolicyEvaluationConstructionError` | internal fatal; Adım 11 fail-closed | Hayır | public result yok | minimal best-effort integrity intent | `security.policy.result_construction_failure` |

Reason reachability invariant'ı: `ALLOWED` Step 18 success; `UNKNOWN_ACTION` 2; `UNKNOWN_PERMISSION` 3/7; `UNKNOWN_ROLE` 7; `REGISTRY_VERSION_MISMATCH` 3/7; `TENANT_POLICY_VERSION_MISMATCH` 5/7; `PRINCIPAL_KIND_NOT_ALLOWED` 4/7/8; `INSUFFICIENT_AUTHENTICATION_STRENGTH` 9; `RESOURCE_NOT_FOUND` 10; `RESOURCE_STATE_INVALID` 10/12/13; `TENANT_MISMATCH` 11; `RESOURCE_OWNERSHIP_MISMATCH` 12; `SUBJECT_PREDICATE_FAILED` 14; `PERMISSION_NOT_GRANTED` 15; iki store reason 7/10; `DATA_INTEGRITY_VIOLATION` 1/7/10/16/17'den üretilebilir. Step 18 construction failure taxonomy'ye yeni reason eklemez. Dead reason yoktur.

#### 15.15.1 Step 7 permission-materialization alt-precedence

Repository tek snapshot içinde aşağıdaki sırayla kontrol eder; ilk failure terminaldir. Caller/adapter bu sırayı değiştiremez.

| Substep | Validation/failure | Exact reason / outcome | Retryable | Exact audit event / metric | Success next |
|---:|---|---|---:|---|---:|
| 7.1 | statement/pool deadline aşıldı | `POLICY_STORE_TIMEOUT` / INDETERMINATE | Evet | `security.authorization.indeterminate.policy_store_timeout` / `security.policy.store_timeout` | 7.2 |
| 7.2 | store/network/session unavailable | `POLICY_STORE_UNAVAILABLE` / INDETERMINATE | Evet | `security.authorization.indeterminate.policy_store_unavailable` / `security.policy.store_unavailable` | 7.3 |
| 7.3 | referenced role row yok | `UNKNOWN_ROLE` / DENY | Hayır | `security.authorization.deny.unknown_role` / `security.policy.unknown_role` | 7.4 |
| 7.4 | referenced permission registry/row yok | `UNKNOWN_PERMISSION` / DENY | Hayır | `security.authorization.deny.unknown_permission` / `security.policy.unknown_permission` | 7.5 |
| 7.5 | permission registry version mismatch | `REGISTRY_VERSION_MISMATCH` / DENY | Hayır | `security.authorization.deny.registry_version_mismatch` / `security.policy.registry_version` | 7.6 |
| 7.6 | tenant policy version mismatch | `TENANT_POLICY_VERSION_MISMATCH` / DENY | Hayır | `security.authorization.deny.tenant_policy_version_mismatch` / `security.policy.tenant_version` | 7.7 |
| 7.7 | role-set proof/reference/digest/assignment-version mismatch | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 7.8 |
| 7.8 | role veya assignment inactive/revoked/validity dışı | `UNKNOWN_ROLE` / DENY | Hayır | `security.authorization.deny.unknown_role` / `security.policy.unknown_role` | 7.9 |
| 7.9 | HUMAN/SERVICE permission safety flag ihlali | `PRINCIPAL_KIND_NOT_ALLOWED` / DENY | Hayır | `security.authorization.deny.principal_kind_not_allowed` / `security.policy.principal_kind` | 7.10 |
| 7.10 | diğer FK/duplicate/relational corruption | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 7.11 |
| 7.11 | `EffectivePermissionSet` constructor invariant failure | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | Step 8 |

#### 15.15.1.1 Step 7 literal multi-error golden matrisi

Aşağıdaki **11** case ayrı test adıdır; her satır mock/spy call-count ile terminal substep'ten sonraki kontrolün hiç çağrılmadığını doğrular. Hiding exact reason metadata registry'sinden türetilir ve tabloda `H` ile gösterilir: `A` = action policy, `Y` = always hide.

| ID | Repository state | Injected concurrent failure | Expected terminal | Outcome / retry | Audit event | Metric | No later work |
|---:|---|---|---|---|---|---|---|
| S7-01 | referenced role unknown | statement/pool timeout | `POLICY_STORE_TIMEOUT` at 7.1 | INDETERMINATE / yes / H=Y | `security.authorization.indeterminate.policy_store_timeout` | `security.policy.store_timeout` | 7.2–7.11 not called |
| S7-02 | referenced role unknown | store unavailable | `POLICY_STORE_UNAVAILABLE` at 7.2 | INDETERMINATE / yes / H=Y | `security.authorization.indeterminate.policy_store_unavailable` | `security.policy.store_unavailable` | 7.3–7.11 not called |
| S7-03 | role and permission rows absent | none | `UNKNOWN_ROLE` at 7.3 | DENY / no / H=A | `security.authorization.deny.unknown_role` | `security.policy.unknown_role` | 7.4–7.11 not called |
| S7-04 | registry version stale and proof invalid | none | `REGISTRY_VERSION_MISMATCH` at 7.5 | DENY / no / H=A | `security.authorization.deny.registry_version_mismatch` | `security.policy.registry_version` | 7.6–7.11 not called |
| S7-05 | tenant policy version stale and proof invalid | none | `TENANT_POLICY_VERSION_MISMATCH` at 7.6 | DENY / no / H=A | `security.authorization.deny.tenant_policy_version_mismatch` | `security.policy.tenant_version` | 7.7–7.11 not called |
| S7-06 | proof invalid and assignment inactive | none | `DATA_INTEGRITY_VIOLATION` at 7.7 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | 7.8–7.11 not called |
| S7-07 | proof invalid and FK/duplicate relation corrupt | none | `DATA_INTEGRITY_VIOLATION` at 7.7 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | 7.8–7.11 not called |
| S7-08 | assignment inactive and permission kind unsafe | none | `UNKNOWN_ROLE` at 7.8 | DENY / no / H=A | `security.authorization.deny.unknown_role` | `security.policy.unknown_role` | 7.9–7.11 not called |
| S7-09 | registry version stale; eventual permission-set constructor would fail | none | `REGISTRY_VERSION_MISMATCH` at 7.5 | DENY / no / H=A | `security.authorization.deny.registry_version_mismatch` | `security.policy.registry_version` | 7.6–7.11 including constructor not called |
| S7-10 | all prior state valid | `EffectivePermissionSet` constructor invariant failure | `DATA_INTEGRITY_VIOLATION` at 7.11 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | Step 8 not called |
| S7-11 | permission unknown and eventual kind-safety invalid | none | `UNKNOWN_PERMISSION` at 7.4 | DENY / no / H=Y | `security.authorization.deny.unknown_permission` | `security.policy.unknown_permission` | 7.5–7.11 not called |

Bu kararlar adapter-independent'dır. S7-10 normal `PolicyEvaluationResult` terminal-construction failure değildir; bu nedenle `PolicyEvaluationConstructionError` değil mevcut 17-code taxonomy içindeki `DATA_INTEGRITY_VIOLATION` sonucunu üretir. Aynı multi-error state farklı PostgreSQL adapter/fake uygulamalarında aynı terminal reason, outcome, retryable, hiding, audit ve metric metadata'sını üretmek zorundadır.

#### 15.15.2 Step 10 resource-resolution alt-precedence

| Substep | Validation/failure | Exact reason / outcome | Retryable | Exact audit event / metric | Success next |
|---:|---|---|---:|---|---:|
| 10.1 | `ResourceSecurityReference` identifier/compound-ID, tenant-key, field-presence, correlation/time ve expected-version format invariant'ları | `RESOURCE_STATE_INVALID` / DENY | Hayır | `security.authorization.deny.resource_state_invalid` / `security.policy.resource_invalid` | 10.2 |
| 10.2 | exact closed `PolicyScopeType`; forged/string/legacy enum state | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 10.3 |
| 10.3 | 8 durable / 3 synthetic resolver exact selection; valid enum için tek resolver yok veya iki resolver yolu var | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 10.4 |
| 10.4 | selected resolver statement/pool timeout | `POLICY_STORE_TIMEOUT` / INDETERMINATE | Evet | `security.authorization.indeterminate.policy_store_timeout` / `security.policy.store_timeout` | 10.5 |
| 10.5 | selected resolver/store unavailable | `POLICY_STORE_UNAVAILABLE` / INDETERMINATE | Evet | `security.authorization.indeterminate.policy_store_unavailable` / `security.policy.store_unavailable` | 10.6 |
| 10.6 | tenant-qualified row yok; durable cross-tenant da aynı ve ikinci lookup yok | `RESOURCE_NOT_FOUND` / DENY + hide | Hayır | `security.authorization.deny.resource_not_found` / `security.policy.resource_not_found` | 10.7 |
| 10.7 | görünür mevcut row'da FK/company-period/tenant/relation corruption | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 10.8 |
| 10.8 | status/type/required security state invalid veya valid-format expected version authoritative version'dan farklı | `RESOURCE_STATE_INVALID` / DENY | Hayır | `security.authorization.deny.resource_state_invalid` / `security.policy.resource_invalid` | 10.9 |
| 10.9 | `ResourceSecurityVersionCodec v1` authoritative manifest/type/digest construction failure | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 10.10 |
| 10.10 | `ResourceSecurityScope` DTO construction failure | `DATA_INTEGRITY_VIOLATION` / INDETERMINATE | Hayır | `security.authorization.indeterminate.data_integrity_violation` / `security.policy.integrity_failure` | 10.11 |
| 10.11 | immutable authoritative scope başarıyla döndü | — | — | — | Step 11 |

#### 15.15.2.1 Step 10 literal multi-error golden matrisi

Aşağıdaki **17** case ayrı test adıdır. “Missing permission” valid registered permission'ın effective set'te olmamasıdır; unknown registry permission değildir. Her terminal satır spy/call-count ile sonraki resolver/check/codec/DTO/predicate/permission basamaklarının çalışmadığını doğrular.

| ID | Reference / repository state | Injected concurrent failure | Expected terminal | Outcome / retry / hiding | Audit event | Metric | No later work |
|---:|---|---|---|---|---|---|---|
| S10-01 | malformed typed/canonical identifier | store unavailable | `RESOURCE_STATE_INVALID` at 10.1 | DENY / no / H=Y | `security.authorization.deny.resource_state_invalid` | `security.policy.resource_invalid` | resolver selection/store not called |
| S10-02 | forged string/legacy scope enum | resolver timeout | `DATA_INTEGRITY_VIOLATION` at 10.2 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | resolver selection/store not called |
| S10-03 | same-tenant row absent | resolver timeout | `POLICY_STORE_TIMEOUT` at 10.4 | INDETERMINATE / yes / H=Y | `security.authorization.indeterminate.policy_store_timeout` | `security.policy.store_timeout` | not-found and later checks not called |
| S10-04 | visible row relationally corrupt | store unavailable | `POLICY_STORE_UNAVAILABLE` at 10.5 | INDETERMINATE / yes / H=Y | `security.authorization.indeterminate.policy_store_unavailable` | `security.policy.store_unavailable` | corruption and later checks not called |
| S10-05 | unknown durable resource; valid permission absent from effective set | none | `RESOURCE_NOT_FOUND` at 10.6 | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | Step 15 possession not called |
| S10-06 | existing cross-tenant durable resource; valid permission absent | none | `RESOURCE_NOT_FOUND` at 10.6 | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | no unscoped probe; Step 15 not called |
| S10-07 | cross-tenant durable row contains stale internal policy/resource version invisible to qualified query | none | `RESOURCE_NOT_FOUND` at 10.6 | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | hidden row/version never materialized |
| S10-08 | cross-tenant durable row is also corrupt | none | `RESOURCE_NOT_FOUND` at 10.6 | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | no unscoped corruption probe |
| S10-09 | same-tenant row exists and is relationally corrupt; contradictory fake not-found marker injected | fake marker | `DATA_INTEGRITY_VIOLATION` at 10.7 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | state/codec/DTO not called; row-presence discriminant authoritative |
| S10-10 | visible COMPANY_PERIOD row relation corrupt and synthetic tenant comparison would mismatch | none | `DATA_INTEGRITY_VIOLATION` at 10.7 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | Step 11 tenant check not called |
| S10-11 | resource state invalid | codec would fail | `RESOURCE_STATE_INVALID` at 10.8 | DENY / no / H=Y | `security.authorization.deny.resource_state_invalid` | `security.policy.resource_invalid` | codec/DTO not called |
| S10-12 | authoritative codec and eventual DTO would fail | none | `DATA_INTEGRITY_VIOLATION` at 10.9 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | DTO constructor not called |
| S10-13 | authoritative version manifest malformed; eventual DTO would fail | none | `DATA_INTEGRITY_VIOLATION` at 10.9 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | DTO constructor not called |
| S10-14 | valid enum has missing/ambiguous resolver registration | store unavailable | `DATA_INTEGRITY_VIOLATION` at 10.3 | INDETERMINATE / no / H=Y | `security.authorization.indeterminate.data_integrity_violation` | `security.policy.integrity_failure` | store not called |
| S10-15 | synthetic resolver returns authoritative tenant different from identity; valid permission absent | none | `TENANT_MISMATCH` at top Step 11 | DENY / no / H=Y | `security.authorization.deny.tenant_mismatch` | `security.policy.tenant_mismatch` | Step 12–15 not called |
| S10-16 | paired unknown and existing cross-tenant durable references | none | both `RESOURCE_NOT_FOUND` at 10.6 with identical DENY/no/hide/audit/metric | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | no unscoped lookup in either path |
| S10-17 | caller supplies canonical, self-consistent COMPANY_PERIOD IDs for existing same-tenant company and period, but authoritative healthy `period.company_id` points to another same-tenant company | none | `RESOURCE_NOT_FOUND` at 10.6 | DENY / no / H=Y | `security.authorization.deny.resource_not_found` | `security.policy.resource_not_found` | selected synthetic resolver and tenant-qualified pair lookup each called once; secondary/unscoped lookup, 10.7–10.11 and Steps 11–15 not called |

Model A row-presence discriminant'ı exact'tir: tenant-qualified query row döndürmezse 10.6 ve corruption araştırılmaz; aynı-tenant görünür row dönerse “not-found flag” diye ikinci bir adapter sinyali kabul edilmez ve relation corruption 10.7'de değerlendirilir. Aynı multi-error reference/state her adapter'da aynı terminal metadata'yı üretir. Property testleri öncelikli hata bulunduğunda sonraki adımların call-count'unu sıfır doğrular.

COMPANY_PERIOD ayrımı literal ve değişmezdir: **A)** S10-17'de caller'ın verdiği iki canonical UUID kendi içinde biçimsel olarak geçerli, iki row aynı tenant'ta görünür ve persisted ilişkiler sağlıklı olsa da period requested company'ye ait değilse tenant-qualified compound lookup row döndürmez ve sonuç `RESOURCE_NOT_FOUND` olur; **B)** S10-10'da görünür row'un persisted `period.company_id`/FK zinciri kendi içinde bozuksa `DATA_INTEGRITY_VIOLATION` olur; **C)** company veya period cross-tenant ise Model A hiding ile `RESOURCE_NOT_FOUND`; **D)** company veya period gerçekten yoksa `RESOURCE_NOT_FOUND`; **E)** yalnız trusted same-tenant synthetic resolver'ın authoritative output tenant'ı identity tenant'ından farklı olan internal durumda top-level Step 11 `TENANT_MISMATCH` üretir. S10-17 fixture'ı company, period, tenant ve healthy FK state'ini; request exact `cp1` ID'sini ve UUID alanlarını; expected reason/outcome/hiding/retryable/audit/metric'i; resolver ve lookup call-count'larını; secondary/unscoped lookup ile permission-possession ve sonraki kontrollerin çalışmadığını birebir doğrular.

Adım 10 pure/internal evaluation, registry ve authoritative permission/resource resolution portlarıyla sınırlıdır. Pre-persistence revoke/re-evaluation, audit delivery ve mevcut 5.0C `AuthorizationDecision` mapping'i yalnız Adım 11'dedir.

### 15.16 Adım 11 — 5.0C `AuthorizationPort` adapter sözleşmesi

Adım 11'in production sınıfı `LocalAuthorizationPolicyClient`'tır. Bu sınıf değişmemiş 5.0C `AuthorizationPort`'u uygular; HTTP, FastAPI, Pydantic, raw bearer token, raw claim, SQLAlchemy entity veya persistence write işlemi içermez. Adım 9 identity repository'sini, Adım 10 permission/resource repository'lerini ve policy engine'i koordine eder. Adım 11 yeni public DTO veya `AuthorizationDecision` alanı eklemez.

#### 15.16.1 Trusted internal authorization context

Frozen `AuthorizationPort` imzaları identity kanıtını taşımadığından identity kaynağı `ApplicationAuditContextDTO` değildir. Adım 11 yalnız aşağıdaki framework-bağımsız internal portu tüketir:

```python
class AuthorizationCheckpoint(str, Enum):
    START = "START"
    RESUME = "RESUME"
    RESUME_SOURCE = "RESUME_SOURCE"
    READ = "READ"
    CANCEL = "CANCEL"
    RETRY = "RETRY"
    PRE_PERSIST_START = "PRE_PERSIST_START"
    PRE_PERSIST_RESUME = "PRE_PERSIST_RESUME"
    PRE_PERSIST_RETRY = "PRE_PERSIST_RETRY"
    PRE_PERSIST_RESUME_SOURCE = "PRE_PERSIST_RESUME_SOURCE"

class TrustedAuthorizationContextErrorCode(str, Enum):
    AUTH_CONTEXT_MISSING = "AUTH_CONTEXT_MISSING"
    AUTH_CONTEXT_INVALID = "AUTH_CONTEXT_INVALID"
    AUTH_CONTEXT_STALE = "AUTH_CONTEXT_STALE"
    AUTH_CONTEXT_EXPIRED = "AUTH_CONTEXT_EXPIRED"
    AUTH_CONTEXT_SUBJECT_MISMATCH = "AUTH_CONTEXT_SUBJECT_MISMATCH"
    AUTH_CONTEXT_TENANT_MISMATCH = "AUTH_CONTEXT_TENANT_MISMATCH"
    AUTH_CONTEXT_PROVIDER_UNAVAILABLE = "AUTH_CONTEXT_PROVIDER_UNAVAILABLE"
    AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION = "AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION"

class AuthorizationAuditDeliveryErrorCode(str, Enum):
    AUDIT_STORE_UNAVAILABLE = "AUDIT_STORE_UNAVAILABLE"
    AUDIT_STORE_TIMEOUT = "AUDIT_STORE_TIMEOUT"
    AUDIT_EVENT_INVALID = "AUDIT_EVENT_INVALID"
    AUDIT_EVENT_UNSUPPORTED = "AUDIT_EVENT_UNSUPPORTED"
    AUDIT_DELIVERY_CONFLICT = "AUDIT_DELIVERY_CONFLICT"
    AUDIT_DATA_INTEGRITY_VIOLATION = "AUDIT_DATA_INTEGRITY_VIOLATION"

@dataclass(frozen=True, repr=False)
class TrustedAuthorizationContext:
    issuer: str
    subject: str
    tenant_key: str
    token_issued_at: datetime
    expires_at: datetime | None
    expected_principal_kind: IdentityKind
    service_client_id: str | None
    authentication_strength: PolicyAuthenticationStrength
    correlation_id: str
    request_id: str | None
    authorization_context_reference: str
    checkpoint: AuthorizationCheckpoint
    resource_reference: ResourceSecurityReference
    resolved_at: datetime

class TrustedAuthorizationContextProviderPort(Protocol):
    def resolve_context(
        self, *, checkpoint: AuthorizationCheckpoint,
        application_scope: ApplicationScopeDTO,
        audit_context: ApplicationAuditContextDTO,
    ) -> TrustedAuthorizationContext: ...

class AuthorizationRevalidationPort(Protocol):
    def revalidate_start(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_resume(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_retry(self, scope: ApplicationScopeDTO, actor: ApplicationAuditContextDTO) -> AuthorizationDecision: ...
    def revalidate_resume_source(
        self, source_run_id: str, target_scope: ApplicationScopeDTO,
        actor: ApplicationAuditContextDTO,
    ) -> AuthorizationDecision: ...

@dataclass(frozen=True, repr=False)
class TrustedAuthorizationContextError(Exception):
    code: TrustedAuthorizationContextErrorCode
    correlation_reference: str | None

@dataclass(frozen=True, repr=False)
class AuthorizationAuditDeliveryError(Exception):
    code: AuthorizationAuditDeliveryErrorCode
```

İki internal error da exact closed enum dışında kurulamaz; `retryable`, metric ve safe message caller argümanı değil aşağıdaki tablolardan derived property'dir. `args` yalnız safe message içerir; raw cause, token, claim, subject, tenant, resource ID, SQL/DSN veya receipt `str/repr/args` yüzeyine girmez; subclass ve mutation yasaktır. Context provider expected operational failure'ı yalnız `TrustedAuthorizationContextError` ile bildirir. `correlation_reference`, varsa canonical `cr1`, yoksa `None`'dır; raw correlation değildir. Unknown exception Adım 11'de `AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION`, process-start missing provider ise readiness failure olur.

Mevcut public `SecurityAuditPort` imzası değişmez. Production `DurableSecurityAuditAdapter` raw sink/client hatasını boundary'de yukarıdaki `AuthorizationAuditDeliveryError`'a normalize eder: deadline/timeout → `AUDIT_STORE_TIMEOUT`; connection/pool/provider unavailable → `AUDIT_STORE_UNAVAILABLE`; same idempotency key + different digest → `AUDIT_DELIVERY_CONFLICT`; malformed/mismatched receipt veya durable-record proof → `AUDIT_DATA_INTEGRITY_VIOLATION`. `AUDIT_EVENT_INVALID/UNSUPPORTED` sink çağrısından önce local projection validation'ında üretilir. `LocalAuthorizationPolicyClient` raw exception sınıfı/message'ı inceleyerek taxonomy seçmez; typed olmayan sink exception'ı conservative `AUDIT_DATA_INTEGRITY_VIOLATION` yapar. Böylece 5.0C port değişmeden exact normalization sahibi production adapter sınırı bellidir.

`resource_reference`, frozen public imzada bulunmayan fakat action'ın doğru authoritative kaynağa yönelmesi için gereken trusted request-bound integration fact'idir. Caller veya `ApplicationAuditContextDTO` bu alanı assemble edemez. Adım 12 provider'ı endpoint/request bağlamından bunu üretir: START/RESUME/RETRY ve history gibi parent-scope kontrollerinde `COMPANY_PERIOD`; source kontrolünde source `ANALYSIS_RUN`; cancel ve tek-run read kontrollerinde hedef `ANALYSIS_RUN`. Adım 11 yalnız reference'ı Adım 10 engine'e verir; pre-resolved scope kabul etmez. `ApplicationAuditContextDTO` yalnız correlation/audit tutarlılık assertion'ıdır ve identity/resource authority değildir.

Context raw HTTP header, token, claim mapping'i, email/display name, ORM row veya mutable collection taşımaz. `issuer`, `subject`, `tenant_key`, kind/client ve token zamanı yalnız trusted request-bound composition'dan gelir. Provider aynı request/checkpoint için byte-equivalent immutable context döndürür; process-global/context-cache/stale fallback yasaktır. Test provider'ı `is_fake=True` taşır ve production composition validation bunu reddeder. Gerçek provider implementasyonu Adım 12'dir; Adım 11 yalnız bu portu tüketir.

Context validation sırası kapalıdır:

1. provider çağrısı ve exact DTO type;
2. canonical issuer/subject/tenant/correlation/request ID formatı;
3. checkpoint ve `resource_reference` resolver-family uyumu;
4. context tenant == application scope tenant; frozen `ApplicationAuditContextDTO` correlation alanı taşımadığından correlation authority yalnız trusted context provider'dır ve audit DTO'dan türetilmez;
5. `audit_context.actor_id` mevcutsa raw subject değil, `SubjectReferenceHashCodec v1` ile context subject'ten üretilmiş exact `srh1` değeridir; constant-time consistency assertion yapılır ve actor alanı authority olmaz;
6. timezone-aware `token_issued_at`, `resolved_at`, optional `expires_at`;
7. future `token_issued_at > resolved_at + 60 saniye` → INVALID; ardından `expires_at is not None and expires_at <= resolved_at` → EXPIRED; ardından `resolved_at - token_issued_at > 15 dakika` → STALE;
8. HUMAN için `service_client_id=None`; SERVICE için canonical non-null client ID ve `SERVICE_CREDENTIAL` strength;
9. Adım 9 repository resolution;
10. returned identity issuer/subject/tenant/kind ve service binding exact;
11. `authorization_context_reference == authz:v1:<H|S>:<membership_uuid>:<membership_version>:<tenant_policy_version>`.

İlk başarısızlık terminaldir. Missing/stale/expired/inconsistent context, repository çağrısı veya policy evaluation olmadan fail-closed sonuç üretir. `resolved_at`, **checkpoint-resolution instant**'ıdır: aynı request içindeki aynı checkpoint/invocation yeniden okunduğunda değişmez; `PRE_PERSIST_*` ayrı checkpoint olduğu için trusted clock'tan yeni bir `resolved_at` alır. Böylece uzun execution sırasında expire/stale olan token persistence öncesinde görülür. Pre-persistence context yeni immutable DTO'dur; issuer/subject/tenant/token bağının initial context ile exact eşitliği ayrıca doğrulanır, Adım 9 authoritative DB state'i yeniden okunur ve initial DTO reuse edilmez.

`TrustedAuthorizationContextErrorCode` exact sekiz üyedir:

| Code | `granted` | `revoked` | Retry | Required audit | Metric | Safe message | Adapter decision code |
|---|---:|---:|---:|---:|---|---|---|
| `AUTH_CONTEXT_MISSING` | false | false | false | evet | `security.authorization.context_missing` | `Authorization context is unavailable.` | `AUTHZ_CONTEXT_MISSING` |
| `AUTH_CONTEXT_INVALID` | false | false | false | evet | `security.authorization.context_invalid` | `Authorization context is invalid.` | `AUTHZ_CONTEXT_INVALID` |
| `AUTH_CONTEXT_STALE` | false | false | false | evet | `security.authorization.context_stale` | `Authorization context is stale.` | `AUTHZ_CONTEXT_STALE` |
| `AUTH_CONTEXT_EXPIRED` | false | false | false | evet | `security.authorization.context_expired` | `Authorization context is expired.` | `AUTHZ_CONTEXT_EXPIRED` |
| `AUTH_CONTEXT_SUBJECT_MISMATCH` | false | false | false | evet | `security.authorization.context_subject_mismatch` | `Authorization context is inconsistent.` | `AUTHZ_CONTEXT_SUBJECT_MISMATCH` |
| `AUTH_CONTEXT_TENANT_MISMATCH` | false | false | false | evet | `security.authorization.context_tenant_mismatch` | `Authorization context is inconsistent.` | `AUTHZ_CONTEXT_TENANT_MISMATCH` |
| `AUTH_CONTEXT_PROVIDER_UNAVAILABLE` | false | false | true | evet | `security.authorization.context_provider_unavailable` | `Authorization provider is unavailable.` | `AUTHZ_PROVIDER_UNAVAILABLE` |
| `AUTH_CONTEXT_DATA_INTEGRITY_VIOLATION` | false | false | false | evet | `security.authorization.context_integrity` | `Authorization context is invalid.` | `AUTHZ_CONTEXT_INTEGRITY_FAILURE` |

Context hatasında subject HMAC üretilebiliyorsa exact `srh1` kullanılır; trusted subject oluşmadan hata verilmişse audit `actor_id="<unresolved>"`, safe attribute `subject_reference_status=UNAVAILABLE` taşır. Bu sabit değer identity veya pseudonym değildir ve hiçbir grant yolunda kullanılamaz.

Adım 9 repository çağrı mapping'i literal ve tek anlamlıdır: `issuer=context.issuer`, `subject=context.subject`, `tenant_key=context.tenant_key`, `token_issued_at=context.token_issued_at`, `expected_principal_kind=context.expected_principal_kind`, `expected_service_client_id=context.service_client_id`, `correlation_id=context.correlation_id`, `now=context.resolved_at`. Repository'nin zorunlu `request_id: str` girdisi için context request ID mevcutsa exact canonical değer; yoksa `ari1:<sha256("ari1\n" + correlation_reference + "\n" + checkpoint.value)>` kullanılır. Raw correlation, token veya subject bu derived reference'a girmez; `correlation_reference` exact `cr1`'dır. Bu fallback yalnız diagnostic request reference'ıdır, identity veya authorization authority değildir.

#### 15.16.2 Altı method ve pre-persistence checkpoint akışı

Altı public method imzası Bölüm 15.5 ile byte-level aynı kalır. Pre-persistence phase aynı public methodun çağrı sayısından tahmin edilmez: `LocalAuthorizationPolicyClient` ayrıca yukarıdaki internal `AuthorizationRevalidationPort`'u uygular ve 5.0C application-service production wiring'i persistence öncesinde exact `revalidate_*` metodunu çağırır. `AnalysisApplicationService` internal constructor wiring'ine zorunlu `authorization_revalidation: AuthorizationRevalidationPort` dependency'si eklenir; mevcut `authorization: AuthorizationPort` initial kontroller için değişmeden kalır. Mevcut `_execute` içindeki ikinci `authorize_method` çağrısı exact `authorization_revalidation.revalidate_start/resume/retry` dispatch'iyle, resume source write öncesi kontrolü de `revalidate_resume_source` ile değiştirilir. Production'da iki dependency'nin aynı `LocalAuthorizationPolicyClient` instance'ı olması zorunludur; missing dependency, public-method fallback'i veya farklı instance readiness failure'dır. Bu internal constructor/wiring değişikliği public 5.0C port/DTO sözleşmesi değildir ve router'a açılmaz. Böylece process-local invocation counter, thread-local flag veya “ikinci çağrı=revalidation” heuristiği yasaktır.

Her initial/revalidation çağrısı şu sırayı izler: context resolve/validate → Adım 9 fresh identity → authorization-context-reference proof → Adım 10 fresh effective permission materialization → registered action/reference request assembly → engine evaluation → audit event mapping → required delivery → exhaustive decision mapping → `adr1` final reference → fail-closed return.

| Public method/checkpoint | Context checkpoint | Action(lar) | Trusted resource reference | Ek kural |
|---|---|---|---|---|
| `authorize_start(scope, actor)` | `START` | `analysis.start` | exact `COMPANY_PERIOD` | run claim/same-subject replay 5.0C `RunScopeClaim` sahibidir; adapter audit field'ından run ID çıkarmaz |
| `authorize_resume(scope, actor)` | `RESUME` | `analysis.resume` | target `COMPANY_PERIOD` | source ayrıca ayrı `authorize_resume_source` ile kontrol edilir |
| `authorize_resume_source(source_run_id, target_scope, actor)` | `RESUME_SOURCE` | `analysis.resume_source` | provider'ın exact source `ANALYSIS_RUN` reference'ı; `resource_id == source_run_id` assertion | source/destination tenant ve company/period resolver sonucuyla exact |
| `authorize_read(scope, actor, include_payload=False)` | `READ` | `analysis.read` | provider'ın endpoint-bound `ANALYSIS_RUN` veya history için `COMPANY_PERIOD` reference'ı | metadata guard; endpoint-specific permission Adım 13'te ayrıca zorunlu |
| `authorize_read(..., include_payload=True)` | `READ` | sıralı `analysis.read`, sonra `analysis.payload.read` | aynı reference iki evaluation boyunca yeniden spoof edilemez | iki ALLOW ve iki required audit tamamlanmadan grant yok |
| `authorize_cancel(scope, actor)` | `CANCEL` | önce `analysis.cancel.own`; HUMAN için yalnız `RESOURCE_OWNERSHIP_MISMATCH` veya `PERMISSION_NOT_GRANTED` sonucunda `analysis.cancel.any` | provider'ın hedef `ANALYSIS_RUN` reference'ı | first deny required audit teslim edilmişse fallback açılır; custom role yalnız `cancel.any` taşıyabilir; missing/cross-tenant/state-invalid/integrity/outage/audit-failure sonucu fallback veya existence probe'una çevrilmez; SERVICE `cancel.any` deneyemez |
| `authorize_retry(scope, actor)` | `RETRY` | `analysis.retry` | target `COMPANY_PERIOD` | original operation RESUME ise source kontrolü ayrıca zorunlu |
| `revalidate_start/resume/retry` | ilgili `PRE_PERSIST_*` | initial action'ın aynısı | aynı semantic target için fresh resolver lookup | initial result veya identity DTO tekrar kullanılmaz |
| `revalidate_resume_source` | `PRE_PERSIST_RESUME_SOURCE` | `analysis.resume_source` | fresh source `ANALYSIS_RUN` | target revalidation'dan sonra ve persistence'dan önce ayrıca çalışır |

Adapter raw exception çıkarmaz ve HTTP status üretmez. Expected provider/repository/audit failure `AuthorizationDecision(granted=False, ...)` olur; programmer error dahi boundary'de safe terminal `AUTHZ_ADAPTER_INTEGRITY_FAILURE` kararına normalize edilir. `INDETERMINATE` ve `DENY` hiçbir zaman grant değildir. `ALLOW`, yalnız `AuditIntent.required=False` veya required audit başarıyla teslim edilmişse grant olabilir.

#### 15.16.3 `AuditIntent` → mevcut 5.0C audit sözleşmesi

Public `SecurityAuditPort.record_required_event(SecurityAuditEventDTO)` ve `ApplicationEventType` değiştirilmez. Mapping şöyledir:

| Adım 10 / internal alan | `SecurityAuditEventDTO` projection |
|---|---|
| ALLOW | `event_type=AUTHORIZATION_GRANTED` |
| DENY veya INDETERMINATE; context/identity/adapter failure | `event_type=AUTHORIZATION_DENIED` |
| policy `event_name` | `safe_attributes["event_name"]`; exact korunur |
| outcome/reason/action/resource type | ayrı sorted safe attributes |
| raw resource ID | attribute'a girmez; `rr1:<sha256(canonical resource type + version + typed ID)>` |
| tenant | raw attribute'a girmez; `tr1:<sha256(canonical tenant_key)>` |
| subject | `actor_id=subject_reference_hash`; ayrıca same HMAC safe attribute |
| correlation | public `correlation_id`; ayrıca `cr1:<sha256(correlation_id)>` reference |
| request ID | raw değer taşınmaz; varsa `qr1:<sha256(request_id)>` |
| severity | safe attribute exact enum value |
| occurred_at | policy `evaluated_at`; context failure'da trusted clock time |
| provider decision reference | delivery öncesi `audit_delivery=PENDING` ile hesaplanan provisional `adr1` safe attribute; final receipt sonrası returned decision için yeniden hesaplanır |
| application scope | mevcut zorunlu `scope` alanı değişmeden taşınır; bu authorized durable audit sink için explicit bounded exception'dır; safe attributes scope UUID'lerini tekrar etmez |
| run/application digest | Adım 11'de authoritative değer yoksa `run_id=None`, `application_command_digest=None` |

`safe_attributes` key sırası lexicographic, unique tuple'dır. Unsupported outcome/event type veya attribute overflow `AUDIT_EVENT_UNSUPPORTED/INVALID` olur; sessiz field drop yoktur. Tek bilinçli causal reduction final `provider_decision_reference`'ın event oluşturulurken henüz audit receipt içermemesidir: event provisional `adr1(PENDING)` taşır, returned decision final delivery state'li `adr1` taşır. İki reference aynı `evaluation_reference` ve audit idempotency key ile bağlıdır.

Safe reference ve audit-key codec'leri `name|tag|UTF8-byte-length|payload\n` framing'ini kullanır; header prefix output prefix'iyle aynıdır. Exact manifestler:

- `cr1`: `correlation_id(s)`;
- `qr1`: `request_id(s)`;
- `tr1`: `tenant_key(s)`;
- `rr1`: `resource_type(e)`, `resource_version(s?)`, ardından `ResourceSecurityReference` içindeki scope-manifest sırasıyla typed identifier alanları;
- `ar1`: `receipt_id(s)`, `audit_record_digest(h)`, `event_type(e)`;
- `aik1`: `correlation_reference(s)`, `subject_reference(s?)`, `subject_reference_status(e)`, `action_code(s)`, `policy_reason(e?)`, `resource_reference(s?)`, `evaluated_at(t)`, `event_name(s)`.

Her output `<prefix>:<64-lowercase-sha256>`'dır. Nullable değer `n|4|null`, UTC değer exact altı mikrosaniye `Z`, digest `h`, enum `e`, string `s` tag'idir. Unknown field, alternate order, implicit concatenation, Unicode normalization, raw ID fallback veya silent coercion yasaktır. Receipt, `SecurityAuditReceiptDTO` exact type; requested event type equality; canonical non-empty receipt ID; lowercase 64-hex record digest ve UTC-aware `recorded_at >= occurred_at` kontrollerini geçmeden `ar1` üretilemez. Receipt `recorded_at` güvenli reference digest'ine dahil edilmez; sink'in durable record digest'i authoritative freshness/integrity kanıtıdır.

Audit idempotency key exact `aik1:<sha256>`'dır ve yukarıdaki manifestten üretilir. Scope reference `asr1:<sha256>` aynı framing ile exact `company_id(u)`, `financial_period_id(u)`, `tenant_id(u?)`, `operation_kind(e)`, `original_operation(e)`, `previous_run_id(s?)` sırasından üretilir; public DTO serialization veya 5.0B storage codec'i değildir. Canonical event digest `aed1:<sha256>`; `event_type`, `occurred_at`, `cr1`, `asr1`, `actor_id(srh1|<unresolved>)`, nullable run/decision/application digest ve lexicographically sorted safe attributes üzerinden aynı typed framing'le hesaplanır. `audit_event_digest` alanının kendisi digest girdisinden dışlanır; `audit_idempotency_key` girdiye dahildir. Key ve event digest `safe_attributes` içinde taşınır. Aynı key + aynı digest replay aynı receipt'i döndürür; aynı key + farklı digest `AUDIT_DELIVERY_CONFLICT`; sink duplicate üretmez. Adım 11 adapter içi automatic retry yapmaz.

Audit failure taxonomy kapalıdır:

| Code | Retry | Metric | Safe message | Required ALLOW etkisi | Existing DENY etkisi |
|---|---:|---|---|---|---|
| `AUDIT_STORE_UNAVAILABLE` | true | `security.authorization.audit_store_unavailable` | `Authorization audit is unavailable.` | `AUDIT_REQUIRED_BUT_UNAVAILABLE`, grant=false | deny korunur; operational metric |
| `AUDIT_STORE_TIMEOUT` | true | `security.authorization.audit_store_timeout` | `Authorization audit timed out.` | aynı | deny korunur; operational metric |
| `AUDIT_EVENT_INVALID` | false | `security.authorization.audit_event_invalid` | `Authorization audit event is invalid.` | `AUTHZ_AUDIT_INTEGRITY_FAILURE`, grant=false | deny korunur; integrity alert |
| `AUDIT_EVENT_UNSUPPORTED` | false | `security.authorization.audit_event_unsupported` | `Authorization audit event is unsupported.` | aynı | deny korunur; integrity alert |
| `AUDIT_DELIVERY_CONFLICT` | false | `security.authorization.audit_delivery_conflict` | `Authorization audit delivery conflicted.` | aynı | deny korunur; integrity alert |
| `AUDIT_DATA_INTEGRITY_VIOLATION` | false | `security.authorization.audit_integrity` | `Authorization audit integrity validation failed.` | aynı | deny korunur; integrity alert |

`SECURITY_CRITICAL` ve `ALLOW_AND_DENY` ALLOW audit outage'ında final karar `AUDIT_REQUIRED_BUT_UNAVAILABLE` olur. `DENY_ONLY` deny audit outage'ında original deny decision code/revoked değeri değişmez, final `adr1` audit failure'ı içerir ve best-effort security metric zorunludur. Audit sink exception/cause/receipt ID doğrudan decision veya log'a girmez.

Adım 11'in detailed policy-decision eventi ile mevcut 5.0C `AnalysisApplicationService._audit_authorization` application-boundary eventi iki ayrı audit kaydıdır; biri diğerinin replay'i veya substitute'u değildir. Adım 11 idempotency key'i yalnız detailed event'i tekilleştirir. Mevcut boundary event public 5.0C davranışı olarak korunur ve onun outage'ı mevcut `SECURITY_AUDIT_FAILED` fail-closed sonucunu üretir. Bu sonraki boundary failure, adapter'ın döndürdüğü DENY decision code/revoked değerini mutate etmez; yalnız application outcome'un daha genel audit failure olarak kapanmasına yol açar. Step 12 mapping'i `ApplicationAuditContextDTO.actor_id` alanına raw subject yerine exact `srh1` koymak zorundadır; böylece mevcut boundary event de subject/PII sızdırmaz. Testler bir authorization evaluation için exact bir detailed event ve exact bir boundary event bekler; detailed replay yalnız kendi `aik1` key/digest kuralına tabidir.

#### 15.16.4 Exhaustive `AuthorizationDecision` mapping

`AuthorizationDecision` exact alanları `granted`, `revoked`, `decision_code`, `provider_decision_reference`, `decided_at` olarak kalır. `decision_code` Adım 11 internal closed enum value'sudur; public DTO değiştirilmez. `decided_at` policy evaluation instant'ıdır, audit completion wall time değildir.

Internal `AuthorizationAdapterDecisionCode` kapalı seti aşağıdaki **47 unique literal** ile sınırlıdır; `AuthorizationDecision.decision_code` yalnız bu enumun `.value` değerini taşır:

```text
AUTHZ_ALLOWED
AUTHZ_UNKNOWN_ACTION
AUTHZ_UNKNOWN_PERMISSION
AUTHZ_UNKNOWN_ROLE
AUTHZ_REGISTRY_VERSION_MISMATCH
AUTHZ_TENANT_POLICY_VERSION_MISMATCH
AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED
AUTHZ_PERMISSION_NOT_GRANTED
AUTHZ_STRENGTH_INSUFFICIENT
AUTHZ_TENANT_MISMATCH
AUTHZ_RESOURCE_OWNERSHIP_MISMATCH
AUTHZ_SUBJECT_PREDICATE_FAILED
AUTHZ_RESOURCE_NOT_FOUND
AUTHZ_RESOURCE_STATE_INVALID
AUTHZ_PROVIDER_UNAVAILABLE
AUTHZ_PROVIDER_TIMEOUT
AUTHZ_POLICY_INTEGRITY_FAILURE
AUTHZ_CONTEXT_MISSING
AUTHZ_CONTEXT_INVALID
AUTHZ_CONTEXT_STALE
AUTHZ_CONTEXT_EXPIRED
AUTHZ_CONTEXT_SUBJECT_MISMATCH
AUTHZ_CONTEXT_TENANT_MISMATCH
AUTHZ_CONTEXT_INTEGRITY_FAILURE
AUDIT_REQUIRED_BUT_UNAVAILABLE
AUTHZ_AUDIT_INTEGRITY_FAILURE
AUTHZ_IDENTITY_REVOKED_PRINCIPAL
AUTHZ_IDENTITY_REVOKED_MEMBERSHIP
AUTHZ_IDENTITY_REVOKED_TOKEN
AUTHZ_TENANT_INACTIVE
AUTHZ_IDENTITY_NOT_FOUND
AUTHZ_IDENTITY_TENANT_NOT_FOUND
AUTHZ_IDENTITY_TENANT_MISMATCH
AUTHZ_IDENTITY_PRINCIPAL_KIND_MISMATCH
AUTHZ_IDENTITY_MEMBERSHIP_NOT_FOUND
AUTHZ_IDENTITY_MEMBERSHIP_NOT_YET_VALID
AUTHZ_IDENTITY_SERVICE_SAFE_ROLE_NOT_FOUND
AUTHZ_IDENTITY_SERVICE_ROLE_PERMISSION_INVALID
AUTHZ_IDENTITY_NONCANONICAL_INPUT
AUTHZ_IDENTITY_INTEGRITY_FAILURE
AUTHZ_REVALIDATION_REVOKED_PRINCIPAL
AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP
AUTHZ_REVALIDATION_REVOKED_TOKEN
AUTHZ_REVALIDATION_REVOKED_TENANT
AUTHZ_REVALIDATION_REVOKED_POLICY
AUTHZ_REVALIDATION_REVOKED_RESOURCE
AUTHZ_ADAPTER_INTEGRITY_FAILURE
```

Duplicate literal, alias, case-folding, prefix-based dynamic construction ve unknown string yasaktır. Resume-source evaluation aynı policy/context/identity code'larını kullanır; source'a özel yeni dynamic decision code üretilmez.

Audit requirement reason'dan tek başına türetilmez; Bölüm 15.8'deki exact action manifesti + outcome formülü aynen korunur: `ALLOWED` için `ALLOW_AND_DENY|SECURITY_CRITICAL` required, `DENY_ONLY|NONE` not-required; valid registered action'a sahip DENY için `DENY_ONLY|ALLOW_AND_DENY|SECURITY_CRITICAL` required, `NONE` not-required; üç INDETERMINATE reason için her zaman required. Action/permission metadata çözülemeyen `UNKNOWN_ACTION`, `UNKNOWN_PERMISSION`, adapter/context/identity/integrity terminal'leri `SECURITY_CRITICAL` required audit üretir. Aşağıdaki “exact result requirement” hücreleri bu formülle oluşturulmuş immutable `PolicyEvaluationResult.audit_intent.requirement` değerini ifade eder; adapter yeniden yorumlamaz.

| Policy reason | granted | revoked | decision_code | Retry | Exact audit requirement | ADR reason/code delta | Safe external behavior |
|---|---:|---:|---|---:|---|---|---|
| `ALLOWED` | true | false | `AUTHZ_ALLOWED` | false | yukarıdaki ALLOW formülü; required ise delivery başarı şartı | `ALLOWED/AUTHZ_ALLOWED` | allow |
| `UNKNOWN_ACTION` | false | false | `AUTHZ_UNKNOWN_ACTION` | false | `SECURITY_CRITICAL` | `UNKNOWN_ACTION/AUTHZ_UNKNOWN_ACTION` | deny/integrity |
| `UNKNOWN_PERMISSION` | false | false | `AUTHZ_UNKNOWN_PERMISSION` | false | `SECURITY_CRITICAL` | `UNKNOWN_PERMISSION/AUTHZ_UNKNOWN_PERMISSION` | deny/integrity |
| `UNKNOWN_ROLE` | false | false | `AUTHZ_UNKNOWN_ROLE` | false | exact result `audit_intent.requirement` | `UNKNOWN_ROLE/AUTHZ_UNKNOWN_ROLE` | deny |
| `REGISTRY_VERSION_MISMATCH` | false | false | `AUTHZ_REGISTRY_VERSION_MISMATCH` | false | exact result `audit_intent.requirement` | same reason + decision code | deny |
| `TENANT_POLICY_VERSION_MISMATCH` | false | false | `AUTHZ_TENANT_POLICY_VERSION_MISMATCH` | false | exact result requirement | same reason + decision code | deny |
| `PRINCIPAL_KIND_NOT_ALLOWED` | false | false | `AUTHZ_PRINCIPAL_KIND_NOT_ALLOWED` | false | exact result requirement | same reason + decision code | deny |
| `PERMISSION_NOT_GRANTED` | false | false | `AUTHZ_PERMISSION_NOT_GRANTED` | false | exact result requirement | same reason + decision code | deny |
| `INSUFFICIENT_AUTHENTICATION_STRENGTH` | false | false | `AUTHZ_STRENGTH_INSUFFICIENT` | false | exact result requirement | reason + `AUTHZ_STRENGTH_INSUFFICIENT` | deny |
| `TENANT_MISMATCH` | false | false | `AUTHZ_TENANT_MISMATCH` | false | exact result requirement | same reason + decision code | hidden deny |
| `RESOURCE_OWNERSHIP_MISMATCH` | false | false | `AUTHZ_RESOURCE_OWNERSHIP_MISMATCH` | false | exact result requirement | same reason + decision code | deny/hidden per policy |
| `SUBJECT_PREDICATE_FAILED` | false | false | `AUTHZ_SUBJECT_PREDICATE_FAILED` | false | exact result requirement | same reason + decision code | deny |
| `RESOURCE_NOT_FOUND` | false | false | `AUTHZ_RESOURCE_NOT_FOUND` | false | exact result requirement | same reason + decision code | hidden deny |
| `RESOURCE_STATE_INVALID` | false | false | `AUTHZ_RESOURCE_STATE_INVALID` | false | exact result requirement | same reason + decision code | hidden deny/integrity |
| `POLICY_STORE_UNAVAILABLE` | false | false | `AUTHZ_PROVIDER_UNAVAILABLE` | true | required=true; exact result requirement | reason + `AUTHZ_PROVIDER_UNAVAILABLE` | dependency unavailable |
| `POLICY_STORE_TIMEOUT` | false | false | `AUTHZ_PROVIDER_TIMEOUT` | true | required=true; exact result requirement | reason + `AUTHZ_PROVIDER_TIMEOUT` | dependency unavailable |
| `DATA_INTEGRITY_VIOLATION` | false | false | `AUTHZ_POLICY_INTEGRITY_FAILURE` | false | `SECURITY_CRITICAL` | reason + `AUTHZ_POLICY_INTEGRITY_FAILURE` | fail-closed integrity |

Tüm ADR satırlarında tablodaki delta'ya ek olarak Bölüm 15.16.5'in registry/tenant version, resource version, `srh1`, membership version, iki timestamp, audit state/receipt ve correlation reference girdileri zorunludur. Böylece aynı reason farklı identity/resource/audit state'inde yanlışlıkla aynı reference üretmez.

Policy result oluşmadan terminal olan context/identity/adapter failure'larında ADR girdileri adapter yorumuna bırakılmaz:

| ADR alanı | Pre-policy terminal değeri |
|---|---|
| `policy_registry_version` | process-start validation'dan geçmiş compiled registry exact version'ı |
| `tenant_policy_version` | `null`; kısmi repository state dışarı çıkarılmaz |
| `action_code` | methodun primary registered action'ı: cancel için `analysis.cancel.own`, payload read dahil read için `analysis.read`, diğerlerinde Bölüm 15.16.2 literal action'ı |
| `decision_code` | context/identity/adapter taxonomy exact mapping'i |
| `policy_reason` | `null` |
| `resource_version` | `null` |
| `principal_reference` | trusted context doğrulandı ve hash üretildiyse exact `srh1`, aksi halde `null` |
| `membership_version` / `identity_resolved_at` | identity DTO başarıyla oluşmadıysa ikisi de `null` |
| `policy_evaluated_at` | terminal normalization için alınan tek trusted-clock instant; aynı değer `AuthorizationDecision.decided_at` olur |
| `audit_delivery` / receipt | exact audit attempt sonucu; receipt raw değildir |
| `correlation_reference` | trusted correlation varsa exact `cr1`; context öncesi yoksa request-bound composition'ın safe correlation reference'ı |

Bu terminal normalization tek kez çalışır; partial tenant/membership/resource veri sızıntısı, action fallback veya ikinci policy evaluation yoktur. Context provider güvenilir correlation reference dahi sağlayamıyorsa sabit terminal fallback kullanılır ve best-effort integrity metric üretilir.

Unknown/non-enum reason, missing metadata row veya result/action mismatch `AUTHZ_ADAPTER_INTEGRITY_FAILURE`, grant=false, revoked=false olur; unknown value coerce edilmez. Mapping literal 17 satırla import/test invariant'ıdır.

Identity taxonomy mapping'i aşağıdaki **19/19 literal** satırdır; prefix concatenation yapılmaz. “Initial code / revoked” ve “revalidation code / revoked” ayrımı exact'tir. Tüm satırlarda granted=false; yalnız store outage/timeout retryable=true; audit `SECURITY_CRITICAL` required'dır.

| Identity source code | Initial decision / revoked | Revalidation decision / revoked |
|---|---|---|
| `IDENTITY_NOT_FOUND` | `AUTHZ_IDENTITY_NOT_FOUND` / false | aynı / false |
| `TENANT_NOT_FOUND` | `AUTHZ_IDENTITY_TENANT_NOT_FOUND` / false | aynı / false |
| `TENANT_MISMATCH` | `AUTHZ_IDENTITY_TENANT_MISMATCH` / false | aynı / false |
| `PRINCIPAL_KIND_MISMATCH` | `AUTHZ_IDENTITY_PRINCIPAL_KIND_MISMATCH` / false | aynı / false |
| `TENANT_INACTIVE` | `AUTHZ_TENANT_INACTIVE` / false | `AUTHZ_REVALIDATION_REVOKED_TENANT` / true |
| `PRINCIPAL_INACTIVE` | `AUTHZ_IDENTITY_REVOKED_PRINCIPAL` / true | `AUTHZ_REVALIDATION_REVOKED_PRINCIPAL` / true |
| `SUBJECT_BINDING_INACTIVE` | `AUTHZ_IDENTITY_REVOKED_PRINCIPAL` / true | `AUTHZ_REVALIDATION_REVOKED_PRINCIPAL` / true |
| `MEMBERSHIP_NOT_FOUND` | `AUTHZ_IDENTITY_MEMBERSHIP_NOT_FOUND` / false | aynı / false |
| `MEMBERSHIP_INACTIVE` | `AUTHZ_IDENTITY_REVOKED_MEMBERSHIP` / true | `AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP` / true |
| `MEMBERSHIP_NOT_YET_VALID` | `AUTHZ_IDENTITY_MEMBERSHIP_NOT_YET_VALID` / false | aynı / false |
| `MEMBERSHIP_EXPIRED` | `AUTHZ_IDENTITY_REVOKED_MEMBERSHIP` / true | `AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP` / true |
| `SERVICE_SAFE_ROLE_NOT_FOUND` | `AUTHZ_IDENTITY_SERVICE_SAFE_ROLE_NOT_FOUND` / false | aynı / false |
| `SERVICE_ROLE_PERMISSION_INVALID` | `AUTHZ_IDENTITY_SERVICE_ROLE_PERMISSION_INVALID` / false | aynı / false |
| `TOKEN_REVOKED_BY_PRINCIPAL` | `AUTHZ_IDENTITY_REVOKED_TOKEN` / true | `AUTHZ_REVALIDATION_REVOKED_TOKEN` / true |
| `TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY` | `AUTHZ_IDENTITY_REVOKED_TOKEN` / true | `AUTHZ_REVALIDATION_REVOKED_TOKEN` / true |
| `NONCANONICAL_IDENTITY_INPUT` | `AUTHZ_IDENTITY_NONCANONICAL_INPUT` / false | aynı / false |
| `DATA_INTEGRITY_VIOLATION` | `AUTHZ_IDENTITY_INTEGRITY_FAILURE` / false | aynı / false |
| `IDENTITY_STORE_UNAVAILABLE` | `AUTHZ_PROVIDER_UNAVAILABLE` / false | aynı / false |
| `IDENTITY_STORE_TIMEOUT` | `AUTHZ_PROVIDER_TIMEOUT` / false | aynı / false |

Pre-persistence sırasında initial ALLOW sonrasında `UNKNOWN_ROLE`, `UNKNOWN_PERMISSION`, registry/tenant version mismatch, principal-kind safety veya permission removal görülürse `AUTHZ_REVALIDATION_REVOKED_POLICY`; ownership/subject predicate veya resource-state/version değişimi görülürse `AUTHZ_REVALIDATION_REVOKED_RESOURCE`; `revoked=true` olur. `RESOURCE_NOT_FOUND` yalnız hidden/missing sonucu olduğundan gerçek revoke kanıtı değildir ve `revoked=false`; store/context/audit outage da hiçbir zaman revoked değildir. Normal initial permission deny `revoked=false` kalır.

Context taxonomy Bölüm 15.16.1, audit taxonomy Bölüm 15.16.3 exact decision code'larına map edilir. Mapping/`AuthorizationDecision` constructor failure ikinci constructor recursion yapmaz; literal terminal reference `adr1:a31a2ecaceba5e0f9ad33c96bde95be366114e04e9b9a68bdb546ce66a65e3da` ile `AuthorizationDecision(False, False, "AUTHZ_ADAPTER_INTEGRITY_FAILURE", ..., trusted_clock_time)` tek safe fallback'tir. Fallback construction da başarısızsa internal fatal exception üst boundary'de `AUTHORIZATION_PROVIDER_UNAVAILABLE` olarak fail-closed normalize edilir; grant üretilmez.

#### 15.16.5 `AuthorizationDecisionReferenceCodec v1`

Final reference exact `adr1:<64-lowercase-sha256>`'dır. Canonical bytes header'ı `b"adr1\n"`; kayıt framing'i ResourceSecurityVersionCodec ile aynı `name|tag|UTF8-byte-length|payload\n` kuralıdır. Sabit sıra:

1. `policy_registry_version(s)`;
2. `tenant_policy_version(i?)`;
3. `action_code(s)`;
4. `decision_code(e)`;
5. `policy_reason(e?)`;
6. `resource_version(s?)`;
7. `principal_reference(s?)` — yalnız `srh1`;
8. `membership_version(i?)`;
9. `identity_resolved_at(t?)`;
10. `policy_evaluated_at(t)`;
11. `audit_delivery(e)` — `PENDING|NOT_REQUIRED|DELIVERED|FAILED_REQUIRED|FAILED_NON_REQUIRED`;
12. `audit_receipt_reference(s?)` — `ar1:<sha256(canonical receipt id + record digest)>`;
13. `correlation_reference(s)` — `cr1:<sha256(correlation_id)>`.

Optional null exact `tag=n,payload=null` olur. UUID, raw subject, tenant key, resource ID, token, SQL veya receipt ID frame'e girmez. Positive versions, UTC exact six-microsecond `Z`, closed enum, canonical `rsv1/srh1/ar1/cr1` pattern ve manifest field set/order zorunludur. Unknown/malformed input fail-closed terminal mapping'e gider. Aynı semantic decision byte-identical reference üretir; audit state/receipt, policy or membership version, resource version, revocation reason veya evaluation instant değişirse reference değişir.

Golden vectors ortak input olarak registry `1.0.0`, tenant version `7`, action `analysis.start`, resource `rsv1:` + 64 `a`, principal `srh1:k1:` + 64 `b`, membership version `3`, identity time `2026-08-02T10:11:12.123456Z`, evaluation time `2026-08-02T10:11:13.123456Z`, receipt `ar1:` + 64 `c`, correlation `cr1:` + 64 `d` kullanır:

| Vector | Değişen alanlar | Expected output |
|---|---|---|
| ADR-1 allow/delivered | `AUTHZ_ALLOWED`, `ALLOWED`, `DELIVERED` | `adr1:452ed9e0f9ede5b0c50aac48d9aacab07d497a769529de6bded94354b7b1ea8f` |
| ADR-2 deny/delivered | `AUTHZ_PERMISSION_NOT_GRANTED`, `PERMISSION_NOT_GRANTED`, `DELIVERED` | `adr1:61784854978384a5f9af72ee13eb34a55ddfb285c455bdb2ed6d2a344e8782d6` |
| ADR-3 required audit failure | `AUDIT_REQUIRED_BUT_UNAVAILABLE`, policy reason `ALLOWED`, `FAILED_REQUIRED`, receipt null | `adr1:ef85e717b6c66ad123db259a159ff8dbdacbc70be2d1dc8c7a5566937d4f3364` |
| ADR-4 revalidation revoked | `AUTHZ_REVALIDATION_REVOKED_MEMBERSHIP`, reason/resource null, `DELIVERED` | `adr1:105d9d963b13207ba4279690cd0ef08c725b9c6d06a53a815bb46196b0ed3151` |

Testler canonical ADR-1 bytes'ını da literal fixture olarak doğrular; yalnız digest assertion yeterli değildir.

#### 15.16.6 Pre-persistence revalidation, transaction ve TOCTOU

5.0C application-service implementation'ı public `AuthorizationPort` initial çağrılarını korur; production wiring'e internal `AuthorizationRevalidationPort` eklenir ve persistence öncesi `revalidate_start/resume/retry` çağrılır. Resume/RETRY(original RESUME) için target revalidation'dan sonra `revalidate_resume_source` ayrıca zorunludur. Hiçbir initial identity, permission set, scope veya policy result reuse edilmez. Sonuç ALLOW ve required audit delivered değilse `persist_terminal_run` hiç çağrılmaz. Public command/query/port imzası değişmez; test fake'leri initial ve revalidation portlarını ayrı uygular.

Transaction kararı: security identity/permission/resource read'leri kısa ayrı `READ ONLY, REPEATABLE READ` snapshot'lar; 5.0B terminal persistence kendi transaction'ıdır. Frozen public portlar ve session-factory sahipliği korunarak tek shared transaction kurulmaz. Bu nedenle garanti **“revalidation snapshot'ından önce commit edilmiş revoke/değişiklik write'ı engeller”** ile sınırlıdır; snapshot tamamlandıktan sonra persistence commit'inden önce oluşan yeni revoke için atomik sıfır-TOCTOU iddiası yoktur. Şema/public persistence contract değişikliği olmadan daha güçlü garanti verilemez. V1 mitigasyonu revalidation'ı ownership planından sonra ve `RunScopeClaim.verify`/terminal write'tan hemen önce yapmak, fresh resource version çözmek, positive cache kullanmamak ve mevcut scope/FK/digest/immutability constraint'lerine güvenmektir. Cross-transaction authorization epoch/CAS veya shared serializable transaction future hardening'dir.

Expected resource version contextte varsa fresh authoritative scope ile mismatch `RESOURCE_STATE_INVALID`; pre-persistence'ta `AUTHZ_REVALIDATION_REVOKED_RESOURCE`, revoked=true, persistence call-count=0 olur. Revalidation ALLOW sonrası persistence DB conflict/unavailable olursa authorization audit kaydı geri alınmaz; bu kayıt yalnız “write yetkilendirildi” anlamındadır, “write commit edildi” anlamında değildir. Terminal persistence için mevcut application `TERMINAL_RUN_PERSISTED` auditi ayrı kalır. Revalidation sonucu cache edilmez veya sonraki request'e taşınmaz.

Resume source revalidation source run'ı fresh tenant-qualified resolver ile yükler; source target tenant/company/period exact değilse, hidden/cross-tenant/missing ise veya permission/owner/resource version değişmişse fail-closed olur. Destination context ayrıca target action ile fresh değerlendirilir. Initial source ALLOW persistence öncesinde yeterli değildir; source revalidation başarısızsa snapshot daha önce materialize edilmiş olsa bile terminal persistence yapılmaz ve payload caller'a dönmez.

#### 15.16.7 Adım 11 constructor ve dependency graph

```python
class LocalAuthorizationPolicyClient(AuthorizationPort, AuthorizationRevalidationPort):
    def __init__(
        self, *, context_provider: TrustedAuthorizationContextProviderPort,
        identity_repository: SecurityIdentityRepositoryPort,
        policy_repository: AuthorizationPolicyRepositoryPort,
        policy_engine: AuthorizationPolicyEnginePort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        clock: ApplicationClockPort,
        subject_reference_hash_codec: SubjectReferenceHashCodec,
        decision_reference_codec: AuthorizationDecisionReferenceCodec,
    ) -> None: ...
```

Resource repository ve synthetic resolver Adım 10 engine construction'ında bind edilir; adapter router veya SQLAlchemy session almaz. Required dependency missing/no-op/fake production binding readiness'i kapatır. Adım 11 context provider'ın request-bound production implementasyonunu yapmaz; Adım 12 bunu bind eder.

---

## 16. Port, Provisioning ve Identity Lifecycle Sözleşmeleri

### 16.1 Runtime security portları

```python
class JwtVerifierPort(Protocol):
    def verify(self, token: str, *, now: datetime) -> VerifiedJwt: ...

class JwksProviderPort(Protocol):
    def get_key(self, issuer: str, kid: str, *, now: datetime) -> VerificationKey: ...
    def readiness_check(self, deadline: datetime) -> bool: ...

@dataclass(frozen=True)
class VerifiedLocalIdentity:
    principal_id: UUID
    principal_kind: IdentityKind
    provider_issuer: str
    provider_subject: str
    tenant_id: UUID
    tenant_key: str
    membership_id: UUID
    principal_status: SecurityEntityStatus
    tenant_status: SecurityEntityStatus
    binding_status: SecurityEntityStatus
    membership_status: SecurityEntityStatus
    authentication_context_subject: str
    authentication_context_tenant_key: str
    roles: tuple[str, ...]
    permission_resolution_reference: str
    role_set_digest: str
    permission_registry_version: str
    tenant_policy_version: int
    tokens_valid_after: datetime
    membership_valid_from: datetime
    membership_valid_until: datetime | None
    principal_version: int
    membership_version: int
    resolved_at: datetime

class SecurityIdentityRepositoryPort(Protocol):
    def resolve_principal_and_membership(
        self, *, issuer: str, subject: str, tenant_key: str,
        token_issued_at: datetime, expected_principal_kind: IdentityKind,
        expected_service_client_id: str | None,
        correlation_id: str, request_id: str, now: datetime,
    ) -> VerifiedLocalIdentity: ...

class AuthorizationPolicyEnginePort(Protocol):
    def evaluate(
        self, *, request: PolicyEvaluationRequest,
        effective_permissions: EffectivePermissionSet,
    ) -> PolicyEvaluationResult: ...

class AuthenticationSecurityAuditPort(Protocol):
    def record_required_event(self, event: AuthenticationAuditEvent) -> AuditReceipt: ...
```

`AuthorizationPolicyEnginePort` internal exact-action değerlendirmesidir; `ResourceSecurityRepositoryPort` sekiz durable domain scope'unu, `SyntheticSecurityScopeResolverPort` SYSTEM/TENANT/COMPANY_PERIOD scope'larını çözer. Analysis core değişmemiş 5.0C `AuthorizationPort` kullanır. Adım 11 `LocalAuthorizationPolicyClient`, aynı closed PermissionRegistry engine'ini değişmemiş 5.0C/5.0D adapter contract'larına bağlar.

#### 16.1.1 `VerifiedLocalIdentity` invariant'ları

`VerifiedLocalIdentity`, framework-bağımsız ve immutable internal DTO'dur. `roles`, ASCII role code'larından oluşan unique, lexicographically ordered `tuple`'dır; mutable collection, ORM entity veya lazy relationship içermez. DTO raw bearer token, raw claims, email, display name, IP, User-Agent veya başka kişisel veri taşımaz.

- HUMAN ve SERVICE aynı anda geçerli olamaz; `principal_kind` authoritative `security_principals.kind` değeridir. Token profile yalnız `expected_principal_kind` olarak karşılaştırılır ve local kind'ın kaynağı değildir.
- HUMAN için ACTIVE membership ve en az bir active HUMAN-safe rol zorunludur. HUMAN'a atanmış her active rolün tüm permission'ları `human_allowed=true` olmalı ve `SERVICE_OPERATOR` gibi SERVICE-only rol bulunmamalıdır.
- SERVICE için ACTIVE tenant membership ve en az bir active service-safe rol zorunludur. Ayrı `security_service_grants` tablosu ve DTO'da synthetic/derived grant ID/status/version alanı yoktur. “Service grant”, membership + active role setinin tüm permission'larının `service_allowed=true` olmasıdır. `SERVICE_OPERATOR` yalnız built-in varsayılandır; service-safe custom role tek başına yeterlidir. Hiç service-safe rol yoksa `SERVICE_SAFE_ROLE_NOT_FOUND`, herhangi bir assigned active rol human-only permission içeriyorsa `SERVICE_ROLE_PERMISSION_INVALID` üretilir.
- `tenant_id` ile `tenant_key` aynı tek `security_tenants` satırından gelmeli; `authentication_context_subject == provider_subject` ve `authentication_context_tenant_key == tenant_key` olmalıdır.
- Başarılı DTO'daki tenant, principal, binding ve membership status'ları ACTIVE'dir. Version alanları pozitif, tüm zamanlar UTC-aware'dir.
- Repository permission kararı veya allow/deny üretmez. `permissions` taşınmaz; Adım 10/11 için exact proof seti `permission_resolution_reference`, `role_set_digest`, `permission_registry_version` ve `tenant_policy_version` alanlarıdır. Bunlar identity-resolution sırasında role/permission safety doğrulamasının immutable kanıt referansıdır; grant veya authorization decision değildir.
- Internal tenant UUID yalnız security repository/policy adapter sınırında kalır. 5.0A–5.0D application DTO'larına, `AuthenticationContext.tenant_id` alanına, API response'una veya engine input'una sızmaz; bu sınırlar canonical external `tenant_key` kullanır.
- Adım 9 authentication/identity state'i doğrular; authorization kararı, resource ownership kararı, HTTP status veya route davranışı üretmez.

Constructor/`__post_init__` aşağıdaki invariant'ları fail-closed uygular:

- `principal_id`, `tenant_id` ve `membership_id` gerçek `UUID` instance'larıdır; string coercion yapılmaz.
- `tokens_valid_after`, `membership_valid_from`, optional `membership_valid_until` ve `resolved_at` normalize edilmiş UTC-aware `datetime`'dır; naive veya DTO'ya kadar normalize edilmemiş UTC dışı offset reddedilir. Repository port girdisindeki aware offset önce aynı instant korunarak UTC'ye çevrilir. `resolved_at`, injected current resolution time'dır ve token zamanından türetilmez.
- `roles` yalnız non-empty `tuple[str, ...]` kabul eder. Role code'ları canonical ASCII'dir, lexicographically artan sıradadır ve duplicate role kesin reddedilir; deduplicate/sort ile sessiz düzeltme yapılmaz.
- `principal_status`, `tenant_status`, `binding_status` ve `membership_status` ACTIVE değilse başarı DTO'su kurulamaz. Version'lar pozitif olmalıdır.
- `authentication_context_subject/provider_subject` ve `authentication_context_tenant_key/tenant_key` exact eşleşmelidir.
- HUMAN ve SERVICE için membership ve non-empty canonical role tuple zorunludur. DTO constructor custom role permission'larını okuyamaz ve service/human safety'yi yeniden hesaplamaz; bu kontrol repository-proven invariant'tır. SERVICE_OPERATOR adına özel DTO-local zorunluluk yoktur.
- `role_set_digest` exact 64 lowercase hexadecimal SHA-256, `permission_registry_version` supported closed registry version, `tenant_policy_version` pozitif integer olmalıdır. `permission_resolution_reference` non-empty ve exact `policy-ref/v1:<tenant-policy-version>:<membership-id>:<membership-version>:<permission-registry-version>:<role-set-digest>` biçimindedir; DTO constructor alanlar arası format/equality kontrolü yapar.
- Tenant, principal ve membership FK ilişkileri aynı snapshot'ta doğrulanmış olmalıdır. DTO bu relational proof'u ORM nesnesi olarak taşımaz; repository doğrulanmamış değerlerle constructor çağırmaz.
- Constructor hiçbir mutable collection, raw token/claim, permission listesi, SQL/ORM nesnesi veya PII kabul etmez. Her DTO-local cross-field invariant violation repository sınırında `DATA_INTEGRITY_VIOLATION` olur; invalid `VerifiedLocalIdentity` hiçbir durumda döndürülemez.

DTO-local invariant'lar yalnız DTO'nun taşıdığı alanlarla sınırlıdır: gerçek UUID tipleri; kapalı `principal_kind`; canonical tenant_key/issuer/subject; ACTIVE status'lar; pozitif version'lar; normalize UTC zamanlar; non-empty immutable/sıralı/unique role tuple; exact proof alan formatı ve reference içi equality; subject/tenant context equality; raw sensitive/infrastructure veri taşımama. Constructor authoritative PostgreSQL ilişki veya custom-role permission safety sorgusu yapmaz.

Repository-proven invariant'lar şunlardır: tenant_key↔tenant UUID; binding↔principal; membership↔principal+tenant; local authoritative principal kind; membership status/validity; active role assignment'ları; HUMAN için tüm rol permission'larında `human_allowed=true`; SERVICE için en az bir rol ve tüm rol permission'larında `service_allowed=true`; permission registry version; role-set digest/reference; effective revocation boundary; tüm relational/data-integrity kontrolleri. Bunlardan biri başarısızsa DTO constructor çağrılmaz; beklenen state deny kodu, beklenmeyen çelişki `DATA_INTEGRITY_VIOLATION` üretir. DTO-local constructor hatası da repository boundary'sinde `DATA_INTEGRITY_VIOLATION`'a normalize edilir.

`role_set_digest`, aynı snapshot'taki active assignment'lar için role code sırasına göre canonical kayıtlardan hesaplanır. Her kayıt exact `role_id` (lowercase hyphenated UUID), `role_code`, decimal `role_version` ve lexicographically sorted unique permission code tuple'ını taşır. Bütün kayıtlar UTF-8 JSON'da `sort_keys=True`, separators `(',', ':')`, whitespace/Unicode normalization/coercion olmadan serialize edilir; SHA-256 lowercase hex digest alınır. `permission_registry_version` her permission satırında exact ve tek olmalı; `tenant_policy_version` aynı tenant satırından gelmelidir. Reference yukarıdaki exact alanlardan üretilir ve DTO constructor tarafından biçimsel olarak çapraz doğrulanır.

#### 16.1.2 Repository çözümleme sözleşmesi

Tek bağlayıcı metot `resolve_principal_and_membership(...)`'dir. Tüm string ve datetime girdileri query çalışmadan önce exact canonical kurallarla doğrulanır. HUMAN çağrısında `expected_service_client_id=None`; SERVICE çağrısında canonical non-empty client ID zorunludur ve ACTIVE binding'in `service_client_id` değeriyle exact eşleşir.

Repository tek tutarlı snapshot içinde sırasıyla exact `(issuer,subject)` binding'i, bağlı principal'ı, exact `tenant_key` tenant'ını, aynı internal tenant/principal membership'ini, membership-role ve role satırlarını okur. Principal kind, tüm status/validity/revocation alanları, client binding, version'lar ve tenant ilişkisi bu snapshot'tan doğrulanır. Kısmi row sonucu veya farklı transaction'lardan birleştirilmiş identity kabul edilmez.

Başarı çıktısı yalnız `VerifiedLocalIdentity`'dir. Beklenen domain/identity başarısızlıkları aşağıdaki kapalı `IdentityResolutionErrorCode` taşıyan immutable `IdentityResolutionError` exception'ı ile döner. Exception yalnız `code`, `retryable`, `correlation_id` ve safe sabit public olmayan mesaj taşır; SQL text, row value, issuer/subject, database exception veya stack detail taşımaz. Programmer error dışında başka exception repository sınırını geçemez.

#### 16.1.3 Kapalı identity resolution taxonomy

Exception modeli bağlayıcı v1 kararıdır; result-envelope kullanılmaz. Enum kapalıdır ve HTTP kodu taşımaz:

```python
class IdentityResolutionErrorCode(str, Enum):
    IDENTITY_NOT_FOUND = "IDENTITY_NOT_FOUND"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    PRINCIPAL_KIND_MISMATCH = "PRINCIPAL_KIND_MISMATCH"
    TENANT_INACTIVE = "TENANT_INACTIVE"
    PRINCIPAL_INACTIVE = "PRINCIPAL_INACTIVE"
    SUBJECT_BINDING_INACTIVE = "SUBJECT_BINDING_INACTIVE"
    MEMBERSHIP_NOT_FOUND = "MEMBERSHIP_NOT_FOUND"
    MEMBERSHIP_INACTIVE = "MEMBERSHIP_INACTIVE"
    MEMBERSHIP_NOT_YET_VALID = "MEMBERSHIP_NOT_YET_VALID"
    MEMBERSHIP_EXPIRED = "MEMBERSHIP_EXPIRED"
    SERVICE_SAFE_ROLE_NOT_FOUND = "SERVICE_SAFE_ROLE_NOT_FOUND"
    SERVICE_ROLE_PERMISSION_INVALID = "SERVICE_ROLE_PERMISSION_INVALID"
    TOKEN_REVOKED_BY_PRINCIPAL = "TOKEN_REVOKED_BY_PRINCIPAL"
    TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY = "TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY"
    NONCANONICAL_IDENTITY_INPUT = "NONCANONICAL_IDENTITY_INPUT"
    DATA_INTEGRITY_VIOLATION = "DATA_INTEGRITY_VIOLATION"
    IDENTITY_STORE_UNAVAILABLE = "IDENTITY_STORE_UNAVAILABLE"
    IDENTITY_STORE_TIMEOUT = "IDENTITY_STORE_TIMEOUT"

@dataclass(frozen=True, repr=False, init=False, eq=False)
class IdentityResolutionError(Exception):
    code: IdentityResolutionErrorCode
    safe_message: str
    retryable: bool
    audit_event: str
    metric_name: str
    correlation_id: str | None

    def __init__(
        self, code: IdentityResolutionErrorCode,
        *, correlation_id: str | None = None,
    ) -> None: ...

    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
```

Constructor yalnız gerçek `IdentityResolutionErrorCode` kabul eder; string/unknown code coercion kesin reddedilir. `safe_message`, `retryable`, `audit_event` ve `metric_name` caller tarafından verilemez, aşağıdaki immutable exhaustive metadata registry'sinden türetilir; `Exception.args` yalnız bu safe message'ı içerir. Business alanları `object.__setattr__` ile yalnız constructor içinde bir kez kurulur ve sonrasında değiştirilemez. Python runtime'ın traceback/context/cause alanları business contract'a dahil değildir ve boundary serialization'a alınmaz.

`__str__` yalnız `safe_message` döndürür. `__repr__`, yalnız `IdentityResolutionError(code=<ENUM>, retryable=<bool>, correlation_id=<safe-or-None>)` biçimindedir. Equality/hash yalnız `(code, correlation_id)` üzerinden deterministiktir; raw cause veya traceback dahil edilmez. Internal adapter gerekirse `raise ... from exc` kullanabilir, fakat cause yalnız internal debug/logging sınırında redacted structured telemetry'ye gider; API/router cause, SQLAlchemy/PostgreSQL message, SQL statement, table/column, DSN, token, claim, issuer/subject veya PII okuyamaz ve serialize edemez.

| Enum / exact string | Fail-closed sonuç | Retryable | Audit olayı | Metric | Externally distinguishable / HTTP sahibi | Safe message template ve redaction |
|---|---|---:|---|---|---|---|
| `IDENTITY_NOT_FOUND` | identity yok | Hayır | `IDENTITY_RESOLUTION_REJECTED` | `security.identity.not_found` | Hayır; 401/404 sonraki boundary | `Identity could not be resolved.`; issuer/subject yok |
| `TENANT_NOT_FOUND` | tenant yok | Hayır | `IDENTITY_RESOLUTION_REJECTED` | `security.identity.tenant_not_found` | Hayır; sonraki boundary | `Identity could not be resolved.`; tenant yok |
| `TENANT_MISMATCH` | cross-tenant ret | Hayır | `CROSS_TENANT_IDENTITY_REJECTED` | `security.identity.tenant_mismatch` | Hayır; existence hiding sonraki boundary | `Identity scope is invalid.`; tenant değerleri yok |
| `PRINCIPAL_KIND_MISMATCH` | profil ret | Hayır | `IDENTITY_PROFILE_REJECTED` | `security.identity.kind_mismatch` | Hayır; sonraki boundary | `Identity profile is invalid.`; subject/client yok |
| `TENANT_INACTIVE` | identity kullanılamaz | Hayır | `IDENTITY_STATE_REJECTED` | `security.identity.tenant_inactive` | Hayır; sonraki boundary | `Identity is not active.`; tenant yok |
| `PRINCIPAL_INACTIVE` | identity kullanılamaz | Hayır | `IDENTITY_STATE_REJECTED` | `security.identity.principal_inactive` | Hayır; sonraki boundary | `Identity is not active.`; principal yok |
| `SUBJECT_BINDING_INACTIVE` | binding kullanılamaz | Hayır | `IDENTITY_STATE_REJECTED` | `security.identity.binding_inactive` | Hayır; sonraki boundary | `Identity is not active.`; binding/subject yok |
| `MEMBERSHIP_NOT_FOUND` | tenant grant yok | Hayır | `IDENTITY_MEMBERSHIP_REJECTED` | `security.identity.membership_not_found` | Hayır; sonraki boundary | `Identity membership is invalid.`; membership/tenant yok |
| `MEMBERSHIP_INACTIVE` | membership kullanılamaz | Hayır | `IDENTITY_MEMBERSHIP_REJECTED` | `security.identity.membership_inactive` | Hayır; sonraki boundary | `Identity membership is invalid.`; membership yok |
| `MEMBERSHIP_NOT_YET_VALID` | erken kullanım ret | Hayır | `IDENTITY_MEMBERSHIP_REJECTED` | `security.identity.membership_not_yet_valid` | Hayır; sonraki boundary | `Identity membership is invalid.`; zaman/ID yok |
| `MEMBERSHIP_EXPIRED` | süresi geçmiş | Hayır | `IDENTITY_MEMBERSHIP_REJECTED` | `security.identity.membership_expired` | Hayır; sonraki boundary | `Identity membership is invalid.`; zaman/ID yok |
| `SERVICE_SAFE_ROLE_NOT_FOUND` | service-safe rol yok | Hayır | `SERVICE_IDENTITY_REJECTED` | `security.identity.service_role_not_found` | Hayır; sonraki boundary | `Service identity grant is invalid.`; role/membership yok |
| `SERVICE_ROLE_PERMISSION_INVALID` | SERVICE rolünde human-only permission | Hayır | `SERVICE_IDENTITY_REJECTED` | `security.identity.service_role_invalid` | Hayır; sonraki boundary | `Service identity grant is invalid.`; role/permission yok |
| `TOKEN_REVOKED_BY_PRINCIPAL` | token ret | Hayır | `REVOKED_TOKEN_REJECTED` | `security.identity.token_principal_revoked` | Hayır; 401 sonraki authentication boundary | `Identity token is not valid.`; token/zaman/principal yok |
| `TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY` | token ret | Hayır | `IDENTITY_VALIDITY_REJECTED` | `security.identity.token_before_validity` | Hayır; sonraki boundary | `Identity token is not valid.`; token/zaman yok |
| `NONCANONICAL_IDENTITY_INPUT` | query başlamaz | Hayır | `IDENTITY_INPUT_REJECTED` | `security.identity.input_invalid` | Hayır; safe 401 sonraki authentication boundary | `Identity input is invalid.`; raw input yok |
| `DATA_INTEGRITY_VIOLATION` | identity üretilmez | Hayır | `IDENTITY_INTEGRITY_FAILURE` | `security.identity.integrity_failure` | Hayır; safe 500 sonraki integration boundary | `Identity state is invalid.`; row/SQL yok |
| `IDENTITY_STORE_UNAVAILABLE` | stale fallback yok | Evet | `IDENTITY_STORE_FAILURE` | `security.identity.store_unavailable` | Hayır; 503 sonraki integration boundary | `Identity service is unavailable.`; DB/provider detail yok |
| `IDENTITY_STORE_TIMEOUT` | stale fallback yok | Evet | `IDENTITY_STORE_FAILURE` | `security.identity.store_timeout` | Hayır; 503 sonraki integration boundary | `Identity service is unavailable.`; timeout/SQL detail yok |

**Kategori sayısı: 19.** Enum değerleri ve tablo birebirdir; registry completeness testi enum eksik/fazla metadata satırını startup/test invariant breach olarak reddeder. Membership revocation mevcut durable modelde `MEMBERSHIP_INACTIVE` ile temsil edilir; ulaşılamayan ikinci bir token-revocation kategorisi tutulmaz. Not-found, inactive, revoked, invalid ve cross-tenant kategorileri internal olarak operasyon/audit ayrımı için korunur; API caller'ına kategorik ayrım olarak taşınmaz. Authentication boundary 401, resource authorization boundary 403/404 existence hiding ve integration boundary 500/503 mapping'inin tek sahibidir. Adım 9 tek başına HTTP kararı vermez.

#### 16.1.4 HUMAN / SERVICE resolution decision table

| Profil | Token profili | Authoritative local satırlar | Binding ve tenant ilişkisi | Grant gereksinimi | Başarı alanları | Fail kategorileri |
|---|---|---|---|---|---|---|
| HUMAN | HUMAN audience + expected HUMAN; client ID yok | ACTIVE binding → HUMAN principal; ACTIVE tenant; ACTIVE membership | exact issuer/subject; membership `(tenant.id,principal.id)` | membership current-time validity; en az bir active HUMAN-safe rol; role set normalized | membership ID/version dolu; kind HUMAN; SERVICE-only rol yok | identity/tenant/kind/binding/membership/validity/principal-token veya integrity kodları |
| SERVICE | SERVICE audience + expected SERVICE + exact client ID | ACTIVE service binding → SERVICE principal; ACTIVE tenant; ACTIVE membership; active service-safe role set | exact issuer/subject/client ID; membership ve roller aynı tenant | membership current-time validity + en az bir rol; her permission `service_allowed=true`; SERVICE_OPERATOR opsiyonel default | membership ID/version dolu; kind SERVICE; normalized service-safe roles | HUMAN kodlarına ek `SERVICE_SAFE_ROLE_NOT_FOUND`/`SERVICE_ROLE_PERMISSION_INVALID` |

Her iki profilde tenant mismatch kesin `TENANT_MISMATCH`; token profile ile local principal kind uyuşmazlığı `PRINCIPAL_KIND_MISMATCH`; binding/principal/tenant/membership revocation fail-closed'dur. Ayrı service-grant tablosu, synthetic grant UUID'si veya ikinci grant source of truth yaratılmaz.

#### 16.1.5 Exact validation ve error precedence

Repository aşağıdaki 15 basamağı değişmez sırayla uygular. Bir basamak başarısız olduğunda exception üretilir ve sonraki basamakların hiçbiri çalışmaz. Her satırdaki audit/metric taxonomy metadata registry'sinden alınır; raw değerler redacted kalır. PostgreSQL timeout/unavailable herhangi bir DB basamağında oluşursa mevcut business değerlendirmesini tamamlamaya çalışmadan sırasıyla `IDENTITY_STORE_TIMEOUT`/`IDENTITY_STORE_UNAVAILABLE` üretilir. Beklenen tekil/FK/tenant ilişkisini bozan persisted state, bulunduğu ilk basamakta business not-found kodu yerine `DATA_INTEGRITY_VIOLATION` üretir.

| # | Kontrol | Başarısızlık kodu / tek anlamlı karar | Sonraki kontrol | Audit / metric | Retryable ve redaction |
|---:|---|---|---|---|---|
| 1 | issuer, subject, tenant_key, client/correlation/request ve UTC datetime canonicality | `NONCANONICAL_IDENTITY_INPUT` | Çalışmaz | `IDENTITY_INPUT_REJECTED` / `security.identity.input_invalid` | Hayır; raw input yok |
| 2 | exact tenant_key resolution | satır yoksa `TENANT_NOT_FOUND`; duplicate/UUID-key bozukluğu integrity | Çalışmaz | taxonomy metadata | Hayır; tenant yok |
| 3 | exact unique issuer+subject binding resolution | satır yoksa `IDENTITY_NOT_FOUND`; duplicate persisted satır integrity | Çalışmaz | taxonomy metadata | Hayır; issuer/subject yok |
| 4 | binding FK'sinden principal resolution | FK target yoksa `DATA_INTEGRITY_VIOLATION` | Çalışmaz | taxonomy metadata | Hayır; IDs/row yok |
| 5 | expected token profile/client ile local principal kind | mismatch `PRINCIPAL_KIND_MISMATCH`; SERVICE client mismatch aynı kod | Çalışmaz | taxonomy metadata | Hayır; subject/client yok |
| 6 | tenant status | ACTIVE değilse `TENANT_INACTIVE` | Çalışmaz | taxonomy metadata | Hayır; tenant yok |
| 7 | principal status | ACTIVE değilse `PRINCIPAL_INACTIVE`; eski token ayrıca değerlendirilmez | Çalışmaz | taxonomy metadata | Hayır; principal yok |
| 8 | binding status | mevcut fakat ACTIVE değilse `SUBJECT_BINDING_INACTIVE` | Çalışmaz | taxonomy metadata | Hayır; binding yok |
| 9 | tenant/binding/principal relational integrity | principal yalnız başka tenant membership'lerine sahipse `TENANT_MISMATCH`; impossible FK/duplicate/cross-tenant composite state `DATA_INTEGRITY_VIOLATION` | Çalışmaz | taxonomy metadata | Hayır; relation values yok |
| 10 | exact `(tenant.id,principal.id)` HUMAN/SERVICE membership | principal'ın hiçbir membership'i yoksa veya target tenant membership'i yok ve başka tenant membership'i de yoksa `MEMBERSHIP_NOT_FOUND` | Çalışmaz | taxonomy metadata | Hayır; membership yok |
| 11 | membership status | REVOKED ise `MEMBERSHIP_INACTIVE`, SUSPENDED ise aynı; token revocation kodu ayrıca değerlendirilmez | Çalışmaz | taxonomy metadata | Hayır; status/ID yok |
| 12 | membership current-time validity | `now < valid_from` → `MEMBERSHIP_NOT_YET_VALID`; `now > valid_until` → `MEMBERSHIP_EXPIRED` | Çalışmaz | taxonomy metadata | Hayır; timestamps yok |
| 13 | active role assignment, role/permission kind safety ve proof üretimi | SERVICE role yok → `SERVICE_SAFE_ROLE_NOT_FOUND`; herhangi SERVICE rolünde `service_allowed=false` → `SERVICE_ROLE_PERMISSION_INVALID`; HUMAN'da active HUMAN-safe rol yok, SERVICE-only/`human_allowed=false` permission, stale registry/version/digest veya impossible role FK/tenant state → `DATA_INTEGRITY_VIOLATION` | Çalışmaz | taxonomy metadata | Hayır; role/permission yok |
| 14 | principal token ve membership issuance boundaries | active principal için eski token → `TOKEN_REVOKED_BY_PRINCIPAL`; membership valid_from öncesi token → `TOKEN_ISSUED_BEFORE_VALIDITY_BOUNDARY`. Membership revoke zaten Basamak 11'de `MEMBERSHIP_INACTIVE` olur | Çalışmaz | taxonomy metadata | Hayır; token/time yok |
| 15 | `VerifiedLocalIdentity` constructor/cross-field invariant'ları | herhangi ihlal `DATA_INTEGRITY_VIOLATION` | DTO dönmez | `IDENTITY_INTEGRITY_FAILURE` / `security.identity.integrity_failure` | Hayır; DTO/raw state yok |

Çakışma kararları bağlayıcıdır: unknown issuer+subject `IDENTITY_NOT_FOUND`; bulunan inactive binding `SUBJECT_BINDING_INACTIVE`; yanlış tenant claim ile başka tenant membership'i `TENANT_MISMATCH`; hiç membership yok `MEMBERSHIP_NOT_FOUND`; inactive principal eski token'dan önce `PRINCIPAL_INACTIVE`; inactive membership eski token'dan önce `MEMBERSHIP_INACTIVE`; revocation kodları yalnız ilgili entity önceki status/validity basamaklarında ACTIVE/geçerli kaldığında üretilebilir. Inactive binding + missing membership sonucunda binding kodu, tenant mismatch + missing target membership sonucunda mismatch kodu kazanır. Beklenen FK/unique invariant'ını ihlal eden “binding var, principal row yok” gibi state her zaman `DATA_INTEGRITY_VIOLATION`'dır.

#### 16.1.6 PostgreSQL snapshot, outage ve transaction semantiği

- Adapter SQLAlchemy `session_factory` alır; framework bağımsız port veya DTO SQLAlchemy import etmez.
- Her resolve çağrısı tek kısa `READ ONLY, REPEATABLE READ` PostgreSQL transaction'ı açar. Bütün identity join/role okumaları aynı snapshot'a aittir; request transaction'ına veya 5.0B persistence transaction'ına katılmaz.
- Security DB statement/connection-pool acquisition timeout'u config kaynaklı, pozitif ve en çok 3 saniyedir; önerilen production varsayılanı 2 saniyedir. Pool exhaustion `IDENTITY_STORE_TIMEOUT`, bağlantı/provider kaybı `IDENTITY_STORE_UNAVAILABLE` olur.
- Repository retry yapmaz. Retry kararı yalnız üst integration katmanındadır; aynı request içinde sınırsız veya otomatik retry yasaktır.
- DB timeout/unavailable durumunda stale `VerifiedLocalIdentity` kullanılmaz. Eksik join, duplicate authoritative binding, tenant-key/UUID uyuşmazlığı, invalid version/status veya kısmi state `DATA_INTEGRITY_VIOLATION` üretir.
- Repository security audit sink'e transaction içinden yazmaz. Safe error code/correlation üst authentication composition'a verilir; taxonomy tablosundaki required audit orada yazılır. Audit sink outage kimliği geçerli yapmaz ve DB hatasını maskemez; required audit politikası ayrıca fail-closed uygulanır.

#### 16.1.7 Adım 9 sınırı ve kapanış kararı

Adım 9 yalnız internal DTO/port ve authoritative identity repository adapter'ını kapsar. Yeni migration gerekmez; E1/E2 schema ve modelleri yeterlidir, model/schema değişikliği beklenmez. 5.0A–5.0D public contract etkisi yoktur. Permission karar motoru Adım 10'a, değişmemiş 5.0C `AuthorizationPort` adapter'ı Adım 11'e, request-bound provider Adım 12'ye ve router/API entegrasyonu Adım 13/14'e aittir. Bu alt aşamada bunların hiçbiri öne çekilmez.

### 16.2 Bootstrap trust root

Production bootstrap yalnız composition root'ta bind edilen private administrative control-plane adapter'ından gelir. v1 trust profile:

- mutual TLS;
- pinned administrative CA/trust bundle;
- allowlisted workload/SPIFFE-like identity exact match;
- replay-protected signed bootstrap envelope;
- public API router'a kayıt yok;
- CLI, application pod shell'i veya manual SQL authoritative provisioning kanalı değildir.

```python
class BootstrapTrustPort(Protocol):
    def verify_bootstrap_authority(
        self, envelope: BootstrapEnvelope, *, now: datetime,
    ) -> BootstrapAuthority: ...

    def is_bootstrap_open(self) -> bool: ...

    def verify_platform_provisioning_authority(
        self, envelope: ProvisioningAuthorityEnvelope, *, now: datetime,
    ) -> PlatformProvisioningAuthority: ...
```

İlk bootstrap yalnız security state boşken bir tenant, bir HUMAN principal, onun subject binding'i, ACTIVE membership'i ve TENANT_ADMIN role assignment'ını tek transaction'da oluşturabilir. Başarılı bootstrap sonrası immutable `bootstrap_closed_at` state'i oluşur; bootstrap authority normal tenant yönetimi için kullanılamaz. Re-open yalnız ayrı break-glass operasyonu ve audit ile future operations policy konusudur; v1 runtime'da yoktur.

Bootstrap kapandıktan sonra yeni tenant, global principal veya external subject binding yaşam döngüsünün tek güven kökü `PlatformProvisioningAuthority`'dir. Bu authority aynı private mTLS control-plane'den gelir fakat ayrı workload allowlist'i ve exact `platform-provisioning/v1` signed envelope audience'ı ile doğrulanır; tenant rolü değildir ve HTTP bearer principal'ına dönüştürülmez. `create_tenant`, `create_principal`, `revoke_principal` ve `rotate_subject_binding` yalnız bu authority'yi kabul eder. `create_tenant` yeni tenant + ilk HUMAN principal + subject binding + membership + TENANT_ADMIN assignment'ını atomik oluşturur; boş tenant yaratmaz. Tenant yöneticisi global principal veya başka tenant yaratamaz/revoke edemez.

### 16.3 IdentityProvisioningPort

```python
class IdentityProvisioningPort(Protocol):
    def create_tenant(self, command: CreateTenantCommand) -> ProvisioningOutcome: ...
    def create_principal(self, command: CreatePrincipalCommand) -> ProvisioningOutcome: ...
    def create_membership(self, command: CreateMembershipCommand) -> ProvisioningOutcome: ...
    def assign_role(self, command: AssignRoleCommand) -> ProvisioningOutcome: ...
    def revoke_membership(self, command: RevokeMembershipCommand) -> ProvisioningOutcome: ...
    def revoke_principal(self, command: RevokePrincipalCommand) -> ProvisioningOutcome: ...
    def rotate_subject_binding(self, command: RotateSubjectBindingCommand) -> ProvisioningOutcome: ...
    def get_provisioning_status(
        self, authority_id: str, idempotency_key: str,
    ) -> ProvisioningOutcome | None: ...
```

Tüm mutation command'ları immutable ve en az şunları taşır:

- trusted `authority`;
- 16–128 ASCII `idempotency_key`;
- timezone-aware `requested_at`;
- correlation ID;
- operation-specific exact IDs/tenant_key/roles;
- canonical payload schema version.

Revoke command'ları ayrıca `effective_at` ve closed reason code taşır. v1 scheduled revocation yoktur: `effective_at <= now+60s` olmalı ve commit edildiği anda authorization read'lerinde etkili olur. Future effective time reddedilir.

#### 16.3.1 Trusted custom role administration

Public/self-service custom-role API ve UI 5.0E kapsam dışıdır. Custom `security_roles` ve `security_role_permissions` kayıtları yine authoritative PostgreSQL state'tir; production'da manual SQL yönetim kanalı değildir. Identity provisioning portunu büyütmek yerine ayrı framework-bağımsız internal port seçilmiştir:

```python
class RoleAdministrationOperation(str, Enum):
    CREATE_CUSTOM_ROLE = "CREATE_CUSTOM_ROLE"
    REPLACE_CUSTOM_ROLE_PERMISSIONS = "REPLACE_CUSTOM_ROLE_PERMISSIONS"
    DISABLE_CUSTOM_ROLE = "DISABLE_CUSTOM_ROLE"

@dataclass(frozen=True)
class RoleAdministrationCommand:
    operation: RoleAdministrationOperation
    authority: ProvisioningAuthority
    tenant_key: str
    role_id: UUID
    role_code: str
    permission_codes: tuple[str, ...]
    expected_role_version: int | None
    idempotency_key: str
    requested_at: datetime
    correlation_id: str
    payload_schema_version: str = "role-admin/1"

class RoleAdministrationPort(Protocol):
    def create_custom_role(
        self, command: RoleAdministrationCommand,
    ) -> ProvisioningOutcome: ...
    def replace_custom_role_permissions(
        self, command: RoleAdministrationCommand,
    ) -> ProvisioningOutcome: ...
    def disable_custom_role(
        self, command: RoleAdministrationCommand,
    ) -> ProvisioningOutcome: ...
    def get_role_operation_status(
        self, authority_id: str, idempotency_key: str,
    ) -> ProvisioningOutcome | None: ...
```

Yalnız active HUMAN tenant authority + PHISHING_RESISTANT strength + `security.role.assign` aynı tenant üzerinde bu portu çağırabilir; SERVICE ve platform authority normal tenant rol kataloğunu yönetemez. Command role/permission tuple'ı canonical ASCII, non-empty, unique ve lexicographically ordered olmalıdır. Create için `expected_role_version=None`; replace/disable için pozitif exact current version zorunludur. Built-in role code'ları bu portla oluşturulamaz/değiştirilemez/devre dışı bırakılamaz.

Her mutation required pre-transaction audit, existing provisioning operation ledger'ında authority+idempotency-key digest kuralı ve tek PostgreSQL transaction kullanır. Create role version `1` üretir; permission replacement ve disable exact CAS sonrası `role.version += 1`; üç işlem de `tenant.policy_version += 1` yapar. Existing `assign_role`/assignment removal da `membership.version += 1` ve `tenant.policy_version += 1` yapmak zorundadır. Aynı key+payload idempotent success, farklı payload conflict; audit veya transaction failure state bırakmaz.

Role/permission veya membership-role değişikliği canonical role-set bytes'ını ve/veya reference version'larını değiştirir. Positive identity cache olmadığı için değişiklik commit'inden sonraki ilk resolution yeni digest/reference üretir. Active SERVICE principal'ın custom rolüne `service_allowed=false` permission eklenirse sonraki resolution `SERVICE_ROLE_PERMISSION_INVALID` ile fail-closed olur. Bu internal administration read-path'in authoritative fixture/state üretmesini sağlar; public role-management endpoint'i eklemez ve yeni schema gerektirmez.

### 16.4 Provisioning authorization

- Bootstrap authority yalnız one-time bootstrap aggregate'ını oluşturabilir.
- Platform provisioning authority yalnız `create_tenant`, `create_principal`, `revoke_principal` ve `rotate_subject_binding` işlemlerini yapabilir; tenant-scoped rol değildir.
- Normal tenant provisioning authority active HUMAN principal, PHISHING_RESISTANT strength ve current tenant membership gerektirir.
- membership create/revoke: aynı tenant'ta `security.membership.manage`;
- role assignment: aynı tenant'ta ayrıca `security.role.assign`;
- normal tenant authority tenant/principal oluşturamaz, global principal revoke edemez ve subject binding değiştiremez;
- platform authority membership/role mutation'ını ancak `create_tenant` atomik bootstrap aggregate'ının parçası olarak yapabilir; sonradan tenant yönetimini bypass edemez;
- normal tenant authority başka tenant'a mutation yapamaz;
- SERVICE principal provisioning yapamaz.

Self-service/admin HTTP API bu milestone'da yoktur; trusted administrative control plane aynı framework-independent portu çağırır.

### 16.5 Idempotency ve concurrency

Canonical command bytes SHA-256 digest'i `security_provisioning_operations` içinde authority+key ile unique tutulur:

- aynı key + aynı digest → terminal projection idempotent success;
- aynı key + farklı digest → `PROVISIONING_IDEMPOTENCY_CONFLICT`;
- concurrent same-key insert → unique constraint tek winner; loser row'u reload edip digest karşılaştırır;
- duplicate `(issuer,subject)` başka principal'a bağlanamaz;
- subject rotation yeni binding unique değilse tüm transaction rollback;
- role/membership cross-tenant constraint ihlali fail-closed;
- partial create/assign/revoke yoktur.

### 16.6 Transaction ve required audit politikası

1. Bootstrap/normal authority doğrulanır.
2. Canonical command digest hesaplanır ve idempotency preflight yapılır.
3. Required `PROVISIONING_MUTATION_AUTHORIZED` audit event'i operation kind, authority ID, target IDs, reason, correlation ve payload digest ile durable sink'e yazılır.
4. Audit receipt alınamazsa DB transaction **başlamaz**, `SECURITY_AUDIT_FAILED` döner.
5. Tek PostgreSQL transaction idempotency row + domain mutation + receipt ID'yi yazar ve commit eder.
6. Commit başarısızsa state yoktur; `PROVISIONING_COMMIT_FAILED` best-effort operational event'i üretilir.
7. Commit sonrası `PROVISIONING_MUTATION_COMMITTED` operational/audit event'i denenir; başarısızlığı committed state'i geri almaz, required pre-commit receipt sayesinde mutation audit bağı korunur ve mandatory alert üretir.

Bu event'ler state rebuild kaynağı değildir; event sourcing kullanılmaz.

### 16.7 Lifecycle kuralları

- Revoke principal `tokens_valid_after=effective_at`, status DISABLED ve reason'ı atomik yazar; tüm memberships effective olarak deny olur.
- Revoke membership yalnız ilgili tenant grant'ini kapatır; positive cache olmadığı için commit sonrası ilk authorization read'inde etkilidir.
- Subject rotation eski binding'i REVOKED, yenisini ACTIVE yapar; external subject hiçbir zaman başka principal'a reassigned edilmez.
- Hard delete yoktur. Reactivation v1 kapsam dışıdır; yeni explicit membership/binding operation gerektirir.
- Role assignment permission escalation check'i target role permission'larının authority'nin assignable set'ini aşmasını reddeder; TENANT_ADMIN dahi bootstrap-only yetki yaratamaz.
- Role assignment, SERVICE principal için rolün bütün permission'larında `service_allowed=true`, HUMAN principal için bütün permission'larda `human_allowed=true` olmasını transaction içinde doğrular; tek uygunsuz permission tüm assignment'ı rollback eder. Repository aynı kuralı her resolution'da tekrar fail-closed doğrular. SERVICE_OPERATOR zorunlu değildir ve service-safe custom role aynı authoritative tablolarda temsil edilir.

SQLAlchemy yalnız repository adapter'larında; FastAPI yalnız bearer/dependency composition'da bulunur. JWT ve provisioning core contract'larında FastAPI, Pydantic veya SQLAlchemy yoktur.

---

## 17. Request-Scoped Composition

5.0D `TrustedAuthenticationContextProviderPort.current_context()` imzası değişmez.

### 17.1 Adım 12 exact internal contract

Adım 12 iki donmuş public sınırı adapter ile bağlar; ikisini de genişletmez: 5.0D
`AuthenticationContext`/`TrustedAuthenticationContextProviderPort` ve Adım 11
`TrustedAuthorizationContextProviderPort`. Frozen 5.0D DTO'da bulunmayan principal-kind ve SERVICE
client proof'u raw claim'den tekrar okunmaz. Strict JWT verifier'ın `VerifiedJwt` çıktısı ile Adım 9'un
aynı token için ürettiği `VerifiedLocalIdentity` sonucu exact eşleştirilerek aşağıdaki internal,
immutable request binding oluşturulur:

```python
@dataclass(frozen=True, repr=False)
class TrustedRequestIdentityProfile:
    principal_kind: IdentityKind
    service_client_id: str | None
    request_id: str

@dataclass(frozen=True, repr=False)
class RequestAuthorizationTarget:
    checkpoint: AuthorizationCheckpoint
    scope_type: PolicyScopeType
    resource_id: UUID | str
    tenant_key: str
    company_id: UUID | None
    period_id: UUID | None
    expected_resource_version: str | None

@dataclass(frozen=True, repr=False)
class RequestAuthorizationPlan:
    targets: tuple[RequestAuthorizationTarget, ...]

class RequestBoundAuthenticationContextProvider(TrustedAuthenticationContextProviderPort):
    def current_context(self) -> AuthenticationContext: ...
    def trusted_identity_profile(self) -> TrustedRequestIdentityProfile: ...
    def readiness_check(self, deadline: datetime) -> bool: ...

class RequestBoundTrustedAuthorizationContextProvider(TrustedAuthorizationContextProviderPort):
    def resolve_context(
        self, *, checkpoint: AuthorizationCheckpoint,
        application_scope: ApplicationScopeDTO,
        audit_context: ApplicationAuditContextDTO,
    ) -> TrustedAuthorizationContext: ...
    def readiness_check(self, deadline: datetime) -> bool: ...
```

`RequestBoundAuthenticationContextProvider` yalnız `VerifiedJwt + VerifiedLocalIdentity + safe
correlation/request ID + ApiRuntimeProfile` factory'siyle kurulur. Factory issuer, subject, tenant,
principal kind, token time ve active membership proof'unu exact karşılaştırır. HUMAN için
`service_client_id=None`, `oidc_bearer_jwt` ve BASIC/STRONG/PHISHING_RESISTANT; SERVICE için canonical
non-null verified client ID, `oauth2_client_credentials_jwt` ve frozen 5.0D `STRONG` üretilir.
`authorization_context_reference`, local identity'nin membership UUID/version ve tenant policy
version değerlerinden üretilir. Raw bearer, raw claim map, JOSE header, email/display-name, IP veya
identity header bu DTO/adapter'lara giremez.

`RequestAuthorizationPlan`, endpoint semantic'inin sonraki Adım 13 composition'ında sağlayacağı
trusted resource intent'tir; HTTP request/body/header değildir. Her checkpoint exact bir target'a
sahiptir, duplicate checkpoint ve plan dışı checkpoint fail-closed'dur. Provider target'ı kendi
trusted correlation ve checkpoint-resolution zamanı ile `ResourceSecurityReference`'a çevirir.
START/RESUME/RETRY ve bunların PRE_PERSIST eşleri `COMPANY_PERIOD`; RESUME_SOURCE eşleri source
`ANALYSIS_RUN`; CANCEL ve tek-run READ hedef `ANALYSIS_RUN` kullanır. Unscoped fallback, caller
tarafından pre-resolved scope ve resource existence probe yoktur.

### 17.2 Request lifecycle, freshness ve isolation

- Provider instance'ı tek request'e aittir; process-global mutable identity, thread-local,
  `ContextVar`, stale fallback veya cross-request cache yoktur.
- Underlying request-bound authentication provider'ın ilk sonucu request identity snapshot'ıdır.
  Sonraki checkpoint okumaları byte/value-equivalent olmak zorundadır; değişim integrity failure'dır.
- Aynı request + aynı checkpoint ilk çözümlemede immutable olarak cache edilir ve tüm sync/async
  caller'lara aynı DTO instance/value döner. Cache yalnız kapalı 10 checkpoint ile bounded'dır;
  lock yalnız request-local first-materialization yarışını tekilleştirir.
- Farklı checkpoint yeni trusted clock instant'ı alır. Özellikle `PRE_PERSIST_*`, token expiry,
  15 dakikalık max-age ve 60 saniyelik future-skew kurallarını yeniden değerlendirir.
- Missing context → `AUTH_CONTEXT_MISSING`; expired → `AUTH_CONTEXT_EXPIRED`; stale →
  `AUTH_CONTEXT_STALE`; timeout/unavailable → `AUTH_CONTEXT_PROVIDER_UNAVAILABLE`; malformed,
  changed snapshot, plan mismatch veya unknown failure → ilgili INVALID/INTEGRITY code. Hiçbiri grant
  veya stale context üretmez.
- Context tenant'ı application scope tenant'ıyla exact eşleşir. Correlation authority yalnız
  authenticated request context'tir; `ApplicationAuditContextDTO` identity authority değildir.
- Production profile, `is_fake=True`, request-bound olmayan, readiness vermeyen veya required methodu
  eksik authentication/provider binding'ini startup/readiness'te reddeder. TEST explicit fake
  kullanabilir; DEVELOPMENT yalnız explicit local profile'dır.
- Readiness yalnız wiring/dependency availability gösterir; request identity yaratmaz ve identity
  state'i saklamaz. Authentication/JWKS/provider outage false döner; clock/admission dışı best-effort
  observability bu karara dahil değildir.

Bu provider HTTP status üretmez, header parse etmez ve router çağırmaz. Raw `X-User-Id`,
`X-Tenant-Id`, `X-Subject-Id` yasağı mevcut 5.0D boundary'de korunur; Adım 13 yalnız bu request-bound
factory/plan'ı endpoint semantic'ine bağlayacaktır.

FastAPI dependency akışı:

1. Authorization header ve correlation ID alınır.
2. Token doğrulanır.
3. Local principal/membership state çözülür.
4. Authentication audit yazılır.
5. Immutable AuthenticationContext oluşturulur.
6. Request-bound provider bu context ile kurulur.
7. Base `AnalysisApiRuntime`, yalnız bu request için bound provider ile kopyalanır.
8. Mevcut analysis router aynı `current_context()` çağrısını kullanır.

Global runtime'a subject/context yazılmaz. Session veya provider instance'ı request'ler arasında principal state taşımaz.

---

## 18. Legacy Route-Protection Envanteri

### 18.1 Production public/disabled kararı

| Method/path | Production classification | Response |
|---|---|---|
| `GET /health/live` | PUBLIC | `{"status":"live"}`; marka/version/dependency yok |
| `GET /health/ready` | PUBLIC | yalnız `ready: bool`, sabit status; sensitive detail yok |
| `GET /` | DISABLED | generic 404; route production app'te register edilmez |
| `GET /health` | DISABLED | generic 404; route production app'te register edilmez |
| `/docs`, `/redoc`, `/openapi.json` | DISABLED | production default register edilmez |

Başka anonymous endpoint yoktur.

### 18.2 Ortak sınıflandırma sözleşmesi

- `P0`: public health; trusted ingress default 60 request/min/source, application authentication yok.
- `P1`: protected standard; process-local authentication verification admission global 200 concurrent, source başına 20 concurrent; saturation `429` + `Retry-After: 1`. Source key yalnız trusted-proxy config sonrası client address'tir; yoksa yalnız global limit uygulanır.
- `P2`: P1 + mevcut 5.0D global/tenant/subject analysis admission.
- `P3`: P1 + mevcut upload size/file-count limitleri.

Limitler config ile düşürülebilir/yükseltilebilir fakat production'da sıfır/limitsiz olamaz. Process-local rate/admission authorization veya distributed correctness kaynağı değildir.

Protected security failure envelope `SecurityErrorEnvelopeV1`:

```json
{"success":false,"data":null,"error":{"code":"...","category":"...","message":"...","retryable":false,"correlation_id":"..."},"warnings":[],"correlation_id":"..."}
```

Legacy success DTO'ları değişmez; yalnız authentication/authorization/security failure'ları bu common versioned envelope'u kullanır. Analysis route'ları mevcut 5.0D `ApiOutcomeResponseV1` envelope'unu korur.

`WWW-Authenticate` exact:

- missing bearer: `Bearer realm="api"`;
- invalid/expired/revoked bearer: `Bearer realm="api", error="invalid_token"`;
- 403/404/409/429/500/503: header yok.

### 18.3 Gerçek repository envanteri — normative matrix

Kısaltmalar: `SEC`=SecurityErrorEnvelopeV1, `AN`=mevcut analysis envelope; `AUTHZ(X)`=grant/deny required audit; `H404`=cross-tenant/hidden resource 404; tüm protected satırlarda authentication required ve authn success/failure audit zorunludur. Her satırın allowed principal kind ve minimum strength değeri Bölüm 15.2'deki exact permission kaydının H/S ve Min strength sütunlarıdır; birden çok permission varsa principal tüm izinlerin H/S intersection'ında olmalı ve en yüksek minimum strength'i sağlamalıdır. Adapter bu değerleri override edemez. Her protected satırda authentication/JWKS/security DB/authorization outage fail-closed 503'tür; required audit event yazılamazsa handler başlamaz ve 503 döner.

| Method/path | Class | Permission / scope | Hide/deny | Rate | Audit | Envelope / WWW |
|---|---|---|---|---|---|---|
| `GET /health/live` | PUBLIC | none/GLOBAL | none | P0 | none | minimal/no WWW |
| `GET /health/ready` | PUBLIC | none/GLOBAL | sensitive detail hidden | P0 | readiness metric | minimal/no WWW |
| `POST /api/v1/companies` | PROTECTED | `company.create`/context tenant | 403 | P1 | AUTHZ(company.create) | SEC/401 rule |
| `GET /api/v1/companies` | PROTECTED | `company.list`/tenant-filtered | 403 | P1 | AUTHZ(company.list) | SEC/401 rule |
| `GET /api/v1/companies/{company_id}` | PROTECTED | `company.read`/company tenant | H404 | P1 | AUTHZ(company.read) | SEC/401 rule |
| `POST /api/v1/companies/{company_id}/periods` | PROTECTED | `period.create`/company | H404 | P1 | AUTHZ(period.create) | SEC/401 rule |
| `GET /api/v1/companies/{company_id}/periods` | PROTECTED | `period.list`/company | H404 | P1 | AUTHZ(period.list) | SEC/401 rule |
| `GET /api/v1/periods/{period_id}` | PROTECTED | `period.read`/period→company | H404 | P1 | AUTHZ(period.read) | SEC/401 rule |
| `GET /api/v1/periods/{period_id}/documents` | PROTECTED | `document.list`/period→company | H404 | P1 | AUTHZ(document.list) | SEC/401 rule |
| `GET /api/v1/documents/{document_id}` | PROTECTED | `document.read`/document→company | H404 | P1 | AUTHZ(document.read) | SEC/401 rule |
| `GET /api/v1/documents/{document_id}/analyses` | PROTECTED | `analysis_result.list`/document→company | H404 | P1 | AUTHZ(analysis_result.list) | SEC/401 rule |
| `GET /api/v1/analyses/{analysis_id}` | PROTECTED | `analysis_result.read`/result→company | H404 | P1 | AUTHZ(analysis_result.read) | SEC/401 rule |
| `POST /api/v1/periods/{period_id}/trial-balances` | PROTECTED | `trial_balance.upload`/period→company | H404 | P3 | AUTHZ(trial_balance.upload) | SEC/401 rule |
| `POST /api/v1/trial-balance/validate` | PROTECTED | `trial_balance.validate`/tenant | 403 | P3 | AUTHZ(trial_balance.validate) | SEC/401 rule |
| `POST /api/v1/bulk-uploads` | PROTECTED | `bulk_upload.create`/tenant | 403 | P3 | AUTHZ(bulk_upload.create) | SEC/401 rule |
| `GET /api/v1/bulk-uploads/{batch_id}` | PROTECTED | `bulk_upload.read`/batch tenant | H404 | P1 | AUTHZ(bulk_upload.read) | SEC/401 rule |
| `GET /api/v1/bulk-uploads/{batch_id}/items` | PROTECTED | `bulk_upload.read`/batch tenant | H404 | P1 | AUTHZ(bulk_upload.read) | SEC/401 rule |
| `PATCH /api/v1/bulk-uploads/{batch_id}/items/{item_id}` | PROTECTED | `bulk_upload.update`/batch+item FK | H404 | P1 | AUTHZ(bulk_upload.update) | SEC/401 rule |
| `PATCH /api/v1/bulk-uploads/{batch_id}/items` | PROTECTED | `bulk_upload.update`/batch | H404 | P1 | AUTHZ(bulk_upload.update) | SEC/401 rule |
| `POST /api/v1/bulk-uploads/{batch_id}/confirm` | PROTECTED | `bulk_upload.confirm`/batch | H404 | P3 | AUTHZ(bulk_upload.confirm) | SEC/401 rule |
| `POST /api/v1/analysis-runs` | PROTECTED | `analysis.start`/tenant+company+period | permission 403; existing wrong scope 409 | P2 | AUTHZ(analysis.start) | AN/401 rule |
| `POST /api/v1/analysis-runs/{previous_run_id}/resume` | PROTECTED | `analysis.resume` + `analysis.resume_source`/source-target | source H404; target run conflict 409 | P2 | AUTHZ(resume/source) | AN/401 rule |
| `POST /api/v1/analysis-runs/{previous_run_id}/retry` | PROTECTED | `analysis.retry` + source if original RESUME | source H404; target run conflict 409 | P2 | AUTHZ(retry/source) | AN/401 rule |
| `POST /api/v1/analysis-runs/{run_id}/cancel` | PROTECTED | owner `analysis.cancel.own`, non-owner `analysis.cancel.any`/claim | H404 or same-tenant 403 | P1 | AUTHZ(cancel) | AN/401 rule |
| `GET /api/v1/analysis-runs/{run_id}/status` | PROTECTED | `analysis.read` + `analysis.status.read`/claim | H404 | P1 | AUTHZ(status.read) | AN/401 rule |
| `GET /api/v1/analysis-runs/{run_id}/result?include_payloads=false` | PROTECTED | `analysis.read` + `analysis.result.read`/claim | H404 | P1 | AUTHZ(result.read) | AN/401 rule |
| `GET /api/v1/analysis-runs/{run_id}/result?include_payloads=true` | PROTECTED | previous + `analysis.payload.read` + `analysis.result.payload.read` | H404 | P1 | AUTHZ(result.payload.read) | AN/401 rule |
| `GET /api/v1/analysis-runs/{run_id}/executions/{engine_code}?include_payload=false` | PROTECTED | `analysis.read` + `analysis.execution.read`/claim | H404 | P1 | AUTHZ(execution.read) | AN/401 rule |
| `GET /api/v1/analysis-runs/{run_id}/executions/{engine_code}?include_payload=true` | PROTECTED | previous + `analysis.payload.read` + `analysis.execution.payload.read` | H404 | P1 | AUTHZ(execution.payload.read) | AN/401 rule |
| `GET /api/v1/analysis-runs` | PROTECTED | `analysis.read` + `analysis.history.read`/tenant+company+period | 403; wrong company/period H404 | P1 | AUTHZ(history.read) | AN/401 rule |

Cross-tenant generic resource read/write her zaman 404'dür. Mevcut 5.0D idempotency contract'ı nedeniyle aynı analysis `run_id` ile farklı tenant/company/period/subject **write/replay** kesin 409'dur; başka endpoint bu istisnayı kullanamaz.

#### 18.3.1 Adım 13 request security session ve exact sıra

Adım 13, frozen 5.0C `AuthorizationPort`'u genişletmez. Request-bound
`AnalysisRequestSecuritySession`, aynı Adım 11 `LocalAuthorizationPolicyClient` instance'ını sarar;
router initial kararı application çağrısından önce alır ve exact scope+actor+method anahtarıyla yalnız
aynı request içinde cache eder. Application service aynı public methodu çağırdığında aynı immutable
karar döner; ikinci policy evaluation yapılmaz. `revalidate_*` hiçbir zaman cache edilmez ve aynı
Adım 11 instance'ına fresh gider. Endpoint-specific sekiz read action'ı internal
`authorize_registered_action(action_code, scope, actor)` kapısından geçer; bu method public 5.0C
contract değildir ve yalnız compiled 33-action registry'sini kabul eder.

Write sırası exact: header/correlation validation → bearer authentication → trusted request provider
→ scope/subject replay preflight → admission lease → target initial authorization → varsa previous-run
source authorization → trusted input resolution → command mapping → application service (cached initial
decision) → engine → uncached pre-persistence target/source revalidation → persistence → projection →
lease release. Initial deny'da application service, claim veya persistence çağrılmaz. Retry'nin
`original_operation` değeri ne olursa olsun 5.0C previous-run snapshot/reuse kaynağı bulunduğundan
previous run `analysis.resume_source` ile doğrulanır; clean fallback yoktur.

Run read/cancel için router caller query'sinden yalnız canonical company/period scope claim'i kurar;
önce tenant-qualified Adım 10 `ANALYSIS_RUN` resolver authorization'ı çalışır, sonra existing
ownership view yüklenir. Böylece global-ID load cross-tenant existence probe'u olamaz. Status/result/
execution generic `analysis.read` (payload istenirse ayrıca `analysis.payload.read`) ve exact endpoint
action'ının ikisini ister. History `COMPANY_PERIOD` resource type'lı `analysis.history.read` kararını
tek authoritative read guard olarak kullanır; resource-type uyumsuz `analysis.read` evaluation'ı
yapılmaz, fakat frozen read facade guard'ına aynı cached endpoint decision verilir.

HTTP mapping kapalıdır: missing bearer `AUTHENTICATION_REQUIRED`/401 ve
`Bearer realm="api"`; malformed/invalid/expired/revoked `INVALID_TOKEN`/401 ve
`Bearer realm="api", error="invalid_token"`; authentication/identity/policy/audit provider outage
503; durable `RESOURCE_NOT_FOUND` ve hiding-required deny 404; authenticated permission/strength/kind
deny 403; same-run different scope/subject replay 409. Raw decision reason, token, claim, issuer, kid,
role veya exception public envelope'a girmez.

### 18.4 Router registration completeness

Her router `ProtectedRouteDefinition` registry'sinden router-level authentication/admission dependency alır; resource authorization endpoint dependency'sidir. Yalnız exact PUBLIC/DISABLED allowlist istisnadır. Startup/test, FastAPI registered `(method,path)` setini bu tabloyla birebir karşılaştırır. Classification'sız yeni route, duplicate classification veya public allowlist dışı anonymous route production app build/readiness failure'ıdır.

Adım 14 executable registry'si exact **28** kayıttır: 2 PUBLIC health, 18 legacy
PROTECTED ve Adım 13'te korunmuş 8 analysis-run route. Framework'ün deferred
`include_router` kayıtları completeness kontrolünde recursive olarak açılır; yalnız top-level
`app.routes` sayımı geçerli değildir. Legacy router'ların ortak dependency'si request body veya
handler çalışmadan önce raw identity header yasağını, bounded P1 lease'i, request-bound bearer
authentication'ı ve trusted legacy authorization adapter'ını sırasıyla uygular. Production
composition'da adapter `authorize`, `try_acquire`, `release` ve `readiness_check` sözleşmelerinin
tamamını sağlamalı; fake/missing/incomplete binding readiness alamaz.

Legacy authorization adapter'ı exact manifest satırındaki permission ve resource scope'u Adım 9–11
authoritative yoluna projekte eder; tenant-qualified durable resolver lookup, principal-kind,
strength, ownership/subject predicate ve required audit delivery kararları adapter sınırında kalır.
Router SQL veya policy reason yorumlamaz. Lease; authentication, authorization, handler,
cancellation ve exception dahil bütün çıkışlarda `finally` ile release edilir. Closed HTTP mapping:
missing/invalid credential 401, authenticated permission/strength/kind deny 403, Model A hidden
resource 404, local saturation 429 ve authentication/policy/audit outage 503'tür; upstream decision
code veya exception response'a taşınmaz.

### 18.5 Query kuralı

Tenant filter SQL query'nin parçasıdır. Önce global ID ile satır yükleyip sonra Python'da tenant karşılaştırmak yeterli değildir. ID-based cross-tenant kaynak `404` ile gizlenir; list endpoint'i yalnız current tenant satırlarını sayar ve döndürür.

Write path'te tenant caller body/query/header alanından alınmaz. Resource FK zinciri ile context tenant uyuşmuyorsa transaction başlamaz veya rollback edilir.

---

## 19. HTTP Error Semantiği

| Durum | HTTP | Public code/policy |
|---|---:|---|
| Authorization header yok | 401 | `AUTHENTICATION_REQUIRED`; generic `WWW-Authenticate: Bearer` |
| Malformed scheme/JWT/header/claims | 401 | `INVALID_TOKEN`; neden ayrıntısı yok |
| Signature/issuer/audience/algorithm invalid | 401 | `INVALID_TOKEN` |
| Expired/not-yet-valid/revoked token | 401 | `INVALID_TOKEN` |
| Unknown kid, successful refresh sonrası yok | 401 | `INVALID_TOKEN` |
| JWKS/provider timeout veya stale cache refresh failure | 503 | `AUTHENTICATION_PROVIDER_UNAVAILABLE`, retryable |
| Security DB unavailable | 503 | `AUTHENTICATION_PROVIDER_UNAVAILABLE` veya `AUTHORIZATION_PROVIDER_UNAVAILABLE` |
| Authenticated fakat permission/strength yok | 403 | `UNAUTHORIZED` |
| Cross-tenant ID resource | 404 | existence hiding |
| Same run farklı subject/scope replay | 409 | mevcut 5.0D conflict semantiği |
| Required authentication/security audit sink unavailable | 503 | fail-closed |

Public message token parse nedeni, issuer URL, kid, membership, role, SQL veya exception ayrıntısı içermez. Authentication error response token'ı veya claim payload'ını echo etmez.

---

## 20. Security Audit

Authentication audit, 5.0C application-scope `SecurityAuditPort` event'lerini değiştirmez. Ayrı authentication-level event envelope aynı durable sink'e adapter ile yazılır.

Required olaylar:

- `AUTHENTICATION_SUCCEEDED`;
- `AUTHENTICATION_FAILED`;
- `TOKEN_EXPIRED`;
- `TOKEN_REVOKED`;
- `UNTRUSTED_ISSUER_REJECTED`;
- `JWT_SIGNATURE_REJECTED`;
- `JWKS_REFRESH_FAILED`;
- `TENANT_MEMBERSHIP_REJECTED`;
- `AUTHORIZATION_GRANTED`;
- `AUTHORIZATION_DENIED`;
- `CROSS_TENANT_ACCESS_REJECTED`;
- `PRINCIPAL_REVOKED`;
- `MEMBERSHIP_REVOKED`.

Audit metadata:

- token'ın kendisini içermez;
- subject için keyed hash veya local principal ID kullanır;
- JTI yalnız keyed hash olarak tutulabilir;
- IP/user-agent yalnız salted/keyed hash olarak taşınır;
- raw claim set, email, document payload veya exception içermez;
- correlation ID zorunludur.

Minimum production retention baseline 365 gündür. Deployment/compliance policy daha uzun süre seçebilir; daha kısa süre readiness/config validation tarafından reddedilir. Audit sink provider seçimi bu invariant'ı değiştirmez.

Authentication success/failure ve authorization decision audit'i yazılamazsa protected use-case başlamaz. Post-terminal persistence audit davranışı mevcut 5.0C warning politikasını korur. Audit event'leri event sourcing değildir.

---

## 21. Sensitive Data ve Logging

- Authorization header hiçbir log/span/error/audit alanına girmez.
- JWT payload debug log'u yasaktır.
- Issuer allowlist dışı value public cevaba yansıtılmaz.
- Subject/email yerine local principal ID veya keyed hash tercih edilir.
- JWKS public key material'i application log'una yazılmaz.
- SQL exception ve policy-decision internal reason public response'a çıkmaz.
- Error metadata yalnız correlation ID ve safe category taşır.
- Secrets yalnız environment/secret manager binding'inden gelir; repository veya migration'a yazılmaz.

---

## 22. Configuration

Production config en az:

- runtime profile;
- issuer profiles;
- exact audiences;
- JWKS URI;
- allowed algorithms/types;
- tenant/claims-version/acr-amr claim mapping;
- JWKS TTL ve HTTP timeout;
- token max lifetime ve clock skew;
- authorization DB timeout;
- durable security-audit sink binding;
- subject/audit hash key secret reference.

Config startup'ta validate edilir. Eksik issuer/audience/JWKS/audit/policy binding, symmetric algorithm, HTTP JWKS URL, limitsiz timeout veya fake adapter production readiness'i kapatır. Silent default issuer veya allow-all permission yoktur.

---

## 23. Readiness ve Outage Politikası

`/health/ready` sensitive detail vermeden aşağıdakileri doğrular:

- issuer registry geçerli ve boş değil;
- her issuer için fresh/refreshable JWKS;
- security PostgreSQL erişilebilir;
- authorization policy registry geçerli;
- durable security-audit sink erişilebilir;
- trusted authentication adapter production-safe;
- clock timezone-aware;
- hiçbir fake/allow-all/no-op required adapter bind edilmemiş.

Observability outage readiness'i tek başına kapatmaz ve business işlemini bloklamaz. Authentication provider/JWKS, security DB, authorization veya required audit outage protected request'i fail-closed durdurur.

---

## 24. Transaction Sınırları

- JWT cryptographic verification DB transaction açmaz.
- Principal/membership/policy read kısa, read-only transaction'dır.
- Legacy resource ownership read scope-qualified kısa transaction'dır.
- Company/bulk batch tenant binding'i ilgili resource write transaction'ıyla atomiktir.
- 5.0C RunScopeClaim short transaction ve 5.0B terminal persistence transaction sınırları değişmez.
- Authorization pre-persistence revalidation ayrı güncel read kullanır.
- Audit sink transaction'ı domain DB transaction'ıyla distributed transaction'a dönüştürülmez; mevcut pre/post-commit politikaları korunur.

Request boyunca tek uzun “global DB transaction” kullanılmaz.

---

## 25. Concurrency ve Revocation Yarışları

- Membership/role/status değişiklikleri optimistic version ile yapılır.
- Authorization decision güncel committed version'ı okur.
- Pre-execution grant sonrası revoke olursa 5.0C pre-persistence revalidation persistence'ı reddeder.
- Token doğrulama ile membership revoke aynı anda yarışırsa authorization read'in gördüğü committed state authoritative'dir; stale positive cache yoktur.
- Tenant ownership değiştirilemez; company/batch başka tenant'a UPDATE ile taşınamaz.
- Duplicate principal veya membership concurrent insert DB unique constraint ile tek winner üretir.

---

## 26. Determinizm ve Framework İzolasyonu

JWT validation `now` değerini injected clock'tan alır. Tests sabit zaman kullanır. JWKS selection ve permission evaluation insertion order'dan bağımsız, canonical sıralıdır.

Security core:

- FastAPI/Pydantic/SQLAlchemy import etmez;
- token doğrulama sonucu immutable dataclass'tır;
- kapalı enum ve tuple kullanır;
- raw dict claim set'ini public application contract'a taşımaz.

FastAPI yalnız header/dependency/error adapter'ında, SQLAlchemy yalnız repository adapter'ında bulunur.

---

## 27. Test Stratejisi

### 27.1 Contract/import testleri

- 5.0A–5.0D public contract snapshot'ları değişmedi;
- security core'da FastAPI/Pydantic/SQLAlchemy importu yok;
- exact immutable DTO/enum/port signatures;
- no raw identity-header fallback.

### 27.2 JWT unit/golden testleri

- RS256/PS256/ES256 valid vectors;
- wrong signature/issuer/audience/kid/type;
- `none`, HS confusion, key-type mismatch;
- duplicate header keys ve duplicate claim keys;
- unknown `crit`, `b64=false`, embedded `jwk/jku/x5u/x5c/x5t`;
- weak RSA key, invalid exponent, disallowed EC curve, wrong key use/key_ops;
- malformed/non-canonical Base64URL ve NumericDate overflow/type;
- expired/future/over-lifetime/nbf/skew boundaries;
- malformed/whitespace/case/Unicode `sub`, tenant_key ve jti;
- missing/unknown/non-canonical claims_version;
- duplicate/ambiguous tenant claim sources;
- HUMAN/SERVICE audience, principal kind ve client_id mismatch;
- missing HUMAN acr/amr, unknown strength evidence, SERVICE alternative strength;
- oversized token;
- ID/refresh/opaque token rejection;
- raw token/claims never logged or audited.

### 27.3 JWKS testleri

- fresh-cache hit;
- ETag 304;
- unknown-kid forced refresh exactly once;
- rotation overlap;
- removed key rejection;
- stale cache + outage 503;
- successful refresh + unknown kid 401;
- redirect/HTTP/host mismatch rejection;
- concurrent refresh single-flight;
- random-kid flood produces bounded refresh count;
- minimum forced-refresh suppression;
- negative-cache hit, TTL, LRU eviction ve hard size bound;
- response byte/key-count limit;
- stale-while-error known-key use ve hard-stale rejection;
- required metric/audit categories;
- cache TTL property tests.

### 27.4 Provisioning test matrisi

- bootstrap first tenant/principal/subject/membership/TENANT_ADMIN atomik success;
- bootstrap ikinci kez fail-closed;
- platform authority ile additional tenant aggregate atomik success;
- invalid mTLS/workload/envelope platform authority rejection;
- tenant authority tenant/principal create, global principal revoke veya subject rotation yapamaz;
- platform authority post-bootstrap membership/role yönetimini bypass edemez;
- duplicate tenant_key;
- duplicate provider+subject binding;
- same idempotency key + same payload idempotent success;
- same key + different payload conflict;
- concurrent principal/membership provisioning tek winner;
- membership create ve immediate revoke;
- unauthorized role assignment;
- cross-tenant role assignment rejection;
- service/human role escalation attempt;
- revoked principal ve membership;
- future effective_at rejection;
- required audit unavailable → transaction başlamaz;
- DB failure → full rollback;
- subject binding rotation success/conflict;
- get_provisioning_status deterministic projection.

### 27.5 Ownership/authorization PostgreSQL testleri

- duplicate issuer+subject rejection;
- duplicate tenant membership rejection;
- cross-tenant role assignment rejection;
- inactive tenant/principal/membership deny;
- valid_from/valid_until boundaries;
- `tokens_valid_after` revocation;
- company/bulk batch tenant binding required for new writes;
- historical unbound resource hidden;
- tenant ownership UPDATE rejection;
- concurrent membership/principal insert one winner;
- DB outage fail-closed;
- migration upgrade → downgrade-safety → upgrade.

Her built-in role için PermissionRegistry'deki her permission üzerinde exhaustive allow/deny parametrik matrix çalışır. Ayrıca unknown permission, HUMAN→service-only, SERVICE→human-only, insufficient strength, hidden resource ve provider/DB outage testleri zorunludur. Pre-persistence revoke/revalidation bu genel gruba dahil değildir; exact sahibi Bölüm 27.5.3 Adım 11 kapısıdır.

#### 27.5.1 Adım 9 identity repository ve revocation test kapısı

Başarılı PostgreSQL senaryoları:

- valid HUMAN resolution;
- `SERVICE_OPERATOR` ile valid SERVICE resolution;
- yalnız service-safe custom role ile, `SERVICE_OPERATOR` olmadan valid SERVICE resolution;
- DB boundary `12:00:00.000000` ve aynı NumericDate token iat kabulü;
- DB boundary `12:00:00.000001` veya `12:00:00.999999`, token iat `12:00:00` iken ret;
- token iat effective boundary'den bir saniye sonra kabul;
- principal `tokens_valid_after` ile membership `valid_from` maximum boundary seçimi;
- PostgreSQL mikrosaniye round-trip ve Python karşılaştırma eşitliği;
- UTC dışı aware input'un instant korunarak UTC'ye çevrilmesi ve hiçbir truncation yapılmaması;
- `now == membership_valid_from` ve `now == membership_valid_until` kabulü;
- provisioning ile principal veya membership revoke commit'inden sonraki ilk resolution'da anında ret.

Fail-closed senaryolar:

- unknown issuer/subject ve unknown tenant;
- tenant mismatch ve noncanonical tenant key;
- wrong principal kind veya HUMAN/SERVICE profile/client mismatch;
- inactive tenant, inactive principal ve inactive/revoked subject binding;
- missing, suspended veya revoked membership;
- membership not-yet-valid ve expired;
- SERVICE için hiç service-safe role olmaması;
- SERVICE rolünde human-only permission ve mixed service-safe/human-only permission bulunması;
- inactive SERVICE membership ve duplicate role assignment/data-integrity state;
- stale/unknown permission registry version;
- custom role permission değişikliğinde role/tenant version ve role-set digest/reference değişimi;
- HUMAN için active HUMAN-safe rol gereksinimi ve human-only policy doğrulaması;
- relational permission-state corruption → `DATA_INTEGRITY_VIOLATION`;
- `token_issued_at < tokens_valid_after` ve membership validity boundary'den eski token;
- naive input/persisted datetime ve UTC conversion/truncation ihlali;
- corrupt cross-tenant membership/role relation, duplicate authoritative binding ve invalid version;
- database statement/pool timeout ve database unavailable;
- raw SQLAlchemy/PostgreSQL exception, SQL text ve persisted identity değerlerinin exception/audit/metric dışına sızmaması.

Parametrik precedence senaryoları:

- principal inactive + old token → yalnız `PRINCIPAL_INACTIVE`;
- membership inactive + old token → yalnız `MEMBERSHIP_INACTIVE`;
- tenant mismatch + missing target membership → yalnız `TENANT_MISMATCH`;
- inactive binding + missing membership → yalnız `SUBJECT_BINDING_INACTIVE`;
- binding mevcut + principal FK target yok → `DATA_INTEGRITY_VIOLATION`;
- validity failure + principal token boundary failure → daha erken validity/status basamağının exact kodu;
- her structural duplicate/FK/cross-tenant persisted corruption → bulunduğu ilk basamakta `DATA_INTEGRITY_VIOLATION`.

Exact error-contract testleri:

- 19 enum exact string value ve metadata registry exhaustive coverage;
- unknown/string error code constructor rejection;
- deterministic retryable/audit/metric/safe-message mapping;
- `str`, `repr`, equality ve hash'in safe/deterministic olması;
- safe message, serialization ve exception chaining yolunda raw DB exception/SQL/DSN/token/claim/PII sızıntısı olmaması.

DTO constructor testleri:

- HUMAN veya SERVICE `membership_id` olmadan ret;
- empty, duplicate veya canonical sırasız role tuple reddi;
- eksik/malformed `permission_resolution_reference`, `role_set_digest`, `permission_registry_version` veya `tenant_policy_version` reddi;
- reference ile membership/version/registry/digest alan uyuşmazlığı reddi;
- naive/UTC dışı datetime reddi;
- invalid UUID, non-ACTIVE status ve zero/negative version reddi;
- immutable collection ve frozen field davranışı.

Custom-role permission safety, assignment activity, registry version ve digest üretimi yalnız repository integration testinin sorumluluğudur; DTO constructor testleri permission satırı okumaz veya service-safe kararı yeniden üretmez.

Kapı başarı kriteri: Adım 9 contract/unit ve gerçek PostgreSQL testleri, E1 provisioning testleri, E2 enforcement testleri, migration cycle ve tam Docker `tests/` paketi **0 failed, 0 skipped** olmalıdır; `git diff --check` temiz kalmalıdır. Bu kapı yeşil olmadan Adım 10'a geçilmez.

#### 27.5.2 Adım 10 authorization policy engine test kapısı

Adım 10 test sahipliği aşağıdaki exact gruplardır:

- **Contracts:** tüm yeni enum'lar kapalı; DTO'lar frozen; invalid constructor state, safe `str/repr`, no HTTP/FastAPI/Pydantic/SQLAlchemy import guard.
- **Compiled SecurityAction golden manifest:** Bölüm 15.6.1'deki 33 literal action'ın action/permission, scope, operation, internal strength, exact kind seti, `ownership_requirement`, predicate, hiding, audit ve version alanlarının tamamı tek golden fixture ile birebir eşleşir; eksik/fazla action yoktur.
- **PermissionRegistry:** exact 33 unique permission, immutable manifest, canonical registry digest/golden constant, additive-version kuralı, unknown permission ve stale version fail-closed.
- **Strength compiler:** source `BASIC/STRONG/PHISHING_RESISTANT` exhaustive mapping, 33 compiled action, unknown source value rejection, HUMAN ordering, SERVICE_CREDENTIAL eksen ayrımı ve iki yönlü cross-axis ret.
- **Action compiler:** Bölüm 15.6'daki tüm unique source action literal'ları exact operation'a map edilir; fallback/prefix/substring yoktur; unknown action reddedilir. `APPLICATION_READ_GUARD`, `STATUS_READ`, `RESULT_METADATA_READ` ve `EXECUTION_PAYLOAD_READ` ayrı golden assertions'dır.
- **Built-in roles:** altı rol × 33 permission = **198** parametrik ALLOW/DENY hücresi; duplicate/unknown role; TENANT_ADMIN ve SERVICE_OPERATOR exact golden matrisleri; canonical matrix digest.
- **Custom roles:** valid HUMAN ve valid service-safe SERVICE custom role; SERVICE'de human-only/mixed permission, HUMAN'da service-only permission; stale assignment version/digest/reference; committed permission mutation'ının bir sonraki evaluation'da görünmesi.
- **Ownership/action semantics:** owner + `analysis.cancel.own` ownership success; initiator fakat owner olmayan + `analysis.cancel.own` → `RESOURCE_OWNERSHIP_MISMATCH`; missing owner → `RESOURCE_STATE_INVALID`; non-owner + `analysis.cancel.any` + permission ownership/predicate nedeniyle reddedilmez; same-tenant cross-subject resume/read; cross-tenant hidden; 33 action ownership golden alanı. Golden/compiler/endpoint fixture'larında `analysis.cancel.own=RESOURCE_OWNER_REQUIRED/NONE`, `analysis.cancel.any=NONE/NONE`; static canonical-action scan eski self-style alias'ları ve registered manifest dışı predicate association'larını reddeder.
- **SELF/request contract:** exact `PolicyEvaluationRequest`; SELF target zorunluluğu; `identity.provider_subject` tek kaynak; beş predicate'in required/forbidden girdileri, case sensitivity ve raw-subject redaction.
- **Resource resolution topology:** exact immutable `ResourceSecurityReference`; caller owner/tenant/version/relation metadata spoofing impossible; malformed reference store öncesi ret; durable ve synthetic exact resolver selection; resolver bypass/pre-resolved scope/direct scope injection production DI reddi; no double resolution; cross-tenant scope engine'e ulaşmaz; same reference + same authoritative state aynı scope.
- **Synthetic scopes:** closed 11-member `PolicyScopeType`; exact name/value seti; `TRIAL_BALANCE` accepted ve legacy `TRIAL_BALANCE_RESOURCE` rejected/no alias; 11 enum = 11 manifest = 11 production vector set equality; valid/invalid SYSTEM, TENANT, COMPANY_PERIOD; forbidden fields; unknown tenant; compound-ID/relation/company mismatch; cross-tenant; resolver timeout/unavailable ve version determinism.
- **Resource codec primitives:** Bölüm 15.7.3'teki 11 low-level vector literal bytes/digest testi; bunlar production acceptance sayılmaz.
- **Production scope codec:** 11 tam manifest golden vector, exact bytes ve `rsv1` digest; input-order/timezone/null equivalence, one-field mutation; missing/forbidden/unknown/partial/invalid production negatif matrisi.
- **Resource repository:** sekiz authoritative domain path için same-tenant, owner/initiator, unknown ve cross-tenant aynı hidden `RESOURCE_NOT_FOUND`, unscoped fallback query yokluğu, PostgreSQL timeout/unavailable, corruption ve no-partial-scope.
- **Precedence matrices:** Step 7'nin exact **11** `S7-01..S7-11` ve Step 10'un exact **17** `S10-01..S10-17` literal multi-error golden case'i, tabloda yazılı terminal reason/outcome/retryable/hiding/audit/metric ve no-later-call beklentileriyle parametrik test edilir. S10-17 ayrıca healthy same-tenant fixture, caller'ın yanlış company/period pair input'u, exact `RESOURCE_NOT_FOUND` metadata'sı, tek resolver/qualified-lookup çağrısı ve sıfır secondary/unscoped/later-call beklentisini doğrular. Property testleri ilk failure sonrası call-count sıfır, aynı inputta adapter-independent sonuç ve Model A indistinguishability doğrular; dolaylı “listed combinations” genişletmesi yoktur.
- **Subject reference:** `srh1` canonical frame, domain separation, issuer/tenant/kind/key-version binding, beş literal HMAC vector, key rotation ve raw-subject redaction negatifleri.
- **PolicyRepositoryError:** dokuz exact enum/metadata/mapping satırı ve keyword-only constructor; field/args/new-attribute write ile bütün delete girişimlerinin reddi, exact subclass rejection, metadata override reddi, exact `args=(safe_message,)`, correlation-redacted `repr`, safe `str`, raw cause/SQL/DSN/token/claim/subject/resource-ID/PII suppression ve unknown-code rejection.
- **Terminal construction:** invalid result enum/resource version/audit intent/correlation; ikinci result-constructor çağrısı olmadan exact immutable `PolicyEvaluationConstructionError`; signature/constants, field/args/new-attribute/delete mutation ve subclass rejection; safe `str/repr/args`, raw cause/input leak yokluğu ve Adım 11 fail-closed mapping snapshot'ı.
- **Execution manifest:** exact internal `orchestration_run_id: UUID`, FK/join ownership yolu ve production execution digest vector.
- **Reason reachability:** Adım 10'daki **17** reason'ın her biri exact precedence step'inden parametrik üretilir; dead/alias code yoktur. Adım 11 audit-unavailable kodu ayrı adapter testidir.
- **Audit intent:** 17 reason için exact event name, requirement-derived required flag, severity/metric, HMAC subject reference, caller override reddi ve adapter-order independence.
- **Policy result:** typed ALLOW/DENY/INDETERMINATE, exact 17 reason metadata satırı, hiding flag, exact `AuditIntent` ve deterministic immutable result.
- **Property:** unknown permission hiçbir zaman allow değil; HUMAN strength monotonic; tenant/kind mismatch hiçbir zaman allow değil; SERVICE human-only, HUMAN service-only permission alamaz; aynı canonical input aynı sonucu üretir.

PostgreSQL adapter testleri `AuthorizationPolicyRepositoryPort` proof revalidation, `ResourceSecurityRepositoryPort` durable ownership snapshot'ı ve `SyntheticSecurityScopeResolverPort` TENANT/COMPANY_PERIOD authoritative relation çözümünü kapsar. SYSTEM resolver pure unit/golden test ile doğrulanır. Adım 10 policy engine audit sink çağırmadığı için audit-outage ve pre-persistence revoke testleri bu kapıda yoktur.

Regresyon sırası: Adım 9 contract **21**, Adım 9 repository **36**, provisioning **5**, E2 **8**, migration-cycle **1**, ardından yeni testlerle tam Docker paketi. Her kapıda **0 failed, 0 skipped** ve `git diff --check` temiz olmalıdır. Bu kapı yeşil olmadan Adım 11'e geçilmez.

#### 27.5.3 Adım 11 adapter/revalidation test sahipliği

Yalnız Adım 11 aşağıdaki kapıyı sahiplenir; Adım 12 provider implementation'ı, router ve HTTP testi bu kapıya alınmaz:

- değişmemiş 5.0C `AuthorizationPort` altı method imzası ve `AuthorizationDecision` exact field snapshot'ı;
- `TrustedAuthorizationContext` DTO constructor/immutability/safe repr; valid, missing, invalid, stale, expired, subject mismatch, tenant mismatch, provider outage, integrity failure;
- initial checkpoint'te valid olup `PRE_PERSIST_*` checkpoint zamanında expired/stale olan context; checkpoint-local deterministic `resolved_at` ve initial/pre-persist issuer-subject-tenant-token binding equality;
- fake context provider production rejection ve aynı request/checkpoint için deterministic context;
- `ApplicationAuditContextDTO.actor_id` exact `srh1` consistency; raw subject actor rejection ve mevcut 5.0C boundary audit event'inde PII bulunmaması;
- context → Adım 9 fresh repository argument mapping'i; raw token/claim/header taşınmadığı static import/field guard;
- Adım 9'un 19 error code'unun exhaustive adapter mapping'i; revoked/retryable/decision-code matrix;
- Adım 10'un **17/17** reason'ının literal `AuthorizationDecision` mapping'i; unknown reason fail-closed, DENY/INDETERMINATE hiçbir zaman grant değil;
- `AuthorizationAdapterDecisionCode` exact **47/47** literal set equality, no alias/dynamic prefix construction ve her code için `AuthorizationDecision` constructor invariant'ı;
- context sekizli, audit altılı ve identity on dokuzlu taxonomy'nin exact metadata/mapping coverage'ı;
- `AuditIntent → SecurityAuditEventDTO` exact projection: event type, exact event-name preservation, safe resource/tenant/request references, `srh1`, sorted attributes, no raw PII/SQL/token;
- audit success; required timeout/unavailable; invalid/unsupported event; delivery conflict/integrity; `DENY_ONLY` audit outage'ında deny preservation;
- audit idempotency: same key+digest same receipt, same key+different digest conflict, adapter içi retry yok;
- aynı evaluation için exact bir Adım 11 detailed policy event + exact bir mevcut 5.0C application-boundary event; iki semantik event'in replay sayılmaması ve her iki outage sınırının fail-closed sonucu;
- `AuthorizationDecisionReferenceCodec v1`: **4/4** digest golden vector, ADR-1 literal canonical bytes, mutation/type/order/null/time negatives ve terminal fallback reference;
- pre-persistence principal revoke, membership revoke/expiry, token boundary, role removal, permission removal, tenant policy version change, resource ownership/version change, provider/audit outage;
- initial ALLOW sonrası revalidation deny'da persistence port call-count exact sıfır; final ALLOW+required audit success'te exact bir;
- `AnalysisApplicationService` initial çağrısının yalnız `AuthorizationPort`'a, ikinci kontrolün yalnız internal `AuthorizationRevalidationPort`'a gitmesi; iki production binding'in aynı adapter instance olması; missing/different binding ve public-method fallback readiness failure;
- cancel: owner success, HUMAN ownership-mismatch→any, HUMAN own-permission-missing→any, custom-role any-only success; first-deny audit outage, resource-not-found/state-invalid/integrity/outage ve SERVICE için any fallback call-count sıfır;
- resume source initial ALLOW sonra revoke/permission removal/ownership-version/cross-tenant/missing; destination mismatch; final source revalidation deny'da persistence sıfır;
- security revalidation snapshot'ından önce commit edilmiş mutation görünür; snapshot sonrası race için atomiklik iddiası olmadığı contract testi/dokümantasyon assertion'ı;
- audit success sonrası persistence failure'da authorization audit receipt korunur, terminal-persisted audit üretilmez;
- Adım 9 contract **21**, Adım 9 PostgreSQL repository **36**, Adım 10 **395**, provisioning **5**, E2 **8**, migration-cycle **1** regresyon kapıları;
- tam Docker `tests/`: **0 failed, 0 skipped** ve `git diff --check` temiz.

Adım 11 kapısı required audit delivery ve revalidation sahibidir; endpoint-specific read permission, request-bound provider implementation ve route wiring sonraki exact adımlarda kalır.

#### 27.5.4 Adım 12 request-bound provider test kapısı

Yalnız Adım 12 aşağıdaki kabul kapısını sahiplenir; router/HTTP permission wiring Adım 13'e kalır:

- valid HUMAN BASIC/STRONG/PHISHING_RESISTANT mapping ve valid SERVICE `SERVICE_CREDENTIAL` mapping;
- JWT/local identity issuer, subject, tenant, principal-kind ve SERVICE client mismatch negatives;
- missing, malformed, stale, expired, future-issued context ile exact expiry/max-age sınırları;
- provider timeout/unavailable/unknown failure fail-closed ve raw cause redaction;
- same request/checkpoint deterministic DTO; initial ile PRE_PERSIST ayrı zaman/freshness kontrolü;
- duplicate/missing/wrong-scope checkpoint target, tenant/company/period/run binding negatives;
- concurrent thread ve async task same-request determinism; ayrı provider instance'ları arasında
  context/cache contamination olmaması; global/thread-local/ContextVar identity state import guard;
- raw identity header'ın mevcut 5.0D boundary'de reddi; Step 12 DTO/field/import graph'ında raw bearer,
  token, claims, JOSE veya PII bulunmaması;
- fake/static/non-request-bound provider'ın production'da reddi; missing/unavailable provider ve
  readiness false; TEST/DEVELOPMENT profile ayrımı;
- correlation/request ID propagation, safe repr ve immutable DTO/plan/provider state;
- Adım 11 `TrustedAuthorizationContextProviderPort` exact compatibility ve valid context ile gerçek
  policy evaluation entegrasyonu;
- Adım 11 **90**, Adım 10 **395**, Adım 9 contract **21**, Adım 9 PostgreSQL **36**, provisioning
  **5**, E2 **8**, migration-cycle **1** regresyon kapıları;
- tam Docker `tests/`: **0 failed, 0 skipped** ve `git diff --check` temiz.

### 27.6 Route matrix testleri

Matristeki her protected route için en az:

- missing authentication 401;
- valid authentication + missing permission 403;
- correct tenant/permission success;
- cross-tenant ID 404;
- list/count tenant isolation;
- required write strength deny/grant;
- raw identity header cannot override;
- raw exception/token redaction.
- exact `WWW-Authenticate` missing/invalid token davranışı;
- common versioned legacy security error envelope;
- production `/`, `/health`, docs/redoc/openapi disabled;
- authentication admission saturation/Retry-After.

Route inventory test'i, FastAPI registered route set'ini normative matrix ile exact karşılaştırır. Yeni protected route action/policy tanımı olmadan testte fail eder.

### 27.7 Analysis regression testleri

- mevcut sekiz analysis endpoint'i değişmez;
- same run same subject replay;
- different subject/tenant/company/period fail-closed;
- resume-source authorization ordering;
- pre-persistence membership revoke — yalnız Bölüm 27.5.3 Adım 11 kapısında;
- wrong-scope persisted result projection yok;
- post-commit audit warning ve projection recovery değişmez.

### 27.8 Security audit testleri

- success/failure/deny/revoke event'i;
- token/claim/raw exception sızıntısı yok;
- audit unavailable pre-use-case failure;
- post-commit mevcut warning semantiği;
- subject/JTI hashing deterministik ve secret-bound.

### 27.9 Property/fuzz testleri

- arbitrary malformed bearer/JWT hiçbir uncaught exception üretmez;
- permission union order-independent;
- tenant scope hiçbir mapping yolunda caller override alamaz;
- deny is monotonic: permission kaldırma grant üretemez;
- canonical issuer/audience comparison substring kabul etmez.
- tenant_key canonical regex dışındaki her değer reddedilir;
- PermissionRegistry/role expansion insertion order'dan bağımsızdır;
- random-kid dizisi bounded network refresh invariant'ını aşamaz.

### 27.10 Migration/historical binding testleri

- E1 clean upgrade;
- valid canonical historical claim + provisioned tenant E2 success;
- invalid case/Unicode/whitespace historical tenant E2 fail;
- unknown historical tenant E2 fail;
- null/unbound resource quarantine ve API hidden;
- new company/batch/claim null/unknown tenant negative insert;
- tenant FK ve ownership immutability;
- E2→E1 non-destructive downgrade→E2;
- non-empty security state E1→pre-5.0E downgrade refusal;
- empty-state full upgrade→downgrade→upgrade.

---

## 28. Docker Kabul Kriterleri

1. Baseline implementasyon öncesi `0 failed`.
2. Tüm JWT/JWKS/security unit testleri `0 failed`.
3. Tüm legacy ve analysis router security testleri `0 failed`.
4. Gerçek PostgreSQL ownership/membership/revocation/concurrency testleri `0 failed`.
5. Migration upgrade/downgrade-safety/upgrade testi `0 failed`.
6. Tam Docker `tests/` paketi `0 failed` ve `0 skipped`.
7. `git diff --check` temiz.
8. Production runtime fake/allow-all/no-op adapter ile ready olamıyor.
9. Raw token/identity/exception leak taraması temiz.
10. Architecture Book v1.5.0 ayrı onaylı dokümantasyon turunda senkronize edilmiş.

---

## 29. Performans Hedefleri

- Fresh JWKS cache ile network çağrısı: request başına 0.
- JWT verify + local identity lookup warm-path p95 hedefi: 75 ms altında.
- Authorization DB/policy evaluation p95 hedefi: 50 ms altında.
- JWKS HTTP timeout: Bölüm 12 uyarınca exact 2 saniye.
- Security DB timeout: config, bounded; limitsiz bekleme yok.
- Permission evaluation role/permission sayısına bounded ve deterministic.

Bu değerler sertifikasyon değildir; Docker/performance smoke test kabul eşikleridir.

---

## 30. Risk Analizi

| Risk | Etki | Mitigasyon | Blocking |
|---|---|---|---|
| Legacy route korunmadan kalır | Cross-tenant veri ihlali | Exact route inventory + registration test | Hayır |
| Token role/group claim'i grant olur | Privilege escalation | Local membership/permission authoritative | Hayır |
| Algorithm confusion | Authentication bypass | Asymmetric closed allowlist + key-type match | Hayır |
| Unknown kid sırasında outage | Yanlış 401 veya fail-open | Forced refresh + 503 fail-closed | Hayır |
| Stale JWKS sonsuza kadar kullanılır | Revoked key kabulü | 120 sn bounded stale-while-error + 420 sn hard-stale rejection | Hayır |
| JWT provider revocation gecikir | Compromised token window | ≤15 dk token + local tokens_valid_after | Hayır; residual documented |
| Historical resources unbound | Yanlış tenant assignment | Auto-backfill yok; hidden until explicit binding | Hayır |
| Membership revoke yarışı | Revoke sonrası write | No positive cache + pre-persist revalidation | Hayır |
| Token/log data leak | Credential compromise | Structured redaction + leak tests | Hayır |
| Security DB/audit outage | Availability kaybı | Fail-closed, readiness false | Hayır; intentional |
| 5.0C/D contract değişikliği | Regression | Adapter-only implementation + snapshot tests | Hayır |

---

## 31. Reddedilen Alternatifler

1. **Raw user/tenant header:** trusted identity değildir; kesin reddedildi.
2. **Token group/role claim'ini doğrudan permission saymak:** local membership sahipliğini bypass eder; reddedildi.
3. **Local password database:** v1 resource-server kapsamını büyütür; reddedildi.
4. **Opaque token'ı doğrulamadan kabul:** trust kanıtı yoktur; reddedildi.
5. **Her request'te JWKS fetch:** availability ve latency riski; bounded cache seçildi.
6. **Stale JWKS ile süresiz devam:** revoked key kabul riski; reddedildi.
7. **Dynamic issuer/JWKS URL'yi token'dan almak:** SSRF/key-confusion riski; reddedildi.
8. **Positive authorization cache:** immediate local revocation'ı bozar; v1'de reddedildi.
9. **Generic polymorphic resource-owner tablosu:** gerçek FK bütünlüğünü kaybeder; reddedildi.
10. **Security audit'i domain event stream yapmak:** event sourcing yasağına aykırı; reddedildi.
11. **Authentication middleware içinde business authorization:** action/resource bağlamını kaybeder; dependency + policy port ayrımı seçildi.
12. **5.0D AuthenticationContext alanlarını genişletmek:** public contract ihlali; internal verified identity + mapping seçildi.

---

## 32. Açık Kararlar

Aşağıdaki kararlar mimariyi veya implementasyon contract'ını değiştirmeyen deployment/operasyon seçimleridir:

| ID | Açık karar | Tür | Blocking |
|---|---|---|---|
| OD-1 | Production OIDC vendor'ı ve exact issuer/audience/JWKS değerleri | Deployment configuration | Hayır |
| OD-2 | Durable audit sink/SIEM ürün/provider seçimi | Operations | Hayır; port, required delivery ve redaction sabit |
| OD-3 | Jurisdiction/compliance gereğine göre 365 günlük minimumun üzerindeki exact retention | Operations/compliance | Hayır; minimum tasarımda kilitli |
| OD-4 | Tenant'lara atanacak initial custom role kataloglarının dağılımı | Tenant operations | Hayır; built-in exhaustive roller ve registry sabit |

**Açık karar sayısı: 4. Blocking karar sayısı: 0.**

Provisioning channel architecture, built-in role matrix, tenant canonicalization, JWT parser/library, HUMAN/SERVICE profiles, static JWKS kararı ve public/legacy route davranışı bu revizyonda kapanmıştır. Kalan dört madde implementasyon davranışını değiştirmeyen deployment/operasyon seçimidir. Production deployment OD-1/OD-2/OD-3 için geçerli config/binding olmadan readiness alamaz.

---

## 33. Test-Gated Implementasyon Adımları

Her adımın hedef testleri ve tam regresyonu yeşil olmadan sonraki adıma geçilmez.

1. **Baseline:** tam Docker paketi; `0 failed` değilse dur.
2. **Framework-independent security contracts:** enums/dataclasses/ports/issuer profile; import-guard ve contract testleri.
3. **Strict bearer/JWT verifier:** golden/negative/property testleri.
4. **JWKS provider/cache:** rotation/outage/concurrency testleri.
5. **E1 additive migration ve modeller:** security tabloları, nullable resource tenant bağları ve quarantine; gerçek PostgreSQL constraint + E1 downgrade testleri.
6. **Bootstrap/platform provisioning ve tenant yönetimi:** BootstrapTrustPort, IdentityProvisioningPort, idempotency/audit/transaction testleri; trusted fixture tenant/principal/membership/role üretimi.
7. **Historical binding gate:** yalnız provisioned tenant_key'lere explicit company/batch/run binding; invalid/unbound quarantine testleri.
8. **E2 enforcement migration:** validated run-claim FK, new-row non-null/known-tenant enforcement ve E2→E1→E2 cycle testleri.
9. **Identity repositories ve revocation:** Bölüm 16.1'deki exact immutable `VerifiedLocalIdentity`, tek `SecurityIdentityRepositoryPort`, 19 kodlu kapalı taxonomy, 15 basamaklı precedence ve no-positive-cache immediate revocation uygulanır; HUMAN/SERVICE subject/client/binding, service-safe custom role ve error/DTO contract testleriyle Bölüm 27.5.1 kapısı tamamen yeşil olmalıdır. Migration/model/schema değişikliği yoktur.
10. **Authorization policy engine:** Bölüm 15.6–15.15'teki immutable action/request/reference/resource/result/audit-intent contract'ları, engine'e ait 17 kodlu reason taxonomy, exact `TRIAL_BALANCE` dahil closed 11-member `PolicyScopeType`, `OwnershipRequirement`, 33-action literal golden manifesti, 198 hücreli built-in rol matrisi, exhaustive strength/action compiler'ları, `analysis.cancel.own=RESOURCE_OWNER_REQUIRED/NONE`, `analysis.cancel.any=NONE/NONE`, `ResourceSecurityReference → engine-selected resolver → authoritative ResourceSecurityScope` tek topolojisi, Model A cross-tenant hiding, `ResourceSecurityVersionCodec v1` için 11 primitive + 11 tam production vector, `SubjectReferenceHashCodec v1`, immutable `PolicyRepositoryError`, immutable/non-recursive `PolicyEvaluationConstructionError`, internal execution-run UUID semantiği, authoritative `AuthorizationPolicyRepositoryPort` + `ResourceSecurityRepositoryPort` + `SyntheticSecurityScopeResolverPort` adapter'ları, 11-case Step 7 ve 17-case Step 10 literal multi-error kapıları ve 18 basamaklı pure/internal evaluation uygulanır. Bölüm 27.5.2 kapısı tamamen yeşil olmalıdır; audit sink/delivery, Adım 11 `AUDIT_REQUIRED_BUT_UNAVAILABLE`, 5.0C adapter ve pre-persistence revalidation yoktur. Migration/model/schema değişikliği yoktur.
11. **5.0C AuthorizationPort adapter:** Bölüm 15.16'daki `TrustedAuthorizationContextProviderPort` tüketilir (implementation Adım 12'de kalır); context her checkpoint'te doğrulanır, Adım 9 identity ve Adım 10 permission/resource state fresh çözülür, **17/17** result literal olarak değişmemiş 5.0C `AuthorizationDecision`'a map edilir, `AuditIntent` mevcut `SecurityAuditEventDTO`'ya safe/idempotent biçimde projekte edilip required `SecurityAuditPort` delivery uygulanır, `AuthorizationDecisionReferenceCodec v1` final `adr1` üretir ve pre-persist principal/membership/policy/resource revoke ile resume-source revalidation yapılır. Public contract snapshot ve Bölüm 27.5.3 kapısı tamamen yeşil olmalıdır; provider implementation, router/API/HTTP, endpoint-specific read permission ve legacy routes yoktur. Migration/model/schema değişikliği yoktur.
12. **Request-bound AuthenticationContext provider:** Bölüm 17.1–17.2 internal request binding,
    frozen 5.0D `AuthenticationContext` mapping'i, checkpoint-specific trusted resource plan,
    request-local bounded deterministic cache, freshness/expiry revalidation ve production
    fake/missing/readiness fail-closed composition uygulanır. Bölüm 27.5.4 kapısı tamamen yeşil
    olmalıdır; router/HTTP permission wiring, legacy routes, migration/model ve Adım 13+ yoktur.
13. **Analysis-run router entegrasyonu:** Bölüm 18.3.1 request security session, bearer authentication
    factory, initial-decision cache, uncached pre-persistence revalidation, exact endpoint action planı,
    Model A authorization-before-load sırası, closed HTTP mapping ve OpenAPI bearer metadata'sı sekiz
    endpoint üzerinde uygulanır. Router/HTTP testleri tamamen yeşil olmalıdır; legacy routes Adım 14,
    migration/model ve yeni action/permission yoktur.
14. **Legacy route dependency katmanı:** route matrisi sırasıyla companies → periods → documents/analyses → trial balance → bulk upload; her grup test-gated.
15. **Security audit/redaction/readiness:** outage, leak ve production fake-adapter testleri.
16. **Cross-tenant/IDOR PostgreSQL integration:** list/count/get/write, provisioning ve concurrency testleri.
17. **Tam Docker doğrulama:** full suite, security subset, PostgreSQL, migration, concurrency, OpenAPI/schema.
18. **Static kapanış:** `git diff --check`, status, contract-import taraması ve tasarım sapması raporu.
19. **Architecture Book v1.5.0:** implementasyon doğrulandıktan sonra ayrı kullanıcı onayıyla dokümantasyon senkronizasyonu.

---

## 34. Production Readiness Kriterleri

- Blocking açık karar `0`.
- 5.0A–5.0D public contract diff'i yok.
- Production issuer/audience/JWKS config explicit.
- Symmetric/none/dynamic-key JWT kabul edilmiyor.
- Tenant/membership/role state authoritative ve DB constraint'li.
- Bootstrap/platform provisioning ile tenant-scoped yönetim ayrımı ve provisioning idempotency testleri yeşil.
- Her protected route exact action/resource policy'ye bağlı.
- Route registry gerçek repository envanteriyle birebir ve classification'sız route readiness alamıyor.
- Cross-tenant IDOR/list/count testleri yeşil.
- Revocation ve pre-persistence revalidation yeşil.
- Random-kid flood, bounded negative cache, stale/hard-stale ve rotation yarış testleri yeşil.
- Required audit fail-closed; observability best-effort.
- Token/claim/raw exception leak testleri temiz.
- Production fake/allow-all/no-op adapter ile startup/readiness başarısız.
- Tam Docker `0 failed`, `0 skipped`.
- PostgreSQL ve migration cycle testleri yeşil.
- Architecture Book v1.5.0 gerçek implementasyonla senkron.

---

## 35. Architecture Book v1.5.0 Senkronizasyon Planı

İmplementasyon ve terminal doğrulama tamamlandıktan sonra ayrı dokümantasyon turunda:

- metadata ve covered milestone 5.0E;
- authentication/authorization trust boundary;
- authoritative identity/tenant/membership ownership matrix;
- OAuth/OIDC/JWT ve JWKS politikası;
- route-protection matrisi;
- security data model/migration head;
- revocation, audit, readiness ve fail-closed kurallar;
- test sayıları ve Production Readiness checklist;
- dosya yapısı ve mimari prensipler

yalnız çalışan kodla doğrulanan gerçeklere göre güncellenir.

---

## 36. Tasarım Kapanışı ve Kullanıcı Onay Kapısı

Bu tasarım, 5.0A–5.0D public contract'larını değiştirmeden provider-neutral JWT authentication, authoritative local authorization ve legacy route protection için executable architecture tanımlar.

- Design Readiness: **%100**
- Blocking karar: **0**
- Adım 11 Design Readiness: **%100 — trusted context consumer portu, audit projection/delivery, exhaustive decision mapping, revalidation ve bounded TOCTOU sözleşmeleri executable seviyede kilitlidir**
- Adım 11 Runtime Readiness: **%0 — bu revizyon yalnız tasarımdır; Adım 10 ve önceki yeşil runtime kapıları korunur**
- İmplementasyona teknik olarak hazır: **Evet**
- İmplementasyon yetkisi: **Yok; ayrıca açık kullanıcı onayı gerekir**

Bu dokümanın oluşturulması production kodu, test, migration, model, repository, API veya runtime davranışı değiştirmez.

---

## 37. Bağımsız Mimari Denetim Sonrası Revizyon Raporu

| Bulgu | Kök neden | Uygulanan düzeltme | Eklenen sözleşme | Eklenen test kategorisi | Kapanma durumu |
|---|---|---|---|---|---|
| C1 — Closed authorization policy | Permission, rol, endpoint ve 5.0C checkpoint kararları adapter yorumuna açıktı | Sürümlü exhaustive registry, built-in rol matrisi, gerçek route matrisi ve deterministik deny/hide/outage kararları kilitlendi | `PermissionRegistry v1.0.0`, `PermissionDefinition`, `AuthorizationPolicyEnginePort`, exact 5.0C decision table | Full role allow/deny matrix, endpoint classification, scope/strength/kind/outage | **KAPALI** |
| C2 — Provisioning ve identity lifecycle | Authoritative identity state için trusted, idempotent, transaction-safe create/revoke yolu yoktu | One-time bootstrap, ayrı platform authority, tenant-local yönetim, required pre-transaction audit ve immediate revocation tanımlandı | `BootstrapTrustPort`, `IdentityProvisioningPort`, provisioning command/outcome/operation ledger | Bootstrap, duplicate/concurrent provisioning, audit outage, rollback, escalation, revoke/rotation | **KAPALI** |
| C3 — Canonical tenant identity | Token tenant değeri, application tenant string'i ve PostgreSQL ownership key'i tek canonical temsille bağlı değildi | External immutable tenant_key ile internal UUID ayrıldı; canonicalization ve E1/binding/E2 migration lifecycle kilitlendi | `security_tenants`, canonical tenant_key, validated run-claim reference, quarantine/downgrade | Historical binding, invalid canonical form, FK/non-null, cross-tenant, migration cycle | **KAPALI** |
| H1 — Claims normalization/version | Subject, tenant, JTI ve version coercion adapter'lar arasında değişebilirdi | Exact charset/length/case, ambiguous-source rejection ve tek accepted claims version tanımlandı | `auth-claims/1` ve closed claim validation | Whitespace/case/Unicode, duplicate/ambiguous claim, unknown version | **KAPALI** |
| H2 — Human/service profilleri | Human ve machine identity strength/membership/revocation semantiği karışıktı | Ayrı audience/claim/binding/strength/role/context kuralları tanımlandı | Principal kind + subject/service-client binding profilleri ve HUMAN/SERVICE context mapping | Cross-profile token, audience/client binding, acr/amr, permission-kind, revoke | **KAPALI** |
| H3 — JWT/JWS parser ve crypto | Library default'ları ve permissive JOSE parsing confusion riski taşıyordu | Tek vetted dependency, strict pre-parser, asymmetric algorithm/key profili ve explicit verification zorunlu oldu | `PyJWT[crypto]>=2.10,<3`, compact-JWS parser/crypto profile | Golden/fuzz, duplicate key, algorithm confusion, weak key, encoding | **KAPALI** |
| H4 — Unknown-kid/JWKS abuse | Random kid ve outage unbounded network/cache work veya süresiz stale trust doğurabilirdi | Bounded per-issuer cache, negative LRU, refresh interval/single-flight, network limitleri, stale window ve hard-stale rejection sabitlendi | JWKS cache/network/refresh decision contract ve metric/audit seti | Random-kid flood, negative-cache bound, suppression, rotation race, stale boundaries | **KAPALI** |
| H5 — OIDC discovery | Issuer metadata kaynağı dynamic discovery olarak yorumlanabiliyordu | v1 discovery reddedildi; static HTTPS exact allowlisted config zorunlu oldu | Immutable `OidcIssuerProfile`; no-discovery/no token-derived URL | Redirect/host/HTTP/dynamic URL ve duplicate config | **KAPALI** |
| H6 — Public/legacy route matrisi | Legacy route'lar ve public istisnalar exhaustive sınıflandırılmamıştı | Gerçek registered route inventory, public/disabled allowlist, exact envelope/WWW ve build-time completeness gate tanımlandı | `ProtectedRouteDefinition`, P0–P3, normative route matrix | Every-route classification, unauthenticated legacy, docs disabled, WWW/envelope | **KAPALI** |
| Adım 9 — SERVICE grant/role modeli çelişkisi | Bazı bölümler SERVICE_OPERATOR'ı zorunlu, bazıları service-safe custom role'ü geçerli sayıyordu; synthetic grant alanları authoritative değildi | ACTIVE membership + en az bir active service-safe role tek model seçildi; SERVICE_OPERATOR opsiyonel built-in default oldu; ayrı grant tablosu/DTO alanı kaldırıldı | `VerifiedLocalIdentity` yalnız membership + normalized roles taşır; tüm SERVICE role permission'ları `service_allowed=true` olmak zorunda | SERVICE_OPERATOR ve custom-role success; mixed/human-only/empty/duplicate/inactive role negatifleri | **KAPALI** |
| Adım 9 — Identity validation/error precedence eksikliği | Aynı anda inactive, mismatch, missing ve revoked state olduğunda error seçimi deterministik değildi | 15 basamaklı fail-fast precedence, structural integrity override ve status-before-revocation kararları kilitlendi | Exact resolution-order decision table ve 19 kodlu reachable taxonomy | Principal/membership inactive + old token, mismatch/missing, inactive-binding/missing, integrity ve validity/revocation parametrik testleri | **KAPALI** |
| Adım 9 — `IdentityResolutionError` exact contract eksikliği | Enum değerleri, constructor-derived metadata ve safe repr/serialization davranışı executable değildi | Exact closed enum, immutable business fields, metadata-derived retry/audit/metric/message ve cause-redaction sözleşmesi tanımlandı | `IdentityResolutionErrorCode` + `IdentityResolutionError(code, correlation_id)`; HTTP mapping içermez | Exhaustive enum/metadata, unknown-code, deterministic metadata/equality/repr ve raw DB leak testleri | **KAPALI** |
| Adım 9 — `tokens_valid_after` precision conflict | JWT bölümü tam saniye storage, repository bölümü mikrosaniye `TIMESTAMPTZ` ve no-truncation söylüyordu | PostgreSQL mikrosaniye authoritative seçildi; NumericDate whole-second UTC instant, direct timestamp comparison ve non-null boundary kilitlendi | Exact UTC normalization, `iat < / == / > effective boundary`, `max(tokens_valid_after,membership_valid_from)` | `.000000/.000001/.999999`, +1 saniye, max boundary, PostgreSQL round-trip, timezone conversion ve no-truncation | **KAPALI** |
| Adım 9 — DTO-local vs repository-proven permission invariant conflict | DTO yalnız role code taşıdığı halde custom-role permission safety'yi constructor'ın yeniden doğrulaması isteniyordu | DTO yalnız taşıdığı UUID/status/time/role/proof formatını doğrular; authoritative permission/relationship safety repository'ye verildi | `role_set_digest`, `permission_registry_version`, `tenant_policy_version`, exact reference; trusted `RoleAdministrationPort` | DTO format/immutability negatifleri ayrı; repository SERVICE/HUMAN safety, registry/digest/version/corruption testleri ayrı | **KAPALI** |
| Adım 10 — `SecurityAction` contract eksikliği | Permission, operation, strength, predicate, hiding ve audit girdileri adapter yorumuna açıktı | Exact immutable alanlar, dört kapalı enum ve registry invariant'ları kilitlendi | `SecurityAction`, `PolicyOperationKind`, `SubjectPredicateKind`, `PolicyExistenceHiding`, `PolicyAuditRequirement` | Closed enum, immutable DTO, invalid action/permission/version, import guard | **KAPALI** |
| Adım 10 — `ResourceSecurityScope` contract eksikliği | Resource owner/tenant/company/period/subject alanları için tek canonical projection yoktu | Typed identifier, required/forbidden alan matrisi, ownership state ve deterministic resource version tanımlandı | `ResourceSecurityScope`, `ResourceOwnershipState` | Resource-type constructor, same/cross tenant, owner/initiator, invalid partial scope | **KAPALI** |
| Adım 10 — Policy result / 5.0C decision belirsizliği | Internal engine sonucunun public 5.0C `AuthorizationDecision`'ı değiştirebileceği ima ediliyordu | Internal 17-reason `PolicyEvaluationResult` ayrıldı; audit delivery reason'ı Adım 11 taxonomy'sine verildi; public mapping yalnız Adım 11'e bırakıldı | `PolicyOutcome`, `PolicyReasonCode`, `PolicyEvaluationResult`, `AuthorizationAdapterDecisionCode` | 17 engine reason reachability + ayrı audit-unavailable adapter testi | **KAPALI** |
| Adım 10 — Custom-role permission materialization eksikliği | `VerifiedLocalIdentity` permission listesi taşımadığı için custom roller değerlendirilemiyordu | Built-in/custom aynı PostgreSQL proof-revalidation yoluna bağlandı; positive cache yasaklandı | `PolicyMaterializationRequest`, `EffectivePermissionSet`, `AuthorizationPolicyRepositoryPort` | HUMAN/SERVICE custom role, stale version/digest/reference, immediate mutation visibility | **KAPALI** |
| Adım 10 — Resource ownership portu eksikliği | Kaynak sahipliği ve outage semantiği router/repository yorumuna kalıyordu | Sekiz durable kaynak için `ResourceSecurityRepositoryPort`, üç sentetik scope için ayrı resolver, exact path matrisi ve short read-only snapshot sınırı seçildi | `resolve_durable_scope(...)`, `SyntheticSecurityScopeResolverPort` ve 8+3 çözüm yolu | not-found/cross-tenant hiding, sentetik scope, DB outage/timeout, relational corruption | **KAPALI** |
| Adım 10 — Subject predicate semantiği eksikliği | SELF/INITIATOR/SAME_TENANT karşılaştırmaları kapalı değildi ve owner kontrolü predicate ile karışabiliyordu | Beş predicate için exact, case-sensitive input/decision tablosu getirildi; owner kontrolü yalnız `OwnershipRequirement`'a verildi | `SubjectPredicateKind` + `OwnershipRequirement` evaluation contract | match/mismatch, owner-required, missing subject metadata, hiding, raw-subject leak | **KAPALI** |
| Adım 10 — Audit failure sahipliği belirsizliği | Policy evaluation ile required audit delivery aynı katmanda yorumlanabiliyordu | Engine yalnız deterministic `AuditIntent` üretir; sink/delivery/fail-closed mapping yalnız Adım 11'e ayrıldı | `AuditIntent`, audit-requirement manifesti | Adım 10 intent; Adım 11 outage/delivery/decision mapping | **KAPALI** |
| Adım 10 — Pre-persistence testi yanlış adımdaydı | Genel authorization test grubu pre-persistence revoke'u pure engine kapısına dahil ediyordu | Bölüm 27.5.2 pure engine ve Bölüm 27.5.3 adapter/revalidation kapıları ayrıldı | Exact Adım 10/11 test sahipliği | Adım 10 registry/policy; Adım 11 revoke/resume-source/audit regression | **KAPALI** |
| **CRITICAL — Strength conversion eksikliği** | Permission metadata enum'u ile internal policy strength ekseni arasında exact compiler yoktu | BASIC→PASSWORD, STRONG→MFA, PHISHING_RESISTANT→PHISHING_RESISTANT kilitlendi; SERVICE_CREDENTIAL ayrı eksen oldu | Exhaustive strength lookup + HUMAN/SERVICE cross-axis kuralları | 33 compiled action, unknown source strength, iki eksen negatifleri | **KAPALI** |
| **HIGH — Permission action mapping eksikliği** | Special read action'lar fallback “remaining” grubuna düşebilirdi | Tüm unique source action literal'ları exact immutable operation lookup'a alındı | 23-row action→operation mapping + 33-row action manifesti | Golden 33, special reads, no fallback, unknown action | **KAPALI** |
| **CRITICAL — Ownership/predicate çelişkisi** | Resource owner eşitliği ile action-level subject predicate aynı reason/boolean'a indirgenmişti | Tenant ownership, resource-owner requirement ve subject predicate ayrı fail-fast basamaklara ve ayrı reason'lara bölündü; `OWNER` predicate kaldırıldı | `OwnershipRequirement`, ownership-state decision table + Steps 11–14 | owner mismatch, tenant-wide non-owner access, SYSTEM/SHARED ve predicate independence | **KAPALI** |
| **HIGH — SELF engine input eksikliği** | SELF target subject engine imzasında yoktu | Exact immutable request ve predicate-required/forbidden girdiler tanımlandı | `PolicyEvaluationRequest` + yeni engine signature | SELF/EXPLICIT/INITIATOR/SAME_TENANT/NONE ve redaction | **KAPALI** |
| **HIGH — Audit-event üretimi belirsizliği** | Event adı, severity ve required flag caller/adapter yorumuna açıktı | Event formülü, 17 reason metadata'sı ve HMAC subject reference kilitlendi | Immutable `AuditIntent` | Exact 17 names/metadata, override rejection, ordering independence | **KAPALI** |
| **HIGH — Resource-version codec eksikliği** | “Canonical JSON” type/precision/order/null semantiğini kilitlemiyordu | Typed framed byte codec, 11 scope manifesti ve ayrı 11 primitive + 11 production SHA vector tanımlandı | `ResourceSecurityVersionCodec v1`, `rsv1:<sha256>` | 11 primitive, 11 full production, type/order/time/null/mutation ve invalid-manifest negatives | **KAPALI** |
| **HIGH — Golden/reachability test kapısı eksikliği** | Compiler alanları, dead reason'lar ve canonical bytes birebir kabul kapısı değildi | Adım 10 kapısı literal manifest, 17-reason reachability, ownership/predicate ve iki codec-vector setiyle genişletildi | Bölüm 27.5.2 executable acceptance matrix | 33 action, 17 reason, 11+11 vector, repository error ve adapter-order testleri | **KAPALI** |
| **CRITICAL — SUBJECT_OWNED action-policy conflict** | `SUBJECT_OWNED` sınıflandırması non-owner erişimini action'dan bağımsız otomatik reddediyordu | Sınıflandırma yalnız metadata yapıldı; owner zorunluluğunun tek sahibi closed `ownership_requirement` oldu | `OwnershipRequirement`, 33-action `Own` golden alanı ve action-family decision table | cancel.any/own, owner-missing, same-tenant cross-subject read/resume, cross-tenant hide | **KAPALI** |
| **CRITICAL — Sentetik scope resolver yokluğu** | SYSTEM, TENANT ve COMPANY_PERIOD durable resource gibi veya adapter yorumuyla çözülebiliyordu | Closed 11-scope enum ve ayrı exact sentetik resolver seçildi | `PolicyScopeType`, `SyntheticSecurityScopeResolverPort`, identifier/relation/version tabloları | 3 sentetik scope success/negative/outage/determinism | **KAPALI** |
| **CRITICAL — Invalid production codec golden vectors** | Primitive encoder örnekleri production scope kabul vektörü gibi sayılıyordu | Primitive ve production acceptance setleri kesin ayrıldı; her 11 scope için tam manifest literal olarak donduruldu | 11 primitive vector + 11 full production vector | constructor acceptance, partial/unknown/forbidden/type/time/relation negatives | **KAPALI** |
| **CRITICAL — Cross-tenant not-found ambiguity** | Repository ile engine arasında existence-hiding sahipliği belirsizdi | Model A seçildi: tenant-qualified query, unknown/cross-tenant aynı `RESOURCE_NOT_FOUND`, secondary lookup yasak | Durable ve synthetic resolver hiding/telemetry contract'ı | indistinguishable outcome, no unscoped fallback, synthetic mismatch, missing-permission ordering | **KAPALI** |
| **HIGH — Step 7 sub-precedence ambiguity** | Aynı snapshot'taki store/role/version/proof/state hataları için tek sonuç yoktu | 7.1–7.11 fail-fast alt-sırası ve çoklu-hata golden kararları kilitlendi | Permission-materialization decision table | tüm satırlar ve 11 literal multi-error case | **KAPALI** |
| **HIGH — Step 10 sub-precedence ambiguity** | Malformed input, outage, not-found, corruption, state ve codec hataları çakışabiliyordu | 10.1–10.11 fail-fast alt-sırası, unresolved reference topolojisi ve Model A sonuçları kilitlendi | Resource-resolution decision table + `ResourceSecurityReference` | tüm satırlar ve 17 literal multi-error case | **KAPALI** |
| **HIGH — Subject-reference hash framing gap** | Subject pseudonymization framing/key-version semantiği adapter'a bırakılmıştı | Exact length-prefixed HMAC-SHA256 frame, domain separator ve `srh1` output seçildi | `SubjectReferenceHashCodec v1` | 5 literal HMAC vector, malformed/missing/unicode/rotation/redaction | **KAPALI** |
| **RELATED — PolicyRepositoryError immutability gap** | Repository hatasının metadata/cause yüzeyi ile write/delete/subclass ve correlation repr yolları mutasyona veya sızıntıya açıktı | Keyword-only validated constructor, derived metadata, frozen set/delete guards, exact `__init_subclass__`, single safe-message args, correlation-redacted repr ve hidden cause kilitlendi | 9-code executable `PolicyRepositoryError` contract'ı | exhaustive metadata, exact signature/args, field/args/new-attribute/delete mutation, subclass, unknown code, correlation redaction ve raw-cause suppression | **KAPALI** |
| **RELATED — Terminal result-construction recursion** | Sonuç constructor'ı bozulduğunda aynı constructor ile normalization recursive failure yaratabilirdi | İkinci result construction yasaklandı; exact immutable safe internal terminal exception seçildi | `PolicyEvaluationConstructionError` ve Adım 11 fail-closed mapping sınırı | invalid result fields, no second constructor, mutation/subclass rejection, safe terminal error, no leak | **KAPALI** |
| **RELATED — Execution run identifier ambiguity** | Execution manifestindeki `run_id` internal FK ile external run kimliğini ayırmıyordu | Exact internal UUID FK alanı seçildi | `orchestration_run_id: UUID` → `orchestration_engine_executions.run_id` → `orchestration_runs.id` | exact join/ownership ve production execution digest vector | **KAPALI** |
| **CRITICAL — `analysis.cancel.own` çift semantiği** | Compiler prose ile invariant/golden manifest farklı predicate davranışı tanımlıyordu | Tek karar `cancel.own=RESOURCE_OWNER_REQUIRED/NONE`, `cancel.any=NONE/NONE`; owner/initiator fallback yasaklandı | Compiler, 33-action manifest, action-family ve endpoint matrisi | owner/non-owner/initiator-only/missing-owner/canonical-name tests | **KAPALI** |
| **CRITICAL — Resource-resolution topoloji çelişkisi** | Engine request'i resolved scope taşırken Step 10 tekrar resolver çağırıyordu | Request yalnız unresolved immutable reference taşır; resolver seçimi engine'e, tek authoritative scope resolver çıktısına verildi | `ResourceSecurityReference`, request signature ve production DI/bypass yasağı | spoof/bypass/selection/no-double-resolution/cross-tenant tests | **KAPALI** |
| **HIGH — Trial-balance scope adı çelişkisi** | Closed enum ile final acceptance listesi farklı literal kullanıyordu | Tek exact name/value `TRIAL_BALANCE`; alias ve legacy form fail-closed reddedildi | 11-row enum/manifest/vector/resolver freeze | exact members/values/set equality/no-alias tests | **KAPALI** |
| **HIGH — Multi-error test kapısı dolaylıydı** | Alt-sıra tablosu zorunlu kombinasyonların tamamını literal expected result olarak dondurmuyordu | Step 7 için 11, Step 10 için 17 named golden case ve no-later-call property eklendi | S7-01..11 ve S10-01..17 acceptance matrices | exact reason/outcome/retry/hiding/audit/metric/call-count tests | **KAPALI** |
| **HIGH — Terminal exception immutability eksikliği** | `__slots__` tek başına field/new-attribute/delete/args mutasyonunu kapatmıyordu | Frozen constructor, derived constants, guarded set/delete, safe surface ve hidden cause tanımlandı | Exact `PolicyEvaluationConstructionError` Python-benzeri contract | signature/constants/mutation/subclass/safe repr/raw-cause tests | **KAPALI** |

Revizyon sonucu: önceki Adım 9/10 bulgularına ek olarak son hedefli denetimdeki **2 kritik + 3 yüksek**, son doğrulamadaki **3 yüksek** ve kapanış bütünlük döngüsünde saptanan `PolicyRepositoryError.args/repr` güvenli yüzeyine ait **2 yüksek** blocking bulgu kapalıdır; kalan blocking karar: **0**. Adım 10 engine taxonomy'si **17**, top-level precedence'i **18 basamak**, permission-materialization alt-sırası **11 basamak** ve resource-resolution alt-sırası **11 basamak**tır. Multi-error kabul yüzeyi Step 7 için **11**, Step 10 için **17** literal case; codec kabul yüzeyi **11 primitive unit vector** ile ayrı **11 full production-scope vector** içerir. Adım 11 için ayrıca **47 decision code + 8 context + 6 audit + 19 identity + 17 policy-reason** kapalı mapping yüzeyi ve **4 ADR golden vector** tanımlıdır. Kalan OD-1–OD-4 yalnız deployment/operasyon seçimleridir ve startup/readiness invariant'larını gevşetemez. Design Readiness **%100**; runtime/Production Readiness Adım 11 implementasyonu ve kabul testleri tamamlanana kadar mevcut çalışan aşamalarla sınırlıdır. Adım 11 executable architecture seviyesinde implementasyona hazırdır; implementasyon yalnız ayrıca kullanıcı onayıyla başlayabilir.

---

## 38. Adım 11 Tasarım Revizyonu ve Bağımsız Kapanış Denetimi

| Blocking bulgu | Kök neden | Uygulanan düzeltme | Executable sözleşme | Kapanış |
|---|---|---|---|---|
| Trusted identity/context girdisi yoktu | Frozen `AuthorizationPort` scope+audit context'i token freshness ve identity proof taşımıyordu | Identity kaynağı audit DTO'dan ayrıldı; request-bound trusted context consumer portu tanımlandı, implementation Adım 12'de bırakıldı | `TrustedAuthorizationContext`, `TrustedAuthorizationContextProviderPort`, 8-code taxonomy, checkpoint/resource binding | **KAPALI** |
| Audit intent delivery mapping'i yoktu | Adım 10 intent alanları mevcut 5.0C audit event'ine kayıpsız/idempotent bağlanmamıştı | Exact projection, explicit bounded scope/referencing, HMAC subject, idempotency key, receipt ve 6-code failure taxonomy kilitlendi | `AUTHORIZATION_GRANTED/DENIED` mapping, safe attributes, `aik1/rr1/tr1/qr1/ar1` references | **KAPALI** |
| `AuthorizationDecision` mapping'i açık değildi | 17 reason'ın grant/revoke/code/reference davranışı adapter yorumuna kalıyordu | 17/17 literal policy table, 19 identity, 8 context, 6 audit mapping'i ve terminal fallback tanımlandı | Existing 5.0C DTO + internal closed decision codes + `AuthorizationDecisionReferenceCodec v1` | **KAPALI** |
| Revalidation/TOCTOU sınırı belirsizdi | Security read ile 5.0B write ayrı transaction sahipleriydi | Fresh last-check-before-write, source tekrar kontrolü, zero persistence after deny ve dürüst bounded TOCTOU garantisi seçildi | `PRE_PERSIST_*` checkpoints; separate short snapshots; no cache/shared transaction claim | **KAPALI** |
| Kapanış audit'i — checkpoint freshness ve dispatch | Request boyunca sabit `resolved_at` uzun execution sonunda expiry'yi göremiyor; mevcut ikinci public çağrı revalidation checkpoint'ini kanıtlamıyordu | `resolved_at` checkpoint-local yapıldı; zorunlu internal revalidation dependency ve exact service dispatch kilitlendi | `AuthorizationRevalidationPort`, same-instance production wiring, no fallback/heuristic | **KAPALI** |
| Kapanış audit'i — cancel custom-role yolu | Yalnız ownership mismatch fallback'i, sadece `cancel.any` taşıyan geçerli HUMAN custom rolünü erişilemez yapıyordu | HUMAN için ownership mismatch veya own-permission-missing exact fallback; diğer terminallerde sıfır fallback seçildi | Deterministic cancel decision/call-count table | **KAPALI** |
| Kapanış audit'i — audit/ADR integration | Existing 5.0C boundary audit ile detailed event ilişkisi ve policy öncesi ADR null alanları açık değildi | İki audit kaydının ayrı semantiği, typed sink normalization, pseudonymous actor ve pre-policy ADR literal normalization tanımlandı | 6-code typed audit error, `srh1` actor, terminal ADR input table | **KAPALI** |

Bağımsız bütünlük denetimi sonuçları:

- Altı public `AuthorizationPort` imzası ve beş alanlı `AuthorizationDecision` değişmemiştir.
- Context provider implementation'ı Adım 12'de, endpoint permission/router wiring'i Adım 13'te, legacy route protection Adım 14'te kalmıştır.
- Adım 11 raw token/header/claim, HTTP status, router, SQLAlchemy session veya persistence transaction sahiplenmez.
- ALLOW/DENY/INDETERMINATE, audit required/outage ve revoked ayrımları çakışmasızdır; provider/audit/store outage hiçbir zaman grant veya revoked üretmez.
- Resume source initial allow sonucu reuse edilmez; target ve source persistence öncesi fresh değerlendirilir.
- Audit event'in provisional reference ile final decision reference arasındaki causal fark explicit ve deterministic'tir.
- Initial ve pre-persistence checkpoint zamanları ayrıdır; uzun execution sırasında expiry/staleness fail-closed görülür.
- Existing application-boundary audit ile Adım 11 detailed event ayrı ve güvenli kayıtlardır; raw subject her ikisinde de yasaktır.
- HUMAN custom role yalnız `analysis.cancel.any` taşısa da exact fallback ile kullanılabilir; SERVICE veya hidden/integrity/outage yolu fallback açmaz.
- Zero-TOCTOU iddiası yapılmaz; mevcut frozen transaction topolojisinin sağlayabildiği exact sınır belgelenmiştir.
- Yeni schema/model/migration veya public contract değişikliği gerekmemektedir.
- Kritik blocking: **0**. Yüksek blocking: **0**. Design Readiness: **%100**.

**Adım 11 — 5.0C AuthorizationPort adapter tasarımı FINAL olarak onaylanabilir ve implementasyona hazırdır.**
