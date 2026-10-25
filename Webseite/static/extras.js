/* Additional guided controls; shares the dashboard's validated settings API. */
function scanCategory(category) {
 return currentBot().channel_labels?.[category] || (category==='streams'?'Livestreams (bisheriges Ziel)':null)
  || (currentBot().command_defaults?.[category]?'Befehl /'+(settings().command_settings?.[category]?.name||currentBot().command_defaults[category][0]):null)
  || ({dashboard:'Dashboard-Nachrichten',history:'Älterer Verlauf',command:'Befehlsantworten'}[category]) || category;
}
function formatDiscordText(value) {
 const raw=String(value??''),pattern=/\[([^\]\n]+)\]\((https:\/\/[^\s)]+)\)|<#(\d+)>|<@!?(\d+)>|<@&(\d+)>|`(\d{15,22})`|(?<![\w/])(\d{15,22})(?!\d)/g;
 const prose=text=>esc(text).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
 let out='',offset=0;for(const match of raw.matchAll(pattern)){
  out+=prose(raw.slice(offset,match.index));offset=match.index+match[0].length;
  if(match[2]){try{const u=new URL(match[2]);out+=u.protocol==='https:'&&!u.username&&!u.password?`<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(match[1])} ↗</a>`:prose(match[0]);}catch{out+=prose(match[0]);}}
  else out+=entity(match[3]||match[4]||match[5]||match[6]||match[7],match[3]?'channel':match[5]?'role':'member');
 }return out+prose(raw.slice(offset));
}
function enhanceConfiguration(c) {
 const allowed=bot==='jarvis'?['links','birthdays','rank','activity','notifications','join_log','message_logs','server_logs','unban','untimeout','reinvite']:['leave_log','timeout','ban','kick'];
 const roleOptions=(value)=>'<option value="">Rolle auswählen</option>'+(guild().roles||[]).map(r=>`<option value="${esc(r.id)}" ${String(value)===String(r.id)?'selected':''}>${esc(idLabel(r.name,r.id))}</option>`).join('');
 const row=(level='',role='')=>`<div class="level-row inline-fields"><label>Ab Stufe<input name="level" type="number" min="0" value="${esc(level)}" required></label><label>Belohnungsrolle<select name="role" required>${roleOptions(role)}</select></label><button type="button" class="quiet remove-level">Eintrag entfernen</button></div>`;
 $('#advanced-form').closest('details').insertAdjacentHTML('beforebegin',`<div class="grid-2"><form id="features-form" class="panel"><h2>◈ Aktive Aufgaben</h2><p>Schalte einzelne Aufgaben dieses Bots an oder aus. Die grundsätzliche Aufteilung zwischen Jarvis und Ultron bleibt erhalten.</p>${allowed.map(key=>`<label class="check"><input type="checkbox" name="${key}" ${c.features.includes(key)?'checked':''}>${esc(featureLabels[key])}</label>`).join('')}<button class="primary">Aufgaben speichern</button><p class="small" style="margin-top:14px">Danach unter Befehle „Befehle aktualisieren“ verwenden.</p></form><section class="panel"><h2>📅 Geburtstag am 29. Februar</h2><form id="leap-form"><label>In Jahren ohne 29. Februar gratulieren<select name="leap">${[['feb28','Am 28. Februar'],['mar1','Am 1. März'],['only_leap_years','Nur in Schaltjahren']].map(([key,label])=>`<option value="${key}" ${c.leap_day===key?'selected':''}>${label}</option>`).join('')}</select></label><button class="primary">Geburtstagsregel speichern</button></form></section></div>${bot==='jarvis'?`<form id="level-form" class="panel"><h2>🏅 Belohnungen für Aktivität</h2><p>Ab welcher Stufe soll welche Rolle vergeben werden? Verwaltungsrollen sind nicht als Belohnung erlaubt. Die Botrolle muss über der Belohnungsrolle stehen.</p><div id="level-rows">${Object.entries(c.level_roles||{}).map(([l,r])=>row(l,r)).join('')}</div><div class="button-row"><button type="button" id="add-level" class="quiet">+ Belohnungsrolle</button><button class="primary">Stufenrollen speichern</button></div></form>`:''}`);
 bindForm('#features-form',async(f,b)=>action('settings',{patch:{features:allowed.filter(key=>f.elements[key].checked)}},b));
 bindForm('#leap-form',async(f,b)=>action('settings',{patch:{leap_day:f.elements.leap.value}},b));
 if(bot==='jarvis'){
  const remove=()=>$$('.remove-level').forEach(b=>b.onclick=()=>b.closest('.level-row').remove());remove();
  $('#add-level').onclick=()=>{$('#level-rows').insertAdjacentHTML('beforeend',row());remove();};
  bindForm('#level-form',async(f,b)=>{const level_roles={};for(const el of $$('.level-row')){const key=$('[name=level]',el).value;if(key in level_roles)throw Error('Jede Stufe bitte nur einmal verwenden.');level_roles[key]=$('[name=role]',el).value;}await action('settings',{patch:{level_roles}},b);});
 }
}
