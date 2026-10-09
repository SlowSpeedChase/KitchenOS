/* Calendar planning owns only preparation scheduling, never the legacy grid save. */
(() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const button = (text, action, cls) => { const n = el('button', text, cls); n.type = 'button'; n.addEventListener('click', action); return n; };
  const label = (text, input) => { const n = el('label', text); n.append(input); return n; };
  const input = (type, value, attrs = {}) => { const n = el('input'); n.type = type; n.value = value; Object.assign(n, attrs); return n; };
  const overlap = (a,b,c,d) => a < d && b > c;
  function zonedParts(value, zone) {
    return Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
  }
  function localStamp(value, zone) { const p = zonedParts(value, zone); return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`; }
  function offsetStamp(date, time, zone) {
    // Resolve civil time against the selected IANA zone, not the browser's zone.
    const desired = Date.parse(`${date}T${time}:00Z`); let instant = desired;
    for (let i=0; i<3; i++) { const represented = Date.parse(`${localStamp(instant,zone)}:00Z`); instant += desired-represented; }
    if (localStamp(instant,zone) !== `${date}T${time}`) throw new Error('That time does not exist in this timezone. Choose another time.');
    const offset = Math.round((desired-instant)/60000), sign = offset < 0 ? '-' : '+';
    return `${date}T${time}:00${sign}${String(Math.floor(Math.abs(offset)/60)).padStart(2,'0')}:${String(Math.abs(offset)%60).padStart(2,'0')}`;
  }
  async function json(url, options={}) {
    const response = await fetch(url,options); const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || 'Unable to load. Try refreshing.'); error.status=response.status; throw error; }
    return data;
  }
  function mount({root, week, onScheduled}) {
    let currentWeek=week, generation=0, controller, snapshot, cooks=[], selected=null, dayIndex=0, expanded=false, destroyed=false, submitting=false;
    root.classList.add('pc'); root.replaceChildren();
    const status=el('p','Loading calendar…','pc-status'); status.setAttribute('role','status');
    const heading=el('h2','Make room to cook');
    const intro=el('p','Choose a meal, then a cooking opening. Time Blocking stays flexible.','pc-intro');
    const refresh=button('Refresh calendar',()=>load());
    const timeline=el('section',null,'pc-calendar'); timeline.setAttribute('aria-label','Calendar and planned meals');
    const tray=el('section',null,'pc-tray');
    const editor=el('section',null,'pc-editor'); editor.hidden=true;
    const content=el('div',null,'pc-content'); const side=el('div',null,'pc-side'); side.append(tray,editor); content.append(timeline,side);
    root.append(heading,intro,status,refresh,content);
    let dateInput,timeInput,durationInput,zoneInput,mealInput,servingsInput,openings,warnings,estimate,submit;
    const zone=()=>snapshot?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
    const clock=value=>new Intl.DateTimeFormat(undefined,{timeZone:zone(),hour:'numeric',minute:'2-digit'}).format(new Date(value));
    const dates=()=>Object.keys(snapshot?.days || {}).sort();
    const dayTitle=d=>new Intl.DateTimeFormat(undefined,{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(`${d}T12:00Z`));
    function renderTray() {
      tray.replaceChildren(el('h3','Meals to plan'));
      const available=cooks.filter(c=>!c.date && !c.bundle_id && !c.cooked_at);
      if (!available.length) tray.append(el('p','No unscheduled meals this week. Add a recipe in Grid, or choose a planned meal below.'));
      for (const c of available) {
        const card=el('article',null,'pc-meal'); card.append(el('h4',c.recipe));
        if(c.notes)card.append(el('p',c.notes));
        card.append(button('Choose cooking time',()=>choose(c)));tray.append(card);
      }
    }
    function renderCalendar() {
      timeline.replaceChildren();
      const ds=dates(), nav=el('div',null,'pc-day-nav');
      const prev=button('Previous day',()=>{dayIndex=Math.max(0,dayIndex-1);renderCalendar();});prev.disabled=dayIndex===0;
      const next=button('Next day',()=>{dayIndex=Math.min(ds.length-1,dayIndex+1);renderCalendar();});next.disabled=dayIndex===ds.length-1;
      nav.append(prev,el('strong',ds[dayIndex]?dayTitle(ds[dayIndex]):''),next);timeline.append(nav);
      const expand=button(expanded?'Show until 10 pm':'Show until midnight',()=>{expanded=!expanded;renderCalendar();});expand.setAttribute('aria-pressed',String(expanded));timeline.append(expand);
      const lanes=el('div',null,'pc-lanes');
      ds.forEach((d,index)=>{
        const lane=el('section',null,`pc-day${index===dayIndex?' pc-selected-day':''}`);lane.append(el('h3',dayTitle(d)));
        const allDay=el('div',null,'pc-all-day');
        const dayStart=Date.parse(offsetStamp(d,'00:00',zone()));
        const nextDate=new Date(`${d}T12:00Z`);nextDate.setUTCDate(nextDate.getUTCDate()+1);
        const dayEnd=Date.parse(offsetStamp(nextDate.toISOString().slice(0,10),'00:00',zone()));
        const events=(snapshot.events||[]).filter(e=>overlap(dayStart,dayEnd,Date.parse(e.start),Date.parse(e.end)));
        events.filter(e=>e.all_day).forEach(e=>{
          const item=el('div',null,'pc-all-day-item');item.append(el('strong',e.title),el('small',snapshot.choices[e.id]?'All-day context':'Needs your choice'));
          [['blocking','Blocks cooking'],['background','Background information']].forEach(([choice,text])=>{
            const b=button(text,async()=>{
              b.disabled=true;
              try { await json(`/api/planning-calendar/occurrences/${e.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({choice,revision:snapshot.revision})});await load(); }
              catch(err){status.textContent=err.message;if(err.status===409)await load();}
              finally{b.disabled=false;}
            });b.setAttribute('aria-pressed',String(snapshot.choices[e.id]===choice));item.append(b);
          });allDay.append(item);
        });
        if(!events.some(e=>e.all_day))allDay.append(el('small',snapshot.days[d].covered?'No all-day events':'Calendar availability unknown'));
        lane.append(allDay);
        const track=el('div',null,'pc-track');const endHour=expanded?24:22;
        for(let hour=12;hour<endHour;hour++){const tick=el('div',hour===12?'12 pm':hour<24?`${hour%12 || 12}${hour<12?' am':' pm'}`:'midnight','pc-hour');tick.style.top=`${(hour-12)*64}px`;track.append(tick);}
        track.style.height=`${(endHour-12)*64}px`;
        const blocks=events.filter(e=>!e.all_day).map(e=>({...e,kind:e.role}));
        (snapshot.schedules||[]).filter(s=>s.date===d).forEach(s=>blocks.push({...s,id:`cook-${s.cook_id}`,title:s.recipe,end:new Date(Date.parse(s.start)+s.duration_minutes*60000).toISOString(),kind:'cook'}));
        const visible=blocks.map(e=>{const a=localStamp(Math.max(dayStart,Date.parse(e.start)),zone()).slice(11).split(':').map(Number);const b=Date.parse(e.end)>=dayEnd?[24,0]:localStamp(e.end,zone()).slice(11).split(':').map(Number);return {...e,a:Math.max(12,a[0]+a[1]/60),b:Math.min(endHour,b[0]+b[1]/60)};}).filter(e=>e.b>e.a).sort((a,b)=>a.a-b.a || a.b-b.b);
        // Assign overlap clusters independent columns, not overlays with hidden labels.
        let cluster=[],clusterEnd=0;
        function paint(){if(!cluster.length)return;const ends=[];cluster.forEach(e=>{let column=ends.findIndex(end=>end<=e.a);if(column<0)column=ends.length;ends[column]=e.b;e.column=column;});cluster.forEach(e=>{
          const block=button('',()=>{
            if(e.kind==='cook'){const c=cooks.find(c=>c.id===e.cook_id);if(c)choose(c);}
            else detail.textContent=`${e.title} · ${clock(e.start)}–${clock(e.end)} · ${e.role==='flexible'?'Flexible · Time Blocking':'Commitment'}`;
          },`pc-block pc-${e.kind}-block`);
          block.append(el('strong',e.title),el('small',`${clock(e.start)}–${clock(e.end)}`),el('small',e.kind==='flexible'?'Flexible':e.kind==='cook'?'Cooking':'Commitment'));
          block.style.top=`${(e.a-12)*64}px`;block.style.height=`${Math.max(44,(e.b-e.a)*64-4)}px`;block.style.left=`calc(34px + (100% - 36px) * ${e.column/ends.length})`;block.style.width=`calc((100% - 36px) / ${ends.length} - 3px)`;track.append(block);
        });cluster=[];}
        visible.forEach(e=>{if(e.a>=clusterEnd)paint();cluster.push(e);clusterEnd=Math.max(clusterEnd,e.b);});paint();lane.append(track);
        const mealList=el('div',null,'pc-day-meals');cooks.filter(c=>c.date===d).forEach(c=>{const title=`${c.recipe} · ${c.meal || 'Meal'}`;mealList.append(c.bundle_id||c.cooked_at?el('p',title):button(title,()=>choose(c)));});lane.append(mealList);lanes.append(lane);
      });
      timeline.append(lanes);const detail=el('p','Select an event for its full name and time.','pc-event-detail');detail.setAttribute('role','status');timeline.append(detail);
    }
    async function choose(cook) {
      selected=cook;editor.hidden=false;editor.replaceChildren();
      const selectionWeek=currentWeek; let durationEdited=false;
      const existing=(snapshot.schedules||[]).find(s=>s.cook_id===cook.id);
      const start=existing?localStamp(existing.start,existing.timezone):null;
      const form=el('form');form.append(el('h3',cook.recipe));
      estimate=el('p',existing?`${existing.duration_minutes} min · reserved cooking time`:'90 min · planning estimate');form.append(estimate);
      dateInput=input('date',start?.slice(0,10)||cook.date||dates()[dayIndex],{required:true,min:dates()[0],max:dates()[6]});
      timeInput=input('time',start?.slice(11)||'18:00',{required:true,step:'900'});
      durationInput=input('number',existing?.duration_minutes||90,{min:'15',max:'360',step:'15',required:true});
      zoneInput=input('text',existing?.timezone||zone(),{required:true});
      servingsInput=input('number','1',{min:'0.25',step:'0.25',required:true});
      mealInput=el('select');['breakfast','lunch','snack','dinner'].forEach(m=>{const o=el('option',m[0].toUpperCase()+m.slice(1));o.value=m;mealInput.append(o);});mealInput.value=cook.meal||'dinner';
      const fields=el('div',null,'pc-fields');fields.append(label('Cooking date',dateInput),label('Start time',timeInput),label('Duration (minutes)',durationInput),label('Meal',mealInput),label('Timezone',zoneInput));
      if(!cook.date)fields.append(label('Servings to eat',servingsInput));else form.append(el('p','Existing servings and leftovers will be kept.'));
      form.append(fields);warnings=el('p',null,'pc-warning');warnings.setAttribute('role','status');form.append(warnings);
      openings=el('div',null,'pc-openings');form.append(el('h4','Cooking openings'),openings);
      submit=el('button','Schedule meal','pc-submit');submit.type='submit';form.append(submit,button('Cancel',()=>{selected=null;editor.hidden=true;}));editor.append(form);
      const update=()=>{renderOpenings();warn();};dateInput.addEventListener('change',()=>{dayIndex=Math.max(0,dates().indexOf(dateInput.value));renderCalendar();update();});timeInput.addEventListener('input',warn);zoneInput.addEventListener('change',warn);
      durationInput.addEventListener('input',()=>{durationEdited=true;});
      durationInput.addEventListener('change',()=>{estimate.textContent=`${durationInput.value} min · your planning window`;load();warn();});
      form.addEventListener('submit',schedule);update();dateInput.focus();
      load();
      if(!existing){
        try {const recipe=await json(`/api/recipes/${encodeURIComponent(cook.recipe)}`);if(selected!==cook||currentWeek!==selectionWeek||!editor.contains(form))return;
          const timing=recipe.cooking_duration;
          const minutes=timing?.minutes;
          if(minutes && !durationEdited){durationInput.value=Math.max(15,Math.min(360,Math.ceil(minutes/15)*15));estimate.textContent=`${durationInput.value} min · ${timing.source==='recipe'?'recipe timing':'planning estimate'}`;await load();}
          // Timing updates must not overwrite a duration the user has edited.
        } catch (_) { /* Honest 90-minute fallback remains visible. */ }
      }
    }
    function renderOpenings(){
      if(!selected||!openings)return;openings.replaceChildren();const day=snapshot?.days[dateInput.value];
      if(snapshot?.duration_minutes!==Number(durationInput.value)){openings.append(el('p','Updating cooking openings…'));return;}
      if(!day?.covered){openings.append(el('p','Availability unknown. You can still set a time manually.'));return;}
      const candidates=(day.windows||[]).filter(w=>!(snapshot.schedules||[]).some(s=>s.cook_id===selected.id&&s.start===w.start));
      if(!candidates.length){openings.append(el('p','No opening fits this duration. Try a shorter window or another day.'));return;}
      const picker=el('select');picker.setAttribute('aria-label','Available cooking openings');
      candidates.forEach((w,i)=>{const o=el('option',`${clock(w.start)}–${clock(w.end)}${w.overlaps_flexible?' · overlaps Time Blocking':''}${w.unresolved_all_day_ids.length?' · conditional':''}`);o.value=i;picker.append(o);});
      const use=()=>{const w=candidates[Number(picker.value)];timeInput.value=localStamp(w.start,zone()).slice(11);zoneInput.value=zone();warn();};
      openings.append(picker,button('Use this opening',use,'pc-opening'));
      picker.addEventListener('change',()=>{const w=candidates[Number(picker.value)];const context=w.adjacent_event_ids.map(id=>snapshot.events.find(e=>e.id===id)).filter(Boolean);near.textContent=context.map(e=>`${e.title} · ${clock(e.start)}–${clock(e.end)}`).join(' / ');});const near=el('small');openings.append(near);picker.dispatchEvent(new Event('change'));
    }
    function warn(){
      if(!selected)return;try{
        const start=Date.parse(offsetStamp(dateInput.value,timeInput.value,zoneInput.value)),end=start+Number(durationInput.value)*60000;
        const messages=[];
        if(!snapshot?.days[dateInput.value]?.covered)messages.push('Calendar availability is unknown.');
        for(const e of snapshot?.events||[]){if(!overlap(start,end,Date.parse(e.start),Date.parse(e.end)))continue;
          if(e.all_day){if(snapshot.choices[e.id]==='blocking')messages.push(`Blocks cooking: ${e.title}.`);else if(!snapshot.choices[e.id])messages.push(`Needs your choice: ${e.title}.`);}
          else messages.push(`${e.role==='flexible'?'Overlaps Time Blocking':'Conflicts with commitment'}: ${e.title} (${clock(e.start)}–${clock(e.end)}).`);
        }
        for(const s of snapshot?.schedules||[]){if(s.cook_id!==selected.id&&overlap(start,end,Date.parse(s.start),Date.parse(s.start)+s.duration_minutes*60000))messages.push(`Overlaps cooking: ${s.recipe}.`);}
        warnings.textContent=messages.join(' ') || 'No calendar conflict in this window.';
      }catch(err){warnings.textContent=err.message;}
    }
    async function schedule(event){
      event.preventDefault();if(submitting||!selected)return;
      const target=selected,weekAtStart=currentWeek;submitting=true;submit.disabled=true;
      try{
        const start=offsetStamp(dateInput.value,timeInput.value,zoneInput.value);
        await json(`/api/cooks/${target.id}/schedule`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:dateInput.value,meal:mealInput.value,start,timezone:zoneInput.value,duration_minutes:Number(durationInput.value),servings_to_eat:Number(servingsInput.value)})});
        if(currentWeek===weekAtStart){selected=null;editor.hidden=true;await load();status.textContent='Meal scheduled.';await onScheduled?.();}
      }catch(err){status.textContent=err.message;warnings.textContent=err.message;}
      finally{submitting=false;if(submit)submit.disabled=false;}
    }
    async function load(){
      const gen=++generation;controller?.abort();controller=new AbortController();
      const duration=selected?Number(durationInput.value):90;
      try{
        const [data,board]=await Promise.all([json(`/api/planning-calendar/${currentWeek}?duration_minutes=${duration}${selected?'&exclude_cook_id='+selected.id:''}`,{signal:controller.signal}),json(`/api/week-board/${currentWeek}`,{signal:controller.signal})]);
        if(destroyed||gen!==generation)return;snapshot=data;cooks=board.cooks;
        status.textContent=data.fresh?`Calendar updated · ${new Date(data.synced_at).toLocaleString()} · ${zone()}`:'Calendar needs refresh';
        renderTray();renderCalendar();if(selected){renderOpenings();warn();}
      }catch(err){if(err.name!=='AbortError'&&gen===generation){
          status.textContent='Couldn’t refresh calendar. Check your connection and try again.';
          if(snapshot){snapshot={...snapshot,fresh:false,events:[],choices:{},days:Object.fromEntries(Object.keys(snapshot.days).map(d=>[d,{covered:false,windows:[]}]))};renderCalendar();if(selected){renderOpenings();warn();}}
        }}
    }
    const timer=setInterval(()=>{if(!document.hidden&&!submitting)load();},60000);load();
    return {setWeek(value){if(value===currentWeek)return;currentWeek=value;selected=null;dayIndex=0;editor.hidden=true;snapshot=null;timeline.replaceChildren();tray.replaceChildren();load();},destroy(){destroyed=true;generation++;controller?.abort();clearInterval(timer);root.replaceChildren();}};
  }
  window.KitchenPlanningCalendar={mount};
})();
