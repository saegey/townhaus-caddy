# townhaus-caddy

Homelab monorepo managing a Caddy reverse proxy stack, Frigate NVR, Raspberry Pi audio services, CamillaDSP, Beszel monitoring, and AdGuard DNS — all deployed via Ansible.

## Hosts

| Host | Role |
|---|---|
| `beelink.local` | Main server — Caddy, AdGuard, Immich, Beszel Hub |
| `aswitch.local` | Audio Pi — Shairport, CamillaDSP, GPIO relay services |
| `pi-cam.local` | Lounge Pi — Shairport, CamillaDSP, DAC status service |

## Services

### beelink.local (Docker Compose)

| Service | URL | Description |
|---|---|---|
| Caddy | — | Reverse proxy with internal TLS CA |
| AdGuard Home | `https://adguard` | DNS server and ad blocker |
| Immich | `https://immich` | Photo library |
| Frigate | `https://frigate` | NVR / camera |
| Groovenet | `https://groovenet` | Music streaming |
| Home Assistant | `https://ha` | Home automation |
| Scrypted | `https://scrypted` | Camera management |
| UniFi | `https://unifi` | Network management |
| Beszel | `https://beszel` | Node monitoring |
| Uptime Kuma | `https://uptime` | HTTP endpoint monitoring |

### aswitch.local (systemd)

| Service | Description |
|---|---|
| `aswitch.service` | GPIO relay — routes audio source via MQTT |
| `audio_activity.service` | USB audio RMS detector — publishes active/inactive state |
| `camilladsp.service` | DSP engine — EQ and processing |
| `camillagui.service` | CamillaGUI web UI (`https://aswitch`) |
| `shairport-sync.service` | AirPlay receiver → ALSA Loopback → CamillaDSP |

### pi-cam.local (systemd)

| Service | Description |
|---|---|
| `dac_status.service` | USB DAC presence detector — publishes to MQTT |
| `camilladsp.service` | DSP engine — EQ and processing |
| `camillagui.service` | CamillaGUI web UI (`https://pi-cam`) |
| `shairport-sync.service` | AirPlay receiver → ALSA Loopback → CamillaDSP |

### Audio signal chain (both Pis)

```
AirPlay source → Shairport Sync → ALSA Loopback → CamillaDSP → USB DAC → speakers
```

## Repository layout

```
.
├── ansible/
│   ├── ansible.cfg
│   ├── inventory.ini           # gitignored — copy from inventory.ini.example
│   ├── requirements.yml        # ansible-galaxy collections
│   ├── deploy.yml              # beelink Docker stack playbook
│   ├── group_vars/
│   │   ├── all/main.yml        # shared vars (versions, ports, MQTT)
│   │   ├── aswitch.yml         # aswitch-specific vars
│   │   ├── pi_cam.yml          # pi-cam-specific vars
│   │   └── townhaus_caddy/     # beelink vars (gitignored, copy from *.example)
│   ├── playbooks/
│   │   ├── beelink.yml         # AdGuard DNS + Beszel agent + Frigate config
│   │   ├── aswitch.yml         # all aswitch services
│   │   └── pi_cam.yml          # all pi-cam services
│   └── roles/
│       ├── aswitch_services/   # Python services + venv + env from 1Password
│       ├── camilladsp/         # CamillaDSP + CamillaGUI install and config
│       ├── shairport/          # shairport-sync.conf template
│       ├── frigate/            # Frigate config template + 1Password secrets
│       ├── beszel_hub/         # smartmontools for SMART monitoring
│       ├── beszel_agent/       # Beszel agent binary + service + Hub SSH key
│       └── adguard_dns/        # declarative DNS rewrites via AdGuard API
├── camilladsp/
│   └── configs/                # reference EQ presets (scp'd from aswitch)
├── services/
│   ├── aswitch/                # Python source (git subtree from aswitch repo)
│   │   ├── aswitch.py
│   │   ├── audio_activity.py
│   │   ├── dac_status.py
│   │   ├── home_assistant/     # example HA YAML
│   │   └── esphome/            # ESPHome IR blaster config
│   └── frigate/                # Frigate infra (git subtree from frigate-beelink)
│       ├── docker-compose.yml  # standalone compose (superseded by root compose)
│       └── config/             # config template reference
├── Caddyfile
└── docker-compose.yml
```

## Prerequisites

```bash
brew install ansible 1password-cli just
ansible-galaxy collection install -r ansible/requirements.yml
op signin
```

## First-time setup

```bash
# Inventory
cp ansible/inventory.ini.example ansible/inventory.ini
# Edit ansible/inventory.ini — add ansible_host=<IP> for any host where mDNS is unreliable

# beelink vars
cp ansible/group_vars/townhaus_caddy/main.yml.example ansible/group_vars/townhaus_caddy/main.yml
cp ansible/group_vars/townhaus_caddy/beszel.yml.example ansible/group_vars/townhaus_caddy/beszel.yml
# Edit both files — set 1Password refs, beelink LAN IP, AdGuard credentials
```

**1Password items required** (all in the `Homelab` vault):

| Item | Fields |
|---|---|
| `Immich Database` | `password` |
| `Backblaze Immich` | `key_id`, `application_key`, `restic_password` |
| `MQTT` | `username`, `password` |
| `AdGuard` | `username`, `password` |
| `Frigate` | `mqtt_password`, `doorbell_rtsp_url`, `doorbell_talk_rtsp_url`, `backyard_rtsp_url`, `backyard_rtsp_sub_url`, `homekit_pin` |

## Deploying

```bash
# Show every available command
just

# Deploy the Docker stack and host roles on beelink
just deploy-beelink

# Deploy either Pi
just deploy-aswitch
just deploy-pi-cam

# Deploy all hosts
just deploy

# Validate playbook syntax and the working diff
just check
```

The lower-level `just deploy-stack` and `just configure-beelink` recipes are
available when only the Compose stack or host roles need to change.

## Dotfiles

Linux hosts can optionally install your dotfiles repo into `~/.dotfiles` and
apply the Stow-managed files into the target user's home directory.

The Ansible role is opt-in and assumes Debian-family hosts. It installs the
required packages, clones the repo, runs `stow --restow` for the configured
packages, and can set the user's default shell to `zsh`.

To enable it for a host group, add variables to the relevant group vars file:

```yaml
dotfiles_enabled: true
dotfiles_repo: https://github.com/saegey/dotfiles.git
```

For example:

- `ansible/group_vars/aswitch.yml`
- `ansible/group_vars/pi_cam.yml`
- `ansible/group_vars/townhaus_caddy/main.yml`

Because the repo is public, the default uses HTTPS and does not require SSH
keys on the target hosts. The clone is also shallow by default (`depth: 1`,
single branch) because the hosts only need the current dotfiles tree, not full
history.

The role intentionally does not run the dotfiles repo's interactive bootstrap
scripts. Those scripts call `sudo` internally, which does not compose cleanly
with Ansible's privilege escalation. The role applies the Stow-managed files
directly and installs the Debian-side prerequisites itself.

## CamillaDSP presets

Seven EQ presets are managed in `ansible/roles/camilladsp/templates/configs/` and deployed to both Pis. The ALSA capture/playback devices are set per-host in `group_vars`:

| Preset | Description |
|---|---|
| `camilla.yml` | Default — light bass boost |
| `flat.yml` | No processing |
| `reference.yml` | Flat bass/treble at 0 dB |
| `tonecontrol.yml` | Adjustable bass/treble |
| `late-night.yml` | Bass and treble lift for low volumes |
| `relaxed.yml` | Slight presence cut |
| `warm.yml` | Bass lift, treble cut |

Switch presets via the CamillaGUI web UI (`https://aswitch` or `https://pi-cam`).

## Frigate NVR

Frigate runs as a Docker service on beelink with `network_mode: host` (required for go2rtc/HomeKit local discovery). The config is deployed to `/srv/storage/frigate-config/config.yml` by the Ansible `frigate` role.

All credentials (MQTT password, camera RTSP URLs, HomeKit PIN) are stored in 1Password and rendered into the config at deploy time — no plaintext secrets in the repo.

```bash
# First-time setup
cp ansible/group_vars/townhaus_caddy/frigate.yml.example ansible/group_vars/townhaus_caddy/frigate.yml
# Edit frigate.yml — set frigate_mqtt_host, email, and 1Password refs

# Deploy config + start container
just deploy-beelink
```

## Immich backups

Immich is backed up to a private Backblaze B2 bucket with Restic. The backup
role creates a fresh compressed PostgreSQL dump first, then takes an encrypted,
deduplicated snapshot of both the dump and the complete
`IMMICH_UPLOAD_LOCATION`. It retains 7 daily, 5 weekly, and 12 monthly
snapshots. A weekly repository check reads and verifies 5% of the stored data.

The role is opt-in. To configure it:

1. Create a private B2 bucket and note its S3 endpoint. Set its lifecycle rule
   to **Keep only the last version of the file**; Restic manages backup history.
   Do not enable Object Lock because it prevents Restic from pruning snapshots.
2. Create an application key restricted to that bucket with read/write access.
3. Create a `Backblaze Immich` item in the `Homelab` 1Password vault with
   `key_id`, `application_key`, and a separately generated `restic_password`.
   Keep that Restic password permanently; the repository cannot be recovered
   without it. From zsh, create the item without placing secrets in shell
   history or command arguments:

   ```zsh
   read "B2_KEY_ID?Backblaze application key ID: "
   read -s "B2_APPLICATION_KEY?Backblaze application key: " && printf '\n'
   RESTIC_PASSWORD="$(openssl rand -base64 48)"

   op item create \
     --category "Secure Note" \
     --title "Backblaze Immich" \
     --vault Homelab \
     "key_id[concealed]=$B2_KEY_ID" \
     "application_key[concealed]=$B2_APPLICATION_KEY" \
     "restic_password[concealed]=$RESTIC_PASSWORD"

   unset B2_KEY_ID B2_APPLICATION_KEY RESTIC_PASSWORD
   ```

   Verify that all three references resolve without revealing their values:

   ```bash
   for field in key_id application_key restic_password; do
     op read "op://Homelab/Backblaze Immich/$field" >/dev/null || exit 1
   done
   echo "Backblaze Immich credentials are available"
   ```

4. Copy and edit the variables file:

   ```bash
   cp ansible/group_vars/townhaus_caddy/immich_backup.yml.example \
     ansible/group_vars/townhaus_caddy/immich_backup.yml
   ```

5. Deploy the host roles and run the first backup manually:

   ```bash
   just deploy-beelink
   just immich-backup
   just immich-backup-logs
   ```

The daily backup runs around 03:30 local time and the integrity check runs
weekly. Inspect the schedules and most recent result with:

```bash
just immich-backup-status
```

For a restore, recover both `/srv/storage/immich/library` and
`/var/lib/immich-backup/immich-database.sql.gz` from the same Restic snapshot,
then follow Immich's database restore procedure. Test this process before
treating the backup as production-ready.

## AdGuard DNS

DNS rewrites are managed declaratively in `ansible/group_vars/townhaus_caddy/beszel.yml` under `adguard_dns_rewrites`. All short hostnames resolve to beelink's LAN IP; Caddy handles the reverse proxy. Run the beelink playbook to apply changes.

## Beszel monitoring

Beszel Hub runs as a Docker container on beelink (`https://beszel`). Agents run on all three hosts. The Hub's SSH public key is automatically distributed to each agent via the Ansible playbooks — no manual key copying needed.

After running the playbooks, add each host in the Beszel UI (**Add System**) with port `45876`.

beelink runs the agent as root for SMART disk monitoring (`smartmontools` installed automatically).

## Caddy internal TLS

Caddy issues certs from its own local CA. Trust the root cert on your devices:

```bash
mkdir -p ./certs
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./certs/caddy-root.crt

# macOS
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ./certs/caddy-root.crt

# Debian/Ubuntu
sudo cp ./certs/caddy-root.crt /usr/local/share/ca-certificates/caddy-root.crt
sudo update-ca-certificates
```

## Useful commands

```bash
# Reload Caddy config without downtime
just caddy-reload

# Follow logs
just logs caddy
just logs adguardhome
just logs immich-server
just logs beszel-hub

# Check Pi service status
just status-aswitch
just status-pi-cam
```

## Home Assistant reverse proxy

Add to `configuration.yaml`:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 10.0.0.0/8
```
