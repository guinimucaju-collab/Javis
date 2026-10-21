# Relatório dos testes automatizados — Javis

Data: 21/10/2026 · Python 3.14.7 · pytest 9.1.1 · numpy 2.5.3 · Windows 10/11

## 1. O que foi feito

Foi criada uma suíte de testes automatizados para o pacote `javis/`, com **132 testes** que rodam
sem internet, sem Ollama e sem tocar nos seus dados reais (cada teste usa uma pasta temporária).

```
tests/
├── conftest.py       # fixtures: pasta de dados temporária, raiz do Tk, app completo
├── test_storage.py   # estado, migrações, backups, datas          (37 testes)
├── test_llm.py       # orçamento de contexto, prompts, protocolo de eventos (27 testes)
├── test_ui.py        # páginas, tema, vidro, registros, plano, exportação (28 testes)
├── test_theme.py     # paletas e cores                            (12 testes)
├── test_analise.py   # fluxo da análise (Ollama falso) e relações  (11 testes)
├── test_glass.py     # motor de vidro (numpy)                     (9 testes)
└── test_widgets.py   # controles de vidro                         (8 testes)
```

### Como rodar

```powershell
python -m pip install pytest pytest-cov   # uma vez
python -m pytest                          # roda tudo
python -m pytest --cov=javis --cov-report=term-missing   # com cobertura
```

`pytest.ini` já aponta para a pasta `tests/`. Os testes de interface abrem uma janela do Tk
(escondida) — em uma máquina sem sessão gráfica eles são pulados automaticamente.

## 2. Resultado

```
132 passed in 66s
```

| Módulo     | Antes | Agora | Observação                                   |
|------------|-------|-------|----------------------------------------------|
| config.py  | 100%  | 100%  |                                              |
| theme.py   | 100%  | 100%  |                                              |
| glass.py   | 89%   | 89%   | só falta o caminho do "vidro" com numpy       |
| storage.py | 88%   | 88%   |                                              |
| llm.py     | 72%   | 88%   | +16 pontos com o teste do protocolo de eventos|
| ui.py      | 52%   | 64%   | +12 pontos                                   |
| widgets.py | 54%   | 58%   | desenho e animação                            |
| **total**  | **58%**| **66%** | 3.427 linhas de código                       |

## 3. Bugs reais encontrados (e corrigidos)

Os testes acharam **5 defeitos** que só apareceram porque o comportamento foi verificado de
verdade, e não "a olho" na tela.

### 3.1 A análise nunca era salva (grave)

O evento `done` do Ollama chegava na interface como texto puro, e a interface esperava a tupla
`(pergunta, resposta, erro)`. O erro ficava engolido por um `except` e era só registrado no log.
Consequência: **a resposta aparecia na tela (via streaming), mas nunca era gravada no histórico,
a proposta de atualização do plano nunca era montada, o registro não era marcado como analisado e
a relação possível com outras ações nunca era oferecida.**

- `javis/llm.py`: o evento `done` agora leva `(pergunta, resposta, erro)`.
- `javis/ui.py`: o repasse do evento na thread foi tornado explícito.
- `tests/test_llm.py` + `tests/test_analise.py`: teste de regressão do formato do evento e do
  ciclo completo (pergunta → resposta na tela → histórico → proposta → relação → confirmação).

### 3.2 Cada salvamento do plano criava uma versão "anterior" à toa

O arquivo do plano era gravado com CRLF (Windows) e comparado com o texto da tela, que usa LF.
Todo "Salvar plano" era considerado uma alteração: uma cópia extra do arquivo era guardada a cada
vez e o histórico enchia de "Plano atualizado".

- `javis/storage.py`: `atomic_write` grava com `\n` explícito.
- `javis/ui.py`: a comparação ignora a diferença de quebra de linha.

### 3.3 A migração da pasta antiga apagava as versões do plano

Ao migrar de `JavisBismarck` para `Javis`, os arquivos `Plano_Bismarck_*.md` eram renomeados e
**depois a pasta era apagada** — as versões do plano não migravam.

- `javis/storage.py`: os arquivos são movidos para a pasta nova antes da limpeza.

### 3.4 A numeração dos IDs misturava os tipos

`next_id("A", ...)` olhava para todos os registros, inclusive os de nota: com um `N-001` no
estado, a primeira ação nascia como `A-002` (e não `A-001`).

- `javis/storage.py`: a contagem agora é por prefixo (`N-`, `A-`, `D-`, `AN-`).

### 3.5 O arquivo de dados não era criado na primeira abertura

O `estado.json` só aparecia depois da primeira gravação. Como o notebook e o guia mandam abrir o
app "uma vez para criar o arquivo", isso agora acontece na primeira abertura.

- `javis/storage.py`: `load_state()` grava o arquivo inicial.

## 4. O que está coberto

**Persistência (`storage.py`, 88%)**
- ida e volta do estado (gravar → ler → comparar);
- estado corrompido: o arquivo quebrado é guardado e o backup mais recente é recuperado;
- escrita atômica (sem arquivo `.tmp` sobrando);
- backup diário do estado e backup de versões do plano;
- migração de schema (campos ausentes, relações sem status, nome antigo do projeto);
- migração da pasta antiga (com e sem dados novos);
- regras de ID, histórico (limite), datas aceitas e rejeitadas.

**IA (`llm.py`, 88%)**
- orçamento de tokens: o que não cabe é descartado e **o que foi cortado é registrado**;
- o contexto enviado cabe na janela do modelo;
- leitura da resposta: seção de relações, extração da proposta para o plano, "Nenhuma atualização
  proposta" reconhecida como "sem mudança";
- protocolo de eventos com a interface (`chunk`, `done`, `error`, cancelamento).

**Interface (`ui.py`, 64%)**
- todas as páginas existem e trocam de lugar;
- tema: troca, persistência e abertura no tema escolhido; tema inválido é ignorado;
- efeito de vidro: desligar muda o desenho do fundo (imagem → retângulos) e a escolha é salva;
- registros: salvar, limpar a caixa, aparecer na lista, contador de palavras/caracteres;
- plano: salvar, guardar versão anterior, recarregar do disco, plano vazio;
- exportação em Markdown e backup `.zip` (com o diálogo de arquivo substituído por um caminho
  temporário, para não abrir janelas);
- resiliência: app abre **sem numpy** e com o arquivo de estado Unexpectedamente inválido.

**Vidro e controles (`glass.py` 89%, `widgets.py` 58%, `theme.py` 100%)**
- a cena tem exatamente o tamanho esperado e o formato PPM/PNG é válido;
- sem numpy, o vidro devolve `None` e o app cai no visual simples;
- botões, caixas e radios respondem (inclusive o botão desabilitado);
- todo tema tem os campos obrigatórios e cores válidas.

## 5. Lacunas conhecidas (próximos passos)

1. **Diálogos modais** (`FormDialog`, "Nova ação", "Registrar decisão") — sem cobertura; exigem
   simular o `Toplevel` ou refatorar o diálogo para devolver dados por callback.
2. **`acrylic.py` (17%)** — só o caminho do Windows com DWM; precisa de uma máquina real.
3. **Importação de arquivos** (`import_file`) — o `filedialog` é bloqueado, mas a leitura de
   PDF/DOCX (com `pypdf`) e o limite de 8 MB não são testados.
4. **`widgets.py`** — o desenho e as animações de hover/foco são verificados só de forma indireta
   ("desenhou algo?"), não por captura de imagem.
5. **Testes de desempenho** — não há medição de quanto tempo leva o redesenho do fundo em
   computador fraco, que é justamente o caso do "efeito de vidro desligado".
6. **Concorrência** — a troca de job da análise (`job_id`) tem teste indireto, mas não há teste
   que force respostas fora de ordem.

## 6. Recomendações

1. Rodar `python -m pytest` antes de cada commit (a suíte leva ~1 minuto).
2. Criar os testes dos diálogos com `FormDialog`: o caminho mais barato é dar ao diálogo um
   `callback` e devolver os valores, sem `wait_window`.
3. Medir o tempo de `glass.compose` em uma máquina fraca e colocar isso no relatório — é o número
   que justifica a opção "sem vidro".
4. Adicionar um teste de fumaça que abre o app real e fecha (o que foi feito manualmente aqui).
5. Guardar o relatório de cobertura em CI quando o projeto passar a usar GitHub Actions.
