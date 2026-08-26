#!/usr/bin/env bash
set -euo pipefail

umask 077

INTEGRATION_ROOT="${OPENVOICE_V2_INTEGRATION_ROOT:-/fast/repos/openvoice-v2-agent-control}"
SOURCE_ROOT="${OPENVOICE_V2_SOURCE_ROOT:-/fast/repos/openvoice-v2-upstream}"
ENV_ROOT="${OPENVOICE_V2_ENV_ROOT:-/fast/venvs/openvoice-v2-py39}"
MODEL_ROOT="${OPENVOICE_V2_MODEL_ROOT:-/fast/models/openvoice-v2}"
TOOL_ROOT="${OPENVOICE_V2_TOOL_ROOT:-/fast/tools/miniforge-openvoice-v2}"
CACHE_ROOT="${OPENVOICE_V2_CACHE_ROOT:-/fast/cache/openvoice-v2}"
EVIDENCE_ROOT="${OPENVOICE_V2_EVIDENCE_ROOT:-/fast/qualification/openvoice-v2-current}"
BUILD_ROOT="${OPENVOICE_V2_BUILD_ROOT:-/fast/build/openvoice-v2-74a1d147b17a8c3092dd5430504bd83ef6c7eb23}"

OPENVOICE_COMMIT="74a1d147b17a8c3092dd5430504bd83ef6c7eb23"
MELOTTS_COMMIT="209145371cff8fc3bd60d7be902ea69cbdb7965a"
MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/download/26.5.3-0/Miniforge3-Linux-x86_64.sh"
MINIFORGE_SHA256="14db468222ad564658656f769506056209b6dc375f5e7dfd31eb5ebbf08fa529"

for required in "$INTEGRATION_ROOT" "$SOURCE_ROOT"; do
  resolved="$(readlink -f "$required")"
  case "$resolved" in
    /fast/repos/*) ;;
    *) echo "Refusing repository outside /fast/repos: $resolved" >&2; exit 2 ;;
  esac
done

test -f "$INTEGRATION_ROOT/UPSTREAM.lock.json"
test "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" = "$OPENVOICE_COMMIT"
git -C "$SOURCE_ROOT" merge-base --is-ancestor "$OPENVOICE_COMMIT" HEAD
test -z "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=no)"
git -C "$SOURCE_ROOT" remote set-url --push upstream DISABLED

mkdir -p "$CACHE_ROOT" "$MODEL_ROOT" "$EVIDENCE_ROOT" "$(dirname "$ENV_ROOT")" "$(dirname "$TOOL_ROOT")"
chmod 700 "$CACHE_ROOT" "$MODEL_ROOT" "$EVIDENCE_ROOT"

installer="$CACHE_ROOT/Miniforge3-26.5.3-0-Linux-x86_64.sh"
if [ ! -f "$installer" ]; then
  curl -fL --retry 5 --retry-delay 2 "$MINIFORGE_URL" -o "$installer.partial"
  mv "$installer.partial" "$installer"
fi
printf '%s  %s\n' "$MINIFORGE_SHA256" "$installer" | sha256sum -c -

if [ ! -x "$TOOL_ROOT/bin/conda" ]; then
  if [ -e "$TOOL_ROOT" ]; then
    echo "Incomplete Miniforge target exists: $TOOL_ROOT" >&2
    exit 3
  fi
  bash "$installer" -b -p "$TOOL_ROOT"
fi

if [ ! -x "$ENV_ROOT/bin/python" ]; then
  "$TOOL_ROOT/bin/conda" create -y -p "$ENV_ROOT" --strict-channel-priority -c conda-forge python=3.9.23 pip
fi

PYTHON="$ENV_ROOT/bin/python"
test "$($PYTHON -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')" = "3.9.23"

PATCH_FILE="$INTEGRATION_ROOT/patches/openvoice-numpy-1.22.4.patch"
PATCH_SHA256="$(sha256sum "$PATCH_FILE" | cut -d' ' -f1)"
if [ ! -f "$BUILD_ROOT/.openvoice-integration-source" ]; then
  if [ -e "$BUILD_ROOT" ]; then
    echo "Unverified OpenVoice build target exists: $BUILD_ROOT" >&2
    exit 5
  fi
  mkdir -p "$BUILD_ROOT"
  git -C "$SOURCE_ROOT" archive "$OPENVOICE_COMMIT" | tar -x -C "$BUILD_ROOT"
  (cd "$BUILD_ROOT" && git apply --no-index --ignore-space-change "$PATCH_FILE")
  printf 'upstream_commit=%s\npatch_sha256=%s\n' \
    "$OPENVOICE_COMMIT" "$PATCH_SHA256" > "$BUILD_ROOT/.openvoice-integration-source"
fi
grep -Fx "upstream_commit=$OPENVOICE_COMMIT" "$BUILD_ROOT/.openvoice-integration-source"
grep -Fx "patch_sha256=$PATCH_SHA256" "$BUILD_ROOT/.openvoice-integration-source"
grep -Fq "'numpy==1.22.4'" "$BUILD_ROOT/setup.py"
if grep -Fq "'numpy==1.22.0'" "$BUILD_ROOT/setup.py"; then
  echo "OpenVoice packaging compatibility patch was not applied cleanly" >&2
  exit 6
fi

if ! $PYTHON -c 'import av, numpy; assert av.__version__ == "10.0.0" and numpy.__version__ == "1.22.4"' 2>/dev/null; then
  "$TOOL_ROOT/bin/conda" install -y -p "$ENV_ROOT" --strict-channel-priority -c conda-forge \
    'numpy=1.22.4=py39hc58783e_0' \
    'ffmpeg=6.1.2=gpl_hdfc89ed_706' \
    'av=10.0.0=py39h90d6480_4'
fi

export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONNOUSERSITE=1
export PYTHONPATH=
export HF_HOME="$MODEL_ROOT/hf-cache"
export HF_HUB_DISABLE_TELEMETRY=1
export NLTK_DATA="$MODEL_ROOT/nltk-data"
mkdir -p "$HF_HOME" "$NLTK_DATA"

$PYTHON -m pip install --upgrade \
  pip==25.1.1 setuptools==75.8.2 wheel==0.45.1
$PYTHON -m pip install \
  --index-url https://download.pytorch.org/whl/cu121 \
  torch==2.5.1+cu121 torchaudio==2.5.1+cu121
$PYTHON -m pip install -r "$INTEGRATION_ROOT/requirements-overlay.txt"
$PYTHON -m pip install "$BUILD_ROOT"
$PYTHON -m pip install \
  "git+https://github.com/myshell-ai/MeloTTS.git@$MELOTTS_COMMIT"

if ! $PYTHON -c 'import pathlib,unidic,sys; sys.exit(0 if (pathlib.Path(unidic.DICDIR)/"dicrc").is_file() else 1)'; then
  $PYTHON -m unidic download
fi

$PYTHON - <<'PY'
import os
import nltk
root = os.environ["NLTK_DATA"]
for package in ("averaged_perceptron_tagger", "averaged_perceptron_tagger_eng", "cmudict"):
    nltk.download(package, download_dir=root, quiet=True, raise_on_error=True)
PY

$PYTHON "$INTEGRATION_ROOT/scripts/download_pinned_models.py" \
  --lock "$INTEGRATION_ROOT/UPSTREAM.lock.json" \
  --model-root "$MODEL_ROOT" \
  --report "$MODEL_ROOT/model-download-report.json"

if [ -e "$SOURCE_ROOT/checkpoints_v2" ] && [ ! -L "$SOURCE_ROOT/checkpoints_v2" ]; then
  echo "Refusing to replace non-symlink checkpoint path: $SOURCE_ROOT/checkpoints_v2" >&2
  exit 4
fi
if [ ! -e "$SOURCE_ROOT/checkpoints_v2" ]; then
  ln -s "$MODEL_ROOT/checkpoints_v2" "$SOURCE_ROOT/checkpoints_v2"
fi

$PYTHON -m pip check
$PYTHON -c 'import av, numpy; assert av.__version__ == "10.0.0" and numpy.__version__ == "1.22.4"'
$PYTHON -m pip freeze --all > "$MODEL_ROOT/pip-freeze.txt"
"$TOOL_ROOT/bin/conda" list -p "$ENV_ROOT" --explicit > "$MODEL_ROOT/conda-explicit.txt"
$PYTHON "$INTEGRATION_ROOT/scripts/verify_environment.py" \
  --integration-root "$INTEGRATION_ROOT" \
  --source-root "$SOURCE_ROOT" \
  --build-root "$BUILD_ROOT" \
  --model-root "$MODEL_ROOT" \
  --report "$EVIDENCE_ROOT/install-report.json"

printf '%s\n' "INSTALL_OK report=$EVIDENCE_ROOT/install-report.json"
