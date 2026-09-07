set shell := ["zsh", "-cu"]

beelink := "beelink"
beelink_app_dir := "/srv/docker/townhaus-caddy"

# List available recipes.
default:
    @just --list

# Install Python packages required by Ansible collections (uses mise Python from host_vars/localhost.yml).
pip-deps:
    # The v2-compatible package preserves the uptime_kuma_api import path used
    # by the Ansible collection while adding Uptime Kuma v2 support.
    mise which python3 | xargs -I{} {} -m pip install --upgrade uptime-kuma-api2

# Install required Ansible collections and Python packages.
dependencies:
    ansible-galaxy collection install -r ansible/requirements.yml
    just pip-deps

# Validate every Ansible playbook without contacting a host.
syntax-check:
    ansible-playbook --syntax-check -i ansible/inventory.ini.example ansible/deploy.yml
    ansible-playbook --syntax-check -i ansible/inventory.ini.example ansible/playbooks/beelink.yml
    ansible-playbook --syntax-check -i ansible/inventory.ini.example ansible/playbooks/aswitch.yml
    ansible-playbook --syntax-check -i ansible/inventory.ini.example ansible/playbooks/pi_cam.yml

# Run repository validation checks.
check:
    just syntax-check
    just lint
    git diff --check

# Lint Ansible content. Use `pre-commit install` once to run this automatically before commits.
lint:
    ansible-lint ansible/

# Apply Ansible lint's available automatic fixes.
lint-fix:
    ansible-lint --fix ansible/

# Deploy the Docker Compose stack to beelink.
deploy-stack:
    ansible-playbook ansible/deploy.yml --ask-become-pass

# Apply beelink host roles, including backup timers and service configuration.
configure-beelink:
    ansible-playbook ansible/playbooks/beelink.yml --ask-become-pass

# Deploy and configure the complete beelink stack.
deploy-beelink:
    just deploy-stack
    just configure-beelink

# Deploy all services to aswitch.
deploy-aswitch:
    ansible-playbook ansible/playbooks/aswitch.yml --ask-become-pass

# Fast deploy for the IR logger service on aswitch.
deploy-ir:
    cd services/aswitch && ASWITCH_USER=saegey ASWITCH_SERVICE=ir_logger.service ./deploy/deploy.sh

# Push the aswitch env file and restart only the IR logger service.
push-ir-env:
    cd services/aswitch && ASWITCH_USER=saegey ASWITCH_ENV_FILE=env/aswitch.env ASWITCH_RESTART_SERVICES=ir_logger.service ./deploy/push_env.sh

# Deploy all services to pi-cam.
deploy-pi-cam:
    ansible-playbook ansible/playbooks/pi_cam.yml --ask-become-pass

# Deploy all three hosts.
deploy:
    just deploy-beelink
    just deploy-aswitch
    just deploy-pi-cam

# Start an Immich backup immediately.
immich-backup:
    ssh {{ beelink }} "sudo systemctl start immich-backup.service"

# Run an Immich repository integrity check immediately.
immich-backup-check:
    ssh {{ beelink }} "sudo systemctl start immich-backup-check.service"

# Show Immich backup service and timer status.
immich-backup-status:
    ssh -t {{ beelink }} "sudo systemctl status immich-backup.service --no-pager"
    ssh {{ beelink }} "systemctl list-timers 'immich-backup*' --no-pager"

# Show the latest Immich backup logs.
immich-backup-logs:
    ssh -t {{ beelink }} "sudo journalctl -u immich-backup.service -n 100 --no-pager"

# Follow Immich backup logs.
immich-backup-follow:
    ssh -t {{ beelink }} "sudo journalctl -u immich-backup.service -f"

# Show Docker Compose service status on beelink.
status:
    ssh {{ beelink }} "cd {{ beelink_app_dir }} && docker compose ps"

# Follow a Docker Compose service's logs on beelink, e.g. `just logs immich-server`.
logs service:
    ssh -t {{ beelink }} "cd {{ beelink_app_dir }} && docker compose logs -f --tail=100 {{ service }}"

# Reload Caddy without restarting its container.
caddy-reload:
    ssh {{ beelink }} "cd {{ beelink_app_dir }} && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile"

# Mount beelink music library for local GrooveNET dev (macOS).
mount-music:
    sudo mkdir -p /Volumes/music
    sudo mount -t nfs -o resvport,ro beelink.local:/srv/music /Volumes/music

# Unmount beelink music library.
unmount-music:
    sudo umount /Volumes/music

# Show audio services on aswitch.
status-aswitch:
    ssh saegey@aswitch.local "systemctl status camilladsp camillagui shairport-sync aswitch audio_activity --no-pager"

# Show IR logger status on aswitch.
status-ir:
    ssh saegey@aswitch.local "systemctl status pigpiod ir_logger --no-pager"

# Follow IR logger logs on aswitch.
logs-ir:
    ssh -t saegey@aswitch.local "journalctl -u ir_logger.service -f"

# Show audio services on pi-cam.
status-pi-cam:
    ssh saegey@pi-cam.local "systemctl status camilladsp camillagui shairport-sync dac_status amp_trigger --no-pager"
