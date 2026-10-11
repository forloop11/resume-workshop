import unittest

from tests import RESUME

import generate_header
import generate_resume
import generate_text


class TextResume(unittest.TestCase):
    def test_every_section(self):
        text = generate_text.render(RESUME, generate_resume.SECTIONS)
        self.assertTrue(text.startswith("ADA EXAMPLE\nENGINEER · WRITER\nSpringfield, IL · +1 555 0100 · ada@example.com\n"
                                        "example.com · github.com/ada\n\nPROFESSIONAL SUMMARY\n\n"))
        for line in (
            "Acme, Springfield, IL (Jan 2018 – Present)",  # the employer's dates span its roles
            "Lead (Mar 2020 – Present)\n- Cut costs by $1M_2 {really}.\nStack: Python, Make",
            "Engineer (Jan 2018 – Mar 2020)\nDid the work.\n\nStack: SQL",
            "EARLY CAREER\n\nIntern, Old Co (2001–2003)",
            "Library (2019 – Present)\nTutor\n- Taught reading.",
            "BS in Physics, State U (2017)\nCourses: Optics · Waves",
            "Cert A, Body · Cert B",
            "Paper: Journal (2021). On things.",
            "Tool: A tool.\n- Works.\nStack: Go · Rust",
            "Languages (Expert): Python · R",
            "English (Native)",
            "A. Boss: Hire her.",
        ):
            self.assertIn(line, text)
        self.assertNotIn("\\", text)  # no LaTeX in the text version
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))

    def test_order_and_empty_sections(self):
        resume = {key: RESUME[key] for key in ("basics", "work", "awards")}
        text = generate_text.render(resume, ["recognition", "pagebreak", "education", "summary"])
        self.assertLess(text.index("RECOGNITION & SPEAKING"), text.index("PROFESSIONAL SUMMARY"))
        self.assertNotIn("EDUCATION", text)
        self.assertNotIn("PROFESSIONAL EXPERIENCE", text)  # not in the order


class EveryField(unittest.TestCase):
    """Each field of the JSON Resume schema is printed, in the PDF's LaTeX
    and in the text resume."""
    URL = "https://example.com/a_b/c%20d?x=1&y=2#frag~{z}"
    RESUME = {
        "basics": {**RESUME["basics"], "image": "input/photo.png",
                   "location": {"address": "1 Main St\nApt 2", "postalCode": "62701", "city": "Springfield", "countryCode": "US", "region": "IL"},
                   "profiles": [{"network": "GitHub", "username": "ada", "url": "https://github.com/ada/"},
                                {"network": "Mastodon", "username": "ada", "url": "https://example.social/@ada"},
                                {"network": "Signal", "username": "ada.01"}]},
        "work": [
            {"name": "Acme", "location": "Springfield, IL", "description": "Makers of anvils & rockets_2", "position": "Lead", "url": URL,
             "startDate": "2020-03", "summary": "Led.", "highlights": ["Cut costs."]},
            {"name": "Old Co", "location": "Shelbyville", "description": "A shop", "position": "Intern", "url": "https://old.example.com",
             "startDate": "2001", "endDate": "2003", "summary": "Swept", "highlights": ["Floors", "Windows"], "earlyCareer": True},
        ],
        "volunteer": [{"organization": "Library", "position": "Tutor", "url": "https://library.example.org", "startDate": "2019"}],
        "education": [{"institution": "State U", "url": "https://stateu.example.edu", "area": "Physics", "studyType": "BS", "endDate": "2017"}],
        "awards": [{"title": "Prize", "date": "2024-06", "awarder": "The Academy", "summary": "For a thing."},
                   {"title": "Acme Cup (2021)", "date": "2021", "awarder": "ACME", "summary": "Again."}],
        "certificates": [{"name": "Cert A", "date": "2023-01-15", "url": "https://certs.example.com/a", "issuer": "Body"}],
        "publications": [{"name": "Paper", "publisher": "Journal", "releaseDate": "2021-05", "url": "https://doi.example.org/x_y"}],
        "projects": [{"name": "Tool", "description": "A tool.", "startDate": "2022-01", "endDate": "2023-06", "url": "https://tool.example.com",
                      "roles": ["Author", "Maintainer"], "entity": "Tool Foundation", "type": "application"}],
        "meta": {"canonical": "https://example.com/resume.json", "version": "v1.2.0", "lastModified": "2026-10-01T12:00:00"},
    }

    def setUp(self):
        self.header = generate_header.render(*generate_header.header_fields(self.RESUME["basics"]))
        self.tex = generate_resume.render(self.RESUME, generate_resume.SECTIONS)
        self.text = generate_text.render(self.RESUME, generate_resume.SECTIONS)

    def test_header(self):
        self.assertIn("1 Main St, Apt 2, Springfield, IL 62701, US~~", self.header)
        self.assertIn(r"\includegraphics[height=0.9in]{\detokenize{input/photo.png}}", self.header)
        self.assertIn(r"\href{https://github.com/ada/}{github.com/ada}", self.header)  # the address names the network
        self.assertIn(r"\href{https://example.social/@ada}{Mastodon: example.social/@ada}", self.header)
        self.assertIn("Signal: ada.01", self.header)  # no URL: plain text
        self.assertIn("1 Main St, Apt 2, Springfield, IL 62701, US · ", self.text)
        self.assertIn("github.com/ada · Mastodon: example.social/@ada · Signal: ada.01\n", self.text)

    def test_a_photo_on_the_web_cannot_be_included(self):
        fields, _ = generate_header.header_fields({**self.RESUME["basics"], "image": "https://example.com/me.png"})
        self.assertNotIn("image", fields)
        fields, _ = generate_header.header_fields({**self.RESUME["basics"], "image": "file:///home/me/me.png"})
        self.assertEqual(fields["image"], "/home/me/me.png")

    def test_urls_make_names_links(self):
        link = lambda url, text: "{\\hypersetup{urlcolor=.}\\href{%s}{%s}}" % (url, text)  # noqa: E731
        for expected in (
            link(r"https://example.com/a_b/c\%20d?x=1\&y=2\#frag~\%7Bz\%7D", "Acme"),
            link("https://old.example.com", "Old Co"), link("https://library.example.org", "Library"),
            link("https://stateu.example.edu", "State U"), link("https://certs.example.com/a", "Cert A"),
            link("https://doi.example.org/x_y", "Paper"), link("https://tool.example.com", "Tool"),
        ):
            self.assertIn(expected, self.tex)
        self.assertNotIn("example.com/a_b", self.text)  # the text resume has no links

    def test_the_rest(self):
        for tex, text in (
            (r"{\small\itshape\color{muted}Makers of anvils \& rockets\_2\par}", "Acme, Springfield, IL (Mar 2020 – Present)\nMakers of anvils & rockets_2\nLead"),
            (r"}, Shelbyville (2001--2003), A shop, Swept: Floors; Windows", "Intern, Old Co, Shelbyville (2001–2003), A shop, Swept: Floors; Windows"),
            (r"\entry{Prize, The Academy (Jun 2024)}{For a thing.}", "Prize, The Academy (Jun 2024): For a thing."),
            (r"\entry{Acme Cup (2021)}{Again.}", "Acme Cup (2021): Again."),  # the title says both already
            ("}, Body (2023)", "Cert A, Body (2023)"),
            (r"(Author, Maintainer, Tool Foundation, application, Jan 2022 -- Jun 2023)}}{A tool.}", "Tool (Author, Maintainer, Tool Foundation, application, Jan 2022 – Jun 2023): A tool."),
            (r"Version v1.2.0 $\cdot$ Updated Oct 2026 $\cdot$ \href{https://example.com/resume.json}{example.com/resume.json}",
             "Version v1.2.0 · Updated Oct 2026 · https://example.com/resume.json\n"),
        ):
            self.assertIn(tex, self.tex)
            self.assertIn(text, self.text)

    def test_a_resume_without_them_is_unchanged(self):
        self.assertNotIn("hypersetup", generate_resume.render(RESUME, generate_resume.SECTIONS))
        self.assertNotIn("vfill", generate_resume.render(RESUME, generate_resume.SECTIONS))


class Header(unittest.TestCase):
    def render(self, **basics):
        return generate_header.render(*generate_header.header_fields({**RESUME["basics"], **basics}))

    def test_pdf_properties_come_from_the_resume(self):
        header = self.render(name="Zoë O'Brien & Co_1", label="Data · ML – 100% | Lead")
        self.assertIn(r"pdftitle={Zoë O'Brien \& Co\_1 Resume}", header)
        self.assertIn(r"pdfauthor={Zoë O'Brien \& Co\_1}", header)
        self.assertIn(r"pdfsubject={Data \textperiodcentered{} ML \textendash{} 100\% | Lead}", header)

    def test_missing_field(self):
        with self.assertRaises(SystemExit) as failure:
            self.render(name="")
        self.assertIn("basics.name", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
