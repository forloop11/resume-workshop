TEXFILE = input/format
OUTPUT = output/resume
DOCKER_IMAGE = resume-builder

.PHONY: build pdf txt header geometry resume rxresume schema validate ats test editor appimage install-appimage uninstall-appimage clean user docker-image docker-build

header: input/resume.json scripts/generate_header.py scripts/jsonresume.py
	python3 scripts/generate_header.py

geometry: input/geometry.yaml scripts/generate_geometry.py
	python3 scripts/generate_geometry.py

resume: input/resume.json input/section_order.yaml scripts/generate_resume.py scripts/jsonresume.py
	python3 scripts/generate_resume.py

# Exports output/rxresume.json, the resume as a Reactive Resume (rxresu.me)
# document, for importing there.
rxresume: input/resume.json input/section_order.yaml input/geometry.yaml input/format.tex scripts/export_rxresume.py scripts/generate_resume.py scripts/generate_header.py scripts/generate_geometry.py scripts/jsonresume.py
	python3 scripts/export_rxresume.py

# Writes output/resume-workshop.json: the JSON Resume schema plus this
# project's extension fields, for editors to check input/resume.json against.
schema: etc/resume-schema.json scripts/generate_schema.py scripts/generate_resume.py
	python3 scripts/generate_schema.py

# Checks input/resume.json against the JSON Resume schema (etc/resume-schema.json)
# and the generator's own rules, and the Reactive Resume export against its
# schema (etc/rxresume-schema.json). Needs jsonschema (pip install -r requirements.txt).
validate: input/resume.json etc/resume-schema.json etc/rxresume-schema.json scripts/validate_resume.py scripts/export_rxresume.py
	python3 scripts/validate_resume.py

# Checks the text resume for what applicant tracking systems trip on, and,
# with a job description, which of its terms the resume has:
#   make ats JOB=job.txt
ats: input/resume.json input/section_order.yaml scripts/check_ats.py scripts/generate_text.py
	python3 scripts/check_ats.py $(JOB)

# The tests in tests/. Those of the editor need its packages
# (pip install -r requirements.txt), and make and pdflatex to compare builds;
# they are skipped without them.
test:
	python3 -B -m unittest discover -s tests -t .

# The desktop editor (editor/, a Qt app). Needs PySide6 and jsonschema
# (pip install -r requirements.txt). It builds resumes itself, with these
# same scripts (editor/build.py), rather than by running make.
editor:
	python3 editor/main.py

# The editor as an AppImage, with its own Python and pip packages:
# dist/Resume_Workshop-x86_64.AppImage. Needs curl and an internet connection
# (see packaging/build-appimage.sh).
APPIMAGE = dist/Resume_Workshop-x86_64.AppImage

$(APPIMAGE): requirements.txt requirements-grammar.txt $(shell find editor scripts packaging -type f -not -path '*/__pycache__/*' 2>/dev/null)
	packaging/build-appimage.sh

appimage: $(APPIMAGE)

# Copies the AppImage to ~/Applications (or $$APPIMAGE_DIR) and adds it to the
# applications menu, opening the resume in this checkout.
install-appimage: $(APPIMAGE)
	packaging/install-appimage.sh

uninstall-appimage:
	packaging/install-appimage.sh --uninstall

# The PDF alone, without the text and Reactive Resume versions. pdflatex
# runs twice: the second run gives the PDF its bookmarks, from the section
# list the first one wrote.
pdf: header geometry resume $(TEXFILE).tex
	mkdir -p output
	pdflatex -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex
	pdflatex -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex

# The plain-text resume alone, written from the same inputs as the PDF.
txt: input/resume.json input/section_order.yaml scripts/generate_text.py scripts/generate_resume.py scripts/generate_header.py scripts/jsonresume.py
	python3 scripts/generate_text.py

build: pdf txt rxresume schema
	rm -f $(OUTPUT).aux $(OUTPUT).fdb_latexmk $(OUTPUT).fls $(OUTPUT).log $(OUTPUT).out $(OUTPUT).synctex.gz

# Copies the build output to a filename derived from input/resume.json's
# `basics.name` field (lowercased, spaces replaced with underscores, everything
# else stripped down to alphanumerics and underscores), e.g.
# "Todd Takala" -> output/todd_takala_resume.pdf.
user: build
	name=$$(python3 -c 'import json; print(json.load(open("input/resume.json"))["basics"]["name"])' | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd 'a-z0-9_'); \
	rm -f "output/$${name}_resume.pdf"; \
	cp $(OUTPUT).pdf "output/$${name}_resume.pdf"

clean:
	rm -f $(OUTPUT).aux $(OUTPUT).fdb_latexmk $(OUTPUT).fls $(OUTPUT).log $(OUTPUT).out $(OUTPUT).synctex.gz interim/header.tex interim/geometry.tex interim/resume_content.tex

# Build the PDF/txt without needing pdflatex/pandoc/python3 installed locally.
docker-image:
	docker build -t $(DOCKER_IMAGE) -f docker/Dockerfile .

docker-build: docker-image
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$$(pwd)":/resume $(DOCKER_IMAGE)

