"""Configuration and bookmark taxonomy."""
from pathlib import Path

MODEL = "gemma4:e2b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
CDP_URL = "http://127.0.0.1:9222"
ENABLE_BOOKMARK_SUMMARIES = False
FORCE_REBUILD_CATEGORIES = True
ENABLE_OLLAMA_CATEGORY_FALLBACK = False
CATEGORY_TAXONOMY_VERSION = "2026-04-25-v2"

# Path.home() is your user home directory, for example /Users/kirankonathala.
OBSIDIAN_VAULT = None # Path("/Volumes/Projects/Obsidian Vault")

OUTPUT_DIR = OBSIDIAN_VAULT if OBSIDIAN_VAULT and OBSIDIAN_VAULT.exists() else Path.cwd()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE = OUTPUT_DIR / "bookmarks_cache.json"
OUTPUT = OUTPUT_DIR / "bookmark_analysis.md"
HTML_OUTPUT = OUTPUT_DIR / "bookmark_dashboard.html"
CHECKPOINT = OUTPUT_DIR / "bookmark_checkpoint.json"
RESUME_LOG = OUTPUT_DIR / "bookmark_resume.log"

TWITTER_EPOCH = 1288834974657
CHECKPOINT_EVERY = 10
SCRAPE_TEST_LIMIT = None
FOLDER_SCAN_STABLE_SCROLLS = 8
STOP_ON_FIRST_STALE_FOLDER = True

FOLDER_CATEGORIES = [
    {
        "category_name": "Artificial Intelligence (AI) & LLMs",
        "description": "Topics covering the core concepts, models, training, and application of AI, including fine-tuning, RAG, and model architecture.",
        "items": [
            "LLM Training",
            "Finetuning LLM",
            "LLM RAG",
            "Fine tuning DeepSeek",
            "Gemma Models",
            "Claude Skills",
            "LLM Local",
            "LLM Finetuning",
            "AI Vision LLM",
            "AI Voice",
            "Voice models",
            "Voice chat local LLM",
            "AI Agents",
            "Agentic Development",
            "LLM Webscraper",
            "AI Prompts",
            "AI Design Prompts",
            "AI Use Cases",
            "AI Investing",
            "AI SEO",
            "LLM Webscraper",
            "AI Autoresearch",
        ],
    },
    {
        "category_name": "AI Tools & Agent Ecosystem",
        "description": "Focuses on practical tools, frameworks, agent development, and utilizing AI services via APIs.",
        "items": [
            "AI API",
            "AI Model API Keys",
            "AI Tools for Agents",
            "Agent Web Stack",
            "AI Agent Skills",
            "AI IDE",
            "Cursor",
            "Codex",
            "OpenRouter",
            "OpenClaw",
            "AI Github",
            "AI Tools Productivity",
            "Vector database",
            "AI Voice",
            "Telegram Bots",
            "AI Video Gen",
            "Hermes",
        ],
    },
    {
        "category_name": "Programming & Development",
        "description": "Guides and topics related to coding, scripting, workflows, and version control.",
        "items": [
            "Python",
            "Python UV",
            "Coding workflows AI",
            "Write Tests in Code",
            "Web scraping",
            "Git Ingest",
            "Postgres",
            "Log Management",
            "Server Optimization",
            "unsloth",
            "AI Github",
            "AI software costs",
        ],
    },
    {
        "category_name": "System & Infrastructure",
        "description": "Topics related to hardware, hosting, deployment, and large-scale server management.",
        "items": [
            "Infrastructure hosting",
            "Local AI",
            "Mac Mini",
            "Server Optimization",
            "MCP Server",
            "MCP",
            "Buildings and Floor Plans",
            "Tailscale",
        ],
    },
    {
        "category_name": "Business & Entrepreneurship",
        "description": "Focuses on starting, growing, and managing businesses, and financial wellness.",
        "items": [
            "Entrepreneurship",
            "Business ownership life",
            "Startup Ideas",
            "AI Stocks",
            "Financial Wellness",
            "Retirement",
            "Immigration matters",
            "LinkedIn Profile",
            "Deals",
        ],
    },
    {
        "category_name": "Personal & Professional Growth",
        "description": "Covers soft skills, mind health, learning strategies, and professional development.",
        "items": [
            "Personal",
            "Productivity",
            "High Performer at Work",
            "Skills",
            "Learning and Memory",
            "Motivated and mind health",
        ],
    },
    {
        "category_name": "Design & Creative Arts",
        "description": "Content focused on visual design, art, and creative expression.",
        "items": [
            "iOS Design",
            "Figma App design",
            "Design Ideas",
            "Painting hacks",
            "Handpan",
            "Websites",
        ],
    },
    {
        "category_name": "Health & Wellness",
        "description": "Information related to physical fitness, health, and lifestyle.",
        "items": [
            "Health",
            "Fitness",
            "Healthy recipes",
            "Dumbbell Bench",
        ],
    },
    {
        "category_name": "Learning & Knowledge",
        "description": "Courses, academic topics, memory techniques, and general knowledge.",
        "items": [
            "Learning and Memory",
            "AI Courses",
            "Stanford courses",
            "eBooks",
            "Free Courses",
            "Write Papers",
            "Obsidian Memory",
            "Math tricks",
            "Math",
        ],
    },
    {
        "category_name": "General & Miscellaneous",
        "description": "Catch-all topics, specific interests, and general knowledge.",
        "items": [
            "Jeans",
            "AI Security",
            "Security",
            "Inspirational",
            "Biology",
            "OCR",
            "Cute",
            "AI Video Gen",
        ],
    }
]



# FOLDER_CATEGORIES = [
#     {
#         "category_name": "Artificial Intelligence (AI) & LLMs",
#         "description": "Topics covering the core concepts, models, training, and application of AI.",
#         "items": [
#             "AI Videos",
#             "LLM Finetuning",
#             "LLM Training",
#             "Gemma Models",
#             "Claude Skills",
#             "AI Model API Keys",
#             "LLM RAG",
#             "AI Agents",
#             "AI Agent Skills",
#             "AI Vision LLM",
#             "LLM Webscraper",
#             "Local LLM",
#             "Fine tuning DeepSeek",
#             "AI Prompts",
#             "AI Design Prompts",
#             "AI Use Cases",
#             "AI Investing",
#             "AI SEO",
#             "AI Tools Productivity",
#             "AI Planning & Execution",
#             "AI IDE",
#             "AI Autoresearch",
#             "Hermes",
#         ],
#     },
#     {
#         "category_name": "AI Tools & Agent Ecosystem",
#         "description": "Focuses on practical tools, frameworks, platforms, and agent development.",
#         "items": [
#             "Agent Web Stack",
#             "AI Tools for Agents",
#             "AI Software Costs",
#             "AI Github",
#             "AI API",
#             "OpenRouter",
#             "OpenClaw",
#             "AI Voice",
#             "Telegram Bots",
#             "Agentic Development",
#         ],
#     },
#     {
#         "category_name": "Programming & Development",
#         "description": "Guides and topics related to coding, scripting, infrastructure, and software development.",
#         "items": [
#             "Python",
#             "Python UV",
#             "Github",
#             "unsloth",
#             "Write Tests in Code",
#             "Web scraping",
#             "Git Ingest",
#             "Database Tips",
#             "Log Management",
#             "Server Optimization",
#             "MCP Server",
#             "Vector database",
#             "Tailscale",
#             "Codex",
#             "Dashboards",
#         ],
#     },
#     {
#         "category_name": "System & Infrastructure",
#         "description": "Topics related to hardware, hosting, operating systems, and deployment.",
#         "items": [
#             "Infrastructure hosting",
#             "Local AI",
#             "Mac Mini",
#             "Server Optimization",
#             "MCP",
#             "Buildings and Floor Plans",
#         ],
#     },
#     {
#         "category_name": "Personal & Professional Growth",
#         "description": "Covers career development, soft skills, personal finance, and self-improvement.",
#         "items": [
#             "Personal",
#             "Productivity",
#             "High Performer at Work",
#             "Entrepreneurship",
#             "Financial Wellness",
#             "Retirement",
#             "Immigration matters",
#             "Success stories",
#             "Content creator",
#             "Skills",
#             "LinkedIn Profile",
#         ],
#     },
#     {
#         "category_name": "Design & Creative Arts",
#         "description": "Content focused on visual design, art, and creative expression.",
#         "items": [
#             "iOS Design",
#             "Figma App design",
#             "Design Ideas",
#             "Painting hacks",
#             "Handpan",
#         ],
#     },
#     {
#         "category_name": "Health & Wellness",
#         "description": "Information related to physical fitness, health, and lifestyle.",
#         "items": [
#             "Health",
#             "Fitness",
#             "Healthy recipes",
#             "Dumbbell Bench",
#         ],
#     },
#     {
#         "category_name": "Learning & Knowledge",
#         "description": "Courses, academic topics, and educational content.",
#         "items": [
#             "Learning and Memory",
#             "AI Courses",
#             "Stanford courses",
#             "eBooks",
#             "Free Courses",
#             "Write Papers",
#             "Obsidian Memory",
#         ],
#     },
#     {
#         "category_name": "General & Miscellaneous",
#         "description": "Catch-all categories for unique or unrelated topics.",
#         "items": [
#             "Personal",
#             "Inspirational",
#             "AI Security",
#             "Security",
#             "AI Voice",
#         ],
#     },
# ]
