/* SPDX-License-Identifier: EUPL-1.2 */
/* Ocho idiomas en el navegador: castellano (es, la fuente), inglés (en), catalán (ca), chino simplificado (zh), francés (fr),
   alemán (de), italiano (it) y portugués europeo (pt).
   Se carga la primera, antes que cualquier otro script de la página, y trae los diccionarios (i18n/es.js y i18n/<idioma>.js) de forma
   síncrona, de modo que I18N.t() ya funciona en el resto de scripts.
   Elección del idioma: el que la persona eligió (almacenamiento local de este navegador, sin cookies) > el de la primera visita según
   Accept-Language (lo pone el servidor en <meta name="gastro-idioma">) > los idiomas del navegador > castellano.
   Nada se traduce por su cuenta: cada texto lo ha redactado una persona. Una clave que falta cae a castellano. */
(function () {
  var IDIOMAS = ['es', 'en', 'ca', 'zh', 'fr', 'de', 'it', 'pt'];
  var NOMBRES = { es: 'Castellano', en: 'English', ca: 'Català', zh: '中文', fr: 'Français', de: 'Deutsch', it: 'Italiano', pt: 'Português' };
  var CLAVE = 'gastro_idioma';
  var script = document.currentScript;
  var raiz = script && script.src ? script.src.replace(/[^\/]*$/, '') : '/';

  function lee() { try { return localStorage.getItem(CLAVE); } catch (e) { return null; } }
  function guarda(v) { try { localStorage.setItem(CLAVE, v); } catch (e) { /* sin almacenamiento: vale para esta visita */ } }
  function base(etiqueta) { return String(etiqueta || '').toLowerCase().split(/[-_]/)[0]; }
  function valido(l) { return IDIOMAS.indexOf(l) >= 0 ? l : null; }
  function delNavegador() {
    var ls = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language];
    for (var i = 0; i < ls.length; i++) { if (valido(base(ls[i]))) return base(ls[i]); }
    return null;
  }
  var meta = document.querySelector('meta[name="gastro-idioma"]');
  var lang = valido(lee()) || valido(meta && meta.content) || delNavegador() || 'es';
  document.documentElement.lang = lang;

  window.I18N_DIC = window.I18N_DIC || {};
  document.write('<script src="' + raiz + 'i18n/es.js"><\/script>');
  if (lang !== 'es') document.write('<script src="' + raiz + 'i18n/' + lang + '.js"><\/script>');

  function dic(l) { return (window.I18N_DIC && window.I18N_DIC[l]) || {}; }
  function relleno(txt, p, escapar) {
    return txt.replace(/\{(\w+)\}/g, function (m, k) {
      if (!p || p[k] === undefined || p[k] === null) return m;
      return escapar ? esc(p[k]) : String(p[k]);
    });
  }
  function esc(s) {
    return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function bruto(clave) {
    var v = dic(lang)[clave];
    if (v === undefined) v = dic('es')[clave];
    return v === undefined ? clave : v;
  }

  var MESES = {
    es: 'enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'.split(' '),
    en: 'January February March April May June July August September October November December'.split(' '),
    ca: 'gener febrer març abril maig juny juliol agost setembre octubre novembre desembre'.split(' '),
    zh: '1月 2月 3月 4月 5月 6月 7月 8月 9月 10月 11月 12月'.split(' '),
    fr: 'janvier février mars avril mai juin juillet août septembre octobre novembre décembre'.split(' '),
    de: 'Januar Februar März April Mai Juni Juli August September Oktober November Dezember'.split(' '),
    it: 'gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split(' '),
    pt: 'janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro'.split(' ')
  };
  var DIAS = {   // de domingo (0) a sábado (6), como Date.getDay()
    es: 'domingo lunes martes miércoles jueves viernes sábado'.split(' '),
    en: 'Sunday Monday Tuesday Wednesday Thursday Friday Saturday'.split(' '),
    ca: 'diumenge dilluns dimarts dimecres dijous divendres dissabte'.split(' '),
    zh: '星期日 星期一 星期二 星期三 星期四 星期五 星期六'.split(' '),
    fr: 'dimanche lundi mardi mercredi jeudi vendredi samedi'.split(' '),
    de: 'Sonntag Montag Dienstag Mittwoch Donnerstag Freitag Samstag'.split(' '),
    it: 'domenica lunedì martedì mercoledì giovedì venerdì sabato'.split(' '),
    pt: 'domingo segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado'.split(' ')
  };
  // Separador de miles y de decimales de cada idioma (fr: espacio fino; pt: espacio duro)
  var SEPARADORES = { es: '.,', ca: '.,', de: '.,', it: '.,', en: ',.', zh: ',.', fr: '\u202f,', pt: '\u00a0,' };
  function dosCifras(n) { return (n < 10 ? '0' : '') + n; }
  function fechaDe(x) { return x instanceof Date ? x : new Date(typeof x === 'number' && x < 1e11 ? x * 1000 : x); }

  var cambios = [];
  var I18N = {
    idiomas: IDIOMAS, nombres: NOMBRES,
    get lang() { return lang; },
    t: function (clave, p) { return relleno(bruto(clave), p, false); },
    // Para meter en innerHTML: el texto del diccionario es de confianza, los valores {x} se escapan
    th: function (clave, p) { return relleno(bruto(clave), p, true); },
    // Plural: clave.uno (n = 1) o clave.otros; recibe {n}
    tn: function (clave, n, p) { return I18N.t(clave + (n === 1 ? '.uno' : '.otros'), Object.assign({ n: n }, p || {})); },
    // Un campo de la carta que rellena el dueño: texto (solo castellano) u objeto {es, en, ca, zh, fr, de, it, pt}; un idioma vacío cae a castellano
    tr: function (v, l) {
      if (v && typeof v === 'object') return v[l || lang] || v.es || '';
      return v == null ? '' : String(v);
    },
    esc: esc,
    numero: function (n, dec) {
      var d = dec === undefined ? 2 : dec, neg = n < 0, s = Math.abs(n).toFixed(d), partes = s.split('.');
      var sep = SEPARADORES[lang] || SEPARADORES.es;
      var ent = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, sep.charAt(0));
      return (neg ? '-' : '') + ent + (partes[1] ? sep.charAt(1) + partes[1] : '');
    },
    moneda: function (n) { var s = I18N.numero(n, 2); return (lang === 'en' || lang === 'zh') ? '€' + s : s + ' €'; },
    hora: function (x) { var d = fechaDe(x); return dosCifras(d.getHours()) + ':' + dosCifras(d.getMinutes()); },
    fecha: function (x) {
      var d = fechaDe(x), m = MESES[lang][d.getMonth()];
      if (lang === 'zh') return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日';
      if (lang === 'en' || lang === 'fr' || lang === 'it') return d.getDate() + ' ' + m + ' ' + d.getFullYear();
      if (lang === 'de') return d.getDate() + '. ' + m + ' ' + d.getFullYear();
      if (lang === 'ca') return d.getDate() + ' ' + (/^[aeiou]/.test(m) ? 'd’' : 'de ') + m + ' de ' + d.getFullYear();
      return d.getDate() + ' de ' + m + ' de ' + d.getFullYear();
    },
    fechaHora: function (x) { return I18N.fecha(x) + (lang === 'zh' ? ' ' : ', ') + I18N.hora(x); },
    diaSemana: function (x) { return DIAS[lang][fechaDe(x).getDay()]; },
    // «2026-10» -> «octubre de 2026» · «October 2026» · «2026年10月» · «octobre 2026»
    mes: function (ym) {
      var a = String(ym).split('-'), y = +a[0], m = +a[1];
      if (lang === 'zh') return y + '年' + m + '月';
      if (lang === 'en' || lang === 'fr' || lang === 'de' || lang === 'it') return MESES[lang][m - 1] + ' ' + y;
      return MESES[lang][m - 1] + ' de ' + y;
    },
    // Campo de marca.json con idiomas (lema, intro…): window.MARCA_I18N lo pone la página
    marca: function (campo) { return I18N.tr((window.MARCA_I18N || {})[campo]); },
    // Rellena los elementos marcados:  data-i18n="clave"  ·  data-i18n-html="clave"  ·  data-i18n-attr="placeholder:clave;aria-label:otra"  ·  data-marca="lema"
    aplicar: function (r) {
      r = r || document;
      var q = function (s) { return Array.prototype.slice.call(r.querySelectorAll(s)); };
      q('[data-i18n]').forEach(function (e) { e.textContent = I18N.t(e.getAttribute('data-i18n')); });
      q('[data-i18n-html]').forEach(function (e) { e.innerHTML = I18N.th(e.getAttribute('data-i18n-html')); });
      q('[data-i18n-attr]').forEach(function (e) {
        e.getAttribute('data-i18n-attr').split(';').forEach(function (par) {
          var i = par.indexOf(':'); if (i > 0) e.setAttribute(par.slice(0, i).trim(), I18N.t(par.slice(i + 1).trim()));
        });
      });
      q('[data-marca]').forEach(function (e) { var v = I18N.marca(e.getAttribute('data-marca')); if (v) e.textContent = v; });
    },
    // Registra qué hace la página cuando cambia el idioma (volver a pintar lo suyo)
    alCambiar: function (fn) { cambios.push(fn); },
    cambiar: function (l) {
      if (!valido(l) || l === lang) return;
      lang = l; guarda(l); document.documentElement.lang = l;
      var cargar = function () { I18N.aplicar(); pintarSelectores(); cambios.forEach(function (fn) { fn(l); }); };
      if (window.I18N_DIC[l]) return cargar();
      var s = document.createElement('script');
      s.src = raiz + 'i18n/' + l + '.js'; s.onload = cargar; s.onerror = cargar;
      document.head.appendChild(s);
    },
    selector: function (donde) {
      var s = document.createElement('select');
      s.className = 'sel-idioma';
      IDIOMAS.forEach(function (l) {
        var o = document.createElement('option'); o.value = l; o.textContent = NOMBRES[l]; o.lang = l; s.appendChild(o);
      });
      s.addEventListener('change', function () { I18N.cambiar(s.value); });
      donde.appendChild(s); pintarSelectores();
      return s;
    }
  };
  function pintarSelectores() {
    Array.prototype.forEach.call(document.querySelectorAll('select.sel-idioma'), function (s) {
      s.value = lang; s.setAttribute('aria-label', I18N.t('comun.idioma'));
    });
  }
  window.I18N = I18N;

  // Todas las peticiones a este mismo servidor llevan el idioma elegido (errores, correos y tarjetas salen en él)
  if (window.fetch) {
    var original = window.fetch.bind(window);
    window.fetch = function (url, opc) {
      try {
        var u = new URL(typeof url === 'string' ? url : url.url, location.href);
        if (u.origin === location.origin) {
          opc = Object.assign({}, opc || {});
          var h = new Headers(opc.headers || (typeof url !== 'string' && url.headers) || {});
          h.set('X-Idioma', lang); opc.headers = h;
        }
      } catch (e) { /* se deja pasar tal cual */ }
      return original(url, opc);
    };
  }

  function listo() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-selector-idioma]'), function (e) {
      if (!e.firstChild) I18N.selector(e);
    });
    I18N.aplicar();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', listo); else listo();
})();
