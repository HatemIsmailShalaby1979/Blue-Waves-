"""Comprehensive single-page Cockpit UI (HTML/JS/CSS).

Kept as a separate module so the handler file stays readable and the large
inline UI can be edited independently.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blue Waves Cockpit — Full Board Control</title>
<style>
  :root {
    --bg:#0a0e14; --panel:#141a22; --panel2:#1b232e; --border:#26303d;
    --text:#e6edf3; --muted:#8b98a5; --accent:#38bdf8; --green:#34d399;
    --amber:#fbbf24; --red:#f87171; --purple:#a78bfa;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--text); font-size:14px; }
  header { display:flex; align-items:center; gap:16px; padding:14px 24px;
           background:var(--panel); border-bottom:1px solid var(--border);
           position:sticky; top:0; z-index:50; }
  header h1 { font-size:18px; color:var(--accent); }
  header .tag { color:var(--muted); font-size:12px; }
  header .spacer { flex:1; }
  .nav { display:flex; gap:6px; flex-wrap:wrap; }
  .nav button { background:var(--panel2); color:var(--text); border:1px solid var(--border);
                padding:6px 12px; border-radius:6px; cursor:pointer; font-size:12px; }
  .nav button.active { background:var(--accent); color:#000; border-color:var(--accent); }
  main { padding:20px 24px; max-width:1500px; margin:0 auto; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
  .grid.wide { grid-template-columns:1fr; }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:16px; }
  .card h2 { color:var(--accent); font-size:14px; margin-bottom:12px; letter-spacing:.3px;
             display:flex; align-items:center; gap:8px; }
  .card h2 .count { margin-left:auto; background:var(--accent); color:#000; border-radius:10px;
                    padding:1px 8px; font-size:11px; }
  .stat { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px dashed var(--border); }
  .stat:last-child { border-bottom:none; }
  .stat .k { color:var(--muted); }
  .stat .v { color:var(--text); font-weight:600; }
  .ok { color:var(--green); } .warn { color:var(--amber); } .bad { color:var(--red); }
  .btn { background:var(--accent); color:#000; border:none; padding:7px 14px; border-radius:6px;
         cursor:pointer; font-size:12px; font-weight:600; margin:3px; }
  .btn:hover { filter:brightness(1.1); }
  .btn.green { background:var(--green); } .btn.amber { background:var(--amber); }
  .btn.red { background:var(--red); } .btn.gray { background:var(--panel2); color:var(--text);
             border:1px solid var(--border); }
  .btn.sm { padding:4px 9px; font-size:11px; margin:1px; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  input, select, textarea { background:var(--panel2); color:var(--text); border:1px solid var(--border);
          border-radius:6px; padding:8px 10px; margin:4px 0; width:100%; font-size:13px; }
  textarea { resize:vertical; font-family:inherit; }
  label { display:block; color:var(--muted); font-size:11px; margin:8px 0 2px; }
  .row { display:flex; gap:10px; }
  .library-item { border:1px solid var(--border); border-radius:10px; overflow:hidden; margin-bottom:16px;
                  background:var(--panel2); }
  .library-item .head { display:flex; align-items:center; gap:10px; padding:10px 14px;
                        border-bottom:1px solid var(--border); flex-wrap:wrap; }
  .library-item .head .title { font-weight:600; }
  .badge { font-size:10px; padding:2px 8px; border-radius:10px; font-weight:600;
           border:1px solid var(--border); }
  .badge.awaiting_owner,.badge.ready_to_publish { background:var(--amber); color:#000; }
  .badge.approved { background:var(--green); color:#000; }
  .badge.uploaded_unlisted { background:var(--purple); color:#000; }
  .badge.published { background:var(--accent); color:#000; }
  .badge.rejected { background:var(--red); color:#000; }
  .badge.composing,.badge.mixing,.badge.queued,.badge.scripted { background:var(--purple); color:#000; }
  .badge.produced,.badge.fact_checked { background:#e0e0e0; color:#000; }
  .player-wrap { padding:10px 14px; background:#000; }
  video,audio { width:100%; max-height:320px; border-radius:6px; }
  .meta { padding:10px 14px; color:var(--muted); font-size:12px; }
  .actions { padding:10px 14px; border-top:1px solid var(--border); display:flex; gap:4px; flex-wrap:wrap; align-items:center; }
  #status { position:fixed; bottom:16px; right:16px; max-width:480px; background:#000d;
            border:1px solid var(--border); border-radius:8px; padding:12px 16px; font-size:12px;
            z-index:100; display:none; white-space:pre-wrap; max-height:260px; overflow:auto; }
  .muted { color:var(--muted); } .small { font-size:11px; }
  .agent { border:1px solid var(--border); border-radius:8px; padding:12px; background:var(--panel2); }
  .agent .name { font-weight:700; color:var(--accent); }
  .agent .role { color:var(--muted); font-size:12px; }
  .agent .tier { display:inline-block; font-size:10px; background:var(--panel);
                 border:1px solid var(--border); padding:1px 7px; border-radius:8px; margin-top:4px; }
  .agent .can { margin-top:6px; font-size:11px; color:var(--green); }
  .agent .cannot { font-size:11px; color:var(--red); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; }
  .tabs { display:flex; gap:4px; margin-bottom:12px; flex-wrap:wrap; }
  .tab { background:var(--panel2); color:var(--muted); border:1px solid var(--border); padding:6px 12px;
         border-radius:6px; cursor:pointer; font-size:12px; }
  .tab.active { background:var(--accent); color:#000; }
  .secret-field { -webkit-text-security:disc; }
  .hidden-panel { display:none; }
  .pill { display:inline-block; padding:2px 9px; border-radius:10px; font-size:11px;
          background:var(--panel2); border:1px solid var(--border); margin:2px; }
  .prog { height:8px; background:var(--panel2); border-radius:6px; overflow:hidden; margin-top:6px; }
  .prog > .fill { height:100%; background:var(--accent); }
</style>
</head>
<body>
<header>
  <h1>Blue Waves Cockpit</h1>
  <span class="tag" id="version-tag">v0.3.0</span>
  <span class="spacer"></span>
  <nav class="nav" id="nav"></nav>
</header>
<main>
  <div id="sections"></div>
</main>
<div id="status" onclick="this.style.display='none'"></div>

<script>
let SECRETS_SAVED = false;

// ---------- helpers ----------
async function api(path, opts={}) {
  const r = await fetch(path, opts);
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch(e) { data = text; }
  if (!r.ok && data && data.error) throw new Error(data.error);
  if (!r.ok) throw new Error('HTTP '+r.status);
  return data;
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function money(cents){ return '$' + (Number(cents||0)/100).toFixed(2); }
function toast(msg){ const el=document.getElementById('status'); el.style.display='block';
  el.textContent = typeof msg==='string' ? msg : JSON.stringify(msg,null,2); setTimeout(()=>el.style.display='none', 8000); }
function badgeClass(s){ return esc(s || ''); }

const NAV = [
  ['overview','Overview'], ['library','Media Library'], ['approvals','Approvals'],
  ['publish','YouTube Publish'],
  ['crew','Crew & Tasks'], ['generate','Generate'], ['finance','Finance Plan'],
  ['shepo','SHEPO Finance'], ['meta','Metacognition'], ['providers','Providers & Keys'], ['scheduler','Scheduler'],
  ['monetization','Monetization']
];

function renderNav(){
  document.getElementById('nav').innerHTML = NAV.map(([id,label])=>
    `<button data-id="${id}" onclick="showSection('${id}')">${label}</button>`).join('');
}
function showSection(id, push=true){
  document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active', b.dataset.id===id));
  window._cur = id;
  if (push) history.replaceState(null,'','#'+id);
  document.getElementById('sections').innerHTML = '<div class="card"><p class="muted">Loading '+id+'…</p></div>';
  LOADERS[id]();
}
async function ensureLoaded(){}

const LOADERS = {};

// ---------- Overview ----------
LOADERS.overview = async function(){
  const [health, queue, fin, prov, crew, sched] = await Promise.all([
    api('/api/health'), api('/api/dashboard'), api('/api/finance/plan'),
    api('/api/providers'), api('/api/crew'), api('/api/scheduler')
  ]);
  document.getElementById('version-tag').textContent = 'v'+(health.version||'0.3.0');
  let provHtml = Object.entries(prov.approvals||{}).map(([n,a])=>`
    <div class="stat"><span class="k">${esc(n)}</span>
      <span class="v ${a.approved?'ok':'warn'}">${a.approved?'Approved':'Needs approval'}</span></div>`).join('');
  document.getElementById('sections').innerHTML = `
    <div class="grid wide">
      <div class="card">
        <h2>System Health</h2>
        <div class="grid">
          <div class="card">
            <div class="stat"><span class="k">Service</span><span class="v">${esc(health.service)}</span></div>
            <div class="stat"><span class="k">Version</span><span class="v">${esc(health.version)}</span></div>
            <div class="stat"><span class="k">Tenant</span><span class="v">${esc(health.tenant_id)}</span></div>
            <div class="stat"><span class="k">Ledger</span><span class="v ${health.ledger_intact?'ok':'bad'}">${health.ledger_intact?'Intact':'Broken'}</span></div>
            <div class="stat"><span class="k">Cloud Budget</span><span class="v">${money(health.cloud_budget_cents)}</span></div>
            <div class="stat"><span class="k">Queue</span><span class="v">${health.queue_size}</span></div>
            <div class="stat"><span class="k">Music</span><span class="v">${health.music_assets}</span></div>
            <div class="stat"><span class="k">Podcasts</span><span class="v">${health.podcast_assets}</span></div>
          </div>
          <div class="card">
            <h2>Queue Status</h2>
            <div class="stat"><span class="k">Total</span><span class="v">${queue.total}</span></div>
            <div class="stat"><span class="k">Pending</span><span class="v">${queue.pending}</span></div>
            <div class="stat"><span class="k">Ready</span><span class="v">${queue.ready_to_publish}</span></div>
            <div class="stat"><span class="k">Published</span><span class="v">${queue.published}</span></div>
            <div class="stat"><span class="k">Rejected</span><span class="v">${queue.rejected}</span></div>
          </div>
          <div class="card">
            <h2>Provider Approvals</h2>${provHtml||'<p class="muted">None</p>'}
          </div>
        </div>
        <div class="grid" style="margin-top:4px">
          <div class="card">
            <h2>Finance Plan</h2>
            <div class="stat"><span class="k">Spent</span><span class="v">${money(fin.plan.spent_cents)}</span></div>
            <div class="stat"><span class="k">Budget</span><span class="v">${money(fin.plan.budget_monthly_cents)}</span></div>
            <div class="stat"><span class="k">Remaining</span><span class="v">${money(fin.plan.remaining_cents)}</span></div>
            <div class="stat"><span class="k">Utilization</span><span class="v">${fin.plan.utilization_pct}%</span></div>
            <div class="prog"><div class="fill" style="width:${Math.min(100,fin.plan.utilization_pct)}%"></div></div>
            <div class="small muted">${esc(fin.plan.goal)}</div>
          </div>
          <div class="card">
            <h2>Scheduler</h2>
            <div class="stat"><span class="k">Total jobs</span><span class="v">${sched.total_jobs||0}</span></div>
            <div class="stat"><span class="k">Pending</span><span class="v">${sched.pending||0}</span></div>
            <div class="stat"><span class="k">Completed</span><span class="v">${sched.completed||0}</span></div>
            <div class="stat"><span class="k">Weekly published</span><span class="v">${sched.weekly_published||0}/${sched.weekly_limit||0}</span></div>
          </div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <h2>Crew (${crew.agents.length})</h2>
      <div class="grid">
        ${crew.agents.map(a=>`
          <div class="agent">
            <div class="name">${esc(a.name)}</div>
            <div class="role">${esc(a.role)}</div>
            <span class="tier">${esc(a.tier)}</span>
            <div class="can">Can: ${esc((a.can||[]).join(', '))}</div>
            <div class="cannot">Cannot: ${esc((a.cannot||[]).join(', '))}</div>
          </div>`).join('')}
      </div>
    </div>`;
};

// ---------- Media Library ----------
function playerHTML(item){
  const src = item.media_url && item.media_exists ? item.media_url : '';
  const body = item.content_type==='video'
    ? `<video controls preload="metadata" src="${src}"></video>`
    : `<audio controls preload="metadata" src="${src}"></audio>`;
  if (!src) return '<p class="muted small">No playable media file (missing or empty)</p>';
  return body;
}
LOADERS.library = async function(){
  const data = await api('/api/library');
  const items = data.items||[];
  const filter = '<p class="muted">Total: '+items.length+'</p>';
  document.getElementById('sections').innerHTML = `
    <div class="card wide-card">
      <h2>Media Library <span class="count">${items.length}</span></h2>
      <p class="muted small">Review each generated piece. Approve to unlock publishing, or reject to let the relevant crew member regenerate with your feedback.</p>
      ${items.map(item=>`
        <div class="library-item" data-id="${esc(item.asset_id)}">
          <div class="head">
            <span class="badge">${esc(item.content_type)}</span>
            <span class="title">${esc(item.title||item.topic||item.asset_id)}</span>
            <span class="badge ${badgeClass(item.status)}">${esc(item.status)}</span>
            <span class="pill">attempt ${item.attempt||1}</span>
            ${(item.provider||item.tts_provider)?`<span class="pill" title="generating provider">via ${esc(item.provider||item.tts_provider)}</span>`:''}
            ${(item.metadata&&item.metadata.provider_attempts)?`<span class="pill small" title="${esc(item.metadata.provider_attempts.join(' → '))}">chain: ${esc(item.metadata.provider_attempts.join('→'))}</span>`:''}
            ${item.quality_score!=null?`<span class="pill">quality ${item.quality_score}</span>`:''}
            ${item.quality_issues&&item.quality_issues.length?`<span class="pill bad">${esc(item.quality_issues.join('; '))}</span>`:''}
            <div style="margin-left:auto" class="small muted">${esc(item.created_by||'-')} · ${esc(item.created_at||'')}</div>
          </div>
          <div class="player-wrap">${playerHTML(item)}</div>
          <div class="actions" data-type="${esc(item.content_type)}" data-id="${esc(item.asset_id)}" data-status="${esc(item.status)}">
            <button class="btn green sm act-approve">Approve</button>
            <button class="btn red sm act-reject">Reject</button>
            <button class="btn amber sm act-retry" data-prompt="${esc(item.title||item.topic||'')}">Retry w/ feedback</button>
            <button class="btn blue sm act-publish">Publish</button>
            <input class="feedback" placeholder="${item.status==='rejected'?'Feedback for regeneration (optional)':''}" ${item.status!=='rejected'?'disabled':'style=display:none'}>
          </div>
        </div>`).join('')}
    </div>`;
  document.querySelectorAll('.act-approve').forEach(b=>b.onclick=()=>doApprove(b.closest('.actions')));
  document.querySelectorAll('.act-reject').forEach(b=>b.onclick=()=>doReject(b.closest('.actions')));
  document.querySelectorAll('.act-retry').forEach(b=>b.onclick=()=>doRetry(b.closest('.actions'), b));
  document.querySelectorAll('.act-publish').forEach(b=>b.onclick=()=>doPublish(b.closest('.actions')));
};
async function action(type,id,path,payload){
  try{ const r = await api('/api/'+path+'/'+type+'/'+id, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload||{})}); toast(r); } catch(e){ toast('Error: '+e.message); }
  if (window._cur === 'publish') { LOADERS.publish(); return; }
  LOADERS.library(); LOADERS.approvals();
}
async function doApprove(a){ await action(a.dataset.type,a.dataset.id,'approve',{}); }
async function doReject(a){ await action(a.dataset.type,a.dataset.id,'reject',{reason:prompt('Reason for rejection?','Was not satisfactory')}); }
async function doRetry(a,btn){
  const cur = a.querySelector('.feedback');
  const enhancement = cur && cur.value ? cur.value : (btn.dataset.prompt||'');
  const fb = prompt('Enhancement for regeneration', cur&&cur.value?cur.value:'Improve quality and clarity.');
  if(fb===null) return;
  await action(a.dataset.type,a.dataset.id,'retry',{enhancement:fb, quality:'high'});
}
async function doPublish(a){ await action(a.dataset.type,a.dataset.id,'publish',{channel:'youtube'}); }

// ---------- Approvals ----------
LOADERS.approvals = async function(){
  const data = await api('/api/library');
  const items = (data.items||[]).filter(i=>i.status==='awaiting_owner');
  document.getElementById('sections').innerHTML = `
    <div class="card wide-card">
      <h2>Pending Approval <span class="count">${items.length}</span></h2>
      <p class="muted small">Listen / watch below, then approve or reject. Rejected items move to &quot;Retry&quot; so the crew can regenerate with your feedback.</p>
      ${items.length===0?'<p class="ok">No items awaiting your review.</p>' : items.map(item=>`
        <div class="library-item">
          <div class="head">
            <span class="badge">${esc(item.content_type)}</span>
            <span class="title">${esc(item.title||item.topic||item.asset_id)}</span>
            <div style="margin-left:auto" class="small muted">${esc(item.created_by||'-')}</div>
          </div>
          <div class="player-wrap">${playerHTML(item)}</div>
          <div class="actions" data-type="${esc(item.content_type)}" data-id="${esc(item.asset_id)}">
            <button class="btn green sm act-approve">Approve</button>
            <button class="btn red sm act-reject">Reject</button>
          </div>
        </div>`).join('')}
    </div>`;
  document.querySelectorAll('.act-approve').forEach(b=>b.onclick=()=>doApprove(b.closest('.actions')));
  document.querySelectorAll('.act-reject').forEach(b=>b.onclick=()=>doReject(b.closest('.actions')));
};

// ---------- Crew & Tasks ----------
LOADERS.crew = async function(){
  const crew = await api('/api/crew');
  const tasks = (crew.tasks||[]).slice().reverse();
  const byAgent = {};
  crew.agents.forEach(a=> byAgent[a.id] = tasks.filter(t=> t.agent_id===a.id.toUpperCase() || (a.name && t.agent_id===a.name.toUpperCase())));
  document.getElementById('sections').innerHTML = `
    <div class="card wide-card">
      <h2>Crew Members</h2>
      <div class="grid">
        ${crew.agents.map(a=>`
          <div class="agent">
            <div class="name">${esc(a.name)}</div>
            <div class="role">${esc(a.role)}</div>
            <span class="tier">${esc(a.tier)}</span>
            <div class="can">Can: ${esc((a.can||[]).join(', '))}</div>
            <div class="cannot">Cannot: ${esc((a.cannot||[]).join(', '))}</div>
          </div>`).join('')}
      </div>
      <h2 style="margin-top:20px">Task Board</h2>
      <table>
        <tr><th>Crew</th><th>Task / Topic</th><th>Type</th><th>Status</th><th>Action</th></tr>
        ${tasks.map(t=>`
          <tr>
            <td>${esc(t.agent_id||'')}</td>
            <td>${esc(t.name)}</td>
            <td>${esc(t.content_type||'')}</td>
            <td>${esc(t.status||'')}</td>
            <td>
              ${t.content_type&&t.asset_id?`
                <button class="btn sm gray" onclick="showSection('library')">Open</button>`:''}
              ${t.status==='rejected'&&t.content_type&&t.asset_id?`
                <button class="btn sm amber" onclick="showSection('library')">Retry</button>`:''}
            </td>
          </tr>`).join('')}
      </table>
    </div>`;
};

// ---------- Generate ----------
LOADERS.generate = async function(){
  let langOpts = '<option value="en">English</option>';
  try{
    const lr = await api('/api/languages');
    const list = (lr && lr.languages) || [];
    if(list.length){
      langOpts = list.map(function(l){
        return '<option value="'+esc(l.code)+'"'+(l.code==='en'?' selected':'')+'>'+esc(l.label)+'</option>';
      }).join('');
    }
  }catch(e){ /* fall back to English only */ }
  document.getElementById('sections').innerHTML = `
    <div class="grid">
      <div class="card"><h2>Generate Music</h2>
        <label>Topic</label><input id="g-m-topic" placeholder="e.g. Lo-fi study beats">
        <label>Genre</label><input id="g-m-genre" value="cinematic">
        <label>Mood</label><input id="g-m-mood" value="inspirational">
        <label>Duration (s)</label><input id="g-m-dur" value="180">
        <label>Quality</label><select id="g-m-q"><option>free</option><option>standard</option><option selected>high</option></select>
        <button class="btn" onclick="genMusic()">Generate Music</button>
      </div>
      <div class="card"><h2>Upload Music (MP3/WAV)</h2>
        <p class="muted small">Bring your own track — Suno web export or free-library music (YT Audio Library, Pixabay). Validated, mastered to −14 LUFS, queued for review like generated tracks.</p>
        <label>Audio file</label><input id="u-m-file" type="file" accept=".mp3,.wav,.m4a,.ogg,.flac,audio/*">
        <label>Title</label><input id="u-m-title" placeholder="e.g. Ocean Waves at Dawn">
        <div class="row">
          <div style="flex:1"><label>Genre</label><input id="u-m-genre" value="cinematic"></div>
          <div style="flex:1"><label>Mood</label><input id="u-m-mood" value="inspirational"></div>
        </div>
        <label>Source</label><select id="u-m-source"><option value="suno_web">Suno web export</option><option value="youtube_audio_library">YouTube Audio Library</option><option value="pixabay">Pixabay Music</option><option value="other_free">Other free-licensed</option></select>
        <label>License note</label><input id="u-m-license" placeholder="e.g. YT Audio Library, cleared for monetization">
        <label>Lyrics (optional)</label><textarea id="u-m-lyrics" rows="2"></textarea>
        <button class="btn" onclick="uploadMusic()">Upload & Queue for Review</button>
        <div id="u-m-status" class="small muted" style="margin-top:8px"></div>
      </div>
      <div class="card"><h2>Ingest External Video</h2>
        <p class="muted small">Bring in a video produced elsewhere. It is hashed, copied into the app's own storage, probe-checked and queued for your review — the same owner gate as generated work. Upload to YouTube unlisted, review the real embed, then publish.</p>
        <label>File path on this machine</label><input id="i-v-path" placeholder="E:\\path\\to\\video.mp4">
        <label>Topic</label><input id="i-v-topic" placeholder="e.g. Helix Codex framework explainer">
        <label>Title (optional — overrides the SEO draft)</label><input id="i-v-title" placeholder="e.g. Helix Codex in 6 minutes">
        <div class="row">
          <div style="flex:1"><label>Pillar</label><select id="i-v-pillar"><option>education</option><option selected>tech</option><option>science</option><option>business</option></select></div>
          <div style="flex:1"><label>Language</label><select id="i-v-lang"><option value="en" selected>English</option><option value="ar">Arabic</option></select></div>
        </div>
        <label>Source</label><select id="i-v-source"><option value="external_file">External file</option><option value="owner_produced">Owner produced</option><option value="client_supplied">Client supplied</option></select>
        <p class="muted small">Accepts mp4, mov, webm, mkv up to 2 GB. The original is never modified.</p>
        <button class="btn" onclick="ingestVideo()">Ingest &amp; Queue for Review</button>
        <div id="i-v-status" class="small muted" style="margin-top:8px"></div>
      </div>
      <div class="card"><h2>Generate Podcast</h2>
        <label>Topic</label><input id="g-p-topic" placeholder="e.g. The science of sleep">
        <label>Language</label><select id="g-p-lang" onchange="loadVoices()">${langOpts}</select>
        <div class="row">
          <div style="flex:1"><label>Host name</label><input id="g-p-hname" value="Alex"></div>
          <div style="flex:1"><label>Guest name</label><input id="g-p-gname" value="Sarah"></div>
        </div>
        <label>Host voice</label><select id="g-p-hvoice"></select>
        <label>Guest voice</label><select id="g-p-gvoice"></select>
        <label>Script (optional)</label><textarea id="g-p-script" rows="3" placeholder="Leave blank to auto-build a two-host dialogue about the topic"></textarea>
        <label>Duration (s)</label><input id="g-p-dur" value="600">
        <label>Quality</label><select id="g-p-q"><option>free</option><option>standard</option><option selected>high</option></select>
        <p class="muted small">Two named voices in the chosen language, written to fill the full duration. Speaker labels are never spoken aloud.</p>
        <button class="btn" onclick="genPodcast()">Generate Podcast</button>
      </div>
      <div class="card"><h2>Generate Video</h2>
        <label>Topic</label><input id="g-v-topic" placeholder="e.g. How batteries work">
        <label>Scene description</label><textarea id="g-v-prompt" rows="2" placeholder="Describe what should be shown"></textarea>
        <label>Duration (s, max 600)</label><input id="g-v-dur" value="20" onchange="refreshQuote()">
        <label>Quality</label><select id="g-v-q" onchange="refreshQuote()"><option>free</option><option>standard</option><option selected>high</option></select>
        <label>Scene provider (60s+ jobs)</label><select id="g-v-prov" onchange="refreshQuote()"><option value="">Auto (best available)</option><option value="stock">Stock footage ($0 B-roll)</option><option value="kling">Kling cloud (metered)</option><option value="seedance">Seedance cloud (metered)</option></select>
        <p class="muted small">Narration is always English. High quality renders 1080p. 60s+ runs as a background job (multi-scene + chapters) with live progress below.</p>
        <p class="muted small" id="g-v-quote"></p>
        <button class="btn" onclick="genVideo()">Generate Video</button>
        <div id="g-v-job" style="margin-top:10px"></div>
      </div>
      <div class="card"><h2>Background Video Jobs</h2>
        <div id="g-jobs"><p class="muted small">No jobs yet.</p></div>
        <button class="btn gray" onclick="refreshJobs()">Refresh jobs</button>
      </div>
      <div class="card"><h2>Add to Queue</h2>
        <label>Content Type</label><select id="g-c-type"><option>video</option><option>music</option><option>podcast</option></select>
        <label>Topic</label><input id="g-c-topic" placeholder="Queue topic">
        <label>Priority</label><select id="g-c-pri"><option>normal</option><option selected>high</option><option>low</option></select>
        <label>Quality</label><select id="g-c-q"><option>free</option><option>standard</option><option selected>high</option></select>
        <button class="btn" onclick="genQueue()">Add Request</button>
      </div>
    </div>`;
  loadVoices(); refreshJobs(); refreshQuote();
};
async function genMusic(){ const b={topic:val('g-m-topic'),genre:val('g-m-genre'),mood:val('g-m-mood'),duration_seconds:+val('g-m-dur')||180,quality:sel('g-m-q')}; try{await api('/api/generate/music',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}); toast('Music generated'); showSection('library');}catch(e){toast('Error: '+e.message);} }
async function loadVoices(){
  const lang = sel('g-p-lang')||'en';
  try {
    const d = await api('/api/voices?language='+encodeURIComponent(lang));
    const opts = (d.voices||[]).map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');
    const hv = document.getElementById('g-p-hvoice'), gv = document.getElementById('g-p-gvoice');
    if (hv) hv.innerHTML = opts;
    if (gv && hv) { gv.innerHTML = opts; if (hv.options.length>1) gv.selectedIndex = 1; }
  } catch(e){ /* keep previous options */ }
}
async function genPodcast(){ const b={topic:val('g-p-topic'),language:sel('g-p-lang')||'en',script:val('g-p-script'),duration_seconds:+val('g-p-dur')||600,quality:sel('g-p-q'),host_name:val('g-p-hname')||'Host',guest_name:val('g-p-gname')||'Guest',host_voice:sel('g-p-hvoice')||'',guest_voice:sel('g-p-gvoice')||''}; try{await api('/api/generate/podcast',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}); toast('Podcast generated'); showSection('library');}catch(e){toast('Error: '+e.message);} }
async function refreshQuote(){
  const el = document.getElementById('g-v-quote');
  if (!el) return;
  const dur = +val('g-v-dur')||20;
  if (dur < 60) { el.textContent = ''; return; }
  try {
    const q = await api('/api/jobs/quote?duration='+dur+'&quality='+encodeURIComponent(sel('g-v-q'))
      +'&provider='+encodeURIComponent(sel('g-v-prov')||''));
    el.textContent = q.error ? ('Quote: '+q.error)
      : (`Quote: $${q.estimated_usd.toFixed(2)} via ${q.provider}` +
         (q.free_remaining_cents==null ? ' (no free balance recorded — testing mode)'
          : (` · free left $${(q.free_remaining_cents/100).toFixed(2)}` + (q.affordable?'':' · OVER BUDGET — job will be refused'))));
  } catch(e){ el.textContent = ''; }
}
async function genVideo(){
  const b={topic:val('g-v-topic'),prompt:val('g-v-prompt')||val('g-v-topic'),duration:+val('g-v-dur')||20,quality:sel('g-v-q'),preferred_provider:sel('g-v-prov')||undefined};
  if (b.duration >= 60) {
    try {
      const job = await api('/api/jobs/video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
      if (job.error) throw new Error(job.error);
      toast('Background job started: '+job.job_id+' — progress below, page auto-refreshes');
      pollJob(job.job_id); refreshJobs();
    } catch(e){ toast('Error: '+e.message); }
    return;
  }
  try{await api('/api/generate/video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}); toast('Video generated'); showSection('library');}catch(e){toast('Error: '+e.message);}
}
async function pollJob(jobId){
  const el = document.getElementById('g-v-job');
  if (!el) return;
  try {
    const j = await api('/api/jobs/'+jobId);
    el.innerHTML = `<div class="stat"><span class="k">${esc(j.stage||j.status)}</span><span class="v">${j.progress}%</span></div>
      <div class="prog"><div class="fill" style="width:${j.progress}%"></div></div>
      ${j.asset_id?`<p class="ok small">Done: ${esc(j.asset_id)} — <a href="#library" onclick="showSection('library')">open library</a></p>`:''}
      ${j.error?`<p class="bad small">${esc(j.error)}</p>`:''}`;
    if (j.status==='running' || j.status==='queued') setTimeout(()=>pollJob(jobId), 5000);
    else refreshJobs();
  } catch(e){ el.innerHTML = '<p class="bad small">Job poll failed: '+esc(e.message)+'</p>'; }
}
async function refreshJobs(){
  const el = document.getElementById('g-jobs');
  if (!el) return;
  try {
    const d = await api('/api/jobs');
    const jobs = d.jobs||[];
    el.innerHTML = jobs.length ? jobs.slice(0,10).map(j=>
      `<div class="stat"><span class="k">${esc(j.topic)} (${j.duration}s)</span>
       <span class="v">${esc(j.status)} ${j.progress}%${j.asset_id?' · '+esc(j.asset_id):''}</span></div>`).join('')
      : '<p class="muted small">No jobs yet.</p>';
  } catch(e){ el.innerHTML = '<p class="bad small">'+esc(e.message)+'</p>'; }
}
async function genQueue(){ const b={content_type:sel('g-c-type'),topic:val('g-c-topic'),priority:sel('g-c-pri'),quality:sel('g-c-q')}; try{await api('/api/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}); toast('Added to queue'); showSection('overview');}catch(e){toast('Error: '+e.message);} }
async function uploadMusic(){
  const inp = document.getElementById('u-m-file');
  const st = document.getElementById('u-m-status');
  if (!inp || !inp.files || !inp.files[0]) { toast('Choose an MP3/WAV file first'); return; }
  const fd = new FormData();
  fd.append('file', inp.files[0]);
  fd.append('title', val('u-m-title'));
  fd.append('genre', val('u-m-genre')||'cinematic');
  fd.append('mood', val('u-m-mood')||'inspirational');
  fd.append('source', sel('u-m-source')||'owner_upload');
  fd.append('license_note', val('u-m-license'));
  fd.append('lyrics', document.getElementById('u-m-lyrics').value.trim());
  st.textContent = 'Uploading and mastering…';
  try {
    const r = await fetch('/api/upload/music', {method:'POST', body:fd});
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    st.textContent = '';
    toast('Uploaded: '+data.asset_id+' — review it in the library');
    showSection('library');
  } catch(e){ st.textContent = ''; toast('Upload error: '+e.message); }
}
function val(id){return document.getElementById(id).value.trim();}
function sel(id){return document.getElementById(id).value;}

// ---------- YouTube Publish (ingest → unlisted → review → public) ----------
async function ingestVideo(){
  const st = document.getElementById('i-v-status');
  const path = val('i-v-path');
  if (!path) { toast('Enter the path to a video file on this machine'); return; }
  st.textContent = 'Hashing and copying into app storage…';
  try {
    const r = await api('/api/ingest/video', {method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path, topic:val('i-v-topic'), title:val('i-v-title'),
        pillar:sel('i-v-pillar'), language:sel('i-v-lang'), source:sel('i-v-source')})});
    if (r.error) throw new Error(r.error);
    st.textContent = '';
    toast('Ingested ' + r.asset_id + ' (' + r.media_manifest.resolution + ', ' +
      Math.round(r.media_manifest.duration) + 's) — review it under Approvals, then publish it.');
    showSection('publish');
  } catch(e){ st.textContent = ''; toast('Ingest error: '+e.message); }
}
async function runPreflight(){
  const el = document.getElementById('yt-preflight');
  if (el) el.textContent = 'Running preflight…';
  try {
    const r = await api('/api/preflight/youtube');
    if (el) el.textContent = JSON.stringify(r, null, 2);
    toast('Preflight complete');
  } catch(e){ if (el) el.textContent = ''; toast('Preflight error: '+e.message); }
}
async function startYoutubeOauth(){
  try {
    const r = await api('/api/youtube/oauth/start');
    if (r.error) throw new Error(r.error);
    window.open(r.authorization_url, '_blank');
    toast('Consent opened in a new tab. Approve all scopes, then the callback lands back here.');
  } catch(e){ toast('OAuth error: '+e.message); }
}
async function saveReviewMetadata(id){
  try {
    const r = await api('/api/review/'+id+'/metadata', {method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:val('rv-title-'+id), description:val('rv-desc-'+id), tags:val('rv-tags-'+id)})});
    if (r.error) throw new Error(r.error);
    toast('Metadata saved');
    LOADERS.publish();
  } catch(e){ toast('Save error: '+e.message); }
}
async function uploadUnlisted(id){
  if (!confirm('Upload this video to YouTube as UNLISTED? This spends 1600 of your 10000 daily API quota units.')) return;
  toast('Uploading to YouTube (unlisted) — this can take a while for large files…');
  try {
    const r = await api('/api/upload-unlisted/'+id, {method:'POST'});
    if (r.error) throw new Error(r.error);
    toast('Uploaded unlisted: '+r.youtube_url);
    LOADERS.publish();
  } catch(e){ toast('Upload error: '+e.message); }
}
async function goPublic(id){
  if (!confirm('Publish this video PUBLICLY on YouTube?\\n\\nThis is irreversible from here — going public exposes the video to everyone. Only continue after you have watched the unlisted embed above.')) return;
  try {
    const r = await api('/api/go-public/'+id, {method:'POST'});
    if (r.error) throw new Error(r.error);
    toast('Now public: '+r.youtube_url);
    LOADERS.publish();
  } catch(e){
    toast('Publish blocked: '+e.message+
      '\\n\\nIf this says "private-lock", open YouTube Studio and switch the video to Public manually — the metadata is already applied.');
    LOADERS.publish();
  }
}
LOADERS.publish = async function(){
  const data = await api('/api/library');
  const videos = (data.items||[]).filter(i=>i.content_type==='video');
  const reviewable = videos.filter(i=>i.status==='uploaded_unlisted');
  const ready = videos.filter(i=>i.status==='approved');
  const published = videos.filter(i=>i.status==='published');
  const reviews = [];
  for (const item of reviewable){ reviews.push(await api('/api/review/'+item.asset_id)); }
  document.getElementById('sections').innerHTML = `
    <div class="card wide-card">
      <h2>YouTube Publish <span class="count">${reviewable.length}</span></h2>
      <p class="muted small">Ingest → upload unlisted → watch the real embed → edit metadata → go public. The agent can ingest and upload unlisted; only you can approve and publish.</p>
      ${reviewable.length===0?'<p class="muted small">Nothing awaiting review. Ingest a video under Generate, approve it under Approvals, then upload it unlisted below.</p>':''}
      ${reviews.map(r=>`
        <div class="library-item" data-id="${esc(r.asset_id)}">
          <div class="head">
            <span class="badge">video</span>
            <span class="title">${esc(r.topic)}</span>
            <span class="badge ${badgeClass(r.status)}">${esc(r.status)}</span>
            <span class="pill">${esc(r.resolution||'')} · ${Math.round(r.duration||0)}s</span>
            <span class="pill" title="unlisted video id">${esc(r.youtube_video_id||'')}</span>
            <div style="margin-left:auto" class="small muted">${esc(r.source_path||'')}</div>
          </div>
          <div class="player-wrap">${playerHTML({content_type:'video', media_url:r.media_url, media_exists:r.media_exists})}</div>
          ${r.youtube_embed_url?`<div class="player-wrap" style="background:#000">
            <iframe width="100%" height="320" src="${esc(r.youtube_embed_url)}" title="Unlisted preview"
              frameborder="0" allow="accelerometer; clipboard-write; encrypted-media; picture-in-picture" allowfullscreen></iframe>
          </div>
          <div class="meta">Unlisted embed — this is exactly what a viewer with the link sees.
            <a href="${esc(r.youtube_url||'#')}" target="_blank" rel="noopener">Open on YouTube</a></div>`:''}
          <div class="meta">
            <label>Title (max 100)</label>
            <input id="rv-title-${esc(r.asset_id)}" value="${esc(r.seo_metadata.title||'')}">
            <label>Description</label>
            <textarea id="rv-desc-${esc(r.asset_id)}" rows="5">${esc(r.seo_metadata.description||'')}</textarea>
            <label>Tags (comma separated)</label>
            <input id="rv-tags-${esc(r.asset_id)}" value="${esc((r.seo_metadata.tags||[]).join(', '))}">
            <button class="btn gray sm" onclick="saveReviewMetadata('${esc(r.asset_id)}')">Save metadata</button>
          </div>
          <div class="actions" data-id="${esc(r.asset_id)}">
            <button class="btn green sm" onclick="goPublic('${esc(r.asset_id)}')">Go Public</button>
            <button class="btn red sm act-reject" data-type="video">Reject</button>
            <span class="small muted">Going public is irreversible from here.</span>
          </div>
        </div>`).join('')}
    </div>
    <div class="card wide-card" style="margin-top:16px">
      <h2>Approved, not yet uploaded <span class="count">${ready.length}</span></h2>
      ${ready.length===0?'<p class="muted small">No approved videos waiting on an unlisted upload.</p>':ready.map(item=>`
        <div class="library-item">
          <div class="head">
            <span class="badge">video</span>
            <span class="title">${esc(item.title||item.topic||item.asset_id)}</span>
            <span class="badge ${badgeClass(item.status)}">${esc(item.status)}</span>
            <span class="pill">${esc((item.media_manifest||{}).resolution||'')}</span>
          </div>
          <div class="player-wrap">${playerHTML(item)}</div>
          <div class="actions">
            <button class="btn blue sm" onclick="uploadUnlisted('${esc(item.asset_id)}')">Upload unlisted</button>
            <span class="small muted">1600 quota units · the video stays unlisted until you say otherwise.</span>
          </div>
        </div>`).join('')}
    </div>
    ${published.length?`<div class="card wide-card" style="margin-top:16px">
      <h2>Published <span class="count">${published.length}</span></h2>
      <table><tr><th>Asset</th><th>Topic</th><th>YouTube</th></tr>
        ${published.map(item=>`<tr><td>${esc(item.asset_id)}</td><td>${esc(item.topic)}</td>
          <td>${(item.media_manifest||{}).youtube_url?`<a href="${esc(item.media_manifest.youtube_url)}" target="_blank" rel="noopener">${esc(item.media_manifest.youtube_video_id||'')}</a>`:'-'}</td></tr>`).join('')}
      </table>
    </div>`:''}`;
  document.querySelectorAll('.act-reject').forEach(b=>b.onclick=()=>doReject(b.closest('.actions')));
};

// ---------- Finance Plan ----------
LOADERS.finance = async function(){
  const fin = await api('/api/finance/plan');
  const cfg = fin.status||{};
  document.getElementById('sections').innerHTML = `
    <div class="grid">
      <div class="card"><h2>Spend Status</h2>
        <div class="stat"><span class="k">Weekly spend</span><span class="v">${money(cfg.weekly_costs)}</span></div>
        <div class="stat"><span class="k">Music</span><span class="v">${money(cfg.music_costs)}</span></div>
        <div class="stat"><span class="k">Podcast</span><span class="v">${money(cfg.podcast_costs)}</span></div>
        <div class="stat"><span class="k">Video</span><span class="v">${money(cfg.video_costs)}</span></div>
      </div>
      <div class="card"><h2>Budget & Goal</h2>
        <div class="stat"><span class="k">Goal</span><span class="v">${esc(fin.plan.goal)}</span></div>
        <div class="stat"><span class="k">Target</span><span class="v">${esc(fin.plan.target)}</span></div>
        <div class="stat"><span class="k">Time frame</span><span class="v">${esc(fin.plan.time_frame)}</span></div>
        <div class="prog"><div class="fill" style="width:${Math.min(100,fin.plan.utilization_pct)}%"></div></div>
        <div class="small muted">${fin.plan.utilization_pct}% of monthly budget used</div>
      </div>
      <div class="card"><h2>Owners of Record (Finance)</h2>
        ${fin.responsibilities.map(r=>`<div class="stat"><span class="k">${esc(r.role)}</span><span class="v small">${esc(r.responsible)}</span></div>`).join('')}
      </div>
    </div>`;
};

// ---------- Metacognition ----------
LOADERS.meta = async function(){
  const intel = await api('/api/intelligence');
  const ranking = intel.performance_ranking||[];
  const shipo = intel.shipo||{};
  document.getElementById('sections').innerHTML = `
    <div class="card wide-card">
      <h2>SHIPO Recommendation (requires owner approval)</h2>
      <p>${esc(shipo.strategy||'-')}</p>
      <div class="grid" style="margin-top:12px">
        <div class="card"><h2>Viral Topic Suggestions</h2>
          ${(shipo.viral_topic_suggestions||[]).map(s=>`<div class="pill">${esc(s)}</div>`).join('')||'<p class="muted">None</p>'}
        </div>
        <div class="card"><h2>Production Pattern</h2>
          <div class="stat"><span class="k">Recommended</span><span class="v">${esc(shipo.recommended_production_pattern||'-')}</span></div>
          <div class="stat"><span class="k">Owner approval</span><span class="v">${shipo.requires_owner_approval?'<span class="warn">Required</span>':'<span class="ok">Not required</span>'}</span></div>
        </div>
      </div>
      <h2 style="margin-top:18px">Performance Ranking</h2>
      <table>
        <tr><th>Asset</th><th>Type</th><th>Provider</th><th>Score</th><th>Status</th><th></th></tr>
        ${ranking.map(r=>`
          <tr>
            <td>${esc(r.topic||r.asset_id)}</td>
            <td>${esc(r.content_type)}</td>
            <td>${esc(r.provider)}</td>
            <td>${esc(r.winning_metrics?JSON.stringify(r.winning_metrics):'')}</td>
            <td>${esc(r.status)}</td>
            <td>${r.status==='proposed'?`<button class="btn green sm" onclick="approveMemory('${esc(r.memory_id)}')">Approve</button>`:`<span class="ok">${esc(r.approved_at||'')}</span>`}</td>
          </tr>`).join('')}
      </table>
    </div>`;
};
async function approveMemory(mid){ try{await api('/api/memory/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory_id:mid})}); toast('Recommendation approved'); showSection('meta');}catch(e){toast('Error: '+e.message);} }

// ---------- Providers & Keys ----------
const PROVIDER_FIELDS = [
  ['openrouter','OpenRouter',['api_key','base_url','model']],
  ['groq','Groq',['api_key','base_url','model']],
  ['nvidia_nim','NVIDIA NIM',['api_key','base_url','model']],
  ['cerebras','Cerebras',['api_key','base_url','model']],
  ['huggingface','HuggingFace',['api_key','base_url','model']],
  ['suno','Suno (music) — no public API key exists; leave empty, music routes via aimlapi',['api_key']],
  ['kling','Kling (video)',['api_key']],
  ['seedance','Seedance (video)',['api_key']],
  ['pexels','Pexels (free stock video)',['api_key']],
  ['pixabay','Pixabay (free stock video)',['api_key']],
  ['kokoro','Kokoro (tts) — blank key + local base URL for Docker (e.g. http://localhost:8880/v1)',['api_key','base_url']],
  ['elevenlabs','ElevenLabs (tts)',['api_key','base_url']],
  ['aimlapi','aimlapi (music)',['api_key']],
  ['kai','KAI.AI (music)',['api_key']],
];
LOADERS.providers = async function(){
  const pv = await api('/api/providers');
  const conn = await api('/api/connections');
  document.getElementById('sections').innerHTML = `
    <div class="grid wide">
      <div class="card"><h2>Cloud Provider Terms Approval</h2>
        <table>
          <tr><th>Provider</th><th>Status</th><th>Action</th></tr>
          ${Object.entries(pv.approvals||{}).map(([n,a])=>`
            <tr>
              <td>${esc(n)}</td>
              <td class="${a.approved?'ok':'warn'}">${a.approved?('Approved by '+(a.approved_by||'')):'Needs approval'}</td>
              <td>
                ${a.approved
                  ?`<button class="btn red sm" onclick="revokeProvider('${esc(n)}')">Revoke</button>`
                  :`<button class="btn green sm" onclick="approveProvider('${esc(n)}')">Approve terms</button>`}
              </td>
            </tr>`).join('')}
        </table>
        <p class="small muted" style="margin-top:8px">Approving a provider lets the system route generation to it. Credentials are encrypted at rest with BLUE_WAVES_MASTER_PASSWORD.</p>
      </div>
      <div class="card"><h2>YouTube Connection</h2>
        <p class="small muted">Publishing needs the <code>youtube.force-ssl</code> scope — it is what lets the system flip a video from unlisted to public. Re-authorize once to grant it; consent is yours to give, in the browser.</p>
        <div class="stat"><span class="k">Status</span><span class="v ${conn&&conn.youtube&&conn.youtube.connected?'ok':'warn'}">${conn&&conn.youtube&&conn.youtube.connected?'connected':'not connected'}</span></div>
        <div class="stat"><span class="k">Recorded scopes</span><span class="v small">${esc(((conn&&conn.youtube&&conn.youtube.scopes)||[]).join(', ')||'—')}</span></div>
        <button class="btn" onclick="startYoutubeOauth()">Re-authorize YouTube (grant force-ssl)</button>
        <button class="btn gray" onclick="runPreflight()">Run preflight</button>
        <pre id="yt-preflight" class="small muted" style="white-space:pre-wrap;max-height:260px;overflow:auto;margin-top:8px"></pre>
      </div>
      <div class="card"><h2>API Keys</h2>
        <p class="small muted">Secrets are encrypted at rest and are never shown again after saving. Screenshot nothing.</p>
        ${PROVIDER_FIELDS.map(([id,name,fields])=>`
          <div class="agent" style="margin-bottom:10px">
            <div class="name">${esc(name)} <span class="tier">${conn&&conn[id]&&conn[id].connected?'connected':'not configured'}</span></div>
            ${fields.map(f=>`
              <label>${esc(f)}</label>
              <input type="${f==='api_key'||f==='client_secret'?'password':''}" class="${f==='api_key'?'secret':''}"
                     data-provider="${esc(id)}" data-field="${esc(f)}" placeholder="${f==='api_key'?'Enter '+name+' API key':esc(f)}">
            `).join('')}
            <button class="btn" onclick="saveProviderKeys('${esc(id)}')">Save ${esc(name)}</button>
          </div>`).join('')}
        <div id="key-confirm" style="display:none" class="card" style="margin-top:10px"
             ><p class="ok">Keys saved and encrypted. Input fields cleared — keys are no longer displayed.</p></div>
      </div>
    </div>`;
};
async function approveProvider(n){ await api('/api/providers/approve/'+n,{method:'POST',headers:{'Content-Type':'application/json'},body:'{"actor":"owner"}'}); toast(n+' approved'); showSection('providers'); }
async function revokeProvider(n){ await api('/api/providers/revoke/'+n,{method:'POST'}); toast(n+' revoked'); showSection('providers'); }
async function saveProviderKeys(provider){
  const payload = {provider};
  document.querySelectorAll(`input[data-provider="${provider}"]`).forEach(inp=>{
    if (inp.value.trim()) payload[inp.dataset.field] = inp.value.trim();
  });
  if (!Object.keys(payload).some(k=>k!=='provider')){ toast('Nothing to save'); return; }
  try {
    const res = await api('/api/connections', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    document.querySelectorAll(`input[data-provider="${provider}"]`).forEach(inp=>inp.value='');
    toast('Saved & encrypted: '+JSON.stringify(res));
    const c=document.getElementById('key-confirm'); if(c)c.style.display='block';
  } catch(e){ toast('Error: '+e.message); }
}

// ---------- Scheduler ----------
LOADERS.scheduler = async function(){
  const s = await api('/api/scheduler');
  const q = await api('/api/queue');
  document.getElementById('sections').innerHTML = `
    <div class="grid">
      <div class="card"><h2>Scheduler Stats</h2>
        ${Object.entries({total_jobs:'Total jobs',pending:'Pending',running:'Running',completed:'Completed',failed:'Failed',weekly_published:'Weekly published',weekly_limit:'Weekly limit',queue_size:'Queue size',publish_window_days:'Publish days'}).map(([k,label])=>
          `<div class="stat"><span class="k">${label}</span><span class="v">${esc(Array.isArray(s[k])?s[k].join(','):(s[k]!==undefined?s[k]:'-'))}</span></div>`).join('')}
        <button class="btn" onclick="schedTick()">Run scheduler tick</button>
      </div>
      <div class="card"><h2>Queue Detail</h2>
        <table>
          <tr><th>ID</th><th>Type</th><th>Topic</th><th>Stage</th><th>Pri</th></tr>
          ${q.map(r=>`<tr><td>${esc(r.id)}</td><td>${esc(r.content_type)}</td><td>${esc(r.topic)}</td><td>${esc(r.stage)}</td><td>${esc(r.priority)}</td></tr>`).join('')}
        </table>
      </div>
    </div>`;
};
async function schedTick(){ try{const r=await api('/api/scheduler/tick',{method:'POST'}); toast(r); showSection('scheduler');}catch(e){toast('Error: '+e.message);} }

// ---------- Monetization ----------
LOADERS.monetization = async function(){
  const mk = await api('/api/monetization/mediakit');
  const sp = await api('/api/sponsors');
  document.getElementById('sections').innerHTML = `
    <div class="grid">
      <div class="card"><h2>Media Kit</h2>
        <div class="stat"><span class="k">Channel</span><span class="v">${esc(mk.channel_name)}</span></div>
        <div class="stat"><span class="k">Audience</span><span class="v small">${esc(mk.audience_summary)}</span></div>
        <div class="stat"><span class="k">Videos</span><span class="v">${mk.content_breakdown?mk.content_breakdown.videos:'-'}</span></div>
        <div class="stat"><span class="k">Music</span><span class="v">${mk.content_breakdown?mk.content_breakdown.music:'-'}</span></div>
        <div class="stat"><span class="k">Podcasts</span><span class="v">${mk.content_breakdown?mk.content_breakdown.podcasts:'-'}</span></div>
        <div class="stat"><span class="k">Views</span><span class="v">${mk.totals?mk.totals.view_count:'-'}</span></div>
      </div>
      <div class="card"><h2>Sponsor Pipeline</h2>
        <table>
          <tr><th>Name</th><th>Contact</th><th>Status</th><th>Budget</th></tr>
          ${(sp.prospects||[]).map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.contact)}</td><td>${esc(p.status)}</td><td>${money(p.budget_usd*100)}</td></tr>`).join('')||'<tr><td colspan=4 class="muted">No prospects yet</td></tr>'}
        </table>
        <h2 style="margin-top:12px">Add Prospect</h2>
        <label>Name</label><input id="sp-name">
        <label>Contact</label><input id="sp-contact">
        <label>Niche</label><input id="sp-niche">
        <label>Budget (USD)</label><input id="sp-budget">
        <button class="btn" onclick="addSponsor()">Add Sponsor</button>
      </div>
    </div>`;
};
async function addSponsor(){ try{await api('/api/sponsors',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:val('sp-name'),contact:val('sp-contact'),niche:val('sp-niche'),budget_usd:+val('sp-budget')||0})}); toast('Sponsor added'); showSection('monetization');}catch(e){toast('Error: '+e.message);} }

// ---------- SHEPO Finance ----------
LOADERS.shepo = async function(){
  const plan = await api('/api/shepo/finance');
  const shepo = plan.shepo_report || {};
  const proj = shepo.revenue_projection || {};
  const be = shepo.break_even_analysis || {};
  const contentCosts = shepo.content_costs || {};
  const providerCmp = shepo.provider_comparison || [];
  document.getElementById('sections').innerHTML = `
    <div class="card">
      <h2>SHEPO — Finance & Profit Strategist</h2>
      <p class="muted">Agent responsible for real cost tracking, revenue projection, and profitability analysis.</p>
    </div>
    <div class="grid">
      <div class="card">
        <h2>Revenue Projection</h2>
        <div class="stat"><span class="k">Views/Video</span><span class="v">${proj.views_per_video || '-'}</span></div>
        <div class="stat"><span class="k">CPM</span><span class="v">$${(proj.cpm||0).toFixed(2)}</span></div>
        <div class="stat"><span class="k">Uploads/Month</span><span class="v">${proj.upload_frequency || '-'}</span></div>
        <div class="stat"><span class="k">Revenue/Video</span><span class="v">${money(proj.revenue_per_video_cents||0)}</span></div>
        <div class="stat"><span class="k">Monthly Revenue</span><span class="v">${money(proj.monthly_revenue_cents||0)}</span></div>
        <div class="stat"><span class="k">Monthly Cost</span><span class="v">${money(proj.monthly_cost_cents||0)}</span></div>
        <div class="stat"><span class="k">Net Profit</span><span class="v" style="color:${(proj.net_profit_cents||0)>0?'var(--green)':'var(--red)'}">${money(proj.net_profit_cents||0)}</span></div>
        <div class="stat"><span class="k">Profitable?</span><span class="v" style="color:${proj.profitable?'var(--green)':'var(--red)'}">${proj.profitable?'YES':'Not yet'}</span></div>
      </div>
      <div class="card">
        <h2>Break-Even Analysis</h2>
        <div class="stat"><span class="k">Monthly Cost</span><span class="v">${money(be.monthly_cost_cents||0)}</span></div>
        <div class="stat"><span class="k">Current Revenue</span><span class="v">${money(be.current_monthly_revenue_cents||0)}</span></div>
        <div class="stat"><span class="k">Required Views/Video</span><span class="v">${be.required_views_per_video||'-'}</span></div>
        <div class="stat"><span class="k">Months to Break Even</span><span class="v" style="color:${be.break_even_feasible?'var(--green)':'var(--red)'}">${be.break_even_feasible?be.months_to_break_even:'N/A'}</span></div>
        <div class="stat"><span class="k">Avg CPM</span><span class="v">$${(be.avg_cpm||0).toFixed(2)}</span></div>
      </div>
    </div>
    <div class="card">
      <h2>Cost by Content Type</h2>
      <table>
        <tr><th>Content Type</th><th>Cost (cents)</th></tr>
        <tr><td>Music</td><td>${money(contentCosts.music_cents||0)}</td></tr>
        <tr><td>Podcast</td><td>${money(contentCosts.podcast_cents||0)}</td></tr>
        <tr><td>Video</td><td>${money(contentCosts.video_cents||0)}</td></tr>
        <tr><td><strong>Total</strong></td><td><strong>${money(shepo.weekly_cost_cents||0)}</strong></td></tr>
      </table>
    </div>
    <div class="card">
      <h2>Provider Cost Comparison</h2>
      <table>
        <tr><th>Provider</th><th>Cost/Unit (cents)</th><th>Unit</th><th>Notes</th></tr>
        ${providerCmp.map(p=>`<tr><td>${esc(p.provider)}</td><td>${p.cost_per_unit_cents}</td><td>${esc(p.unit)}</td><td class="small">${esc(p.notes)}</td></tr>`).join('')}
      </table>
    </div>
    <div class="card">
      <h2>Cost by Provider</h2>
      <table>
        <tr><th>Provider</th><th>Total Cost (cents)</th></tr>
        ${Object.entries(shepo.total_costs||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${money(v)}</td></tr>`).join('')||'<tr><td colspan=2 class="muted">No costs tracked yet</td></tr>'}
      </table>
    </div>`;
};

// ---------- boot ----------
function boot(){
  renderNav();
  const hash = (location.hash||'#overview').replace('#','');
  const target = NAV.some(n=>n[0]===hash) ? hash : 'overview';
  showSection(target, false);
  // 10s auto-refresh on current section for live monitoring
  setInterval(()=>{ if(['overview','approvals','shepo','crew'].includes(window._cur)) LOADERS[window._cur](); }, 10000);
}
boot();
</script>
</body>
</html>
"""
