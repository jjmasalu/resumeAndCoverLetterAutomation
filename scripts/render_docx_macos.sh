#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/render_docx_macos.sh /absolute/path/to/file.docx [more.docx ...]" >&2
  exit 1
fi

if [[ ! -d /Applications/LibreOffice.app ]]; then
  echo "LibreOffice.app is required at /Applications/LibreOffice.app" >&2
  exit 1
fi

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "pdftoppm is required. Install poppler first: brew install poppler" >&2
  exit 1
fi

OUTDIR="${RENDER_OUTDIR:-$(pwd)/tmp/docs}"
PROFILE_DIR="${TMPDIR:-/tmp}/lo_profile_render_${$}"
STDOUT_LOG="${OUTDIR}/soffice.stdout.log"
STDERR_LOG="${OUTDIR}/soffice.stderr.log"

mkdir -p "${OUTDIR}"
rm -f "${STDOUT_LOG}" "${STDERR_LOG}"

echo "Launching LibreOffice through macOS open ..."
echo "If macOS prompts you, click Open or Allow."

open -n -W -a /Applications/LibreOffice.app \
  --stdin /dev/null \
  --stdout "${STDOUT_LOG}" \
  --stderr "${STDERR_LOG}" \
  --args \
  -env:UserInstallation="file://${PROFILE_DIR}" \
  --headless \
  --convert-to pdf \
  --outdir "${OUTDIR}" \
  "$@"

for input in "$@"; do
  stem="$(basename "${input}")"
  stem="${stem%.*}"
  pdf_path="${OUTDIR}/${stem}.pdf"
  if [[ ! -f "${pdf_path}" ]]; then
    echo "Expected PDF was not created: ${pdf_path}" >&2
    exit 1
  fi
  pdftoppm -png "${pdf_path}" "${OUTDIR}/${stem}" >/dev/null
done

echo "Rendered files saved in ${OUTDIR}"
echo "LibreOffice stdout: ${STDOUT_LOG}"
echo "LibreOffice stderr: ${STDERR_LOG}"
