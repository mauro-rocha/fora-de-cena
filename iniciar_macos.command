#!/usr/bin/env bash
# Abre o Fora de Cena no macOS. Pode ser executado com dois cliques no Finder.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Execute ./instalar_macos.sh primeiro."
    read -r -p "Pressione Enter para fechar." _
    exit 1
fi
exec .venv/bin/python main.py "$@"
