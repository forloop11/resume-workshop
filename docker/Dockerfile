# Reproducible build environment for `make docker-build`.
# Base image ships pdflatex + pandoc on TeX Live's "basic" scheme; the extra
# tlmgr installs below add the packages this resume's .tex file needs
# (titlesec/enumitem/ragged2e for layout, helvetic for the Type1 Helvetica
# fonts) that aren't in that base scheme.
FROM pandoc/latex:3.10-debian

RUN tlmgr update --self \
    && tlmgr install titlesec enumitem ragged2e helvetic \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /resume
RUN mkdir -p interim
ENTRYPOINT ["make"]
CMD ["build"]
