#!/usr/bin/env bash
# install.sh — One-command installer for MCP OKF
# Usage: ./install.sh [--with-cognitive-trace] [--with-hooks]
#
# Reduces onboarding from 5 manual steps to 1 command.
# Zero extra dependencies on happy path: bash + Python only.
# Idempotent: safe to re-run — never overwrites existing config.
set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ── Parse flags ──
WITH_COGNITIVE_TRACE=false
WITH_HOOKS=false

for arg in "$@"; do
    case "$arg" in
        --with-cognitive-trace) WITH_COGNITIVE_TRACE=true ;;
        --with-hooks)           WITH_HOOKS=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--with-cognitive-trace] [--with-hooks]"
            echo ""
            echo "  --with-cognitive-trace  Detect Obsidian vault and print plugin install guide"
            echo "  --with-hooks             Install .pre-commit-config.yaml (validate + index + health)"
            exit 0
            ;;
        *) echo -e "${RED}Unknown option: $arg${NC}"; exit 1 ;;
    esac
done

# ── Resolve repo root (where this script lives) ──
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║   MCP OKF Installer                  ║${NC}"
echo -e "${BOLD}${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ══════════════════════════════════════════════════════════════
# 1. Verify Python 3.11+
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[1/7]${NC} Checking Python 3.11+..."

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not found. Install Python 3.11 or newer.${NC}"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo -e "${RED}Error: Python $PY_VER found — 3.11+ required.${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python $PY_VER"

# ══════════════════════════════════════════════════════════════
# 2. Install Python dependencies (mcp, pyyaml)
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[2/7]${NC} Installing mcp + pyyaml + okf-mcp..."

pip install mcp pyyaml 2>&1 | tail -1 || {
    echo -e "${RED}Error: pip install failed. Check your Python/pip setup.${NC}"
    exit 1
}

# Install the package itself so the okf-mcp binary is available in PATH.
if pip install "$REPO_ROOT" 2>&1 | tail -1; then
    echo -e "  ${GREEN}✓${NC} okf-mcp installed"
else
    echo -e "  ${YELLOW}⚠${NC}  pip install . failed — okf-mcp binary will NOT be available in PATH"
    echo "     You can still run the server with: python3 -m cli (but NOT as an MCP server)"
fi
echo -e "  ${GREEN}✓${NC} Dependencies ready"

# ══════════════════════════════════════════════════════════════
# 3. Detect vault (env var or interactive prompt)
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[3/7]${NC} Detecting vault..."

if [ -n "${OKF_VAULT:-}" ]; then
    VAULT="$OKF_VAULT"
    echo -e "  Using \$OKF_VAULT: ${GREEN}$VAULT${NC}"
else
    read -r -p "  Path to your OKF vault [~/OKF-Vault]: " USER_VAULT
    VAULT="${USER_VAULT:-$HOME/OKF-Vault}"
    # Expand leading tilde
    VAULT="${VAULT/#\~/$HOME}"
fi

# Resolve to absolute path; create if missing
VAULT="$(cd "$VAULT" 2>/dev/null && pwd || echo "")"
if [ -z "$VAULT" ] || [ ! -d "$VAULT" ]; then
    echo -e "  ${YELLOW}Directory does not exist — creating.${NC}"
    mkdir -p "${USER_VAULT:-$HOME/OKF-Vault}"
    VAULT="$(cd "${USER_VAULT:-$HOME/OKF-Vault}" && pwd)"
fi
echo -e "  Vault: ${GREEN}$VAULT${NC}"

# ══════════════════════════════════════════════════════════════
# 4. Copy config template (idempotent — never overwrite)
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[4/7]${NC} Setting up vault config..."

CONFIG_DEST="$VAULT/.okf.config.yaml"

if [ -f "$CONFIG_DEST" ]; then
    echo -e "  ${YELLOW}⚠${NC}  .okf.config.yaml exists — skipping (idempotent)"
else
    cp "$REPO_ROOT/okf.config.example.yaml" "$CONFIG_DEST"
    echo -e "  ${GREEN}✓${NC} Copied okf.config.example.yaml → .okf.config.yaml"
fi

# ══════════════════════════════════════════════════════════════
# 5. Prompt for smoke_entry_point and configure it
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[5/7]${NC} Configuring smoke test entry point..."

# Read current value (defaults to 'tp3-cibernetico' from the example config)
CURRENT_SMOKE=$(grep -E '^\s*smoke_entry_point:' "$CONFIG_DEST" | awk '{print $2}' || true)

if [ "$CURRENT_SMOKE" = "tp3-cibernetico" ] || [ -z "$CURRENT_SMOKE" ]; then
    echo "  The health check verifies that traverse + read work by probing"
    echo "  a single known concept. Pick any concept slug in your vault."
    read -r -p "  Smoke entry point slug: " SMOKE_ENTRY

    if [ -n "$SMOKE_ENTRY" ]; then
        sed -i "s/^\(\s*smoke_entry_point:\).*/\1 $SMOKE_ENTRY/" "$CONFIG_DEST"
        echo -e "  ${GREEN}✓${NC} smoke_entry_point → '$SMOKE_ENTRY'"
    else
        echo -e "  ${YELLOW}⚠${NC}  Skipped — edit health.smoke_entry_point in .okf.config.yaml later"
    fi
else
    echo -e "  ${GREEN}✓${NC} Already configured: '$CURRENT_SMOKE'"
fi

# ══════════════════════════════════════════════════════════════
# 6. Run health check to verify the installation
# ══════════════════════════════════════════════════════════════
echo -e "${BOLD}[6/7]${NC} Running health check..."

# Run from repo root so that `python3 -m cli` resolves the cli package.
# Use $OKF_VAULT env var to avoid argparse flag-ordering edge cases.
HEALTH_OUTPUT=$(cd "$REPO_ROOT" && OKF_VAULT="$VAULT" python3 -m cli health 2>&1) || true
echo "$HEALTH_OUTPUT"

if echo "$HEALTH_OUTPUT" | grep -qE 'Health:|health:'; then
    echo -e "  ${GREEN}✓${NC} Health check completed"
else
    echo -e "  ${YELLOW}⚠${NC}  Health check had issues — review the output above"
fi

# ══════════════════════════════════════════════════════════════
# 7. Print MCP registration snippet for Claude Code
# ══════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}[7/7]${NC} MCP registration"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Add to ${BOLD}~/.claude/.mcp.json${NC} (requires pip install . from step 2):"
echo ""
cat <<JSONSNIPPET
{
  "mcpServers": {
    "okf": {
      "command": "okf-mcp",
      "args": []
    }
  }
}
JSONSNIPPET
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ══════════════════════════════════════════════════════════════
# 8. [OPTIONAL] --with-cognitive-trace
# ══════════════════════════════════════════════════════════════
if $WITH_COGNITIVE_TRACE; then
    echo ""
    echo -e "${BOLD}[OPTIONAL] Cognitive Trace${NC}"

    if [ -d "$VAULT/.obsidian" ]; then
        echo -e "  ${GREEN}✓${NC} Obsidian vault detected at $VAULT/.obsidian/"
        echo ""
        echo "  ── Cognitive Trace Plugin ──"
        echo "  The plugin visualizes agent activity as an interactive graph."
        echo ""
        echo "  To install:"
        echo "    1. Copy the plugin directory into your Obsidian plugins:"
        echo "       cp -r <cognitive-trace-plugin> \\"
        echo "           $VAULT/.obsidian/plugins/cognitive-trace/"
        echo "    2. Open Obsidian → Settings → Community Plugins"
        echo "    3. Enable 'Cognitive Trace'"
        echo "    4. Restart Obsidian"
        echo "    5. Verify: python3 -m cli analytics"
        echo ""
        echo "  The plugin reads event_log.jsonl from the plugin directory"
        echo "  and renders traversals, reads, and decisions over time."
    else
        echo -e "  ${YELLOW}⚠${NC}  No .obsidian/ directory found in this vault."
        echo "  Cognitive Trace requires an Obsidian vault to visualize events."
        echo "  Open this vault in Obsidian first, then re-run with --with-cognitive-trace."
    fi
fi

# ══════════════════════════════════════════════════════════════
# 9. [OPTIONAL] --with-hooks
# ══════════════════════════════════════════════════════════════
if $WITH_HOOKS; then
    echo ""
    echo -e "${BOLD}[OPTIONAL] Git Pre-commit Hooks${NC}"

    HOOKS_FILE="$VAULT/.pre-commit-config.yaml"

    if [ -f "$HOOKS_FILE" ]; then
        echo -e "  ${YELLOW}⚠${NC}  .pre-commit-config.yaml exists — skipping (idempotent)"
    else
        cat > "$HOOKS_FILE" <<'PRECOMMIT'
# Pre-commit hooks for OKF vault
# Validates concept integrity before every commit.
#
# Install:  pre-commit install
# Run once: pre-commit run --all-files

repos:
  - repo: local
    hooks:
      - id: okf-validate
        name: OKF Validate
        description: Validate YAML frontmatter of staged concepts
        entry: python3 -m cli validate
        language: system
        pass_filenames: false
        always_run: true

      - id: okf-index
        name: OKF Index
        description: Regenerate index.md and log.md
        entry: python3 -m cli index
        language: system
        pass_filenames: false
        always_run: true

      - id: okf-health
        name: OKF Health
        description: Full vault health check (strict mode)
        entry: python3 -m cli health --strict
        language: system
        pass_filenames: false
        always_run: true
PRECOMMIT
        echo -e "  ${GREEN}✓${NC} Created $HOOKS_FILE"
        echo ""
        echo "  To activate:"
        echo "    cd $VAULT && pre-commit install"
        echo ""
        echo "  Hooks run before every commit: validate → index → health."
        echo "  Install pre-commit: pip install pre-commit"
    fi
fi

# ── Done ──
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║   Installation complete!             ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  Vault:  ${GREEN}$VAULT${NC}"
echo -e "  Config: ${GREEN}$CONFIG_DEST${NC}"
echo -e "  Repo:   ${GREEN}$REPO_ROOT${NC}"
echo ""
echo "  Next steps:"
echo "    1. Review $CONFIG_DEST — adjust taxonomy and thresholds"
echo "    2. Add the MCP JSON snippet above to ~/.claude/.mcp.json"
echo "    3. Restart your AI agent to pick up the new MCP server"
echo "    4. Try: 'okf_search --todos' to see pending work"
