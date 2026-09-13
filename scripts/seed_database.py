"""Seed the CORP database with realistic sample data across all 13 tables."""

import asyncio
import hashlib
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from corp.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def uid() -> str:
    return str(uuid.uuid4())


def now_minus(days: int = 0, hours: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


CREATORS = [
    {
        "name": "MKBHD",
        "niche": "technology",
        "discovery_source": "manual",
        "status": "SCORED",
        "handle": "@mkbhd",
        "external_id": "UCBcRF18a7Qf58cCRy5xuWwQ",
        "subscriber_count": 19_400_000,
    },
    {
        "name": "Ali Abdaal",
        "niche": "productivity",
        "discovery_source": "manual",
        "status": "RESEARCH_COMPLETE",
        "handle": "@aliabdaal",
        "external_id": "UCoOae5nYA7VqaXzerajD0lg",
        "subscriber_count": 5_600_000,
    },
    {
        "name": "Linus Tech Tips",
        "niche": "technology",
        "discovery_source": "manual",
        "status": "APPROVED",
        "handle": "@LinusTechTips",
        "external_id": "UCXuqSBlHAE6Xw-yeJA0Tunw",
        "subscriber_count": 16_200_000,
    },
    {
        "name": "Matt D'Avella",
        "niche": "lifestyle/minimalism",
        "discovery_source": "referral",
        "status": "SCORED",
        "handle": "@MattDAvella",
        "external_id": "UCJ24N4O0bP7LGt_qBwk1JRw",
        "subscriber_count": 3_800_000,
    },
    {
        "name": "Thomas Frank",
        "niche": "productivity",
        "discovery_source": "manual",
        "status": "HUMAN_REVIEW",
        "handle": "@Thomasfrank",
        "external_id": "UCG-KntY7aVnIGXYEBQvmBAQ",
        "subscriber_count": 2_900_000,
    },
    {
        "name": "Fireship",
        "niche": "programming",
        "discovery_source": "manual",
        "status": "COLLECTED",
        "handle": "@Fireship",
        "external_id": "UCsBjURrPoezykLs9EqgamOA",
        "subscriber_count": 3_400_000,
    },
    {
        "name": "Peter McKinnon",
        "niche": "photography/filmmaking",
        "discovery_source": "referral",
        "status": "RESEARCH_COMPLETE",
        "handle": "@paboromancykinnonpost",
        "external_id": "UC3DkFux8Iv3GtrIEP8NYXHQ",
        "subscriber_count": 5_900_000,
    },
    {
        "name": "Marques Brownlee Shorts",
        "niche": "technology",
        "discovery_source": "algorithm",
        "status": "DISCOVERED",
        "handle": "@mkbhdshorts",
        "external_id": "UCKfkNSaGVOBlGzqJPQs2Wuw",
        "subscriber_count": 450_000,
    },
]

VIDEOS_PER_CREATOR = [
    [
        ("The BEST Smartphone of 2024!", 8_200_000, 320_000, 14_500),
        ("I Tested Every Major AI Assistant", 5_100_000, 210_000, 11_200),
        ("Galaxy S24 Ultra Review — 3 Months Later", 6_400_000, 275_000, 9_800),
        ("Why I Switched to iPhone", 12_300_000, 480_000, 32_100),
        ("The Problem With Tech Reviews", 3_700_000, 195_000, 8_900),
    ],
    [
        ("My Honest Advice to Someone Who Wants to Be Rich", 4_300_000, 180_000, 7_600),
        ("I Tried Every Productivity System", 2_800_000, 120_000, 5_400),
        ("How I Built 7 Streams of Income", 6_100_000, 250_000, 12_300),
        ("The Anti-Productivity Manifesto", 1_900_000, 95_000, 4_200),
        ("Tools I Use Every Day as a Creator", 1_500_000, 78_000, 3_100),
    ],
    [
        ("We Built a $200,000 PC", 9_800_000, 410_000, 18_700),
        ("I Bought the World's Most Expensive GPU", 7_200_000, 340_000, 15_200),
        ("Honest Review: Framework Laptop 16", 3_400_000, 180_000, 9_100),
        ("Why Everyone is Switching to Linux", 5_600_000, 265_000, 12_800),
        ("The Worst Tech Fails of 2024", 4_100_000, 220_000, 10_400),
    ],
    [
        ("I Tried Minimalism for 30 Days", 3_200_000, 140_000, 6_200),
        ("Why I Quit Social Media for a Year", 5_800_000, 230_000, 11_400),
        ("The One Habit That Changed My Life", 2_400_000, 105_000, 4_800),
        ("How to Actually Be Productive", 1_800_000, 82_000, 3_600),
    ],
    [
        ("The Ultimate Notion Setup for Students", 4_700_000, 190_000, 8_900),
        ("How I Plan My Entire Life in Notion", 3_100_000, 135_000, 6_200),
        ("10 Notion Templates You Need", 2_200_000, 95_000, 4_100),
        ("My Complete Study System", 5_300_000, 215_000, 9_700),
    ],
    [
        ("God-Tier Developer Roadmap", 3_900_000, 175_000, 7_800),
        ("Every Programming Language Explained in 15 Minutes", 6_200_000, 290_000, 13_100),
        ("10 Coding Principles Every Developer Should Know", 2_100_000, 98_000, 4_500),
    ],
    [
        ("Cinematic B-Roll Tutorial", 4_100_000, 195_000, 8_200),
        ("How I Edit My YouTube Videos", 2_800_000, 130_000, 5_600),
        ("Camera Settings You're Getting Wrong", 3_500_000, 160_000, 7_100),
        ("The SECRET to Amazing Photos", 2_200_000, 105_000, 4_400),
    ],
    [
        ("iPhone vs Android in 60 Seconds", 850_000, 42_000, 1_900),
    ],
]

COMMENT_TEMPLATES = [
    {
        "text": "I've been struggling with {topic} for months. Any recommendations for a better solution?",
        "type": "question",
        "category": "product_need",
    },
    {
        "text": "This is exactly the problem I face at work every day. We need a tool that handles {topic} automatically.",
        "type": "comment",
        "category": "workflow_pain",
    },
    {
        "text": "Great video! But I wish there was a service that could do {topic} without all the manual setup.",
        "type": "comment",
        "category": "service_gap",
    },
    {
        "text": "I switched from {old} to {new} and it completely changed my workflow. Highly recommend!",
        "type": "comment",
        "category": "product_switch",
    },
    {
        "text": "Would love a course on this. I'd pay good money to learn {topic} properly.",
        "type": "comment",
        "category": "education_demand",
    },
    {
        "text": "Does anyone know a free alternative? The pricing on these tools is getting ridiculous.",
        "type": "question",
        "category": "price_sensitivity",
    },
    {
        "text": "I run a small business and {topic} is our biggest bottleneck. Would happily pay for a solution.",
        "type": "comment",
        "category": "commercial_intent",
    },
    {
        "text": "This is misleading. You didn't mention the {issue} problem which makes this unusable for professionals.",
        "type": "comment",
        "category": "expert_critique",
    },
    {
        "text": "I've been waiting for someone to make a video about this. The {topic} ecosystem is so confusing.",
        "type": "comment",
        "category": "information_need",
    },
    {
        "text": "Can you do a follow-up comparing {topic} for enterprise vs personal use?",
        "type": "question",
        "category": "segment_request",
    },
    {
        "text": "As a {role}, I can confirm this is the #1 pain point in our industry right now.",
        "type": "comment",
        "category": "industry_validation",
    },
    {
        "text": "I built something similar at my company. Happy to chat about what worked and what didn't.",
        "type": "comment",
        "category": "builder_signal",
    },
]

TOPICS_BY_NICHE = {
    "technology": ["smartphones", "AI assistants", "battery life", "camera quality", "software updates", "ecosystem lock-in", "repairability"],
    "productivity": ["time management", "note-taking", "habit tracking", "automation", "digital minimalism", "second brain"],
    "programming": ["web frameworks", "DevOps", "system design", "coding interviews", "open source", "AI coding tools"],
    "photography/filmmaking": ["color grading", "camera gear", "lighting", "video editing", "content workflow"],
    "lifestyle/minimalism": ["decluttering", "intentional living", "digital detox", "mindfulness", "sustainable habits"],
}

CLUSTER_LABELS = [
    ("Tool fatigue and decision paralysis", "Users overwhelmed by too many options in the productivity tool space"),
    ("Pricing frustration with SaaS subscriptions", "Recurring complaints about rising costs of software subscriptions"),
    ("Need for all-in-one workflow solution", "Desire for a single tool that replaces multiple point solutions"),
    ("AI integration gaps in existing tools", "Tools lack meaningful AI features despite marketing claims"),
    ("Learning curve barriers", "New users struggle with complex setups and steep learning curves"),
    ("Data portability and vendor lock-in", "Concerns about being trapped in ecosystems with no export options"),
    ("Mobile experience deficiencies", "Desktop-first tools provide poor mobile/tablet experiences"),
    ("Collaboration pain points", "Teams struggle with real-time collaboration in current tools"),
    ("Content creation workflow bottlenecks", "Creators spend too much time on repetitive production tasks"),
    ("Privacy and data ownership concerns", "Users want control over their data without cloud dependencies"),
]


AUTHOR_HANDLES = [
    "@techenthusiast42", "@productivitynerd", "@devjane", "@studiomike",
    "@minimallife", "@codecraft", "@pixelpower", "@datadiva",
    "@startupfounder", "@freelancer_pro", "@educator_sam", "@creativestudio",
    "@remoteworker", "@airesearcher", "@designthink", "@contentcreator99",
    "@businessowner_j", "@student_dev", "@marketing_guru", "@sysadmin_k",
]


async def seed(session: AsyncSession) -> None:
    creator_ids: list[str] = []
    content_item_ids: list[list[str]] = []
    evidence_ids: list[str] = []
    observation_ids: list[str] = []
    cluster_ids: list[str] = []
    research_run_ids: list[str] = []

    # ── Creators + Platform Accounts ────────────────────────────────
    print("Seeding creators...")
    for c in CREATORS:
        cid = uid()
        creator_ids.append(cid)
        await session.execute(
            text("""
                INSERT INTO creators (id, name, niche, discovery_source, status, created_at, updated_at)
                VALUES (:id, :name, :niche, :ds, :status, :ca, :ua)
            """),
            {
                "id": cid, "name": c["name"], "niche": c["niche"],
                "ds": c["discovery_source"], "status": c["status"],
                "ca": now_minus(days=random.randint(30, 90)),
                "ua": now_minus(days=random.randint(0, 5)),
            },
        )
        paid = uid()
        await session.execute(
            text("""
                INSERT INTO creator_platform_accounts
                (id, creator_id, platform, handle, external_id, subscriber_count, verified, created_at, updated_at)
                VALUES (:id, :cid, 'youtube', :handle, :eid, :subs, true, :ca, :ua)
            """),
            {
                "id": paid, "cid": cid, "handle": c["handle"],
                "eid": c["external_id"], "subs": c["subscriber_count"],
                "ca": now_minus(days=random.randint(30, 90)),
                "ua": now_minus(days=random.randint(0, 5)),
            },
        )
    print(f"  {len(CREATORS)} creators created")

    # ── Research Runs ───────────────────────────────────────────────
    print("Seeding research runs...")
    for i, cid in enumerate(creator_ids):
        for phase in ["acquisition", "intelligence", "scoring"]:
            rrid = uid()
            research_run_ids.append(rrid)
            await session.execute(
                text("""
                    INSERT INTO research_runs
                    (id, creator_id, status, started_at, completed_at, config_snapshot, prompt_versions, model_versions, created_at, updated_at)
                    VALUES (:id, :cid, :status, :sa, :ca, :cs, :pv, :mv, :cra, :ua)
                """),
                {
                    "id": rrid, "cid": cid,
                    "status": "completed" if CREATORS[i]["status"] != "DISCOVERED" else "pending",
                    "sa": now_minus(days=random.randint(10, 30)),
                    "ca": now_minus(days=random.randint(5, 10)),
                    "cs": json.dumps({"pipeline": phase, "adapter": "youtube"}),
                    "pv": json.dumps({"extraction": "v1.0", "topics": "v1.0"}),
                    "mv": json.dumps({"primary": "gemini-1.5-flash"}),
                    "cra": now_minus(days=random.randint(10, 30)),
                    "ua": now_minus(days=random.randint(5, 10)),
                },
            )
    print(f"  {len(research_run_ids)} research runs created")

    # ── Content Items ───────────────────────────────────────────────
    print("Seeding content items...")
    total_content = 0
    for i, cid in enumerate(creator_ids):
        creator_content_ids = []
        videos = VIDEOS_PER_CREATOR[i] if i < len(VIDEOS_PER_CREATOR) else []
        niche = CREATORS[i]["niche"].split("/")[0]
        topics = TOPICS_BY_NICHE.get(niche, TOPICS_BY_NICHE["technology"])

        for j, (title, views, likes, comments) in enumerate(videos):
            ciid = uid()
            creator_content_ids.append(ciid)
            ext_id = f"yt_{uid()[:11]}"
            pub_date = now_minus(days=random.randint(7, 180))
            await session.execute(
                text("""
                    INSERT INTO content_items
                    (id, creator_id, platform, external_id, title, description, content_type,
                     published_at, view_count, like_count, comment_count, url, topics, created_at, updated_at)
                    VALUES (:id, :cid, 'youtube', :eid, :title, :desc, 'VIDEO',
                            :pub, :views, :likes, :comments, :url, :topics, :ca, :ua)
                """),
                {
                    "id": ciid, "cid": cid, "eid": ext_id, "title": title,
                    "desc": f"In this video, we explore {title.lower()}...",
                    "pub": pub_date, "views": views, "likes": likes,
                    "comments": comments,
                    "url": f"https://youtube.com/watch?v={ext_id}",
                    "topics": json.dumps(random.sample(topics, min(3, len(topics)))),
                    "ca": pub_date, "ua": pub_date,
                },
            )
            total_content += 1
        content_item_ids.append(creator_content_ids)
    print(f"  {total_content} content items created")

    # ── Audience Interactions + Evidence ─────────────────────────────
    print("Seeding interactions and evidence...")
    total_interactions = 0
    total_evidence = 0
    rr_idx = 0

    for i, cid in enumerate(creator_ids):
        ci_ids = content_item_ids[i]
        niche = CREATORS[i]["niche"].split("/")[0]
        topics = TOPICS_BY_NICHE.get(niche, TOPICS_BY_NICHE["technology"])

        for ci_id in ci_ids:
            num_comments = random.randint(8, 20)
            rr_id = research_run_ids[rr_idx % len(research_run_ids)]

            for _ in range(num_comments):
                template = random.choice(COMMENT_TEMPLATES)
                topic = random.choice(topics)
                comment_text = template["text"].format(
                    topic=topic,
                    old=random.choice(["Notion", "Evernote", "Trello", "Asana", "ClickUp"]),
                    new=random.choice(["Obsidian", "Logseq", "Capacities", "Craft", "Heptabase"]),
                    issue=random.choice(["latency", "privacy", "cost", "integration", "reliability"]),
                    role=random.choice(["developer", "designer", "manager", "freelancer", "student"]),
                )
                int_id = uid()
                ext_id = f"cmt_{uid()[:11]}"
                posted = now_minus(days=random.randint(1, 90))

                await session.execute(
                    text("""
                        INSERT INTO audience_interactions
                        (id, content_item_id, external_id, text, author_handle,
                         interaction_type, posted_at, like_count, created_at, updated_at)
                        VALUES (:id, :ciid, :eid, :txt, :author, :itype, :posted, :likes, :ca, :ua)
                    """),
                    {
                        "id": int_id, "ciid": ci_id, "eid": ext_id,
                        "txt": comment_text,
                        "author": random.choice(AUTHOR_HANDLES),
                        "itype": template["type"].upper(),
                        "posted": posted, "likes": random.randint(0, 500),
                        "ca": posted, "ua": posted,
                    },
                )
                total_interactions += 1

                eid = uid()
                evidence_ids.append(eid)
                await session.execute(
                    text("""
                        INSERT INTO evidence
                        (id, source_type, source_id, source_platform, raw_text,
                         author_handle, source_url, access_method, compliance_status,
                         collected_at, research_run_id)
                        VALUES (:id, :stype, :sid, 'youtube', :raw,
                                :author, :url, 'OFFICIAL', 'COMPLIANT',
                                :collected, :rrid)
                    """),
                    {
                        "id": eid, "stype": template["type"], "sid": ext_id,
                        "raw": comment_text,
                        "author": random.choice(AUTHOR_HANDLES),
                        "url": f"https://youtube.com/watch?v=x#comment={ext_id}",
                        "collected": posted, "rrid": rr_id,
                    },
                )
                total_evidence += 1

        rr_idx += 1

    print(f"  {total_interactions} interactions created")
    print(f"  {total_evidence} evidence rows created")

    # ── Problem Observations ────────────────────────────────────────
    print("Seeding problem observations...")
    total_obs = 0
    obs_per_evidence = min(len(evidence_ids), 300)
    sampled_evidence = random.sample(evidence_ids, obs_per_evidence)

    for eid in sampled_evidence:
        num_obs = random.randint(1, 3)
        for _ in range(num_obs):
            oid = uid()
            observation_ids.append(oid)
            category = random.choice([
                "product_need", "workflow_pain", "service_gap",
                "education_demand", "price_sensitivity", "commercial_intent",
            ])
            embedding = [random.gauss(0, 0.3) for _ in range(384)]
            await session.execute(
                text("""
                    INSERT INTO problem_observations
                    (id, evidence_id, text, category, is_inferred,
                     extraction_prompt_version, model_version, confidence, embedding,
                     created_at, updated_at)
                    VALUES (:id, :eid, :txt, :cat, :inferred,
                            'v1.0', 'gemini-1.5-flash', :conf, :emb,
                            :ca, :ua)
                """),
                {
                    "id": oid, "eid": eid,
                    "txt": f"Users express {category.replace('_', ' ')} related to current tooling gaps",
                    "cat": category, "inferred": random.choice([True, False]),
                    "conf": round(random.uniform(0.6, 0.98), 3),
                    "emb": str(embedding),
                    "ca": now_minus(days=random.randint(5, 20)),
                    "ua": now_minus(days=random.randint(0, 5)),
                },
            )
            total_obs += 1
    print(f"  {total_obs} problem observations created")

    # ── Problem Clusters + Members ──────────────────────────────────
    print("Seeding problem clusters...")
    for label, desc in CLUSTER_LABELS:
        pcid = uid()
        cluster_ids.append(pcid)
        freq = random.randint(5, 50)
        await session.execute(
            text("""
                INSERT INTO problem_clusters
                (id, label, description, frequency, recency_score,
                 evidence_strength, creator_count, model_version,
                 created_at, updated_at)
                VALUES (:id, :label, :desc, :freq, :recency,
                        :strength, :cc, 'gemini-1.5-flash',
                        :ca, :ua)
            """),
            {
                "id": pcid, "label": label, "desc": desc,
                "freq": freq, "recency": round(random.uniform(0.3, 0.95), 3),
                "strength": round(random.uniform(0.4, 0.9), 3),
                "cc": random.randint(1, len(CREATORS)),
                "ca": now_minus(days=random.randint(5, 15)),
                "ua": now_minus(days=random.randint(0, 5)),
            },
        )

    total_members = 0
    for pcid in cluster_ids:
        num_members = random.randint(5, min(20, len(observation_ids)))
        member_obs = random.sample(observation_ids, num_members)
        for oid in member_obs:
            mid = uid()
            await session.execute(
                text("""
                    INSERT INTO problem_cluster_members
                    (id, cluster_id, observation_id, similarity_score)
                    VALUES (:id, :cid, :oid, :sim)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": mid, "cid": pcid, "oid": oid,
                    "sim": round(random.uniform(0.65, 0.99), 4),
                },
            )
            total_members += 1
    print(f"  {len(CLUSTER_LABELS)} clusters, {total_members} memberships created")

    # ── Commercial Signals ──────────────────────────────────────────
    print("Seeding commercial signals...")
    total_signals = 0
    signal_evidence = random.sample(evidence_ids, min(len(evidence_ids), 80))
    for j, pcid in enumerate(cluster_ids):
        num_signals = random.randint(3, 8)
        for _ in range(num_signals):
            sid = uid()
            eid = random.choice(signal_evidence)
            level = random.choice(["WEAK", "MODERATE", "STRONG", "VALIDATION"])
            await session.execute(
                text("""
                    INSERT INTO commercial_signals
                    (id, problem_cluster_id, signal_level, evidence_id,
                     rationale, confidence, classification_model, prompt_version,
                     created_at, updated_at)
                    VALUES (:id, :pcid, :level, :eid,
                            :rat, :conf, 'gemini-1.5-flash', 'v1.0',
                            :ca, :ua)
                """),
                {
                    "id": sid, "pcid": pcid, "level": level, "eid": eid,
                    "rat": f"Audience signals indicate {level} commercial intent for this problem cluster",
                    "conf": round(random.uniform(0.5, 0.95), 3),
                    "ca": now_minus(days=random.randint(3, 10)),
                    "ua": now_minus(days=random.randint(0, 3)),
                },
            )
            total_signals += 1
    print(f"  {total_signals} commercial signals created")

    # ── Creator Scores ──────────────────────────────────────────────
    print("Seeding creator scores...")
    total_creator_scores = 0
    for i, cid in enumerate(creator_ids):
        if CREATORS[i]["status"] in ("DISCOVERED", "COLLECTING", "COLLECTED"):
            continue
        csid = uid()
        components = {
            "audience_size": round(random.uniform(0.5, 1.0), 3),
            "engagement_rate": round(random.uniform(0.3, 0.9), 3),
            "content_quality": round(random.uniform(0.4, 0.95), 3),
            "niche_authority": round(random.uniform(0.3, 0.85), 3),
            "growth_trajectory": round(random.uniform(0.2, 0.8), 3),
        }
        agg = round(sum(components.values()) / len(components), 3)
        comp_hash = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()
        band = "HIGH" if agg > 0.7 else "MEDIUM" if agg > 0.5 else "LOW"

        await session.execute(
            text("""
                INSERT INTO creator_scores
                (id, creator_id, component_scores, aggregate_score, computed_hash,
                 confidence_band, rule_version, model_version, research_run_id,
                 created_at, updated_at)
                VALUES (:id, :cid, :cs, :agg, :hash,
                        :band, 'v1.0', 'gemini-1.5-flash', :rrid,
                        :ca, :ua)
            """),
            {
                "id": csid, "cid": cid, "cs": json.dumps(components),
                "agg": agg, "hash": comp_hash, "band": band,
                "rrid": research_run_ids[i * 3] if i * 3 < len(research_run_ids) else None,
                "ca": now_minus(days=random.randint(3, 10)),
                "ua": now_minus(days=random.randint(0, 3)),
            },
        )
        total_creator_scores += 1
    print(f"  {total_creator_scores} creator scores created")

    # ── Opportunity Scores ──────────────────────────────────────────
    print("Seeding opportunity scores...")
    total_opp_scores = 0
    opp_score_ids = []
    for i, cid in enumerate(creator_ids):
        if CREATORS[i]["status"] in ("DISCOVERED", "COLLECTING", "COLLECTED", "EXTRACTING"):
            continue
        num_opps = random.randint(2, min(5, len(cluster_ids)))
        selected_clusters = random.sample(cluster_ids, num_opps)
        for pcid in selected_clusters:
            osid = uid()
            opp_score_ids.append((osid, cid))
            components = {
                "problem_severity": round(random.uniform(0.4, 0.95), 3),
                "market_size": round(random.uniform(0.3, 0.9), 3),
                "creator_fit": round(random.uniform(0.4, 0.85), 3),
                "commercial_viability": round(random.uniform(0.3, 0.8), 3),
                "competitive_gap": round(random.uniform(0.2, 0.7), 3),
            }
            agg = round(sum(components.values()) / len(components), 3)
            comp_hash = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()
            band = "HIGH" if agg > 0.7 else "MEDIUM" if agg > 0.5 else "LOW"

            await session.execute(
                text("""
                    INSERT INTO opportunity_scores
                    (id, creator_id, problem_cluster_id, component_scores,
                     aggregate_score, computed_hash, confidence_band,
                     rule_version, model_version, research_run_id,
                     created_at, updated_at)
                    VALUES (:id, :cid, :pcid, :cs,
                            :agg, :hash, :band,
                            'v1.0', 'gemini-1.5-flash', :rrid,
                            :ca, :ua)
                """),
                {
                    "id": osid, "cid": cid, "pcid": pcid,
                    "cs": json.dumps(components), "agg": agg,
                    "hash": comp_hash, "band": band,
                    "rrid": research_run_ids[i * 3 + 2] if i * 3 + 2 < len(research_run_ids) else None,
                    "ca": now_minus(days=random.randint(2, 8)),
                    "ua": now_minus(days=random.randint(0, 2)),
                },
            )
            total_opp_scores += 1
    print(f"  {total_opp_scores} opportunity scores created")

    # ── Human Decisions ─────────────────────────────────────────────
    print("Seeding human decisions...")
    total_decisions = 0
    for i, cid in enumerate(creator_ids):
        if CREATORS[i]["status"] not in ("APPROVED", "REJECTED", "WATCHING", "HUMAN_REVIEW"):
            continue
        decision_type = {
            "APPROVED": "APPROVE",
            "REJECTED": "REJECT",
            "WATCHING": "WATCH",
            "HUMAN_REVIEW": "WATCH",
        }[CREATORS[i]["status"]]

        matching_opps = [oid for oid, c in opp_score_ids if c == cid]
        opp_id = matching_opps[0] if matching_opps else None

        did = uid()
        await session.execute(
            text("""
                INSERT INTO human_decisions
                (id, creator_id, opportunity_score_id, decision, gate,
                 rationale, decided_at, decided_by)
                VALUES (:id, :cid, :osid, :dec, 'GATE_A',
                        :rat, :da, :db)
            """),
            {
                "id": did, "cid": cid, "osid": opp_id,
                "dec": decision_type,
                "rat": f"Creator shows {'strong' if decision_type == 'APPROVE' else 'moderate'} opportunity signals",
                "da": now_minus(days=random.randint(1, 5)),
                "db": "analyst@corp.example",
            },
        )
        total_decisions += 1
    print(f"  {total_decisions} human decisions created")

    await session.commit()
    print("\nDatabase seeded successfully!")


async def main() -> None:
    print("=" * 60)
    print("CORP Database Seeder")
    print("=" * 60)
    print(f"Database: {settings.database_url}")
    print()

    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM creators"))
        count = result.scalar()
        if count and count > 0:
            print(f"Database already has {count} creators. Clearing existing data...")
            await session.execute(text("DELETE FROM human_decisions"))
            await session.execute(text("DELETE FROM commercial_signals"))
            await session.execute(text("DELETE FROM opportunity_scores"))
            await session.execute(text("DELETE FROM creator_scores"))
            await session.execute(text("DELETE FROM problem_cluster_members"))
            await session.execute(text("DELETE FROM problem_clusters"))
            await session.execute(text("DELETE FROM problem_observations"))
            # Evidence is append-only with a trigger blocking deletes,
            # so we need to drop the trigger, delete, then recreate
            await session.execute(text(
                "DROP TRIGGER IF EXISTS evidence_immutable ON evidence"
            ))
            await session.execute(text("DELETE FROM evidence"))
            await session.execute(text("""
                CREATE OR REPLACE FUNCTION prevent_evidence_mutation()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'Evidence table is append-only: % not allowed', TG_OP;
                END;
                $$ LANGUAGE plpgsql;
            """))
            await session.execute(text("""
                CREATE TRIGGER evidence_immutable
                BEFORE UPDATE OR DELETE ON evidence
                FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation()
            """))
            await session.execute(text("DELETE FROM audience_interactions"))
            await session.execute(text("DELETE FROM content_items"))
            await session.execute(text("DELETE FROM research_runs"))
            await session.execute(text("DELETE FROM creator_platform_accounts"))
            await session.execute(text("DELETE FROM creators"))
            await session.commit()
            print("Cleared.\n")

        await seed(session)

    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    async with async_session() as session:
        tables = [
            "creators", "creator_platform_accounts", "content_items",
            "audience_interactions", "evidence", "research_runs",
            "problem_observations", "problem_clusters", "problem_cluster_members",
            "commercial_signals", "creator_scores", "opportunity_scores",
            "human_decisions",
        ]
        for t in tables:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {t}"))
            count = result.scalar()
            print(f"  {t:35s} {count:>6}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
