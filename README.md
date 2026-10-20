# Javis — Plano Bismarck

O Javis é um assistente local com interface para servir como segundo cérebro operacional do Plano Bismarck. Ele recebe notas, perguntas, relatos e relatórios; analisa o contexto; sugere próximos passos; ajuda a revisar decisões; e acompanha resultados de ações registradas.

## Privacidade

- O histórico, as decisões, as ações e o plano ficam no computador, em `%LOCALAPPDATA%\JavisBismarck`.
- As análises usam o Ollama local (`127.0.0.1`); o conteúdo não é enviado a um serviço de IA na internet pelo Javis. A variável `JAVIS_OLLAMA_URL` só é aceita se apontar para `127.0.0.1`, `localhost` ou `::1`.
- O Javis só pode acompanhar informações que você registra ou importa. Ele procura relações possíveis entre relatos e ações anteriores, mesmo quando o relato não cita diretamente a ação.
- Uma relação encontrada é uma hipótese, não prova de causa. O Javis pede confirmação antes de vincular relatos ou aprovar mudanças no plano.
- Este repositório contém o aplicativo, não os dados pessoais do plano. O `.gitignore` ajuda a evitar que dados locais sejam adicionados ao Git por acidente; ele não substitui a configuração de repositório privado nem criptografa arquivos.

## Requisitos

- Windows 10 ou 11.
- Python 3.11 ou superior, caso o computador não tenha o Python incluído no ambiente usado para preparar o Javis.
- [Ollama para Windows](https://ollama.com/download/windows).
- Um modelo instalado no Ollama. Em um notebook com 8 GB de RAM, `qwen3:1.7b` é a opção recomendada para triagens rápidas. Um modelo maior pode levar mais tempo.

Para baixar o modelo recomendado uma vez, abra o PowerShell e execute:

```powershell
ollama pull qwen3:1.7b
```

Depois, abra o Ollama e inicie o Javis pelo atalho da Área de Trabalho. Se ainda não houver atalho, execute `Criar_Atalho_Javis.ps1` uma vez. Também é possível iniciar com `Iniciar_Javis.ps1`. Os scripts procuram o Python automaticamente (`pyw.exe` ou `pythonw.exe`); para usar outro, defina `JAVIS_PYTHONW`.

Opcional: para abrir arquivos PDF, instale o leitor uma vez (`py -m pip install pypdf`). Os demais formatos (TXT, MD, CSV, JSON, DOCX) já funcionam sem instalar nada.

## Uso

1. Registre uma nota, pergunta, ação, resultado ou decisão na interface. Também é possível importar relatórios e arquivos compatíveis.
2. Com a análise automática ligada, o Javis faz uma triagem local e procura relações com registros e ações recentes.
3. Revise as relações e sugestões. Confirme quando quiser associar um acontecimento a uma ação.
4. Aprove uma atualização somente depois de revisar a proposta. O Javis guarda versões anteriores do plano.
5. Para acompanhar uma ação, registre os resultados observados; o Javis pode sugerir uma revisão quando aparecer informação relacionada.

O Javis não observa acontecimentos fora do aplicativo nem conclui sozinho que uma ação causou um resultado.

## Interface

O visual é em **vidro**: um cartão translúcido sobre um fundo aurora animado, com cantos arredondados, borda especular e profundidade de lente.

- Navegação lateral com realce ao passar o mouse, menus (Arquivo, Editar, Exibir, IA, Ajuda) e atalhos de teclado (Ajuda › Atalhos de teclado).
- Três temas: **Aurora** (padrão), **Meia-noite** e **Aurora clara**. `Ctrl+T` alterna entre eles.
- Tamanho de fonte ajustável (`Ctrl++`, `Ctrl+-`, `Ctrl+0`) e suporte a telas de alta resolução.
- Listas ordenáveis, com filtros, menu de botão direito e destaque de ações com revisão vencida.
- Análises com títulos destacados e IDs clicáveis; botão **Parar** (`Esc`) para interromper a resposta.
- Notificações flutuantes ao salvar registro, plano, exportação e backup.
- Histórico com as respostas completas das análises, restauração de versões do plano e rascunho automático.
- Formulários com datas flexíveis (`AAAA-MM-DD`, `DD/MM/AAAA`, `hoje`, `amanhã`, `+7`).
- Backup diário automático, recuperação de dados corrompidos, backup `.zip` e exportação em Markdown.

### Como o vidro é feito

O Tk não compõe o canal alfa de uma imagem (verificado em captura de tela real: um PNG semitransparente vira opaco). Por isso o Javis **pré-compõe** o vidro em Python: desenha o fundo aurora, tira uma cópia desfocada dele para dentro de cada painel e mistura o branco do vidro por cima. O resultado é o mesmo efeito do acrylic do Windows, sem depender de API do sistema. A cor dos widgets é amostrada da região correspondente, então não há emenda entre o vidro e o conteúdo.

O cálculo é vetorizado quando o `numpy` está instalado e cai para uma versão pura em Python quando não está. O `numpy` é **opcional**: o aplicativo funciona igual sem ele.

## Arquivos

- `Javis.pyw`: ponto de entrada (abre a interface).
- `javis/`: o código, dividido por assunto:
  - `config.py` — caminhos, constantes e limites de contexto.
  - `storage.py` — leitura, gravação, migração e backups do estado.
  - `llm.py` — prompts, orçamento de tokens e chamadas ao Ollama.
  - `theme.py` — paletas de cor.
  - `glass.py` — o motor que desenha o fundo e os painéis de vidro.
  - `ui.py` — a interface.
- `Iniciar_Javis.ps1`: abre o aplicativo sem janela de console.
- `Criar_Atalho_Javis.ps1`: cria o atalho na Área de Trabalho.
- `Javis_Plano_Bismarck.ipynb`: alternativa em formato de notebook (somente leitura; não grava nada).
- `%LOCALAPPDATA%\JavisBismarck`: dados privados, plano, versões anteriores (`versoes_plano`), backups diários (`backups_estado`) e `javis.log`.
