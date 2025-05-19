FROM ubuntu:jammy AS base

ARG PYTHON_VERSION=3.11

WORKDIR /app
ADD . /app

RUN pip install .
