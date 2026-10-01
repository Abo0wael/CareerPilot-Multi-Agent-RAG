---
title: CareerPilot API
emoji: 🧭
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: cc-by-sa-4.0
short_description: Multi-agent job matching and verified CV tailoring (API)
---

# CareerPilot API

FastAPI backend of CareerPilot: a multi-agent assistant that matches a CV to real job
postings, reports matched and missing requirements, and tailors CV bullets that a
verifier agent checks claim by claim. All model calls go to the Groq API.

- `GET /health` liveness, `GET /docs` interactive API docs
- Source and documentation: see the project repository (docs/DEPLOY.md)

Job data: derived from *LinkedIn Job Postings (2023-2024)* by Arsh Koneru
([Kaggle](https://www.kaggle.com/datasets/arshkon/linkedin-job-postings)), CC BY-SA 4.0.
