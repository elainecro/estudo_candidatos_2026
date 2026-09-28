# Estudo dos candidatos 2026 (Espírito Santo)

Guia estático para estudar antes de votar: o que cada cargo faz, o que cada
partido defende e o histórico de cada candidato (tempo de vida pública,
mandatos, projetos apresentados, em tramitação e aprovados).

**Abrir:** basta abrir `index.html` no navegador. Não precisa de servidor nem
de instalar nada. Se publicar no GitHub Pages, o site é a raiz do repositório.

## O que tem

| Seção | Conteúdo | Arquivo |
|---|---|---|
| Cargos | o que cada cargo decide, o que não decide, como avaliar um candidato, glossário, ordem dos votos na urna | `data/cargos.json` |
| Partidos | 30 partidos registrados: espectro, ideologia, marcos (o que fizeram quando tiveram poder), críticas frequentes, quem lançaram no ES | `data/partidos.json` |
| Candidatos | filtro por cargo, partido, busca e "só quem já tem mandato"; ficha com chapa, mandatos, gestão (para quem governou), projetos, relatorias, fiscalização e denúncias que fez, processos e denúncias contra, e fontes | `data/candidatos.json` |

## Cobertura dos dados (25/09/2026)

| Cargo | No guia | Registrados no TSE |
|---|---|---|
| Presidente | 12 deferidos + Leonardo Avalanche (substituto do PRTB, registro a confirmar) + Marçal (indeferido) | 13 pedidos, 12 aptos em 11/09 |
| Governador | 5 | 5 |
| Senador | 11 | 11 |
| Deputado federal | 15 (os 7 que tentam reeleição, o substituto de quem desistiu e nomes com mandato anterior) | 135 |
| Deputado estadual | 24 (os 22 deputados atuais que tentam reeleição + 2 ex-parlamentares) | 403 |

Ou seja: **as majoritárias estão completas; as proporcionais estão
parciais.** Para importar todos os candidatos do TSE e puxar os projetos da
Câmara e do Senado, rode o script abaixo em uma máquina com internet aberta.

Onde um dado não foi confirmado, o JSON tem `null` em vez de chute. Na
página, isso aparece como "nº a confirmar" ou "sem consolidação".

## Publicar num link (celular)

```bash
python3 scripts/build_bundle.py
python3 scripts/build_artifact.py        # gera dist/artifact.html, um arquivo só
```

`dist/artifact.html` é a página inteira embutida (CSS, JS e dados) no formato
que o Artifact do Claude espera. Para GitHub Pages ou Netlify, use o
`index.html` normal.

## Ver o site na sua máquina

Não precisa de servidor. Clone o repositório e abra o `index.html` no
navegador (duplo clique, ou `open index.html` no Mac, `xdg-open index.html`
no Linux, `start index.html` no Windows). Se preferir um endereço local:

```bash
python3 -m http.server 8000
# depois abra http://localhost:8000
```

## Coletar os dados (roda na sua máquina)

Só precisa de Python 3.9 ou mais novo. Sem pip, sem dependência.

```bash
git clone https://github.com/elainecro/estudo_candidatos_2026.git
cd estudo_candidatos_2026
git checkout claude/es-candidates-page-anan76

# 1. Teste sem gravar nada. Leia o que ele imprime.
python3 scripts/fetch_dados.py --tse --dry-run

# 2. Rode fonte por fonte, do mais leve para o mais pesado.
python3 scripts/fetch_dados.py --tse        # lista completa, bens, certidões, eleições anteriores (~5 min)
python3 scripts/fetch_dados.py --contas     # receitas, despesas e doadores da campanha (~5 min)
python3 scripts/fetch_dados.py --senado     # autorias, relatorias, filiações e votos-chave dos senadores (~2 min)
python3 scripts/fetch_dados.py --camara     # projetos, cota, comissões e votos-chave dos deputados (~20 min)
python3 scripts/fetch_dados.py --links      # links de conferência (instantâneo, sem rede)

# 3. Emendas exigem chave gratuita do Portal da Transparência:
#    https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email
export PORTAL_TRANSPARENCIA_KEY=cole_a_chave_aqui
python3 scripts/fetch_dados.py --emendas

# ou tudo de uma vez (sem emendas se a chave não estiver definida):
python3 scripts/fetch_dados.py --tudo

# 4. Empacote e veja
python3 scripts/build_bundle.py
open index.html
```

O que cada fonte enche na ficha:

| Fonte | Campos | Cobre |
|---|---|---|
| TSE DivulgaCand | número, situação, foto, `bens`, `certidoes`, `eleicoes_anteriores`, `trocas_de_partido`, cria fichas novas | todos os candidatos |
| TSE contas | `campanha` (receitas, despesas, fundo público, maiores doadores) | todos com registro |
| Câmara | `projetos`, `gastos` (cota por ano), `comissoes`, `votacoes_chave` | quem é ou foi deputado federal |
| Senado | `projetos`, `relatorias`, `filiacoes`, `votacoes_chave` | quem é ou foi senador |
| Portal da Transparência | `emendas` (total, por ano, maiores destinos) | deputados e senadores |
| links | `links` (DivulgaCand, Câmara, Senado, Radar do Congresso, Comovotou, TCE-ES, Jusbrasil) | todos |

As votações-chave estão em `data/votacoes_chave.json`. Edite a lista se quiser
medir outros temas. Números de proposição precisam ser conferidos.

Avisos:

- O script **nunca rodou contra as APIs de verdade** (a rede do ambiente em
  que foi escrito bloqueava esses domínios). Os normalizadores foram testados
  com respostas de exemplo. É provável que algum campo venha com nome
  diferente do esperado; nesse caso o valor fica nulo em vez de quebrar.
  Se algo vier vazio, abra a URL impressa no erro no navegador e compare.
- O TSE limita requisições. Se começar a falhar com 429, espere alguns
  minutos e rode de novo; o script atualiza o que já existe sem duplicar.
- Fichas criadas pelo TSE vêm com histórico vazio (`projetos: null`,
  `resumo` padrão). O que não tem API continua manual: gestão, fiscalização,
  processos, TCE-ES e Ales.
- Para republicar no link do celular: `python3 scripts/build_artifact.py` e
  me peça para publicar o `dist/artifact.html`.
- Fluxo do git: os dados (`data/candidatos.json`, `data/bundle.js`, fotos)
  vêm da sua máquina; scripts, página e resumos vêm daqui. Sempre `git pull`
  antes de commitar dados, e rode `build_bundle.py` depois do pull.

## Ler os PDFs do TSE (planos de governo e certidões)

Precisa dos zips `proposta_governo_2026_ES.zip` e `certidao_criminal_2026_ES.zip`
em `data/cache/` (baixe no navegador, em dadosabertos.tse.jus.br).

```bash
pip3 install pypdf
python3 scripts/ler_pdfs.py --propostas    # texto dos planos -> data/propostas/<tse_id>.txt
python3 scripts/ler_pdfs.py --certidoes    # lê as certidões com texto embutido (poucas)

# Quase todas as certidões do ES são imagem escaneada. Para essas, OCR:
pip3 install pyobjc-framework-Vision pyobjc-framework-Quartz   # macOS, usa o OCR do sistema
python3 scripts/ocr_certidoes.py --cargo governador             # comece pelos majoritários
python3 scripts/ocr_certidoes.py                                # todas as 'indeterminada' (20 a 60 min)
python3 scripts/build_bundle.py
```

Fora do macOS o `ocr_certidoes.py` usa `tesseract` + `pymupdf` (veja o cabeçalho
do script). O texto OCR fica em `data/cache/ocr/` e não vai para o git.

Os resumos estruturados dos planos ficam em `data/propostas_resumo/<tse_id>.json`
(síntese, eixos, promessas mensuráveis, lacunas). Foram escritos por IA a partir
do texto integral, e o `build_bundle.py` os mescla na ficha como `proposta_resumo`.
Ficam em arquivo separado de `candidatos.json` de propósito: os coletores
reescrevem o `candidatos.json`, e o resumo não pode ser perdido nisso. Para
escrever um novo, copie o formato de um dos cinco existentes.

## Estrutura de um candidato

```json
{
  "id": "fabiano-contarato", "cargo": "senador", "nome_urna": "Fabiano Contarato",
  "partido": "PT", "numero": "133", "situacao": "deferido",
  "tipo_historico": "legislativo",         // legislativo | executivo | misto | sem_mandato
  "inicio_politica": 2018,                 // usado para "anos de vida pública"
  "mandatos": [{"cargo": "Senador", "periodo": "2019-atual", "partido": "Rede / PT"}],
  "projetos": {
    "apresentados": {"total": null, "obs": "..."},
    "em_tramitacao": [{"id": "PL 4146/2020", "titulo": "...", "obs": "..."}],
    "aprovados": [{"titulo": "...", "norma": "Lei 14.434/2022", "ano": 2022, "status": "em vigor", "papel": "autor"}]
  },
  "fontes": ["https://..."]
}
```

`projetos: null` significa "não consolidado". Para quem nunca teve mandato a
página explica isso em vez de mostrar zeros.

Campos extras, todos listas (vazias quando não há nada localizado):

```json
"gestao":       [{"cargo": "Prefeito de X", "periodo": "2013-2020", "realizacoes": ["..."], "criticas": ["..."], "fonte": "..."}],
"relatorias":   [{"titulo": "...", "resultado": "relator; virou a Lei ...", "ano": 2023}],
"fiscalizacao": [{"tipo": "CPI | denúncia | representação | fiscalização", "descricao": "...", "ano": 2026}],
"processos":    [{"descricao": "...", "status": "arquivado | em andamento | condenado | ...", "ano": 2021, "fonte": "https://..."}]
```

Campos preenchidos pelo coletor: `bens`, `certidoes`, `eleicoes_anteriores`,
`trocas_de_partido`, `campanha`, `gastos`, `comissoes`, `votacoes_chave`,
`filiacoes`, `emendas`, `links`, além de `camara_id`, `senado_id` e `tse_id`.

`gestao` é a métrica certa para quem foi prefeito, governador ou secretário:
lei não mede gestão. `processos` lista o que está em fontes públicas com o
status da última notícia encontrada. Investigação não é condenação e
arquivamento não é atestado de inocência.

## Fontes

TSE (DivulgaCandContas e Dados Abertos), Câmara dos Deputados (dadosabertos),
Senado Federal (dadosabertos), Assembleia Legislativa do ES e imprensa
capixaba (Folha Vitória, A Gazeta, ES Hoje, Século Diário e outros). Cada
ficha traz os links usados.

## Limites que você precisa saber

- "Projetos aprovados" só faz sentido para quem já foi parlamentar. Prefeitos,
  governadores e secretários têm histórico de gestão, não de leis. Estreantes
  não têm histórico nenhum, e a página diz isso.
- Poucos projetos de autoria viram lei. Relatorias e articulação pesam tanto
  quanto autoria, e isso não cabe em três colunas. Use os números como
  ponto de partida, não como nota.
- "Marcos" e "críticas" dos partidos são um resumo do que a sigla sustentou
  em governos. O candidato local pode discordar do partido.
