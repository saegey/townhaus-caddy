# frigate-infra

Infrastructure-oriented Docker Compose deployment for Frigate on Debian 12 with Intel VAAPI support.

## Repository Layout

- `docker-compose.yml`: Frigate service definition
- `.env.example`: environment variable template
- `config/config.template.yml`: starter Frigate configuration template
- `storage/`: bind-mounted media storage (recordings, clips, snapshots)
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

3. Update `config/config.template.yml`:
- Set MQTT broker credentials to match the existing external Home Assistant MQTT broker.
- Set `mqtt.port` if your broker is not on `1883`.
- Replace the placeholder RTSP URL in `cameras.front_door.ffmpeg.inputs[0].path`, then set `enabled: true` when ready.
- Set `go2rtc.homekit.<camera>.pin` (or `FRIGATE_HOMEKIT_PIN` in `.env`) for Apple Home pairing.

At startup, `./scripts/start.sh` seeds `/srv/storage/frigate-config/config.yml` from this template
only if the runtime config does not already exist.

4. Start Frigate:

```bash
./scripts/start.sh
```

5. Open Frigate UI:
- `http://<host-ip>:5000`

6. Open go2rtc UI for HomeKit pairing:
- `http://<host-ip>:1984`

## Operations

- Start: `./scripts/start.sh`
- Stop: `./scripts/stop.sh`
- Logs: `./scripts/logs.sh`
- Update to latest stable image: `./scripts/update.sh`

## HomeKit Notes

- Frigate is configured with `network_mode: host`, which is the recommended path for go2rtc HomeKit discovery and pairing.
- Pair cameras from go2rtc UI (`http://<host-ip>:1984`) and add them in Apple Home using the PIN in your config.

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
