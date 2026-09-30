# Tech-Subset Precision Audit (re-run)

**Sample:** 50 postings drawn uniformly at random from the final index (`index/careerpilot.db`, 13,975 jobs):

```python
rows = conn.execute("SELECT job_id, title, company_name FROM jobs ORDER BY job_id").fetchall()
sample = random.Random(42).sample(rows, 50)   # seed 42 (the previous audit used 2026)
```

**Classification rule** (single annotator; ambiguous titles were checked against the posting description):
- **Tech:** the core of the job is software, web or mobile development; data, analytics or ML; IT infrastructure, networking, security or IT operations; or digital-hardware engineering (e.g. FPGA).
- **Non-tech:** other engineering disciplines (process/boilers, plant electrical and instrumentation, industrial machine controls, opto-mechanical, environmental), apparel, or other non-technical work.
- **Borderline:** industrial controls engineers whose job includes PLC/HMI programming. They are counted **non-tech** in the main number; the previous audit counted "Control Engineer" as tech, so the lenient number is also given.

| # | Job ID | Title | Company | Class | Reason |
|---|---|---|---|---|---|
| 1 | 3904399649 | NEO4J Database Administrator Level 3 | Flexton Inc. | Tech | Database administration |
| 2 | 3888957480 | Staff Systems Engineer (*Active Secret required) | Northrop Grumman | Tech | Systems engineering for defense IT/software systems |
| 3 | 3884853922 | Senior Front-End Engineer (remote) | myGwork | Tech | Front-end development |
| 4 | 3905293183 | Project Engineer | Cleaver-Brooks | Non-tech | Boiler process engineering (P&IDs, heat and mass flow) |
| 5 | 3899535180 | Data Analyst, Business Intelligence | HealthCare Partners | Tech | BI / data analysis |
| 6 | 3898165459 | iOS Developer | Vaspire Technologies | Tech | Mobile development |
| 7 | 3895546835 | Lead Ruby on Rails Engineer | Aha! | Tech | Web back-end development |
| 8 | 3890897274 | Control Engineer | Reliance One | Non-tech (borderline) | Electrical controls for material-handling machines; includes PLC/HMI programming |
| 9 | 3905281059 | The North Face: Technical Developer, Apparel (Global) | The North Face | Non-tech | Apparel technical design (patterns, garments) |
| 10 | 3888476608 | Sr Data Scientist | The Walt Disney Company | Tech | Data science |
| 11 | 3904922297 | Building Automation Controls Engineer | Bedrock Detroit | Non-tech (borderline) | Building control-system electronics; some control software |
| 12 | 3905291267 | Full Stack Engineer | Agility Partners | Tech | Full-stack development |
| 13 | 3903433286 | Corticon Developer | Mastech Digital | Tech | Business-rules software development |
| 14 | 3887835767 | Senior Software Engineer | Complete Staffing Solutions | Tech | Python data pipelines |
| 15 | 3903844065 | Software Engineer (Hybrid) | Blackhawk Network | Tech | Software engineering |
| 16 | 3901956533 | Appian Developer | Centraprise | Tech | Low-code platform development |
| 17 | 3884933608 | Software Implementation Consultant | PointClickCare | Tech | Configures and implements a software product |
| 18 | 3884922172 | Product System Engineer | Avo Photonics | Non-tech | Opto-electronic / opto-mechanical hardware |
| 19 | 3887909763 | Manager People Data & Analytics | AngloGold Ashanti | Tech | Data analytics (HR domain) |
| 20 | 3895527397 | Application Developer | Inceed | Tech | Application development |
| 21 | 3898156629 | Lead IT Asset Management Engineer (SAM) | DTCC | Tech | IT operations (software asset management) |
| 22 | 3902823365 | GCP Platform Engineer | Sun Technologies | Tech | Cloud platform engineering |
| 23 | 3903892170 | Principal Machine Learning Engineer (AI, NLP, LLM) | Palo Alto Networks | Tech | ML engineering |
| 24 | 3884860120 | Senior Front-End Engineer (remote) | myGwork | Tech | Front-end development (repost of #3) |
| 25 | 3903469911 | Engineer I | The Mosaic Company | Non-tech | Mining/chemical plant engineering |
| 26 | 3894890217 | ServiceNow Security & Data Protection Engineer | CVS Health | Tech | Security engineering on an IT platform |
| 27 | 3904995064 | Network Voice Engineer | Raas Infotek | Tech | Networking / VoIP |
| 28 | 3904501405 | Reliability I&E Engineer | OCI Global | Non-tech | Plant instrumentation and electrical reliability |
| 29 | 3904955094 | Sr. Engineer, IT Asset Management | ICE | Tech | IT operations |
| 30 | 3903431139 | Linux Engineer | SSi People | Tech | Systems administration |
| 31 | 3901952644 | Senior Application Development Engineer | Centene | Tech | Application development |
| 32 | 3895539838 | Senior Engineer - Solid Waste | SCS Engineers | Non-tech | Environmental / civil engineering |
| 33 | 3902340728 | Microsoft Dynamics CRM Developer | IQVIA | Tech | CRM software development |
| 34 | 3903842155 | Software Developer - Ruby on Rails | Hughes | Tech | Web development |
| 35 | 3899540634 | Senior Frontend Developer (React) | Sibitalent | Tech | Front-end development |
| 36 | 3905873982 | Principal Design Verification Engineer (FPGA) | Dice | Tech | Digital-hardware verification |
| 37 | 3884431576 | Senior Developer – React Native | Avesta Computer Services | Tech | Mobile development |
| 38 | 3905330491 | VP, Modelling Data Scientist | BlackRock | Tech | Data science |
| 39 | 3905866964 | Informatica MDM Developer | Talent Groups | Tech | Data integration development |
| 40 | 3891088945 | Principal Machine Learning Engineer | Teaching Strategies | Tech | ML engineering |
| 41 | 3904952291 | Controls Engineer | Dice (client: General Motors) | Non-tech (borderline) | Electrical controls for CNC/robots in manufacturing |
| 42 | 3901957260 | Back End Developer | Randstad Digital | Tech | Back-end development |
| 43 | 3901371319 | Lead Data Scientist | Trane Technologies | Tech | Data science |
| 44 | 3899540477 | Machine Learning Engineer | Cloud Resources | Tech | ML engineering |
| 45 | 3891077593 | Electronics Engineer / Computer Scientist | Air Force Civilian Service | Tech | Computer science and software problem resolution |
| 46 | 3895487867 | Workday Developer & Integrations Specialist | Lesley University | Tech | Enterprise software integration |
| 47 | 3905335626 | Power Platform Developer | WennSoft | Tech | Low-code development |
| 48 | 3901357157 | Web Developer | DataAnnotation | Tech | Coding work (AI training data) |
| 49 | 3888472990 | Data Management & Technology Expert (Sr Director/Analyst) | Gartner | Tech | Research analyst on data-management technology |
| 50 | 3887892624 | Lead Information Security Engineer | Wells Fargo | Tech | Information security |

## Result

| Count | Tech | Precision | 95% CI (Wilson) |
|---|---|---|---|
| **Main (borderline controls = non-tech)** | **41 / 50** | **82%** | about 69%–90% |
| Lenient (PLC controls = tech, as in the previous audit) | 44 / 50 | 88% | about 76%–94% |

**Errors:**
- **Six non-tech jobs in the sample:** plant/process engineering (#4, #25, #28), environmental (#32), photonics hardware (#18) and apparel (#9). They get in through title keywords like "engineer" combined with an ENG skill tag.
- **Three borderline:** industrial controls (#8, #11, #41).
- **One duplicate:** #3 and #24 are reposts of the same job.

The previous tool reported 94% (47/50, seed 2026). This independent sample gives 82% (88% lenient). The gap is not significant at the 5% level (two-proportion z ≈ 1.85, p ≈ 0.06), and the two audits had different annotators and borderline conventions. The honest estimate of subset precision is **roughly 80–90%, not 94%**.
