#!/usr/bin/env bash
# Set up a repository of an old static site hosted on bunny.net (vault OldSites).
# The template files are copied from OrangeJuice97 first (see README.md,
# "Reuse for another site"); this script then fills in the site-specific parts.
#
#   scripts/bootstrap.sh init <repo> <storage-zone> <pull-zone>
#       site.json (ids and hostname looked up on bunny.net), infra/secrets.env,
#       state passphrase generated in Proton Pass (never shown), files of the
#       storage zone downloaded into site/, README title.
#   scripts/bootstrap.sh github
#       public GitHub repository <owner>/<repo> (if missing) and its secrets
#       BUNNY_API_KEY and TF_VAR_STATE_PASSPHRASE, read from Proton Pass.
#
# Needs: pass-cli (logged in), gh (logged in), tofu, jq, curl, python3.
set -euo pipefail

cd "$(dirname "$0")/.."
VAULT=OldSites
API_KEY_REF="pass://$VAULT/bunny-api-key/password"

with_api_key() {
  pass-cli run --env-file <(echo "BUNNYNET_API_KEY=$API_KEY_REF") -- "$@"
}

cmd_init() {
  local repo=$1 zone=$2 pz=$3
  [ -n "$repo" ] && [ -n "$zone" ] && [ -n "$pz" ] || { echo "usage: $0 init <repo> <storage-zone> <pull-zone>"; exit 1; }

  echo "Looking up $zone / $pz on bunny.net..."
  # shellcheck disable=SC2016
  with_api_key sh -c '
    set -e
    zone_id=$(curl -fsS -H "AccessKey: $BUNNYNET_API_KEY" "https://api.bunny.net/storagezone?perPage=1000" \
      | jq -e --arg n "$1" "[.[] | select(.Name == \$n and (.Deleted | not))][0].Id")
    curl -fsS -H "AccessKey: $BUNNYNET_API_KEY" "https://api.bunny.net/pullzone?perPage=1000" \
      | jq -e --arg repo "$3" --arg zone "$1" --argjson zone_id "$zone_id" --arg pz "$2" "
          (if type == \"object\" then .Items else . end) | [.[] | select(.Name == \$pz)][0]
          | if .StorageZoneId != \$zone_id then error(\"pull zone \(\$pz) does not serve storage zone \(\$zone)\") else . end
          | [.Hostnames[] | select(.IsSystemHostname | not) | .Value] as \$h
          | if (\$h | length) != 1 then error(\"expected one custom hostname, got \(\$h)\") else . end
          | {repo: \$repo, storage_zone: \$zone, storage_zone_id: \$zone_id, pullzone: \$pz, pullzone_id: .Id, hostname: \$h[0]}" > site.json
  ' sh "$zone" "$pz" "$repo"
  cat site.json

  local item="$repo-tofu-state-passphrase"
  if pass-cli item list --vault-name "$VAULT" | grep -q ": $item "; then
    echo "Proton Pass item $item already exists."
  else
    pass-cli item create login --vault-name "$VAULT" --title "$item" --generate-password=40 >/dev/null
    echo "Proton Pass item $item created."
  fi
  sed -i '' -e "s|^TF_VAR_state_passphrase=.*|TF_VAR_state_passphrase=pass://$VAULT/$item/password|" infra/secrets.env
  sed -i '' -e "1s|^# .*|# $repo|" README.md

  if [ -d site ] && [ -n "$(find site -type f | head -1)" ]; then
    echo "site/ already holds files: not downloaded again."
  else
    with_api_key python3 scripts/import_storage.py
  fi

  (cd infra && rm -f terraform.tfstate && pass-cli run --env-file secrets.env -- sh -c 'tofu init -input=false >/dev/null && tofu plan -input=false -no-color' | grep -E "will be|Plan:|^\s+~ ")
  with_api_key python3 scripts/deploy.py --dry-run
  python3 scripts/smoke_test.py
}

cmd_github() {
  local repo owner
  repo=$(jq -r .repo site.json)
  owner=$(gh api user --jq .login)
  if gh repo view "$owner/$repo" >/dev/null 2>&1; then
    echo "Repository $owner/$repo already exists."
  else
    gh repo create "$owner/$repo" --public --description "Old static site $(jq -r .hostname site.json), hosted on bunny.net"
  fi
  # Secrets go from Proton Pass to GitHub through stdin: never shown nor written.
  # shellcheck disable=SC2016
  pass-cli run --env-file infra/secrets.env -- sh -c '
    printf %s "$BUNNYNET_API_KEY" | gh secret set BUNNY_API_KEY --repo "$1"
    printf %s "$TF_VAR_state_passphrase" | gh secret set TF_VAR_STATE_PASSPHRASE --repo "$1"
  ' sh "$owner/$repo"
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$owner/$repo.git"
}

case "${1:-}" in
  init) shift; cmd_init "${1:-}" "${2:-}" "${3:-}" ;;
  github) cmd_github ;;
  *) echo "usage: $0 init <repo> <storage-zone> <pull-zone> | github"; exit 1 ;;
esac
