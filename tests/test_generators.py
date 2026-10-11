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
