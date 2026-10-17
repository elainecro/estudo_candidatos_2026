/* 2º turno: os dois finalistas de cada disputa lado a lado. Usa a ficha e os dados de app.js (window.ESTUDO_APP). */
(function () {
  'use strict';
  const D = window.ESTUDO_2026; const A = window.ESTUDO_APP;
  if (!D || !A || !D.segundo_turno) return;
  const { esc, CANDS, CARGO_POR_ID, PARTIDO_POR_SIGLA, ESPECTRO_POR_ID, espectroDe, corEsp, anosPolitica, fmtData } = A;
  const T = D.segundo_turno;
  const $ = (s, el = document) => el.querySelector(s);
  const POR_ID = Object.fromEntries(CANDS.map(c => [c.id, c]));

  // "sem dado" nunca vira zero: quando o campo não foi coletado, a célula diz isso
  const SEM = txt => `<span class="sem-dado">${esc(txt || 'não coletado')}</span>`;
  const brl = v => (v === null || v === undefined) ? null : 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  const brlCurto = v => {
    if (v === null || v === undefined) return null;
    const n = Number(v);
    if (n >= 1e6) return 'R$ ' + (n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
    if (n >= 1e3) return 'R$ ' + Math.round(n / 1e3).toLocaleString('pt-BR') + ' mil';
    return brl(n);
  };
  // projetos só contam como levantados quando a fonte deu o total (Câmara, Senado); Ales e câmaras municipais ficam de fora
  const consolidado = c => c.projetos?.apresentados?.total !== null && c.projetos?.apresentados?.total !== undefined;
  const corta = (t, n) => { t = String(t || ''); if (t.length <= n) return t; return t.slice(0, n).replace(/\s+\S*$/, '').replace(/[\s.,;:]+$/, '') + '…'; };
  const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
  const lista = (arr, max = 99) => arr.length ? `<ul>${arr.slice(0, max).map(x => `<li>${x}</li>`).join('')}</ul>${arr.length > max ? `<details><summary class="nota">mais ${arr.length - max}</summary><ul>${arr.slice(max).map(x => `<li>${x}</li>`).join('')}</ul></details>` : ''}` : '';

  // ------------------------------------------------------------ cada linha
  // Cada função recebe um candidato e devolve o HTML da célula. A mesma função roda para os dois lados.
  const LINHAS = [
    { grupo: 'Quem é' },
    { rotulo: 'Chapa', f: c => c.chapa ? `Vice: <b>${esc(c.chapa.vice || 'não informado')}</b>${c.chapa.partido_vice ? ` (${esc(c.chapa.partido_vice)})` : ''}${c.chapa.coligacao ? `<div class="obs">${esc(c.chapa.coligacao)}</div>` : ''}` : SEM() },
    { rotulo: 'Perfil', f: c => [c.idade ? c.idade + ' anos' : '', c.ocupacao, c.escolaridade ? c.escolaridade.toLowerCase() : ''].filter(Boolean).map(esc).join(' · ') || SEM() },
    { rotulo: 'Partido e espectro', f: c => { const p = PARTIDO_POR_SIGLA[c.partido]; const e = espectroDe(c.partido); return `<a href="#" data-partido="${esc(c.partido)}">${esc(c.partido)}</a>${p?.federacao ? ` · federação ${esc(p.federacao)}` : ''}<div class="obs"><span class="esp-dot" style="${corEsp(e)}"></span>${esc(ESPECTRO_POR_ID[e]?.nome || e)}</div>`; } },

    { grupo: 'Trajetória' },
    { rotulo: 'Na vida pública', f: c => { const a = anosPolitica(c); return c.tipo_historico === 'sem_mandato' ? 'Nunca teve mandato' : (c.inicio_politica ? `Desde <b>${c.inicio_politica}</b> (${a} anos)` : SEM()); } },
    { rotulo: 'Perfil de carreira', f: c => ({ legislativo: 'Legislativo (fez carreira propondo e votando leis)', executivo: 'Executivo (fez carreira governando)', misto: 'Misto (Legislativo e Executivo)', sem_mandato: 'Sem mandato' }[c.tipo_historico] || SEM()) },
    { rotulo: 'Mandatos e cargos', f: c => c.mandatos?.length ? lista(c.mandatos.map(m => `<b>${esc(m.periodo)}</b> ${esc(m.cargo)}`)) : 'Nenhum mandato eletivo anterior' },
    { rotulo: 'Eleições disputadas', f: c => {
      // só o histórico conferido à mão; o do TSE é incompleto e faria uma pessoa parecer menos votada do que foi
      if (!c.historico_fonte) return SEM('histórico do TSE incompleto');
      const el = c.eleicoes_anteriores || [];
      return `<b>${el.length}</b> disputadas, <b>${c.vezes_eleito}</b> vencidas<div class="obs">${plural(c.trocas_de_partido, 'troca', 'trocas')} de partido entre elas</div>${lista([...el].reverse().map(e => `<b>${esc(e.ano)}</b> ${esc(e.cargo || '')}${e.uf ? ' (' + esc(e.uf) + ')' : ''} · ${esc(e.partido || '')} <span class="obs">${esc(e.resultado || 'resultado não confirmado')}</span>`), 4)}`;
    } },

    { grupo: 'O que fez com o poder que teve', nota: 'Quem governou se mede pela gestão; quem legislou, pelos projetos e relatorias. Comparar o número de projetos de quem passou a vida no Executivo com o de quem passou no Legislativo engana.' },
    { rotulo: 'Gestão (Executivo)', f: c => c.gestao?.length
      ? c.gestao.map(g => `<p class="cel-par"><b>${esc(g.cargo)}</b> · ${esc(g.periodo)}</p>`).join('') + '<p class="obs">Realizações e críticas de cada gestão estão na ficha completa.</p>'
      : (c.tipo_historico === 'executivo' || c.tipo_historico === 'misto' ? SEM('teve cargo executivo, balanço não consolidado') : 'Nunca teve cargo executivo') },
    { rotulo: 'Projetos de lei', f: c => {
      if (!consolidado(c)) return c.tipo_historico === 'sem_mandato' ? 'Nunca teve mandato' : SEM('não consolidado (a fonte não tem coleta automática)');
      const pj = c.projetos; const ap = pj.aprovados?.length || 0; const tr = pj.em_tramitacao?.length || 0;
      const lei = i => `${esc(i.id || '')}${i.id ? ': ' : ''}${esc(corta(i.titulo, 140))}`;
      return `<b>${pj.apresentados.total}</b> apresentados<div class="obs">${plural(ap, 'aprovado e em vigor', 'aprovados e em vigor')} · ${tr} em tramitação</div>${ap ? lista(pj.aprovados.map(lei), 3) : ''}<div class="obs">Fonte: ${esc(pj.fonte || '')}</div>`;
    } },
    { rotulo: 'Relatorias e direção', f: c => c.relatorias?.length ? `<b>${c.relatorias.length}</b> registradas` : (consolidado(c) ? 'Nenhuma registrada' : SEM('não consolidado')) },
    { rotulo: 'Votações em temas-chave', f: c => {
      const v = (c.votacoes_chave || []).filter(x => /^(aprovad|rejeitad|mantid)/i.test(x.descricao || '') && !/destaque|requerimento|emenda n[ºo°]|dvs/i.test(x.descricao || ''));
      if (!c.votacoes_chave?.length) return SEM('nenhum voto registrado nas votações escolhidas');
      const porTema = {}; for (const x of (v.length ? v : c.votacoes_chave)) if (!porTema[x.tema]) porTema[x.tema] = x.voto || 'sem registro';
      return lista(Object.entries(porTema).map(([t, voto]) => `${esc(t)}: <b>${esc(voto)}</b>`));
    } },

    { grupo: 'O que promete', nota: 'Resumo, feito com ajuda de IA, do plano de governo entregue ao TSE no 1º turno. As contagens dependem do resumo: servem de pista, não de nota. Em 17/10 conferimos os planos publicados pelo TSE para o 2º turno: são os mesmos do 1º turno.' },
    { rotulo: 'Síntese do plano', f: c => c.proposta_resumo?.sintese ? `<p class="cel-par">${esc(c.proposta_resumo.sintese)}</p>` : SEM('resumo não escrito') },
    { rotulo: 'Eixos', f: c => c.proposta_resumo?.eixos?.length ? lista(c.proposta_resumo.eixos.map(e => esc(e.tema))) : SEM() },
    { rotulo: 'Promessas com número ou prazo', f: c => { const m = c.proposta_resumo?.mensuraveis; return m ? `<b>${m.length}</b>${m.length ? lista(m.map(esc), 3) : ''}` : SEM(); } },
    { rotulo: 'O que o plano não diz', f: c => { const m = c.proposta_resumo?.lacunas; return m ? `<b>${m.length}</b> lacunas apontadas${m.length ? lista(m.map(esc), 3) : ''}` : SEM(); } },

    { grupo: 'Processos e listas', nota: 'Investigação não é condenação, e arquivamento não é atestado de inocência. Abra a ficha para ver a fonte de cada item.' },
    { rotulo: 'Processos e denúncias na imprensa', f: c => c.processos?.length ? `<b>${c.processos.length}</b>${lista(c.processos.map(p => `${esc(corta(p.descricao, 220))}<div class="obs">${esc(p.status || '')}${p.ano ? ' · ' + p.ano : ''}</div>`))}` : 'Nenhum localizado' },
    { rotulo: 'Certidões criminais do registro', f: c => c.certidoes_flag ? `<span class="tag ${c.certidoes_flag === 'nada consta' ? 'ok' : c.certidoes_flag === 'com apontamentos' ? 'bad' : 'warn'}">${esc(c.certidoes_flag)}</span>` : SEM(c.cargo === 'presidente' ? 'certidões nacionais não lidas (o guia leu só as do ES)' : null) },
    { rotulo: 'Listas de sanção (TCU, CEIS, CNEP, CEAF)', f: c => { const s = c.sancoes; if (!s) return SEM(); const n = ['tcu', 'ceis', 'cnep', 'ceaf'].reduce((t, k) => t + (s[k]?.length || 0), 0); return n ? `<span class="tag bad">${plural(n, 'ocorrência', 'ocorrências')}</span>` : '<span class="tag ok">nada</span>'; } },

    { grupo: 'Dinheiro', nota: 'Patrimônio é o que o candidato declarou ao TSE. A campanha é a prestação parcial do 1º turno; o valor final sai depois da eleição.' },
    { rotulo: 'Patrimônio declarado', f: c => c.bens ? `<b>${brlCurto(c.bens.total)}</b><div class="obs">${plural(c.bens.itens?.length ?? 0, 'bem', 'bens')}</div>` : SEM() },
    { rotulo: 'Campanha: quanto recebeu', f: c => { const k = c.campanha; if (!k) return SEM(); const pct = k.receitas ? Math.round(100 * (k.fundo_publico_e_partido || 0) / k.receitas) : null; return `<b>${brlCurto(k.receitas)}</b>${pct !== null ? `<div class="obs">${pct}% de fundo público e partido</div>` : ''}${k.atualizado_em ? `<div class="obs">até ${esc(fmtData(k.atualizado_em))}</div>` : ''}`; } },
    { rotulo: 'Campanha: maiores doadores', f: c => c.campanha?.maiores_doadores?.length ? lista(c.campanha.maiores_doadores.slice(0, 3).map(d => `${esc(d.nome)} <span class="obs">${brlCurto(d.valor)}</span>`)) : SEM(c.campanha ? 'nenhum doador listado' : null) },
  ];

  // ------------------------------------------------------------ desenho
  function cabeca(c) {
    return `<button type="button" class="duelo-cab" data-abrir="${esc(c.id)}">
      ${c.foto ? `<img class="foto" src="${esc(c.foto)}" alt="" loading="lazy" onerror="this.remove()">` : ''}
      <span class="numero">${esc(c.numero || '')}</span>
      <span class="duelo-nome">${esc(c.nome_urna)}</span>
      <span class="obs">${esc(c.partido)}</span>
      <span class="duelo-ficha">Ficha completa →</span>
    </button>`;
  }
  function desenharDuelo(d) {
    const sec = document.getElementById(d.cargo); if (!sec) return;
    const [a, b] = d.candidatos.map(id => POR_ID[id]).sort((x, y) => Number(x.numero) - Number(y.numero));
    let corpo = '';
    for (const l of LINHAS) {
      if (l.grupo) { corpo += `<div class="duelo-grupo"><h3>${esc(l.grupo)}</h3>${l.nota ? `<p class="nota">${esc(l.nota)}</p>` : ''}</div>`; continue; }
      corpo += `<div class="duelo-linha"><div class="duelo-rotulo">${esc(l.rotulo)}</div><div class="duelo-cel">${l.f(a)}</div><div class="duelo-cel">${l.f(b)}</div></div>`;
    }
    sec.innerHTML = `
      <h2>${esc(d.titulo)}</h2>
      <p class="intro">${esc(CARGO_POR_ID[d.cargo].o_que_e)} <a href="${esc(d.fonte)}" target="_blank" rel="noopener">Confirmação do 2º turno no TSE</a>.</p>
      <div class="duelo">
        <div class="duelo-topo">${cabeca(a)}${cabeca(b)}</div>
        ${corpo}
      </div>`;
  }

  function avisos() {
    $('#avisos').innerHTML = [
      esc(T.nota),
      '“Não coletado” quer dizer que o guia não tem esse dado, não que a pessoa tem zero. Os dois lados nem sempre têm as mesmas fontes: a Câmara e o Senado têm API; a Assembleia do ES, não.',
      'Os números de projetos, relatorias e votações vêm dos sites da Câmara e do Senado. Contam quantidade, não qualidade. Uma lei importante pesa mais que dez homenagens.',
      `Os planos que o TSE publicou para o 2º turno são idênticos aos do 1º (conferido em 17/10). <a href="${esc(T.planos_2o_turno)}" target="_blank" rel="noopener">Planos no site do TSE</a>.`,
      'Apoios recebidos depois do 1º turno, debates e promessas novas de campanha não estão nesta página.',
    ].map(t => `<li>${t}</li>`).join('');
    $('#atualizado').textContent = `Disputas conferidas em ${fmtData(T.atualizado_em)}. Dados dos candidatos de ${fmtData(D.candidatos.meta.atualizado_em)}. 2º turno: ${fmtData(T.data)}.`;
  }

  document.addEventListener('click', e => {
    const b = e.target.closest('[data-abrir]');
    if (b) { const c = POR_ID[b.dataset.abrir]; if (c) A.abrirCandidato(c); return; }
    const p = e.target.closest('.duelo a[data-partido]');
    if (p) { e.preventDefault(); const x = PARTIDO_POR_SIGLA[p.dataset.partido]; if (x) A.abrirPartido(x); }
  });

  for (const d of T.disputas) desenharDuelo(d);
  avisos();
})();
