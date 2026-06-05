#!/usr/bin/env bash
# deploy.sh — Build, eval-gate, and deploy the ai-persona stack.
#
# Usage:
#   ./deploy.sh                   # full deploy with eval gate
#   ./deploy.sh --skip-evals      # skip eval gate (e.g. first-ever deploy)
#   ./deploy.sh --ingest          # re-run rag-ingest on Fly.io after deploy
#   ./deploy.sh --skip-evals --ingest
#
# Prerequisites:
#   flyctl     https://fly.io/docs/hands-on/install-flyctl/
#   vercel     npm i -g vercel
#   python3    with evals/requirements.txt installed
#
# Required env (set in .env or shell before running):
#   FLY_API_TOKEN, VERCEL_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY

set -euo pipefail
IFS=$'\n\t'

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}==>${RESET} ${BOLD}$*${RESET}"; }
ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET} $*"; }
die()  { echo -e "${RED}  ✗ FATAL:${RESET} $*" >&2; exit 1; }

# ── Parse flags ───────────────────────────────────────────────────────────────
SKIP_EVALS=false
RUN_INGEST=false

for arg in "$@"; do
    case "$arg" in
        --skip-evals) SKIP_EVALS=true  ;;
        --ingest)     RUN_INGEST=true   ;;
        *) die "Unknown flag: $arg" ;;
    esac
done

# ── Prerequisites ─────────────────────────────────────────────────────────────
log "Checking prerequisites"
for cmd in flyctl vercel python3; do
    command -v "$cmd" >/dev/null 2>&1 \
        && ok "$cmd found" \
        || die "$cmd is not installed — see deploy.sh header for install links"
done

[[ -f .env ]] || die ".env not found — copy .env and fill in API keys"
# shellcheck source=.env
set -a; source .env; set +a

# ── Step 1: Eval gate ─────────────────────────────────────────────────────────
if [[ "$SKIP_EVALS" == true ]]; then
    warn "Skipping eval gate (--skip-evals flag)"
else
    log "Step 1/4 — Running eval gate"

    if [[ -z "${PERSONA_API_URL:-}" ]]; then
        warn "PERSONA_API_URL not set — running eval against http://localhost:8000"
        warn "Make sure persona-api is running: docker-compose up -d persona-api"
    fi

    EVAL_API_URL="${PERSONA_API_URL:-http://localhost:8000}"

    # Install eval deps if needed
    python3 -c "import anthropic" 2>/dev/null \
        || pip install -q -r evals/requirements.txt

    (cd evals && python3 eval_chat.py --api-url "$EVAL_API_URL" --out results.json)

    python3 - <<'PYEOF'
import json, sys
try:
    data = json.load(open("evals/results.json"))
except FileNotFoundError:
    print("  evals/results.json not found — did eval_chat.py complete?")
    sys.exit(1)

rate = data["metrics"]["hallucination_rate"]
n    = data["metrics"]["n_questions"]
print(f"  Questions evaluated : {n}")
print(f"  Hallucination rate  : {rate:.1%}")
print(f"  Overall accuracy    : {data['metrics']['overall_accuracy']:.1%}")

THRESHOLD = 0.15
if rate > THRESHOLD:
    print(f"\n  BLOCKED: hallucination_rate {rate:.1%} exceeds {THRESHOLD:.0%} threshold.")
    print("  Fix the failing questions and re-run, or use --skip-evals to bypass.")
    sys.exit(1)
print(f"\n  PASS — hallucination within {THRESHOLD:.0%} threshold.")
PYEOF

    ok "Eval gate passed"
fi

# ── Step 2: Deploy persona-api to Fly.io ─────────────────────────────────────
log "Step 2/4 — Deploying persona-api to Fly.io"

[[ -n "${FLY_API_TOKEN:-}" ]] \
    || warn "FLY_API_TOKEN not set — flyctl will use cached login instead"

# Push all Fly.io secrets from .env (skips vars with empty values)
log "  Syncing Fly.io secrets from .env"
FLY_SECRETS=()
for key in ANTHROPIC_API_KEY OPENAI_API_KEY VAPI_API_KEY VAPI_ASSISTANT_ID \
           VAPI_PHONE_NUMBER_ID ELEVENLABS_API_KEY \
           GOOGLE_CREDENTIALS_JSON GOOGLE_CALENDAR_ID OWNER_EMAIL \
           GITHUB_TOKEN PERSONA_NAME; do
    val="${!key:-}"
    [[ -n "$val" ]] && FLY_SECRETS+=("${key}=${val}")
done

if [[ ${#FLY_SECRETS[@]} -gt 0 ]]; then
    (cd packages/persona-api && flyctl secrets set "${FLY_SECRETS[@]}" --stage)
    ok "Secrets staged"
else
    warn "No non-empty secrets found — skipping flyctl secrets set"
fi

(cd packages/persona-api && flyctl deploy --remote-only)

FLY_APP=$(cd packages/persona-api && flyctl config show --json | python3 -c "import json,sys; print(json.load(sys.stdin)['app'])")
FLY_HOSTNAME=$(cd packages/persona-api && flyctl status --json 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('Hostname',''))" 2>/dev/null || echo "")
FLY_URL="https://${FLY_APP}.fly.dev"
ok "persona-api deployed → ${FLY_URL}"

# ── Step 3: Run rag-ingest on the Fly.io volume (optional) ────────────────────
if [[ "$RUN_INGEST" == true ]]; then
    log "Step 3/4 — Re-running rag-ingest on Fly.io"

    warn "rag-ingest runs inside the persona-api container."
    warn "The resume PDF and config.yaml must already be on the volume."
    warn "To upload them:  flyctl ssh sftp shell -a ${FLY_APP}"

    # This assumes the persona-api image has the rag package included.
    # If not, run ingest locally and upload chroma_db via flyctl ssh sftp.
    flyctl ssh console \
        --app "$FLY_APP" \
        --command "cd /app && python -c \"
import sys; sys.path.insert(0, '/app')
from packages.rag import ingest
\" " 2>/dev/null || {
        warn "Remote ingest failed — run locally and upload the chroma_db volume:"
        warn "  1. python packages/rag/ingest.py"
        warn "  2. flyctl ssh sftp shell -a ${FLY_APP}"
        warn "     sftp> put -r chroma_db /data/chroma_db"
    }
else
    log "Step 3/4 — Skipping remote ingest (pass --ingest to run it)"
    warn "If this is the first deploy, run ingest locally, then:"
    warn "  flyctl ssh sftp shell -a ${FLY_APP:-soumya-persona-api}"
    warn "  sftp> put -r chroma_db /data/chroma_db"
fi

# ── Step 4: Deploy chat-ui to Vercel ─────────────────────────────────────────
log "Step 4/4 — Deploying chat-ui to Vercel"

[[ -n "${VERCEL_TOKEN:-}" ]] \
    || die "VERCEL_TOKEN not set — run 'vercel login' or set the token"

# Inject the Fly.io API URL as a Vercel env var for the production deploy
VERCEL_URL=$(
    PERSONA_API_URL="$FLY_URL" \
    vercel --prod --cwd packages/chat-ui \
           --token "$VERCEL_TOKEN" \
           --env PERSONA_API_URL="$FLY_URL" \
           2>&1 | grep -E "^https://" | tail -1
)
VERCEL_URL="${VERCEL_URL:-<check Vercel dashboard>}"
ok "chat-ui deployed → ${VERCEL_URL}"

# ── Step 5: Update Vapi webhook URL ──────────────────────────────────────────
if [[ -n "${VAPI_API_KEY:-}" && -n "${VAPI_ASSISTANT_ID:-}" ]]; then
    log "Updating Vapi assistant webhook URL to ${FLY_URL}"
    PERSONA_API_URL="$FLY_URL" \
        python3 packages/voice/setup_vapi.py --update 2>/dev/null \
        && ok "Vapi webhook updated" \
        || warn "Vapi update failed — update manually: PERSONA_API_URL=${FLY_URL}"
else
    warn "VAPI_API_KEY or VAPI_ASSISTANT_ID not set — skipping Vapi update"
    warn "Run manually after setting them:  PERSONA_API_URL=${FLY_URL} python packages/voice/setup_vapi.py --update"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}  Deployment complete!${RESET}"
echo ""
echo -e "  ${BOLD}Chat UI${RESET}    → ${VERCEL_URL}"
echo -e "  ${BOLD}API${RESET}        → ${FLY_URL}"
echo -e "  ${BOLD}API docs${RESET}   → ${FLY_URL}/docs"
echo ""
echo -e "  ${BOLD}Voice${RESET}: call the Vapi phone number provisioned via setup_vapi.py"
echo -e "  ${BOLD}Evals${RESET}: cd evals && python eval_chat.py --api-url ${FLY_URL}"
echo -e "  ${BOLD}Report${RESET}: cd evals && python generate_eval_report.py"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
