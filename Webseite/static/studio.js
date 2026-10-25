/* Local studio shell. All authorization is also enforced by the server. */
const pagePermissions={overview:['view.overview','view.analytics'],channels:['edit.channels','view.settings'],sources:['edit.links','edit.sources','view.settings'],commands:['edit.commands','run.sync','view.settings'],embeds:['edit.embeds','send.messages'],settings:['view.settings','edit.activity','edit.birthdays','edit.general','edit.roles','edit.embeds','edit.sources'],logs:['view.logs','run.scan'],moderation:['moderate.ban','moderate.unban','moderate.timeout','moderate.kick','moderate.untimeout','moderate.reinvite','view.logs'],access:[]};
const settingPermissions={birthday_time:'edit.birthdays',timezone:'edit.birthdays',leap_day:'edit.birthdays',text_xp:'edit.activity',minimum_message_length:'edit.activity',text_cooldown_seconds:'edit.activity',voice_enabled:'edit.activity',voice_xp_per_minute:'edit.activity',voice_message_xp_per_minute:'edit.activity',voice_minimum_members:'edit.activity',poll_seconds:'edit.sources',live_poll_seconds:'edit.sources',color:'edit.embeds',creator_name:'edit.general',log_message_content:'edit.general'};
pagePermissions.members=['view.members'];
function can(permission){return !!currentUser&&(currentUser.is_owner||(currentUser.permissions||[]).includes(permission));}
function pageAllowed(key){return key==='access'||(pagePermissions[key]||[]).some(can);}
function idLabel(name,id){return currentUser?.preferences?.identity_order==='id'?`${id} · ${name||'Name nicht verfügbar'}`:`${name||'Name nicht verfügbar'} · ${id}`;}
function identity(name,id){
 const sid=String(id??'');if(!sid)return esc(name||'Nicht verfügbar');
 return `<span class="identity ${currentUser?.preferences?.identity_order==='id'?'id-first':''}"><button type="button" class="identity-name" data-copy-name="${esc(name&&String(name)!==sid?name:'')}" title="Namen kopieren" aria-label="Name ${esc(name||'nicht verfügbar')} kopieren">${esc(name&&String(name)!==sid?name:'Name nicht verfügbar')}<span aria-hidden="true"> ⧉</span></button><button type="button" class="identity-id" data-copy-id="${esc(sid)}" title="ID kopieren: ${esc(sid)}" aria-label="ID ${esc(sid)} kopieren">${esc(sid)}<span aria-hidden="true"> ⧉</span></button></span>`;
}
function entity(id,kind='member'){
 const g=guild(),list=kind==='channel'?g?.channels:kind==='role'?g?.roles:g?.members;
 const name=(list||[]).find(x=>String(x.id)===String(id))?.name;
 const found=name||(g?.channels||[]).find(x=>String(x.id)===String(id))?.name||(g?.roles||[]).find(x=>String(x.id)===String(id))?.name||(g?.members||[]).find(x=>String(x.id)===String(id))?.name||(g?.moderation_history||[]).find(x=>String(x.user)===String(id))?.name;
 return identity(found,id);
}
function eventCards(events){return events.map(e=>{
 const member=String(e.text||'').match(/(?:^|\n)Mitglied: (\d{15,22}) · ([^\n]+)/);
 let body=member?String(e.text).replace(member[0],''):e.text;
 const safeLink=url=>/^https:\/\/discord\.com\/channels\/\d+\/\d+\/\d+$/.test(url||'');
 return `<article class="timeline-item"><div class="event-topline"><span class="event-type">${/beigetreten/i.test(e.title)?'BEITRITT':/ausgetreten/i.test(e.title)?'ABSCHIED':/nachricht/i.test(e.title)?'NACHRICHT':'SERVER'}</span><small>${esc(new Date(e.created).toLocaleString('de-AT'))} · #${esc(e.id)}</small></div><h3>${esc(e.title)}</h3>${member?`<div class="event-member">${identity(member[2],member[1])}</div>`:''}${body?`<p>${formatDiscordText(body)}</p>`:''}${safeLink(e.log_url)||safeLink(e.source_url)?`<div class="button-row event-links">${safeLink(e.log_url)&&!e.log_deleted?`<a href="${esc(e.log_url)}" target="_blank" rel="noopener noreferrer">Protokoll in Discord ↗</a>`:''}${safeLink(e.source_url)&&!e.source_deleted?`<a href="${esc(e.source_url)}" target="_blank" rel="noopener noreferrer">${/beigetreten/i.test(e.title)?'Willkommensnachricht':/ausgetreten/i.test(e.title)?'Abschiedsnachricht':'Ursprüngliche Nachricht'} ↗</a>`:''}${e.source_deleted?'<span class="small muted">Zugehörige Nachricht gelöscht.</span>':''}${e.log_deleted?'<span class="small muted">Protokollnachricht gelöscht.</span>':''}</div>`:''}</article>`;
 }).join('');}
function studioIcon(key){
 const shapes={overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',channels:'<path d="M9 3 7 21M17 3l-2 18M3 9h18M2 16h18"/>',sources:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 6 3-6 3z"/>',commands:'<path d="m5 7 5 5-5 5m8 0h6"/><rect x="2" y="3" width="20" height="18" rx="2"/>',embeds:'<path d="M3 3h18v18H3zM3 8h18m-13 0v13m3-9h6m-6 4h4"/>',settings:'<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',logs:'<path d="M7 3h10l3 3v15H4V3zM8 9h8m-8 4h8m-8 4h5"/>',moderation:'<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6zM8 12l3 3 5-6"/>',access:'<circle cx="9" cy="7" r="4"/><path d="M2 21v-3a7 7 0 0 1 12-5m3 0v8m-4-4h8"/>'};
 return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[key]||shapes.overview}</svg>`;
}
function botArtwork(name){
 if(name==='jarvis')return `<svg class="bot-art jarvis-art" viewBox="0 0 240 180" role="img" aria-label="Jarvis: goldener Rechenkern"><defs><radialGradient id="core"><stop stop-color="#f6dba5"/><stop offset="1" stop-color="#8b672f" stop-opacity="0"/></radialGradient></defs><circle cx="120" cy="90" r="71" fill="url(#core)" opacity=".3"/><g class="orbit"><ellipse cx="120" cy="90" rx="69" ry="69"/><ellipse cx="120" cy="90" rx="48" ry="69" transform="rotate(38 120 90)"/><ellipse cx="120" cy="90" rx="69" ry="32" transform="rotate(-30 120 90)"/><circle cx="120" cy="90" r="58" stroke-dasharray="3 10"/></g><path d="M45 90h46m57 0h50M120 20v42m0 56v42" stroke-dasharray="4 5"/><circle class="core-pulse" cx="120" cy="90" r="18"/><circle cx="120" cy="90" r="9" fill="currentColor"/><g fill="currentColor"><circle cx="60" cy="57" r="4"/><circle cx="183" cy="116" r="4"/><circle cx="109" cy="22" r="3"/></g><path d="M22 40V25h23m150 130h23v-15" stroke-opacity=".4"/></svg>`;
 return `<svg class="bot-art ultron-art" viewBox="0 0 240 180" role="img" aria-label="Ultron: metallischer Wächter"><path d="m86 28 34-10 34 10 17 29-8 70-22 26h-42l-22-26-8-70z" fill="#3e4547"/><path d="m86 28 18 30-7 53 23 28 23-28-7-53 18-30M120 18v71m-43 38 20-16m66 16-20-16m-44 42 9-27h24l9 27"/><path d="m81 65 21 7-3 10-16-6m76-11-21 7 3 10 16-6" class="eye-glow" fill="currentColor"/><path d="m108 97 12-8 12 8-12 12z" fill="#202727"/><path d="m104 118 16 4 16-4m-62-54-12 10v33l14 12m90-55 12 10v33l-14 12"/><path d="M42 25H25v20m173 110h17v-20" stroke-opacity=".4"/></svg>`;
}
function applyPreferences(){
 const p=currentUser?.preferences||{};document.documentElement.dataset.theme=p.theme||'retro';document.documentElement.dataset.reducedMotion=String(!!p.reduced_motion);
 $('#theme-switch').value=p.theme||'retro';$('#identity-switch').textContent=p.identity_order==='id'?'ID · Name':'Name · ID';
 $('#account-name').textContent=currentUser?.display_name||currentUser?.username||'Gast';$('#account-initial').textContent=(currentUser?.display_name||'B')[0].toUpperCase();$('#account-role').textContent=currentUser?.is_owner?'Inhaber · alle Rechte':'Persönlicher Zugang';
}
async function savePreference(patch){const r=await api('/api/preferences',{method:'PATCH',body:JSON.stringify(patch)});currentUser=r.user||{...currentUser,preferences:{...currentUser.preferences,...patch}};applyPreferences();render();}
$('#theme-switch').onchange=e=>savePreference({theme:e.target.value}).catch(e=>toast(e.message,true));
$('#identity-switch').onclick=()=>savePreference({identity_order:currentUser?.preferences?.identity_order==='id'?'name':'id'}).catch(e=>toast(e.message,true));
window.addEventListener('dashboard-user-updated',e=>{currentUser=e.detail;applyPreferences();render();});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-copy-id], [data-copy-name]');if(!b)return;e.preventDefault();const value=b.dataset.copyId||b.dataset.copyName;if(!value)return;const label=b.dataset.copyId?'ID':'Name';try{if(!navigator.clipboard?.writeText)throw Error();await navigator.clipboard.writeText(value);toast(label+' kopiert: '+value);}catch{await ask(label+' kopieren',value+'\nMarkiere und kopiere den Text. Dein Browser erlaubt hier keinen direkten Zugriff auf die Zwischenablage.','Schließen');}});

function overviewV3(){
 const g=guild(),s=g?.stats||{},viewer=currentUser?.display_name||currentUser?.username||'du';
 const features=[['embeds','Nachrichten mit Charakter.','Vorlagen, Texte und Bildkarten gestalten.'],['channels','Alles an seinem Platz.','Kanäle und Forum-Beiträge zuordnen.'],['sources','Deine Inhalte kommen an.','Quellen und Ankündigungen abstimmen.'],['commands','Klar, was zu tun ist.','Befehle verständlich beschreiben.'],['logs','Den Überblick behalten.','Ereignisse und ihre Verweise nachlesen.'],['access','Zusammen arbeiten.','Persönliche Zugänge und Darstellung.']].filter(([k])=>pageAllowed(k));
 $('#content').innerHTML=`<div class="studio-intro"><div><span class="issue-label">MITTELKAP / ARBEITSPLATZ 04</span><h2>Guten Tag, ${esc(viewer)}<span class="orange-period">.</span></h2><p>Deine Community. Zwei Charaktere. Hier stellst du ein, wie sie zusammenarbeiten.</p></div><div class="studio-seal" aria-hidden="true"><span>MK</span><small>BOT<br>STUDIO</small></div></div>
 <div class="metrics">${[['Mitglieder',s.members,'aktuell auf dem Server'],['Nachrichten',s.messages,'seit Beginn der Erfassung'],['Sprachminuten',s.voice_seconds===undefined?undefined:Math.floor(s.voice_seconds/60),'erfasste Anwesenheit'],['Geburtstage',s.birthdays,'freiwillig eingetragen']].map(([l,n,h],i)=>`<div class="metric"><div class="metric-label"><span>${l}</span><span class="metric-index">0${i+1}</span></div><strong>${n===undefined?'—':number(n)}</strong><small>${n===undefined?'Für diesen Zugang nicht verfügbar':h}</small></div>`).join('')}</div>
 <div class="grid-2 bot-pair">${['jarvis','ultron'].map(name=>{const b=data.bots.find(x=>x.bot===name);return `<section class="bot-card ${name}"><div class="window-title"><span>${name==='jarvis'?'01 / ASSISTENZ':'02 / MODERATION'}</span>${badge(b?.online)}</div><div class="bot-card-body"><div><h2>${name==='jarvis'?'J.A.R.V.I.S.':'ULTRON'}</h2><p>${name==='jarvis'?'Ein guter Empfang. Hilfreiche Antworten. Zeit für die Community.':'Klare Grenzen. Nachvollziehbare Entscheidungen. Ordnung im Server.'}</p><div class="bot-tags">${name==='jarvis'?'<span>Begrüßung</span><span>Geburtstage</span><span>Aktivität</span>':'<span>Abschied</span><span>Moderation</span>'}</div></div>${botArtwork(name)}</div><div class="bot-card-bottom"><small>${b?.online?'Verbindung zu Discord steht.':'Aktuell keine aktive Verbindung.'}</small>${pageAllowed('settings')?`<a href="#settings" data-open-bot="${name}">Einstellungen öffnen ↗</a>`:''}</div></section>`;}).join('')}</div>
 <div class="section-title"><h2>Was möchtest du anpassen?</h2><span class="issue-label">WERKZEUGE</span></div><div class="grid-3 workbench">${features.map(([path,title,desc],i)=>`<a href="#${path}" class="feature-card"><div class="feature-top">${studioIcon(path)}<span>0${i+1} ↗</span></div><h3>${title}</h3><p>${desc}</p></a>`).join('')}</div>
 ${g?.leaders?.length?`<section class="panel activity-panel"><div class="panel-head"><div><div class="eyebrow">AKTIVITÄT / GESAMTER ZEITRAUM</div><h2>Die Community in Bewegung.</h2></div><span class="stamp">TOP ${g.leaders.length}</span></div><div class="activity-list">${g.leaders.map((m,i)=>`<div class="activity-row"><span class="activity-place">${String(i+1).padStart(2,'0')}</span><div>${identity(m.name,m.user||m.id)}<div class="bar"><span style="width:${Math.max(1,Math.min(100,Number(m.xp)/(Number(g.leaders[0].xp)||1)*100))}%"></span></div></div><strong>${number(m.xp)}<small> XP</small></strong><span class="small muted">${number(m.messages)} Nachrichten</span></div>`).join('')}</div></section>`:''}`;
 $$('[data-open-bot]').forEach(el=>el.onclick=()=>bot=el.dataset.openBot);
}
function membersPage(){
 const g=guild();$('#content').innerHTML=`<div class="panel"><label>Mitglied oder Rolle finden<input id="member-search" type="search" placeholder="Name oder vollständige ID"></label><p class="small">Der Bot überträgt bis zu 1.000 Mitglieder. Angezeigt werden verfügbare Discord-Namen; Webkonten verwaltest du unter „Konten & Darstellung“.</p></div><div class="grid-2"><section class="panel"><h2>Mitglieder <small id="member-count"></small></h2><div id="member-list"></div></section><section class="panel"><h2>Serverrollen <small id="role-count"></small></h2><div id="role-list"></div></section></div>`;
 const draw=()=>{const q=$('#member-search').value.trim().toLocaleLowerCase('de');for(const [items,selector,counter] of [[g.members||[],'#member-list','#member-count'],[g.roles||[],'#role-list','#role-count']]){const filtered=items.filter(x=>(x.name+' '+x.id).toLocaleLowerCase('de').includes(q));$(selector).innerHTML=filtered.map(x=>`<div class="entity-row">${identity(x.name,x.id)}</div>`).join('')||'<p>Keine passenden Einträge.</p>';$(counter).textContent=filtered.length+' / '+items.length;}};$('#member-search').oninput=draw;draw();
}
function lockForm(selector,permission){const f=$(selector);if(!f||can(permission))return;f.querySelectorAll('input,select,textarea,button').forEach(e=>e.disabled=true);const n=document.createElement('p');n.className='read-note';n.textContent='Du kannst diesen Bereich ansehen. Zum Ändern fehlt deinem Konto die Freigabe.';f.append(n);}
function decoratePage(){
 let serverLabel=$('.server-identity');if(!serverLabel){serverLabel=document.createElement('div');serverLabel.className='server-identity';$('.server-card').after(serverLabel);}serverLabel.innerHTML=guild()?identity(guild().name,guild().id):'';
 if(!can('view.settings')){
  if(!can('edit.general'))$('#features-form')?.remove();
  if(!can('edit.birthdays'))$('#leap-form')?.closest('section')?.remove();
  if(!can('edit.roles'))$('#level-form')?.remove();
  if(!can('edit.embeds'))$('#messages-form')?.remove();
  if(!can('edit.links'))$('#links-form')?.closest('section')?.remove();
  if(!can('edit.sources')){$('#sources-form')?.closest('.panel')?.remove();$('#delay-form')?.closest('.panel')?.remove();}
  if(page==='commands'&&!can('edit.commands')){$$('.command-card').forEach(e=>e.remove());$('#commands-form .primary')?.remove();}
  if(!can('run.scan'))$('#scan-form')?.remove();
 }
 // Keep forms understandable even for restricted accounts. This supplements API checks.
 for(const [selector,p] of Object.entries({'#channels-form':'edit.channels','#links-form':'edit.links','#sources-form':'edit.sources','#delay-form':'edit.sources','#commands-form':'edit.commands','#messages-form':'edit.embeds','#features-form':'edit.general','#leap-form':'edit.birthdays','#level-form':'edit.roles','#scan-form':'run.scan'}))lockForm(selector,p);
 $$('#settings-form input').forEach(el=>el.disabled=!can(settingPermissions[el.name]||'edit.general'));
 const save=$('#settings-form button');if(save)save.disabled=!$$('#settings-form input').some(el=>!el.disabled);
 if(!currentUser?.is_owner){$('#roles-form')?.remove();$('#advanced-form')?.closest('details')?.remove();}
 if($('#sync'))$('#sync').disabled=!can('run.sync');
 // Selected objects show a copyable ID beside their human name.
 $$('select', $('#content')).filter(s=>!s.multiple).forEach(s=>{
  if(![...s.options].some(o=>/^\d{15,22}$/.test(o.value)))return;
  const list=[...(guild()?.channels||[]),...(guild()?.roles||[]),...(guild()?.members||[])];
  const draw=()=>{let detail=s.nextElementSibling;if(!detail?.classList.contains('selected-identity')){detail=document.createElement('div');detail.className='selected-identity';s.after(detail);}const item=list.find(x=>String(x.id)===s.value);detail.innerHTML=s.value?identity(item?.name,s.value):'';};draw();s.addEventListener('change',draw);
 });
 enhanceIdPickers();
}
