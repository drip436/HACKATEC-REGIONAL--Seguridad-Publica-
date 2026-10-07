// Mapa de la región (Google Maps, o Leaflet/OSM de respaldo): cámaras, incidentes (rojo = abierto, verde = resuelto),
// zonas de riesgo (círculos rojos translúcidos), patrullas libres (azul, en su base)
// y la patrulla asignada animada por su ruta de calles. También la capa de calor.
// Se usa Leaflet directamente (sin react-leaflet) para exponer a Reflex una
// API pequeña basada en props. Las coordenadas se dibujan tal como llegan.
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const ROJO = "#dc2626";
const AZUL = "#2563eb";
const VERDE = "#16a34a";
// La patrulla que llegó se queda unos segundos en el lugar y luego vuelve a su base.
const PATRULLA_VISIBLE_TRAS_LLEGAR_MS = 10 * 1000;
// Zoom al encuadrar incidentes: nunca más cerca que una vista de colonia.
const ZOOM_MAX_ENCUADRE = 15;
// Al elegir el punto de una cámara: con menos zoom un clic se desvía kilómetros
// (puede caer en el mar), así que primero se acerca y solo después se marca.
const ZOOM_MIN_MARCAR = 15;

const CSS = `
.so-mapa { width: 100%; border-radius: 10px; background: #eef0f3; z-index: 0; border: 1px solid #e5e7eb; }
/* Mapa base apagado: los colores quedan para incidentes, patrullas y zonas. */
.so-mapa .leaflet-tile-pane { filter: grayscale(0.85) brightness(1.04) contrast(0.92); }
.so-mapa .leaflet-tooltip { background: #111827; color: #f9fafb; border: 0; border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0,0,0,.15); font: 12px/1.4 Inter, system-ui, sans-serif; padding: 4px 8px; }
.so-mapa .leaflet-tooltip::before { display: none; }
.so-mapa .leaflet-control-attribution { font-size: 10px; background: rgba(255,255,255,.8); }
.so-alerta { display: block; width: 12px; height: 12px; border-radius: 50%; background: ${ROJO};
  border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(17,24,39,.25); cursor: pointer; }
.so-alerta.so-resuelto { background: ${VERDE}; }
.so-alerta.so-sel { box-shadow: 0 0 0 1px rgba(17,24,39,.25), 0 0 0 5px rgba(220,38,38,.25); }
.so-alerta.so-resuelto.so-sel { box-shadow: 0 0 0 1px rgba(17,24,39,.25), 0 0 0 5px rgba(22,163,74,.25); }
.so-camara { display: block; width: 9px; height: 9px; border-radius: 2px; background: #374151; border: 1.5px solid #fff; }
.so-camara.so-inactiva { background: #9ca3af; }
.so-unidad { display: block; width: 10px; height: 10px; border-radius: 50%; background: ${AZUL};
  border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(17,24,39,.25); }
.so-patrulla { display: block; width: 14px; height: 14px; border-radius: 50%; background: ${AZUL};
  border: 2px solid #fff; box-shadow: 0 0 0 4px rgba(37,99,235,.22); }
.so-patrulla.so-llego { box-shadow: 0 0 0 4px rgba(22,163,74,.3); }
.so-rondin { display: block; width: 12px; height: 12px; border-radius: 50%; border: 2.5px solid #0f766e; background: #fff; }
`;

// Distancia aproximada en metros entre [lat, lng]: suficiente para repartir el avance.
function distancia(a, b) {
  const k = 111320;
  const dx = (b[1] - a[1]) * k * Math.cos((a[0] * Math.PI) / 180);
  const dy = (b[0] - a[0]) * k;
  return Math.hypot(dx, dy);
}

// Punto de la ruta a la `fraccion` (0-1) de su longitud total.
function sobreRuta(ruta, acum, fraccion) {
  const meta = acum[acum.length - 1] * fraccion;
  let i = 1;
  while (i < acum.length - 1 && acum[i] < meta) i++;
  const tramo = acum[i] - acum[i - 1] || 1;
  const t = Math.min(1, Math.max(0, (meta - acum[i - 1]) / tramo));
  return [ruta[i - 1][0] + (ruta[i][0] - ruta[i - 1][0]) * t, ruta[i - 1][1] + (ruta[i][1] - ruta[i - 1][1]) * t];
}

function icono(html, lado) {
  return L.divIcon({ className: "", html, iconSize: [lado, lado], iconAnchor: [lado / 2, lado / 2] });
}

export function MapaLeaflet({
  centro,
  zoom = 8,
  camaras = [],
  alertas = [],
  unidades = [],
  zonas = [],
  rondines = [],
  patrullas = [],
  encuadre = [],
  foco = [],
  calor = [],
  seleccion = "",
  marcador = [],
  altura = "380px",
  onAlerta,
  onClicMapa,
}) {
  const nodo = useRef(null);
  const mapa = useRef(null);
  const capas = useRef(null);
  const encuadrado = useRef(false);
  const alClic = useRef(onAlerta);
  alClic.current = onAlerta;
  const alClicMapa = useRef(onClicMapa);
  alClicMapa.current = onClicMapa;
  const pin = useRef(null);

  useEffect(() => {
    const m = L.map(nodo.current, { center: centro, zoom, attributionControl: true, zoomControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m);
    capas.current = {
      zonas: L.layerGroup().addTo(m),
      calor: L.layerGroup().addTo(m),
      camaras: L.layerGroup().addTo(m),
      unidades: L.layerGroup().addTo(m),
      rondines: L.layerGroup().addTo(m),
      rutas: L.layerGroup().addTo(m),
      alertas: L.layerGroup().addTo(m),
      patrullas: L.layerGroup().addTo(m),
    };
    mapa.current = m;
    // Modo "elegir punto": el clic fija la coordenada exacta donde se pulsó.
    m.on("click", (e) => {
      if (!alClicMapa.current) return;
      if (m.getZoom() < ZOOM_MIN_MARCAR) {
        m.setView(e.latlng, Math.min(m.getZoom() + 4, ZOOM_MIN_MARCAR));
        return;
      }
      alClicMapa.current(e.latlng.lat, e.latlng.lng);
    });
    if (onClicMapa) nodo.current.style.cursor = "crosshair";
    const observador = new ResizeObserver(() => m.invalidateSize());
    observador.observe(nodo.current);
    return () => {
      observador.disconnect();
      m.remove();
      mapa.current = null;
    };
  }, []);

  // Vista inicial regional; en cuanto hay incidentes o cámaras, se encuadra sobre ellos (una vez).
  useEffect(() => {
    if (!mapa.current || encuadrado.current || !encuadre.length) return;
    encuadrado.current = true;
    if (encuadre.length === 1) {
      mapa.current.setView(encuadre[0], ZOOM_MAX_ENCUADRE, { animate: false });
    } else {
      mapa.current.fitBounds(L.latLngBounds(encuadre), { padding: [36, 36], maxZoom: ZOOM_MAX_ENCUADRE, animate: false });
    }
  }, [encuadre]);

  // Punto elegido para la cámara (diálogo de vinculación): se dibuja y se centra.
  useEffect(() => {
    if (!mapa.current) return;
    if (pin.current) {
      pin.current.remove();
      pin.current = null;
    }
    if (marcador.length !== 2) return;
    pin.current = L.marker(marcador, { icon: icono('<span class="so-alerta so-sel"></span>', 12), keyboard: false })
      .bindTooltip(`${marcador[0].toFixed(6)}, ${marcador[1].toFixed(6)}`)
      .addTo(mapa.current);
    const vista = mapa.current.getZoom() < 14 ? 16 : mapa.current.getZoom();
    if (!mapa.current.getBounds().pad(-0.2).contains(marcador) || mapa.current.getZoom() < 14) {
      mapa.current.setView(marcador, vista, { animate: true });
    }
  }, [marcador[0], marcador[1]]);

  useEffect(() => {
    const capa = capas.current.zonas.clearLayers();
    zonas.forEach((z) =>
      L.circle([z.lat, z.lng], {
        radius: z.radio_m,
        color: ROJO,
        weight: 1,
        opacity: 0.45,
        fillColor: ROJO,
        fillOpacity: Math.min(0.4, Math.max(0.25, z.opacidad)),
        interactive: true,
      })
        .bindTooltip(`Zona de riesgo · ${z.nombre} · ${z.eventos} eventos`, { sticky: true })
        .addTo(capa),
    );
  }, [zonas]);

  useEffect(() => {
    const capa = capas.current.camaras.clearLayers();
    camaras.forEach((c) =>
      L.marker([c.lat, c.lng], {
        icon: icono(`<span class="so-camara${c.activa ? "" : " so-inactiva"}"></span>`, 9),
        keyboard: false,
      })
        .bindTooltip(`Cámara · ${c.nombre}${c.activa ? "" : " (en revisión)"}`)
        .addTo(capa),
    );
  }, [camaras]);

  useEffect(() => {
    const capa = capas.current.unidades.clearLayers();
    unidades
      .filter((u) => u.estado === "libre")
      .forEach((u) =>
        L.marker([u.lat, u.lng], { icon: icono('<span class="so-unidad"></span>', 10), keyboard: false, zIndexOffset: 500 })
          .bindTooltip(`${u.id} · ${u.base} · libre`)
          .addTo(capa),
      );
  }, [unidades]);

  useEffect(() => {
    const capa = capas.current.alertas.clearLayers();
    alertas.forEach((a) => {
      const sel = a.id === seleccion ? " so-sel" : "";
      const resuelto = a.caso === "resuelto";
      const estado = { pendiente: "pendiente", en_camino: "unidad en camino", resuelto: "atendido y resuelto" }[a.caso] || "";
      L.marker([a.lat, a.lng], {
        icon: icono(`<span class="so-alerta${resuelto ? " so-resuelto" : ""}${sel}"></span>`, 12),
        title: `${a.tipo_txt}, severidad ${a.sev_txt}, ${estado}`,
        zIndexOffset: resuelto ? 600 : 1000,
      })
        .bindTooltip(`${a.tipo_txt} · ${a.sev_txt} · ${estado} · ${a.hora}`)
        .on("click", () => alClic.current && alClic.current(a.id))
        .addTo(capa);
    });
  }, [alertas, seleccion]);

  useEffect(() => {
    const capa = capas.current.rondines.clearLayers();
    rondines.forEach((r) =>
      L.marker([r.lat, r.lng], { icon: icono('<span class="so-rondin"></span>', 12), keyboard: false, zIndexOffset: 2000 })
        .bindTooltip(r.texto)
        .addTo(capa),
    );
  }, [rondines]);

  // --- Patrulla asignada: solo la unidad que atiende un incidente se mueve. Un bucle
  // de animación la lleva por su ruta según la hora real de salida y de llegada.
  const enRuta = useRef(new Map());
  useEffect(() => {
    const vigentes = new Set();
    const ahora = Date.now();
    patrullas.forEach((p) => {
      const llego = p.estado === "resuelto";
      if (llego && ahora - (p.llegada_real_ms || p.llegada_ms) > PATRULLA_VISIBLE_TRAS_LLEGAR_MS) return;
      if (!p.ruta || p.ruta.length < 2) return;
      vigentes.add(p.id);
      let u = enRuta.current.get(p.id);
      if (!u) {
        const acum = [0];
        for (let i = 1; i < p.ruta.length; i++) acum.push(acum[i - 1] + distancia(p.ruta[i - 1], p.ruta[i]));
        u = {
          linea: L.polyline(p.ruta, { color: AZUL, weight: 3, opacity: 0.7, dashArray: "6 6" }).addTo(capas.current.rutas),
          marca: L.marker(p.ruta[0], { icon: icono('<span class="so-patrulla"></span>', 14), zIndexOffset: 3000, keyboard: false })
            .bindTooltip(`${p.unidad} · en camino`)
            .addTo(capas.current.patrullas),
          acum,
        };
        enRuta.current.set(p.id, u);
        // Recién despachada: encuadrar la ruta completa para ver a la unidad acercarse.
        if (!llego && mapa.current && ahora - p.inicio_ms < 15000) {
          mapa.current.flyToBounds(u.linea.getBounds(), { padding: [40, 40], duration: 1.2, maxZoom: 16 });
        }
      }
      u.datos = p;
      if (llego) {
        u.linea.setStyle({ opacity: 0 });
        u.marca.setIcon(icono('<span class="so-patrulla so-llego"></span>', 14));
        u.marca.setTooltipContent(`${p.unidad} · en el lugar: caso resuelto`);
      }
    });
    for (const [id, u] of enRuta.current) {
      if (!vigentes.has(id)) {
        capas.current.rutas.removeLayer(u.linea);
        capas.current.patrullas.removeLayer(u.marca);
        enRuta.current.delete(id);
      }
    }
  }, [patrullas]);

  useEffect(() => {
    let cuadro;
    const animar = () => {
      const ahora = Date.now();
      for (const u of enRuta.current.values()) {
        const p = u.datos;
        const fraccion = p.estado === "resuelto" ? 1 : Math.min(1, Math.max(0, (ahora - p.inicio_ms) / (p.llegada_ms - p.inicio_ms)));
        u.marca.setLatLng(sobreRuta(p.ruta, u.acum, fraccion));
      }
      cuadro = requestAnimationFrame(animar);
    };
    cuadro = requestAnimationFrame(animar);
    return () => cancelAnimationFrame(cuadro);
  }, []);

  // Violencia detectada o cámara recién vinculada: el mapa vuela al punto exacto.
  useEffect(() => {
    if (foco.length === 3 && mapa.current) {
      encuadrado.current = true;
      mapa.current.flyTo([foco[0], foco[1]], 16, { duration: 1.2 });
    }
  }, [foco[2]]);

  useEffect(() => {
    const elegida = alertas.find((a) => a.id === seleccion);
    if (!elegida || !mapa.current) return;
    // Solo se desplaza si la alerta elegida queda fuera (o al borde) de la vista.
    const punto = L.latLng(elegida.lat, elegida.lng);
    if (!mapa.current.getBounds().pad(-0.15).contains(punto)) mapa.current.panTo(punto);
  }, [seleccion]);

  useEffect(() => {
    let vigente = true;
    const capa = capas.current.calor.clearLayers();
    if (!calor.length) return;
    // leaflet.heat se registra sobre el `L` global, por eso se importa después.
    window.L = L;
    import("leaflet.heat").then(() => {
      if (!vigente) return;
      L.heatLayer(calor, {
        radius: 18,
        blur: 15,
        minOpacity: 0.3,
        max: Math.max(4, calor.length / 40),
        gradient: { 0.3: "#fecaca", 0.6: "#f87171", 0.85: "#dc2626", 1: "#7f1d1d" },
      }).addTo(capa);
    });
    return () => {
      vigente = false;
    };
  }, [calor]);

  return (
    <>
      <style>{CSS}</style>
      <div ref={nodo} className="so-mapa" style={{ height: altura }} role="application" aria-label="Mapa de la región" />
    </>
  );
}

// ============================================================================
// Google Maps (Maps JavaScript API). Misma API de props que MapaLeaflet; si la
// llave falla (gm_authFailure), no hay red o se agotó la cuota, se muestra
// MapaLeaflet en su lugar para que el panel nunca se quede sin mapa.
// ============================================================================

let cargaGoogle = null;

function cargarGoogle(clave) {
  if (window.google?.maps?.marker) return Promise.resolve(window.google.maps);
  if (!cargaGoogle) {
    cargaGoogle = new Promise((ok, mal) => {
      window.__soGoogleListo = () => ok(window.google.maps);
      // Google llama esto si la llave es inválida, la API no está habilitada o no hay cuota.
      window.gm_authFailure = () => {
        window.__soGoogleFallo = true;
        window.dispatchEvent(new Event("so-google-fallo"));
      };
      const s = document.createElement("script");
      s.src =
        "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(clave) +
        "&v=weekly&libraries=marker&language=es&region=MX&loading=async&callback=__soGoogleListo";
      s.async = true;
      s.onerror = () => {
        cargaGoogle = null;
        mal(new Error("No se pudo cargar Google Maps"));
      };
      document.head.appendChild(s);
    });
  }
  return cargaGoogle;
}

function punto(html) {
  const caja = document.createElement("div");
  caja.innerHTML = html;
  caja.style.transform = "translateY(50%)"; // AdvancedMarker ancla abajo al centro: se centra el punto
  return caja;
}

function quitar(lista) {
  lista.forEach((o) => (o.setMap ? o.setMap(null) : (o.map = null)));
  lista.length = 0;
}

export function MapaGoogle(props) {
  const [fallo, setFallo] = useState(!props.clave || (typeof window !== "undefined" && window.__soGoogleFallo));
  useEffect(() => {
    const alFallar = () => setFallo(true);
    window.addEventListener("so-google-fallo", alFallar);
    return () => window.removeEventListener("so-google-fallo", alFallar);
  }, []);
  if (fallo) return <MapaLeaflet {...props} />;
  return <MapaGoogleInterno {...props} alFallar={() => setFallo(true)} />;
}

function MapaGoogleInterno({
  clave,
  centro,
  zoom = 8,
  camaras = [],
  alertas = [],
  unidades = [],
  zonas = [],
  rondines = [],
  patrullas = [],
  encuadre = [],
  foco = [],
  calor = [],
  seleccion = "",
  marcador = [],
  altura = "380px",
  onAlerta,
  onClicMapa,
  alFallar,
}) {
  const nodo = useRef(null);
  const mapa = useRef(null);
  const gm = useRef(null);
  const capas = useRef({ zonas: [], calor: [], camaras: [], unidades: [], rondines: [], alertas: [] });
  const enRuta = useRef(new Map());
  const pin = useRef(null);
  const encuadrado = useRef(false);
  const alClic = useRef(onAlerta);
  alClic.current = onAlerta;
  const alClicMapa = useRef(onClicMapa);
  alClicMapa.current = onClicMapa;
  const [listo, setListo] = useState(false);

  useEffect(() => {
    let vivo = true;
    cargarGoogle(clave)
      .then((maps) => {
        if (!vivo || !nodo.current) return;
        gm.current = maps;
        const m = new maps.Map(nodo.current, {
          center: { lat: centro[0], lng: centro[1] },
          zoom,
          mapId: "DEMO_MAP_ID",
          mapTypeControl: false,
          streetViewControl: false,
          clickableIcons: false,
          gestureHandling: "greedy",
        });
        m.addListener("click", (e) => {
          if (!alClicMapa.current) return;
          if (m.getZoom() < ZOOM_MIN_MARCAR) {
            m.setCenter(e.latLng);
            m.setZoom(Math.min(m.getZoom() + 4, ZOOM_MIN_MARCAR));
            return;
          }
          alClicMapa.current(e.latLng.lat(), e.latLng.lng());
        });
        mapa.current = m;
        setListo(true);
      })
      .catch(() => vivo && alFallar());
    return () => {
      vivo = false;
      for (const lista of Object.values(capas.current)) quitar(lista);
      for (const u of enRuta.current.values()) {
        u.linea.setMap(null);
        u.marca.map = null;
      }
      enRuta.current.clear();
      mapa.current = null;
    };
  }, []);

  const marca = (lat, lng, html, opciones = {}) =>
    new gm.current.marker.AdvancedMarkerElement({
      map: mapa.current,
      position: { lat, lng },
      content: punto(html),
      ...opciones,
    });

  useEffect(() => {
    if (!listo || encuadrado.current || !encuadre.length) return;
    encuadrado.current = true;
    if (encuadre.length === 1) {
      mapa.current.setCenter({ lat: encuadre[0][0], lng: encuadre[0][1] });
      mapa.current.setZoom(ZOOM_MAX_ENCUADRE);
      return;
    }
    const caja = new gm.current.LatLngBounds();
    encuadre.forEach(([lat, lng]) => caja.extend({ lat, lng }));
    mapa.current.fitBounds(caja, 36);
    gm.current.event.addListenerOnce(mapa.current, "idle", () => {
      if (mapa.current.getZoom() > ZOOM_MAX_ENCUADRE) mapa.current.setZoom(ZOOM_MAX_ENCUADRE);
    });
  }, [listo, encuadre]);

  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.zonas);
    zonas.forEach((z) => {
      const c = new gm.current.Circle({
        map: mapa.current,
        center: { lat: z.lat, lng: z.lng },
        radius: z.radio_m,
        strokeColor: ROJO,
        strokeOpacity: 0.45,
        strokeWeight: 1,
        fillColor: ROJO,
        fillOpacity: Math.min(0.4, Math.max(0.25, z.opacidad)),
        clickable: false,
      });
      capas.current.zonas.push(c);
    });
  }, [listo, zonas]);

  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.camaras);
    camaras.forEach((c) =>
      capas.current.camaras.push(
        marca(c.lat, c.lng, `<span class="so-camara${c.activa ? "" : " so-inactiva"}"></span>`, {
          title: `Cámara · ${c.nombre}${c.activa ? "" : " (en revisión)"}`,
        }),
      ),
    );
  }, [listo, camaras]);

  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.unidades);
    unidades
      .filter((u) => u.estado === "libre")
      .forEach((u) =>
        capas.current.unidades.push(
          marca(u.lat, u.lng, '<span class="so-unidad"></span>', { title: `${u.id} · ${u.base} · libre`, zIndex: 500 }),
        ),
      );
  }, [listo, unidades]);

  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.alertas);
    alertas.forEach((a) => {
      const sel = a.id === seleccion ? " so-sel" : "";
      const resuelto = a.caso === "resuelto";
      const estado = { pendiente: "pendiente", en_camino: "unidad en camino", resuelto: "atendido y resuelto" }[a.caso] || "";
      const m = marca(a.lat, a.lng, `<span class="so-alerta${resuelto ? " so-resuelto" : ""}${sel}"></span>`, {
        title: `${a.tipo_txt} · ${a.sev_txt} · ${estado} · ${a.hora}`,
        zIndex: resuelto ? 600 : 1000,
        gmpClickable: true,
      });
      m.addListener("click", () => alClic.current && alClic.current(a.id));
      capas.current.alertas.push(m);
    });
  }, [listo, alertas, seleccion]);

  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.rondines);
    rondines.forEach((r) =>
      capas.current.rondines.push(marca(r.lat, r.lng, '<span class="so-rondin"></span>', { title: r.texto, zIndex: 2000 })),
    );
  }, [listo, rondines]);

  useEffect(() => {
    if (!listo) return;
    if (pin.current) {
      pin.current.map = null;
      pin.current = null;
    }
    if (marcador.length !== 2) return;
    pin.current = marca(marcador[0], marcador[1], '<span class="so-alerta so-sel"></span>', {
      title: `${marcador[0].toFixed(6)}, ${marcador[1].toFixed(6)}`,
      zIndex: 5000,
    });
    const m = mapa.current;
    const aqui = new gm.current.LatLng(marcador[0], marcador[1]);
    if (m.getZoom() < 14 || !m.getBounds() || !m.getBounds().contains(aqui)) {
      m.setCenter(aqui);
      if (m.getZoom() < 14) m.setZoom(16);
    }
  }, [listo, marcador[0], marcador[1]]);

  // Patrulla asignada: solo la unidad que atiende un incidente se mueve por su ruta.
  useEffect(() => {
    if (!listo) return;
    const vigentes = new Set();
    const ahora = Date.now();
    patrullas.forEach((p) => {
      const llego = p.estado === "resuelto";
      if (llego && ahora - (p.llegada_real_ms || p.llegada_ms) > PATRULLA_VISIBLE_TRAS_LLEGAR_MS) return;
      if (!p.ruta || p.ruta.length < 2) return;
      vigentes.add(p.id);
      let u = enRuta.current.get(p.id);
      if (!u) {
        const acum = [0];
        for (let i = 1; i < p.ruta.length; i++) acum.push(acum[i - 1] + distancia(p.ruta[i - 1], p.ruta[i]));
        const camino = p.ruta.map(([lat, lng]) => ({ lat, lng }));
        u = {
          linea: new gm.current.Polyline({
            map: mapa.current,
            path: camino,
            strokeOpacity: 0,
            icons: [{ icon: { path: "M 0,-1 0,1", strokeColor: AZUL, strokeOpacity: 0.75, scale: 3 }, offset: "0", repeat: "12px" }],
          }),
          marca: marca(p.ruta[0][0], p.ruta[0][1], '<span class="so-patrulla"></span>', {
            title: `${p.unidad} · en camino`,
            zIndex: 3000,
          }),
          acum,
        };
        enRuta.current.set(p.id, u);
        if (!llego && ahora - p.inicio_ms < 15000) {
          const caja = new gm.current.LatLngBounds();
          camino.forEach((x) => caja.extend(x));
          mapa.current.fitBounds(caja, 40);
        }
      }
      u.datos = p;
      if (llego) {
        u.linea.setMap(null);
        u.marca.content = punto('<span class="so-patrulla so-llego"></span>');
        u.marca.title = `${p.unidad} · en el lugar: caso resuelto`;
      }
    });
    for (const [id, u] of enRuta.current) {
      if (!vigentes.has(id)) {
        u.linea.setMap(null);
        u.marca.map = null;
        enRuta.current.delete(id);
      }
    }
  }, [listo, patrullas]);

  useEffect(() => {
    let cuadro;
    const animar = () => {
      const ahora = Date.now();
      for (const u of enRuta.current.values()) {
        const p = u.datos;
        const fraccion = p.estado === "resuelto" ? 1 : Math.min(1, Math.max(0, (ahora - p.inicio_ms) / (p.llegada_ms - p.inicio_ms)));
        const [lat, lng] = sobreRuta(p.ruta, u.acum, fraccion);
        u.marca.position = { lat, lng };
      }
      cuadro = requestAnimationFrame(animar);
    };
    cuadro = requestAnimationFrame(animar);
    return () => cancelAnimationFrame(cuadro);
  }, []);

  useEffect(() => {
    if (!listo || foco.length !== 3) return;
    encuadrado.current = true;
    mapa.current.panTo({ lat: foco[0], lng: foco[1] });
    mapa.current.setZoom(16);
  }, [listo, foco[2]]);

  useEffect(() => {
    if (!listo) return;
    const elegida = alertas.find((a) => a.id === seleccion);
    const caja = mapa.current.getBounds();
    if (elegida && caja && !caja.contains({ lat: elegida.lat, lng: elegida.lng })) {
      mapa.current.panTo({ lat: elegida.lat, lng: elegida.lng });
    }
  }, [listo, seleccion]);

  // Calor: celdas de ~1 km; más eventos = círculo más oscuro y opaco.
  useEffect(() => {
    if (!listo) return;
    quitar(capas.current.calor);
    if (!calor.length) return;
    const celdas = new Map();
    calor.forEach(([lat, lng]) => {
      const k = `${Math.round(lat * 100)}|${Math.round(lng * 100)}`;
      const c = celdas.get(k) || { lat: 0, lng: 0, n: 0 };
      c.lat += lat;
      c.lng += lng;
      c.n += 1;
      celdas.set(k, c);
    });
    const tope = Math.max(...[...celdas.values()].map((c) => c.n));
    for (const c of celdas.values()) {
      const t = c.n / tope;
      capas.current.calor.push(
        new gm.current.Circle({
          map: mapa.current,
          center: { lat: c.lat / c.n, lng: c.lng / c.n },
          radius: 350 + 650 * t,
          strokeWeight: 0,
          fillColor: t > 0.66 ? "#7f1d1d" : t > 0.33 ? "#dc2626" : "#f87171",
          fillOpacity: 0.2 + 0.45 * t,
          clickable: false,
        }),
      );
    }
  }, [listo, calor]);

  return (
    <>
      <style>{CSS}</style>
      <div
        ref={nodo}
        className="so-mapa"
        style={{ height: altura, cursor: onClicMapa ? "crosshair" : undefined }}
        role="application"
        aria-label="Mapa de la región"
      />
    </>
  );
}
