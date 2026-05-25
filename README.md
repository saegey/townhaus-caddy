# frigate-infra

Infrastructure-oriented Docker Compose deployment for Frigate on Debian 12 with Intel VAAPI support.
Includes optional Scrypted service for camera UX/integration experiments.

## Repository Layout

- `docker-compose.yml`: Frigate service definition
- `.env.example`: environment variable template
- `config/config.yml`: starter Frigate configuration
- `storage/`: bind-mounted media storage (recordings, clips, snapshots)
- `scrypted/`: bind-mounted Scrypted state/config/plugins
- `scripts/`: helper operational scripts

## Prerequisites (Debian 12)

1. Install Docker Engine from Docker's official repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

2. Add your user to required groups and re-login:

```bash
sudo usermod -aG docker "$USER"
sudo usermod -aG video "$USER"
sudo usermod -aG render "$USER"
```

3. Verify Intel render node exists:

```bash
ls -l /dev/dri/renderD128
```

Expected result: device node exists and is accessible to `video`/`render` group members.

4. (Optional but recommended) Verify VAAPI stack with `vainfo`:

```bash
sudo apt-get install -y vainfo intel-media-va-driver-non-free
vainfo
```

`vainfo` should return supported Intel codecs and no fatal initialization errors.

## Setup

1. Clone/create this repo on the Debian host.
2. Copy and edit environment variables:

```bash
cp .env.example .env
```

Important: Frigate config environment substitution expects variables beginning with `FRIGATE_` (for example `FRIGATE_MQTT_HOST`).

3. Update `config/config.yml`:
- Set MQTT broker credentials to match the existing external Home Assistant MQTT broker.
- Set `mqtt.port` if your broker is not on `1883`.
- Replace the placeholder RTSP URL in `cameras.front_door.ffmpeg.inputs[0].path`, then set `enabled: true` when ready.

4. Start Frigate:

```bash
./scripts/start.sh
```

5. Open Frigate UI:
- `http://<host-ip>:5000`

6. (Optional) Use Scrypted UI:
- `https://<host-ip>:10443` (or `http://<host-ip>:11080` on first boot)

## Operations

- Start: `./scripts/start.sh`
- Stop: `./scripts/stop.sh`
- Logs: `./scripts/logs.sh`
- Update to latest stable image: `./scripts/update.sh`

## Scrypted Notes

- Compose includes `scrypted` with `network_mode: host` for best camera discovery compatibility.
- Persistent Scrypted data is stored under `./scrypted`.
- First start can take a minute while plugins initialize.

Start only Scrypted:

```bash
docker compose up -d scrypted
```

Follow Scrypted logs:

```bash
docker compose logs -f scrypted
```

### Recommended Caddy entry (from your proxy stack)

Add this in your Caddy stack if you want internal HTTPS aliasing:

```caddyfile
scrypted, scrypted.home.arpa {
	import common
	reverse_proxy https://beelink.tail0bdbb0.ts.net:10443 {
		transport http {
			tls_insecure_skip_verify
		}
	}
}
```

Then add AdGuard rewrites:
- `scrypted` -> `<beelink-tailscale-ip>`
- `scrypted.home.arpa` -> `<beelink-tailscale-ip>`

## Notes on Hardware Acceleration

- Compose maps `/dev/dri/renderD128` into the container.
- Frigate starter config uses `ffmpeg.hwaccel_args: preset-vaapi`.
- If acceleration does not engage, verify host `vainfo`, group membership (`video`, `render`), and device availability (`/dev/dri/renderD128`).

## Recommended Storage Strategy

For resilient home-lab production behavior:

- Use NVMe for OS and Docker metadata/databases (fast metadata and low latency).
- Use external SSD/HDD for Frigate recordings under `./storage` (capacity and endurance).
- Keep enough free space for retention windows and review clips.

## Security and Reliability Defaults

- Uses `restart: unless-stopped`.
- Uses bind mounts for transparent host-level backup and migration.
- Uses read-only `/etc/localtime` mount for timestamp consistency.
- Uses `tmpfs` cache mount to reduce disk churn for ephemeral cache data.
- Sets `shm_size: 256mb` to satisfy Frigate shared-memory requirements.
