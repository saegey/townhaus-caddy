# Caddy Homelab Reverse Proxy (Tailscale + MagicDNS)

Production-quality Caddy setup for an internal-only homelab network, using:
- Tailscale for private network access
- MagicDNS for upstream service resolution
- Caddy internal CA (`tls internal`) for HTTPS certs

This setup is designed to run from:
- `/srv/docker/caddy`

## Recommended folder structure

```text
/srv/docker/caddy/
├── docker-compose.yml
├── Caddyfile
├── .env
├── certs/
└── README.md
```

## Endpoints

Recommended dedicated internal hostnames:
- `https://frigate` -> `http://beelink.tail0bdbb0.ts.net:5000`
- `https://groovenet` -> `http://beelink.tail0bdbb0.ts.net:3000`
- `https://ha` -> `http://homeassistant.tail0bdbb0.ts.net:8123`
- `https://scrypted` -> `https://host.docker.internal:10443` (via Caddy container -> host gateway)
- `https://frigate.home.arpa` -> `http://beelink.tail0bdbb0.ts.net:5000`
- `https://groovenet.home.arpa` -> `http://beelink.tail0bdbb0.ts.net:3000`
- `https://ha.home.arpa` -> `http://homeassistant.tail0bdbb0.ts.net:8123`
- `https://scrypted.home.arpa` -> `https://host.docker.internal:10443` (via Caddy container -> host gateway)

Optional alternate endpoints (included in `Caddyfile`):
- `https://beelink/frigate`
- `https://beelink/groovenet`
- `https://homeassistant`

Dedicated hostnames are preferred over nested paths because apps like Frigate and Home Assistant often behave better at site root.
Use `home.arpa` FQDNs on iOS for reliable resolution; short names are fine on desktop if your local DNS/hosts supports them.

## Why this works with Tailscale MagicDNS

- Caddy runs as a reverse proxy and resolves upstream targets via MagicDNS:
  - `beelink.tail0bdbb0.ts.net`
  - `homeassistant.tail0bdbb0.ts.net`
- Client devices connect to Caddy over Tailscale-private networking only.
- No public DNS challenge or Let's Encrypt is needed.
- TLS certificates are issued locally by Caddy’s internal CA and trusted on your devices.

## Startup

1. Copy env template:

```bash
cp .env.example .env
```

2. Start:

```bash
docker compose up -d
```

3. Validate:

```bash
docker compose ps
docker compose logs -f caddy
docker compose logs -f adguardhome
```

4. First-time AdGuard setup:

- Open `http://<caddy-host-tailscale-ip>:3001`
- Complete setup wizard
- Keep AdGuard DNS listening on port `53`
- Point your Tailscale DNS or client DNS to your Caddy host Tailscale IP
- Add DNS rewrites in AdGuard:
  - `frigate` -> `<caddy-host-tailscale-ip>`
  - `groovenet` -> `<caddy-host-tailscale-ip>`
  - `ha` -> `<caddy-host-tailscale-ip>`
  - `scrypted` -> `<caddy-host-tailscale-ip>`
  - `frigate.home.arpa` -> `<caddy-host-tailscale-ip>`
  - `groovenet.home.arpa` -> `<caddy-host-tailscale-ip>`
  - `ha.home.arpa` -> `<caddy-host-tailscale-ip>`
  - `scrypted.home.arpa` -> `<caddy-host-tailscale-ip>`

After setup, AdGuard may move its main web UI to container port `80`.
In this Compose setup that is published as:
- `http://<caddy-host-tailscale-ip>:3080`

## Reload config (no downtime)

After editing `Caddyfile`:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## Logs

Follow logs:

```bash
docker compose logs -f caddy
docker compose logs -f adguardhome
```

Recent logs:

```bash
docker compose logs --tail=200 caddy
docker compose logs --tail=200 adguardhome
```

## Caddy + AdGuard in one stack vs separate stacks

Running together in one Compose project is fine for homelab and easier to operate:
- One `.env`
- One `docker compose up -d`
- One place for backups

Separate stacks are better only if you want independent lifecycle/isolation (for example DNS restarts independent from proxy changes).

## Internal TLS model (`tls internal`)

- `tls internal` tells Caddy to issue certs from its own local CA.
- Caddy stores CA/certs in the persisted `caddy_data` volume.
- Certs are valid only in your trusted internal context, not publicly trusted by browsers by default.

## Trusting Caddy's internal root CA

First export the root cert from the container:

```bash
mkdir -p ./certs
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./certs/caddy-root.crt
```

### macOS

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ./certs/caddy-root.crt
```

### Linux (Debian/Ubuntu)

```bash
sudo cp ./certs/caddy-root.crt /usr/local/share/ca-certificates/caddy-root.crt
sudo update-ca-certificates
```

### Linux (RHEL/Fedora/CentOS)

```bash
sudo cp ./certs/caddy-root.crt /etc/pki/ca-trust/source/anchors/caddy-root.crt
sudo update-ca-trust extract
```

If browser trust still fails, restart the browser after adding trust.

## Home Assistant reverse proxy requirements

Add this to Home Assistant `configuration.yaml` (adjust subnet/IP to your Docker network as needed):

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 10.0.0.0/8
```

For tighter security, replace broad private CIDRs with the exact Docker bridge subnet or specific Caddy container IP range.

Then restart Home Assistant.

## WebSocket support

Caddy `reverse_proxy` supports WebSockets by default, so Frigate, Home Assistant, and other realtime apps work without extra websocket directives.

## Extending for future services

Add a new site block in `Caddyfile`:

```caddyfile
grafana {
	import common
	reverse_proxy http://beelink.tail0bdbb0.ts.net:3001
}
```

Same pattern applies for:
- `portainer`
- `meilisearch`
- `minio`

Then run:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```
