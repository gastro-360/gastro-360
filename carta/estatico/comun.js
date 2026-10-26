// SPDX-License-Identifier: EUPL-1.2
// Utilidades compartidas por la carta, la cocina y el backoffice.
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
