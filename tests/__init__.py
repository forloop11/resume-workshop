"""The project's tests: `make test`.

They use only the standard library's unittest. test_backend, the editor's
backend, needs jsonschema (requirements.txt) and skips without it; the parts
of it that build a PDF also need a TeX engine, and make to compare with.
The editor's window has a test of its own: `make app-test`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
for folder in ("scripts", "app/backend"):
    sys.path.insert(0, str(ROOT / folder))

# A resume with every section, and the characters LaTeX treats specially.
RESUME = {
    "basics": {
        "name": "Ada Example", "label": "Engineer · Writer", "email": "ada@example.com", "phone": "+1 555 0100",
        "url": "https://example.com", "summary": "Builds things 100% of the time & writes about them.",
        "location": {"city": "Springfield", "region": "IL"},
        "profiles": [{"network": "GitHub", "username": "ada", "url": "https://github.com/ada/"}],
    },
    "work": [
        {"name": "Acme", "location": "Springfield, IL", "position": "Lead", "startDate": "2020-03",
         "highlights": ["Cut costs by $1M_2 {really}."], "stack": "Python, Make"},
        {"name": "Acme", "location": "Springfield, IL", "position": "Engineer", "startDate": "2018-01", "endDate": "2020-03",
         "summary": "Did the work.", "companyStack": "SQL"},
        {"name": "Old Co", "position": "Intern", "startDate": "2001", "endDate": "2003", "earlyCareer": True},
    ],
    "volunteer": [{"organization": "Library", "position": "Tutor", "startDate": "2019", "highlights": ["Taught reading."]}],
    "education": [{"institution": "State U", "studyType": "BS", "area": "Physics", "endDate": "2017", "courses": ["Optics", "Waves"]}],
    "certificates": [{"name": "Cert A", "issuer": "Body"}, {"name": "Cert B"}],
    "awards": [{"title": "Prize", "summary": "For a thing."}],
    "publications": [{"name": "Paper", "publisher": "Journal", "releaseDate": "2021-05", "summary": "On things."}],
    "projects": [{"name": "Tool", "description": "A tool.", "highlights": ["Works."], "keywords": ["Go", "Rust"]}],
    "skills": [{"name": "Languages", "level": "Expert", "keywords": ["Python", "R"]}],
    "languages": [{"language": "English", "fluency": "Native"}],
    "interests": [{"name": "Chess", "keywords": ["Openings"]}],
    "references": [{"name": "A. Boss", "reference": "Hire her."}],
}
