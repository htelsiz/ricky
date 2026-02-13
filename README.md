# Ricky

Custom GitHub App that reviews PRs as Ricky LaFleur from Trailer Park Boys. Powered by Gemini 3 Pro via Vertex AI.

Every PR review shows up from "Ricky" with his avatar. Technical advice is correct — the delivery is pure Ricky.

## Architecture

```
GitHub PR Event
  → Tailscale Funnel (public HTTPS, terminates TLS)
  → NixOS MicroVM (QEMU via microvm.nix)
  → FastAPI webhook handler (uvicorn :8000)
  → Gemini 3 Pro Preview (Vertex AI, global endpoint)
  → GitHub API (posts review as the Ricky app)
```

The app runs inside a lightweight NixOS microVM with Tailscale handling public HTTPS ingress directly — no reverse proxy needed.

## Webhook Handler

| File | Purpose |
|------|---------|
| `src/main.py` | FastAPI app, webhook endpoint, HMAC-SHA256 signature verification |
| `src/github_auth.py` | GitHub App JWT auth, installation token exchange + caching |
| `src/webhook_handler.py` | Event routing: PR events → review, `@ricky` mentions → reply |
| `src/gemini_client.py` | Vertex AI REST client, sends diff + persona prompt to Gemini |

### Events Handled

- **`pull_request`** (`opened`, `synchronize`, `reopened`): Fetches the diff, loads `.gemini/styleguide.md` as system prompt, generates review via Gemini, posts it as a PR review comment.
- **`issue_comment`** (`created`): If the comment contains `@ricky`, generates an in-character reply.

### Endpoints

- `GET /health` — health check
- `GET /debug/logs` — in-memory ring buffer of recent logs (last 200 entries)
- `POST /webhook` — GitHub webhook receiver (HMAC-verified)

## Ricky Persona

The persona lives in `.gemini/styleguide.md` and is fetched from each repo at review time. If missing, a built-in fallback prompt is used. The styleguide controls:

- Rickyisms (butchered sayings)
- TPB character references for code patterns
- Review structure and tone

## Infrastructure

### MicroVM (NixOS module: `ricky.nix`)

- **Hypervisor:** QEMU (2 vCPUs, 1024 MB RAM)
- **Network:** TAP interface on `microbr` bridge, static IP `192.168.83.10/24`
- **Tailscale:** Runs inside the VM with Funnel for public HTTPS + SSH for management
- **virtiofs shares:**
  - `/nix/store` → `/nix/.ro-store` (read-only, shared with host)
  - `/etc/nixos/secrets/ricky` → `/secrets` (read-only)
  - `/var/lib/microvms/ricky/tailscale` → `/var/lib/tailscale` (persistent state across rebuilds)
- **Hardening:** `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`

### Secrets

All secrets live on the host at `/etc/nixos/secrets/ricky/` and are mounted read-only into the VM:

| File | Purpose |
|------|---------|
| `app-id` | GitHub App ID |
| `private-key.pem` | GitHub App RSA private key |
| `webhook-secret` | Webhook HMAC-SHA256 secret |
| `gcp-service-account.json` | GCP service account key (Vertex AI access) |
| `gcp-project` | GCP project ID |
| `tailscale-auth-key` | Tailscale auth key (reusable, for VM join) |

### Gemini API

- **Model:** `gemini-3-pro-preview`
- **Endpoint:** Global (`aiplatform.googleapis.com/v1beta1/.../locations/global/...`)
- **Auth:** GCP service account with `roles/aiplatform.user`

Note: Gemini 3 Pro is only available on the global endpoint, not regional ones like `us-central1`.

## Setup

### 1. Create the GitHub App

- **Webhook URL:** `https://<vm-tailscale-hostname>/ricky/webhook`
- **Permissions:** `contents: read`, `pull_requests: write`, `issues: write`
- **Events:** `pull_request`, `issue_comment`

Save the app ID, private key, and webhook secret to the secrets directory.

### 2. GCP Service Account

```bash
gcloud iam service-accounts create ricky-webhook --project=<PROJECT>
gcloud projects add-iam-policy-binding <PROJECT> \
  --member="serviceAccount:ricky-webhook@<PROJECT>.iam.gserviceaccount.com" \
  --role=roles/aiplatform.user
gcloud iam service-accounts keys create gcp-service-account.json \
  --iam-account=ricky-webhook@<PROJECT>.iam.gserviceaccount.com
```

### 3. NixOS Flake

Add to your flake inputs:

```nix
ricky-src = {
  url = "path:/home/ht/projects/ricky";  # or github:htelsiz/ricky
  flake = false;
};
```

Import the microVM module (`ricky.nix`) and the network bridge module (`microvm-network.nix`).

### 4. Tailscale Funnel

After the VM joins the tailnet, SSH in and set up funnel:

```bash
ssh root@<vm-hostname>
tailscale funnel --bg --set-path /ricky http://127.0.0.1:8000
```

### 5. Deploy

```bash
sudo nixos-rebuild switch --flake /etc/nixos#phoenix
```

### 6. Verify

```bash
# VM running
systemctl status microvm@ricky

# Health check from host
curl http://192.168.83.10:8000/health

# Health check via public URL
curl https://<vm-tailscale-hostname>/ricky/health

# VM logs
ssh root@<vm-hostname> journalctl -u ricky -f
```

## Adding Ricky to a Repo

1. Install the GitHub App on the repo
2. Optionally add `.gemini/styleguide.md` with the Ricky persona (see this repo for an example)
3. Open a PR — Ricky will review it automatically
4. Mention `@ricky` in any issue/PR comment for an in-character reply
