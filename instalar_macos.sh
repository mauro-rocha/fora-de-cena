#!/usr/bin/env bash
# Instala o Fora de Cena pelos fontes no macOS (Apple Silicon). Pode ser executado de novo sem problema.
set -euo pipefail
cd "$(dirname "$0")"

falha() { echo; echo "Falha de instalação: $1"; echo "Consulte MACOS.md."; exit 1; }

[ "$(uname -s)" = "Darwin" ] || falha "este script é para macOS."
[ "$(uname -m)" = "arm64" ] || falha "é necessário um Mac com Apple Silicon (M1 ou mais novo). O MediaPipe 1.1.1 não tem versão para Mac Intel."

procurar_python() {
    PY=""
    for candidato in "${PYTHON:-}" python3.14 /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 \
                     /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14; do
        [ -n "$candidato" ] || continue
        if command -v "$candidato" >/dev/null 2>&1 && \
           "$candidato" -c 'import sys,platform; sys.exit(0 if sys.version_info[:2]==(3,14) and platform.machine()=="arm64" else 1)' 2>/dev/null; then
            PY="$(command -v "$candidato")"; return 0
        fi
    done
    return 1
}

BREW=""
for b in brew /opt/homebrew/bin/brew; do command -v "$b" >/dev/null 2>&1 && { BREW="$(command -v "$b")"; break; }; done

if ! procurar_python; then
    [ -n "$BREW" ] || falha "Python 3.14 não encontrado e o Homebrew não está instalado. Instale o Python 3.14 pelo python.org e execute de novo."
    echo "Instalando Python 3.14 com Tk pelo Homebrew…"
    "$BREW" install python@3.14 python-tk@3.14
    procurar_python || falha "o Homebrew instalou, mas o Python 3.14 não foi encontrado."
fi
echo "Usando $PY"

if ! "$PY" -c 'import tkinter; tkinter.Tcl()' 2>/dev/null; then
    if [ -n "$BREW" ] && [[ "$PY" == "$("$BREW" --prefix)"/* ]]; then
        echo "Instalando Tk para o Python do Homebrew…"
        "$BREW" install python-tk@3.14
    fi
    "$PY" -c 'import tkinter; tkinter.Tcl()' 2>/dev/null || \
        falha "o Python encontrado não tem Tcl/Tk. Com Homebrew: brew install python-tk@3.14 (ou use o instalador do python.org)."
fi

if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,14) else 1)' 2>/dev/null; then
    echo "Ambiente antigo com outra versão do Python; recriando…"
    mv .venv ".venv-antigo-$(date +%s)"
fi
if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock.txt -r requirements-macos.lock.txt
.venv/bin/python -m pip check
.venv/bin/python setup_models.py

chmod +x iniciar_macos.command "Fora de Cena.command" 2>/dev/null || true
echo
echo "Instalação concluída."
