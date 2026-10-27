#!/usr/bin/env bash
# Dois cliques no Finder: instala na primeira vez (ou se algo faltar) e abre o Fora de Cena.
cd "$(dirname "$0")"
pronto() {
    [ -x .venv/bin/python ] && [ -f models/checksums.json ] && \
    .venv/bin/python -c 'import mediapipe, cv2, customtkinter, pyvirtualcam, AVFoundation' 2>/dev/null
}
if ! pronto; then
    echo "Preparando o Fora de Cena (só na primeira vez; leva alguns minutos)…"
    if ! bash ./instalar_macos.sh; then
        read -r -p "A instalação falhou. Pressione Enter para fechar." _
        exit 1
    fi
fi
echo "Abrindo o Fora de Cena…"
exec .venv/bin/python main.py
