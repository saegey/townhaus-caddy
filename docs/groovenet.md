# GrooveNET operations

GrooveNET runs as its own Compose stack on beelink at
`/srv/docker/groovenet`. Caddy attaches to its shared Docker network and
reverse-proxies `https://groovenet`; the root Compose stack does not manage its
containers.

## Deploy a release

The tracked image pin is `groovenet_image_tag` in
`ansible/group_vars/townhaus_caddy/groovenet.yml`. Update that value in a
reviewed commit, then deploy it:

```bash
just deploy-groovenet
```

For a one-off test without changing the tracked pin:

```bash
just deploy-groovenet vX.Y.Z
```

The override updates the running stack only. It does not edit the tracked pin,
so update and merge the configuration before relying on that release for future
deployments.

The playbook uses `groovenet_source_ref` to fetch Compose files and `.env.tpl`.
That ref is intentionally separate from the image tag.

## Vinyl ingest

`audio_activity.service` on aswitch uploads 15-second mono WAV windows to
`/api/audio/ingest` only while audio activity is present. It starts after two
seconds of activity, keeps a 30-second inactive hold, and retries network or
5xx failures from its local spool.

```bash
ssh aswitch.local 'journalctl -u audio_activity -n 100 --no-pager'
ssh aswitch.local 'find ~/aswitch/groovenet-spool -maxdepth 1 -type f | wc -l'
```

Successful requests are accepted by GrooveNET and removed from the spool.
Persistent spool growth means the endpoint, TLS trust, or server response needs
attention.
