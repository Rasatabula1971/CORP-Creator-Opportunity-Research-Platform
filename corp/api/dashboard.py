"""Dashboard route — serves the CORP research console with live DB data."""

import json

from fastapi import APIRouter, Depends, Response
from sqlalchemy import case, distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.database import get_session

dashboard_router = APIRouter()

PRODUCT_IDEAS = {
    "AI integration gaps in existing tools": "AI-native productivity tool that actually delivers on AI promises \u2014 not a wrapper, a tool built from scratch around LLMs",
    "Data portability and vendor lock-in": "Open-format data hub / universal exporter that frees users from ecosystem lock-in across Notion, Google, Apple etc.",
    "Need for all-in-one workflow solution": "Unified workspace that replaces 5+ point solutions \u2014 project management, notes, tasks, calendar, docs in one tool",
    "Mobile experience deficiencies": "Mobile-first version of popular desktop productivity tools \u2014 or a native mobile workspace that doesn\u2019t feel like an afterthought",
    "Pricing frustration with SaaS subscriptions": "Affordable one-time-purchase or freemium alternative to expensive SaaS tools (Notion, Figma, Adobe pricing fatigue)",
    "Learning curve barriers": "Guided onboarding course / interactive tutorial platform for complex tools \u2014 people will pay to skip the learning curve",
    "Collaboration pain points": "Real-time collaboration layer that works across existing tools rather than forcing everyone onto one platform",
    "Content creation workflow bottlenecks": "Automated content production pipeline \u2014 batch editing, thumbnail generation, SEO optimization, scheduling in one flow",
    "Privacy and data ownership concerns": "Self-hosted / local-first productivity suite with optional sync \u2014 data stays on your device by default",
    "Tool fatigue and decision paralysis": "Curated tool recommendation engine or \u2018productivity stack\u2019 builder \u2014 tell it your role, get a tested setup",
}


async def _gather_dashboard_data(session: AsyncSession) -> dict:
    """Pull all insight data from the database for the dashboard."""
    data: dict = {}

    # Problem clusters
    result = await session.execute(
        select(ProblemCluster).order_by(ProblemCluster.frequency.desc())
    )
    clusters = result.scalars().all()
    data["clusters"] = [
        {
            "label": c.label,
            "description": c.description,
            "frequency": c.frequency,
            "evidence_strength": round(float(c.evidence_strength), 2),
            "creator_count": c.creator_count,
        }
        for c in clusters
    ]

    # Commercial signals per cluster
    result = await session.execute(
        select(CommercialSignal, ProblemCluster.label)
        .join(ProblemCluster, CommercialSignal.problem_cluster_id == ProblemCluster.id)
        .order_by(ProblemCluster.label, CommercialSignal.confidence.desc())
    )
    data["signals"] = [
        {
            "cluster": row[1],
            "level": row[0].signal_level.value if hasattr(row[0].signal_level, "value") else str(row[0].signal_level),
            "confidence": round(float(row[0].confidence), 2),
        }
        for row in result.all()
    ]

    # Strongest signal per cluster
    strongest: dict[str, dict] = {}
    level_rank = {"VALIDATION": 4, "STRONG": 3, "MODERATE": 2, "WEAK": 1}
    for s in data["signals"]:
        existing = strongest.get(s["cluster"])
        if existing is None or level_rank.get(s["level"], 0) > level_rank.get(existing["level"], 0):
            strongest[s["cluster"]] = {"level": s["level"], "conf": s["confidence"]}
    data["strongest_signals"] = strongest

    # Opportunities with creator + cluster context
    result = await session.execute(
        select(OpportunityScore, Creator.name, Creator.status, ProblemCluster.label, ProblemCluster.description)
        .join(Creator, OpportunityScore.creator_id == Creator.id)
        .join(ProblemCluster, OpportunityScore.problem_cluster_id == ProblemCluster.id)
        .order_by(OpportunityScore.aggregate_score.desc())
    )
    data["opportunities"] = [
        {
            "creator": row[1],
            "status": row[2].value if hasattr(row[2], "value") else str(row[2]),
            "cluster": row[3],
            "cluster_desc": row[4],
            "score": round(float(row[0].aggregate_score), 2),
            "confidence": row[0].confidence_band.value if hasattr(row[0].confidence_band, "value") else str(row[0].confidence_band),
            "components": {k: round(float(v), 2) for k, v in row[0].component_scores.items()},
        }
        for row in result.all()
    ]

    # Problem observation categories
    result = await session.execute(
        select(ProblemObservation.category, func.count(ProblemObservation.id).label("cnt"))
        .group_by(ProblemObservation.category)
        .order_by(text("cnt DESC"))
    )
    data["obs_categories"] = [
        {"category": row[0], "count": row[1]} for row in result.all()
    ]

    # Evidence quotes
    result = await session.execute(
        select(Evidence.raw_text, Evidence.author_handle, Evidence.source_platform)
        .where(func.length(Evidence.raw_text) > 40)
        .order_by(func.random())
        .limit(30)
    )
    data["evidence_quotes"] = [
        {"text": row[0], "author": row[1], "platform": row[2]}
        for row in result.all()
    ]

    # Creators with scores
    result = await session.execute(
        select(
            Creator.name,
            Creator.status,
            CreatorPlatformAccount.handle,
            CreatorPlatformAccount.subscriber_count,
            CreatorScore.aggregate_score,
            CreatorScore.confidence_band,
        )
        .outerjoin(CreatorPlatformAccount, CreatorPlatformAccount.creator_id == Creator.id)
        .outerjoin(CreatorScore, CreatorScore.creator_id == Creator.id)
        .order_by(func.coalesce(CreatorScore.aggregate_score, 0).desc())
    )
    data["creators"] = [
        {
            "name": row[0],
            "status": row[1].value if hasattr(row[1], "value") else str(row[1]),
            "handle": row[2],
            "subscribers": row[3],
            "score": round(float(row[4]), 2) if row[4] is not None else None,
            "confidence": (row[5].value if hasattr(row[5], "value") else str(row[5])) if row[5] is not None else None,
        }
        for row in result.all()
    ]

    # Summary counts
    creator_count = await session.scalar(select(func.count(Creator.id)))
    evidence_count = await session.scalar(select(func.count(Evidence.id)))
    cluster_count = await session.scalar(select(func.count(ProblemCluster.id)))
    opp_count = await session.scalar(select(func.count(OpportunityScore.id)))
    obs_count = await session.scalar(select(func.count(ProblemObservation.id)))
    data["counts"] = {
        "creators": creator_count,
        "evidence": evidence_count,
        "clusters": cluster_count,
        "opportunities": opp_count,
        "observations": obs_count,
    }

    # Product ideas
    data["product_ideas"] = PRODUCT_IDEAS

    return data


DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CORP Research Console</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..700&family=Instrument+Serif&display=swap">
<style>
:root {
  --surface-page: #f2f3f6;
  --surface-card: #ffffff;
  --ink-primary: #111215;
  --ink-secondary: #5c5e66;
  --ink-muted: #898b94;
  --border: rgba(17,18,21,0.08);
  --border-strong: rgba(17,18,21,0.14);
  --cat-1: #2a78d6; --cat-2: #eb6834; --cat-3: #1baf7a;
  --cat-4: #eda100; --cat-5: #e87ba4; --cat-7: #4a3aa7;
  --status-good: #0ca30c; --status-good-text: #006300;
  --font-body: 'DM Sans', system-ui, -apple-system, sans-serif;
  --font-display: 'Instrument Serif', Georgia, serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-page: #111215; --surface-card: #1c1d21;
    --ink-primary: #f0f1f3; --ink-secondary: #9a9ca6; --ink-muted: #6b6d77;
    --border: rgba(240,241,243,0.08); --border-strong: rgba(240,241,243,0.14);
    --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70;
    --cat-4: #c98500; --cat-5: #d55181; --cat-7: #9085e9;
    --status-good-text: #0ca30c;
  }
}
:root[data-theme="dark"] {
  --surface-page: #111215; --surface-card: #1c1d21;
  --ink-primary: #f0f1f3; --ink-secondary: #9a9ca6; --ink-muted: #6b6d77;
  --border: rgba(240,241,243,0.08); --border-strong: rgba(240,241,243,0.14);
  --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70;
  --cat-4: #c98500; --cat-5: #d55181; --cat-7: #9085e9;
  --status-good-text: #0ca30c;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:var(--font-body); background:var(--surface-page); color:var(--ink-primary); padding:24px 24px 48px; line-height:1.5; }
.header { margin-bottom:28px; }
.header h1 { font-family:var(--font-display); font-size:28px; font-weight:400; letter-spacing:-0.01em; margin-bottom:4px; }
.header .sub { color:var(--ink-muted); font-size:13px; }
.counts-row { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:28px; }
.count-chip { background:var(--surface-card); border:1px solid var(--border); border-radius:8px; padding:8px 14px; font-size:13px; }
.count-chip strong { font-size:18px; display:block; font-variant-numeric:tabular-nums; }
.section-label { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--ink-muted); margin-bottom:12px; }
.opp-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:16px; margin-bottom:36px; }
.opp-card { background:var(--surface-card); border:1px solid var(--border); border-radius:10px; padding:20px; display:flex; flex-direction:column; gap:12px; }
.opp-card.top-pick { border-color:var(--cat-1); border-width:2px; position:relative; }
.opp-card.top-pick::before { content:'Top opportunity'; position:absolute; top:-9px; left:16px; background:var(--cat-1); color:#fff; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; padding:1px 8px; border-radius:4px; }
.opp-rank { font-size:12px; font-weight:600; color:var(--ink-muted); }
.opp-title { font-size:17px; font-weight:600; line-height:1.3; }
.opp-desc { font-size:13px; color:var(--ink-secondary); line-height:1.5; }
.opp-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:auto; }
.opp-tag { font-size:11px; padding:3px 8px; border-radius:5px; background:var(--border); color:var(--ink-secondary); white-space:nowrap; }
.opp-tag.score { background:var(--cat-1); color:#fff; font-weight:600; }
.opp-tag.signal-VALIDATION, .opp-tag.signal-STRONG { background:rgba(12,163,12,0.12); color:var(--status-good-text); }
.opp-tag.signal-MODERATE { background:rgba(250,178,25,0.12); color:#8a6300; }
.opp-tag.signal-WEAK { background:var(--border); color:var(--ink-muted); }
.score-bars { display:flex; flex-direction:column; gap:4px; }
.score-row { display:flex; align-items:center; gap:8px; font-size:11px; }
.score-row .lbl { width:110px; text-align:right; color:var(--ink-muted); flex-shrink:0; }
.score-row .bar-track { flex:1; height:6px; background:var(--border); border-radius:3px; overflow:hidden; }
.score-row .bar-fill { height:100%; border-radius:3px; background:var(--cat-1); }
.score-row .val { width:32px; font-variant-numeric:tabular-nums; color:var(--ink-secondary); }
.quotes-section { margin-bottom:36px; }
.quotes-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px; }
.quote-card { background:var(--surface-card); border:1px solid var(--border); border-radius:8px; padding:14px 16px; }
.quote-text { font-size:13px; color:var(--ink-primary); line-height:1.55; margin-bottom:8px; font-style:italic; }
.quote-author { font-size:11px; color:var(--ink-muted); }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:36px; }
@media (max-width:700px) { .two-col { grid-template-columns:1fr; } .opp-grid { grid-template-columns:1fr; } }
.panel { background:var(--surface-card); border:1px solid var(--border); border-radius:10px; padding:20px; }
.panel h3 { font-size:14px; font-weight:600; margin-bottom:16px; }
.hbar-list { display:flex; flex-direction:column; gap:10px; }
.hbar-item { display:flex; align-items:center; gap:10px; }
.hbar-label { width:130px; font-size:12px; text-align:right; color:var(--ink-secondary); flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hbar-track { flex:1; height:14px; background:var(--border); border-radius:4px; overflow:hidden; }
.hbar-fill { height:100%; border-radius:4px; }
.hbar-val { width:28px; font-size:12px; font-variant-numeric:tabular-nums; color:var(--ink-muted); }
.match-table { width:100%; border-collapse:collapse; font-size:13px; }
.match-table th { text-align:left; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; color:var(--ink-muted); padding:0 8px 8px; border-bottom:1px solid var(--border-strong); }
.match-table td { padding:8px; border-bottom:1px solid var(--border); }
.match-table tr:last-child td { border-bottom:none; }
.conf-HIGH { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; background:rgba(12,163,12,0.12); color:var(--status-good-text); }
.conf-MEDIUM { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; background:rgba(250,178,25,0.12); color:#8a6300; }
.conf-LOW { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; background:var(--border); color:var(--ink-muted); }
</style>
</head>
<body>

<div class="header">
  <h1>Creator Opportunity Research</h1>
  <div class="sub">What digital products are audiences asking for? &mdash; Live from database</div>
</div>

<div class="counts-row" id="counts-row"></div>

<div class="section-label">Top product opportunities &mdash; what to build</div>
<div class="opp-grid" id="opp-grid"></div>

<div class="quotes-section">
  <div class="section-label">Audience voice &mdash; actual comments showing demand</div>
  <div class="quotes-grid" id="quotes-grid"></div>
</div>

<div class="two-col">
  <div class="panel">
    <h3>What people complain about most</h3>
    <div class="hbar-list" id="pain-bars"></div>
  </div>
  <div class="panel">
    <h3>Problem clusters &mdash; evidence strength</h3>
    <div class="hbar-list" id="cluster-bars"></div>
  </div>
</div>

<div class="panel" style="margin-bottom:36px">
  <h3 id="opp-table-title">All creator &times; problem matches</h3>
  <div style="overflow-x:auto">
    <table class="match-table" id="match-table">
      <thead><tr>
        <th>Creator</th><th>Problem / product opportunity</th>
        <th style="text-align:right">Score</th><th>Confidence</th><th>Strongest dimension</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="panel">
  <h3 id="creator-table-title">Creators analyzed</h3>
  <div style="overflow-x:auto">
    <table class="match-table" id="creator-table">
      <thead><tr>
        <th>Creator</th><th>Handle</th><th>Subscribers</th><th>Status</th><th style="text-align:right">Score</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

// Counts row
(function() {
  const row = document.getElementById('counts-row');
  const labels = {creators:'Creators analyzed',evidence:'Evidence records',clusters:'Problem clusters',opportunities:'Opportunities scored',observations:'Pain points extracted'};
  for (const [k,label] of Object.entries(labels)) {
    const chip = document.createElement('div');
    chip.className = 'count-chip';
    chip.innerHTML = '<strong>' + (DATA.counts[k]||0) + '</strong>' + label;
    row.appendChild(chip);
  }
})();

// Opportunity cards
(function() {
  const grid = document.getElementById('opp-grid');
  const seen = new Set();
  const unique = [];
  for (const o of DATA.opportunities) {
    if (!seen.has(o.cluster)) {
      seen.add(o.cluster);
      const all = DATA.opportunities.filter(x => x.cluster === o.cluster);
      unique.push({...o, matchCount: all.length});
    }
  }
  unique.sort((a,b) => b.score - a.score);
  const compLabels = {problem_severity:'Problem severity',market_size:'Market size',creator_fit:'Creator fit',commercial_viability:'Viability',competitive_gap:'Competitive gap'};

  unique.slice(0,6).forEach((opp,i) => {
    const signal = DATA.strongest_signals[opp.cluster] || {level:'WEAK'};
    const card = document.createElement('div');
    card.className = 'opp-card' + (i===0?' top-pick':'');
    let bars = '';
    for (const [k,v] of Object.entries(opp.components).sort((a,b)=>b[1]-a[1])) {
      bars += '<div class="score-row"><span class="lbl">'+(compLabels[k]||k)+'</span><div class="bar-track"><div class="bar-fill" style="width:'+Math.round(v*100)+'%"></div></div><span class="val">'+Math.round(v*100)+'</span></div>';
    }
    const idea = DATA.product_ideas[opp.cluster] || '';
    const freq = (DATA.clusters.find(c=>c.label===opp.cluster)||{}).frequency||0;
    card.innerHTML = '<div class="opp-rank">#'+(i+1)+'</div>'
      +'<div class="opp-title">'+esc(opp.cluster)+'</div>'
      +'<div class="opp-desc">'+esc(opp.cluster_desc)+'</div>'
      +(idea?'<div class="opp-desc" style="color:var(--ink-primary);font-weight:500">Product idea: '+esc(idea)+'</div>':'')
      +'<div class="score-bars">'+bars+'</div>'
      +'<div class="opp-meta">'
        +'<span class="opp-tag score">Score '+Math.round(opp.score*100)+'/100</span>'
        +'<span class="opp-tag signal-'+signal.level+'">'+signal.level+' demand</span>'
        +'<span class="opp-tag">'+opp.matchCount+' creator match'+(opp.matchCount>1?'es':'')+'</span>'
        +'<span class="opp-tag">'+freq+' observations</span>'
      +'</div>';
    grid.appendChild(card);
  });
})();

// Quotes
(function() {
  const grid = document.getElementById('quotes-grid');
  const strong = DATA.evidence_quotes.filter(q =>
    /pay|bottleneck|problem|struggling|wish|need|alternative|pain/i.test(q.text)
  ).slice(0,8);
  if (!strong.length) strong.push(...DATA.evidence_quotes.slice(0,4));
  for (const q of strong) {
    const card = document.createElement('div');
    card.className = 'quote-card';
    const t = document.createElement('div'); t.className = 'quote-text'; t.textContent = '\\u201c'+q.text+'\\u201d';
    const a = document.createElement('div'); a.className = 'quote-author'; a.textContent = q.author+' \\u00b7 '+q.platform;
    card.appendChild(t); card.appendChild(a);
    grid.appendChild(card);
  }
})();

// Pain bars
(function() {
  const el = document.getElementById('pain-bars');
  const max = DATA.obs_categories[0]?.count || 1;
  const colors = ['var(--cat-1)','var(--cat-2)','var(--cat-3)','var(--cat-4)','var(--cat-5)','var(--cat-7)'];
  const labels = {product_need:'Product need',workflow_pain:'Workflow pain',service_gap:'Service gap',price_sensitivity:'Price sensitivity',commercial_intent:'Commercial intent',education_demand:'Education demand'};
  DATA.obs_categories.forEach((c,i) => {
    const d = document.createElement('div'); d.className = 'hbar-item';
    d.innerHTML = '<span class="hbar-label">'+esc(labels[c.category]||c.category)+'</span><div class="hbar-track"><div class="hbar-fill" style="width:'+Math.round(c.count/max*100)+'%;background:'+colors[i%colors.length]+'"></div></div><span class="hbar-val">'+c.count+'</span>';
    el.appendChild(d);
  });
})();

// Cluster bars
(function() {
  const el = document.getElementById('cluster-bars');
  DATA.clusters.forEach(c => {
    const s = Math.round(c.evidence_strength*100);
    const color = s>=75?'var(--status-good)':s>=50?'var(--cat-4)':'var(--ink-muted)';
    const short = c.label.length>20 ? c.label.substring(0,18)+'\\u2026' : c.label;
    const d = document.createElement('div'); d.className = 'hbar-item';
    d.innerHTML = '<span class="hbar-label" title="'+esc(c.label)+'">'+esc(short)+'</span><div class="hbar-track"><div class="hbar-fill" style="width:'+s+'%;background:'+color+'"></div></div><span class="hbar-val">'+s+'%</span>';
    el.appendChild(d);
  });
})();

// Match table
(function() {
  document.getElementById('opp-table-title').textContent = 'All creator \\u00d7 problem matches ('+DATA.opportunities.length+' scored opportunities)';
  const tbody = document.querySelector('#match-table tbody');
  const cl = {problem_severity:'Severity',market_size:'Market',creator_fit:'Fit',commercial_viability:'Viability',competitive_gap:'Gap'};
  for (const o of DATA.opportunities) {
    const best = Object.entries(o.components).sort((a,b)=>b[1]-a[1])[0];
    const tr = document.createElement('tr');
    tr.innerHTML = '<td style="font-weight:600">'+esc(o.creator)+'</td><td>'+esc(o.cluster)+'</td><td style="text-align:right;font-variant-numeric:tabular-nums;font-weight:600">'+Math.round(o.score*100)+'</td><td><span class="conf-'+o.confidence+'">'+o.confidence+'</span></td><td style="font-size:12px;color:var(--ink-secondary)">'+(cl[best[0]]||best[0])+' ('+Math.round(best[1]*100)+')</td>';
    tbody.appendChild(tr);
  }
})();

// Creator table
(function() {
  document.getElementById('creator-table-title').textContent = 'Creators analyzed ('+DATA.creators.length+')';
  const tbody = document.querySelector('#creator-table tbody');
  const sl = {DISCOVERED:'Discovered',COLLECTED:'Data collected',SCORED:'Scored',RESEARCH_COMPLETE:'Research done',HUMAN_REVIEW:'Needs review',APPROVED:'Approved'};
  for (const c of DATA.creators) {
    const subs = c.subscribers ? (c.subscribers>=1e6?(c.subscribers/1e6).toFixed(1)+'M':(c.subscribers/1e3).toFixed(0)+'K') : '\\u2014';
    const tr = document.createElement('tr');
    tr.innerHTML = '<td style="font-weight:600">'+esc(c.name)+'</td><td style="color:var(--ink-muted);font-size:12px">'+esc(c.handle||'')+'</td><td style="font-variant-numeric:tabular-nums">'+subs+'</td><td style="font-size:12px;color:var(--ink-secondary)">'+(sl[c.status]||c.status)+'</td><td style="text-align:right;font-variant-numeric:tabular-nums;font-weight:600">'+(c.score!=null?Math.round(c.score*100):'\\u2014')+'</td>';
    tbody.appendChild(tr);
  }
})();

function esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
</script>
</body>
</html>
"""


@dashboard_router.get("/dashboard", response_class=Response)
async def serve_dashboard(session: AsyncSession = Depends(get_session)):
    data = await _gather_dashboard_data(session)
    html = DASHBOARD_HTML.replace("__DATA_PLACEHOLDER__", json.dumps(data))
    return Response(content=html, media_type="text/html")


@dashboard_router.get("/api/dashboard-data")
async def dashboard_data(session: AsyncSession = Depends(get_session)):
    return await _gather_dashboard_data(session)
