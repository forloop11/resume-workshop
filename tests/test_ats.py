import copy
import unittest

from tests import RESUME as SHORT_PHONE

import check_ats
import generate_resume

RESUME = {**SHORT_PHONE, "basics": {**SHORT_PHONE["basics"], "phone": "+1 (217) 555-0100"}}
JOB = """Senior Machine Learning Engineer
We are looking for a machine learning engineer to build machine learning models for anomaly detection.
- Deploy models with Python, PyTorch and CI/CD on AWS
- Experience with anomaly detection and Kubernetes is a plus
"""


class Findings(unittest.TestCase):
    def levels(self, resume, order=generate_resume.SECTIONS):
        return {finding.text: finding.level for finding in check_ats.check(resume, order)}

    def said(self, resume, words, level, order=generate_resume.SECTIONS):
        """Asserts one finding mentions `words`, at `level`."""
        found = [(text, got) for text, got in self.levels(resume, order).items() if words in text]
        self.assertEqual([got for _, got in found], [level], found or f"nothing says {words!r}")

    def test_a_sound_resume(self):
        for words in ("email address is one a parser can read", "full number", "city and a region", "has a work experience section",
                      "has an education section", "has a skills section", "Every job has a start date", "doesn't use “I”"):
            self.said(RESUME, words, "ok")
        self.said(RESUME, "no LinkedIn", "note")
        self.assertNotIn("warn", self.levels(RESUME).values())

    def test_what_it_catches(self):
        resume = copy.deepcopy(RESUME)
        resume["basics"].update(email="ada at example", phone="+1 (xxx) xxx-xxxx", summary="I build things. " * 60)
        resume["basics"]["location"] = {"city": "Springfield"}
        resume["work"][0].pop("startDate")
        resume["work"][0]["highlights"] = ["Responsible for the servers", "We shipped R² models " + "and more " * 40]
        resume["work"][1].pop("summary")
        for words, level in (("doesn't look like one", "warn"), ("10 to 15 digits", "warn"), ("no region", "note"),
                             ("No start date: Lead at Acme", "warn"), ("No bullet points, only a summary: Engineer at Acme", "note"),
                             ("opens with a weak phrase", "warn"), ("use “I”", "note"), ("past about three lines", "note"),
                             ("skim it", "note"), ("² (1×)", "note"), ("Only", "note")):
            self.said(resume, words, level)

    def test_bold_is_not_part_of_the_words(self):
        resume = copy.deepcopy(RESUME)
        resume["work"][0]["highlights"] = ["**Responsible for** the servers"]
        self.said(resume, "opens with a weak phrase", "warn")
        self.assertNotIn("*", " ".join(finding.text for finding in check_ats.check(resume, generate_resume.SECTIONS)))

    def test_sections_left_out(self):
        self.said(RESUME, "no skills section", "warn", order=["summary", "experience", "education"])
        self.said({**RESUME, "education": []}, "no education section", "warn")

    def test_headings_a_parser_may_not_know(self):
        self.said(RESUME, "'Core Competencies' and 'Recognition & Speaking'", "note")
        self.said(RESUME, "Every section heading uses a word parsers recognize", "ok", order=["summary", "experience", "education"])
        # ...which headings of the resume's own put right.
        levels = {finding.text: finding.level for finding in check_ats.check(
            RESUME, generate_resume.SECTIONS, {"competencies": "Technical Skills", "recognition": "Awards & Speaking"})}
        self.assertEqual(levels["Every section heading uses a word parsers recognize."], "ok")
        levels = check_ats.check(RESUME, generate_resume.SECTIONS, {"education": "Schooling"})
        self.assertTrue(any("'Schooling'" in finding.text for finding in levels))


class Keywords(unittest.TestCase):
    def test_terms_of_a_job(self):
        terms = check_ats.job_terms(JOB)
        self.assertEqual(terms[0], "machine learning")  # the most repeated, as a pair
        self.assertIn("anomaly detection", terms)
        for term in ("python", "pytorch", "ci/cd", "aws", "kubernetes", "models"):  # names, and repeated words
            self.assertIn(term, terms)
        for word in ("machine", "learning", "experience", "looking", "plus", "deploy"):  # in a pair, boilerplate, or said once
            self.assertNotIn(word, terms)

    def test_match(self):
        resume = "Built a machine-learning model for detecting anomalies; deployed on AWS with PyTorch and CI/CD."
        match = check_ats.keywords(JOB, resume)
        self.assertEqual(set(match.missing), {"anomaly detection", "kubernetes", "python", "engineer"})
        self.assertEqual(set(match.found), {"machine learning", "models", "pytorch", "ci/cd", "aws"})  # "model" matches "models"

    def test_report(self):
        text = check_ats.report(check_ats.check(RESUME, generate_resume.SECTIONS), check_ats.keywords(JOB, "python"))
        self.assertIn("to note, 0 to fix.", text)
        self.assertIn("note  There is no LinkedIn", text)
        self.assertIn("The resume has 1 of the job description's", text)
        self.assertIn("Missing: machine learning", text)
        self.assertIn("no terms to look for", check_ats.report([], check_ats.keywords("the and of", "python")))


if __name__ == "__main__":
    unittest.main()
