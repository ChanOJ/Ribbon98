# The whole bunny.net setup of the site: a storage zone holding the files
# (site/, deployed by scripts/deploy.py), a pull zone (CDN) in front of it and
# its public hostname. Every value specific to the site comes from site.json.
#
# DNS is not managed here: the hostname is a CNAME to the pull zone system
# hostname (output cdn_hostname) at the registrar (Infomaniak).

locals {
  site = jsondecode(file("${path.module}/../site.json"))
}

resource "bunnynet_storage_zone" "this" {
  name                = local.site.storage_zone
  region              = "DE"
  replication_regions = []
  zone_tier           = "Standard"

  custom_404_file_path = lookup(local.site, "not_found_page", null)
  rewrite_404_to_200   = false

  # Names cannot change on bunny.net: a new name replaces the zone. The new
  # one is created first; the apply workflow then deploys site/ to it.
  lifecycle {
    create_before_destroy = true
  }
}

resource "bunnynet_pullzone" "this" {
  name = local.site.pullzone

  origin {
    type        = "StorageZone"
    storagezone = bunnynet_storage_zone.this.id
  }

  routing {
    tier  = "Standard"
    zones = ["EU"]
  }

  cors_enabled    = true
  cors_extensions = ["css", "eot", "gif", "jpeg", "jpg", "js", "mp3", "mp4", "mpeg", "png", "svg", "ttf", "webm", "webp", "woff", "woff2"]

  block_no_referer = true
  cache_chunked    = true
  log_anonymized   = true

  # CDN cache: 30 days (purged by scripts/deploy.py on each deployment);
  # browsers: as told by the origin.
  cache_expiration_time         = 2592000
  cache_expiration_time_browser = -1

  # TLS security level: "Compatible" drops TLS 1.0/1.1 and the weak RSA/CBC
  # cipher suites allowed by "Legacy".
  tls_level   = "Compatible"
  tls_support = []

  # A new name replaces the pull zone (system hostname <name>.b-cdn.net):
  # the new one is created first, then the hostname moves to it.
  lifecycle {
    create_before_destroy = true
  }
}

resource "bunnynet_pullzone_hostname" "this" {
  pullzone    = bunnynet_pullzone.this.id
  name        = local.site.hostname
  tls_enabled = true
  force_ssl   = true
}

# Edge rules: read-only, security headers, isolation, archives as downloads
# (same model as the other archives). The pages are plain HTML (no script, no
# form, no remote resource; only outbound links), so the CSP is strict.
locals {
  csp = join("; ", [
    "default-src 'self'",
    "script-src 'none'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "media-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'self'",
    "form-action 'none'",
    "base-uri 'self'",
    "connect-src 'self'",
  ])

  archive_extensions = ["rar", "zip", "lha", "arj", "exe"]
}

# 1. Anything but GET/HEAD/OPTIONS is refused at the edge, before the origin.
resource "bunnynet_pullzone_edgerule" "read_only" {
  pullzone    = bunnynet_pullzone.this.id
  description = "Read-only: block every method except GET, HEAD, OPTIONS"
  enabled     = true
  priority    = 1
  match_type  = "MatchAll"

  triggers = [{
    type       = "RequestMethod"
    match_type = "MatchNone"
    patterns   = ["GET", "HEAD", "OPTIONS"]
    parameter1 = null
    parameter2 = null
  }]

  actions = [{ type = "BlockRequest", parameter1 = null, parameter2 = null, parameter3 = null }]
}

# 2. Security headers on every response.
resource "bunnynet_pullzone_edgerule" "security_headers" {
  pullzone    = bunnynet_pullzone.this.id
  description = "Security headers"
  enabled     = true
  priority    = 2
  match_type  = "MatchAny"

  triggers = [{
    type       = "Url"
    match_type = "MatchAny"
    patterns   = ["*"]
    parameter1 = null
    parameter2 = null
  }]

  actions = [
    { type = "SetResponseHeader", parameter1 = "Content-Security-Policy", parameter2 = local.csp, parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "X-Content-Type-Options", parameter2 = "nosniff", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "Referrer-Policy", parameter2 = "no-referrer", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "X-Frame-Options", parameter2 = "SAMEORIGIN", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "Strict-Transport-Security", parameter2 = "max-age=31536000", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "Permissions-Policy", parameter2 = "camera=(), microphone=(), geolocation=(), payment=()", parameter3 = null },
  ]
}

# 2b. Cross-origin isolation.
resource "bunnynet_pullzone_edgerule" "isolation" {
  pullzone    = bunnynet_pullzone.this.id
  description = "Cross-origin isolation (COOP/CORP)"
  enabled     = true
  priority    = 3
  match_type  = "MatchAny"

  triggers = [{
    type       = "Url"
    match_type = "MatchAny"
    patterns   = ["*"]
    parameter1 = null
    parameter2 = null
  }]

  actions = [
    { type = "SetResponseHeader", parameter1 = "Cross-Origin-Opener-Policy", parameter2 = "same-origin", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "Cross-Origin-Resource-Policy", parameter2 = "same-origin", parameter3 = null },
  ]
}

# 3. Untrusted legacy archives/binaries: never interpreted, always downloaded.
resource "bunnynet_pullzone_edgerule" "archives" {
  pullzone    = bunnynet_pullzone.this.id
  description = "Archives: octet-stream + Content-Disposition attachment"
  enabled     = true
  priority    = 4
  match_type  = "MatchAny"

  triggers = [{
    type       = "UrlExtension"
    match_type = "MatchAny"
    patterns   = local.archive_extensions
    parameter1 = null
    parameter2 = null
  }]

  actions = [
    { type = "SetResponseHeader", parameter1 = "Content-Type", parameter2 = "application/octet-stream", parameter3 = null },
    { type = "SetResponseHeader", parameter1 = "Content-Disposition", parameter2 = "attachment", parameter3 = null },
  ]
}

output "storage_zone_name" {
  value = bunnynet_storage_zone.this.name
}

output "pullzone_id" {
  value = bunnynet_pullzone.this.id
}

output "cdn_hostname" {
  description = "bunny.net system hostname, target of the DNS CNAME record."
  value       = "${bunnynet_pullzone.this.name}.${bunnynet_pullzone.this.cdn_domain}"
}
