TEXFILE = input/format
OUTPUT = output/resume
DOCKER_IMAGE = resume-builder

.PHONY: build pdf txt header geometry resume rxresume schema validate ats theme test editor app app-web app-test app-window-test appimage install-appimage uninstall-appimage clean user docker-image docker-build

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

# The tests in tests/. Those of the editor's backend need jsonschema
# (pip install -r requirements.txt), and make and pdflatex to compare builds;
# they are skipped without them. `make app-test` tests the editor's window.
test:
	python3 -B -m unittest discover -s tests -t .

# The desktop editor (app/, a Tauri app with a web front end, and these same
# scripts behind it): see app/README.md. `make editor` runs it, which needs
# Node, Rust with Cargo, the system packages Tauri lists, and jsonschema
# (pip install -r requirements.txt). `make app-web` runs the same window in
# a web browser without Rust, and `make app-test` drives it in a headless
# Chrome.
editor app: app/node_modules
	cd app && npm run tauri dev

app-web: app/node_modules
	cd app && npm run build && python3 backend/devserver.py

app-test: app/node_modules
	cd app && npm run build && npm run smoke

# The app itself, built and driven through WebDriver: its window shows while
# this runs. Needs tauri-driver (cargo install tauri-driver --locked) and the
# system's WebKitWebDriver.
app-window-test: app/node_modules
	cd app && npm run tauri build -- --no-bundle && npm run window

app/node_modules: app/package.json
	cd app && npm install

# The editor as an AppImage, with its own Python, Tectonic, and the TeX
# packages the layout loads: dist/Resume_Workshop-x86_64.AppImage. Needs
# what `make editor` does, curl, and an internet connection (see
# packaging/build_app.py).
APPIMAGE = dist/Resume_Workshop-x86_64.AppImage

# Everything in app/ but what is installed or built there.
$(APPIMAGE): requirements.txt requirements-grammar.txt $(shell find scripts packaging app -type f -not -path '*/__pycache__/*' -not -path 'app/node_modules/*' -not -path 'app/dist/*' -not -path 'app/src-tauri/target/*' -not -path 'app/src-tauri/gen/*' 2>/dev/null | sed 's/ /\\ /g')
	python3 packaging/build_app.py

appimage: $(APPIMAGE)

# Copies the AppImage to ~/Applications (or $$APPIMAGE_DIR) and adds it to the
# applications menu, opening the resume in this checkout.
install-appimage: $(APPIMAGE)
	packaging/install-appimage.sh

uninstall-appimage:
	packaging/install-appimage.sh --uninstall

# The PDF alone, without the text and Reactive Resume versions. pdflatex
# runs twice: the second run gives the PDF its bookmarks, from the section
# list the first one wrote. `make pdf LATEX=tectonic` (or `make build
# LATEX=tectonic`) builds it with Tectonic instead, which reruns itself.
LATEX = pdflatex

pdf: header geometry resume $(TEXFILE).tex
	mkdir -p output
ifeq ($(findstring tectonic,$(notdir $(LATEX))),tectonic)
	$(LATEX) -Z search-path=. --outdir $(dir $(OUTPUT)) $(TEXFILE).tex
	mv $(dir $(OUTPUT))$(notdir $(TEXFILE)).pdf $(OUTPUT).pdf
else
	$(LATEX) -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex
	$(LATEX) -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex
endif

# Makes one of the resume themes in themes/ the layout, input/format.tex,
# in place of the one there: `make theme THEME=traditional`. Without THEME,
# lists them.
theme:
ifdef THEME
	cp themes/$(THEME).tex $(TEXFILE).tex
else
	@echo "Resume themes (make theme THEME=<name>):"; for theme in themes/*.tex; do echo "  $$(basename $$theme .tex)"; done
endif

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

