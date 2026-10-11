#!/usr/bin/env python3
"""Check the text resume for what applicant tracking systems (ATS) trip on.

An ATS reads a resume as plain text and files what it finds: who you are,
where you worked and when, and which of a job's keywords you mention. This
looks at the resume as output/resume.txt has it (generate_text.py) for the
things that commonly go wrong there -- contact details it can't find,
sections it won't recognize, jobs without dates, characters it may drop,
bullets that say little -- and, given a job description, lists which of the
job's terms the resume has and lacks:

    python3 scripts/check_ats.py [job-description.txt]      (make ats)

These are rules of thumb, not any one system's scoring: there is no standard
one. Each finding is "ok", a "note" (worth knowing), or a "warn" (worth
fixing).

Standard library only, like the generators.
"""
import re
import sys
from collections import Counter, namedtuple

from generate_resume import ORDER_SRC, PAGEBREAK, SECTIONS, parse_headings, parse_section_order, section_entries, validate
from generate_text import SECTION_TEXT, render
from jsonresume import SRC, load, plain

Finding = namedtuple("Finding", "level text")  # level: "ok", "note", or "warn"
Match = namedtuple("Match", "found missing")  # a job's terms the resume has and lacks, the job's most used first

# What a parser looks for in a heading to tell what the section is.
HEADING_WORDS = {
    "summary": ["summary", "profile", "objective"], "competencies": ["skills"], "experience": ["experience", "employment"],
    "education": ["education"], "certifications": ["certification", "license"], "recognition": ["award", "honor"],
    "publications": ["publication"], "projects": ["project"], "languages": ["language"], "volunteer": ["volunteer"],
    "references": ["reference"],
}
# The sections a parser expects every resume to have.
CORE = {"experience": "a work experience", "education": "an education", "competencies": "a skills"}
WEAK_OPENINGS = ("responsible for", "duties included", "worked on", "helped", "assisted with", "tasked with", "in charge of")
PRONOUNS = re.compile(r"\b(I|[Mm]e|[Mm]y|[Mm]ine|[Ww]e|[Oo]ur)\b")
LONG_BULLET = 300  # characters: about three lines of the PDF
# Characters every parser reads: ASCII, and the punctuation word processors type.
SAFE = set("’‘“”–—·")
MAX_TERMS = 40
# Words that say nothing about a job: English's most common, and job postings' own.
STOPWORDS = set("""
a about above across after all also an and any are as at be been being both but by can could do does each for from has have having
how if in into is it its may more most must no not of on one or other our out over own per should so some such than that the their
them then there these they this those through to under up us was we were what when where which while who will with within would
you your able ability applicant applicants apply based benefits candidate candidates company day days including include includes
etc experience experienced job join looking opportunity opportunities plus position preferred qualifications required requirement
requirements responsibilities responsibility role roles strong team teams work working years year new well high highly level
need needs help using use used make makes ensure provide provides related relevant across multiple skill skills
""".split())


def bullets(data):
    """Every highlight in the resume's experience, volunteer work, and projects."""
    entries = data.get("work", []) + data.get("volunteer", []) + data.get("projects", [])
    return [text for entry in entries for text in entry.get("highlights") or []]


def check(data, section_order, headings=None):
    """The findings for a resume and its section order, in reading order;
    `headings` as generate_resume.render() takes it."""
    data = plain(data)  # a parser gets the words, not the bold
    basics = data.get("basics", {})
    heading = lambda section: (headings or {}).get(section) or SECTION_TEXT[section][0]  # noqa: E731
    printed = [section for section in section_order if section != PAGEBREAK and (section == "summary" or section_entries(data, section))]
    found = []

    def add(passed, good, bad, level="warn"):
        found.append(Finding("ok", good) if passed else Finding(level, bad))

    # Contact details, which a parser reads from the first lines.
    email = basics.get("email", "")
    add(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email), f"The email address is one a parser can read ({email}).",
        f"The email address {email!r} doesn't look like one." if email else "There is no email address.")
    digits = re.sub(r"\D", "", basics.get("phone", ""))
    add(10 <= len(digits) <= 15, "The phone number has the digits of a full number.",
        f"The phone number {basics.get('phone', '')!r} doesn't have the 10 to 15 digits of a full number.")
    location = basics.get("location") or {}
    add(location.get("city") and location.get("region"), "The location has a city and a region.",
        "The location has no region (state): many systems filter candidates by it.", "note")
    profiles = [basics.get("url", "")] + [profile.get("url", "") for profile in basics.get("profiles", [])]
    add(any("linkedin.com" in url for url in profiles), "There is a LinkedIn profile link.",
        "There is no LinkedIn profile link, which recruiters' systems often look for.", "note")

    # Sections a parser can find and name.
    for section, name in CORE.items():
        add(section in printed, f"The resume has {name} section.",
            f"The resume has no {name.split(' ', 1)[1]} section: add entries for it, and list it in the section order.")
    unusual = [heading(section) for section in printed
               if section in HEADING_WORDS and not any(word in heading(section).lower() for word in HEADING_WORDS[section])]
    if unusual:
        found.append(Finding("note", f"The heading{'s' if len(unusual) > 1 else ''} {' and '.join(repr(h) for h in unusual)} "
                                     f"{'are' if len(unusual) > 1 else 'is'} not the usual name for "
                                     f"{'those sections' if len(unusual) > 1 else 'that section'}; a parser that goes by headings may file "
                                     "the content under something else. A section's heading can be changed in its card "
                                     "in the editor, or in section_order.yaml."))
    else:
        found.append(Finding("ok", "Every section heading uses a word parsers recognize."))

    # Jobs with the dates and detail a parser builds a work history from.
    jobs = [entry for entry in data.get("work", []) if not entry.get("earlyCareer")]
    undated = [f"{entry.get('position', '?')} at {entry.get('name', '?')}" for entry in jobs if not entry.get("startDate")]
    add(not undated, "Every job has a start date.", f"No start date: {'; '.join(undated)}. A parser can't place a job in time without one.")
    bare = [f"{entry.get('position', '?')} at {entry.get('name', '?')}" for entry in jobs if not entry.get("highlights")]
    add(not bare, "Every job has bullet points.", f"No bullet points, only a summary: {'; '.join(bare)}.", "note")
    if "summary" in printed:
        words = len(basics.get("summary", "").split())
        add(words <= 110, f"The summary is {words} words, short enough to be read.",
            f"The summary is {words} words; past about 100, readers and parsers alike skim it.", "note")

    # Bullets that say what was done, and how much.
    lines = bullets(data)
    if lines:
        numbered = sum(bool(re.search(r"\d", line)) for line in lines)
        share = round(100 * numbered / len(lines))
        add(share >= 40, f"{share}% of the {len(lines)} bullet points include a number.",
            f"Only {share}% of the {len(lines)} bullet points include a number; results with figures rank and read better.", "note")
        weak = [line for line in lines if line.lower().startswith(WEAK_OPENINGS)]
        add(not weak, "No bullet point opens with a weak phrase such as “Responsible for”.",
            f"{len(weak)} bullet point{'s open' if len(weak) > 1 else ' opens'} with a weak phrase; start with what you did instead: "
            + "; ".join(f"“{shorten(line)}”" for line in weak[:3]))
        personal = [line for line in lines + [basics.get("summary", "")] if PRONOUNS.search(line)]
        add(not personal, "The text doesn't use “I”, “my”, or “we”.",
            f"{len(personal)} line{'s use' if len(personal) > 1 else ' uses'} “I”, “my”, or “we”, which resumes leave out: "
            + "; ".join(f"“{shorten(line)}”" for line in personal[:3]), "note")
        long = [line for line in lines if len(line) > LONG_BULLET]
        add(not long, "No bullet point runs past about three lines.",
            f"{len(long)} bullet point{'s run' if len(long) > 1 else ' runs'} past about three lines; consider splitting: "
            + "; ".join(f"“{shorten(line)}”" for line in long[:3]), "note")
    keywords = [keyword for skill in data.get("skills", []) for keyword in skill.get("keywords", [])]
    if "competencies" in printed:
        add(len(keywords) >= 10, f"The skills section lists {len(keywords)} skills for a keyword search to find.",
            f"The skills section lists only {len(keywords)} skills; it is where keyword searches look first.", "note")

    # The text itself.
    try:
        text = render(data, section_order, headings)
    except SystemExit as error:
        return found + [Finding("warn", f"The text resume can't be written: {error}")]
    words = len(text.split())
    add(350 <= words <= 1100, f"The resume is {words} words, a usual length.",
        f"The resume is {words} words; most run between about 400 and 1,000.", "note")
    odd = Counter(ch for ch in text if ord(ch) > 126 and ch not in SAFE)
    if odd:
        found.append(Finding("note", "Some older parsers drop or garble these characters: "
                                     + ", ".join(f"{ch} ({count}×)" for ch, count in odd.most_common(8)) + "."))
    else:
        found.append(Finding("ok", "The text has no characters a parser is likely to garble."))
    return found


def shorten(line, length=60):
    return line if len(line) <= length else line[:length].rsplit(" ", 1)[0] + "…"


def stem(word):
    """A word cut down so its forms match: "pipelines", "pipeline"; "forecasting", "forecast"."""
    for ending in ("ing", "ed", "es", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def words_of(text):
    """The words of some text, lowercased, with what joins a technical term
    kept in it ("c++", "ci/cd", "node.js"). A hyphen separates words, so
    "machine-learning" and "machine learning" are the same two."""
    return [word.strip("./") for word in re.findall(r"[a-z0-9][a-z0-9+#./]*", text.lower())]


def named(job):
    """The words a job description writes as names: with a capital inside a
    sentence or after the first letter ("Python", "PyTorch", "AWS"), or
    with a digit or symbol ("c++", "ci/cd"). They are mostly the tools and
    fields it asks for, and count even if it mentions them once."""
    names = set()
    for line in job.splitlines():
        for index, word in enumerate(re.findall(r"[A-Za-z0-9][A-Za-z0-9+#./]*", line)):
            plain = word.strip("./")
            capital_inside = any(ch.isupper() for ch in plain[1:])
            if capital_inside or re.search(r"[0-9+#/]", plain) and re.search(r"[A-Za-z]", plain) or index and plain[:1].isupper():
                names.add(plain.lower())
    return names


def job_terms(job):
    """What a job description asks for: the names it mentions (see
    named()), the other words it repeats, and the pairs of words it repeats
    ("machine learning"), most used first."""
    words = words_of(job)
    keep = lambda word: len(word) > 1 and word not in STOPWORDS and not word.isdigit()  # noqa: E731
    singles = Counter(word for word in words if keep(word))
    pairs = Counter(f"{first} {second}" for first, second in zip(words, words[1:]) if keep(first) and keep(second))
    # A repeated pair is a term, unless a more repeated one has claimed one
    # of its words: with "machine learning", not "learning models" as well.
    repeated, claimed = {}, set()
    for pair, count in pairs.most_common():
        if count >= 2 and not claimed & set(pair.split()):
            repeated[pair] = count
            claimed |= set(pair.split())
    names = named(job)
    terms = {word: count for word, count in singles.items() if (count >= 2 or word in names) and word not in claimed}
    terms.update(repeated)
    order = {word: index for index, word in reversed(list(enumerate(words)))}  # where each first appears
    ranked = sorted(terms, key=lambda term: (-terms[term], order[term.split()[0]]))
    return ranked[:MAX_TERMS]


def keywords(job, resume_text):
    """Which of a job description's terms the resume's text has."""
    have = {stem(word) for word in words_of(resume_text)}
    joined = " ".join(stem(word) for word in words_of(resume_text))
    found, missing = [], []
    for term in job_terms(job):
        stems = [stem(word) for word in term.split()]
        here = " ".join(stems) in joined if len(stems) > 1 else stems[0] in have
        (found if here else missing).append(term)
    return Match(found, missing)


def report(findings, match=None):
    """The findings, and a job's keywords, as text to print."""
    marks = {"ok": "ok  ", "note": "note", "warn": "WARN"}
    lines = [f"{marks[finding.level]}  {finding.text}" for finding in findings]
    counts = Counter(finding.level for finding in findings)
    lines += ["", f"{counts['ok']} ok, {counts['note']} to note, {counts['warn']} to fix."]
    if match:
        total = len(match.found) + len(match.missing)
        if not total:
            lines += ["", "The job description has no terms to look for."]
        else:
            lines += ["", f"The resume has {len(match.found)} of the job description's {total} main terms."]
            if match.missing:
                lines += [f"  Missing: {', '.join(match.missing)}"]
            if match.found:
                lines += [f"  Found:   {', '.join(match.found)}"]
    return "\n".join(lines)


def main():
    data = load()
    section_order = parse_section_order(ORDER_SRC)
    validate(data, section_order)
    match = None
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as job:
            match = keywords(job.read(), render(data, section_order, parse_headings(ORDER_SRC)))
    print(f"ATS check of {SRC}:\n")
    print(report(check(data, section_order, parse_headings(ORDER_SRC)), match))


assert set(HEADING_WORDS) <= set(SECTIONS)

if __name__ == "__main__":
    main()
