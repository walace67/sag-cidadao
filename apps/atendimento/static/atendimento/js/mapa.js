/*
 * SAG-Cidadão — mapas (Leaflet + OpenStreetMap)
 *
 * Arquivo estático servido pelo próprio sistema: a política de segurança
 * (CSP) só permite scripts do próprio site, então nada de JavaScript
 * escrito dentro do HTML. A configuração vem em atributos data-* do elemento.
 *
 *   <div data-mapa="escolher" ...>  cidadão marca o ponto (clique ou GPS)
 *   <div data-mapa="ver" ...>       mostra um ponto (tela de detalhe)
 *   <div data-mapa="gestao" ...>    gestor vê as solicitações (JSON)
 */
(() => {
  "use strict";
  const ATRIBUICAO = '&copy; colaboradores do <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

  function novoMapa(el) {
    const centro = JSON.parse(el.dataset.centro);
    const mapa = L.map(el, { scrollWheelZoom: false }).setView(centro, Number(el.dataset.zoom || 13));
    // O servidor do OpenStreetMap exige saber de qual site vem o pedido
    // (cabeçalho Referer) e bloqueia quem não informa. Nossa política geral
    // (Referrer-Policy: same-origin) não envia nada para outros sites.
    // Aqui liberamos SÓ a origem (ex.: https://sag.exemplo.gov.br), sem o
    // caminho da página, que poderia revelar o número da solicitação.
    L.tileLayer(el.dataset.tiles, {
      maxZoom: 19, attribution: ATRIBUICAO, referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(mapa);
    return mapa;
  }

  // --- Cidadão escolhe o ponto -------------------------------------------
  function escolher(el) {
    const mapa = novoMapa(el);
    const campoLat = document.getElementById(el.dataset.lat);
    const campoLng = document.getElementById(el.dataset.lng);
    const aviso = document.getElementById(el.dataset.aviso);
    const [sul, norte, oeste, leste] = JSON.parse(el.dataset.limites);
    let marcador = null;

    function marcar(lat, lng, centralizar) {
      if (lat < sul || lat > norte || lng < oeste || lng > leste) {
        aviso.textContent = "Esse ponto fica fora do município. Escolha um local em Porto Velho.";
        return;
      }
      // 6 casas decimais: o mesmo formato da coluna DECIMAL(9,6)
      campoLat.value = lat.toFixed(6);
      campoLng.value = lng.toFixed(6);
      if (marcador) marcador.setLatLng([lat, lng]);
      else {
        marcador = L.marker([lat, lng], { draggable: true }).addTo(mapa);
        marcador.on("dragend", () => { const p = marcador.getLatLng(); marcar(p.lat, p.lng, false); });
      }
      if (centralizar) mapa.setView([lat, lng], 17);
      aviso.textContent = "Local marcado. Arraste o marcador para ajustar.";
    }

    if (campoLat.value && campoLng.value) marcar(Number(campoLat.value), Number(campoLng.value), true);
    mapa.on("click", (ev) => marcar(ev.latlng.lat, ev.latlng.lng, false));

    const botaoGps = document.getElementById(el.dataset.gps);
    if (botaoGps) {
      if (!("geolocation" in navigator)) botaoGps.hidden = true;
      botaoGps.addEventListener("click", () => {
        aviso.textContent = "Obtendo sua localização...";
        // O navegador PERGUNTA ao usuário antes de liberar a localização,
        // e só oferece isso em páginas HTTPS (ou no localhost).
        navigator.geolocation.getCurrentPosition(
          (pos) => marcar(pos.coords.latitude, pos.coords.longitude, true),
          () => { aviso.textContent = "Não foi possível obter a localização. Clique no mapa para marcar."; },
          { enableHighAccuracy: true, timeout: 10000 }
        );
      });
    }
    const botaoLimpar = document.getElementById(el.dataset.limpar);
    if (botaoLimpar) botaoLimpar.addEventListener("click", () => {
      if (marcador) { mapa.removeLayer(marcador); marcador = null; }
      campoLat.value = ""; campoLng.value = "";
      aviso.textContent = "Nenhum local marcado (opcional).";
    });
  }

  // --- Mostrar um ponto ---------------------------------------------------
  function ver(el) {
    const mapa = novoMapa(el);
    const ponto = JSON.parse(el.dataset.centro);
    L.marker(ponto).addTo(mapa);
    mapa.setView(ponto, 17);
  }

  // --- Mapa da gestão -----------------------------------------------------
  const CORES = { ABE: "#d97706", ANA: "#2a78d6", EXE: "#7c3aed", CON: "#15803d", IND: "#6b7280", CAN: "#9ca3af" };

  function gestao(el) {
    const mapa = novoMapa(el);
    const contador = document.getElementById(el.dataset.contador);
    fetch(el.dataset.fonte, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then((dados) => {
        const pontos = [];
        dados.pontos.forEach((p) => {
          const m = L.circleMarker([p.lat, p.lng], {
            radius: 7, weight: 1.5, color: "#ffffff", fillColor: CORES[p.status] || "#333", fillOpacity: 0.9,
          }).addTo(mapa);
          // textContent: nada vindo do banco é interpretado como HTML (XSS)
          const caixa = document.createElement("div");
          const titulo = document.createElement("strong"); titulo.textContent = p.categoria;
          const linha = document.createElement("div"); linha.textContent = `${p.status_rotulo} · ${p.bairro} · ${p.aberta_em}`;
          const link = document.createElement("a"); link.href = p.url; link.textContent = `Abrir ${p.protocolo}`;
          caixa.append(titulo, linha, link);
          m.bindPopup(caixa);
          pontos.push([p.lat, p.lng]);
        });
        if (pontos.length) mapa.fitBounds(pontos, { padding: [24, 24], maxZoom: 15 });
        contador.textContent = `${dados.pontos.length} solicitaç${dados.pontos.length === 1 ? "ão" : "ões"} com local marcado de ${dados.total} no período.`;
      })
      .catch(() => { contador.textContent = "Não foi possível carregar os pontos."; });
  }

  const tipos = { escolher, ver, gestao };
  document.querySelectorAll("[data-mapa]").forEach((el) => tipos[el.dataset.mapa] && tipos[el.dataset.mapa](el));
})();
