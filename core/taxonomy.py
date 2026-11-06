"""Job families for every kind of job seeker: skills, role titles, title patterns and companies.

A family groups related roles (Software Engineering, Finance & Accounting, Nursing & Healthcare...).
Resumes are matched against every family, so the roles, levels, industries and searches a person gets
come from their own resume, not from a fixed list of analytics jobs.
"""
from __future__ import annotations

import re
from functools import lru_cache

# ------------------------------------------------------------------ skill vocabulary added on top of core.skills
# canonical -> aliases. Plain phrases match as whole words; a "re:" prefix means a raw regex.
FAMILY_SKILLS: dict[str, str] = {
    # software
    "Java": r"re:\bjava\b(?!\s*script)", "JavaScript": "javascript|js|es6|ecmascript", "TypeScript": "typescript",
    "React": r"re:(?-i:\bReact\b)|\breact\.?js\b|\breact native\b", "Angular": "angular|angularjs", "Vue.js": "vue|vue.js|vuejs",
    "Node.js": "node.js|nodejs|node js|express.js|expressjs", "Django": "django", "Flask": "flask",
    "Spring Boot": "spring boot|springboot|spring framework|spring mvc", "Go": r"re:\bgolang\b|\bgo (?:lang|language)\b",
    "C++": r"re:(?<![\w+#])c\+\+(?![\w+#])|\bcpp\b", "C#": r"re:(?<![\w#])c#(?![\w#])|\bc sharp\b",
    ".NET": r"re:(?<![\w])\.net\b|\basp\.net\b|\bdotnet\b", "PHP": "php|laravel|codeigniter", "Ruby": "ruby|ruby on rails",
    "Kotlin": "kotlin", "Swift": r"re:(?-i:\bSwift\b)|\bswiftui\b", "Android": "android", "iOS": r"re:\bios\b(?! ?\d)", "Flutter": "flutter|dart",
    "HTML/CSS": "html|html5|css|css3|sass|tailwind|bootstrap", "REST APIs": "rest api|restful|rest apis|api development|graphql",
    "Microservices": "microservices|micro-services", "System Design": "system design|distributed systems|scalable systems",
    "Data Structures & Algorithms": "data structures|algorithms|dsa", "Docker": "docker|containeri[sz]ation", "Kubernetes": "kubernetes|k8s|eks|aks|gke",
    "Terraform": "terraform|infrastructure as code|iac|cloudformation", "CI/CD": "ci/cd|ci cd|continuous integration|jenkins|github actions|gitlab ci",
    "Linux": "linux|unix|shell scripting|bash", "Ansible": "ansible|chef|puppet", "Monitoring": "prometheus|grafana|datadog|new relic|splunk|elk",
    "Networking": "networking|tcp/ip|dns|routing|switching|ccna|firewall|vpn", "Cybersecurity": "cybersecurity|cyber security|information security|vapt|siem|soc|penetration testing|iso 27001",
    "ITIL": "itil|incident management|change management|service now|servicenow", "Active Directory": "active directory|windows server|office 365|intune",
    "Kafka": "kafka|rabbitmq|pub/sub", "NoSQL": "nosql|cassandra|dynamodb|redis|elasticsearch", "PostgreSQL": "postgresql|postgres|oracle db|mysql",
    "Deep Learning": "deep learning|neural networks?|cnn|rnn|transformers", "TensorFlow / PyTorch": "tensorflow|pytorch|keras",
    "Computer Vision": "computer vision|opencv|image processing|object detection", "MLOps": "mlops|model deployment|mlflow|kubeflow|sagemaker|vertex ai",
    # QA
    "Selenium": "selenium|webdriver", "Cypress / Playwright": "cypress|playwright|puppeteer", "Manual Testing": "manual testing|test cases|test scenarios|regression testing|smoke testing|uat",
    "Test Automation": "test automation|automation testing|automation framework|testng|junit|pytest|bdd|cucumber",
    "API Testing": "api testing|postman|rest assured|soapui", "Performance Testing": "performance testing|jmeter|loadrunner|load testing",
    "Appium": "appium|mobile testing", "Bug Tracking": "bug tracking|defect tracking|bugzilla|defect management",
    # product & design
    "Product Roadmap": "product roadmap|roadmaps?|product strategy|product vision", "PRDs": "prds?|product requirements|product specs?",
    "User Research": "user research|user interviews|customer interviews|usability research|personas?", "Prioritization": "prioriti[sz]ation|backlog grooming|backlog management",
    "Figma": "figma|figjam", "Adobe XD / Sketch": "adobe xd|sketch app|invision", "Photoshop": "photoshop", "Illustrator": "illustrator",
    "InDesign": "indesign", "After Effects": "after effects", "Premiere Pro": "premiere pro|final cut|davinci resolve",
    "Wireframing & Prototyping": "wireframes?|wireframing|prototyp(?:e|es|ing)|mockups?|user flows?", "Design Systems": "design systems?|component library|style guides?",
    "Usability Testing": "usability testing|user testing|heuristic evaluation", "Typography": "typography|layout design|colou?r theory", "Canva": "canva",
    "Branding": "branding|brand identity|logo design",
    # marketing
    "SEO": "seo|search engine optimi[sz]ation|keyword research|on-page|off-page", "SEM / Google Ads": "sem|google ads|adwords|ppc|paid search",
    "Meta Ads": "meta ads|facebook ads|instagram ads|paid social", "Social Media Marketing": "social media marketing|social media management|smm|instagram|linkedin marketing",
    "Content Marketing": "content marketing|content strategy|blogs?|editorial calendar", "Email Marketing": "email marketing|newsletters?|mailchimp|drip campaigns?",
    "Marketing Automation": "marketing automation|hubspot|marketo|pardot|webengage", "Brand Management": "brand management|brand strategy|brand campaigns?|atl|btl",
    "Campaign Management": "campaign management|campaign planning|campaign execution", "Performance Marketing": "performance marketing|roas|cpa|cpl|user acquisition",
    "Influencer Marketing": "influencer marketing|influencers?", "Market Research": "market research|consumer research|competitor analysis|competitive analysis",
    "Copywriting": "copywriting|ad copy|copy writing", "Event Management": "event management|event planning|trade shows?",
    # sales & support
    "B2B Sales": "b2b sales|enterprise sales|corporate sales|saas sales|solution selling", "B2C Sales": "b2c sales|retail sales|direct sales|field sales|counter sales",
    "Lead Generation": "lead generation|prospecting|lead gen|outbound|cold emailing", "Cold Calling": "cold calling|tele-?calling|outbound calls",
    "Negotiation": "negotiation|negotiating|deal closing|closing deals", "CRM Tools": "crm|salesforce|zoho crm|hubspot crm|leadsquared|freshsales|pipedrive",
    "Account Management": "account management|key accounts?|client management|client servicing", "Pipeline Management": "pipeline management|sales pipeline|funnel management|sales forecasting",
    "Channel Sales": "channel sales|distributors?|dealer network|channel partners?", "Target Achievement": "sales targets?|quota|revenue targets?|achieved \\d+%",
    "Customer Service": "customer service|customer support|customer care|customer handling", "Ticketing Tools": "zendesk|freshdesk|ticketing|jira service|helpdesk tools?",
    "Escalation Handling": "escalations?|complaint handling|grievance", "CSAT / NPS": "csat|nps|customer satisfaction", "Customer Onboarding": "customer onboarding|client onboarding|implementation",
    "Churn & Retention": "churn|renewals?|customer retention|upsell(?:ing)?|cross-sell(?:ing)?", "Troubleshooting": "troubleshoot(?:ing)?|technical support|l1|l2 support",
    # finance, banking
    "Accounting": "accounting|bookkeeping|journal entries|general ledger|ledger|month[- ]end close|finali[sz]ation of accounts",
    "Tally": "tally|tally erp|tally prime", "SAP FICO": "sap fico|sap fi|sap co|sap s/4hana finance", "Financial Reporting": "financial reporting|financial statements|balance sheet|p&l statements?|annual reports?",
    "GST & Indirect Tax": "gst|indirect tax|gstr|vat", "Direct Tax & TDS": "income tax|direct tax|tds|tax returns?|itr|transfer pricing", "Auditing": "audit(?:ing|s)?|internal audit|statutory audit|sox",
    "Budgeting": "budgeting|budget planning|budget preparation|cost control", "FP&A": "fp&a|financial planning|variance analysis|forecasting and budgeting|mis reporting",
    "IFRS / Ind AS": "ifrs|ind as|us gaap|gaap", "Accounts Payable / Receivable": "accounts payable|accounts receivable|invoice processing|collections management|vendor payments",
    "Payroll": "payroll|salary processing|esic", "Costing": "cost accounting|costing|inventory valuation|cma",
    "Credit Analysis": "credit analysis|credit appraisal|credit assessment|cibil|loan appraisal", "Risk Management": "risk management|risk assessment|operational risk|market risk|enterprise risk",
    "Valuation": "valuation|dcf|discounted cash flow|comparable companies|lbo", "Equity Research": "equity research|stock analysis|sector analysis|research reports?",
    "Bloomberg / Capital IQ": "bloomberg|capital iq|factset|refinitiv", "KYC / AML": "kyc|aml|anti[- ]money laundering|customer due diligence",
    "Portfolio Management": "portfolio management|asset management|wealth management|mutual funds?", "Derivatives & Fixed Income": "derivatives|fixed income|bond markets|f&o|futures and options|treasury operations",
    "Loan Processing": "loan processing|loan disbursement|mortgages?|home loans?|personal loans?",
    # HR
    "Recruitment": "recruitment|recruiting|hiring|talent acquisition|end[- ]to[- ]end recruitment", "Sourcing (Talent)": "candidate sourcing|boolean search|naukri|job portals|headhunting|linkedin recruiter",
    "Employee Engagement": "employee engagement|engagement activities|culture building", "Performance Management": "performance management|appraisals?|kras?|okrs?|performance reviews?",
    "HRIS": "hris|hrms|workday hcm|successfactors|darwinbox|keka|greythr|zoho people", "Labour Law Compliance": "labour laws?|labor laws?|statutory compliance|shops and establishment|posh",
    "Compensation & Benefits": "compensation and benefits|compensation & benefits|c&b|salary benchmarking|total rewards|compensation planning", "Employee Relations": "employee relations|grievance handling|disciplinary|exit interviews",
    "Learning & Development": "learning and development|l&d|training needs analysis|tna|training programs?", "Onboarding (HR)": "onboarding|induction|joining formalities",
    # operations, projects
    "Supply Chain Management": "supply chain|scm|end[- ]to[- ]end supply", "Logistics": "logistics|transportation|shipping|freight|last[- ]mile|3pl",
    "Procurement": "procurement|purchasing|purchase orders?|sourcing|rfq|rfp|vendor negotiation", "Vendor Management": "vendor management|supplier management|vendor development",
    "Inventory Management": "inventory management|inventory control|stock management|replenishment", "Warehouse Management": "warehouse|wms|warehousing|dispatch",
    "Demand Planning": "demand planning|demand forecasting|s&op|supply planning", "ERP": "erp|sap mm|sap sd|oracle erp|netsuite|dynamics 365", "Category Management": "category management|assortment|merchandising",
    "Lean / Six Sigma": "lean manufacturing|lean six sigma|six sigma|kaizen|5s|green belt|black belt|tqm", "Project Management": "project management|project planning|project delivery|project execution",
    "PMP / Prince2": "pmp|prince2|capm|pmi", "Agile / Scrum": "agile|scrum|kanban|sprint planning|scrum master", "MS Project": "ms project|microsoft project|primavera|smartsheet",
    "Resource Planning": "resource planning|resource allocation|capacity planning", "Risk & Issue Management": "risk mitigation|raid log|issue management|risk register",
    # legal
    "Contract Drafting": "contract drafting|drafting of agreements|drafting contracts|contract review|contract management|ndas?", "Legal Research": "legal research|case law|legal opinions?",
    "Litigation": "litigation|court proceedings|arbitration|dispute resolution", "Corporate Law": "corporate law|companies act|mergers|m&a|corporate governance",
    "Regulatory Compliance": "regulatory compliance|compliance monitoring|rbi guidelines|sebi|irdai|regulatory filings?", "Company Secretarial": "company secretary|roc filings?|board meetings|secretarial",
    "Intellectual Property": "intellectual property|ipr|trademarks?|patents?|copyrights?", "Data Privacy": "data privacy|gdpr|dpdp|data protection",
    "Due Diligence": "due diligence|legal due diligence",
    # healthcare
    "Patient Care": "patient care|patient management|bedside|icu|opd|ipd|ward management", "Nursing": "nursing|gnm|b\\.?sc nursing|anm|staff nurse",
    "Clinical Research": "clinical research|clinical trials?|ich[- ]gcp|good clinical practice|site management", "Pharmacovigilance": "pharmacovigilance|drug safety|adverse events?|case processing|argus",
    "Medical Coding": "medical coding|icd-?10|cpt|hcpcs|rcm|revenue cycle", "Regulatory Affairs": "regulatory affairs|dossier|ctd|cdsco|usfda",
    "Lab Techniques": "laboratory|lab techniques|pcr|elisa|hplc|chromatography|microbiology|pathology", "EMR / EHR": "emr|ehr|electronic medical records|hospital information system",
    "Pharmacy": "pharmacy|dispensing|pharmacist|b\\.?pharm|m\\.?pharm",
    "MBBS / MD": "mbbs|md medicine|md \\(medicine\\)|bams|bhms|bds|medical degree", "Critical Care": "critical care|icu|ventilator|acls|bls|emergency care", "Medical Sales": "medical representative|pharma sales|doctor calls|detailing",
    # core engineering
    "AutoCAD": "autocad|auto cad|2d drafting", "SolidWorks / CATIA": "solidworks|catia|creo|nx cad|unigraphics|inventor",
    "Revit / BIM": "revit|bim|tekla|navisworks", "STAAD Pro / ETABS": "staad|etabs|sap2000|structural analysis", "ANSYS / FEA": "ansys|fea|cfd|finite element|abaqus",
    "PLC / SCADA": "plc|scada|hmi|dcs|siemens s7|allen bradley", "Quality Control": "quality control|quality assurance|qc|qa/qc|inspection|spc|ppap|apqp|fmea|8d",
    "ISO Standards": "iso 9001|iso 14001|iso 45001|iatf|iso standards?", "GD&T": "gd&t|geometric dimensioning|tolerance stack",
    "Embedded Systems": "embedded c|embedded systems|microcontrollers?|rtos|arm cortex|firmware", "VLSI": "vlsi|verilog|vhdl|rtl design|asic|fpga|systemverilog",
    "Production Planning": "production planning|ppc|shop floor|manufacturing process|line balancing", "Preventive Maintenance": "preventive maintenance|predictive maintenance|breakdown maintenance|tpm",
    "HVAC / MEP": "hvac|mep|plumbing design|fire fighting", "MATLAB / Simulink": "matlab|simulink", "Site Execution": "site execution|site supervision|construction management|billing engineer|bbs|quantity surveying",
    "Electrical Design": "electrical design|panel design|load calculation|switchgear|power distribution|eplan",
    # content & media
    "Content Writing": "content writing|article writing|blog writing|web content|content creation", "Editing & Proofreading": "editing|proofreading|copy editing|sub-editing",
    "Technical Writing": "technical writing|technical documentation|user manuals|api documentation|release notes", "Public Relations": "public relations|pr campaigns?|press releases?|media relations",
    "Corporate Communications": "corporate communications|internal communications|employee communications", "Video Editing": "video editing|video production|reels|youtube",
    "Journalism": "journalism|reporting news|news writing|reporter|newsroom", "WordPress / CMS": "wordpress|cms|webflow|drupal",
    # education
    "Teaching": "teaching|taught|classroom|lesson plans?|pedagogy|cbse|icse|ib curriculum", "Curriculum Development": "curriculum development|curriculum design|syllabus|course design|content development",
    "Instructional Design": "instructional design|addie|articulate storyline|articulate 360|e-?learning", "Training Delivery": "training delivery|facilitation|soft skills training|corporate training|train the trainer",
    "Student Counselling": "student counsell?ing|career counsell?ing|admissions counsell?ing|academic counsell?ing", "Assessment Design": "assessment design|question papers?|grading rubrics?|exam papers?",
    # admin & hospitality
    "MS Office": "ms office|microsoft office|ms word|ms excel|powerpoint|ms outlook|google workspace|g suite", "Calendar & Travel Management": "calendar management|travel arrangements|travel bookings|diary management|scheduling meetings",
    "Office Administration": "office administration|office management|admin operations|front office|reception", "Data Entry": "data entry|typing speed|back office",
    "Facility Management": "facility management|facilities management|housekeeping supervision|security management",
    "Guest Service": "guest service|guest relations|hospitality|front desk|concierge", "F&B Service": "f&b|food and beverage|banquets?|restaurant operations",
    "Food Production": "food production|culinary|kitchen operations|haccp|menu planning", "Travel Booking (GDS)": "gds|amadeus|galileo|sabre|air ticketing|itinerary planning|visa processing",
    "Store Operations": "store operations|retail operations|visual merchandising|pos|shrinkage|store management",
}

# ------------------------------------------------------------------ families
# roles: (title, signal skills, typical min years, typical max years)
FAMILIES: list[dict] = [
    {"key": "analytics", "name": "Data & Analytics",
     "title_rx": r"\bdata\b|analytics|analytical|insight|business intelligence|\bbi\b|reporting|\bmis\b|\bmi\b|"
                 r"business analyst|product analyst|decision scien|data scien|growth analyst|pricing|"
                 r"market(?:ing)? (?:analyst|analytics|intelligence|research)|revenue (?:analyst|operations)|"
                 r"business operations|bizops|metrics|dashboard|visuali[sz]ation|research analyst|"
                 r"(?:analytics|strategy|business) consultant|strategy analyst|strategic|quantitative analyst",
     "exclude_rx": r"engineer|developer|architect|devops|programmer|sdet|\bqa\b|tester|testing|quality assurance|"
                   r"security analyst|\bsoc\b|cyber|network|infrastructure|service desk|"
                   r"sales executive|telecaller|tele-?sales|customer (?:care|support|service)|voice|call cent|training|"
                   r"account(?:ing|ant)|accounts payable|accounts receivable|\bap\b|\bar\b|r2r|p2p|o2c|i2c|controllership|"
                   r"treasury|\bcash\b|fund accounting|\btax\b|audit|reconciliation analyst|financial operations|billing|"
                   r"credit control|securities|derivatives|settlement|credit analyst|underwriting|model validation|valuation|"
                   r"legal|lawyer|paralegal|compliance|\bkyc\b|\baml\b|financial crime|\bhr\b|human resources|"
                   r"people operations|payroll|recruit|talent acquisition|vendor|procurement|sourcing|"
                   r"abstraction|lease|portfolio analyst|\bgst\b|investor relations|facilities|property|fincrime|"
                   r"fraud reporting|\bsar\b|enforcement|lms admin|general manager|\bgm\b|\bdgm\b|\bsvp\b|"
                   r"creative|graphic|designer|content writer|copywriter|project manager|program manager|scrum|"
                   r"workday|servicenow|nurse|teacher|driver|technician|mechanic|claims (?:associate|processor)",
     "skills": ["SQL", "Python", "Excel", "Power BI", "DAX", "Tableau", "Looker Studio", "Statistics", "A/B Testing",
                "Dashboards", "MIS Reporting", "KPI Design", "Data Visualization", "ETL", "Data Modeling", "Funnel Analysis",
                "Product Analytics", "Google Apps Script", "Pandas", "Forecasting", "Segmentation / Clustering",
                "Root Cause Analysis", "Requirement Gathering", "Data Storytelling", "BigQuery", "Snowflake"],
     "roles": [("Business Analyst", ["SQL", "Excel", "Stakeholder Management", "Requirement Gathering", "KPI Design", "Dashboards", "Root Cause Analysis"], 0, 6),
               ("Data Analyst", ["SQL", "Python", "Excel", "Statistics", "Data Visualization", "Power BI", "Pandas"], 0, 5),
               ("Business Intelligence Analyst", ["Power BI", "DAX", "Tableau", "SQL", "Data Modeling", "MIS Reporting", "ETL", "Dashboards"], 1, 7),
               ("Product Analyst", ["SQL", "A/B Testing", "Funnel Analysis", "Product Analytics", "Segmentation / Clustering", "Python", "KPI Design"], 1, 6),
               ("Business / Revenue Operations Analyst", ["KPI Design", "Funnel Analysis", "Excel", "SQL", "Forecasting", "Process Optimization", "Automation"], 1, 7),
               ("MIS / Reporting Analyst", ["Excel", "MIS Reporting", "Automation", "SQL", "Dashboards", "Google Apps Script"], 0, 6),
               ("Decision Scientist / Marketing Analytics", ["Python", "Machine Learning", "Segmentation / Clustering", "Statistics", "A/B Testing", "Marketing Analytics"], 1, 7),
               ("Pricing / Insights Analyst", ["Pricing", "Excel", "SQL", "Statistics", "Data Storytelling", "Forecasting"], 1, 6)],
     "manager": "Analytics Manager",
     "companies": ["Mu Sigma", "Fractal Analytics", "Tiger Analytics", "LatentView", "EXL", "ZS Associates", "Gartner",
                   "American Express", "Swiggy", "Zomato", "Flipkart", "PhonePe", "Paytm", "Razorpay", "Meesho", "Myntra"]},
    {"key": "strategy", "name": "Strategy & Consulting",
     "title_rx": r"strateg|consult|advisory|corporate development|chief of staff|business planning|founder'?s office|"
                 r"management trainee|transformation|business excellence",
     "exclude_rx": r"\bit consultant|sap |salesforce|oracle|technical consultant|software|developer|engineer|sales consultant|"
                   r"travel consultant|recruitment consultant|tax|audit|medical|nutrition",
     "skills": ["Problem Structuring", "Growth Strategy", "Market Research", "Financial Modeling", "Data Storytelling",
                "Stakeholder Management", "Excel", "Process Optimization", "Project Management", "Pricing"],
     "roles": [("Strategy Analyst", ["Problem Structuring", "Growth Strategy", "Excel", "Data Storytelling", "Market Research"], 0, 5),
               ("Management Consultant", ["Problem Structuring", "Stakeholder Management", "Data Storytelling", "Process Optimization"], 2, 8),
               ("Business Consultant", ["Requirement Gathering", "Stakeholder Management", "Process Optimization"], 2, 8),
               ("Corporate Strategy Associate", ["Financial Modeling", "Market Research", "Growth Strategy"], 2, 7),
               ("Founder's Office / Chief of Staff", ["Problem Structuring", "Project Management", "Stakeholder Management", "Growth Strategy"], 2, 8),
               ("Strategy & Operations Manager", ["Process Optimization", "KPI Design", "Growth Strategy", "Project Management"], 4, 10)],
     "manager": "Strategy Manager",
     "companies": ["McKinsey & Company", "Boston Consulting Group", "Bain & Company", "Deloitte", "EY-Parthenon", "KPMG",
                   "PwC", "Accenture Strategy", "Kearney", "Redseer", "Praxis Global Alliance", "Alvarez & Marsal"]},
    {"key": "datasci", "name": "Data Science & AI/ML",
     "title_rx": r"data scien|machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|\bnlp\b|computer vision|"
                 r"mlops|applied scien|research scien|\bllm|gen ?ai|generative",
     "exclude_rx": r"sales|recruit|marketing|annotat|data entry",
     "skills": ["Python", "Machine Learning", "Deep Learning", "TensorFlow / PyTorch", "NLP", "Computer Vision", "Statistics",
                "Scikit-Learn", "GenAI / LLMs", "MLOps", "SQL", "Spark", "Pandas", "Regression", "Forecasting"],
     "roles": [("Data Scientist", ["Python", "Machine Learning", "Statistics", "Scikit-Learn", "SQL"], 1, 6),
               ("Machine Learning Engineer", ["Python", "Machine Learning", "TensorFlow / PyTorch", "MLOps", "Docker"], 1, 7),
               ("AI / GenAI Engineer", ["GenAI / LLMs", "Python", "NLP", "TensorFlow / PyTorch", "REST APIs"], 1, 7),
               ("NLP Engineer", ["NLP", "Python", "Deep Learning", "spaCy", "GenAI / LLMs"], 1, 7),
               ("Computer Vision Engineer", ["Computer Vision", "Deep Learning", "TensorFlow / PyTorch", "Python"], 1, 7),
               ("Associate Data Scientist", ["Python", "Machine Learning", "Statistics", "Pandas"], 0, 3)],
     "manager": "Data Science Manager",
     "companies": ["Google", "Microsoft", "Amazon", "Fractal Analytics", "Tiger Analytics", "Sigmoid", "Swiggy", "Flipkart",
                   "Ola Krutrim", "Sarvam AI", "Uber", "Walmart Global Tech", "American Express", "Mastercard"]},
    {"key": "dataeng", "name": "Data Engineering",
     "title_rx": r"data engineer|etl|big data|data platform|analytics engineer|data architect|database (?:engineer|developer|admin)|\bdba\b|data warehouse",
     "exclude_rx": r"sales|recruit",
     "skills": ["SQL", "Python", "Spark", "Airflow", "ETL", "Kafka", "Snowflake", "BigQuery", "Databricks", "dbt",
                "Data Modeling", "Cloud (AWS/Azure/GCP)", "Hive / Hadoop", "NoSQL", "PostgreSQL"],
     "roles": [("Data Engineer", ["SQL", "Python", "Spark", "ETL", "Airflow", "Cloud (AWS/Azure/GCP)"], 1, 6),
               ("Analytics Engineer", ["SQL", "dbt", "Data Modeling", "Snowflake", "BigQuery"], 1, 6),
               ("Big Data Engineer", ["Spark", "Hive / Hadoop", "Kafka", "Python"], 2, 8),
               ("ETL Developer", ["ETL", "SQL", "Data Modeling"], 1, 6),
               ("Database Administrator", ["PostgreSQL", "SQL", "Linux"], 1, 8),
               ("Data Architect", ["Data Modeling", "Cloud (AWS/Azure/GCP)", "Snowflake", "Databricks"], 7, 15)],
     "manager": "Data Engineering Manager",
     "companies": ["Databricks", "Snowflake", "Sigmoid", "Tredence", "Fractal Analytics", "Thoughtworks", "Walmart Global Tech",
                   "Flipkart", "Zeta", "Atlan", "PhonePe", "Swiggy"]},
    {"key": "software", "name": "Software Engineering",
     "title_rx": r"software|developer|programmer|\bsde\b|full ?stack|front ?end|back ?end|web dev|mobile|android|\bios\b|"
                 r"\bjava\b|python dev|\.net|react|angular|node|golang|flutter|\bengineer\b|tech lead|technical lead|\bsre\b",
     "exclude_rx": r"mechanical|civil|electrical|electronics|production|manufacturing|plant|maintenance|site engineer|"
                   r"sales engineer|service engineer|field engineer|quality engineer|process engineer|design engineer|"
                   r"hvac|instrumentation|structural|chemical|automobile|support engineer|network engineer|"
                   r"test|\bqa\b|sdet|data engineer|ml engineer|machine learning|devops|cloud engineer|security",
     "skills": ["Java", "JavaScript", "TypeScript", "Python", "React", "Angular", "Node.js", "Spring Boot", "Django", "Go",
                "C++", "C#", ".NET", "REST APIs", "Microservices", "System Design", "Data Structures & Algorithms", "HTML/CSS",
                "Git", "Docker", "PostgreSQL", "NoSQL", "Kotlin", "Swift", "Flutter", "Android", "iOS", "PHP"],
     "roles": [("Software Engineer", ["Data Structures & Algorithms", "Java", "Python", "Git", "REST APIs"], 0, 5),
               ("Backend Developer", ["Java", "Spring Boot", "Node.js", "Python", "Django", "Go", "REST APIs", "Microservices", "PostgreSQL"], 1, 7),
               ("Frontend Developer", ["JavaScript", "TypeScript", "React", "Angular", "HTML/CSS"], 1, 7),
               ("Full Stack Developer", ["JavaScript", "React", "Node.js", "Python", "REST APIs", "PostgreSQL"], 1, 7),
               ("Mobile App Developer", ["Android", "Kotlin", "Swift", "iOS", "Flutter"], 1, 7),
               (".NET Developer", [".NET", "C#", "SQL"], 1, 7),
               ("Java Developer", ["Java", "Spring Boot", "Microservices"], 1, 7),
               ("Tech Lead", ["System Design", "Microservices", "Java", "Node.js", "Python"], 6, 12)],
     "manager": "Engineering Manager",
     "companies": ["Google", "Microsoft", "Amazon", "Atlassian", "Adobe", "Salesforce", "Flipkart", "Razorpay", "Zerodha",
                   "Swiggy", "Zomato", "Paytm", "PhonePe", "CRED", "Freshworks", "Zoho", "Postman", "BrowserStack", "TCS", "Infosys"]},
    {"key": "devops", "name": "DevOps, Cloud & IT",
     "title_rx": r"devops|\bsre\b|site reliability|cloud|platform engineer|infrastructure|system admin|sysadmin|network|"
                 r"it support|it admin|it executive|it engineer|security|cyber|\bsoc\b|desktop support|service desk|helpdesk|"
                 r"help desk|it operations|noc",
     "exclude_rx": r"sales|recruit|security guard|security officer|marketing",
     "skills": ["Docker", "Kubernetes", "Terraform", "CI/CD", "Linux", "Cloud (AWS/Azure/GCP)", "Ansible", "Monitoring",
                "Networking", "Cybersecurity", "ITIL", "Active Directory", "Python", "Git"],
     "roles": [("DevOps Engineer", ["Docker", "Kubernetes", "CI/CD", "Terraform", "Linux", "Cloud (AWS/Azure/GCP)"], 1, 7),
               ("Cloud Engineer", ["Cloud (AWS/Azure/GCP)", "Terraform", "Linux", "Networking"], 1, 7),
               ("Site Reliability Engineer", ["Kubernetes", "Monitoring", "Linux", "Python"], 2, 8),
               ("System Administrator", ["Linux", "Active Directory", "Networking", "ITIL"], 1, 7),
               ("Network Engineer", ["Networking", "Cybersecurity", "Linux"], 1, 7),
               ("IT Support Engineer", ["Troubleshooting", "Active Directory", "ITIL", "Networking"], 0, 5),
               ("Cybersecurity Analyst", ["Cybersecurity", "Networking", "Monitoring", "Linux"], 1, 7)],
     "manager": "IT Manager",
     "companies": ["Amazon Web Services", "Microsoft", "Google Cloud", "Red Hat", "Cisco", "Palo Alto Networks", "Zscaler",
                   "HCLTech", "Wipro", "Tech Mahindra", "Infosys", "Rackspace", "Nutanix"]},
    {"key": "qa", "name": "QA & Testing",
     "title_rx": r"\bqa\b|quality assurance|test(?:er|ing)?\b|sdet|automation engineer|quality engineer \(software",
     "exclude_rx": r"mechanical|civil|electrical|manufacturing|lab|clinical|food|textile|production",
     "skills": ["Manual Testing", "Test Automation", "Selenium", "Cypress / Playwright", "API Testing", "Performance Testing",
                "Appium", "Bug Tracking", "Java", "Python", "JIRA / Agile", "SQL"],
     "roles": [("QA Engineer", ["Manual Testing", "Bug Tracking", "API Testing", "SQL"], 0, 5),
               ("Automation Test Engineer", ["Test Automation", "Selenium", "Java", "Python", "Cypress / Playwright"], 1, 7),
               ("SDET", ["Test Automation", "Java", "API Testing", "CI/CD"], 2, 8),
               ("Performance Test Engineer", ["Performance Testing", "API Testing"], 2, 8),
               ("Mobile QA Engineer", ["Appium", "Manual Testing", "Test Automation"], 1, 6)],
     "manager": "QA Lead",
     "companies": ["BrowserStack", "Infosys", "TCS", "Cognizant", "Qualitest", "Capgemini", "Accenture", "Paytm", "Swiggy", "Freshworks"]},
    {"key": "product", "name": "Product Management",
     "title_rx": r"product manager|product owner|product lead|\bapm\b|\bpm\b|product management|head of product|"
                 r"product specialist|group product",
     "exclude_rx": r"product designer|product engineer|product analyst|sales|marketing|production",
     "skills": ["Product Roadmap", "PRDs", "User Research", "Prioritization", "A/B Testing", "Product Analytics", "JIRA / Agile",
                "Stakeholder Management", "SQL", "Wireframing & Prototyping", "Growth Strategy", "Funnel Analysis"],
     "roles": [("Associate Product Manager", ["PRDs", "User Research", "Product Analytics", "SQL"], 0, 3),
               ("Product Manager", ["Product Roadmap", "PRDs", "Prioritization", "User Research", "A/B Testing"], 2, 7),
               ("Product Owner", ["JIRA / Agile", "PRDs", "Prioritization", "Stakeholder Management"], 2, 8),
               ("Technical Product Manager", ["PRDs", "REST APIs", "System Design", "Product Roadmap"], 3, 9),
               ("Growth Product Manager", ["A/B Testing", "Funnel Analysis", "Product Analytics", "Growth Strategy"], 2, 8)],
     "manager": "Senior Product Manager",
     "companies": ["Google", "Microsoft", "Flipkart", "Swiggy", "Zomato", "Razorpay", "CRED", "PhonePe", "Groww", "Meesho",
                   "Zepto", "Ola", "MakeMyTrip", "Urban Company", "Nykaa"]},
    {"key": "design", "name": "Design (UI/UX & Creative)",
     "title_rx": r"designer|\bux\b|\bui\b|user experience|user interface|graphic|visual design|product design|creative|"
                 r"illustrat|motion|art director|animator|3d artist",
     "exclude_rx": r"engineer|instructional|interior|fashion|civil|mechanical|electrical|solution design|circuit",
     "skills": ["Figma", "Adobe XD / Sketch", "Photoshop", "Illustrator", "InDesign", "After Effects", "Premiere Pro",
                "Wireframing & Prototyping", "Design Systems", "User Research", "Usability Testing", "Typography", "Canva", "Branding", "HTML/CSS"],
     "roles": [("UI/UX Designer", ["Figma", "Wireframing & Prototyping", "User Research", "Design Systems"], 0, 6),
               ("Product Designer", ["Figma", "Design Systems", "Usability Testing", "Wireframing & Prototyping"], 2, 8),
               ("Graphic Designer", ["Photoshop", "Illustrator", "InDesign", "Canva", "Typography", "Branding"], 0, 6),
               ("Visual Designer", ["Illustrator", "Typography", "Branding", "Figma"], 1, 7),
               ("UX Researcher", ["User Research", "Usability Testing"], 1, 7),
               ("Motion Graphics Designer", ["After Effects", "Premiere Pro", "Illustrator"], 1, 7)],
     "manager": "Design Lead",
     "companies": ["Adobe", "Swiggy", "Zomato", "CRED", "Razorpay", "Flipkart", "Ogilvy", "Dentsu", "Publicis", "Lowe Lintas",
                   "Canva", "Freshworks", "Zoho"]},
    {"key": "marketing", "name": "Marketing & Growth",
     "title_rx": r"marketing|\bseo\b|\bsem\b|\bppc\b|growth (?:marketing|manager|hacker|lead)|brand|social media|digital|"
                 r"performance|campaign|crm (?:manager|executive)|email market|affiliate|demand gen|acquisition|community manager|"
                 r"product marketing|media planner|media buyer",
     "exclude_rx": r"sales executive|developer|engineer|digital transformation|digital forensic",
     "skills": ["SEO", "SEM / Google Ads", "Meta Ads", "Social Media Marketing", "Content Marketing", "Email Marketing",
                "Marketing Automation", "Google Analytics", "Brand Management", "Campaign Management", "Performance Marketing",
                "Influencer Marketing", "Market Research", "Copywriting", "Marketing Analytics"],
     "roles": [("Digital Marketing Executive", ["SEO", "SEM / Google Ads", "Social Media Marketing", "Google Analytics"], 0, 4),
               ("Performance Marketing Manager", ["Performance Marketing", "SEM / Google Ads", "Meta Ads", "Google Analytics"], 2, 8),
               ("SEO Specialist", ["SEO", "Content Marketing", "Google Analytics"], 1, 6),
               ("Social Media Manager", ["Social Media Marketing", "Content Marketing", "Influencer Marketing", "Canva"], 1, 7),
               ("Brand Manager", ["Brand Management", "Campaign Management", "Market Research"], 2, 8),
               ("Content Marketing Manager", ["Content Marketing", "SEO", "Copywriting"], 2, 8),
               ("Growth Marketing Manager", ["Performance Marketing", "A/B Testing", "Funnel Analysis", "Marketing Automation"], 2, 8),
               ("Product Marketing Manager", ["Market Research", "Brand Management", "Campaign Management"], 3, 9)],
     "manager": "Marketing Manager",
     "companies": ["Hindustan Unilever", "Procter & Gamble", "ITC", "Nestlé", "Dabur", "Marico", "Swiggy", "Zomato", "Nykaa",
                   "Mamaearth (Honasa)", "boAt", "Lenskart", "Ogilvy", "Dentsu", "WPP", "GroupM"]},
    {"key": "sales", "name": "Sales & Business Development",
     "title_rx": r"sales|business development|\bbd[me]?\b|account (?:executive|manager)|key account|inside sales|pre-?sales|"
                 r"relationship (?:manager|officer|executive)|territory|channel|partnerships?|alliances|area manager|"
                 r"regional manager|revenue manager|merchant|corporate sales|client acquisition|franchise",
     "exclude_rx": r"sales ?force (?:developer|admin|consultant)|salesforce|sales operations analyst|engineer(?! sales)|developer",
     "skills": ["B2B Sales", "B2C Sales", "Lead Generation", "Cold Calling", "Negotiation", "CRM Tools", "Account Management",
                "Pipeline Management", "Channel Sales", "Target Achievement", "Stakeholder Management", "MS Office"],
     "roles": [("Sales Executive", ["B2C Sales", "Lead Generation", "Cold Calling", "Target Achievement"], 0, 4),
               ("Business Development Executive", ["Lead Generation", "Cold Calling", "B2B Sales", "CRM Tools"], 0, 4),
               ("Business Development Manager", ["B2B Sales", "Negotiation", "Pipeline Management", "Account Management"], 3, 9),
               ("Account Executive", ["B2B Sales", "Pipeline Management", "Negotiation", "CRM Tools"], 1, 6),
               ("Key Account Manager", ["Account Management", "Negotiation", "B2B Sales"], 3, 9),
               ("Inside Sales Representative", ["Cold Calling", "Lead Generation", "CRM Tools"], 0, 4),
               ("Relationship Manager", ["Account Management", "B2C Sales", "Target Achievement"], 1, 7),
               ("Area Sales Manager", ["Channel Sales", "Target Achievement", "Negotiation"], 4, 10)],
     "manager": "Sales Manager",
     "companies": ["HDFC Bank", "ICICI Bank", "Axis Bank", "Bajaj Finserv", "Salesforce", "Freshworks", "Zoho", "Razorpay",
                   "PhonePe", "Paytm", "BYJU'S", "upGrad", "Hindustan Unilever", "Asian Paints", "Reliance Retail", "Tata Motors"]},
    {"key": "support", "name": "Customer Success & Support",
     "title_rx": r"customer|client servic|help ?desk|technical support|call cent|\bbpo\b|voice process|chat process|non-?voice|"
                 r"service desk|onboarding specialist|support (?:executive|associate|specialist|engineer)|contact cent|cx\b",
     "exclude_rx": r"customer (?:data|insights|analytics)|developer|sales manager",
     "skills": ["Customer Service", "Ticketing Tools", "Escalation Handling", "CSAT / NPS", "Customer Onboarding",
                "Churn & Retention", "Troubleshooting", "CRM Tools", "MS Office", "Account Management"],
     "roles": [("Customer Support Executive", ["Customer Service", "Ticketing Tools", "Escalation Handling"], 0, 4),
               ("Customer Success Manager", ["Customer Onboarding", "Churn & Retention", "Account Management", "CSAT / NPS"], 2, 8),
               ("Technical Support Engineer", ["Troubleshooting", "Ticketing Tools", "Customer Service"], 0, 5),
               ("Client Servicing Executive", ["Account Management", "Customer Service", "Escalation Handling"], 0, 5),
               ("Customer Experience Specialist", ["CSAT / NPS", "Customer Service", "Escalation Handling"], 1, 6),
               ("Team Leader - Customer Support", ["Escalation Handling", "CSAT / NPS", "Customer Service"], 4, 10)],
     "manager": "Customer Support Manager",
     "companies": ["Amazon", "Concentrix", "Teleperformance", "Genpact", "Freshworks", "Zoho", "Swiggy", "Zomato", "Flipkart",
                   "Airtel", "Startek", "iEnergizer", "Sutherland"]},
    {"key": "finance", "name": "Finance & Accounting",
     "title_rx": r"account(?:s|ant|ing)|finance|financial|fp&a|audit|\btax|treasury|controller|payable|receivable|\bca\b|"
                 r"chartered|bookkeep|cost account|billing|\bgst\b|r2r|p2p|o2c|general ledger|reconcil|\bcfo\b",
     "exclude_rx": r"developer|engineer|account executive|key account|account manager|sales|customer",
     "skills": ["Accounting", "Tally", "SAP FICO", "Financial Reporting", "GST & Indirect Tax", "Direct Tax & TDS", "Auditing",
                "Budgeting", "FP&A", "Financial Modeling", "IFRS / Ind AS", "Accounts Payable / Receivable", "Payroll",
                "Costing", "Excel", "Data Validation / Quality"],
     "roles": [("Accountant", ["Accounting", "Tally", "GST & Indirect Tax", "Accounts Payable / Receivable"], 0, 5),
               ("Accounts Executive", ["Accounting", "Tally", "Accounts Payable / Receivable", "Excel"], 0, 4),
               ("Financial Analyst", ["Financial Modeling", "FP&A", "Excel", "Budgeting", "Financial Reporting"], 0, 6),
               ("FP&A Analyst", ["FP&A", "Budgeting", "Financial Modeling", "Excel"], 1, 6),
               ("Internal Auditor", ["Auditing", "Financial Reporting", "IFRS / Ind AS"], 1, 7),
               ("Tax Consultant", ["Direct Tax & TDS", "GST & Indirect Tax"], 1, 7),
               ("Chartered Accountant", ["Auditing", "Direct Tax & TDS", "Financial Reporting", "IFRS / Ind AS"], 0, 8),
               ("Financial Controller", ["Financial Reporting", "IFRS / Ind AS", "Budgeting", "Auditing"], 7, 15)],
     "manager": "Finance Manager",
     "companies": ["Deloitte", "EY", "KPMG", "PwC", "Grant Thornton", "BDO India", "Genpact", "Accenture", "American Express",
                   "Goldman Sachs", "JP Morgan", "Tata Group", "Reliance Industries", "Aditya Birla Group"]},
    {"key": "banking", "name": "Banking, Investments & Risk",
     "title_rx": r"bank|investment|equity research|credit|risk|underwrit|wealth|portfolio|loan|mortgage|trader|trading|"
                 r"valuation|\bm&a\b|private equity|venture|fund|asset management|insurance|actuar|branch manager|kyc|aml",
     "exclude_rx": r"developer|engineer|software|security analyst|cyber|it risk",
     "skills": ["Credit Analysis", "Risk Management", "Valuation", "Financial Modeling", "Equity Research", "Bloomberg / Capital IQ",
                "KYC / AML", "Portfolio Management", "Derivatives & Fixed Income", "Loan Processing", "Excel", "Risk Analytics"],
     "roles": [("Credit Analyst", ["Credit Analysis", "Financial Modeling", "Risk Analytics"], 0, 6),
               ("Equity Research Analyst", ["Equity Research", "Valuation", "Financial Modeling", "Bloomberg / Capital IQ"], 0, 6),
               ("Investment Banking Analyst", ["Valuation", "Financial Modeling", "Bloomberg / Capital IQ"], 0, 4),
               ("Risk Analyst", ["Risk Management", "Risk Analytics", "Excel"], 0, 6),
               ("Relationship Manager - Banking", ["Portfolio Management", "Loan Processing", "Account Management"], 1, 8),
               ("Credit Manager", ["Credit Analysis", "Loan Processing", "Risk Management"], 4, 10),
               ("KYC / AML Analyst", ["KYC / AML", "Regulatory Compliance"], 0, 5),
               ("Wealth Manager", ["Portfolio Management", "Account Management"], 2, 10)],
     "manager": "Risk Manager",
     "companies": ["HDFC Bank", "ICICI Bank", "Kotak Mahindra Bank", "Axis Bank", "SBI", "Goldman Sachs", "JP Morgan",
                   "Morgan Stanley", "Barclays", "HSBC", "Bajaj Finance", "CRISIL", "ICRA", "Motilal Oswal", "Avendus"]},
    {"key": "hr", "name": "Human Resources & Talent",
     "title_rx": r"\bhr\b|human resource|recruit|talent|people (?:partner|ops|operations|team|business)|hrbp|payroll|"
                 r"compensation|learning (?:&|and) development|\bl&d\b|employee relations|staffing|sourcer|\bta\b",
     "exclude_rx": r"developer|engineer|hris developer",
     "skills": ["Recruitment", "Sourcing (Talent)", "Onboarding (HR)", "Employee Engagement", "Performance Management", "Payroll",
                "HRIS", "Labour Law Compliance", "Compensation & Benefits", "Employee Relations", "Learning & Development", "MS Office"],
     "roles": [("HR Executive", ["Recruitment", "Onboarding (HR)", "Employee Engagement", "HRIS"], 0, 4),
               ("Recruiter / Talent Acquisition Specialist", ["Recruitment", "Sourcing (Talent)"], 0, 6),
               ("HR Generalist", ["Employee Relations", "Onboarding (HR)", "Performance Management", "Labour Law Compliance"], 1, 6),
               ("HR Business Partner", ["Employee Relations", "Performance Management", "Employee Engagement"], 4, 10),
               ("Payroll Executive", ["Payroll", "Labour Law Compliance", "HRIS"], 0, 5),
               ("Compensation & Benefits Analyst", ["Compensation & Benefits", "Excel", "HRIS"], 2, 8),
               ("L&D Specialist", ["Learning & Development", "Training Delivery"], 2, 8)],
     "manager": "HR Manager",
     "companies": ["Randstad", "Adecco", "TeamLease", "Quess Corp", "ABC Consultants", "Michael Page", "Deloitte", "Accenture",
                   "Infosys", "Wipro", "Tata Consultancy Services", "Flipkart", "Amazon"]},
    {"key": "operations", "name": "Operations & Supply Chain",
     "title_rx": r"operations|supply chain|logistic|procurement|purchase|buyer|warehouse|inventory|fulfil|vendor|sourcing|"
                 r"planning|planner|\bscm\b|dispatch|fleet|transport|category|merchandis|store manager|import|export|"
                 r"shipping|customs|plant head|production manager",
     "exclude_rx": r"developer|engineer|it operations|security operations|devops|sales operations analyst|financial operations",
     "skills": ["Supply Chain Management", "Logistics", "Procurement", "Vendor Management", "Inventory Management",
                "Warehouse Management", "Demand Planning", "ERP", "Process Optimization", "Lean / Six Sigma", "Category Management", "Excel"],
     "roles": [("Operations Executive", ["Process Optimization", "Excel", "Vendor Management"], 0, 4),
               ("Operations Manager", ["Process Optimization", "Vendor Management", "KPI Design", "Lean / Six Sigma"], 4, 10),
               ("Supply Chain Analyst", ["Supply Chain Management", "Demand Planning", "Excel", "ERP"], 0, 5),
               ("Logistics Coordinator", ["Logistics", "Warehouse Management", "Inventory Management"], 0, 5),
               ("Procurement Specialist", ["Procurement", "Vendor Management", "ERP", "Negotiation"], 1, 7),
               ("Demand Planner", ["Demand Planning", "Forecasting", "ERP"], 1, 7),
               ("Category Manager", ["Category Management", "Vendor Management", "Negotiation"], 3, 9),
               ("Warehouse Manager", ["Warehouse Management", "Inventory Management", "Logistics"], 4, 10)],
     "manager": "Supply Chain Manager",
     "companies": ["Amazon", "Flipkart", "Delhivery", "Blue Dart", "DHL", "Maersk", "Reliance Retail", "BigBasket", "Zepto",
                   "Blinkit", "Hindustan Unilever", "Tata Steel", "Maruti Suzuki", "Mahindra Logistics"]},
    {"key": "project", "name": "Project & Program Management",
     "title_rx": r"project (?:manager|coordinator|lead|executive|management)|program(?:me)? manager|\bpmo\b|delivery manager|"
                 r"scrum master|agile coach|implementation manager",
     "exclude_rx": r"developer|software engineer",
     "skills": ["Project Management", "PMP / Prince2", "Agile / Scrum", "Stakeholder Management", "MS Project", "JIRA / Agile",
                "Resource Planning", "Risk & Issue Management", "Budgeting"],
     "roles": [("Project Coordinator", ["Project Management", "MS Project", "Stakeholder Management"], 0, 4),
               ("Project Manager", ["Project Management", "Stakeholder Management", "Risk & Issue Management", "Budgeting"], 4, 10),
               ("Program Manager", ["Project Management", "Stakeholder Management", "Resource Planning"], 6, 14),
               ("Scrum Master", ["Agile / Scrum", "JIRA / Agile"], 2, 8),
               ("PMO Analyst", ["Project Management", "Excel", "Resource Planning"], 1, 6),
               ("Delivery Manager", ["Project Management", "Agile / Scrum", "Stakeholder Management"], 7, 15)],
     "manager": "Senior Program Manager",
     "companies": ["Accenture", "Infosys", "TCS", "Wipro", "Capgemini", "IBM", "Deloitte", "L&T", "Siemens", "Honeywell", "Amazon"]},
    {"key": "legal", "name": "Legal & Compliance",
     "title_rx": r"legal|lawyer|advocate|counsel|paralegal|compliance|company secretary|\bcs\b|contract|litigation|"
                 r"regulatory|governance|corporate law|\bip\b|patent|trademark|\bllb\b",
     "exclude_rx": r"developer|engineer|contract (?:developer|engineer|staffing)",
     "skills": ["Contract Drafting", "Legal Research", "Litigation", "Corporate Law", "Regulatory Compliance", "Company Secretarial",
                "Intellectual Property", "Data Privacy", "Due Diligence", "Negotiation", "KYC / AML", "Labour Law Compliance"],
     "roles": [("Legal Associate", ["Contract Drafting", "Legal Research", "Due Diligence"], 0, 4),
               ("Legal Counsel", ["Contract Drafting", "Corporate Law", "Regulatory Compliance", "Negotiation"], 3, 10),
               ("Compliance Officer", ["Regulatory Compliance", "KYC / AML", "Data Privacy"], 2, 9),
               ("Company Secretary", ["Company Secretarial", "Corporate Law", "Regulatory Compliance"], 0, 10),
               ("Litigation Associate", ["Litigation", "Legal Research"], 0, 6),
               ("Contract Manager", ["Contract Drafting", "Negotiation"], 3, 10),
               ("IP Associate", ["Intellectual Property", "Legal Research"], 0, 6)],
     "manager": "Legal Manager",
     "companies": ["Cyril Amarchand Mangaldas", "Shardul Amarchand Mangaldas", "AZB & Partners", "Khaitan & Co", "Trilegal",
                   "JSA", "Deloitte", "EY", "Reliance Industries", "Tata Group", "HDFC Bank", "Flipkart"]},
    {"key": "healthcare", "name": "Healthcare & Life Sciences",
     "title_rx": r"doctor|physician|nurse|nursing|pharmac|clinical|medical|healthcare|hospital|patient|\blab\b|laboratory|"
                 r"biotech|regulatory affairs|pharmacovigilance|drug safety|dentist|dental|physiotherap|dietitian|nutrition|"
                 r"radiolog|technician|phlebotom|\bmbbs\b|\bbds\b|\bmd\b|scientist|research associate",
     "exclude_rx": r"software|developer|data scientist|sales engineer",
     "skills": ["Patient Care", "Nursing", "Critical Care", "MBBS / MD", "Clinical Research", "Pharmacovigilance", "Medical Coding", "Regulatory Affairs",
                "Lab Techniques", "EMR / EHR", "Pharmacy", "Medical Sales", "Quality Control"],
     "roles": [("Staff Nurse", ["Nursing", "Patient Care", "EMR / EHR"], 0, 6),
               ("ICU / Critical Care Nurse", ["Nursing", "Critical Care", "Patient Care"], 1, 10),
               ("Nursing Supervisor", ["Nursing", "Patient Care", "Training Delivery"], 6, 15),
               ("Clinical Research Associate", ["Clinical Research", "Regulatory Affairs"], 0, 6),
               ("Pharmacovigilance Associate", ["Pharmacovigilance", "Medical Coding"], 0, 5),
               ("Medical Coder", ["Medical Coding", "EMR / EHR"], 0, 5),
               ("Pharmacist", ["Pharmacy", "Patient Care"], 0, 8),
               ("Lab Technician", ["Lab Techniques", "Quality Control"], 0, 6),
               ("Medical Representative", ["Medical Sales", "B2C Sales", "Target Achievement"], 0, 6),
               ("Regulatory Affairs Associate", ["Regulatory Affairs", "Quality Control"], 1, 7),
               ("Medical Officer", ["MBBS / MD", "Patient Care", "Critical Care"], 0, 10)],
     "manager": "Hospital Administrator",
     "companies": ["Apollo Hospitals", "Fortis Healthcare", "Max Healthcare", "Medanta", "Manipal Hospitals", "Narayana Health",
                   "Sun Pharma", "Dr. Reddy's", "Cipla", "Lupin", "Biocon", "IQVIA", "Parexel", "Syneos Health", "Novartis"]},
    {"key": "core_eng", "name": "Engineering & Manufacturing",
     "title_rx": r"mechanical|civil|electrical|electronics|production|manufacturing|plant|maintenance|quality (?:engineer|control|inspector)|"
                 r"design engineer|site engineer|process engineer|automobile|automotive|hvac|instrumentation|structural|\bcad\b|"
                 r"r&d engineer|embedded|vlsi|chemical engineer|project engineer|planning engineer|estimation|draughtsman|draftsman|"
                 r"tool (?:room|design)|\bmep\b|piping|commissioning|service engineer|field engineer",
     "exclude_rx": r"software|data engineer|devops|cloud|front ?end|back ?end|full ?stack",
     "skills": ["AutoCAD", "SolidWorks / CATIA", "Revit / BIM", "STAAD Pro / ETABS", "ANSYS / FEA", "PLC / SCADA", "Quality Control",
                "ISO Standards", "GD&T", "Embedded Systems", "VLSI", "Production Planning", "Preventive Maintenance", "HVAC / MEP",
                "MATLAB / Simulink", "Site Execution", "Electrical Design", "Lean / Six Sigma", "Project Management"],
     "roles": [("Mechanical Design Engineer", ["SolidWorks / CATIA", "AutoCAD", "GD&T", "ANSYS / FEA"], 0, 7),
               ("Civil Site Engineer", ["Site Execution", "AutoCAD", "STAAD Pro / ETABS"], 0, 7),
               ("Structural Engineer", ["STAAD Pro / ETABS", "AutoCAD", "Revit / BIM"], 1, 8),
               ("Electrical Engineer", ["Electrical Design", "AutoCAD", "PLC / SCADA"], 0, 7),
               ("Production Engineer", ["Production Planning", "Lean / Six Sigma", "Quality Control"], 0, 7),
               ("Quality Engineer", ["Quality Control", "ISO Standards", "Lean / Six Sigma"], 0, 7),
               ("Maintenance Engineer", ["Preventive Maintenance", "PLC / SCADA"], 0, 7),
               ("Embedded Software Engineer", ["Embedded Systems", "C++"], 0, 7),
               ("VLSI Design Engineer", ["VLSI"], 0, 7),
               ("MEP / HVAC Engineer", ["HVAC / MEP", "AutoCAD", "Revit / BIM"], 1, 8)],
     "manager": "Plant Manager",
     "companies": ["Larsen & Toubro", "Tata Motors", "Maruti Suzuki", "Mahindra & Mahindra", "Bosch", "Siemens", "ABB", "Schneider Electric",
                   "Honeywell", "Hero MotoCorp", "Bajaj Auto", "Ashok Leyland", "Tata Projects", "Qualcomm", "Texas Instruments", "Intel"]},
    {"key": "content", "name": "Content, Media & Communications",
     "title_rx": r"content|writer|copywriter|editor|journalist|communications|public relations|\bpr\b|media|video|producer|"
                 r"technical writer|translator|anchor|reporter|scriptwriter|podcast|creator",
     "exclude_rx": r"developer|engineer|media buyer|media planner|social media (?:marketing|manager)",
     "skills": ["Content Writing", "Copywriting", "Editing & Proofreading", "Technical Writing", "SEO", "Public Relations",
                "Corporate Communications", "Video Editing", "Journalism", "WordPress / CMS", "Social Media Marketing", "Premiere Pro"],
     "roles": [("Content Writer", ["Content Writing", "SEO", "WordPress / CMS"], 0, 5),
               ("Copywriter", ["Copywriting", "Content Writing"], 0, 6),
               ("Technical Writer", ["Technical Writing", "Editing & Proofreading"], 0, 7),
               ("Editor", ["Editing & Proofreading", "Content Writing", "Journalism"], 2, 9),
               ("PR / Communications Manager", ["Public Relations", "Corporate Communications"], 3, 10),
               ("Video Editor", ["Video Editing", "Premiere Pro", "After Effects"], 0, 6),
               ("Journalist / Reporter", ["Journalism", "Content Writing"], 0, 8)],
     "manager": "Content Lead",
     "companies": ["Times Internet", "HT Media", "NDTV", "The Indian Express", "Network18", "Pocket FM", "Kuku FM", "Netflix",
                   "Amazon", "Zee Entertainment", "Viacom18", "Ogilvy", "Adfactors PR", "Edelman"]},
    {"key": "education", "name": "Education & Training",
     "title_rx": r"teacher|faculty|lecturer|professor|tutor|trainer|instructional|curriculum|academic|educator|counsell?or|"
                 r"teaching|subject matter expert|\bsme\b|\bpgt\b|\btgt\b|\bprt\b|coach|mentor",
     "exclude_rx": r"developer|engineer|sales coach|agile coach",
     "skills": ["Teaching", "Curriculum Development", "Instructional Design", "Training Delivery", "Student Counselling",
                "Assessment Design", "MS Office", "Content Writing"],
     "roles": [("Teacher", ["Teaching", "Assessment Design"], 0, 10),
               ("Subject Matter Expert", ["Teaching", "Content Writing", "Assessment Design"], 1, 8),
               ("Corporate Trainer", ["Training Delivery", "Learning & Development"], 2, 10),
               ("Instructional Designer", ["Instructional Design", "Curriculum Development"], 1, 8),
               ("Academic Counsellor", ["Student Counselling", "B2C Sales"], 0, 5),
               ("Lecturer / Assistant Professor", ["Teaching", "Curriculum Development"], 0, 10)],
     "manager": "Academic Head",
     "companies": ["BYJU'S", "PhysicsWallah", "Unacademy", "upGrad", "Vedantu", "Simplilearn", "Great Learning", "Delhi Public School",
                   "Amity University", "Manipal Education", "Emeritus", "Coursera"]},
    {"key": "admin", "name": "Administration & Office",
     "title_rx": r"\badmin\b|administrat|office manager|executive assistant|personal assistant|receptionist|front office|"
                 r"back office|data entry|coordinator|secretary|facilit|documentation (?:executive|specialist)|\bmis executive",
     "exclude_rx": r"system admin|database admin|network admin|developer|engineer|salesforce admin",
     "skills": ["MS Office", "Calendar & Travel Management", "Office Administration", "Data Entry", "Facility Management",
                "Vendor Management", "Excel", "Customer Service"],
     "roles": [("Admin Executive", ["Office Administration", "Vendor Management", "MS Office"], 0, 5),
               ("Executive Assistant", ["Calendar & Travel Management", "MS Office"], 1, 10),
               ("Office Administrator", ["Office Administration", "Facility Management"], 1, 8),
               ("Front Office Executive", ["Office Administration", "Customer Service"], 0, 4),
               ("Data Entry Operator", ["Data Entry", "Excel"], 0, 4),
               ("Facilities Manager", ["Facility Management", "Vendor Management"], 5, 12)],
     "manager": "Admin Manager",
     "companies": ["CBRE", "JLL", "Cushman & Wakefield", "ISS Facility Services", "Sodexo", "Tata Consultancy Services",
                   "Infosys", "Genpact", "Accenture", "Concentrix"]},
    {"key": "hospitality", "name": "Hospitality, Travel & Retail",
     "title_rx": r"hotel|hospitality|chef|commis|cook|\bf&b\b|food|restaurant|travel|tour|ticketing|airline|cabin crew|"
                 r"retail|store|cashier|guest|housekeeping|steward|barista|front desk|reservation",
     "exclude_rx": r"developer|engineer|data|analyst",
     "skills": ["Guest Service", "F&B Service", "Food Production", "Travel Booking (GDS)", "Store Operations", "Customer Service",
                "Inventory Management", "B2C Sales"],
     "roles": [("Guest Relations Executive", ["Guest Service", "Customer Service"], 0, 5),
               ("Hotel Operations Executive", ["Guest Service", "F&B Service"], 0, 6),
               ("Chef / Commis", ["Food Production"], 0, 10),
               ("Travel Consultant", ["Travel Booking (GDS)", "Customer Service", "B2C Sales"], 0, 6),
               ("Store Manager", ["Store Operations", "Inventory Management", "B2C Sales"], 3, 10),
               ("Retail Sales Associate", ["B2C Sales", "Customer Service", "Store Operations"], 0, 4),
               ("Cabin Crew", ["Guest Service", "Customer Service"], 0, 6)],
     "manager": "Hotel / Restaurant Manager",
     "companies": ["Taj Hotels (IHCL)", "ITC Hotels", "Oberoi Group", "Marriott", "Hyatt", "Accor", "IndiGo", "Air India",
                   "MakeMyTrip", "Thomas Cook", "Reliance Retail", "Tata Trent", "Shoppers Stop", "DMart", "Starbucks"]},
]

BY_KEY = {f["key"]: f for f in FAMILIES}

# ------------------------------------------------------------------ seniority levels
# label, years from, years to (soft)
BANDS = [("Entry level", 0, 2), ("Mid level", 2, 5), ("Senior", 5, 9), ("Lead / Manager", 8, 14), ("Director / Head", 12, 45)]
BAND_NAMES = [b[0] for b in BANDS]
BAND_HINT = {"Entry level": "0–2 years", "Mid level": "2–5 years", "Senior": "5–9 years",
             "Lead / Manager": "8–14 years", "Director / Head": "12+ years"}

# title words -> the levels a title can belong to (checked in order)
LEVEL_RULES = [
    (r"\b(intern|internship|trainee|apprentice|fresher|graduate trainee)\b", "Intern / Trainee", ["Entry level"]),
    (r"\b(chief|vice president|vp|svp|evp|director|president|cxo|cto|cfo|coo|ceo|head)\b", "Director / Head", ["Director / Head"]),
    (r"\b(general manager|gm|dgm|agm|avp)\b", "General Manager", ["Lead / Manager", "Director / Head"]),
    (r"\b(principal|staff|architect)\b", "Principal / Staff", ["Lead / Manager", "Director / Head"]),
    (r"\bsenior manager\b|\bsr\.? manager\b", "Senior Manager", ["Lead / Manager"]),
    (r"\b(assistant|asst\.?|deputy) manager\b", "Assistant Manager", ["Mid level", "Senior"]),
    (r"\b(manager|mgr)\b", "Manager", ["Senior", "Lead / Manager"]),
    (r"\b(lead|team lead|team leader|supervisor)\b", "Lead", ["Senior", "Lead / Manager"]),
    (r"\b(senior|sr\.?|iii|level 3|l3)\b", "Senior", ["Senior", "Mid level"]),
    (r"\b(junior|jr\.?|entry|associate|executive|assistant|\bi\b|level 1)\b", "Junior / Associate", ["Entry level", "Mid level"]),
]
_LEVEL_C = [(re.compile(p, re.I), label, bands) for p, label, bands in LEVEL_RULES]
LEVEL_WORDS = re.compile(r"\b(senior|sr\.?|junior|jr\.?|lead|principal|staff|associate|assistant|deputy|trainee|intern|"
                         r"head|chief|vp|director|i{1,3}|iv|\d)\b", re.I)


def title_level(title: str) -> tuple[str, list[str]]:
    """Level label and the seniority bands a job title fits ("Mid level" when the title names no level)."""
    for rx, label, bands in _LEVEL_C:
        if rx.search(title or ""):
            return label, bands
    return "Mid level", []


def band_of_years(years: float) -> int:
    for i, (_, lo, hi) in enumerate(BANDS):
        if lo <= years < hi:
            return i
    return len(BANDS) - 1


def default_bands(years: float) -> list[str]:
    """The person's own level plus the next one up (and the one below near a boundary)."""
    i = band_of_years(float(years or 0))
    picks = {i, min(i + 1, len(BANDS) - 1)}
    if i > 0 and years - BANDS[i][1] < 1:
        picks.add(i - 1)
    return [BANDS[k][0] for k in sorted(picks)]


def band_years(bands: list[str]) -> tuple[float, float]:
    rows = [b for b in BANDS if b[0] in (bands or [])]
    if not rows:
        return 0, 45
    return min(r[1] for r in rows), max(r[2] for r in rows)


def level_fit(title: str, years: float) -> tuple[str, float]:
    """How well a title's level suits someone with this much experience (0-1)."""
    label, bands = title_level(title)
    if not bands:
        return label, 0.9
    mine = band_of_years(float(years or 0))
    dist = min(abs(BAND_NAMES.index(b) - mine) for b in bands)
    return label, {0: 1.0, 1: 0.7, 2: 0.35}.get(dist, 0.1)


# ------------------------------------------------------------------ compiled patterns
@lru_cache(maxsize=None)
def _rx(pattern: str):
    return re.compile(pattern, re.I) if pattern else None


def title_in_family(title: str, fam: dict) -> bool:
    t = title or ""
    inc, exc = _rx(fam.get("title_rx", "")), _rx(fam.get("exclude_rx", ""))
    return bool(inc and inc.search(t)) and not (exc and exc.search(t))


def families_of_title(title: str) -> list[str]:
    return [f["key"] for f in FAMILIES if title_in_family(title, f)]


ABBR = [(r"\bbi\b", "business intelligence"), (r"\bsde\b|\bswe\b", "software engineer"), (r"\bml\b", "machine learning"),
        (r"\bhrbp\b", "hr business partner"), (r"\bbde\b", "business development executive"),
        (r"\bbdm\b", "business development manager"), (r"\bsdr\b", "sales development representative"),
        (r"\bcsm\b", "customer success manager"), (r"\bqa\b", "quality assurance"), (r"\bui/ux\b|\bux/ui\b", "ui ux"),
        (r"\bfp&a\b", "fp&a"), (r"\bapm\b", "associate product manager")]


def strip_level(title: str) -> str:
    t = title or ""
    for pat, rep in ABBR:
        t = re.sub(pat, rep, t, flags=re.I)
    t = LEVEL_WORDS.sub(" ", t)
    return re.sub(r"\s+", " ", re.sub(r"[-–,/|()]+", " ", t)).strip()


def family_for_role(role_title: str) -> str | None:
    """Family whose catalog lists this role (or whose title pattern matches it)."""
    base = strip_level(role_title).lower()
    for f in FAMILIES:
        for r in f["roles"]:
            if strip_level(r[0]).lower() == base:
                return f["key"]
        if strip_level(f.get("manager", "")).lower() == base:
            return f["key"]
    fams = families_of_title(role_title)
    return fams[0] if fams else None


def companies_for(keys: list[str]) -> list[dict]:
    out, seen = [], set()
    for k in keys:
        for c in BY_KEY.get(k, {}).get("companies", []):
            if c.lower() not in seen:
                seen.add(c.lower())
                out.append({"name": c, "family": k})
    return out
