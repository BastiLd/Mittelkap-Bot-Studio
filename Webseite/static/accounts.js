/* Dashboard accounts: explicit saves, delegated account administration, no credentials in state. */
(function () {
 'use strict';
 let accessRender = 0;
 const permissionHelp = {
  'view.overview':'Sieht Verbindungsstatus und die allgemeine Übersicht.', 'view.analytics':'Sieht Aktivitätszahlen und Ranglisten.',
  'view.logs':'Sieht gespeicherte Serverereignisse, Moderationsprotokolle und Nachrichtenverweise.', 'view.members':'Sieht die Namen und Discord-IDs von Servermitgliedern.',
  'view.settings':'Darf die aktuellen Bot-Einstellungen ansehen.', 'edit.channels':'Darf Ausgabekanäle und Forum-Beiträge ändern.',
  'edit.links':'Darf öffentliche Profil- und Gaminglinks ändern.', 'edit.sources':'Darf Inhaltsquellen und Stream-Wartezeiten ändern.',
  'edit.activity':'Darf XP-Werte und Sprachaktivität konfigurieren.', 'edit.birthdays':'Darf Uhrzeit und Regeln für Geburtstagsgrüße ändern.',
  'edit.commands':'Darf Namen, Erklärungen, Sichtbarkeit und erlaubte Kanäle der Befehle ändern.',
  'edit.embeds':'Darf Nachrichtenvorlagen und Bildkarten gestalten und speichern. Erlaubt allein keinen öffentlichen Versand.',
  'edit.general':'Darf allgemeine Bot-Einstellungen und aktive Funktionen ändern.', 'edit.roles':'Darf Belohnungsrollen für Stufen verwalten; Verwaltungs- und Schutzrollen bleiben Basti vorbehalten.',
  'run.scan':'Darf den Nachrichtenverlauf erneut einlesen lassen.', 'run.sync':'Darf gespeicherte Slash-Befehle bei Discord aktualisieren.',
  'send.messages':'Darf nach Bestätigung eine Nachricht über den Bot an einen ausgewählten Kanal senden.',
  'moderate.ban':'Darf Mitglieder über Ultron bannen. Botrechte und geschützte Nutzer werden weiterhin geprüft.',
  'moderate.unban':'Darf Serversperren über Jarvis aufheben.', 'moderate.timeout':'Darf Mitglieder über Ultron vorübergehend stummschalten.',
  'moderate.kick':'Darf Mitglieder über Ultron vom Server entfernen, ohne sie dauerhaft zu bannen.',
  'moderate.untimeout':'Darf laufende Stummschaltungen über Jarvis aufheben.',
  'moderate.reinvite':'Darf Einladungen erzeugen und mit ausdrücklich gewählter Benachrichtigung versenden. Wird zusätzlich bei Entbannen mit Einladung benötigt.',
  'users.create':'Darf neue normale Webkonten mit einem ersten Passwort anlegen. Anfangsrechte brauchen zusätzlich die Freigabe zur Rechtevergabe.',
  'users.edit':'Darf Anzeigenamen normaler Konten innerhalb der eigenen Freigaben ändern.',
  'users.password':'Darf Passwörter normaler Konten innerhalb der eigenen Freigaben zurücksetzen. Bestehende Sitzungen werden beendet.',
  'users.permissions':'Darf eigene Funktionsrechte an normale Konten weitergeben. Verwaltungsrechte kann ausschließlich Basti vergeben.',
  'users.disable':'Darf normale Konten innerhalb der eigenen Freigaben sperren und wieder freischalten.'
 };
 function changedUser(user) {
  if(user) window.dispatchEvent(new CustomEvent('dashboard-user-updated',{detail:user}));
 }
 function status(message,isError=false) {
  const target=$('#account-status'); if(target){target.textContent=message;target.classList.toggle('error',isError);}
  toast(message,isError);
 }
 function accountForm(user,catalog,m) {
  const fresh=!user, edit=fresh||m.can_edit, password=fresh||m.can_password, groups=[...new Set(catalog.map(p=>p.group))];
  return `<form id="account-editor" class="account-editor"><div class="panel-head"><div><span class="eyebrow">${user?'BESTEHENDES KONTO':'NEUER ZUGANG'}</span><h2>${user?esc(user.display_name||user.username):'Person hinzufügen'}</h2></div>${user&&m.can_create?'<button type="button" class="quiet" id="account-new">+ Neues Konto</button>':''}</div>
   <p>Jede Person erhält ein eigenes Passwort. Du siehst nur die Freigaben, die du selbst vergeben darfst.</p>
   <div class="inline-fields"><label>Anmeldename<input name="username" autocomplete="off" required minlength="3" maxlength="32" pattern="[a-z0-9][a-z0-9_.-]{2,31}" value="${esc(user?.username||'')}" ${user?'readonly':''} placeholder="z. B. mittelkap"><small>3–32 Kleinbuchstaben, Zahlen, Punkt, - oder _. Nach dem Anlegen unveränderbar.</small></label><label>Anzeigename<input name="display_name" maxlength="64" required value="${esc(user?.display_name||'')}" ${edit?'':'disabled'} placeholder="So soll die Person angezeigt werden"><small>${edit?'Wird in der Verwaltung angezeigt.':'Du darfst den Anzeigenamen dieses Kontos nicht ändern.'}</small></label></div>
   <label>${user?'Neues Passwort (nur zum Zurücksetzen)':'Erstes Passwort'}<input type="password" name="password" autocomplete="new-password" minlength="12" maxlength="256" ${user?'':'required'} ${password?'':'disabled'} placeholder="${user?'Leer lassen, um das Passwort zu behalten':'Mindestens 12 Zeichen'}"><small>${!password?'Dir wurde kein Recht zum Zurücksetzen fremder Passwörter gegeben.':user?'Ein neues Passwort beendet die bisherigen Sitzungen dieser Person.':'Übermittle dieses Passwort privat. Die Person kann es anschließend selbst ändern.'}</small></label>
   <label class="check"><input type="checkbox" name="enabled" ${user?.enabled!==false?'checked':''} ${m.can_disable?'':'disabled'}><span>Zugang ist freigeschaltet<small>${m.can_disable?'Gesperrte Konten können sich nicht anmelden.':'Sperren und Freischalten benötigt eine eigene Freigabe.'}</small></span></label>
   <div class="permission-heading"><h3>Freigegebene Funktionen</h3>${m.can_permissions?'<div class="button-row"><button type="button" class="quiet" data-permission-preset="read">Nur ansehen</button><button type="button" class="quiet" data-permission-preset="none">Alle abwählen</button></div>':''}</div>
   ${m.can_permissions?'':'<p class="small muted">Du darfst keine Rechte vergeben oder entziehen. Ein neu angelegtes Konto startet ohne Funktionsrechte; Basti kann sie ergänzen.</p>'}
   <div class="permissions-grid">${groups.map(group=>`<fieldset class="permission-group"><legend>${esc(group)}</legend>${catalog.filter(p=>p.group===group).map(p=>`<label class="permission-option"><input type="checkbox" name="permission" value="${esc(p.id)}" ${(user?.permissions||[]).includes(p.id)?'checked':''} ${m.can_permissions?'':'disabled'}><span><strong>${esc(p.label)}</strong><small>${esc(permissionHelp[p.id]||'Erlaubt die angegebene Funktion im Dashboard.')}</small></span></label>`).join('')}</fieldset>`).join('')}</div>
   <div class="help-box">${esc(m.rules)}</div>
   <div class="button-row"><button class="primary">${user?'Änderungen speichern':'Zugang anlegen'}</button><span class="small muted">Änderungen werden erst mit Speichern wirksam.</span></div></form>`;
 }
 window.renderAccessV3=async function renderAccessV3() {
  const generation=++accessRender;
  $('#content').innerHTML='<div id="accounts-root" class="panel"><h2>Zugänge werden geladen …</h2><p>Dein Konto und seine Berechtigungen werden geprüft.</p></div>';
  try {
   const auth=await api('/api/auth');
   if(generation!==accessRender||!$('#accounts-root'))return;
   const user=auth.user;
   if(!user)throw Error('Dein Benutzerkonto ist nicht verfügbar. Bitte erneut anmelden.');
   const prefs={identity_order:'name',theme:'retro',reduced_motion:false,...user.preferences};
   const canManage=user.is_owner||(user.permissions||[]).some(p=>p.startsWith('users.'));
   $('#content').innerHTML=`<div id="accounts-root"><section class="account-identity panel"><div class="account-monogram">${esc((user.display_name||user.username).slice(0,2).toUpperCase())}</div><div><span class="eyebrow">DEIN PERSÖNLICHER ZUGANG</span><h2>${esc(user.display_name||user.username)}</h2><p>@${esc(user.username)} · ${user.is_owner?'Oberster Verwalter':canManage?'Webverwalter':'Teamkonto'}<span class="badge">${user.is_owner?'♛ Vollzugriff':number(user.permissions?.length||0)+' freigegebene Rechte'}</span></p></div></section>
   <div class="grid-2"><section class="panel"><h2>So möchtest du arbeiten</h2><p>Diese Darstellung gehört zu deinem Konto. Die Bot-Einstellungen anderer Personen bleiben unverändert.</p><form id="account-preferences"><label>Namen und IDs anzeigen<select name="identity_order"><option value="name" ${prefs.identity_order==='name'?'selected':''}>Name zuerst · ID ergänzend</option><option value="id" ${prefs.identity_order==='id'?'selected':''}>ID zuerst · Name ergänzend</option></select><small>Gilt für Mitglieder, Kanäle und Rollen in der Verwaltung.</small></label><label>Design<select name="theme">${[['dark','Dunkel · ruhig & klar'],['midnight','Mitternacht · tiefes Blau'],['graphite','Graphit · neutral & konzentriert'],['retro','Retro · warm & kontrastreich'],['paper','Papier · hell & aufgeräumt']].map(([v,l])=>`<option value="${v}" ${prefs.theme===v?'selected':''}>${l}</option>`).join('')}</select></label><label class="check"><input type="checkbox" name="reduced_motion" ${prefs.reduced_motion?'checked':''}><span>Bewegungen reduzieren<small>Weniger Animationen und Übergänge im Dashboard.</small></span></label><button class="primary">Meine Darstellung speichern</button></form></section>
   <section class="panel"><h2>Dein Passwort ändern</h2><p>Du brauchst dafür dein aktuelles Passwort. Danach meldest du dich auf anderen Geräten erneut an.</p><form id="account-password"><label>Aktuelles Passwort<input type="password" name="current_password" autocomplete="current-password" required></label><label>Neues Passwort<input type="password" name="password" autocomplete="new-password" required minlength="12" maxlength="256"></label><label>Neues Passwort wiederholen<input type="password" name="repeat" autocomplete="new-password" required minlength="12" maxlength="256"></label><button class="primary">Passwort ändern</button></form></section></div>
   <p id="account-status" role="status" aria-live="polite" class="status-line"></p>
   ${canManage?'<div class="section-title"><div><span class="eyebrow">DEIN TEAM</span><h2>Zugänge & Berechtigungen</h2></div><span class="badge">Nach deiner Freigabe</span></div><div class="account-management"><section class="panel account-list"><h3>Alle Zugänge</h3><div id="account-list"></div></section><section class="panel" id="account-edit-panel"></section></div>':`<section class="panel"><h2>Deine freigegebenen Funktionen</h2><p>Fehlt dir eine Aufgabe, kann Basti deinen Zugang erweitern.</p><div class="permission-pills">${(auth.permission_catalog||[]).filter(p=>(user.permissions||[]).includes(p.id)).map(p=>`<span>${esc(p.label)}</span>`).join('')||'<span>Noch keine Funktionen freigegeben.</span>'}</div></section>`}
   <section class="help-box"><strong>Eigene Konten statt eines geteilten Passworts.</strong> Jeder Zugang hat eigene Rechte. Basti kann einzelne Verwaltungsaufgaben freigeben. Nur berechtigte Personen dürfen normale Zugänge sperren oder Passwörter zurücksetzen. Bot-Tokens sind in dieser Oberfläche nicht sichtbar.</section></div>`;
   bindForm('#account-preferences',async(f,b)=>{const preferences={identity_order:f.elements.identity_order.value,theme:f.elements.theme.value,reduced_motion:f.elements.reduced_motion.checked};buttonBusy(b,true);try{const result=await api('/api/preferences',{method:'PATCH',body:JSON.stringify(preferences)});document.documentElement.dataset.theme=preferences.theme;document.documentElement.dataset.reducedMotion=String(preferences.reduced_motion);changedUser(result.user||{...user,preferences});status('Deine Darstellung wurde gespeichert.');}finally{buttonBusy(b,false);}});
   bindForm('#account-password',async(f,b)=>{if(f.elements.password.value!==f.elements.repeat.value)throw Error('Die neuen Passwörter stimmen nicht überein.');buttonBusy(b,true);try{const result=await post('/api/password',{current_password:f.elements.current_password.value,password:f.elements.password.value});if(result.csrf)csrf=result.csrf;changedUser(result.user);f.reset();status('Passwort geändert. Deine anderen Sitzungen wurden beendet.');}finally{buttonBusy(b,false);}});
   if(!canManage)return;
   const list=await api('/api/users');
   if(generation!==accessRender||!$('#account-edit-panel'))return;
   const m=list.management||{can_create:false,can_edit:false,can_password:false,can_permissions:false,can_disable:false,grantable_permissions:[],rules:'Webverwaltung wird von Basti freigegeben.'};
   const catalog=(list.catalog||auth.permission_catalog||[]).filter(p=>(m.grantable_permissions||[]).includes(p.id));
   $('#account-list').innerHTML=(list.users||[]).map(account=>`<article class="account-entry ${account.enabled?'':'disabled'}"><div class="account-entry-head"><strong>${esc(account.display_name||account.username)}</strong><span class="badge ${account.enabled?'':'offline'}">${account.is_owner?'♛ Basti':(account.permissions||[]).some(p=>p.startsWith('users.'))?'Webverwalter':account.enabled?'Aktiv':'Gesperrt'}</span></div><small>@${esc(account.username)}</small><p>${account.is_owner?'Dauerhafter Vollzugriff.':number(account.permissions?.length||0)+' freigegebene Funktionen.'}</p>${!account.manageable?`<small>${esc(account.management_reason||'Dieses Konto ist geschützt.')}</small>`:`<div class="button-row">${m.can_edit||m.can_password||m.can_permissions?`<button type="button" class="quiet" data-edit-account="${esc(account.id)}">Bearbeiten</button>`:''}${m.can_disable?`<button type="button" class="quiet" data-toggle-account="${esc(account.id)}">${account.enabled?'Sperren':'Freischalten'}</button>`:''}</div>`}</article>`).join('');
   const openEditor=account=>{
    if(!account&&!m.can_create){$('#account-edit-panel').innerHTML=empty('Keine Kontoerstellung freigegeben.','Wähle links ein bearbeitbares Konto. Basti kann weitere Verwaltungsaufgaben freigeben.');return;}
    if(account&&!account.manageable){$('#account-edit-panel').innerHTML=empty('Dieses Konto ist geschützt.',account.management_reason);return;}
    $('#account-edit-panel').innerHTML=accountForm(account,catalog,m);
    $('#account-new')?.addEventListener('click',()=>openEditor(null));
    $$('[data-permission-preset]',$('#account-edit-panel')).forEach(b=>b.onclick=()=>{$$('input[name=permission]',$('#account-editor')).forEach(input=>{if(!input.disabled)input.checked=b.dataset.permissionPreset==='read'&&input.value.startsWith('view.');});});
    bindForm('#account-editor',async(f,b)=>{
     const payload={}, name=f.elements.display_name.value.trim(), password=f.elements.password.value;
     const permissions=$$('input[name=permission]:checked',f).map(el=>el.value).sort();
     if(!account){payload.username=f.elements.username.value.trim().toLowerCase();payload.display_name=name;payload.enabled=m.can_disable?f.elements.enabled.checked:true;payload.permissions=m.can_permissions?permissions:[];if(!password)throw Error('Bitte ein erstes Passwort festlegen.');payload.password=password;}
     else{if(m.can_edit&&name!==account.display_name)payload.display_name=name;if(m.can_password&&password)payload.password=password;if(m.can_disable&&f.elements.enabled.checked!==account.enabled)payload.enabled=f.elements.enabled.checked;if(m.can_permissions&&JSON.stringify(permissions)!==JSON.stringify([...(account.permissions||[])].sort()))payload.permissions=permissions;}
     if(!Object.keys(payload).length){status('Es gibt keine geänderten Einstellungen.');return;}
     buttonBusy(b,true);try{await api(account?'/api/users/'+encodeURIComponent(account.id):'/api/users',{method:account?'PATCH':'POST',body:JSON.stringify(payload)});f.elements.password.value='';toast(account?'Zugang gespeichert.':'Zugang angelegt. Übermittle das Passwort der Person privat.');await renderAccessV3();}finally{buttonBusy(b,false);}
    });
   };
   openEditor(m.can_create?null:(list.users||[]).find(account=>account.manageable)||null);
   $$('[data-edit-account]').forEach(b=>b.onclick=()=>{openEditor(list.users.find(u=>u.id===b.dataset.editAccount));$('#account-edit-panel').scrollIntoView({block:'nearest',behavior:prefs.reduced_motion?'auto':'smooth'});});
   $$('[data-toggle-account]').forEach(b=>b.onclick=async()=>{const account=list.users.find(u=>u.id===b.dataset.toggleAccount);try{if(account.enabled&&!await ask('Zugang sperren?',`${account.display_name||account.username} kann sich danach nicht mehr anmelden. Bestehende Sitzungen werden beendet. Du kannst den Zugang mit der passenden Freigabe wieder aktivieren.`,'Zugang sperren'))return;buttonBusy(b,true);await api('/api/users/'+encodeURIComponent(account.id),{method:'PATCH',body:JSON.stringify({enabled:!account.enabled})});toast(account.enabled?'Zugang gesperrt.':'Zugang freigeschaltet.');await renderAccessV3();}catch(error){status(error.message,true);}finally{buttonBusy(b,false);}});
  } catch(error){if($('#accounts-root'))$('#accounts-root').innerHTML=empty('Zugänge konnten nicht geladen werden.',error.message);toast(error.message,true);}
 };
})();
