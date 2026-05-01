#!/bin/sh
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd) || exit 2
cd "$ROOT" || exit 2

FAILURES=0
WARNINGS=0

pass() {
  printf 'PASS %s\n' "$*"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  printf 'WARN %s\n' "$*"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL %s\n' "$*"
}

has_file() {
  [ -f "$1" ]
}

grep_repo() {
  pattern=$1
  shift
  find . \
    \( -path './.git' -o -path './.worktrees' -o -path '*/node_modules' -o -path './.cache' -o -path './.mypy_cache' -o -path './vendor' \) -prune \
    -o \( "$@" \) -type f -exec grep -Eqs "$pattern" {} +
}

check_required_files() {
  has_file "ENTERPRISE_DEPLOYMENT_READINESS.md" && pass "ENTERPRISE_DEPLOYMENT_READINESS.md exists" || fail "ENTERPRISE_DEPLOYMENT_READINESS.md is missing"
  has_file "scripts/enterprise-readiness-check.sh" && pass "readiness check script exists" || fail "scripts/enterprise-readiness-check.sh is missing"
  has_file "Dockerfile" && pass "Dockerfile exists" || fail "Dockerfile is missing"

  if has_file ".gitlab-ci.yml" || [ -d ".github/workflows" ]; then
    pass "CI configuration exists"
  else
    fail "CI configuration is missing"
  fi
}

check_dockerfile_user() {
  if ! has_file "Dockerfile"; then
    return
  fi

  tmp=${TMPDIR:-/tmp}/enterprise-readiness-docker.$$
  last_from=$(grep -n '^[[:space:]]*FROM[[:space:]]' Dockerfile | tail -1 | cut -d: -f1)
  if [ -z "$last_from" ]; then
    rm -f "$tmp"
    fail "Dockerfile has no FROM instruction"
    return
  fi

  tail -n +"$last_from" Dockerfile > "$tmp"
  user_line=$(grep -E '^[[:space:]]*USER[[:space:]]+' "$tmp" | tail -1 || true)
  rm -f "$tmp"

  if [ -z "$user_line" ]; then
    if grep -Eiq 'enterprise-readiness:[[:space:]]*root-required|root-required|run-as-root-justification' Dockerfile ENTERPRISE_DEPLOYMENT_READINESS.md 2>/dev/null; then
      warn "Dockerfile final stage has no USER but includes an explicit root execution justification"
    else
      fail "Dockerfile final stage has no non-root USER; container appears to run as root"
    fi
    return
  fi

  user_value=$(printf '%s\n' "$user_line" | awk '{print $2}')
  case "$user_value" in
    0|0:0|root|root:root)
      fail "Dockerfile final stage sets USER to root"
      ;;
    *)
      pass "Dockerfile final stage sets non-root USER ($user_value)"
      ;;
  esac
}

check_manifests_for_secrets() {
  manifest_list=${TMPDIR:-/tmp}/enterprise-readiness-manifests.$$
  hits=${TMPDIR:-/tmp}/enterprise-readiness-secret-hits.$$
  : > "$manifest_list"
  : > "$hits"

  find deploy charts \
    \( -path '*/.git/*' -o -path '*/node_modules/*' \) -prune \
    -o -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.tpl' \) -print 2>/dev/null > "$manifest_list" || true

  manifest_count=$(wc -l < "$manifest_list" | tr -d ' ')
  if [ "$manifest_count" = "0" ]; then
    warn "No Kubernetes or Helm manifest files found under deploy/ or charts/"
    rm -f "$manifest_list" "$hits"
    return
  fi

  default_secret_pattern='CHANGEME|CHANGE_ME|CHANGE_ME_IN_PROD|change-me|dev-secret|admin-secret-change-in-prod|claw-secret-change-in-prod|dev-only-change-in-production|REPLACE_ME|REPLACE_WITH|replace-with-a-secure-jwt-secret'
  hardcoded_secret_pattern='^[[:space:]]*([A-Za-z0-9_]*PASSWORD|[A-Za-z0-9_]*SECRET|[A-Za-z0-9_]*TOKEN|[A-Za-z0-9_]*PRIVATE_KEY|DATABASE_URL|database-url|password):[[:space:]]*["'\'']?[A-Za-z0-9][A-Za-z0-9_:/@+=.,-]{3,}'

  while IFS= read -r file; do
    [ -f "$file" ] || continue
    case "$file" in
      *.example.yaml|*.example.yml|*-example.yaml|*-example.yml|*/examples/*|*/sample/*|*/samples/*)
        continue
        ;;
    esac
    grep -En "$default_secret_pattern" "$file" \
      | grep -Ev '^[^:]+:[0-9]+:[[:space:]]*#' >> "$hits" || true
    grep -En "$hardcoded_secret_pattern" "$file" \
      | grep -Ev '(\{\{|\$\{|valueFrom:|secretKeyRef:|existingSecret|required |b64enc|quote|""|example\.com|chart-example|^.*#)' >> "$hits" || true
  done < "$manifest_list"

  if [ -s "$hits" ]; then
    fail "Kubernetes/Helm manifests contain hardcoded or default-looking production secrets"
    sed -n '1,25p' "$hits" | sed 's/^/  /'
  else
    pass "Kubernetes/Helm manifests do not contain obvious hardcoded production secrets"
  fi

  rm -f "$manifest_list" "$hits"
}

check_commands_discoverable() {
  if grep_repo '(^[[:space:]]*test:|go test|pytest|npm[[:space:]]+(run[[:space:]]+)?test|pnpm[[:space:]]+test|yarn[[:space:]]+test)' \
    -name Makefile -o -name '.gitlab-ci.yml' -o -name 'package.json' -o -name 'pyproject.toml' -o -name 'README.md' -o -name 'ENTERPRISE_DEPLOYMENT_READINESS.md'; then
    pass "Test command is discoverable"
  else
    fail "Test command is not discoverable"
  fi

  if grep_repo '(^[[:space:]]*build:|go build|docker build|npm[[:space:]]+run[[:space:]]+build|pnpm[[:space:]]+build|yarn[[:space:]]+build|python[[:space:]]+-m[[:space:]]+build|hatch build|\[build-system\])' \
    -name Makefile -o -name '.gitlab-ci.yml' -o -name 'package.json' -o -name 'pyproject.toml' -o -name 'README.md' -o -name 'ENTERPRISE_DEPLOYMENT_READINESS.md'; then
    pass "Build command is discoverable"
  else
    fail "Build command is not discoverable"
  fi
}

check_config_documentation() {
  if grep -Eiq 'Required secrets|Required customer-controlled dependencies|Required identity integration assumptions|production configuration|Not production' ENTERPRISE_DEPLOYMENT_READINESS.md README.md 2>/dev/null; then
    pass "Production configuration requirements are documented"
  else
    fail "README or readiness doc does not identify production configuration requirements"
  fi
}

check_go_repo() {
  if find . \
    \( -path './.git' -o -path './.worktrees' -o -path './vendor' \) -prune \
    -o -name '*.go' -type f -print | grep -q .; then
    has_file "go.mod" && pass "Go module file exists" || fail "Go files found but go.mod is missing"
    if grep_repo 'go test' -name Makefile -o -name '.gitlab-ci.yml' -o -name 'README.md' -o -name 'ENTERPRISE_DEPLOYMENT_READINESS.md'; then
      pass "Go test command is discoverable"
    else
      fail "Go repo does not expose a discoverable go test command"
    fi
  fi
}

check_python_repo() {
  if has_file "pyproject.toml" || has_file "setup.py"; then
    has_file "pyproject.toml" && pass "Python pyproject.toml exists" || fail "Python project is missing pyproject.toml"
    if grep_repo 'pytest' -name Makefile -o -name '.gitlab-ci.yml' -o -name 'pyproject.toml' -o -name 'README.md' -o -name 'ENTERPRISE_DEPLOYMENT_READINESS.md'; then
      pass "pytest command is discoverable"
    else
      fail "Python repo does not expose a discoverable pytest command"
    fi
  elif find . \
    \( -path './.git' -o -path './.worktrees' -o -path './.venv' -o -path './.mypy_cache' \) -prune \
    -o -name '*.py' -type f -print | grep -q .; then
    warn "Python helper files found but no Python project metadata; skipping Python repo checks"
  fi
}

check_node_packages() {
  package_list=${TMPDIR:-/tmp}/enterprise-readiness-packages.$$
  find . \
    \( -path './.git' -o -path './.worktrees' -o -path '*/node_modules' \) -prune \
    -o -name package.json -type f -print > "$package_list"

  if [ ! -s "$package_list" ]; then
    rm -f "$package_list"
    return
  fi

  while IFS= read -r pkg; do
    [ -f "$pkg" ] || continue
    grep -Eq '"build"[[:space:]]*:' "$pkg" && pass "$pkg defines a build script" || warn "$pkg has no build script"
    grep -Eq '"test"[[:space:]]*:' "$pkg" && pass "$pkg defines a test script" || warn "$pkg has no test script"
    grep -Eq '"lint"[[:space:]]*:' "$pkg" && pass "$pkg defines a lint script" || warn "$pkg has no lint script"
  done < "$package_list"

  rm -f "$package_list"
}

check_required_files
check_dockerfile_user
check_manifests_for_secrets
check_commands_discoverable
check_config_documentation
check_go_repo
check_python_repo
check_node_packages

if [ "$FAILURES" -gt 0 ]; then
  printf 'FAIL enterprise readiness check completed with %s failure(s) and %s warning(s)\n' "$FAILURES" "$WARNINGS"
  exit 1
fi

printf 'PASS enterprise readiness check completed with 0 failure(s) and %s warning(s)\n' "$WARNINGS"
