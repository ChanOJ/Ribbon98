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
