# Fora de Cena no macOS

Execução pelos fontes no macOS. Não há instalador `.app` ainda: o app roda a partir
de um ambiente Python local, criado por um script.

## Requisitos

- Mac com **Apple Silicon** (M1 ou mais novo). Mac Intel não é suportado: o
  MediaPipe 1.1.1 usado pelo projeto não publica versão x86_64 para macOS.
- **Python 3.14 com Tcl/Tk**, por um destes caminhos:
  - instalador oficial do [python.org](https://www.python.org/downloads/macos/), que já inclui Tk;
  - Homebrew: `brew install python@3.14 python-tk@3.14`.
- Git, para clonar.
- **OBS Studio** ([site oficial](https://obsproject.com/download)), apenas para enviar o
  vídeo a chamadas. O modo **Só prévia** funciona sem OBS.

## Instalar e abrir

O jeito mais simples: dê **dois cliques em `Fora de Cena.command`** no Finder. Na primeira
vez ele instala tudo (inclusive o Python 3.14 pelo Homebrew, se faltar) e depois abre o app;
nas próximas, só abre.

Pelo Terminal, o equivalente é:

```bash
git clone https://github.com/arantes-gabs/fora-de-cena.git
cd fora-de-cena
./instalar_macos.sh
./iniciar_macos.command
```

O `instalar_macos.sh` executa estes passos:

1. encontra o Python 3.14 arm64;
2. confere se o Tk está disponível;
3. cria o `.venv`;
4. instala `requirements.lock.txt` mais `requirements-macos.lock.txt`, que traz o
   PyObjC usado para listar as câmeras;
5. baixa os três modelos oficiais com hash verificado.

Para usar outro Python, defina a variável antes:
`PYTHON=/caminho/python3.14 ./instalar_macos.sh`. Depois da instalação, o
`iniciar_macos.command` também pode ser aberto com dois cliques no Finder.

## Permissão de câmera

Na primeira vez que você iniciar a câmera, o macOS pede acesso para o
**Terminal**, ou para o app que abriu o Fora de Cena (iTerm, VS Code...). Permita.
Se você negou por engano, libere em **Ajustes do Sistema → Privacidade e
Segurança → Câmera** e abra o app de novo. O primeiro pedido costuma fazer a
abertura falhar uma vez; o app tenta de novo automaticamente.

## Enviar o vídeo para Meet, Zoom, Teams…

1. Instale o OBS Studio 30 ou mais novo e abra-o uma vez.
2. No OBS, clique em **Iniciar câmera virtual**. O macOS pede para aprovar a
   **extensão de câmera** do OBS em Ajustes do Sistema; aprove.
3. **Pare** a câmera virtual no OBS. Você pode fechar o OBS.
4. No Fora de Cena, em Configurar → Câmera, escolha a saída **OBS Virtual Camera**
   e inicie a câmera.
5. Na chamada, escolha **OBS Virtual Camera** como câmera e desative desfoque e
   fundos virtuais.

Se a chamada não receber os efeitos, use **Reconectar saída** no app e confirme
que a câmera virtual não está ligada dentro do OBS. A opção **Unity Capture**
existe só no Windows e não aparece no macOS.

## Diferenças em relação ao Windows

| Recurso | macOS |
|---|---|
| Atalho **F8** | Funciona com a janela do app em foco (não é global). Em muitos teclados de Mac é preciso **fn + F8**. O botão **Restaurar** funciona sempre. |
| Pasta de dados | Ao rodar pelos fontes, a pasta do próprio repositório (igual ao Windows). Em uma futura versão empacotada: `~/Library/Application Support/ForaDeCena`. |
| Abrir guia / pasta da extensão | Usa o `open` do macOS (navegador e Finder). |
| Extensão do Meet | Igual: Chrome ou Edge → `chrome://extensions` → Modo do desenvolvedor → Carregar sem compactação. |

## Diagnóstico

```bash
.venv/bin/python -B main.py --self-test        # modelos, inferência e canal de saída, sem abrir a câmera
.venv/bin/python -B -m unittest discover -s tests -v
```

Se o app não abrir, o erro aparece no Terminal e é gravado em `startup-error.log`,
na pasta do repositório.
