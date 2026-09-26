import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';

const API=import.meta.env.VITE_API_URL||'http://localhost:8000';
const money=n=>'$'+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:0});

async function api(path,opts={}){
  const token=localStorage.getItem('gtext_token');
  const r=await fetch(API+path,{...opts,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...(opts.headers||{})}});
  if(!r.ok){let msg=await r.text();try{msg=JSON.parse(msg).detail||msg}catch{};throw new Error(msg||r.statusText)}
  return r.json();
}

function Auth({onAuth}){
  const [mode,setMode]=useState('login');
  const [f,setF]=useState({email:'',password:'',name:'',company:''});
  const [err,setErr]=useState('');
  const submit=async()=>{
    try{
      setErr('');
      const r=await api('/auth/'+mode,{method:'POST',body:JSON.stringify(f)});
      localStorage.setItem('gtext_token',r.token);
      onAuth(r);
    }catch(e){setErr(e.message)}
  };
  return <div className="auth"><div className="authbox"><div className="brand"><b>GTEXT</b><span>REAL ESTATE AI</span></div><h1>{mode==='login'?'Investor sign in':'Create investor account'}</h1><p>Lead intelligence, underwriting, seller workflow and portfolio management in one workspace.</p>{mode==='register'&&<><input placeholder="Full name" value={f.name} onChange={e=>setF({...f,name:e.target.value})}/><input placeholder="Company" value={f.company} onChange={e=>setF({...f,company:e.target.value})}/></>}<input type="email" placeholder="Email" value={f.email} onChange={e=>setF({...f,email:e.target.value})}/><input type="password" placeholder="Password (8+ characters)" value={f.password} onChange={e=>setF({...f,password:e.target.value})}/>{err&&<div className="error">{err}</div>}<button className="primary" onClick={submit}>{mode==='login'?'Sign in':'Create account'}</button><button className="link" onClick={()=>setMode(mode==='login'?'register':'login')}>{mode==='login'?'Create an investor account':'Back to sign in'}</button></div></div>
}

function App(){
  const [token,setToken]=useState(localStorage.getItem('gtext_token')||'');
  const [me,setMe]=useState(null);
  const [view,setView]=useState('leads');
  const [properties,setProperties]=useState([]);
  const [selected,setSelected]=useState(null);
  const [health,setHealth]=useState(null);
  const [toast,setToast]=useState('');
  const notify=t=>{setToast(String(t));setTimeout(()=>setToast(''),3200)};
  const load=async()=>{
    if(!token)return;
    try{
      const [p,h,u]=await Promise.all([api('/properties?status=active'),api('/health'),api('/auth/me')]);
      setProperties(p);setHealth(h);setMe(u);if(!selected&&p.length)setSelected(p[0]);
    }catch(e){if(e.message.includes('Authentication')){localStorage.removeItem('gtext_token');setToken('')}else notify(e.message)}
  };
  useEffect(()=>{load()},[token]);
  if(!token)return <Auth onAuth={r=>{setToken(r.token);setMe(r.investor)}}/>;
  const nav=[['leads','Lead Intelligence'],['map','Acquisition Map'],['underwrite','Underwriting'],['crm','Seller / Agent CRM'],['outreach','Seller Outreach'],['analytics','Pipeline Analytics'],['portfolio','Portfolio / Deal Room'],['settings','Buy Box']];
  return <div className="shell">
    <aside><div className="brand"><b>GTEXT</b><span>REAL ESTATE AI</span></div><nav>{nav.map(n=><button key={n[0]} className={view===n[0]?'active':''} onClick={()=>setView(n[0])}>{n[1]}</button>)}</nav><div className="connections"><b>DATA CONNECTIONS</b><span><i className={health?.providers?.rentcast?'on':''}/>RentCast {health?.providers?.rentcast?'connected':'configure'}</span><span><i className={health?.providers?.offmarket?'on':''}/>Off-market {health?.providers?.offmarket?'connected':'configure'}</span><span><i className="on"/>6-hour scheduler</span></div><div className="user"><b>{me?.name||'Investor'}</b><span>{me?.company||me?.email}</span><button onClick={()=>{localStorage.removeItem('gtext_token');setToken('')}}>Sign out</button></div></aside>
    <main>
      {view==='leads'&&<Leads properties={properties} selected={selected} setSelected={setSelected} reload={load} notify={notify}/>}
      {view==='map'&&<MapView properties={properties} setSelected={p=>{setSelected(p);setView('leads')}}/>}
      {view==='underwrite'&&<Underwrite properties={properties} selected={selected} setSelected={setSelected} notify={notify}/>}
      {view==='crm'&&<CRM properties={properties} notify={notify}/>}
      {view==='outreach'&&<Outreach notify={notify}/>}
      {view==='analytics'&&<Analytics notify={notify}/>}
      {view==='portfolio'&&<Portfolio properties={properties} notify={notify}/>}
      {view==='settings'&&<BuyBox notify={notify}/>}
    </main>
    {toast&&<div className="toast">{toast}</div>}
  </div>
}

function Title({title,sub,action}){return <div className="title"><div><span>GTEXT ACQUISITION INTELLIGENCE</span><h1>{title}</h1><p>{sub}</p></div>{action}</div>}

function Leads({properties,selected,setSelected,reload,notify}){
  const [q,setQ]=useState('');
  const [market,setMarket]=useState('all');
  const filtered=useMemo(()=>properties.filter(p=>(market==='all'||p.market_type===market)&&(!q||((p.address+' '+p.city+' '+p.zip).toLowerCase().includes(q.toLowerCase())))),[properties,q,market]);
  const refresh=async()=>{try{const r=await api('/refresh',{method:'POST'});notify('Refresh completed: '+(r.listings?.fetched||0)+' live records observed');reload()}catch(e){notify(e.message)}};
  const qualified=properties.filter(p=>p.analysis.qualified).length;
  return <><Title title="Lead Intelligence" sub="Live and off-market opportunities ranked against your acquisition criteria." action={<button className="primary small" onClick={refresh}>Refresh feeds</button>}/><div className="stats"><Stat label="Active leads" value={properties.length}/><Stat label="Qualified" value={qualified}/><Stat label="Off-market" value={properties.filter(p=>p.market_type==='off-market').length}/><Stat label="Watchlist" value={properties.filter(p=>p.saved).length}/></div><div className="filters"><input placeholder="Search address, city or ZIP" value={q} onChange={e=>setQ(e.target.value)}/><select value={market} onChange={e=>setMarket(e.target.value)}><option value="all">All markets</option><option value="on-market">On-market</option><option value="off-market">Off-market</option></select></div><div className="leadgrid"><section className="list">{filtered.map(p=><button className={'lead '+(selected?.id===p.id?'selected':'')} key={p.id} onClick={()=>setSelected(p)}><div className="score">{p.analysis.score}<small>/100</small></div><div><b>{p.address}</b><span>{p.city}, {p.state} {p.zip}</span><em>{p.beds} bd · {p.baths} ba · {Number(p.sqft).toLocaleString()} sqft</em><div className="tags"><i>{p.market_type}</i>{p.analysis.qualified&&<i>qualified</i>}</div></div><div className="price"><b>{money(p.asking_price)}</b><span>MAO {money(p.analysis.mao)}</span></div></button>)}</section><PropertyDetail p={selected} notify={notify} reload={reload}/></div></>
}

function Stat({label,value}){return <div className="stat"><span>{label}</span><b>{value}</b></div>}

function PropertyDetail({p,notify,reload}){
  const [comps,setComps]=useState(null);const [memo,setMemo]=useState(null);const [distress,setDistress]=useState([]);
  useEffect(()=>{setComps(null);setMemo(null);if(p)api('/distress/'+encodeURIComponent(p.id)).then(setDistress).catch(()=>setDistress([]))},[p?.id]);
  if(!p)return <section className="detail"><p>Select a property to inspect the deal.</p></section>;
  const save=async()=>{await api('/properties/'+encodeURIComponent(p.id)+'/save',{method:'PATCH'});notify('Watchlist updated');reload()};
  const addContact=async()=>{try{await api('/crm/contacts',{method:'POST',body:JSON.stringify({property_id:p.id,contact_type:p.owner_name?'seller':'agent',name:p.owner_name||p.agent_name||'Property contact',email:p.owner_email||p.agent_email||'',phone:p.owner_phone||p.agent_phone||'',status:'new',source:p.source,notes:'Created from property lead'})});notify('Contact added to CRM')}catch(e){notify(e.message)}};
  return <section className="detail"><div className="detailhead"><div><span>{p.status}</span><h2>{p.address}</h2><p>{p.city}, {p.state} {p.zip}</p></div><strong>{p.analysis.score}<small>/100</small></strong></div><div className="metrics"><Metric label="Asking" value={money(p.asking_price)}/><Metric label="ARV" value={money(p.estimated_arv)}/><Metric label="Rehab" value={money(p.estimated_rehab)}/><Metric label="MAO" value={money(p.analysis.mao)}/><Metric label="Flip profit" value={money(p.analysis.flip_profit)}/><Metric label="Gross yield" value={p.analysis.gross_yield+'%'}/></div><h3>Strategy fit</h3><div className="tags">{p.analysis.strategies.map(x=><i key={x}>{x}</i>)}</div><h3>Risk signals</h3>{p.analysis.risks.length?p.analysis.risks.map(x=><p className="risk" key={x}>{x}</p>):<p className="muted">No rule-based risk signals.</p>}<div className="actions"><button onClick={save}>Watchlist</button><button onClick={addContact}>Add CRM</button><button onClick={async()=>{try{setComps(await api('/properties/'+encodeURIComponent(p.id)+'/comps'))}catch(e){notify(e.message)}}}>Sold comps</button><button onClick={async()=>{try{setMemo(await api('/properties/'+encodeURIComponent(p.id)+'/memo',{method:'POST'}))}catch(e){notify(e.message)}}}>AI memo</button></div>{distress.length>0&&<div className="panel"><h3>Verified distress records</h3>{distress.map(d=><p key={d.id}><b>{d.record_type.replaceAll('_',' ')}</b> · severity {d.severity} · equity {d.estimated_equity_pct}%<br/><span>{d.provider} · verified {new Date(d.verified_at).toLocaleDateString()}</span></p>)}</div>}{comps&&<div className="panel"><h3>Sold comps</h3><b>Average {money(comps.average_sale_price)} · {money(comps.average_price_per_sqft)}/sqft</b>{comps.comps.map((c,i)=><p key={i}>{c.address}<span>{money(c.sale_price)} · {c.sale_date}</span></p>)}</div>}{memo&&<div className="panel memo"><h3>Investment memo</h3><pre>{memo.content}</pre></div>}</section>
}

function Metric({label,value}){return <div className="metric"><span>{label}</span><b>{value}</b></div>}

function MapView({properties,setSelected}){
  const ref=useRef(null);const map=useRef(null);
  useEffect(()=>{if(!ref.current||map.current)return;map.current=L.map(ref.current).setView([33.15,-96.75],10);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(map.current);return()=>{map.current?.remove();map.current=null}},[]);
  useEffect(()=>{if(!map.current)return;map.current.eachLayer(layer=>{if(layer instanceof L.Marker)map.current.removeLayer(layer)});const bounds=[];properties.forEach(p=>{if(p.latitude==null||p.longitude==null)return;const m=L.marker([p.latitude,p.longitude]).addTo(map.current);m.bindPopup('<b>'+p.address+'</b><br>'+money(p.asking_price)+'<br>Score '+p.analysis.score);m.on('click',()=>setSelected(p));bounds.push([p.latitude,p.longitude])});if(bounds.length)map.current.fitBounds(bounds,{padding:[40,40]})},[properties]);
  return <><Title title="Acquisition Map" sub="Visualize active acquisition opportunities and jump directly into underwriting."/><div className="map" ref={ref}/></>
}

function Underwrite({properties,selected,setSelected,notify}){
  const [f,setF]=useState({strategy:'Buy & Hold',down_payment_pct:20,interest_rate:7,loan_term_years:30,closing_cost_pct:3,vacancy_pct:5,management_pct:8,maintenance_pct:5,insurance_annual:1800,hoa_monthly:0,utilities_monthly:0,holding_months:6,sales_cost_pct:7});
  const [result,setResult]=useState(null);const p=selected||properties[0];
  const run=async()=>{if(!p)return;try{setResult(await api('/properties/'+encodeURIComponent(p.id)+'/underwrite',{method:'POST',body:JSON.stringify(f)}))}catch(e){notify(e.message)}};
  return <><Title title="Underwriting Lab" sub="Mortgage, rental cash-flow and flip economics from editable assumptions."/><div className="twocol"><section className="workspace"><label>Property<select value={p?.id||''} onChange={e=>setSelected(properties.find(x=>x.id===e.target.value))}>{properties.map(x=><option key={x.id} value={x.id}>{x.address}</option>)}</select></label>{Object.entries(f).map(([k,v])=>k==='strategy'?<label key={k}>Strategy<select value={v} onChange={e=>setF({...f,strategy:e.target.value})}><option>Buy & Hold</option><option>Fix & Flip</option><option>Wholesale</option></select></label>:<label key={k}>{k.replaceAll('_',' ')}<input type="number" value={v} onChange={e=>setF({...f,[k]:+e.target.value})}/></label>)}<button className="primary" onClick={run}>Run underwriting</button></section><section className="workspace"><h2>Results</h2>{!result?<p className="muted">Run an underwriting case to see results.</p>:<div className="resultgrid">{Object.entries(result.results).map(([k,v])=><Metric key={k} label={k.replaceAll('_',' ')} value={typeof v==='number'?v.toLocaleString():v}/>)}</div>}</section></div></>
}

function CRM({properties,notify}){
  const [rows,setRows]=useState([]);const [f,setF]=useState({property_id:'',contact_type:'seller',name:'',email:'',phone:'',status:'new',source:'manual',notes:''});
  const load=()=>api('/crm/contacts').then(setRows).catch(e=>notify(e.message));useEffect(load,[]);
  const add=async()=>{try{await api('/crm/contacts',{method:'POST',body:JSON.stringify({...f,property_id:f.property_id||null})});setF({...f,name:'',email:'',phone:'',notes:''});notify('CRM contact created');load()}catch(e){notify(e.message)}};
  return <><Title title="Seller / Agent CRM" sub="Move property contacts from discovery through negotiation and offer."/><div className="twocol"><section className="workspace"><h2>New contact</h2><label>Property<select value={f.property_id} onChange={e=>setF({...f,property_id:e.target.value})}><option value="">No property</option>{properties.map(p=><option key={p.id} value={p.id}>{p.address}</option>)}</select></label><label>Contact type<select value={f.contact_type} onChange={e=>setF({...f,contact_type:e.target.value})}><option>seller</option><option>agent</option></select></label><input placeholder="Name" value={f.name} onChange={e=>setF({...f,name:e.target.value})}/><input placeholder="Email" value={f.email} onChange={e=>setF({...f,email:e.target.value})}/><input placeholder="Phone" value={f.phone} onChange={e=>setF({...f,phone:e.target.value})}/><textarea placeholder="Notes" value={f.notes} onChange={e=>setF({...f,notes:e.target.value})}/><button className="primary" onClick={add}>Add contact</button></section><section className="workspace"><h2>Pipeline</h2>{rows.length===0?<p className="muted">No contacts yet.</p>:rows.map(r=><div className="row" key={r.id}><div><b>{r.name}</b><span>{r.contact_type} · {r.email||r.phone||'no contact channel'} · {r.property_id||'unlinked'}</span></div><select value={r.status} onChange={async e=>{await api('/crm/contacts/'+r.id+'?status='+encodeURIComponent(e.target.value),{method:'PATCH'});load()}}><option>new</option><option>contacted</option><option>follow-up</option><option>negotiating</option><option>offer-sent</option><option>closed</option><option>lost</option></select></div>)}</section></div></>
}

function Outreach({notify}){
  const [rows,setRows]=useState([]);const [f,setF]=useState({channel:'email',recipient:'',subject:'Property inquiry',body:'Hello, I am interested in discussing your property. If you are open to a conversation, please let me know a convenient time.',consent_confirmed:false,suppressed:false});
  const load=()=>api('/outreach').then(setRows).catch(e=>notify(e.message));useEffect(load,[]);
  const draft=async()=>{try{await api('/outreach',{method:'POST',body:JSON.stringify(f)});notify('Outreach draft saved');load()}catch(e){notify(e.message)}};
  const send=async id=>{try{await api('/outreach/'+id+'/send',{method:'POST'});notify('Message sent');load()}catch(e){notify(e.message)}};
  return <><Title title="Seller Outreach" sub="Draft and queue seller communications with permission and suppression controls."/><div className="twocol"><section className="workspace"><label>Channel<select value={f.channel} onChange={e=>setF({...f,channel:e.target.value})}><option>email</option><option>sms</option></select></label><input placeholder="Recipient" value={f.recipient} onChange={e=>setF({...f,recipient:e.target.value})}/><input placeholder="Subject" value={f.subject} onChange={e=>setF({...f,subject:e.target.value})}/><textarea rows="8" value={f.body} onChange={e=>setF({...f,body:e.target.value})}/><label className="check"><input type="checkbox" checked={f.consent_confirmed} onChange={e=>setF({...f,consent_confirmed:e.target.checked})}/>Permission/consent confirmed for automated delivery</label><button className="primary" onClick={draft}>Save draft</button><p className="muted">Delivery is blocked when consent is not confirmed, the recipient is suppressed, or SMTP/Twilio is not configured.</p></section><section className="workspace"><h2>Queue</h2>{rows.map(r=><div className="row" key={r.id}><div><b>{r.channel.toUpperCase()} · {r.recipient}</b><span>{r.status} · {r.subject||r.body.slice(0,60)}</span></div>{r.status==='draft'&&<button onClick={()=>send(r.id)}>Send</button>}</div>)}</section></div></>
}

function Analytics({notify}){
  const [d,setD]=useState(null);useEffect(()=>{api('/pipeline/analytics').then(setD).catch(e=>notify(e.message))},[]);
  if(!d)return <Title title="Pipeline Analytics" sub="Loading acquisition funnel…"/>;
  return <><Title title="Pipeline Analytics" sub="Track seller engagement, offers and acquisition progression."/><div className="stats"><Stat label="CRM contacts" value={d.contacts_total}/><Stat label="Outreach sent" value={d.outreach_sent}/><Stat label="Offers" value={d.offers_total}/><Stat label="Acceptance rate" value={d.offer_acceptance_rate_pct+'%'}/></div><div className="twocol"><Funnel title="Contact stages" data={d.contact_stages}/><Funnel title="Offer stages" data={d.offer_statuses}/></div><Funnel title="Deal-room stages" data={d.deal_room_stages}/></>
}
function Funnel({title,data}){const arr=Object.entries(data||{}),max=Math.max(1,...arr.map(x=>x[1]));return <section className="workspace"><h2>{title}</h2>{arr.length===0?<p className="muted">No activity yet.</p>:arr.map(([k,v])=><div className="funnel" key={k}><span>{k}</span><i><b style={{width:Math.max(8,v/max*100)+'%'}}/></i><strong>{v}</strong></div>)}</section>}

function Portfolio({properties,notify}){
  const [d,setD]=useState(null);const [pid,setPid]=useState(properties[0]?.id||'');const load=()=>api('/portfolio').then(setD).catch(e=>notify(e.message));useEffect(load,[]);
  const add=async()=>{if(!pid)return;try{await api('/deal-rooms',{method:'POST',body:JSON.stringify({property_id:pid,name:'',stage:'underwriting',purchase_price:0,projected_value:0,invested_capital:0,checklist:[],documents:[],notes:''})});notify('Deal room created');load()}catch(e){notify(e.message)}};
  if(!d)return <Title title="Portfolio / Deal Room" sub="Loading…"/>;
  return <><Title title="Portfolio / Deal Room" sub="Promote opportunities into due diligence, closing and portfolio management." action={<div className="inline"><select value={pid} onChange={e=>setPid(e.target.value)}>{properties.map(p=><option key={p.id} value={p.id}>{p.address}</option>)}</select><button className="primary small" onClick={add}>Create deal room</button></div>}/><div className="stats"><Stat label="Active deals" value={d.active_deals}/><Stat label="Closed deals" value={d.closed_deals}/><Stat label="Purchase basis" value={money(d.portfolio_purchase_basis)}/><Stat label="Projected equity" value={money(d.projected_equity)}/></div><section className="workspace"><h2>Deal rooms</h2>{d.rooms.length===0?<p className="muted">No deal rooms yet.</p>:d.rooms.map(r=><div className="row" key={r.id}><div><b>{r.name}</b><span>{money(r.purchase_price)} basis · {money(r.projected_value)} projected value</span></div><select value={r.stage} onChange={async e=>{await api('/deal-rooms/'+r.id+'?stage='+encodeURIComponent(e.target.value),{method:'PATCH'});load()}}><option>underwriting</option><option>offer</option><option>due-diligence</option><option>financing</option><option>closing</option><option>closed</option><option>lost</option><option>sold</option></select></div>)}</section></>
}

function BuyBox({notify}){
  const [f,setF]=useState(null);useEffect(()=>{api('/settings').then(setF).catch(e=>notify(e.message))},[]);
  if(!f)return <Title title="Acquisition Buy Box" sub="Loading criteria…"/>;
  const set=(k,v)=>setF({...f,[k]:v});const save=async()=>{try{await api('/settings',{method:'PUT',body:JSON.stringify(f)});notify('Buy box saved')}catch(e){notify(e.message)}};
  return <><Title title="Acquisition Buy Box" sub="These thresholds drive qualification, strategy fit and lead ranking." action={<button className="primary small" onClick={save}>Save criteria</button>}/><section className="workspace formgrid">{[['min_deal_score','Minimum deal score'],['mao_percent','MAO factor'],['min_flip_profit','Minimum flip profit'],['min_flip_roi','Minimum flip ROI %'],['min_gross_yield','Minimum gross yield %'],['min_wholesale_spread','Minimum wholesale spread'],['max_price','Maximum purchase price']].map(([k,l])=><label key={k}>{l}<input type="number" step="any" value={f[k]} onChange={e=>set(k,+e.target.value)}/></label>)}<label>Target states<input value={(f.target_states||[]).join(', ')} onChange={e=>set('target_states',e.target.value.split(',').map(x=>x.trim()).filter(Boolean))}/></label><label className="wide">Target cities<input value={(f.target_cities||[]).join(', ')} onChange={e=>set('target_cities',e.target.value.split(',').map(x=>x.trim()).filter(Boolean))}/></label></section></>
}

createRoot(document.getElementById('root')).render(<App/>);
