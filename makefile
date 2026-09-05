TEXFILE = input/format
OUTPUT = output/resume
DOCKER_IMAGE = resume-builder

.PHONY: build header geometry resume editor clean user docker-image docker-build docker-editor

header: input/header.yaml scripts/generate_header.py
	python3 scripts/generate_header.py

geometry: input/geometry.yaml scripts/generate_geometry.py
	python3 scripts/generate_geometry.py

resume: input/resume.json input/section_order.yaml scripts/generate_resume.py
	python3 scripts/generate_resume.py

editor: scripts/editor.py
	python3 scripts/editor.py

build: header geometry resume $(TEXFILE).tex
	mkdir -p output
	pdflatex -jobname=$(OUTPUT) -interaction=nonstopmode $(TEXFILE).tex
	pandoc --wrap=none -f latex -t plain $(TEXFILE).tex -o $(OUTPUT).txt
	rm -f $(OUTPUT).aux $(OUTPUT).fdb_latexmk $(OUTPUT).fls $(OUTPUT).log $(OUTPUT).out $(OUTPUT).synctex.gz

# Copies the build output to a filename derived from input/header.yaml's
# `name` field (lowercased, spaces replaced with underscores, everything
# else stripped down to alphanumerics and underscores), e.g.
# "Todd Takala" -> output/todd_takala_resume.pdf.
user: build
	name=$$(sed -n 's/^name: *//p' input/header.yaml | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd 'a-z0-9_'); \
	rm -f "output/$${name}_resume.pdf"; \
	cp $(OUTPUT).pdf "output/$${name}_resume.pdf"

clean:
	rm -f $(OUTPUT).aux $(OUTPUT).fdb_latexmk $(OUTPUT).fls $(OUTPUT).log $(OUTPUT).out $(OUTPUT).synctex.gz interim/header.tex interim/geometry.tex interim/resume_content.tex

# Build the PDF/txt without needing pdflatex/pandoc/python3 installed locally.
docker-image:
	docker build -t $(DOCKER_IMAGE) -f docker/Dockerfile .

docker-build: docker-image
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$$(pwd)":/resume $(DOCKER_IMAGE)

# Launch the browser editor without needing python3 installed locally.
# --network host so the container's server on RESUME_EDITOR_PORT (default 8765)
# is reachable at http://127.0.0.1:8765/ from the host (Linux only).
docker-editor: docker-image
	docker run --rm -it -u "$$(id -u):$$(id -g)" -v "$$(pwd)":/resume --network host $(DOCKER_IMAGE) editor

