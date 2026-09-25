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
| Candidatos | filtro por cargo, partido, busca e "só quem já tem mandato"; ficha com chapa, mandatos, projetos e fontes | `data/candidatos.json` |

## Cobertura dos dados (25/09/2026)

| Cargo | No guia | Registrados no TSE |
|---|---|---|
| Presidente | 12 deferidos + 1 indeferido (Marçal) | 12 aptos |
| Governador | 5 | 5 |
| Senador | 11 | 11 |
| Deputado federal | 15 (os 7 que tentam reeleição, o substituto de quem desistiu e nomes com mandato anterior) | 135 |
| Deputado estadual | 24 (os 22 deputados atuais que tentam reeleição + 2 ex-parlamentares) | 403 |

Ou seja: **as majoritárias estão completas; as proporcionais estão
parciais.** Para importar todos os candidatos do TSE e puxar os projetos da
Câmara e do Senado, rode o script abaixo em uma máquina com internet aberta.

Onde um dado não foi confirmado, o JSON tem `null` em vez de chute. Na
página, isso aparece como "nº a confirmar" ou "sem consolidação".

## Atualizar os dados

```bash
# 1. importa a lista completa de candidatos (ES + presidente) do TSE
python3 scripts/fetch_dados.py --tse --dry-run   # só mostra
python3 scripts/fetch_dados.py --tse             # grava data/candidatos.json

# 2. puxa projetos de quem é/foi deputado federal ou senador
python3 scripts/fetch_dados.py --camara --senado

# 3. reempacota para a página
python3 scripts/build_bundle.py
```

O script usa só a biblioteca padrão do Python (3.9+). Ele **não foi executado**
no ambiente em que foi escrito, porque a rede estava bloqueada para os
domínios do TSE, da Câmara e do Senado. Trate a primeira rodada como teste.

Para editar à mão (corrigir um número, acrescentar uma lei), edite o JSON e
rode `python3 scripts/build_bundle.py`. O empacotador valida ids duplicados e
partidos/cargos que não existem.

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
