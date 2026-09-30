# Full (non-slim) image: pbr needs git at build time to compute the package version.
FROM python:3.12-bookworm

WORKDIR /app
ADD . /app

RUN pip install .
