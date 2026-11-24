# Resources created by hand in the bunny.net dashboard are adopted into the
# state on the first apply, when site.json gives their ids. Remove the ids once
# they are in the state (and always before renaming a zone): these blocks then
# do nothing.

locals {
  adopt = lookup(local.site, "storage_zone_id", null) != null
}

import {
  for_each = local.adopt ? toset(["this"]) : toset([])
  to       = bunnynet_storage_zone.this
  id       = tostring(local.site.storage_zone_id)
}

import {
  for_each = local.adopt ? toset(["this"]) : toset([])
  to       = bunnynet_pullzone.this
  id       = tostring(local.site.pullzone_id)
}

import {
  for_each = local.adopt ? toset(["this"]) : toset([])
  to       = bunnynet_pullzone_hostname.this
  id       = "${local.site.pullzone_id}|${local.site.hostname}"
}
