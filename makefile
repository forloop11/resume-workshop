TEXFILE = input/format
OUTPUT = output/resume
DOCKER_IMAGE = resume-builder

.PHONY: build header geometry resume rxresume schema validate editor clean user docker-image docker-build

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

# The desktop editor (editor/, an Electron app). Needs Node.js/npm; the first
# run installs Electron into editor/node_modules. ELECTRON_RUN_AS_NODE is
# unset because some hosts (e.g. VS Code's extension host) set it, which
# would make Electron run as plain Node instead of opening a window.
editor/node_modules: editor/package.json editor/package-lock.json
	cd editor && npm ci
	touch editor/node_modules

editor: editor/node_modules
	cd editor && env -u ELECTRON_RUN_AS_NODE npm start

build: header geometry resume rxresume schema $(TEXFILE).tex
	mkdir -p output
	pdflatex -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex
	pandoc --wrap=none -f latex -t plain $(TEXFILE).tex -o $(OUTPUT).txt
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

